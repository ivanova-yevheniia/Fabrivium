"""Engineering input resolution — real data first."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.concept import (
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.models.uncertainty import ValueRevision
from app.services.concept_validation import DEFAULT_BUFFER_CAPACITY, DEFAULT_STATION_CAPACITY

SECONDS_PER_HOUR = 3600.0


class Necessity(str, Enum):
    """What actually depends on this input."""

    # The simulator cannot run without it.
    BLOCKS_SIMULATION = "BLOCKS_SIMULATION"
    # Placement and layout validation need it; throughput does not.
    AFFECTS_LAYOUT = "AFFECTS_LAYOUT"
    # Money. Affects ranking and reporting, never physics.
    COMMERCIAL_ONLY = "COMMERCIAL_ONLY"
    # The simulator has a documented default and runs without it.
    HAS_DEFAULT = "HAS_DEFAULT"


class ResolutionAction(str, Enum):
    """A way this particular value can legitimately be obtained."""

    # Type a number in. Recorded as ENGINEER.
    ENGINEER_INPUT = "ENGINEER_INPUT"
    # Ask the Phase 18 assistant for a range and a working value.
    ESTIMATE = "ESTIMATE"
    # Take a published figure from equipment discovery.
    EXTERNAL_DATA = "EXTERNAL_DATA"
    # Enter a supplier quotation.
    ENTER_QUOTE = "ENTER_QUOTE"
    USE_EXAMPLE_DATA = "USE_EXAMPLE_DATA"
    # Explicitly keep it unknown.
    LEAVE_UNKNOWN = "LEAVE_UNKNOWN"


# Sources that represent a real-world fact or decision about THIS factory.
AUTHORITATIVE_SOURCES = frozenset(
    {
        ValueSource.CUSTOMER,
        ValueSource.ENGINEER,
        ValueSource.DOCUMENT,
        ValueSource.MEASURED,
        ValueSource.MANUFACTURER,
        ValueSource.EXTERNAL_DATA,
    }
)


@dataclass(frozen=True)
class ResolvableInput:
    """One value the engineer may resolve, with everything needed to decide."""

    # Stable address, e.g.
    key: str
    label: str
    # Display unit ("s", "h", "€", "units"), or None for a bare count.
    unit: str | None
    value: float | None
    source: ValueSource
    # The dataset, document or brief the value came from, verbatim.
    detail: str | None
    necessity: Necessity
    # Why the simulator needs it, or why it does not. Shown, not summarised.
    consequence: str
    # Legitimate ways to obtain it, strongest first.
    actions: tuple[ResolutionAction, ...]
    stage_id: str | None = None
    #: True when the value is absent AND the only route to it is commercial
    #: — the state that must render as "quote required" rather than "€0".
    quote_required: bool = False

    # The range this value is the working value of, when it is currently an engineering
    # estimate.
    estimate: object | None = None
    #: One line naming the estimate this value replaced, from the newest
    #: revision on the stage. Present only after an override, and it is what
    #: makes the override visible rather than merely correct.
    superseded: str | None = None

    @property
    def resolved(self) -> bool:
        return self.value is not None

    @property
    def authoritative(self) -> bool:
        """True when this value states a fact or decision about this factory."""
        return self.source in AUTHORITATIVE_SOURCES


@dataclass(frozen=True)
class ComputedValue:
    """A quantity Fabrivium derives. Never editable, always explained."""

    key: str
    label: str
    unit: str | None
    value: float | None
    # The arithmetic, written out, e.g. "57,600 s ÷ 1,900 units".
    formula: str
    blocked_by: str | None = None
    # CALCULATED for arithmetic, SIMULATED for anything a run produced.
    source: ValueSource = ValueSource.CALCULATED


@dataclass(frozen=True)
class ResolutionPlan:
    """Everything the engineer needs to finish this concept."""

    inputs: list[ResolvableInput] = field(default_factory=list)
    computed: list[ComputedValue] = field(default_factory=list)

    @property
    def blocking_unresolved(self) -> list[ResolvableInput]:
        return [
            i
            for i in self.inputs
            if not i.resolved and i.necessity is Necessity.BLOCKS_SIMULATION
        ]

    @property
    def ready_to_simulate(self) -> bool:
        return not self.blocking_unresolved


# Written per quantity, deliberately.

#: Operation physics: the estimator has a real basis for these (process
#: family reference bands, automation level, operation counts).
_ESTIMATABLE = (
    ResolutionAction.ESTIMATE,
    ResolutionAction.ENGINEER_INPUT,
    ResolutionAction.USE_EXAMPLE_DATA,
    ResolutionAction.LEAVE_UNKNOWN,
)

# Operating constraints: nobody can derive how many shifts a company runs.
_ASK_ONLY = (
    ResolutionAction.ENGINEER_INPUT,
    ResolutionAction.USE_EXAMPLE_DATA,
    ResolutionAction.LEAVE_UNKNOWN,
)

# Money for a specific machine: a published price, a quotation, or nothing.
_COMMERCIAL = (
    ResolutionAction.EXTERNAL_DATA,
    ResolutionAction.ENTER_QUOTE,
    ResolutionAction.USE_EXAMPLE_DATA,
    ResolutionAction.LEAVE_UNKNOWN,
)


def _newest_revision_reason(stage: ConceptStage, field_name: str) -> str | None:
    """The most recent revision recorded for one stage field, in words."""
    for revision in reversed(stage.revisions):
        if isinstance(revision, dict):
            if revision.get("field") == field_name:
                return revision.get("reason")
        elif getattr(revision, "field", None) == field_name:
            return getattr(revision, "reason", None)
    return None


def _stage_inputs(stage: ConceptStage) -> list[ResolvableInput]:
    return [
        ResolvableInput(
            key=f"stage.{stage.id}.cycle_time",
            label=f"{stage.name} — cycle time",
            unit="s",
            value=stage.cycle_time.value,
            source=stage.cycle_time.source,
            detail=stage.cycle_time.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence="Processing time per unit. The simulation cannot run a stage without it.",
            actions=_ESTIMATABLE,
            stage_id=stage.id,
            # Guarded by the same predicate `write_input` uses to retire the
            # range, so the row can never offer a basis for a number the
            # range does not describe.
            estimate=(
                stage.cycle_time_estimate
                if _estimate_still_describes(stage, stage.cycle_time)
                else None
            ),
            superseded=_newest_revision_reason(stage, "cycle_time"),
        ),
        ResolvableInput(
            key=f"stage.{stage.id}.capacity",
            label=f"{stage.name} — capacity",
            unit="units in process",
            value=stage.capacity.value,
            source=stage.capacity.source,
            detail=stage.capacity.detail,
            necessity=Necessity.HAS_DEFAULT,
            consequence=(
                f"How many units the station processes at once. Defaults to "
                f"{DEFAULT_STATION_CAPACITY} — one unit at a time — which is the simulator's own "
                f"convention, not an estimate of this station."
            ),
            actions=_ESTIMATABLE,
            stage_id=stage.id,
        ),
        ResolvableInput(
            key=f"stage.{stage.id}.operators_required",
            label=f"{stage.name} — operators",
            unit="people",
            value=stage.operators_required.value,
            source=stage.operators_required.source,
            detail=stage.operators_required.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence=(
                "People this station occupies while running. The simulator queues work "
                "behind the operator pool, so this changes throughput. Enter 0 if the "
                "station runs unattended."
            ),
            actions=_ESTIMATABLE,
            stage_id=stage.id,
        ),
        ResolvableInput(
            key=f"stage.{stage.id}.purchase_cost",
            label=f"{stage.name} — equipment cost",
            unit="€",
            value=stage.purchase_cost.value,
            source=stage.purchase_cost.source,
            detail=stage.purchase_cost.detail,
            necessity=Necessity.COMMERCIAL_ONLY,
            consequence=(
                "Commercial only. The simulation reads no price; an unknown price stays unknown "
                "and is never counted as zero."
            ),
            actions=_COMMERCIAL,
            stage_id=stage.id,
            quote_required=not stage.purchase_cost.known,
        ),
        ResolvableInput(
            key=f"stage.{stage.id}.width",
            label=f"{stage.name} — width",
            unit="m",
            value=stage.width.value,
            source=stage.width.source,
            detail=stage.width.detail,
            necessity=Necessity.AFFECTS_LAYOUT,
            consequence="Used to place the station on the floor. Placement does not affect throughput.",
            actions=_ASK_ONLY,
            stage_id=stage.id,
        ),
        ResolvableInput(
            key=f"stage.{stage.id}.length",
            label=f"{stage.name} — length",
            unit="m",
            value=stage.length.value,
            source=stage.length.source,
            detail=stage.length.detail,
            necessity=Necessity.AFFECTS_LAYOUT,
            consequence="Used to place the station on the floor. Placement does not affect throughput.",
            actions=_ASK_ONLY,
            stage_id=stage.id,
        ),
    ]


def resolution_plan(draft: FactoryConceptDraft) -> ResolutionPlan:
    """Every input this concept needs, and everything it can work out itself."""
    inputs: list[ResolvableInput] = [
        ResolvableInput(
            key="production_target",
            label="Daily production target",
            unit="units/day",
            value=draft.production_target.value,
            source=draft.production_target.source,
            detail=draft.production_target.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence="The demand every result is measured against.",
            actions=(ResolutionAction.ENGINEER_INPUT, ResolutionAction.LEAVE_UNKNOWN),
        ),
        ResolvableInput(
            key="shifts_per_day",
            label="Shifts per day",
            unit=None,
            value=draft.shifts_per_day.value,
            source=draft.shifts_per_day.source,
            detail=draft.shifts_per_day.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence=(
                "An operating decision, not a property of the product. It sets how long the line "
                "runs, so it cannot be inferred from the target."
            ),
            actions=_ASK_ONLY,
        ),
        ResolvableInput(
            key="hours_per_shift",
            label="Hours per shift",
            unit="h",
            value=draft.hours_per_shift.value,
            source=draft.hours_per_shift.source,
            detail=draft.hours_per_shift.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence=(
                "An operating decision, not a property of the product. It sets how long the line "
                "runs, so it cannot be inferred from the target."
            ),
            actions=_ASK_ONLY,
        ),
        ResolvableInput(
            key="operators_available",
            label="Operators available",
            unit="people",
            value=draft.operators_available.value,
            source=draft.operators_available.source,
            detail=draft.operators_available.detail,
            necessity=Necessity.BLOCKS_SIMULATION,
            consequence=(
                "The shared pool the simulation allocates from. This is the whole factory's "
                "workforce, not one station's demand."
            ),
            actions=_ASK_ONLY,
        ),
    ]

    for stage in draft.stages:
        inputs.extend(_stage_inputs(stage))

    for buffer in draft.buffers:
        inputs.append(
            ResolvableInput(
                key=f"buffer.{buffer.id}.capacity",
                label=f"{buffer.name} — buffer size",
                unit="units",
                value=buffer.capacity.value,
                source=buffer.capacity.source,
                detail=buffer.capacity.detail,
                necessity=Necessity.HAS_DEFAULT,
                consequence=(
                    f"Storage between two stages. Defaults to {DEFAULT_BUFFER_CAPACITY}. Whether it "
                    f"matters for this target is a question the simulator can answer — run the "
                    f"buffer sweep rather than assuming a size."
                ),
                actions=_ASK_ONLY,
            )
        )

    inputs.extend(
        [
            ResolvableInput(
                key="budget",
                label="Capital budget",
                unit="€",
                value=draft.budget.value,
                source=draft.budget.source,
                detail=draft.budget.detail,
                necessity=Necessity.COMMERCIAL_ONLY,
                consequence=(
                    "A commercial constraint the customer or the engineer sets. Nothing in the "
                    "factory model implies it, so Fabrivium never proposes a figure."
                ),
                actions=_ASK_ONLY,
            ),
            ResolvableInput(
                key="floor_width",
                label="Floor width",
                unit="m",
                value=draft.floor_width.value,
                source=draft.floor_width.source,
                detail=draft.floor_width.detail,
                necessity=Necessity.AFFECTS_LAYOUT,
                consequence="Bounds where stations may be placed. Does not affect throughput.",
                actions=_ASK_ONLY,
            ),
            ResolvableInput(
                key="floor_length",
                label="Floor length",
                unit="m",
                value=draft.floor_length.value,
                source=draft.floor_length.source,
                detail=draft.floor_length.detail,
                necessity=Necessity.AFFECTS_LAYOUT,
                consequence="Bounds where stations may be placed. Does not affect throughput.",
                actions=_ASK_ONLY,
            ),
        ]
    )

    return ResolutionPlan(inputs=inputs, computed=computed_values(draft))


# Computed values Definitional arithmetic only.

def computed_values(draft: FactoryConceptDraft) -> list[ComputedValue]:
    """What Fabrivium works out for itself, with the arithmetic shown."""
    shifts = draft.shifts_per_day.value
    hours = draft.hours_per_shift.value
    target = draft.production_target.value

    available: float | None = None
    if shifts is not None and hours is not None:
        available = float(shifts) * float(hours) * SECONDS_PER_HOUR

    out = [
        ComputedValue(
            key="available_production_time",
            label="Available production time",
            unit="s/day",
            value=available,
            formula=(
                f"{shifts:g} shifts × {hours:g} h × 3600 s"
                if available is not None
                else "shifts × hours × 3600"
            ),
            blocked_by=None if available is not None else "the operating schedule",
        )
    ]

    takt: float | None = None
    if available is not None and target:
        takt = available / float(target)
    out.append(
        ComputedValue(
            key="required_takt",
            label="Required takt",
            unit="s/unit",
            value=takt,
            formula=(
                f"{available:,.0f} s ÷ {target:,.0f} units"
                if takt is not None
                else "available production time ÷ daily target"
            ),
            blocked_by=(
                None
                if takt is not None
                else ("the operating schedule" if available is None else "the production target")
            ),
        )
    )

    # The sum of stage cycle times is NOT throughput — a line loses output to
    # blocking and starvation — so this is labelled as what it is: the
    # fastest a single unit can traverse the route.
    known_cycles = [s.cycle_time.value for s in draft.stages if s.cycle_time.known]
    all_known = len(known_cycles) == len(draft.stages) and bool(draft.stages)
    out.append(
        ComputedValue(
            key="route_processing_time",
            label="Processing time per unit along the route",
            unit="s",
            value=sum(known_cycles) if all_known else None,  # type: ignore[arg-type]
            formula=" + ".join(f"{c:g}" for c in known_cycles) if all_known else "sum of stage cycle times",
            blocked_by=None if all_known else "at least one stage cycle time",
        )
    )

    # Slowest stage sets the ceiling on a serial line.
    slowest = max(known_cycles) if known_cycles and all_known else None
    out.append(
        ComputedValue(
            key="slowest_stage_cycle_time",
            label="Slowest stage cycle time",
            unit="s",
            value=slowest,
            formula=(
                f"max({', '.join(f'{c:g}' for c in known_cycles)})" if all_known else "max of stage cycle times"
            ),
            blocked_by=None if all_known else "at least one stage cycle time",
        )
    )

    return out


# Reading and writing a value by key

class UnknownInputKey(ValueError):
    """The key does not address anything in this concept."""


_DRAFT_FLOAT_FIELDS = {"production_target", "hours_per_shift", "budget", "floor_width", "floor_length"}
_DRAFT_INT_FIELDS = {"shifts_per_day", "operators_available"}
_STAGE_FLOAT_FIELDS = {"cycle_time", "purchase_cost", "width", "length"}
_STAGE_INT_FIELDS = {"capacity", "operators_required"}


def read_input(draft: FactoryConceptDraft, key: str) -> SourcedFloat | SourcedInt:
    """The current Sourced value at `key`, whatever kind it is."""
    if key in _DRAFT_FLOAT_FIELDS or key in _DRAFT_INT_FIELDS:
        return getattr(draft, key)

    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "stage":
        stage = draft.stage_by_id(parts[1])
        if stage is None:
            raise UnknownInputKey(f"The concept has no stage '{parts[1]}'.")
        if parts[2] not in _STAGE_FLOAT_FIELDS | _STAGE_INT_FIELDS:
            raise UnknownInputKey(f"A stage has no field '{parts[2]}'.")
        return getattr(stage, parts[2])

    if len(parts) == 3 and parts[0] == "buffer" and parts[2] == "capacity":
        for buffer in draft.buffers:
            if buffer.id == parts[1]:
                return buffer.capacity
        raise UnknownInputKey(f"The concept has no buffer '{parts[1]}'.")

    raise UnknownInputKey(f"'{key}' does not address a value in this concept.")


# Overriding an estimate longer describe it.

def _estimate_still_describes(stage: ConceptStage, cycle_time: SourcedFloat) -> bool:
    """Whether `stage.cycle_time_estimate` is still the basis of the value."""
    estimate = stage.cycle_time_estimate
    if estimate is None:
        return False
    if cycle_time.source is not ValueSource.ENGINEERING_ESTIMATE or cycle_time.value is None:
        return False
    working = estimate.get("working_value") if isinstance(estimate, dict) else getattr(estimate, "working_value", None)
    if working is None:
        return False
    return abs(float(working) - float(cycle_time.value)) < 1e-9


# How each source reads in a revision sentence.
_SUPERSEDED_AS: dict[ValueSource, str] = {
    ValueSource.ENGINEERING_ESTIMATE: "the engineering estimate of",
    ValueSource.ENGINEER: "the engineer-entered value of",
    ValueSource.CUSTOMER: "the customer-stated value of",
    ValueSource.MEASURED: "the measured value of",
    ValueSource.DOCUMENT: "the documented value of",
    ValueSource.MANUFACTURER: "the manufacturer-published value of",
    ValueSource.EXAMPLE_DATA: "the example-dataset value of",
    ValueSource.CATALOG_DEFAULT: "the catalog default of",
    ValueSource.EXTERNAL_DATA: "the externally-supplied value of",
    ValueSource.CALCULATED: "the derived value of",
    ValueSource.SIMULATED: "the simulated value of",
}


def _superseded_estimate_reason(stage: ConceptStage, new: SourcedFloat) -> str:
    """One sentence naming what this write replaced, for the revision log."""
    previous = stage.cycle_time
    replaced = _SUPERSEDED_AS.get(previous.source, "the previous value of")

    band = ""
    if previous.source is ValueSource.ENGINEERING_ESTIMATE:
        estimate = stage.cycle_time_estimate
        low = estimate.get("low") if isinstance(estimate, dict) else getattr(estimate, "low", None)
        high = estimate.get("high") if isinstance(estimate, dict) else getattr(estimate, "high", None)
        if low is not None and high is not None:
            band = f" ({low:g}–{high:g} s)"

    where = f" — {new.detail}" if new.detail else ""
    return f"{new.source.value} value supersedes {replaced} {previous.value:g} s{band}{where}"


def _stage_update(
    stage: ConceptStage,
    field_name: str,
    new_value: SourcedFloat | SourcedInt,
) -> dict[str, object]:
    """The full model_copy update for writing one stage field."""
    updates: dict[str, object] = {field_name: new_value}

    previous = getattr(stage, field_name)
    if previous.value == new_value.value and previous.source is new_value.source:
        # Nothing actually changed — a restore, or a re-save of the same figure.
        return updates

    if (
        field_name == "cycle_time"
        and stage.cycle_time_estimate is not None
        and not _estimate_still_describes(stage, new_value)  # type: ignore[arg-type]
    ):
        updates["cycle_time_estimate"] = None
        if new_value.value is not None:
            updates["revisions"] = [
                *stage.revisions,
                ValueRevision(
                    field="cycle_time",
                    previous_value=stage.cycle_time.value,
                    previous_source=stage.cycle_time.source,
                    new_value=float(new_value.value),
                    new_source=new_value.source,
                    reason=_superseded_estimate_reason(stage, new_value),  # type: ignore[arg-type]
                ),
            ]
        # A CLEARED value has nothing to put in `ValueRevision.new_value`,
        # which the model types as a float and should: "the value is gone"
        # is not a new reading. The estimate is still dropped — the point of
        # the contract — and the UNKNOWN badge already says what happened.

    return updates


def write_input(
    draft: FactoryConceptDraft,
    key: str,
    value: float | None,
    source: ValueSource,
    detail: str | None,
) -> FactoryConceptDraft:
    """Return a new draft with `key` set."""
    if value is None:
        source = ValueSource.UNKNOWN
        detail = None

    def as_float() -> SourcedFloat:
        return SourcedFloat.unknown() if value is None else SourcedFloat.of(float(value), source, detail)

    def as_int() -> SourcedInt:
        if value is None:
            return SourcedInt.unknown()
        rounded = int(round(float(value)))
        if abs(float(value) - rounded) > 1e-9:
            raise ValueError(f"'{key}' is a whole number; {value} is not.")
        return SourcedInt.of(rounded, source, detail)

    if key in _DRAFT_FLOAT_FIELDS:
        return _with_floor_kept_whole(draft, draft.model_copy(update={key: as_float()}), key)
    if key in _DRAFT_INT_FIELDS:
        return draft.model_copy(update={key: as_int()})

    parts = key.split(".")
    if len(parts) == 3 and parts[0] == "stage":
        stage_id, field_name = parts[1], parts[2]
        stage = draft.stage_by_id(stage_id)
        if stage is None:
            raise UnknownInputKey(f"The concept has no stage '{stage_id}'.")
        if field_name in _STAGE_FLOAT_FIELDS:
            new_value: SourcedFloat | SourcedInt = as_float()
        elif field_name in _STAGE_INT_FIELDS:
            new_value = as_int()
        else:
            raise UnknownInputKey(f"A stage has no field '{field_name}'.")
        updates = _stage_update(stage, field_name, new_value)
        stages = [s.model_copy(update=updates) if s.id == stage_id else s for s in draft.stages]
        return draft.model_copy(update={"stages": stages})

    if len(parts) == 3 and parts[0] == "buffer" and parts[2] == "capacity":
        buffer_id = parts[1]
        if not any(b.id == buffer_id for b in draft.buffers):
            raise UnknownInputKey(f"The concept has no buffer '{buffer_id}'.")
        buffers = [
            b.model_copy(update={"capacity": as_int()}) if b.id == buffer_id else b
            for b in draft.buffers
        ]
        return draft.model_copy(update={"buffers": buffers})

    raise UnknownInputKey(f"'{key}' does not address a value in this concept.")


# The floor is ONE requirement the concept holds as two numbers.
_FLOOR_PROJECTIONS = ("floor_width", "floor_length")


def _with_floor_kept_whole(
    before: FactoryConceptDraft, draft: FactoryConceptDraft, written_key: str
) -> FactoryConceptDraft:
    """Carry a floor dimension's new provenance across to the other one (G12)."""
    if written_key not in _FLOOR_PROJECTIONS:
        return draft

    written = getattr(draft, written_key)
    previous = getattr(before, written_key)
    if written.value is None:
        return draft
    if written.value == previous.value and written.source is previous.source:
        return draft

    other_key = next(name for name in _FLOOR_PROJECTIONS if name != written_key)
    other = getattr(draft, other_key)
    if other.value is None or other.source is written.source:
        return draft

    return draft.model_copy(
        update={
            other_key: other.model_copy(
                update={
                    "source": written.source,
                    "detail": (
                        f"Part of the floor size set here — the {written_key.split('_')[1]} was "
                        f"changed to {written.value:g} m, so the floor is no longer as it was "
                        f"first recorded."
                    ),
                }
            )
        }
    )


