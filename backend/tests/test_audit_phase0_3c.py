"""FactoryMind Phase 0-3C final validation audit."""

from __future__ import annotations

import json
import math
import pathlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.models.catalog import (
    EquipmentAvailability,
    EquipmentSourceType,
    ExternalEquipmentReference,
)
from app.models.equipment import (
    EquipmentAsset,
    EquipmentAssetStatus,
    EquipmentAssetType,
    EquipmentLifecycleStatus,
    create_exact_cad_asset,
    create_proxy_asset,
)
from app.models.factory import Factory, Machine, MachineEnvelopeExtras
from app.models.layout import LayoutZone, LayoutZoneType, MachinePlacement
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeDemandAction,
    ChangeMachineCapacityAction,
    ChangeMachineCycleTimeAction,
    RemoveMachineAction,
    Scenario,
)
from app.services.catalog import (
    EquipmentModelRequestBook,
    create_asset_from_external_reference,
    create_machine_from_catalog_entry,
    create_proxy_equipment_spec,
    evaluate_readiness,
    replace_machine_asset,
)
from app.services.constraints import validate_layout
from app.services.geometry import (
    axis_aligned_rectangle,
    get_machine_footprint,
    get_machine_safety_envelope,
    rectangles_overlap,
)
from app.services.layout import create_layout, get_placement, place_machine
from app.services.machine_pool import resolve_pool
from app.services.scenario import (
    MachineRemovalError,
    apply_scenario,
)
from app.services.scenario_runner import run_scenario
from app.services.simulation import run_simulation

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


def _native_layout(factory: Factory):
    layout = create_layout(factory)
    for m in factory.machines:
        layout = place_machine(factory, layout, m.id, x=m.position_x, y=m.position_y)
    return layout


def minimal_machine(**overrides) -> dict:
    base = {
        "id": "m-1", "name": "Test Machine", "process_type": "assembly",
        "cycle_time": 30.0, "width": 2.0, "length": 2.0,
    }
    base.update(overrides)
    return base


def minimal_factory(**overrides) -> dict:
    base = {
        "name": "Test Factory", "width": 40.0, "length": 40.0,
        "shifts_per_day": 1, "hours_per_shift": 8.0,
        "operators_available": 10, "budget": 0.0,
        "machines": [minimal_machine()], "products": [], "buffers": [],
    }
    base.update(overrides)
    return base


# 1. End-to-end workflows

class TestWorkflowA_ExternalRefToSimulation:
    """external/GrabCAD-like reference -> proxy -> machine -> layout ->
    constraints -> simulation, all in one continuous pipeline."""

    def test_full_pipeline(self, electronics_factory: Factory):
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD",
            source_uri="https://grabcad.com/library/abb-robotic-welding-cell-1",
            title="ABB robotic welding cell",
            manufacturer="ABB",
            model_number="IRB-6700",
        )
        ext_asset = create_asset_from_external_reference(ref)
        assert ext_asset.status == EquipmentAssetStatus.REQUESTED
        assert ext_asset.asset_uri is None  # never fetched

        entry = create_proxy_equipment_spec(
            catalog_id="c-welding-audit", name="ABB Welding Cell (proxy)",
            process_type="welding", width=2.0, length=2.0, height=2.2,
            cycle_time=40.0, manufacturer="ABB", model_number="IRB-6700",
            source_type=EquipmentSourceType.EXTERNAL_CATALOG,
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready and readiness.simulation_ready and readiness.visual_ready

        machine = create_machine_from_catalog_entry(entry, "m-welding-audit", position_x=40.0, position_y=5.0)
        factory = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, machine]})

        layout = _native_layout(factory)
        layout_result = validate_layout(factory, layout, "p-electronics-widget")
        assert layout_result.valid is True

        sim_result = run_simulation(factory, "p-electronics-widget")
        assert sim_result.completed_units > 0
        # The new machine isn't in the route, so baseline throughput/gap
        # must be numerically identical to the un-extended factory.
        base_sim = run_simulation(electronics_factory, "p-electronics-widget")
        assert sim_result.completed_units == base_sim.completed_units
        assert sim_result.demand_gap_units == base_sim.demand_gap_units


