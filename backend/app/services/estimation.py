"""Engineering estimation assistant — Phase 18."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from app.llm import LLMProvider, LLMProviderError
from app.llm.errors import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.models import LLMRequest
from app.models.concept import FactoryConceptDraft, SourcedFloat, SourcedInt, ValueSource
from app.models.uncertainty import (
    Confidence,
    EstimatedRange,
    EstimateMethod,
    EstimateUnavailable,
    StationAssumptionProposal,
)
from app.services import local_estimator
from app.services.local_estimator import Contradiction, MissingInformation

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600.0


class EstimationMode(str, Enum):
    """Which estimators may run."""

    # Language model first, local heuristic if it cannot be reached.
    AUTO = "AUTO"
    # Language model only. A provider failure is reported, not worked around.
    LLM_ONLY = "LLM_ONLY"
    # Local heuristic only. No provider call is made at all.
    LOCAL_ONLY = "LOCAL_ONLY"


# Provider failures that justify falling back to the local heuristic.
_FALLBACK_TRIGGERS: tuple[type[Exception], ...] = (
    LLMTimeoutError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMAuthenticationError,
    LLMUnsupportedCapabilityError,
    LLMMalformedResponseError,
)


@dataclass(frozen=True)
class EstimationOutcome:
    """What the estimation service produced, and how."""

    estimate: EstimatedRange | None = None
    missing: MissingInformation | None = None
    contradiction: Contradiction | None = None
    fell_back: bool = False
    #: Present only when a fallback happened: the provider-side reason, for
    #: developer-facing detail. Never the primary user message.
    provider_note: str | None = None
    #: Phase 18B — capacity/operator figures the language model volunteered
    #: alongside the cycle time, as (value, basis). Carried here rather than
    #: bolted onto the frozen range, which describes one parameter only.
    llm_capacity: tuple[float, str | None] | None = None
    llm_operators: tuple[float, str | None] | None = None


class AutomationLevel(str, Enum):
    """How the operation is performed."""

    MANUAL = "MANUAL"
    ASSISTED = "ASSISTED"
    AUTOMATIC = "AUTOMATIC"
    UNKNOWN = "UNKNOWN"


class EstimationRequest(BaseModel):
    """What the engineer tells the assistant about one operation."""

    stage_id: str = Field(..., min_length=1)
    stage_name: str = Field(..., min_length=1)
    # The concept stage's own process family ("assembly", "screwdriving").
    process_category: str = Field("", description="Process family, from the concept stage")
    # Free text — "six screws into a plastic electronics enclosure".
    description: str = Field(..., min_length=1)
    automation_level: AutomationLevel = AutomationLevel.UNKNOWN
    # e.g. 6 screws. Optional: many operations have no natural count.
    operations_per_unit: int | None = Field(None, gt=0)
    part_information: str | None = None
    other_constraints: str | None = None


class _RangeProposal(BaseModel):
    """The shape the language model must return. Validated, never trusted raw."""

    low_seconds: float = Field(..., gt=0)
    working_seconds: float = Field(..., gt=0)
    high_seconds: float = Field(..., gt=0)
    confidence: str
    basis: str = Field(..., min_length=1)
    capacity: float | None = None
    capacity_basis: str | None = None
    operators: float | None = None
    operators_basis: str | None = None


# 1. Deterministic derivation

def production_seconds_per_day(draft: FactoryConceptDraft) -> float | None:
    """Available production time, or None while the schedule is unknown."""
    if not draft.shifts_per_day.known or not draft.hours_per_shift.known:
        return None
    return float(draft.shifts_per_day.value or 0) * float(draft.hours_per_shift.value or 0.0) * SECONDS_PER_HOUR


def derive_takt_seconds(draft: FactoryConceptDraft) -> SourcedFloat:
    """Seconds per unit the line must average to meet the target."""
    seconds = production_seconds_per_day(draft)
    if seconds is None or not draft.production_target.known:
        return SourcedFloat.unknown()

    target = float(draft.production_target.value or 0.0)
    if target <= 0:
        return SourcedFloat.unknown()

    takt = seconds / target
    return SourcedFloat.of(
        takt,
        ValueSource.CALCULATED,
        f"{seconds:,.0f} s of production time ÷ {target:,.0f} units/day",
    )


# 2. Assisted estimation

_SYSTEM_PROMPT = """You are assisting a manufacturing engineer during CONCEPT design.

Given a description of one production operation, propose a preliminary cycle
time RANGE in seconds per unit.

Rules you must follow:
- Return a range, not a single figure. Concept-stage work does not justify
  false precision.
- State the basis: what you counted, and what allowance you added.
- If the description does not give you enough to reason from, return
  confidence LOW and say so in the basis.
