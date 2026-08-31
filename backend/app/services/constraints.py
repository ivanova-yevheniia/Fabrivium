"""Deterministic layout constraint engine for Fabrivium Phase 3B."""

from __future__ import annotations

from app.models.constraints import (
    ConstraintSeverity,
    ConstraintType,
    ConstraintViolation,
    LayoutValidationResult,
)
from app.models.equipment import EquipmentLifecycleStatus
from app.models.factory import Factory, Machine
from app.models.layout import FactoryLayout, LayoutZone, LayoutZoneType, MachinePlacement
from app.services.geometry import (
    axis_aligned_rectangle,
    get_machine_footprint,
    get_machine_safety_envelope,
    rectangle_within_bounds,
    rectangles_overlap,
)

# Zone types treated like RESERVED for Phase 3B (see module docstring):
# there is deliberately no per-zone-kind ConstraintType, and no association
# mechanism yet linking a machine to "its" INPUT/OUTPUT zone.
_BLOCKING_ZONE_TYPES = frozenset(
    {LayoutZoneType.RESERVED, LayoutZoneType.INPUT, LayoutZoneType.OUTPUT, LayoutZoneType.SAFETY}
)

_INSTALLED_LIFECYCLE_STATUSES = frozenset(
    {EquipmentLifecycleStatus.EXISTING, EquipmentLifecycleStatus.INSTALLED}
)


# Public entry point

def validate_layout(
    factory: Factory, layout: FactoryLayout, product_id: str | None = None
) -> LayoutValidationResult:
    """
    Validate *layout* against *factory*, returning a fully typed, deterministic result.
    """
    if product_id is not None and not any(p.id == product_id for p in factory.products):
        raise ValueError(
            f"Product '{product_id}' not found in factory '{factory.name}'. "
            f"Available IDs: {sorted(p.id for p in factory.products)}"
        )

    machine_index: dict[str, Machine] = {m.id: m for m in factory.machines}

    violations: list[ConstraintViolation] = []
    violations.extend(_validate_placement_integrity(factory, layout, product_id, machine_index))
    violations.extend(_validate_bounds(factory, layout, machine_index))
    violations.extend(_validate_machine_pairs(layout, machine_index))
    violations.extend(_validate_zones(layout, machine_index))

    violations = _sort_violations(violations)
    error_count = sum(1 for v in violations if v.severity == ConstraintSeverity.ERROR)
    warning_count = sum(1 for v in violations if v.severity == ConstraintSeverity.WARNING)

    return LayoutValidationResult(
        valid=(error_count == 0),
        error_count=error_count,
        warning_count=warning_count,
        violations=violations,
    )


# Placement integrity: UNKNOWN_MACHINE, DUPLICATE_PLACEMENT, MISSING_PLACEMENT

def _validate_placement_integrity(
    factory: Factory,
    layout: FactoryLayout,
    product_id: str | None,
    machine_index: dict[str, Machine],
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []

    for placement in layout.placements:
        if placement.machine_id not in machine_index:
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.UNKNOWN_MACHINE,
                    severity=ConstraintSeverity.ERROR,
                    message=(
                        f"Placement references machine '{placement.machine_id}', which "
                        f"does not exist in factory '{factory.name}'."
                    ),
                    machine_ids=[placement.machine_id],
                )
            )

    counts: dict[str, int] = {}
    for placement in layout.placements:
        counts[placement.machine_id] = counts.get(placement.machine_id, 0) + 1
    for machine_id, count in counts.items():
        if count > 1:
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.DUPLICATE_PLACEMENT,
                    severity=ConstraintSeverity.ERROR,
                    message=f"Machine '{machine_id}' has {count} placements; exactly one is allowed.",
                    machine_ids=[machine_id],
                )
            )

    placed_ids = {p.machine_id for p in layout.placements}
    required_by_route: set[str] = set()
    if product_id is not None:
        product = next(p for p in factory.products if p.id == product_id)
        required_by_route = {step.machine_id for step in product.route}

    for machine in factory.machines:
        if machine.id in placed_ids:
            continue
        if machine.id in required_by_route:
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.MISSING_PLACEMENT,
                    severity=ConstraintSeverity.ERROR,
                    message=(
                        f"Machine '{machine.id}' is required by product '{product_id}' "
                        f"route but has no placement."
                    ),
                    machine_ids=[machine.id],
                )
            )
        elif machine.lifecycle_status in _INSTALLED_LIFECYCLE_STATUSES:
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.MISSING_PLACEMENT,
                    severity=ConstraintSeverity.WARNING,
                    message=(
                        f"Machine '{machine.id}' (lifecycle_status="
                        f"{machine.lifecycle_status.value}) has no placement."
                    ),
                    machine_ids=[machine.id],
                )
            )
        # else: PURCHASE_CANDIDATE / CUSTOM_DESIGN / ORDERED / APPROVED —
        # not yet physically installed, so having no placement is expected
        # and not reported at all.

    return violations


