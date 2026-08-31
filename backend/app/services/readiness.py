"""Concept readiness — Phase 18."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.concept import FactoryConceptDraft, SourcedFloat, SourcedInt, ValueSource
from app.services.concept_validation import concept_gaps, required_gaps


class ProvenanceCounts(BaseModel):
    """How many of the concept's values came from where."""

    model_config = {"frozen": True}

    customer_facts: int = 0
    manufacturer_facts: int = 0
    engineering_estimates: int = 0
    example_data: int = 0
    derived: int = 0
    planning_defaults: int = 0
    unknown: int = 0
    # Typed by the engineer using Fabrivium, including any override of an estimate.
    engineer_decisions: int = 0
    documents: int = 0
    # Observed on a real line. The only category that is not a prediction.
    measured: int = 0
    # From a named external catalog or price list.
    external_data: int = 0
    # Produced by a Fabrivium simulation run.
    simulated: int = 0

    @property
    def total(self) -> int:
        """Every value counted exactly once. See the class note."""
        return (
            self.customer_facts
            + self.manufacturer_facts
            + self.engineering_estimates
            + self.example_data
            + self.derived
            + self.planning_defaults
            + self.unknown
            + self.engineer_decisions
            + self.documents
            + self.measured
            + self.external_data
            + self.simulated
        )


class ConceptReadiness(BaseModel):
    """What the concept holds, and what still blocks it."""

    model_config = {"frozen": True}

    counts: ProvenanceCounts
    simulation_ready: bool
    # Critical unknowns — the ones that actually block simulation.
    unknown_critical: int = 0
    # Unknowns that never block: price, budget, floor size.
    unknown_commercial: int = 0
    # Human-readable labels of what is still required, in gap order.
    missing: list[str] = Field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "SIMULATION READY" if self.simulation_ready else "NOT YET SIMULATION READY"


# Gap keys that are commercial or spatial rather than physical.
_COMMERCIAL_SUFFIXES = ("purchase_cost", "budget", "floor_dimensions")


def _tally(values: list[SourcedFloat | SourcedInt]) -> ProvenanceCounts:
    buckets = {source: 0 for source in ValueSource}
    for value in values:
        # An unknown is counted as unknown regardless of what its source
        # field claims: value-is-None is the authoritative signal, and the
        # two are meant to travel together.
        buckets[ValueSource.UNKNOWN if value.value is None else value.source] += 1

    return ProvenanceCounts(
        customer_facts=buckets[ValueSource.CUSTOMER],
        manufacturer_facts=buckets[ValueSource.MANUFACTURER],
        engineering_estimates=buckets[ValueSource.ENGINEERING_ESTIMATE],
        example_data=buckets[ValueSource.EXAMPLE_DATA],
        derived=buckets[ValueSource.CALCULATED],
        planning_defaults=buckets[ValueSource.CATALOG_DEFAULT],
        unknown=buckets[ValueSource.UNKNOWN],
        engineer_decisions=buckets[ValueSource.ENGINEER],
        documents=buckets[ValueSource.DOCUMENT],
        measured=buckets[ValueSource.MEASURED],
        external_data=buckets[ValueSource.EXTERNAL_DATA],
        simulated=buckets[ValueSource.SIMULATED],
    )


def _all_values(draft: FactoryConceptDraft) -> list[SourcedFloat | SourcedInt]:
    values: list[SourcedFloat | SourcedInt] = [
        draft.production_target,
        draft.shifts_per_day,
        draft.hours_per_shift,
        draft.operators_available,
        draft.floor_width,
        draft.floor_length,
        draft.budget,
    ]
    for stage in draft.stages:
        values.extend(
            [stage.cycle_time, stage.capacity, stage.operators_required, stage.width, stage.length, stage.purchase_cost]
        )
    for buffer in draft.buffers:
        values.append(buffer.capacity)
    return values


def assess_readiness(draft: FactoryConceptDraft) -> ConceptReadiness:
    """Count what the concept is made of, and say whether it can run."""
    blocking = required_gaps(draft)
    all_gaps = concept_gaps(draft)

    commercial = sum(1 for gap in all_gaps if gap.key.endswith(_COMMERCIAL_SUFFIXES))

    return ConceptReadiness(
        counts=_tally(_all_values(draft)),
        simulation_ready=not blocking,
        unknown_critical=len(blocking),
        unknown_commercial=commercial,
        missing=[gap.label for gap in blocking],
    )