- Never state a production rate, a throughput or a daily output. You are
  proposing one assumption; a deterministic simulator computes the rest.

Also propose, ONLY where the description supports it:
- capacity: how many units the station works on AT THE SAME TIME (parallel
  fixtures, twin nests). One person working on one unit is 1. If the
  description does not say, return null.
- operators: how many people this station occupies WHILE IT RUNS. This is
  one station's demand, never the size of the factory's workforce. If the
  description does not say, return null.

Return null rather than guessing. A null is useful; a wrong number is not.

Return JSON only:
{"low_seconds": <number>, "working_seconds": <number>, "high_seconds": <number>,
 "confidence": "HIGH"|"MEDIUM"|"LOW", "basis": "<one sentence>",
 "capacity": <number|null>, "capacity_basis": "<one sentence|null>",
 "operators": <number|null>, "operators_basis": "<one sentence|null>"}"""


def estimate_cycle_time(
    request: EstimationRequest,
    provider: LLMProvider | None,
    *,
    mode: EstimationMode = EstimationMode.AUTO,
) -> EstimationOutcome:
    """Produce a preliminary cycle-time range, by whichever route works."""
    contradiction = local_estimator.detect_contradiction(
        request.description, request.automation_level.value
    )
    if contradiction is not None:
        return EstimationOutcome(contradiction=contradiction)

    if mode is EstimationMode.LOCAL_ONLY:
        return _local_outcome(request, fell_back=False)

    if provider is None:
        if mode is EstimationMode.LLM_ONLY:
            return EstimationOutcome(
                missing=MissingInformation(
                    reason="No language-model provider is configured, and the mode is LLM_ONLY.",
                    questions=["Enter the cycle time directly, or switch the mode to AUTO."],
                )
            )
        logger.info("estimation: no provider configured, using local heuristic")
        return _local_outcome(request, fell_back=True, note="No language-model provider is configured.")

    try:
        result = provider.generate_structured(
            LLMRequest(system_prompt=_SYSTEM_PROMPT, user_prompt=_build_prompt(request)),
            response_model=_RangeProposal,
        )
    except _FALLBACK_TRIGGERS as exc:
        # Logged by class so a quota block and a malformed response remain
        # distinguishable in the logs, even though both fall back.
        logger.warning(
            "estimation: provider failed (%s), falling back to local heuristic: %s",
            type(exc).__name__,
            exc,
        )
        if mode is EstimationMode.LLM_ONLY:
            return EstimationOutcome(
                missing=MissingInformation(
                    reason=f"The language model could not be reached: {exc}",
                    questions=["Enter the cycle time directly, or switch the mode to AUTO."],
                )
            )
        return _local_outcome(request, fell_back=True, note=f"{type(exc).__name__}: {exc}")
    except LLMProviderError as exc:  # pragma: no cover - defensive
        logger.warning("estimation: unclassified provider error, falling back: %s", exc)
        return _local_outcome(request, fell_back=True, note=str(exc))

    parsed = _range_from_proposal(result.parsed, provider, request)
    if isinstance(parsed, EstimatedRange):
        capacity, operators = _optional_extras(result.parsed)
        return EstimationOutcome(estimate=parsed, llm_capacity=capacity, llm_operators=operators)

    # The provider answered, but with something unusable.
    logger.warning("estimation: provider returned an unusable range: %s", parsed.reason)
    if mode is EstimationMode.LLM_ONLY:
        return EstimationOutcome(
            missing=MissingInformation(
                reason=parsed.reason,
                questions=["Enter the cycle time directly, or switch the mode to AUTO."],
            )
        )
    return _local_outcome(request, fell_back=True, note=parsed.reason)


def _local_outcome(
    request: EstimationRequest,
    *,
    fell_back: bool,
    note: str | None = None,
) -> EstimationOutcome:
    """Run the deterministic estimator and wrap whichever answer it gives."""
    outcome = local_estimator.estimate(
        process_category=request.process_category,
        description=request.description,
        automation_level=request.automation_level.value,
        operations_per_unit=request.operations_per_unit,
    )
    if isinstance(outcome, MissingInformation):
        # A fallback that cannot estimate either is still an honest gap, not
        # a provider problem — so the provider note does not travel with it.
        return EstimationOutcome(missing=outcome)
    return EstimationOutcome(estimate=outcome, fell_back=fell_back, provider_note=note)


def _build_prompt(request: EstimationRequest) -> str:
    lines = [f"Operation: {request.stage_name}", f"Description: {request.description}"]
    if request.automation_level is not AutomationLevel.UNKNOWN:
        lines.append(f"Automation level: {request.automation_level.value.lower()}")
    if request.operations_per_unit:
        lines.append(f"Operations per unit: {request.operations_per_unit}")
    if request.part_information:
        lines.append(f"Part information: {request.part_information}")
    if request.other_constraints:
        lines.append(f"Other constraints: {request.other_constraints}")
    return "\n".join(lines)


def _range_from_proposal(
    proposal: object,
    provider: LLMProvider,
    request: EstimationRequest,
) -> EstimatedRange | EstimateUnavailable:
    """Turn a validated proposal into an EstimatedRange, or refuse."""
    data = proposal if isinstance(proposal, dict) else getattr(proposal, "__dict__", {})
    if not data:
        data = {
            "low_seconds": getattr(proposal, "low_seconds", None),
            "working_seconds": getattr(proposal, "working_seconds", None),
            "high_seconds": getattr(proposal, "high_seconds", None),
            "confidence": getattr(proposal, "confidence", "LOW"),
            "basis": getattr(proposal, "basis", ""),
        }

    try:
        confidence = Confidence(str(data.get("confidence", "LOW")).upper())
    except ValueError:
        confidence = Confidence.LOW

    try:
        return EstimatedRange(
            low=float(data["low_seconds"]),
            working_value=float(data["working_seconds"]),
            high=float(data["high_seconds"]),
            unit="s",
            confidence=confidence,
            method=EstimateMethod.LANGUAGE_MODEL,
            basis=str(data.get("basis") or f"Preliminary assumption for {request.stage_name}"),
            model_name=provider.model_name,
            # What the model was told the repetition count was.
            operations_per_unit=request.operations_per_unit,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return EstimateUnavailable(
            reason=f"The assistant returned a range that is not usable ({exc}). Enter a value directly instead.",
            retryable=True,
        )


def manual_range(
    *,
    low: float,
    working: float,
    high: float,
    basis: str,
    confidence: Confidence = Confidence.MEDIUM,
) -> EstimatedRange:
    """The engineer's own range. Needs no provider and never fails silently."""
    return EstimatedRange(
        low=low,
        working_value=working,
        high=high,
        unit="s",
        confidence=confidence,
        method=EstimateMethod.ENGINEER,
        basis=basis,
    )


