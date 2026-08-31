"""
Information gaps, validation and Factory conversion for a factory concept draft — Phase
13.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.concept import (
    ConceptOperationGroup,
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.models.factory import Buffer, Factory, Machine, ProcessStep, Product

# Planning defaults

#: Nominal planning footprint for a station whose equipment has not been
#: chosen yet, in metres. This is a LAYOUT figure only: the simulator reads
#: no dimension (audit §1), so this cannot influence any KPI. It exists
#: because ``Machine.width``/``length`` are required to construct the model
#: at all. Always attributed as CATALOG_DEFAULT and always visible as such.
DEFAULT_STATION_WIDTH_M = 2.5
DEFAULT_STATION_LENGTH_M = 2.0

# Default capacity for a station.
DEFAULT_STATION_CAPACITY = 1

#: Default buffer size used when the engineer asks for buffers between
#: stages without naming a size. Only applied on an explicit action.
DEFAULT_BUFFER_CAPACITY = 50


# Gaps

class GapSeverity(str, Enum):
    # Simulation cannot run until this is supplied.
    REQUIRED = "REQUIRED"
    # Worth having, but the physics does not need it.
    OPTIONAL = "OPTIONAL"


@dataclass(frozen=True)
class ConceptGap:
    """One missing piece of information."""

    # Stable machine-readable key, e.g. "stage.s-screwdriving.cycle_time".
    key: str
    # What to ask the engineer for.
    label: str
    severity: GapSeverity
    # Why the simulator needs it, or why it does not.
    reason: str
    stage_id: str | None = None


def _missing(value: SourcedFloat | SourcedInt) -> bool:
    return value.value is None


def concept_gaps(draft: FactoryConceptDraft) -> list[ConceptGap]:
    """Every piece of information this concept is still missing."""
    required: list[ConceptGap] = []
    optional: list[ConceptGap] = []

    # Structural
    if not draft.stages:
        required.append(
            ConceptGap(
                key="stages",
                label="Production route",
                severity=GapSeverity.REQUIRED,
                reason="A route with at least one stage is what the simulation runs units through.",
            )
        )

    if _missing(draft.production_target):
        required.append(
            ConceptGap(
                key="production_target",
                label="Daily production target",
                severity=GapSeverity.REQUIRED,
                reason="The target is the demand the simulation measures output against.",
            )
        )

    # Operating schedule
    if _missing(draft.shifts_per_day):
        required.append(
            ConceptGap(
                key="shifts_per_day",
                label="Shifts per day",
                severity=GapSeverity.REQUIRED,
                reason="Available production time is a direct input to daily output.",
            )
        )
    if _missing(draft.hours_per_shift):
        required.append(
            ConceptGap(
                key="hours_per_shift",
                label="Hours per shift",
                severity=GapSeverity.REQUIRED,
                reason="Available production time is a direct input to daily output.",
            )
        )

    # Workforce
    if _missing(draft.operators_available):
        required.append(
            ConceptGap(
                key="operators_available",
                label="Operators available",
                severity=GapSeverity.REQUIRED,
                reason="Operators are a shared resource the simulation allocates; a station waits without one.",
            )
        )

    # Per stage
    for stage in draft.stages:
        if _missing(stage.cycle_time):
            required.append(
                ConceptGap(
                    key=f"stage.{stage.id}.cycle_time",
                    label=f"{stage.name} cycle time",
                    severity=GapSeverity.REQUIRED,
                    reason="Processing time per unit is the core physical property of a stage.",
                    stage_id=stage.id,
                )
            )
        if _missing(stage.operators_required):
            # REQUIRED, not optional, and for the same reason `cycle_time` is:
            required.append(
                ConceptGap(
                    key=f"stage.{stage.id}.operators_required",
                    label=f"{stage.name} operators required",
                    severity=GapSeverity.REQUIRED,
                    reason=(
                        "The simulator queues work behind the operator pool, so this "
                        "changes throughput. Enter 0 if the station runs unattended."
                    ),
                    stage_id=stage.id,
                )
            )
        if _missing(stage.purchase_cost):
            optional.append(
                ConceptGap(
                    key=f"stage.{stage.id}.purchase_cost",
                    label=f"{stage.name} equipment cost",
                    severity=GapSeverity.OPTIONAL,
                    reason="Commercial only. The simulation reads no price, and an unknown price stays unknown.",
                    stage_id=stage.id,
                )
            )

    # Building / commercial: never blocking
    if _missing(draft.floor_width) or _missing(draft.floor_length):
        # "You did not state a floor size" and "you stated one and
        # Fabrivium could not read it" are different failures, and only the
        # first is honestly reported by an empty value. The golden run hit
        # the second — "30 by 18 metes", one letter short of a unit word —
        # and the floor came back silently unknown beside a production target
        # that had parsed from the same sentence. Fabrivium will not guess
        # what the typo meant; it stops implying nothing was said.
        from app.services.concept_builder import unreadable_floor_phrase

        unread = unreadable_floor_phrase(draft.customer_brief)
        reason = (
            "Needed to place stations and validate the layout. Placement does not affect throughput."
        )
        if unread:
            reason = (
                f'The requirements say "{unread}", which Fabrivium could not read as a floor '
                f"size — check the units and re-enter it. " + reason
            )
        optional.append(
            ConceptGap(
                key="floor_dimensions",
                label="Floor dimensions",
                severity=GapSeverity.OPTIONAL,
                reason=reason,
            )
        )
    if _missing(draft.budget):
        optional.append(
            ConceptGap(
                key="budget",
                label="Capital budget",
                severity=GapSeverity.OPTIONAL,
                reason="Commercial only. Used to constrain options later, never to compute output.",
            )
        )

    return required + optional


def required_gaps(draft: FactoryConceptDraft) -> list[ConceptGap]:
    return [gap for gap in concept_gaps(draft) if gap.severity is GapSeverity.REQUIRED]


# Validation

@dataclass(frozen=True)
class ConceptValidationResult:
    """Whether this concept can be converted and simulated."""

    # True iff no REQUIRED gap remains.
    simulation_ready: bool
    blocking_gaps: list[ConceptGap] = field(default_factory=list)
    optional_gaps: list[ConceptGap] = field(default_factory=list)
    # Structural problems that are not "missing" but "wrong", e.g.
    errors: list[str] = field(default_factory=list)


def _machine_for_stage(stage: ConceptStage) -> Machine:
    """One stage, one station — the default realization, unchanged."""
    assert stage.cycle_time.value is not None
    return Machine(
        id=stage.id,
        name=stage.name,
        process_type=stage.process_type,
        cycle_time=stage.cycle_time.value,
        capacity=stage.capacity.value if stage.capacity.value is not None else DEFAULT_STATION_CAPACITY,
        operators_required=(
            stage.operators_required.value if stage.operators_required.value is not None else 0
        ),
        # Footprint: layout-only, never read by the simulator.
        width=stage.width.value if stage.width.value is not None else DEFAULT_STATION_WIDTH_M,
        length=stage.length.value if stage.length.value is not None else DEFAULT_STATION_LENGTH_M,
        # An unknown price stays UNKNOWN.
        purchase_cost=stage.purchase_cost.value,
    )


def _compile_group(
    group: ConceptOperationGroup, members: list[ConceptStage]
) -> tuple[Machine, ProcessStep]:
    """Several operations on one resource, as one machine and one route step."""
    assert members, "a validated group always has members"
    cycles = [m.cycle_time.value for m in members]
    assert all(c is not None for c in cycles)

    capacities = [m.capacity.value for m in members if m.capacity.value is not None]
    operators = [m.operators_required.value for m in members if m.operators_required.value is not None]
    prices = [m.purchase_cost.value for m in members]

    machine = Machine(
        id=group.id,
        name=group.name,
        # The cell's process type is its first operation's.
        process_type=members[0].process_type,
        cycle_time=sum(cycles),  # type: ignore[arg-type]
        capacity=min(capacities) if capacities else DEFAULT_STATION_CAPACITY,
        operators_required=max(operators) if operators else 0,
        width=sum((m.width.value or DEFAULT_STATION_WIDTH_M) for m in members),
        length=max((m.length.value or DEFAULT_STATION_LENGTH_M) for m in members),
        purchase_cost=sum(prices) if all(p is not None for p in prices) and prices else None,  # type: ignore[arg-type]
    )
    step = ProcessStep(name=group.name, machine_id=group.id, cycle_time=sum(cycles))  # type: ignore[arg-type]
    return machine, step


def operation_group_errors(draft: FactoryConceptDraft) -> list[str]:
    """Everything wrong with the draft's operation groups."""
    groups = draft.operation_groups
    if not groups:
        return []

    errors: list[str] = []
    order = {stage.id: index for index, stage in enumerate(draft.stages)}
    stage_ids = {stage.id for stage in draft.stages}

    seen_group_ids: set[str] = set()
    claimed: dict[str, str] = {}

    for group in groups:
        if group.id in seen_group_ids:
            errors.append(f"Duplicate operation-group id: '{group.id}'.")
        seen_group_ids.add(group.id)

        # A group's id becomes a Machine id. Colliding with a stage id would
        if group.id in stage_ids:
            errors.append(
                f"Operation group '{group.name}' uses the id '{group.id}', which is already "
                f"a stage id. A group's id becomes the resource's id and must be distinct."
            )

        unknown = [sid for sid in group.stage_ids if sid not in stage_ids]
        if unknown:
            errors.append(
                f"Operation group '{group.name}' names stage(s) not in the route: {sorted(unknown)}."
            )
            continue

        for sid in group.stage_ids:
            if sid in claimed:
                errors.append(
                    f"Stage '{sid}' is in two operation groups ('{claimed[sid]}' and "
                    f"'{group.name}'). One operation is performed by one resource."
                )
            claimed[sid] = group.name

        # Contiguity.
        positions = sorted(order[sid] for sid in group.stage_ids)
        if positions != list(range(positions[0], positions[0] + len(positions))):
            names = [draft.stages[p].name for p in positions]
            errors.append(
                f"Operation group '{group.name}' is not a contiguous run of the route "
                f"({', '.join(names)}). A cell performs consecutive operations; a gap would "
                f"mean the unit leaves and returns, which this model does not represent."
            )

    return errors


