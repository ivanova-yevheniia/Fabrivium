"""FactoryMind Phase 3B – deterministic layout constraint engine tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.constraints import ConstraintSeverity, ConstraintType
from app.models.equipment import (
    EquipmentAsset,
    EquipmentAssetStatus,
    EquipmentAssetType,
    EquipmentLifecycleStatus,
    create_proxy_asset,
)
from app.models.factory import Factory, Machine, MachineEnvelopeExtras
from app.models.layout import FactoryLayout, LayoutZone, LayoutZoneType, MachinePlacement
from app.services.constraints import validate_layout
from app.services.geometry import (
    axis_aligned_rectangle,
    get_machine_footprint,
    get_machine_safety_envelope,
    rectangle_within_bounds,
    rectangles_overlap,
)
from app.services.layout import create_layout, place_machine

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


@pytest.fixture
def electronics_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def minimal_machine(**overrides) -> dict:
    base = {
        "id": "m-1",
        "name": "Test Machine",
        "process_type": "assembly",
        "cycle_time": 30.0,
        "width": 2.0,
        "length": 2.0,
    }
    base.update(overrides)
    return base


def minimal_factory(**overrides) -> dict:
    base = {
        "name": "Test Factory",
        "width": 20.0,
        "length": 20.0,
        "shifts_per_day": 1,
        "hours_per_shift": 8.0,
        "operators_available": 10,
        "budget": 0.0,
        "machines": [minimal_machine()],
        "products": [],
        "buffers": [],
    }
    base.update(overrides)
    return base


def _electronics_layout_at_native_positions(factory: Factory) -> FactoryLayout:
    """Place every machine at its own Machine.position_x/position_y —
    matches the electronics_line.json coordinates, which are already
    well-separated."""
    layout = create_layout(factory)
    for m in factory.machines:
        layout = place_machine(factory, layout, m.id, x=m.position_x, y=m.position_y)
    return layout


# 1. geometry.py — pure rectangle math

class TestGeometryFootprint:
    def test_footprint_rot0_matches_width_length(self):
        m = Machine(**minimal_machine(width=4.0, length=2.0))
        p = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=0.0)
        footprint = get_machine_footprint(m, p)
        xs = [c[0] for c in footprint]
        ys = [c[1] for c in footprint]
        assert min(xs) == pytest.approx(-2.0) and max(xs) == pytest.approx(2.0)
        assert min(ys) == pytest.approx(-1.0) and max(ys) == pytest.approx(1.0)

    def test_footprint_rot90_swaps_axes(self):
        m = Machine(**minimal_machine(width=4.0, length=2.0))
        p = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=90.0)
        footprint = get_machine_footprint(m, p)
        xs = [round(c[0], 6) for c in footprint]
        ys = [round(c[1], 6) for c in footprint]
        assert min(xs) == pytest.approx(-1.0) and max(xs) == pytest.approx(1.0)
        assert min(ys) == pytest.approx(-2.0) and max(ys) == pytest.approx(2.0)

    def test_footprint_translated_to_placement_center(self):
        m = Machine(**minimal_machine(width=2.0, length=2.0))
        p = MachinePlacement(machine_id="m-1", x=10.0, y=5.0, rotation_deg=0.0)
        footprint = get_machine_footprint(m, p)
        cx = sum(c[0] for c in footprint) / 4
        cy = sum(c[1] for c in footprint) / 4
        assert cx == pytest.approx(10.0)
        assert cy == pytest.approx(5.0)

    def test_no_physical_envelope_means_zero_clearance(self):
        m = Machine(**minimal_machine(width=2.0, length=2.0))
        p = MachinePlacement(machine_id="m-1", x=0.0, y=0.0)
        footprint = get_machine_footprint(m, p)
        envelope = get_machine_safety_envelope(m, p)
        assert sorted(footprint) == sorted(envelope)


class TestGeometryOverlap:
    def test_touching_edge_is_not_overlap(self):
        rect_a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        rect_b = axis_aligned_rectangle(2.0, 0.0, 2.0, 2.0)
        assert rectangles_overlap(rect_a, rect_b) is False

    def test_touching_corner_is_not_overlap(self):
        rect_a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        rect_b = axis_aligned_rectangle(2.0, 2.0, 2.0, 2.0)
        assert rectangles_overlap(rect_a, rect_b) is False

    def test_slight_overlap_detected(self):
        rect_a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        rect_b = axis_aligned_rectangle(1.9, 0.0, 2.0, 2.0)
        assert rectangles_overlap(rect_a, rect_b) is True

    def test_disjoint_rectangles(self):
        rect_a = axis_aligned_rectangle(0.0, 0.0, 1.0, 1.0)
        rect_b = axis_aligned_rectangle(10.0, 10.0, 1.0, 1.0)
        assert rectangles_overlap(rect_a, rect_b) is False

    def test_one_inside_other(self):
        rect_a = axis_aligned_rectangle(0.0, 0.0, 10.0, 10.0)
        rect_b = axis_aligned_rectangle(4.0, 4.0, 1.0, 1.0)
        assert rectangles_overlap(rect_a, rect_b) is True

    def test_rotated_rectangles_overlap_via_sat(self):
        m = Machine(**minimal_machine(width=2.0, length=2.0))
        p1 = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=45.0)
        p2 = MachinePlacement(machine_id="m-1", x=2.3, y=0.0, rotation_deg=0.0)
        fp1 = get_machine_footprint(m, p1)
        fp2 = get_machine_footprint(m, p2)
        # A 45°-rotated 2x2 square has a diagonal half-extent of sqrt(2)≈1.414,
        # so it reaches x≈1.414 — past the second square's left edge at
        # 2.3-1.0=1.3, so they overlap (a 0°-rotation reading of the first
        # square, reaching only x=1.0, would have missed this).
        assert rectangles_overlap(fp1, fp2) is True

    def test_rotated_rectangles_clear_via_sat(self):
        m = Machine(**minimal_machine(width=2.0, length=2.0))
        p1 = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=45.0)
        p2 = MachinePlacement(machine_id="m-1", x=3.0, y=0.0, rotation_deg=0.0)
        fp1 = get_machine_footprint(m, p1)
        fp2 = get_machine_footprint(m, p2)
        # Second square's left edge at 3.0-1.0=2.0, beyond the rotated
        # square's diagonal reach of ~1.414 — genuinely clear.
        assert rectangles_overlap(fp1, fp2) is False


class TestGeometryBounds:
    def test_inside_bounds(self):
        rect = axis_aligned_rectangle(1.0, 1.0, 2.0, 2.0)
        assert rectangle_within_bounds(rect, 10.0, 10.0) is True

    def test_touching_boundary_is_within_bounds(self):
        rect = axis_aligned_rectangle(0.0, 0.0, 5.0, 5.0)
        assert rectangle_within_bounds(rect, 5.0, 5.0) is True

    def test_extends_past_right_edge(self):
        rect = axis_aligned_rectangle(8.0, 1.0, 5.0, 1.0)
        assert rectangle_within_bounds(rect, 10.0, 10.0) is False

    def test_extends_past_left_edge(self):
        rect = axis_aligned_rectangle(-1.0, 1.0, 2.0, 2.0)
        assert rectangle_within_bounds(rect, 10.0, 10.0) is False


# 2. constraints.py — validate_layout policy

class TestValidLayout:
    def test_well_separated_machines_valid(self, electronics_factory: Factory):
        layout = _electronics_layout_at_native_positions(electronics_factory)
        result = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert result.valid is True
        assert result.error_count == 0
        assert result.violations == []


class TestOutOfBounds:
    @pytest.fixture
    def factory(self) -> Factory:
        return Factory(**minimal_factory())

    def test_past_right_edge(self, factory: Factory):
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=19.5, y=10.0)  # width=2 -> right edge at 20.5
        result = validate_layout(factory, layout)
        assert result.valid is False
        assert any(v.violation_type == ConstraintType.OUT_OF_BOUNDS for v in result.violations)

    def test_past_left_edge(self, factory: Factory):
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=0.5, y=10.0)  # left edge at -0.5
        result = validate_layout(factory, layout)
        assert result.valid is False
        assert result.violations[0].violation_type == ConstraintType.OUT_OF_BOUNDS

    def test_past_top_edge(self, factory: Factory):
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=10.0, y=19.5)
        result = validate_layout(factory, layout)
        assert result.valid is False

    def test_past_bottom_edge(self, factory: Factory):
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=10.0, y=0.5)
        result = validate_layout(factory, layout)
        assert result.valid is False

    def test_exactly_at_boundary_is_valid(self, factory: Factory):
        """Machine footprint edge exactly at x=0/x=20 is allowed (touching
        is fine — see OUT_OF_BOUNDS formula 0 <= x <= factory_width)."""
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=1.0, y=1.0)  # width=2,length=2: [0,2]x[0,2]
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_safety_envelope_out_of_bounds_is_warning_not_error(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_left=5.0).model_dump(),
                    )
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=1.0, y=10.0)  # footprint [0,2] fine, envelope left edge at 1-1-5=-5
        result = validate_layout(factory, layout)
        assert result.valid is True  # WARNING only, not ERROR
        assert any(
            v.violation_type == ConstraintType.OUT_OF_BOUNDS and v.severity == ConstraintSeverity.WARNING
            for v in result.violations
        )


class TestMachineOverlap:
    def test_overlap_detected(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=5.5, y=5.0)
        result = validate_layout(factory, layout)
        assert result.valid is False
        overlap_violations = [v for v in result.violations if v.violation_type == ConstraintType.MACHINE_OVERLAP]
        assert len(overlap_violations) == 1
        assert overlap_violations[0].machine_ids == ["m-a", "m-b"]

    def test_touching_edge_not_overlap(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)  # [4,6]x[4,6]
        layout = place_machine(factory, layout, "m-b", x=7.0, y=5.0)  # [6,8]x[4,6] — touches at x=6
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_no_duplicate_ab_ba_violation(self):
        """Only one MACHINE_OVERLAP entry per unordered pair, never both
        (m-a,m-b) and (m-b,m-a)."""
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=5.5, y=5.0)
        result = validate_layout(factory, layout)
        overlap_violations = [v for v in result.violations if v.violation_type == ConstraintType.MACHINE_OVERLAP]
        assert len(overlap_violations) == 1

    def test_three_machines_only_expected_pairs_reported(self):
        factory = Factory(
            **minimal_factory(
                width=30.0, length=30.0,
                machines=[
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                    minimal_machine(id="m-c", width=2.0, length=2.0),
                ],
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=5.5, y=5.0)  # overlaps m-a
        layout = place_machine(factory, layout, "m-c", x=20.0, y=20.0)  # isolated
        result = validate_layout(factory, layout)
        overlap_violations = [v for v in result.violations if v.violation_type == ConstraintType.MACHINE_OVERLAP]
        assert len(overlap_violations) == 1
        assert overlap_violations[0].machine_ids == ["m-a", "m-b"]


class TestSafetyClearanceOverlap:
    def test_safety_only_overlap_detected(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        id="m-a", width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_right=5.0).model_dump(),
                    ),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)  # footprint [4,6], envelope right to 11
        layout = place_machine(factory, layout, "m-b", x=9.0, y=5.0)  # footprint [8,10] — clear of m-a footprint, inside m-a's envelope
        result = validate_layout(factory, layout)
        assert result.valid is False
        types = [v.violation_type for v in result.violations]
        assert ConstraintType.SAFETY_CLEARANCE_OVERLAP in types
        assert ConstraintType.MACHINE_OVERLAP not in types

    def test_footprint_overlap_not_also_reported_as_safety_overlap(self):
        """When footprints truly overlap, only MACHINE_OVERLAP should be
        reported for that pair — not also/instead SAFETY_CLEARANCE_OVERLAP,
        which would understate the severity."""
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        id="m-a", width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_right=5.0).model_dump(),
                    ),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=5.5, y=5.0)  # footprints DO overlap
        result = validate_layout(factory, layout)
        types = [v.violation_type for v in result.violations if v.machine_ids == ["m-a", "m-b"]]
        assert types == [ConstraintType.MACHINE_OVERLAP]

    def test_own_footprint_never_violates_own_envelope(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_front=5.0).model_dump(),
                    )
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_no_duplicate_safety_violation_for_pair(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        id="m-a", width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(
                            safety_clearance_right=5.0, safety_clearance_left=5.0
                        ).model_dump(),
                    ),
                    minimal_machine(
                        id="m-b", width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(
                            safety_clearance_right=5.0, safety_clearance_left=5.0
                        ).model_dump(),
                    ),
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=9.0, y=5.0)
        result = validate_layout(factory, layout)
        safety_violations = [v for v in result.violations if v.violation_type == ConstraintType.SAFETY_CLEARANCE_OVERLAP]
        assert len(safety_violations) == 1


class TestAisleZone:
    def test_footprint_blocking_aisle_is_error(self):
        factory = Factory(**minimal_factory())
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)  # footprint [4,6]x[4,6]
        layout = layout.model_copy(
            update={
                "aisle_zones": [
                    LayoutZone(id="aisle-1", name="Aisle", x=0.0, y=4.5, width=20.0, length=1.0, zone_type=LayoutZoneType.AISLE)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is False
        v = next(v for v in result.violations if v.violation_type == ConstraintType.AISLE_BLOCKED)
        assert v.severity == ConstraintSeverity.ERROR
        assert v.zone_ids == ["aisle-1"]

    def test_safety_envelope_only_in_aisle_is_warning(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(
                        width=2.0, length=2.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_back=2.0).model_dump(),
                    )
                ]
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)  # footprint [4,6]x[4,6], envelope back to y=2
        # Aisle spans y=[1,3]: overlaps the envelope's y=[2,6] (region
        # [2,3]) but not the footprint's y=[4,6] — envelope-only intrusion.
        layout = layout.model_copy(
            update={
                "aisle_zones": [
                    LayoutZone(id="aisle-1", name="Aisle", x=0.0, y=1.0, width=20.0, length=2.0, zone_type=LayoutZoneType.AISLE)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is True  # WARNING only
        v = next(v for v in result.violations if v.violation_type == ConstraintType.AISLE_BLOCKED)
        assert v.severity == ConstraintSeverity.WARNING


class TestReservedAndSafetyZones:
    def test_reserved_zone_overlap_is_error(self):
        factory = Factory(**minimal_factory())
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        layout = layout.model_copy(
            update={
                "reserved_zones": [
                    LayoutZone(id="r-1", name="Reserved", x=4.0, y=4.0, width=3.0, length=3.0, zone_type=LayoutZoneType.RESERVED)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is False
        v = next(v for v in result.violations if v.violation_type == ConstraintType.RESERVED_ZONE_OVERLAP)
        assert v.zone_ids == ["r-1"]

    def test_safety_zone_overlap_is_error(self):
        factory = Factory(**minimal_factory())
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        layout = layout.model_copy(
            update={
                "reserved_zones": [
                    LayoutZone(id="s-1", name="Safety Zone", x=4.0, y=4.0, width=3.0, length=3.0, zone_type=LayoutZoneType.SAFETY)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is False
        assert any(v.violation_type == ConstraintType.RESERVED_ZONE_OVERLAP for v in result.violations)

    def test_input_output_zone_overlap_is_error(self):
        factory = Factory(**minimal_factory())
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        layout = layout.model_copy(
            update={
                "reserved_zones": [
                    LayoutZone(id="in-1", name="Input Dock", x=4.0, y=4.0, width=3.0, length=3.0, zone_type=LayoutZoneType.INPUT)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is False

    def test_zone_clear_of_all_machines_valid(self):
        factory = Factory(**minimal_factory())
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        layout = layout.model_copy(
            update={
                "reserved_zones": [
                    LayoutZone(id="r-1", name="Reserved", x=15.0, y=15.0, width=2.0, length=2.0, zone_type=LayoutZoneType.RESERVED)
                ]
            }
        )
        result = validate_layout(factory, layout)
        assert result.valid is True


class TestPlacementIntegrity:
    def test_unknown_machine_placement(self):
        factory = Factory(**minimal_factory())
        layout = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[MachinePlacement(machine_id="does-not-exist", x=1.0, y=1.0)],
        )
        result = validate_layout(factory, layout)
        assert result.valid is False
        assert result.violations[0].violation_type == ConstraintType.UNKNOWN_MACHINE

    def test_duplicate_placement(self):
        factory = Factory(**minimal_factory())
        layout = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[
                MachinePlacement(machine_id="m-1", x=1.0, y=1.0),
                MachinePlacement(machine_id="m-1", x=5.0, y=5.0),
            ],
        )
        result = validate_layout(factory, layout)
        assert result.valid is False
        dup = next(v for v in result.violations if v.violation_type == ConstraintType.DUPLICATE_PLACEMENT)
        assert dup.machine_ids == ["m-1"]

    def test_duplicate_placement_does_not_trigger_self_overlap(self):
        """A machine placed twice must never produce a MACHINE_OVERLAP
        violation against itself (machine_ids=['m-1', 'm-1']) — only
        DUPLICATE_PLACEMENT should fire, regardless of whether the two
        duplicate positions happen to be geometrically close."""
        factory = Factory(**minimal_factory())
        layout = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[
                MachinePlacement(machine_id="m-1", x=5.0, y=5.0),
                MachinePlacement(machine_id="m-1", x=5.5, y=5.0),  # overlapping position
            ],
        )
        result = validate_layout(factory, layout)
        assert not any(v.violation_type == ConstraintType.MACHINE_OVERLAP for v in result.violations)
        assert any(v.violation_type == ConstraintType.DUPLICATE_PLACEMENT for v in result.violations)

    def test_routed_machine_missing_placement_is_error(self):
        factory = Factory(
            **minimal_factory(
                products=[
                    {
                        "id": "p-1", "name": "Widget", "demand_per_day": 10.0,
                        "route": [{"name": "Step", "machine_id": "m-1", "cycle_time": 30.0}],
                    }
                ]
            )
        )
        layout = create_layout(factory)  # m-1 never placed
        result = validate_layout(factory, layout, "p-1")
        assert result.valid is False
        v = next(v for v in result.violations if v.violation_type == ConstraintType.MISSING_PLACEMENT)
        assert v.severity == ConstraintSeverity.ERROR
        assert v.machine_ids == ["m-1"]

    def test_non_routed_existing_machine_missing_placement_is_warning(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-1"),
                    minimal_machine(id="m-2", lifecycle_status="EXISTING"),
                ],
                products=[
                    {
                        "id": "p-1", "name": "Widget", "demand_per_day": 10.0,
                        "route": [{"name": "Step", "machine_id": "m-1", "cycle_time": 30.0}],
                    }
                ],
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)  # m-2 stays unplaced
        result = validate_layout(factory, layout, "p-1")
        assert result.valid is True  # WARNING only
        v = next(v for v in result.violations if v.machine_ids == ["m-2"])
        assert v.violation_type == ConstraintType.MISSING_PLACEMENT
        assert v.severity == ConstraintSeverity.WARNING

    def test_purchase_candidate_missing_placement_not_reported(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-1", lifecycle_status="PURCHASE_CANDIDATE"),
                ]
            )
        )
        layout = create_layout(factory)
        result = validate_layout(factory, layout)  # no product_id
        assert result.valid is True
        assert result.violations == []

    def test_no_product_id_all_existing_machines_get_warning_not_error(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)  # nothing placed
        result = validate_layout(electronics_factory, layout)  # no product_id given
        assert result.valid is True  # only warnings, since no route context
        assert all(v.severity == ConstraintSeverity.WARNING for v in result.violations)
        assert len(result.violations) == 4

    def test_unknown_product_id_raises_value_error(self, electronics_factory: Factory):
        layout = create_layout(electronics_factory)
        with pytest.raises(ValueError):
            validate_layout(electronics_factory, layout, "does-not-exist")


# 3. Rotation behaviour

class TestRotationBehaviour:
    @pytest.mark.parametrize("angle", [0.0, 90.0, 180.0, 270.0])
    def test_rotation_preserves_area_and_no_false_overlap_when_clear(self, angle):
        factory = Factory(
            **minimal_factory(
                width=30.0, length=30.0,
                machines=[
                    minimal_machine(id="m-a", width=4.0, length=1.0),
                    minimal_machine(id="m-b", width=4.0, length=1.0),
                ],
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=10.0, y=10.0, rotation_deg=angle)
        layout = place_machine(factory, layout, "m-b", x=20.0, y=20.0, rotation_deg=angle)
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_90_degree_rotation_avoids_overlap_that_0_degree_would_cause(self):
        """A 4x1 machine rotated 90° at x=10 occupies y in [9,11], x in
        [9.5,10.5] — clear of a neighbour at x=12 that a 0°-rotation
        footprint (spanning x in [8,12]) would have collided with."""
        factory = Factory(
            **minimal_factory(
                width=30.0, length=30.0,
                machines=[
                    minimal_machine(id="m-a", width=4.0, length=1.0),
                    minimal_machine(id="m-b", width=1.0, length=1.0),
                ],
            )
        )
        layout_0deg = create_layout(factory)
        layout_0deg = place_machine(factory, layout_0deg, "m-a", x=10.0, y=10.0, rotation_deg=0.0)
        layout_0deg = place_machine(factory, layout_0deg, "m-b", x=12.0, y=10.0)
        assert validate_layout(factory, layout_0deg).valid is False  # overlap at 0deg

        layout_90deg = create_layout(factory)
        layout_90deg = place_machine(factory, layout_90deg, "m-a", x=10.0, y=10.0, rotation_deg=90.0)
        layout_90deg = place_machine(factory, layout_90deg, "m-b", x=12.0, y=10.0)
        assert validate_layout(factory, layout_90deg).valid is True  # clear at 90deg

    def test_asymmetric_clearance_rotates_with_machine(self):
        """A machine with a large front clearance and small back clearance:
        at rot=0 the danger zone is on +Y; at rot=90 it must have rotated
        to -X, not silently stayed on +Y (which would be a geometry bug)."""
        factory = Factory(
            **minimal_factory(
                width=40.0, length=40.0,
                machines=[
                    minimal_machine(
                        id="m-a", width=2.0, length=1.0,
                        physical_envelope=MachineEnvelopeExtras(safety_clearance_front=5.0).model_dump(),
                    ),
                    minimal_machine(id="m-b", width=1.0, length=1.0),
                ],
            )
        )
        # rot=0: front clearance is +Y. Neighbour placed above (+Y) should conflict.
        layout_front = create_layout(factory)
        layout_front = place_machine(factory, layout_front, "m-a", x=10.0, y=10.0, rotation_deg=0.0)
        layout_front = place_machine(factory, layout_front, "m-b", x=10.0, y=13.0)  # +Y of m-a
        result_front = validate_layout(factory, layout_front)
        assert result_front.valid is False
        assert result_front.violations[0].violation_type == ConstraintType.SAFETY_CLEARANCE_OVERLAP

        # Same neighbour position, but m-a now rotated 90° — front clearance
        # has rotated to -X, so the neighbour at +Y of the ORIGINAL position
        # is no longer in the (now differently-oriented) danger zone.
        layout_rotated = create_layout(factory)
        layout_rotated = place_machine(factory, layout_rotated, "m-a", x=10.0, y=10.0, rotation_deg=90.0)
        layout_rotated = place_machine(factory, layout_rotated, "m-b", x=10.0, y=13.0)
        result_rotated = validate_layout(factory, layout_rotated)
        assert result_rotated.valid is True

        # And the danger zone has correctly moved to -X: a neighbour placed
        # there now conflicts.
        layout_rotated_west = create_layout(factory)
        layout_rotated_west = place_machine(factory, layout_rotated_west, "m-a", x=10.0, y=10.0, rotation_deg=90.0)
        layout_rotated_west = place_machine(factory, layout_rotated_west, "m-b", x=6.0, y=10.0)  # -X of m-a
        result_rotated_west = validate_layout(factory, layout_rotated_west)
        assert result_rotated_west.valid is False


# 4. CAD/asset independence

class TestAssetIndependence:
    def test_proxy_vs_exact_cad_identical_validation(self, electronics_factory: Factory):
        layout = _electronics_layout_at_native_positions(electronics_factory)

        data_proxy = electronics_factory.model_dump()
        data_proxy["machines"][1]["asset"] = create_proxy_asset(model_number="proxy-v1").model_dump()
        factory_proxy = Factory.model_validate(data_proxy)

        data_exact = electronics_factory.model_dump()
        data_exact["machines"][1]["asset"] = EquipmentAsset(
            asset_type=EquipmentAssetType.EXACT_CAD,
            status=EquipmentAssetStatus.AVAILABLE,
            asset_uri="s3://bucket/screwdriving-station.step",
        ).model_dump()
        factory_exact = Factory.model_validate(data_exact)

        result_proxy = validate_layout(factory_proxy, layout, "p-electronics-widget")
        result_exact = validate_layout(factory_exact, layout, "p-electronics-widget")
        assert result_proxy.model_dump() == result_exact.model_dump()

    def test_missing_asset_validates_identically_to_proxy(self, electronics_factory: Factory):
        layout = _electronics_layout_at_native_positions(electronics_factory)
        result_missing = validate_layout(electronics_factory, layout, "p-electronics-widget")

        data_proxy = electronics_factory.model_dump()
        data_proxy["machines"][1]["asset"] = create_proxy_asset().model_dump()
        result_proxy = validate_layout(Factory.model_validate(data_proxy), layout, "p-electronics-widget")

        assert result_missing.model_dump() == result_proxy.model_dump()

    def test_lifecycle_status_change_alone_does_not_affect_geometry_result(self, electronics_factory: Factory):
        """Changing lifecycle_status (not placement, not dimensions) must
        not change MACHINE_OVERLAP/SAFETY/AISLE/OUT_OF_BOUNDS results —
        only the (separate) MISSING_PLACEMENT rule reads lifecycle_status."""
        layout = _electronics_layout_at_native_positions(electronics_factory)
        data = electronics_factory.model_dump()
        data["machines"][1]["lifecycle_status"] = "PURCHASE_CANDIDATE"
        factory_changed = Factory.model_validate(data)

        r1 = validate_layout(electronics_factory, layout, "p-electronics-widget")
        r2 = validate_layout(factory_changed, layout, "p-electronics-widget")
        assert r1.violations == r2.violations


# 5. Deterministic ordering / repeated calls

class TestDeterminism:
    def test_repeated_validation_identical(self, electronics_factory: Factory):
        layout = _electronics_layout_at_native_positions(electronics_factory)
        layout = layout.model_copy(update={
            "placements": [
                p.model_copy(update={"x": 5.0, "y": 5.0}) if p.machine_id == "m-screwdriving" else p
                for p in layout.placements
            ]
        })
        r1 = validate_layout(electronics_factory, layout, "p-electronics-widget")
        r2 = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert r1.model_dump() == r2.model_dump()

    def test_violations_sorted_by_severity_then_type(self):
        factory = Factory(
            **minimal_factory(
                width=30.0, length=30.0,
                machines=[
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                    minimal_machine(id="m-c", width=2.0, length=2.0, lifecycle_status="EXISTING"),
                ],
                products=[
                    {
                        "id": "p-1", "name": "Widget", "demand_per_day": 10.0,
                        "route": [{"name": "Step", "machine_id": "m-a", "cycle_time": 30.0}],
                    }
                ],
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-a", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-b", x=5.5, y=5.0)  # MACHINE_OVERLAP (ERROR)
        # m-c: not routed, EXISTING, unplaced -> MISSING_PLACEMENT (WARNING)
        result = validate_layout(factory, layout, "p-1")

        severities = [v.severity for v in result.violations]
        # All ERRORs must precede all WARNINGs.
        assert severities == sorted(severities, key=lambda s: 0 if s == ConstraintSeverity.ERROR else 1)

    def test_machine_pair_order_independent_of_placement_order(self):
        factory = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-b", width=2.0, length=2.0),
                    minimal_machine(id="m-a", width=2.0, length=2.0),
                ]
            )
        )
        layout1 = create_layout(factory)
        layout1 = place_machine(factory, layout1, "m-b", x=5.0, y=5.0)
        layout1 = place_machine(factory, layout1, "m-a", x=5.5, y=5.0)

        layout2 = create_layout(factory)
        layout2 = place_machine(factory, layout2, "m-a", x=5.5, y=5.0)
        layout2 = place_machine(factory, layout2, "m-b", x=5.0, y=5.0)

        r1 = validate_layout(factory, layout1)
        r2 = validate_layout(factory, layout2)
        assert r1.model_dump() == r2.model_dump()
        assert r1.violations[0].machine_ids == ["m-a", "m-b"]


# 6. Required experiments A-F (electronics_line.json)

class TestExperiments:
    @pytest.fixture
    def base_layout(self, electronics_factory: Factory) -> FactoryLayout:
        layout = _electronics_layout_at_native_positions(electronics_factory)
        return layout.model_copy(
            update={
                "aisle_zones": [
                    LayoutZone(id="aisle-1", name="Main Aisle", x=0.0, y=8.5, width=50.0, length=2.0, zone_type=LayoutZoneType.AISLE)
                ]
            }
        )

    def test_A_valid_layout(self, electronics_factory: Factory, base_layout: FactoryLayout):
        result = validate_layout(electronics_factory, base_layout, "p-electronics-widget")
        assert result.valid is True

    def test_B_machine_collision(self, electronics_factory: Factory, base_layout: FactoryLayout):
        layout = base_layout.model_copy(update={
            "placements": [
                p.model_copy(update={"x": 5.0, "y": 5.0}) if p.machine_id == "m-screwdriving" else p
                for p in base_layout.placements
            ]
        })
        result = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert result.valid is False
        assert any(v.violation_type == ConstraintType.MACHINE_OVERLAP for v in result.violations)

    def test_C_safety_violation(self, electronics_factory: Factory, base_layout: FactoryLayout):
        data = electronics_factory.model_dump()
        data["machines"][0]["physical_envelope"] = MachineEnvelopeExtras(safety_clearance_right=5.0).model_dump()
        factory_c = Factory.model_validate(data)
        result = validate_layout(factory_c, base_layout, "p-electronics-widget")
        assert result.valid is False
        assert any(v.violation_type == ConstraintType.SAFETY_CLEARANCE_OVERLAP for v in result.violations)
        assert not any(v.violation_type == ConstraintType.MACHINE_OVERLAP for v in result.violations)

    def test_D_aisle_block(self, electronics_factory: Factory, base_layout: FactoryLayout):
        layout = base_layout.model_copy(update={
            "placements": [
                p.model_copy(update={"y": 8.5}) if p.machine_id == "m-packaging" else p
                for p in base_layout.placements
            ]
        })
        result = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert result.valid is False
        assert any(v.violation_type == ConstraintType.AISLE_BLOCKED for v in result.violations)

    def test_E_out_of_bounds(self, electronics_factory: Factory, base_layout: FactoryLayout):
        layout = base_layout.model_copy(update={
            "placements": [
                p.model_copy(update={"x": 49.0}) if p.machine_id == "m-packaging" else p
                for p in base_layout.placements
            ]
        })
        result = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert result.valid is False
        assert any(
            v.violation_type == ConstraintType.OUT_OF_BOUNDS and v.severity == ConstraintSeverity.ERROR
            for v in result.violations
        )

    def test_F_purchase_candidate_proxy_validates_from_dimensions_only(
        self, electronics_factory: Factory, base_layout: FactoryLayout
    ):
        laser = Machine(
            id="m-laser", name="Laser Welding Cell", process_type="welding",
            cycle_time=45.0, width=3.2, length=2.1, position_x=40.0, position_y=5.0,
            lifecycle_status=EquipmentLifecycleStatus.PURCHASE_CANDIDATE,
            asset=create_proxy_asset(manufacturer="Acme Lasers", model_number="LWC-3200"),
        )
        factory_f = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, laser]})
        layout_f = place_machine(factory_f, base_layout, "m-laser", x=40.0, y=5.0)

        result = validate_layout(factory_f, layout_f, "p-electronics-widget")
        assert result.valid is True  # PROXY, no CAD, still fully valid from dimensions

        laser_exact = laser.model_copy(update={
            "asset": EquipmentAsset(
                asset_type=EquipmentAssetType.EXACT_CAD, status=EquipmentAssetStatus.AVAILABLE,
                asset_uri="s3://bucket/laser.step",
            )
        })
        factory_f_exact = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, laser_exact]})
        result_exact = validate_layout(factory_f_exact, layout_f, "p-electronics-widget")

        assert result.model_dump() == result_exact.model_dump()


# 7. API — POST /layout/validate

class TestLayoutValidateAPI:
    def test_valid_layout_returns_200_and_valid_true(self, client: TestClient, electronics_json: dict):
        factory = Factory.model_validate(electronics_json)
        layout = _electronics_layout_at_native_positions(factory)
        payload = {
            "factory": electronics_json,
            "layout": layout.model_dump(),
            "product_id": "p-electronics-widget",
        }
        resp = client.post("/layout/validate", json=payload)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_invalid_layout_returns_200_with_valid_false(self, client: TestClient, electronics_json: dict):
        factory = Factory.model_validate(electronics_json)
        layout = _electronics_layout_at_native_positions(factory)
        layout = layout.model_copy(update={
            "placements": [
                p.model_copy(update={"x": 5.0, "y": 5.0}) if p.machine_id == "m-screwdriving" else p
                for p in layout.placements
            ]
        })
        payload = {
            "factory": electronics_json,
            "layout": layout.model_dump(),
            "product_id": "p-electronics-widget",
        }
        resp = client.post("/layout/validate", json=payload)
        assert resp.status_code == 200  # NOT an HTTP error — a valid engineering result
        body = resp.json()
        assert body["valid"] is False
        assert body["error_count"] >= 1
        assert any(v["violation_type"] == "MACHINE_OVERLAP" for v in body["violations"])

    def test_bad_factory_returns_422(self, client: TestClient):
        payload = {"factory": {"name": ""}, "layout": {"factory_width": 10.0, "factory_length": 10.0}}
        resp = client.post("/layout/validate", json=payload)
        assert resp.status_code == 422

    def test_bad_layout_returns_422(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "layout": {"factory_width": -1.0, "factory_length": 10.0}}
        resp = client.post("/layout/validate", json=payload)
        assert resp.status_code == 422

    def test_unknown_product_id_returns_400(self, client: TestClient, electronics_json: dict):
        factory = Factory.model_validate(electronics_json)
        layout = create_layout(factory)
        payload = {
            "factory": electronics_json,
            "layout": layout.model_dump(),
            "product_id": "does-not-exist",
        }
        resp = client.post("/layout/validate", json=payload)
        assert resp.status_code == 400

    def test_response_parses_as_layout_validation_result(self, client: TestClient, electronics_json: dict):
        from app.models.constraints import LayoutValidationResult

        factory = Factory.model_validate(electronics_json)
        layout = _electronics_layout_at_native_positions(factory)
        payload = {"factory": electronics_json, "layout": layout.model_dump()}
        resp = client.post("/layout/validate", json=payload)
        result = LayoutValidationResult.model_validate(resp.json())
        assert isinstance(result.valid, bool)

    def test_error_response_has_no_stack_trace(self, client: TestClient, electronics_json: dict):
        factory = Factory.model_validate(electronics_json)
        layout = create_layout(factory)
        payload = {"factory": electronics_json, "layout": layout.model_dump(), "product_id": "does-not-exist"}
        resp = client.post("/layout/validate", json=payload)
        body_text = json.dumps(resp.json())
        assert "Traceback" not in body_text
        assert ".py\"" not in body_text