def apply_estimate(
    draft: FactoryConceptDraft,
    stage_id: str,
    estimate: EstimatedRange,
) -> FactoryConceptDraft:
    """Write the estimate's working value onto the stage."""
    stages = []
    for stage in draft.stages:
        if stage.id != stage_id:
            stages.append(stage)
            continue
        stages.append(
            stage.model_copy(
                update={
                    "cycle_time": estimate.resolve(),
                    "cycle_time_estimate": estimate,
                }
            )
        )
    return draft.model_copy(update={"stages": stages})

def _optional_extras(parsed: object) -> tuple[tuple[float, str | None] | None, tuple[float, str | None] | None]:
    """Capacity/operator figures the model volunteered, if any."""
    data = parsed if isinstance(parsed, dict) else getattr(parsed, "__dict__", {}) or {}

    def read(field: str) -> tuple[float, str | None] | None:
        value = data.get(field) if isinstance(data, dict) else getattr(parsed, field, None)
        basis = data.get(f"{field}_basis") if isinstance(data, dict) else getattr(parsed, f"{field}_basis", None)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return (number, basis) if number > 0 else None

    return read("capacity"), read("operators")


# Station-level assumptions — Phase 18B


@dataclass(frozen=True)
class StationOutcome:
    """One coherent answer for one station."""

    proposal: StationAssumptionProposal | None = None
    missing: MissingInformation | None = None
    contradiction: Contradiction | None = None


def propose_station_assumptions(
    request: EstimationRequest,
    provider: LLMProvider | None,
    *,
    mode: EstimationMode = EstimationMode.AUTO,
) -> StationOutcome:
    """Cycle time, capacity and operator demand from one description."""
    outcome = estimate_cycle_time(request, provider, mode=mode)

    if outcome.contradiction is not None:
        return StationOutcome(contradiction=outcome.contradiction)

    capacity = local_estimator.propose_capacity(
        process_category=request.process_category,
        description=request.description,
        automation_level=request.automation_level.value,
    )
    operators = local_estimator.propose_operators(
        description=request.description,
        automation_level=request.automation_level.value,
    )

    # Where the model volunteered a figure it wins: it read the whole description.
    capacity = _as_range(outcome.llm_capacity, "units", outcome) or capacity
    operators = _as_range(outcome.llm_operators, "operators", outcome) or operators

    if outcome.estimate is None and capacity is None and operators is None:
        return StationOutcome(missing=outcome.missing)

    return StationOutcome(
        proposal=StationAssumptionProposal(
            stage_id=request.stage_id,
            stage_name=request.stage_name,
            cycle_time=outcome.estimate,
            capacity=capacity,
            operators=operators,
            fell_back=outcome.fell_back,
            provider_note=outcome.provider_note,
        )
    )


