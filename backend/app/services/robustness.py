"""Decision robustness — if this estimate is wrong, does the decision change?"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.concept import FactoryConceptDraft
from app.services.sensitivity import SweepPoint, sweep_cycle_time

# Values probed across the range, endpoints included.
_PROBES = 5


class Robustness(str, Enum):
    # The decision holds across the whole plausible range.
    ROBUST = "ROBUST"
    # The decision changes inside the range. The flip point is reported.
    SENSITIVE = "SENSITIVE"
    #: Nothing in the range reaches the target, so this parameter is not
    #: what stands between the concept and its goal.
    NOT_ACHIEVABLE = "NOT_ACHIEVABLE"
    # The range is too wide to support a recommendation either way.
    CRITICAL_UNKNOWN = "CRITICAL_UNKNOWN"


#: A range this wide relative to its own working value means the estimate is
#: not yet engineering information. Two thirds is deliberately generous: the
#: point is to catch "we really have no idea", not to police normal
#: estimating uncertainty.
_UNUSABLE_SPREAD = 0.66


@dataclass(frozen=True)
class RobustnessResult:
    """Whether an estimate's uncertainty changes the engineering decision."""

    stage_id: str
    stage_name: str
    parameter: str
    unit: str
    low: float
    high: float
    working: float
    verdict: Robustness
    points: list[SweepPoint] = field(default_factory=list)
    simulations_run: int = 0
    # The value at which the outcome flips, when there is one.
    flips_at: float | None = None
    # One sentence an engineer can act on.
    statement: str = ""

    @property
    def spread_fraction(self) -> float:
        if not self.working:
            return 0.0
        return (self.high - self.low) / self.working


def _probe_values(low: float, high: float, count: int = _PROBES) -> list[float]:
    if count < 2 or high <= low:
        return [low]
    step = (high - low) / (count - 1)
    return [low + step * index for index in range(count)]


def assess_robustness(
    draft: FactoryConceptDraft,
    stage_id: str,
    *,
    low: float,
    high: float,
    working: float,
) -> RobustnessResult:
    """Run the concept across an estimate's plausible range and judge it."""
    if high < low:
        raise ValueError("An estimate's upper bound cannot be below its lower bound.")

    stage = draft.stage_by_id(stage_id)
    if stage is None:
        raise ValueError(f"The concept has no stage '{stage_id}'.")

    values = _probe_values(low, high)
    sweep = sweep_cycle_time(draft, stage_id, values)
    points = sweep.points

    meets = [p for p in points if p.meets_target]
    misses = [p for p in points if not p.meets_target]

    common = {
        "stage_id": stage_id,
        "stage_name": stage.name,
        "parameter": "cycle_time",
        "unit": "s",
        "low": low,
        "high": high,
        "working": working,
        "points": points,
        "simulations_run": sweep.simulations_run,
    }

    if not meets:
        return RobustnessResult(
            **common,
            verdict=Robustness.NOT_ACHIEVABLE,
            statement=(
                f"The target is not reached anywhere in the estimated range "
                f"({low:g}–{high:g} s). Improving this estimate will not change the outcome — "
                f"the constraint is elsewhere."
            ),
        )

    if not misses:
        return RobustnessResult(
            **common,
            verdict=Robustness.ROBUST,
            statement=(
                f"The target is reached across the whole estimated range "
                f"({low:g}–{high:g} s), so the decision does not depend on this estimate being "
                f"right."
            ),
        )

    # The outcome flips somewhere inside the range.
    flip = max(p.value for p in meets)
    first_miss = min(p.value for p in misses)

    spread = (high - low) / working if working else 0.0
    if spread > _UNUSABLE_SPREAD:
        return RobustnessResult(
            **common,
            verdict=Robustness.CRITICAL_UNKNOWN,
            flips_at=flip,
            statement=(
                f"The estimate spans {low:g}–{high:g} s around a working value of {working:g} s, "
                f"and the target is reached at the fast end but missed at the slow end. The range "
                f"is too wide to recommend anything on: this value needs measuring before the "
                f"concept can be trusted."
            ),
        )

    return RobustnessResult(
        **common,
        verdict=Robustness.SENSITIVE,
        flips_at=flip,
        statement=(
            f"The decision changes inside the estimated range: the target is reached at "
            f"{flip:g} s but missed by {first_miss:g} s. {stage.name} has to hold at or below "
            f"about {flip:g} s, so this is the number to confirm before committing."
        ),
    )
