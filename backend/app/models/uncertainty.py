"""Uncertainty representation for concept engineering — Phase 18."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.concept import SourcedFloat, ValueSource


class Confidence(str, Enum):
    """How much weight the estimate can carry."""

    #: The range comes from a cited figure or from arithmetic on known
    #: values; the working value is unlikely to be far wrong.
    HIGH = "HIGH"
    # A defensible preliminary assumption for a familiar operation.
    MEDIUM = "MEDIUM"
    # A first-pass figure to make the model runnable at all.
    LOW = "LOW"


class EstimateMethod(str, Enum):
    """How the number was actually arrived at. Never decorative."""

    # Arithmetic on values the concept already holds (e.g.
    DERIVED = "DERIVED"
    # A bundled reference dataset, named in `basis`.
    REFERENCE_DATA = "REFERENCE_DATA"
    # A language model structured the engineer's description into a range.
    LANGUAGE_MODEL = "LANGUAGE_MODEL"
    #: Composed from Fabrivium's documented reference bands when the
    #: language model could not be reached (Phase 18B). The value is still
    #: an ENGINEERING_ESTIMATE — only the mechanism differs.
    LOCAL_HEURISTIC = "LOCAL_HEURISTIC"
    # The engineer typed the range themselves.
    ENGINEER = "ENGINEER"


class EstimatedRange(BaseModel):
    """A preliminary engineering assumption expressed as a range."""

    model_config = {"frozen": True}

    low: float = Field(..., gt=0, description="Optimistic end of the range")
    working_value: float = Field(..., gt=0, description="The value the simulation will use")
    high: float = Field(..., gt=0, description="Pessimistic end of the range")
    unit: str = Field(..., min_length=1, description="e.g. 's', 'units'")

    confidence: Confidence
    method: EstimateMethod
    #: What the number rests on, in the engineer's words — "6 fastening
    #: operations + handling allowance". An estimate without a basis is
    #: indistinguishable from a guess, so this is required.
    basis: str = Field(..., min_length=1)
    #: Only set when a language model was involved, so the provenance view
    #: can name it rather than saying "AI".
    model_name: str | None = None
    # G11 — how many times the operation was assumed to happen per unit when this range
    # was composed.
    operations_per_unit: int | None = None

    @model_validator(mode="after")
    def _ordered_and_contained(self) -> "EstimatedRange":
        if self.low > self.high:
            raise ValueError(f"Estimated range is inverted: low {self.low} > high {self.high}.")
        if not (self.low <= self.working_value <= self.high):
            # A working value outside its own range means the two disagree
            # about what is being claimed, and the KPIs would carry a number
            # the range does not admit.
            raise ValueError(
                f"Working value {self.working_value} lies outside the estimated "
                f"range {self.low}–{self.high}."
            )
        return self

    @property
    def spread(self) -> float:
        return self.high - self.low

    def resolve(self, *, detail: str | None = None) -> SourcedFloat:
        """The single scalar the deterministic pipeline will receive."""
        return SourcedFloat.of(
            self.working_value,
            ValueSource.ENGINEERING_ESTIMATE,
            detail or f"{self.low:g}–{self.high:g} {self.unit}, {self.confidence.value.lower()} confidence · {self.basis}",
        )

    def sweep_points(self) -> list[float]:
        """The values a sensitivity sweep should evaluate."""
        seen: list[float] = []
        for value in (self.low, self.working_value, self.high):
            if not any(abs(value - kept) < 1e-9 for kept in seen):
                seen.append(value)
        return sorted(seen)


class EstimateUnavailable(BaseModel):
    """Why no estimate could be produced."""

    model_config = {"frozen": True}

    reason: str = Field(..., min_length=1)
    #: True when a human could fix this by trying later or configuring a
    #: provider; false when no amount of retrying would help.
    retryable: bool = False


class ValueRevision(BaseModel):
    """One step in a value's life, kept so a change can be explained."""

    model_config = {"frozen": True}

    field: str = Field(..., min_length=1, description="e.g. 'cycle_time'")
    previous_value: float | None = None
    previous_source: ValueSource
    new_value: float
    new_source: ValueSource
    reason: str = Field(..., min_length=1)
    # Where the stronger evidence came from, when there is a document.
    evidence_url: str | None = None

    @model_validator(mode="after")
    def _must_be_a_real_change(self) -> "ValueRevision":
        if self.previous_value == self.new_value and self.previous_source is self.new_source:
            raise ValueError("A revision that changes neither the value nor its source is not a revision.")
        return self


# The order in which evidence supersedes evidence.
EVIDENCE_STRENGTH: dict[ValueSource, int] = {
    ValueSource.UNKNOWN: 0,
    # A stated planning convention, applying to no particular factory.
    ValueSource.CATALOG_DEFAULT: 1,
    # Preliminary assumptions. Good enough to simulate a concept with.
    ValueSource.ENGINEERING_ESTIMATE: 2,
    ValueSource.EXAMPLE_DATA: 2,
    # Fabrivium's own predictions — arithmetic, or a simulation run.
    ValueSource.CALCULATED: 3,
    ValueSource.SIMULATED: 3,
    # Facts about a specific real item, published by whoever sells it.
    ValueSource.MANUFACTURER: 4,
    ValueSource.EXTERNAL_DATA: 4,
    # A person's statement, decision or cited paperwork. See the tie note.
    ValueSource.CUSTOMER: 5,
    ValueSource.ENGINEER: 5,
    ValueSource.DOCUMENT: 5,
    # Observed on a real line. The only entry that is not a prediction.
    ValueSource.MEASURED: 6,
}

# Ranks that mean "a person or an instrument settled this".
DECIDED_BY_A_PERSON = 5


def is_upgrade(previous: ValueSource, new: ValueSource) -> bool:
    """Whether `new` is stronger evidence than `previous`."""
    return EVIDENCE_STRENGTH[new] > EVIDENCE_STRENGTH[previous]


class StationAssumptionProposal(BaseModel):
    """Preliminary simulation assumptions for ONE station — Phase 18B."""

    model_config = {"frozen": True}

    stage_id: str = Field(..., min_length=1)
    stage_name: str = Field(..., min_length=1)

    # Seconds per unit. None when neither route could justify a figure.
    cycle_time: EstimatedRange | None = None
    #: Units the station processes CONCURRENTLY — the simulator's
    #: `simpy.Resource` capacity, not batch size and not buffer space.
    capacity: EstimatedRange | None = None
    # Operators this station occupies from the factory pool while running.
    operators: EstimatedRange | None = None

    #: True when the language model could not be reached and the local
    #: heuristic produced these.
    fell_back: bool = False
    # Provider-side detail, for developers. Never the headline.
    provider_note: str | None = None

    @property
    def proposed_fields(self) -> list[str]:
        """Which parameters actually carry a proposal."""
        return [
            name
            for name, value in (
                ("cycle_time", self.cycle_time),
                ("capacity", self.capacity),
                ("operators", self.operators),
            )
            if value is not None
        ]

    @property
    def has_any(self) -> bool:
        return bool(self.proposed_fields)