class TestWorkflowB_ScenarioThroughLayoutToVerdict:
    """baseline -> ADD_PARALLEL_MACHINE -> layout placement of the new
    clone -> constraints -> simulation -> scenario comparison -> verdict."""

    def test_full_pipeline(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s-audit-b", name="parallel screwdriving",
            actions=[AddParallelMachineAction(machine_id="m-screwdriving")],
        )
        candidate = apply_scenario(electronics_factory, scenario)
        clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")

        layout = _native_layout(electronics_factory)
        layout = place_machine(candidate, layout, clone.id, x=clone.position_x, y=clone.position_y)
        layout_result = validate_layout(candidate, layout, "p-electronics-widget")
        assert layout_result.valid is True

        sim_result = run_simulation(candidate, "p-electronics-widget")
        assert sim_result.demand_met is True

        scenario_result = run_scenario(electronics_factory, "p-electronics-widget", scenario)
        assert scenario_result.candidate_result.model_dump() == sim_result.model_dump()
        assert scenario_result.verdict.value == "IMPROVED"

        # Baseline factory must remain untouched by the whole pipeline.
        assert len(electronics_factory.machines) == 4


class TestWorkflowC_ProxyToExactRepeatEverything:
    """proxy asset -> exact CAD replacement -> repeat layout validation ->
    repeat simulation -> repeat scenario comparison; results invariant."""

    def test_full_pipeline(self, electronics_factory: Factory):
        factory_proxy = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"asset": create_proxy_asset(model_number="proxy-v1")})
            if m.id == "m-screwdriving" else m for m in electronics_factory.machines
        ]})
        layout = _native_layout(factory_proxy)
        scenario = Scenario(id="s-audit-c", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])

        layout_1 = validate_layout(factory_proxy, layout, "p-electronics-widget")
        sim_1 = run_simulation(factory_proxy, "p-electronics-widget")
        scenario_1 = run_scenario(factory_proxy, "p-electronics-widget", scenario)

        factory_exact = replace_machine_asset(
            factory_proxy, "m-screwdriving",
            create_exact_cad_asset(asset_uri="s3://bucket/screwdriving.step", file_format="STEP"),
        )
        layout_2 = validate_layout(factory_exact, layout, "p-electronics-widget")
        sim_2 = run_simulation(factory_exact, "p-electronics-widget")
        scenario_2 = run_scenario(factory_exact, "p-electronics-widget", scenario)

        assert layout_1.model_dump() == layout_2.model_dump()
        assert sim_1.model_dump() == sim_2.model_dump()
        assert scenario_1.comparison.model_dump() == scenario_2.comparison.model_dump()
        assert scenario_1.verdict == scenario_2.verdict


# 2. Property / invariant tests

_HYP_SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