def validate_concept(draft: FactoryConceptDraft) -> ConceptValidationResult:
    """Validate *draft* without converting it."""
    gaps = concept_gaps(draft)
    blocking = [g for g in gaps if g.severity is GapSeverity.REQUIRED]
    optional = [g for g in gaps if g.severity is GapSeverity.OPTIONAL]

    errors: list[str] = []

    stage_ids = [s.id for s in draft.stages]
    duplicates = {sid for sid in stage_ids if stage_ids.count(sid) > 1}
    if duplicates:
        errors.append(f"Duplicate stage id(s): {sorted(duplicates)}")

    known_ids = set(stage_ids)
    for buffer in draft.buffers:
        if buffer.upstream_stage_id not in known_ids:
            errors.append(
                f"Buffer '{buffer.name}' names an upstream stage that is not in the route: "
                f"'{buffer.upstream_stage_id}'."
            )
        if buffer.downstream_stage_id not in known_ids:
            errors.append(
                f"Buffer '{buffer.name}' names a downstream stage that is not in the route: "
                f"'{buffer.downstream_stage_id}'."
            )

    for stage in draft.stages:
        if stage.cycle_time.value is not None and stage.cycle_time.value <= 0:
            errors.append(f"{stage.name}: cycle time must be greater than zero.")
        if stage.capacity.value is not None and stage.capacity.value < 1:
            errors.append(f"{stage.name}: capacity must be at least 1.")

    if draft.production_target.value is not None and draft.production_target.value <= 0:
        errors.append("Production target must be greater than zero.")

    errors.extend(operation_group_errors(draft))

    return ConceptValidationResult(
        simulation_ready=not blocking and not errors,
        blocking_gaps=blocking,
        optional_gaps=optional,
        errors=errors,
    )