def _as_range(
    supplied: tuple[float, str | None] | None,
    unit: str,
    outcome: "EstimationOutcome",
) -> EstimatedRange | None:
    """One model-supplied count as a range, or None if it is unusable."""
    if supplied is None:
        return None
    value, basis = supplied
    model = outcome.estimate.model_name if outcome.estimate else None
    try:
        return EstimatedRange(
            low=value, working_value=value, high=value, unit=unit,
            confidence=outcome.estimate.confidence if outcome.estimate else Confidence.LOW,
            method=EstimateMethod.LANGUAGE_MODEL,
            basis=basis or f"Proposed by {model or 'the language model'} from the description.",
            model_name=model,
        )
    except ValueError:
        return None

def apply_station_assumptions(
    draft: FactoryConceptDraft,
    proposal: StationAssumptionProposal,
    accepted_fields: list[str],
) -> tuple[FactoryConceptDraft, list[str]]:
    """Write the accepted parameters onto the stage. Returns (draft, applied)."""
    accepted = set(accepted_fields)
    applied: list[str] = []
    updates: dict[str, object] = {}

    if "cycle_time" in accepted and proposal.cycle_time is not None:
        updates["cycle_time"] = proposal.cycle_time.resolve()
        updates["cycle_time_estimate"] = proposal.cycle_time
        applied.append("cycle_time")

    # Capacity and operators are whole things — half an operator is not a
    # reading the simulator can act on — so they round rather than truncate.
    for field, source in (("capacity", proposal.capacity), ("operators_required", proposal.operators)):
        key = "operators" if field == "operators_required" else field
        if key in accepted and source is not None:
            updates[field] = SourcedInt.of(
                int(round(source.working_value)),
                ValueSource.ENGINEERING_ESTIMATE,
                _assumption_detail(source),
            )
            applied.append(key)

    if not applied:
        return draft, []

    stages = [
        stage.model_copy(update=updates) if stage.id == proposal.stage_id else stage
        for stage in draft.stages
    ]
    return draft.model_copy(update={"stages": stages}), applied


# Provenance an estimate may NOT silently replace.
PROTECTED_SOURCES: frozenset[ValueSource] = frozenset(
    {
        ValueSource.ENGINEER,
        ValueSource.MEASURED,
        ValueSource.DOCUMENT,
        ValueSource.CUSTOMER,
        ValueSource.MANUFACTURER,
    }
)

# Concept-stage field -> the name the estimation API uses for it.
_ESTIMATE_FIELDS: dict[str, str] = {
    "cycle_time": "cycle_time",
    "capacity": "capacity",
    "operators_required": "operators",
}


@dataclass(frozen=True)
class ProtectedValue:
    """A value an estimate would replace, and what it would replace it with."""

    field: str
    label: str
    value: float | int | None
    source: str
    detail: str | None

    def describe(self) -> str:
        shown = "unknown" if self.value is None else f"{self.value:g}"
        return f"{self.label} is {shown}, entered as {self.source.replace('_', ' ').lower()}"


def protected_values(
    draft: FactoryConceptDraft, stage_id: str, fields: list[str]
) -> list[ProtectedValue]:
    """Which of these stage fields already hold something stronger than an estimate."""
    stage = draft.stage_by_id(stage_id)
    if stage is None:
        return []

    wanted = set(fields)
    found: list[ProtectedValue] = []
    for attribute, api_name in _ESTIMATE_FIELDS.items():
        if api_name not in wanted:
            continue
        current = getattr(stage, attribute, None)
        if current is None or current.value is None:
            continue
        if current.source not in PROTECTED_SOURCES:
            continue
        found.append(
            ProtectedValue(
                field=api_name,
                label=f"{stage.name} {attribute.replace('_', ' ')}",
                value=current.value,
                source=current.source.value,
                detail=current.detail,
            )
        )
    return found


# How a locally-derived estimate names itself in a provenance badge.
LOCAL_HEURISTIC_METHOD_LABEL = "Fabrivium engineering heuristic"


def _assumption_detail(source: EstimatedRange) -> str:
    """The provenance string a badge tooltip shows for a non-cycle value."""
    method = (
        LOCAL_HEURISTIC_METHOD_LABEL
        if source.method is EstimateMethod.LOCAL_HEURISTIC
        else (source.model_name or "language model")
    )
    return f"{source.confidence.value.lower()} confidence · {method} · {source.basis}"