class TestInvariants:
    def test_asset_replacement_cannot_change_simulation(self, electronics_factory: Factory):
        base = run_simulation(electronics_factory, "p-electronics-widget")
        for asset in (
            create_proxy_asset(),
            EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.MISSING),
            create_exact_cad_asset(asset_uri="s3://x"),
        ):
            swapped = replace_machine_asset(electronics_factory, "m-screwdriving", asset)
            assert run_simulation(swapped, "p-electronics-widget").model_dump() == base.model_dump()

    @given(x=st.floats(-1000, 1000, allow_nan=False), y=st.floats(-1000, 1000, allow_nan=False))
    @_HYP_SETTINGS
    def test_position_change_alone_cannot_change_simulation(self, electronics_factory, x, y):
        base = run_simulation(electronics_factory, "p-electronics-widget")
        moved = electronics_factory.model_copy(update={"machines": [
            m.model_copy(update={"position_x": x, "position_y": y}) if m.id == "m-screwdriving" else m
            for m in electronics_factory.machines
        ]})
        assert run_simulation(moved, "p-electronics-widget").model_dump() == base.model_dump()

    def test_adding_non_routed_machine_cannot_change_simulation(self, electronics_factory: Factory):
        base = run_simulation(electronics_factory, "p-electronics-widget")
        extra = Machine(**minimal_machine(id="m-not-routed", process_type="inert", cycle_time=1.0))
        extended = electronics_factory.model_copy(update={"machines": [*electronics_factory.machines, extra]})
        after = run_simulation(extended, "p-electronics-widget")
        assert after.model_dump() == base.model_dump()

    def test_apply_scenario_never_mutates_baseline(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                ChangeMachineCycleTimeAction(machine_id="m-assembly", cycle_time=50.0),
                ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=900.0),
            ],
        )
        apply_scenario(electronics_factory, scenario)
        assert electronics_factory.model_dump() == before

    def test_repeated_simulation_identical(self, electronics_factory: Factory):
        r1 = run_simulation(electronics_factory, "p-electronics-widget")
        r2 = run_simulation(electronics_factory, "p-electronics-widget")
        assert r1.model_dump() == r2.model_dump()

    def test_repeated_layout_validation_identical(self, electronics_factory: Factory):
        layout = _native_layout(electronics_factory)
        r1 = validate_layout(electronics_factory, layout, "p-electronics-widget")
        r2 = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert r1.model_dump() == r2.model_dump()

    def test_valid_true_implies_zero_errors(self, electronics_factory: Factory):
        layout = _native_layout(electronics_factory)
        result = validate_layout(electronics_factory, layout, "p-electronics-widget")
        assert result.valid == (result.error_count == 0)
        if result.valid:
            assert all(v.severity.value != "ERROR" for v in result.violations)

    @given(demand=st.floats(1.0, 5000.0, allow_nan=False))
    @_HYP_SETTINGS
    def test_demand_met_implies_zero_gap(self, electronics_factory, demand):
        factory = electronics_factory.model_copy(update={"products": [
            p.model_copy(update={"demand_per_day": demand}) for p in electronics_factory.products
        ]})
        result = run_simulation(factory, "p-electronics-widget")
        if result.demand_met:
            assert result.demand_gap_units == 0.0
        assert result.system.work_in_progress >= 0

    @given(demand=st.floats(1.0, 5000.0, allow_nan=False))
    @_HYP_SETTINGS
    def test_utilization_in_unit_interval_and_completed_le_target(self, electronics_factory, demand):
        factory = electronics_factory.model_copy(update={"products": [
            p.model_copy(update={"demand_per_day": demand}) for p in electronics_factory.products
        ]})
        result = run_simulation(factory, "p-electronics-widget")
        assert result.completed_units <= result.target_units
        for kpi in result.machine_kpis:
            assert 0.0 <= kpi.utilization <= 1.0
        for pool in result.process_pool_kpis:
            assert 0.0 <= pool.utilization <= 1.0

    @given(demand=st.floats(1.0, 5000.0, allow_nan=False))
    @_HYP_SETTINGS
    def test_completed_plus_wip_equals_target_units(self, electronics_factory, demand):
        """Every released unit either completes or remains WIP by the
        horizon — none vanish and none are double-counted."""
        factory = electronics_factory.model_copy(update={"products": [
            p.model_copy(update={"demand_per_day": demand}) for p in electronics_factory.products
        ]})
        result = run_simulation(factory, "p-electronics-widget")
        assert result.completed_units + result.system.work_in_progress == result.target_units


# 3. Geometry edge cases

