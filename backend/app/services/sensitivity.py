"""Sensitivity sweep and requirement derivation — Phase 18."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.concept import FactoryConceptDraft, SourcedFloat, ValueSource
from app.services.concept_validation import concept_to_factory
from app.services.simulation import run_simulation

# Bound on how many simulations a single threshold search may run.
MAX_SEARCH_RUNS = 24

# The confirmation sweep at the end of a threshold search probes four values.
_MONOTONICITY_SWEEP_RUNS = 4

THRESHOLD_TOLERANCE_SECONDS = 0.1


class SweepPoint(BaseModel):
    """One parameter value and what the simulator actually produced for it."""

    model_config = {"frozen": True}

    value: float
    unit: str
    completed_units: float
    target_units: float
    meets_target: bool
    bottleneck_machine_id: str

    @property
    def gap_units(self) -> float:
        return max(0.0, self.target_units - self.completed_units)


class SensitivityResult(BaseModel):
    """The sweep, plus what can honestly be concluded from it."""

    model_config = {"frozen": True}

    stage_id: str
    stage_name: str
    parameter: str = "cycle_time"
    unit: str = "s"
    points: list[SweepPoint] = Field(default_factory=list)
    # How many simulator runs this cost.
    simulations_run: int = 0
    # False when throughput does not move consistently with the parameter.
    monotonic: bool = True

    @property
    def any_meets_target(self) -> bool:
        return any(p.meets_target for p in self.points)

    @property
    def all_meet_target(self) -> bool:
        return bool(self.points) and all(p.meets_target for p in self.points)

    def summary(self) -> str:
        if self.all_meet_target:
            return "The target is met across the whole estimated range."
        if not self.any_meets_target:
            return "The target is missed across the whole estimated range."
        return "The target is met at part of the estimated range only."


class DerivedRequirement(BaseModel):
    """What the parameter must achieve for the concept to meet its target."""

    model_config = {"frozen": True}

    stage_id: str
    stage_name: str
    parameter: str = "cycle_time"
    unit: str = "s"
    threshold: float | None = None
    # "at most" for cycle time — lower is better.
    direction: str = "at most"
    target_units: float = 0.0
    simulations_run: int = 0
    monotonic: bool = True
    reason: str = ""

    def statement(self) -> str:
        """One sentence an engineer can act on."""
        if self.threshold is None:
            return self.reason
        return (
            f"To achieve {self.target_units:,.0f} units/day with this configuration, "
            f"{self.stage_name} must operate at {self.threshold:.1f} {self.unit}/unit "
            f"or faster."
        )

    def as_sourced(self) -> SourcedFloat:
        """The threshold as a provenance-carrying value."""
        if self.threshold is None:
            return SourcedFloat.unknown()
        return SourcedFloat.of(
            self.threshold,
            ValueSource.CALCULATED,
            f"Derived from {self.simulations_run} simulations against a target of "
            f"{self.target_units:,.0f} units/day",
        )


# Running one point

def _with_cycle_time(draft: FactoryConceptDraft, stage_id: str, seconds: float) -> FactoryConceptDraft:
    """The concept, identical except for one stage's cycle time."""
    stages = [
        stage.model_copy(
            update={
                "cycle_time": SourcedFloat.of(
                    seconds, ValueSource.CALCULATED, f"Sensitivity sweep point: {seconds:g} s"
                )
            }
        )
        if stage.id == stage_id
        else stage
        for stage in draft.stages
    ]
    return draft.model_copy(update={"stages": stages})


def _simulate_with(draft: FactoryConceptDraft, stage_id: str, seconds: float) -> SweepPoint:
    """One sweep point, through the product's own conversion and simulator."""
    factory, product_id = concept_to_factory(_with_cycle_time(draft, stage_id, seconds))
    result = run_simulation(factory, product_id)
    return SweepPoint(
        value=seconds,
        unit="s",
        completed_units=float(result.completed_units),
        target_units=float(result.target_units),
        meets_target=result.completed_units >= result.target_units,
        bottleneck_machine_id=result.system.bottleneck_machine_id,
    )


# The sweep