# Factory bounds

def _validate_bounds(
    factory: Factory, layout: FactoryLayout, machine_index: dict[str, Machine]
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []

    for placement in layout.placements:
        machine = machine_index.get(placement.machine_id)
        if machine is None:
            continue  # reported as UNKNOWN_MACHINE elsewhere

        footprint = get_machine_footprint(machine, placement)
        if not rectangle_within_bounds(footprint, factory.width, factory.length):
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.OUT_OF_BOUNDS,
                    severity=ConstraintSeverity.ERROR,
                    message=(
                        f"Machine '{machine.id}' footprint extends outside the factory "
                        f"floor (0-{factory.width} x 0-{factory.length} m)."
                    ),
                    machine_ids=[machine.id],
                )
            )
            continue  # footprint itself is already the ERROR; skip the softer envelope check

        envelope = get_machine_safety_envelope(machine, placement)
        if not rectangle_within_bounds(envelope, factory.width, factory.length):
            violations.append(
                ConstraintViolation(
                    violation_type=ConstraintType.OUT_OF_BOUNDS,
                    severity=ConstraintSeverity.WARNING,
                    message=(
                        f"Machine '{machine.id}' safety envelope extends outside the "
                        f"factory floor (footprint itself remains inside)."
                    ),
                    machine_ids=[machine.id],
                )
            )

    return violations


# Machine-pair overlap / safety clearance