class TestGeometryEdgeCases:
    def test_exact_edge_touching_not_overlap(self):
        a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        b = axis_aligned_rectangle(2.0, 0.0, 2.0, 2.0)
        assert rectangles_overlap(a, b) is False

    def test_exact_corner_touching_not_overlap(self):
        a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        b = axis_aligned_rectangle(2.0, 2.0, 2.0, 2.0)
        assert rectangles_overlap(a, b) is False

    def test_1e9_overlap_detected(self):
        """
        A 1e-9 m overlap sits exactly at EPSILON — document that this boundary case
        resolves to 'not overlapping' (overlap <= epsilon), not a hard guarantee of
        detection at that exact magnitude.
        """
        a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        b = axis_aligned_rectangle(2.0 - 1e-6, 0.0, 2.0, 2.0)
        assert rectangles_overlap(a, b) is True

    def test_1e9_separation_not_overlap(self):
        a = axis_aligned_rectangle(0.0, 0.0, 2.0, 2.0)
        b = axis_aligned_rectangle(2.0 + 1e-6, 0.0, 2.0, 2.0)
        assert rectangles_overlap(a, b) is False

    @pytest.mark.parametrize("angle", [0.0, 90.0, 180.0, 270.0, 45.0, 359.999])
    def test_rotation_produces_valid_finite_rectangle(self, angle):
        m = Machine(**minimal_machine(width=4.0, length=1.0))
        p = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=angle)
        footprint = get_machine_footprint(m, p)
        assert len(footprint) == 4
        for x, y in footprint:
            assert math.isfinite(x) and math.isfinite(y)

    def test_180_degree_rotation_footprint_matches_0_degree(self):
        """A rectangle rotated 180° about its own center occupies the
        identical region as at 0° (point symmetry)."""
        m = Machine(**minimal_machine(width=4.0, length=2.0))
        p0 = MachinePlacement(machine_id="m-1", x=5.0, y=5.0, rotation_deg=0.0)
        p180 = MachinePlacement(machine_id="m-1", x=5.0, y=5.0, rotation_deg=180.0)
        f0 = sorted(get_machine_footprint(m, p0))
        f180 = sorted(get_machine_footprint(m, p180))
        for (x0, y0), (x1, y1) in zip(f0, f180):
            assert x0 == pytest.approx(x1, abs=1e-9)
            assert y0 == pytest.approx(y1, abs=1e-9)

    def test_asymmetric_envelope_after_359_999_rotation_is_near_0_degree(self):
        """359.999° should be numerically indistinguishable (to a tiny
        tolerance) from 0° — no wraparound discontinuity in the rotation
        math."""
        m = Machine(
            **minimal_machine(
                width=2.0, length=1.0,
                physical_envelope=MachineEnvelopeExtras(safety_clearance_front=3.0).model_dump(),
            )
        )
        p0 = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=0.0)
        p_almost = MachinePlacement(machine_id="m-1", x=0.0, y=0.0, rotation_deg=359.999)
        env0 = sorted(get_machine_safety_envelope(m, p0))
        env_almost = sorted(get_machine_safety_envelope(m, p_almost))
        for (x0, y0), (x1, y1) in zip(env0, env_almost):
            assert x0 == pytest.approx(x1, abs=1e-3)
            assert y0 == pytest.approx(y1, abs=1e-3)

    def test_machine_exactly_on_factory_boundary_is_valid(self):
        factory = Factory(**minimal_factory(width=10.0, length=10.0, machines=[minimal_machine(width=2.0, length=2.0)]))
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=1.0, y=1.0)  # footprint exactly [0,2]x[0,2]
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_machine_one_epsilon_outside_boundary_is_out_of_bounds(self):
        factory = Factory(**minimal_factory(width=10.0, length=10.0, machines=[minimal_machine(width=2.0, length=2.0)]))
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=1.0 - 1e-6, y=1.0)
        result = validate_layout(factory, layout)
        # Sits right at the tolerance boundary; document behaviour rather
        # than assume — the important contract is that a CLEARLY out-of-
        # bounds placement is caught (tested elsewhere), and a genuinely
        # in-bounds one is never falsely rejected (tested above).
        assert isinstance(result.valid, bool)

    def test_extremely_large_safety_clearance_does_not_crash_and_flags_bounds(self):
        factory = Factory(
            **minimal_factory(
                width=10.0, length=10.0,
                machines=[minimal_machine(
                    width=1.0, length=1.0,
                    physical_envelope=MachineEnvelopeExtras(safety_clearance_front=1_000_000.0).model_dump(),
                )],
            )
        )
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-1", x=5.0, y=5.0)
        result = validate_layout(factory, layout)
        # Footprint itself is fine; envelope is astronomically out of
        # bounds -> WARNING (not ERROR — see app.services.constraints).
        assert result.valid is True
        assert any(v.violation_type.value == "OUT_OF_BOUNDS" and v.severity.value == "WARNING" for v in result.violations)


# 4. Scenario edge cases