def sweep_cycle_time(
    draft: FactoryConceptDraft,
    stage_id: str,
    values: list[float],
) -> SensitivityResult:
    """Run the simulator once per value and report what changed."""
    stage = next((s for s in draft.stages if s.id == stage_id), None)
    if stage is None:
        raise ValueError(f"The concept has no stage '{stage_id}'.")

    ordered: list[float] = []
    for value in sorted(values):
        if value > 0 and not any(abs(value - kept) < 1e-9 for kept in ordered):
            ordered.append(value)

    points = [_simulate_with(draft, stage_id, value) for value in ordered]

    return SensitivityResult(
        stage_id=stage_id,
        stage_name=stage.name,
        points=points,
        simulations_run=len(points),
        monotonic=_is_non_increasing([p.completed_units for p in points]),
    )


def _is_non_increasing(values: list[float], tolerance: float = 1e-6) -> bool:
    """Whether throughput never rises as cycle time rises."""
    return all(later <= earlier + tolerance for earlier, later in zip(values, values[1:]))


# Requirement derivation

def _station_name(draft: FactoryConceptDraft, machine_id: str | None) -> str:
    """The station's own name, not its internal identifier."""
    if not machine_id:
        return "not identified"
    stage = next((s for s in draft.stages if s.id == machine_id), None)
    return stage.name if stage else machine_id


def derive_cycle_time_requirement(
    draft: FactoryConceptDraft,
    stage_id: str,
    *,
    fastest: float,
    slowest: float,
) -> DerivedRequirement:
    """The slowest cycle time at which the concept still meets its target."""
    stage = next((s for s in draft.stages if s.id == stage_id), None)
    if stage is None:
        raise ValueError(f"The concept has no stage '{stage_id}'.")

    runs = 0
    fast_point = _simulate_with(draft, stage_id, fastest)
    slow_point = _simulate_with(draft, stage_id, slowest)
    runs += 2

    common = dict(
        stage_id=stage_id,
        stage_name=stage.name,
        target_units=fast_point.target_units,
        simulations_run=runs,
    )

    if not fast_point.meets_target:
        return DerivedRequirement(
            **common,
            threshold=None,
            reason=(
                f"Even at {fastest:g} s the concept reaches only "
                f"{fast_point.completed_units:,.0f} of {fast_point.target_units:,.0f} units/day, so "
                f"{stage.name} is not what is holding the target back. The limiting station is "
                f"{_station_name(draft, fast_point.bottleneck_machine_id)}."
            ),
        )

    if slow_point.meets_target:
        return DerivedRequirement(
            **common,
            threshold=None,
            reason=(
                f"The target is met even at {slowest:g} s, so within the range examined "
                f"{stage.name}'s cycle time does not constrain the outcome."
            ),
        )

    # Bisect the pass/fail boundary. `lo` always passes, `hi` always fails.
    lo, hi = fastest, slowest
    # The cap covers the WHOLE search, not just this loop: the two bracket
    # probes above and the monotonicity sweep below are simulations too, and
    # a documented bound that the reported count can exceed is not a bound.
    budget = MAX_SEARCH_RUNS - _MONOTONICITY_SWEEP_RUNS
    while hi - lo > THRESHOLD_TOLERANCE_SECONDS and runs < budget:
        mid = (lo + hi) / 2.0
        point = _simulate_with(draft, stage_id, mid)
        runs += 1
        if point.meets_target:
            lo = mid
        else:
            hi = mid

    # Confirm the response really is monotonic across the bracket; a
    # threshold quoted from a non-monotonic response would be misleading.
    check = sweep_cycle_time(draft, stage_id, [fastest, lo, hi, slowest])
    runs += check.simulations_run
    if not check.monotonic:
        return DerivedRequirement(
            **{**common, "simulations_run": runs},
            threshold=None,
            monotonic=False,
            reason=(
                "Throughput does not fall consistently as this cycle time rises, so a single "
                "threshold would misrepresent the result. The sweep points are reported instead."
            ),
        )

    return DerivedRequirement(
        **{**common, "simulations_run": runs},
        threshold=lo,
        reason=(
            f"Found by bisection over {runs} simulations; {lo:.1f} s meets the target and "
            f"{hi:.1f} s does not."
        ),
    )