def _validate_machine_pairs(
    layout: FactoryLayout, machine_index: dict[str, Machine]
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []

    # One placement per machine_id (first in sorted order — deterministic).
    by_machine_id: dict[str, MachinePlacement] = {}
    for p in sorted(layout.placements, key=lambda p: p.machine_id):
        if p.machine_id in machine_index and p.machine_id not in by_machine_id:
            by_machine_id[p.machine_id] = p
    placements = [by_machine_id[mid] for mid in sorted(by_machine_id)]

    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            pa, pb = placements[i], placements[j]
            ma, mb = machine_index[pa.machine_id], machine_index[pb.machine_id]
            pair_ids = sorted([ma.id, mb.id])

            footprint_a = get_machine_footprint(ma, pa)
            footprint_b = get_machine_footprint(mb, pb)

            if rectangles_overlap(footprint_a, footprint_b):
                violations.append(
                    ConstraintViolation(
                        violation_type=ConstraintType.MACHINE_OVERLAP,
                        severity=ConstraintSeverity.ERROR,
                        message=f"Machines '{pair_ids[0]}' and '{pair_ids[1]}' physically overlap.",
                        machine_ids=pair_ids,
                    )
                )
                # Footprint overlap is strictly the more severe finding for
                # this pair; a safety-envelope check would be redundant
                # (the envelope always contains the footprint) and would
                # bury the real issue under a second, weaker-sounding one.
                continue

            envelope_a = get_machine_safety_envelope(ma, pa)
            envelope_b = get_machine_safety_envelope(mb, pb)
            if rectangles_overlap(footprint_a, envelope_b) or rectangles_overlap(footprint_b, envelope_a):
                violations.append(
                    ConstraintViolation(
                        violation_type=ConstraintType.SAFETY_CLEARANCE_OVERLAP,
                        severity=ConstraintSeverity.ERROR,
                        message=(
                            f"Machines '{pair_ids[0]}' and '{pair_ids[1]}' do not "
                            f"physically overlap, but at least one machine's footprint "
                            f"enters the other's safety clearance envelope."
                        ),
                        machine_ids=pair_ids,
                    )
                )

    return violations


# Zones

def _validate_zones(
    layout: FactoryLayout, machine_index: dict[str, Machine]
) -> list[ConstraintViolation]:
    violations: list[ConstraintViolation] = []

    all_zones: list[LayoutZone] = sorted(
        [*layout.reserved_zones, *layout.aisle_zones], key=lambda z: z.id
    )
    placements = sorted(
        (p for p in layout.placements if p.machine_id in machine_index),
        key=lambda p: p.machine_id,
    )

    for placement in placements:
        machine = machine_index[placement.machine_id]
        footprint = get_machine_footprint(machine, placement)
        envelope: list | None = None  # computed lazily; only AISLE needs it

        for zone in all_zones:
            zone_rect = axis_aligned_rectangle(zone.x, zone.y, zone.width, zone.length)

            if zone.zone_type == LayoutZoneType.AISLE:
                if rectangles_overlap(footprint, zone_rect):
                    violations.append(
                        ConstraintViolation(
                            violation_type=ConstraintType.AISLE_BLOCKED,
                            severity=ConstraintSeverity.ERROR,
                            message=f"Machine '{machine.id}' footprint blocks aisle '{zone.id}'.",
                            machine_ids=[machine.id],
                            zone_ids=[zone.id],
                        )
                    )
                    continue
                if envelope is None:
                    envelope = get_machine_safety_envelope(machine, placement)
                if rectangles_overlap(envelope, zone_rect):
                    violations.append(
                        ConstraintViolation(
                            violation_type=ConstraintType.AISLE_BLOCKED,
                            severity=ConstraintSeverity.WARNING,
                            message=(
                                f"Machine '{machine.id}' safety clearance extends into "
                                f"aisle '{zone.id}' (footprint itself is clear)."
                            ),
                            machine_ids=[machine.id],
                            zone_ids=[zone.id],
                        )
                    )

            elif zone.zone_type in _BLOCKING_ZONE_TYPES:
                if rectangles_overlap(footprint, zone_rect):
                    violations.append(
                        ConstraintViolation(
                            violation_type=ConstraintType.RESERVED_ZONE_OVERLAP,
                            severity=ConstraintSeverity.ERROR,
                            message=(
                                f"Machine '{machine.id}' footprint intersects "
                                f"{zone.zone_type.value} zone '{zone.id}'."
                            ),
                            machine_ids=[machine.id],
                            zone_ids=[zone.id],
                        )
                    )

    return violations


# Deterministic ordering

_SEVERITY_ORDER = {ConstraintSeverity.ERROR: 0, ConstraintSeverity.WARNING: 1}
_TYPE_ORDER = {t: i for i, t in enumerate(ConstraintType)}


def _sort_violations(violations: list[ConstraintViolation]) -> list[ConstraintViolation]:
    """Deterministic order: severity, then violation_type (declaration
    order of ``ConstraintType`` — matches the Phase 3B spec's listed
    order), then machine_ids, then zone_ids (both already built pre-sorted
    per-violation, so plain lexicographic list comparison is stable)."""
    return sorted(
        violations,
        key=lambda v: (
            _SEVERITY_ORDER[v.severity],
            _TYPE_ORDER[v.violation_type],
            v.machine_ids,
            v.zone_ids,
        ),
    )