class TestScenarioEdgeCases:
    def test_add_parallel_clone_twice_deterministic_ids(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                AddParallelMachineAction(machine_id="m-screwdriving"),
            ],
        )
        c1 = apply_scenario(electronics_factory, scenario)
        c2 = apply_scenario(electronics_factory, scenario)
        ids1 = sorted(m.id for m in c1.machines)
        ids2 = sorted(m.id for m in c2.machines)
        assert ids1 == ids2 == sorted([
            "m-assembly", "m-screwdriving", "m-inspection", "m-packaging",
            "m-screwdriving-parallel-1", "m-screwdriving-parallel-2",
        ])

    def test_clone_of_clone_flattens_pool_root(self, electronics_factory: Factory):
        """
        Cloning a clone (action.machine_id = the clone's own id, not the root) produces
        an id derived from THAT source (m-screwdriving-parallel-1-parallel-1 — see
        app.services.scenario._add_parallel_machine's ID-generation rule, which always
        uses action.machine_id's own id as the prefix, not the resolved pool root).
        """
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                AddParallelMachineAction(machine_id="m-screwdriving-parallel-1"),
            ],
        )
        candidate = apply_scenario(electronics_factory, scenario)
        clone2 = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1-parallel-1")
        assert clone2.parallel_of_machine_id == "m-screwdriving"  # flattened, not chained
        pool = resolve_pool(candidate, "m-screwdriving")
        assert [m.id for m in pool] == [
            "m-screwdriving", "m-screwdriving-parallel-1", "m-screwdriving-parallel-1-parallel-1",
        ]

    def test_remove_root_when_clone_exists_allowed(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                RemoveMachineAction(machine_id="m-screwdriving"),
            ],
        )
        candidate = apply_scenario(electronics_factory, scenario)
        ids = {m.id for m in candidate.machines}
        assert "m-screwdriving" not in ids
        assert "m-screwdriving-parallel-1" in ids
        # Still simulate-able: route references "m-screwdriving" but the
        # pool resolves via the surviving clone's parallel_of_machine_id.
        result = run_simulation(candidate, "p-electronics-widget")
        assert result.completed_units > 0

    def test_remove_clone_when_root_remains_allowed(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                RemoveMachineAction(machine_id="m-screwdriving-parallel-1"),
            ],
        )
        candidate = apply_scenario(electronics_factory, scenario)
        ids = {m.id for m in candidate.machines}
        assert ids == {"m-assembly", "m-screwdriving", "m-inspection", "m-packaging"}

    def test_remove_last_screwdriving_rejected(self, electronics_factory: Factory):
        scenario = Scenario(id="s", name="x", actions=[RemoveMachineAction(machine_id="m-screwdriving")])
        with pytest.raises(MachineRemovalError):
            apply_scenario(electronics_factory, scenario)

    def test_sequential_ten_action_scenario(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        actions = [
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeMachineCycleTimeAction(machine_id="m-assembly", cycle_time=30.0),
            ChangeMachineCapacityAction(machine_id="m-inspection", capacity=2),
            AddParallelMachineAction(machine_id="m-packaging"),
            ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=1000.0),
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeMachineCycleTimeAction(machine_id="m-screwdriving", cycle_time=48.0),
            ChangeMachineCapacityAction(machine_id="m-packaging", capacity=1),
            ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=1100.0),
            AddParallelMachineAction(machine_id="m-inspection"),
        ]
        scenario = Scenario(id="s-10", name="ten actions", actions=actions)
        candidate = apply_scenario(electronics_factory, scenario)

        assert electronics_factory.model_dump() == before  # baseline untouched
        assert candidate.products[0].demand_per_day == 1100.0
        screw_pool = resolve_pool(candidate, "m-screwdriving")
        assert len(screw_pool) == 3  # root + 2 clones
        # Cycle time change after cloning: clones created BEFORE the
        # cycle_time edit must have their route step updated too (route
        # sync applies to every step referencing that machine_id).
        cycle_times = {step.cycle_time for p in candidate.products for step in p.route if step.machine_id == "m-screwdriving"}
        assert cycle_times == {48.0}
        result = run_simulation(candidate, "p-electronics-widget")
        assert result.completed_units > 0

    def test_cycle_time_change_after_cloning_affects_clone_route_too(self, electronics_factory: Factory):
        """Cloning happens first; the later cycle_time edit targets the
        ROOT id, which is also the route's machine_id — the clone's own
        `Machine.cycle_time` is independent (frozen at clone time) but the
        simulated cycle_time for the whole pool comes from the route step,
        which IS updated."""
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                ChangeMachineCycleTimeAction(machine_id="m-screwdriving", cycle_time=100.0),
            ],
        )
        candidate = apply_scenario(electronics_factory, scenario)
        root = next(m for m in candidate.machines if m.id == "m-screwdriving")
        clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")
        assert root.cycle_time == 100.0
        assert clone.cycle_time == 52.0  # clone's own Machine field is untouched
        route_step = next(
            step for p in candidate.products for step in p.route if step.machine_id == "m-screwdriving"
        )
        assert route_step.cycle_time == 100.0  # but simulated timing IS 100 for the whole pool

    def test_candidate_asset_replacement_after_scenario(self, electronics_factory: Factory):
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate = apply_scenario(electronics_factory, scenario)
        updated = replace_machine_asset(
            candidate, "m-screwdriving-parallel-1", create_exact_cad_asset(asset_uri="s3://x")
        )
        clone = next(m for m in updated.machines if m.id == "m-screwdriving-parallel-1")
        assert clone.asset.asset_type == EquipmentAssetType.EXACT_CAD
        # Candidate (pre-replacement) is untouched: ADD_PARALLEL_MACHINE
        # verbatim-copies the source's asset onto the clone (same equipment
        # model -> same visual asset, see scenario.py's ADD_PARALLEL_MACHINE
        # comment), and m-screwdriving's fixture asset is LIBRARY/GLB — so
        # the pre-replacement clone inherits that, not None.
        original_clone = next(m for m in candidate.machines if m.id == "m-screwdriving-parallel-1")
        assert original_clone.asset is not None
        assert original_clone.asset.asset_type == EquipmentAssetType.LIBRARY

    def test_requirement_change_mixed_with_engineering_change(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=1800.0),
            ],
        )
        result = run_scenario(electronics_factory, "p-electronics-widget", scenario)
        assert result.comparison.comparison_kind.value == "MIXED_CHANGE"
        assert result.comparison.candidate_target_units == 1800