# Bulk actions Convenience that must never cost correctness.

@dataclass(frozen=True)
class BulkOutcome:
    """What a bulk action actually did, in terms the UI can show."""

    draft: FactoryConceptDraft
    # Keys that existed and were blank, and now hold a value.
    filled: list[str] = field(default_factory=list)
    # Keys that did not exist before.
    added: list[str] = field(default_factory=list)
    # Keys deliberately left alone because a person had already decided them.
    protected: list[str] = field(default_factory=list)
    # Keys this action had nothing to offer for.
    unavailable: list[str] = field(default_factory=list)


def _protected_keys(draft: FactoryConceptDraft) -> set[str]:
    return {i.key for i in resolution_plan(draft).inputs if i.authoritative}


def apply_example_data_to_unresolved(draft: FactoryConceptDraft) -> BulkOutcome:
    """Fill still-unresolved inputs from the bundled demo dataset."""
    from app.services.concept_example_data import apply_example_engineering_data

    protected = _protected_keys(draft)
    before = {i.key: i.value for i in resolution_plan(draft).inputs}

    filled_draft = apply_example_engineering_data(draft)

    # apply_example_engineering_data already refuses to touch known values;
    # this re-checks against the authoritative set rather than trusting that,
    # because "already known" and "decided by a person" are different rules
    # and only the second one is the promise being made here.
    restored = filled_draft
    for key in protected:
        original = read_input(draft, key)
        restored = write_input(restored, key, original.value, original.source, original.detail)

    after = {i.key: i.value for i in resolution_plan(restored).inputs}
    existed = set(before)
    filled = [k for k, v in after.items() if v is not None and k in existed and before[k] is None]
    added = [k for k in after if k not in existed]
    unavailable = [k for k, v in after.items() if v is None and k in existed and before[k] is None]
    return BulkOutcome(
        draft=restored,
        filled=sorted(filled),
        added=sorted(added),
        protected=sorted(protected & existed),
        unavailable=sorted(unavailable),
    )


def estimatable_keys(draft: FactoryConceptDraft) -> list[str]:
    """Unresolved inputs the Phase 18 estimator can genuinely speak to."""
    return [
        i.key
        for i in resolution_plan(draft).inputs
        if not i.resolved and ResolutionAction.ESTIMATE in i.actions
    ]