# Conversion

class ConceptNotReadyError(ValueError):
    """
    Raised when conversion is attempted on a concept that is still missing something the
    simulator needs.
    """


def concept_to_factory(draft: FactoryConceptDraft) -> tuple[Factory, str]:
    """Convert a validated *draft* into the existing ``Factory`` model."""
    validation = validate_concept(draft)
    if not validation.simulation_ready:
        missing = ", ".join(gap.label for gap in validation.blocking_gaps)
        problems = "; ".join(validation.errors)
        detail = " | ".join(part for part in (missing, problems) if part)
        raise ConceptNotReadyError(
            f"This concept is not ready to simulate. Still required: {detail}"
        )

    machines: list[Machine] = []
    route: list[ProcessStep] = []

    # Which resource each stage ends up on.
    resource_of: dict[str, str] = {}
    emitted: set[str] = set()

    for stage in draft.stages:
        group = draft.group_for_stage(stage.id)
        if group is None:
            # Guarded by validate_concept above; asserted for the type checker
            # and as a tripwire if the gap rules and this function ever diverge.
            assert stage.cycle_time.value is not None
            resource_of[stage.id] = stage.id
            machines.append(_machine_for_stage(stage))
            route.append(
                ProcessStep(
                    name=stage.name,
                    machine_id=stage.id,
                    cycle_time=stage.cycle_time.value,
                )
            )
            continue

        resource_of[stage.id] = group.id
        if group.id in emitted:
            # A grouped run collapses to ONE resource and ONE route step, so
            # only the first member emits. The rest are already accounted
            # for inside that step's work content.
            continue
        emitted.add(group.id)

        members = [s for s in draft.stages if s.id in group.stage_ids]
        machine, step = _compile_group(group, members)
        machines.append(machine)
        route.append(step)

    buffers: list[Buffer] = []
    for buffer in draft.buffers:
        upstream = resource_of[buffer.upstream_stage_id]
        downstream = resource_of[buffer.downstream_stage_id]
        if upstream == downstream:
            # Both ends are inside one cell.
            continue
        buffers.append(
            Buffer(
                id=buffer.id,
                name=buffer.name,
                capacity=buffer.capacity.value if buffer.capacity.value is not None else DEFAULT_BUFFER_CAPACITY,
                upstream_machine_id=upstream,
                downstream_machine_id=downstream,
            )
        )

    product_id = "p-concept"
    assert draft.production_target.value is not None
    assert draft.shifts_per_day.value is not None
    assert draft.hours_per_shift.value is not None
    assert draft.operators_available.value is not None

    product = Product(
        id=product_id,
        name=draft.product_name,
        # The stated target becomes demand_per_day — the field the existing
        # planning pipeline already reads as "the goal" (audit §5).
        demand_per_day=draft.production_target.value,
        route=route,
    )

    factory = Factory(
        name=draft.name,
        # Floor size is layout-only.
        width=draft.floor_width.value if draft.floor_width.value is not None else _derived_floor_width(draft),
        length=draft.floor_length.value if draft.floor_length.value is not None else _derived_floor_length(draft),
        shifts_per_day=draft.shifts_per_day.value,
        hours_per_shift=draft.hours_per_shift.value,
        operators_available=draft.operators_available.value,
        # An unset budget stays unset.
        budget=draft.budget.value,
        machines=machines,
        products=[product],
        buffers=buffers,
    )
    return factory, product_id


def _station_width(stage: ConceptStage) -> float:
    return stage.width.value if stage.width.value is not None else DEFAULT_STATION_WIDTH_M


def _station_length(stage: ConceptStage) -> float:
    return stage.length.value if stage.length.value is not None else DEFAULT_STATION_LENGTH_M


# Spacing between stations in a generated line (m). Layout only.
STATION_GAP_M = 3.0
# Clear margin kept around the line (m). Layout only.
FLOOR_MARGIN_M = 3.0


def _derived_floor_width(draft: FactoryConceptDraft) -> float:
    """Smallest floor that fits the generated line, when no floor was given."""
    if not draft.stages:
        return 2 * FLOOR_MARGIN_M
    total = sum(_station_width(s) for s in draft.stages)
    total += STATION_GAP_M * max(0, len(draft.stages) - 1)
    return round(total + 2 * FLOOR_MARGIN_M, 3)


def _derived_floor_length(draft: FactoryConceptDraft) -> float:
    if not draft.stages:
        return 2 * FLOOR_MARGIN_M
    deepest = max(_station_length(s) for s in draft.stages)
    return round(deepest + 2 * FLOOR_MARGIN_M, 3)