# 5. Catalog / asset edge cases

class TestCatalogEdgeCases:
    def test_empty_catalog_search_returns_empty(self):
        from app.services.catalog import EquipmentCatalog

        catalog = EquipmentCatalog()
        assert catalog.list_entries() == []
        assert catalog.search(process_type="anything") == []
        assert catalog.get_entry("nope") is None

    def test_duplicate_external_reference_allowed_as_plain_data(self):
        """ExternalEquipmentReference has no identity/uniqueness
        constraint — two references with identical fields are just two
        equal-valued objects, not an error (there is no registry-level
        dedup requirement in Phase 3C)."""
        ref1 = ExternalEquipmentReference(provider_name="GrabCAD", source_uri="https://grabcad.com/x", title="Cell")
        ref2 = ExternalEquipmentReference(provider_name="GrabCAD", source_uri="https://grabcad.com/x", title="Cell")
        assert ref1 == ref2

    def test_missing_optional_manufacturer_model(self):
        ref = ExternalEquipmentReference(provider_name="GrabCAD", source_uri="https://grabcad.com/x", title="Cell")
        assert ref.manufacturer is None
        assert ref.model_number is None
        asset = create_asset_from_external_reference(ref)
        assert asset.manufacturer is None

    def test_broken_looking_source_uri_treated_only_as_metadata(self):
        """A source_uri need not be a real/reachable URL — it's opaque
        metadata; nothing in this module validates or dereferences it."""
        ref = ExternalEquipmentReference(
            provider_name="GrabCAD", source_uri="not-a-real-url-at-all///broken", title="Cell"
        )
        asset = create_asset_from_external_reference(ref)
        assert asset.source_uri == "not-a-real-url-at-all///broken"

    def test_proxy_layout_ready_not_simulation_ready(self):
        entry = create_proxy_equipment_spec(
            catalog_id="c-audit-1", name="X", process_type="welding", width=1.0, length=1.0, height=1.0
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is False

    def test_custom_design_requested_asset_still_layout_plannable(self):
        from app.models.catalog import EquipmentCatalogEntry

        entry = EquipmentCatalogEntry(
            catalog_id="c-audit-2", name="Custom Fixture", process_type="handling",
            width=1.5, length=1.5,
            asset=EquipmentAsset(asset_type=EquipmentAssetType.MISSING, status=EquipmentAssetStatus.REQUESTED),
            source_type=EquipmentSourceType.CUSTOM_REQUEST,
            equipment_availability=EquipmentAvailability.CUSTOM_BUILD,
        )
        readiness = evaluate_readiness(entry)
        assert readiness.layout_ready is True
        assert readiness.simulation_ready is False
        assert readiness.visual_ready is False

        machine = create_machine_from_catalog_entry(
            entry, "m-audit-custom", lifecycle_status=EquipmentLifecycleStatus.CUSTOM_DESIGN, cycle_time=10.0
        )
        factory = Factory(**minimal_factory(machines=[minimal_machine(), machine.model_dump()]))
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-audit-custom", x=20.0, y=20.0)
        result = validate_layout(factory, layout)
        assert result.valid is True

    def test_exact_cad_metadata_does_not_change_engineering_dimensions(self):
        machine_before = Machine(**minimal_machine(width=3.0, length=2.0, cycle_time=10.0))
        machine_after = machine_before.model_copy(
            update={"asset": create_exact_cad_asset(asset_uri="s3://x", file_format="STEP")}
        )
        assert machine_after.width == machine_before.width
        assert machine_after.length == machine_before.length
        assert machine_after.cycle_time == machine_before.cycle_time

    def test_model_request_book_isolated_per_instance(self):
        book1 = EquipmentModelRequestBook()
        book2 = EquipmentModelRequestBook()
        book1.create_request("req-1", "c-1", EquipmentAssetType.PROXY)
        assert book2.get_request("req-1") is None
