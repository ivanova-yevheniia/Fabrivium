"""FactoryMind Phase 2C – scenario comparison / what-if evaluation tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.comparison import ScenarioComparisonKind, Verdict
from app.models.factory import Factory
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeDemandAction,
    ChangeMachineCapacityAction,
    ChangeMachineCycleTimeAction,
    RemoveMachineAction,
    Scenario,
)
from app.models.simulation import MachineKPI, ProcessPoolKPI, SimulationResult, SystemKPI
from app.services.comparison import (
    _safe_percent_change,
    calculate_capex_delta,
    compare_results,
    determine_comparison_kind,
    evaluate_verdict,
)
from app.services.scenario_runner import run_scenario

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


def _make_pool_kpi(**overrides) -> ProcessPoolKPI:
    base = dict(
        process_step_name="Stage",
        reference_machine_id="m-1",
        machine_ids=["m-1"],
        processed_units=100,
        utilization=0.5,
        average_queue_length=0.0,
        max_queue_length=0,
        average_wait_time_seconds=0.0,
        max_wait_time_seconds=0.0,
    )
    base.update(overrides)
    return ProcessPoolKPI(**base)


def _make_machine_kpi(**overrides) -> MachineKPI:
    base = dict(
        machine_id="m-1",
        machine_name="Machine One",
        processed_units=100,
        busy_time_seconds=1000.0,
        utilization=0.5,
        average_queue_length=0.0,
        max_queue_length=0,
        average_wait_time_seconds=0.0,
        max_wait_time_seconds=0.0,
    )
    base.update(overrides)
    return MachineKPI(**base)


def _make_result(
    *,
    completed_units: int = 100,
    throughput_per_hour: float = 10.0,
    demand_met: bool = True,
    demand_gap_units: float = 0.0,
    target_units: int = 100,
    demand_per_day: float = 100.0,
    wip: int = 0,
    average_flow_time_seconds: float = 50.0,
    bottleneck_machine_id: str = "m-1",
    pool_kpis: list[ProcessPoolKPI] | None = None,
    machine_kpis: list[MachineKPI] | None = None,
) -> SimulationResult:
    return SimulationResult(
        simulation_time_seconds=3600.0,
        target_units=target_units,
        nominal_route_time_seconds=10.0,
        release_interval_seconds=1.0,
        completed_units=completed_units,
        throughput_per_hour=throughput_per_hour,
        demand_per_day=demand_per_day,
        demand_met=demand_met,
        demand_gap_units=demand_gap_units,
        machine_kpis=machine_kpis if machine_kpis is not None else [_make_machine_kpi()],
        system=SystemKPI(
            average_flow_time_seconds=average_flow_time_seconds,
            max_flow_time_seconds=average_flow_time_seconds,
            work_in_progress=wip,
            bottleneck_machine_id=bottleneck_machine_id,
        ),
        process_pool_kpis=pool_kpis if pool_kpis is not None else [_make_pool_kpi()],
    )


def _scenario(*actions, id: str = "s-1", name: str = "Test Scenario") -> Scenario:
    return Scenario(id=id, name=name, description="", actions=list(actions))


# 1. compare_results — delta math, safe zero handling

class TestCompareResultsDeltas:
    def test_completed_units_delta(self):
        baseline = _make_result(completed_units=100)
        candidate = _make_result(completed_units=150)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.completed_units_delta == 50
        assert comparison.completed_units_before == 100
        assert comparison.completed_units_after == 150

    def test_throughput_per_hour_delta_and_percent(self):
        baseline = _make_result(throughput_per_hour=10.0)
        candidate = _make_result(throughput_per_hour=15.0)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.throughput_per_hour_delta == pytest.approx(5.0)
        assert comparison.throughput_percent_change == pytest.approx(50.0)

    def test_demand_gap_delta_negative_is_improvement(self):
        baseline = _make_result(demand_gap_units=95.0, demand_met=False)
        candidate = _make_result(demand_gap_units=0.0, demand_met=True)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.demand_gap_delta == pytest.approx(-95.0)
        assert comparison.demand_gap_delta < 0

    def test_wip_delta(self):
        baseline = _make_result(wip=95)
        candidate = _make_result(wip=0)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.wip_delta == -95

    def test_average_flow_time_delta_and_percent(self):
        baseline = _make_result(average_flow_time_seconds=200.0)
        candidate = _make_result(average_flow_time_seconds=100.0)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.average_flow_time_delta_seconds == pytest.approx(-100.0)
        assert comparison.average_flow_time_percent_change == pytest.approx(-50.0)

    def test_bottleneck_before_after_and_changed_flag(self):
        baseline = _make_result(bottleneck_machine_id="m-screwdriving")
        candidate = _make_result(bottleneck_machine_id="m-assembly")
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.bottleneck_before == "m-screwdriving"
        assert comparison.bottleneck_after == "m-assembly"
        assert comparison.bottleneck_changed is True

    def test_bottleneck_unchanged_flag(self):
        baseline = _make_result(bottleneck_machine_id="m-1")
        candidate = _make_result(bottleneck_machine_id="m-1")
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.bottleneck_changed is False

    def test_demand_met_before_after_recorded(self):
        baseline = _make_result(demand_met=False)
        candidate = _make_result(demand_met=True)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.demand_met_before is False
        assert comparison.demand_met_after is True

    def test_target_units_exposed_and_changed_flag(self):
        baseline = _make_result(target_units=1200)
        candidate = _make_result(target_units=800)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.baseline_target_units == 1200
        assert comparison.candidate_target_units == 800
        assert comparison.target_units_changed is True

    def test_target_units_unchanged_flag(self):
        baseline = _make_result(target_units=1200)
        candidate = _make_result(target_units=1200)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.target_units_changed is False

    def test_capex_delta_passed_through(self):
        baseline = _make_result()
        candidate = _make_result()
        comparison = compare_results(baseline, candidate, _scenario(), 85000.0)
        assert comparison.capex_delta == pytest.approx(85000.0)


class TestSafePercentChange:
    def test_normal_case(self):
        assert _safe_percent_change(100.0, 150.0) == pytest.approx(50.0)
        assert _safe_percent_change(100.0, 50.0) == pytest.approx(-50.0)

    def test_zero_baseline_zero_candidate_is_zero(self):
        assert _safe_percent_change(0.0, 0.0) == 0.0

    def test_zero_baseline_nonzero_candidate_is_none(self):
        assert _safe_percent_change(0.0, 5.0) is None

    def test_throughput_percent_change_none_when_baseline_zero(self):
        baseline = _make_result(throughput_per_hour=0.0, completed_units=0)
        candidate = _make_result(throughput_per_hour=5.0, completed_units=50)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.throughput_percent_change is None

    def test_flow_time_percent_change_none_when_baseline_zero(self):
        baseline = _make_result(average_flow_time_seconds=0.0)
        candidate = _make_result(average_flow_time_seconds=10.0)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.average_flow_time_percent_change is None

    def test_throughput_percent_change_zero_when_both_zero(self):
        baseline = _make_result(throughput_per_hour=0.0)
        candidate = _make_result(throughput_per_hour=0.0)
        comparison = compare_results(baseline, candidate, _scenario(), 0.0)
        assert comparison.throughput_percent_change == 0.0


# 2. calculate_capex_delta — Phase 2C CAPEX rules

class TestCapexDelta:
    def test_add_one_parallel_machine(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"))
        capex = calculate_capex_delta(electronics_factory, scenario)
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        assert capex == pytest.approx(source.purchase_cost)
        assert capex == pytest.approx(85000.0)

    def test_add_two_parallel_machines_sums_capex(self, electronics_factory: Factory):
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            AddParallelMachineAction(machine_id="m-screwdriving"),
        )
        capex = calculate_capex_delta(electronics_factory, scenario)
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        assert capex == pytest.approx(2 * source.purchase_cost)

    def test_clone_of_clone_capex_uses_root_purchase_cost(self, electronics_factory: Factory):
        """Cloning an already-added parallel machine still charges the
        ultimate source's purchase_cost (a clone's purchase_cost always
        mirrors its root's)."""
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            AddParallelMachineAction(machine_id="m-screwdriving-parallel-1"),
        )
        capex = calculate_capex_delta(electronics_factory, scenario)
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        assert capex == pytest.approx(2 * source.purchase_cost)

    def test_remove_machine_zero_capex(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-packaging"))
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-packaging"),
            RemoveMachineAction(machine_id="m-packaging"),
        )
        capex = calculate_capex_delta(electronics_factory, scenario)
        source = next(m for m in electronics_factory.machines if m.id == "m-packaging")
        # Only the ADD contributes; REMOVE contributes 0.
        assert capex == pytest.approx(source.purchase_cost)

    def test_change_cycle_time_zero_capex(self, electronics_factory: Factory):
        scenario = _scenario(ChangeMachineCycleTimeAction(machine_id="m-screwdriving", cycle_time=99.0))
        assert calculate_capex_delta(electronics_factory, scenario) == 0.0

    def test_change_capacity_zero_capex(self, electronics_factory: Factory):
        scenario = _scenario(ChangeMachineCapacityAction(machine_id="m-screwdriving", capacity=3))
        assert calculate_capex_delta(electronics_factory, scenario) == 0.0

    def test_change_demand_zero_capex(self, electronics_factory: Factory):
        scenario = _scenario(ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=800.0))
        assert calculate_capex_delta(electronics_factory, scenario) == 0.0

    def test_mixed_scenario_sums_only_applicable_actions(self, electronics_factory: Factory):
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=1600.0),
            ChangeMachineCapacityAction(machine_id="m-assembly", capacity=2),
        )
        capex = calculate_capex_delta(electronics_factory, scenario)
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        assert capex == pytest.approx(source.purchase_cost)

    def test_capex_walk_does_not_mutate_baseline(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"))
        calculate_capex_delta(electronics_factory, scenario)
        assert electronics_factory.model_dump() == before


# 3. determine_comparison_kind

class TestComparisonKind:
    def test_engineering_only(self):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-1"))
        assert determine_comparison_kind(scenario) == ScenarioComparisonKind.ENGINEERING_CHANGE

    def test_demand_only(self):
        scenario = _scenario(ChangeDemandAction(product_id="p-1", demand_per_day=100.0))
        assert determine_comparison_kind(scenario) == ScenarioComparisonKind.REQUIREMENT_CHANGE

    def test_mixed(self):
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-1"),
            ChangeDemandAction(product_id="p-1", demand_per_day=100.0),
        )
        assert determine_comparison_kind(scenario) == ScenarioComparisonKind.MIXED_CHANGE

    def test_mixed_regardless_of_action_order(self):
        scenario = _scenario(
            ChangeDemandAction(product_id="p-1", demand_per_day=100.0),
            AddParallelMachineAction(machine_id="m-1"),
        )
        assert determine_comparison_kind(scenario) == ScenarioComparisonKind.MIXED_CHANGE

    def test_multiple_demand_changes_still_requirement_change(self):
        scenario = _scenario(
            ChangeDemandAction(product_id="p-1", demand_per_day=100.0),
            ChangeDemandAction(product_id="p-1", demand_per_day=200.0),
        )
        assert determine_comparison_kind(scenario) == ScenarioComparisonKind.REQUIREMENT_CHANGE

    def test_empty_scenario_is_engineering_change(self):
        assert determine_comparison_kind(_scenario()) == ScenarioComparisonKind.ENGINEERING_CHANGE


# 4. evaluate_verdict — lexicographic priority, tolerances, determinism

class TestEvaluateVerdict:
    def test_demand_unmet_to_met_is_improved(self):
        baseline = _make_result(demand_met=False, demand_gap_units=95.0, wip=95)
        candidate = _make_result(demand_met=True, demand_gap_units=0.0, wip=0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.IMPROVED
        assert "Demand changed from unmet to met." in reasons

    def test_demand_met_to_unmet_is_degraded(self):
        baseline = _make_result(demand_met=True, demand_gap_units=0.0)
        candidate = _make_result(demand_met=False, demand_gap_units=50.0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.DEGRADED
        assert "Demand changed from met to unmet." in reasons

    def test_both_fail_smaller_gap_improved(self):
        baseline = _make_result(demand_met=False, demand_gap_units=100.0)
        candidate = _make_result(demand_met=False, demand_gap_units=10.0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, _ = evaluate_verdict(comparison)
        assert verdict == Verdict.IMPROVED

    def test_both_fail_larger_gap_degraded(self):
        baseline = _make_result(demand_met=False, demand_gap_units=10.0)
        candidate = _make_result(demand_met=False, demand_gap_units=100.0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, _ = evaluate_verdict(comparison)
        assert verdict == Verdict.DEGRADED

    def test_equal_gap_falls_to_throughput_higher_is_improved(self):
        baseline = _make_result(demand_met=False, demand_gap_units=50.0, completed_units=100)
        candidate = _make_result(demand_met=False, demand_gap_units=50.0, completed_units=120)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.IMPROVED
        assert any("Completed units increased" in r for r in reasons)

    def test_equal_output_lower_wip_is_improved(self):
        baseline = _make_result(demand_met=True, completed_units=100, wip=50, average_flow_time_seconds=100.0)
        candidate = _make_result(demand_met=True, completed_units=100, wip=10, average_flow_time_seconds=100.0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.IMPROVED
        assert any("WIP decreased" in r for r in reasons)

    def test_equal_output_higher_wip_is_degraded(self):
        baseline = _make_result(demand_met=True, completed_units=100, wip=10, average_flow_time_seconds=100.0)
        candidate = _make_result(demand_met=True, completed_units=100, wip=50, average_flow_time_seconds=100.0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.DEGRADED
        assert any("WIP increased" in r for r in reasons)

    def test_truly_identical_is_neutral(self):
        baseline = _make_result()
        candidate = _make_result()
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.NEUTRAL
        assert "No material operational difference detected between baseline and candidate." in reasons

    def test_capex_does_not_flip_improvement_to_degraded(self):
        baseline = _make_result(demand_met=False, demand_gap_units=95.0, wip=95)
        candidate = _make_result(demand_met=True, demand_gap_units=0.0, wip=0)
        comparison = compare_results(
            baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 999999.0
        )
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.IMPROVED
        assert any("CAPEX delta" in r for r in reasons)

    def test_capex_reported_but_neutral_stays_neutral(self):
        baseline = _make_result()
        candidate = _make_result()
        comparison = compare_results(
            baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 45000.0
        )
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.NEUTRAL
        assert any("CAPEX delta: +45000" in r for r in reasons)

    def test_requirement_change_always_neutral_even_when_demand_becomes_met(self):
        baseline = _make_result(demand_met=False, demand_gap_units=95.0, target_units=1200)
        candidate = _make_result(demand_met=True, demand_gap_units=0.0, target_units=800)
        comparison = compare_results(
            baseline, candidate, _scenario(ChangeDemandAction(product_id="p-1", demand_per_day=800.0)), 0.0
        )
        verdict, reasons = evaluate_verdict(comparison)
        assert verdict == Verdict.NEUTRAL
        assert comparison.comparison_kind == ScenarioComparisonKind.REQUIREMENT_CHANGE
        assert not any("improved" in r.lower() for r in reasons)
        assert any("REQUIREMENT_CHANGE" in r for r in reasons)

    def test_deterministic_reasons_repeated_calls_identical(self):
        baseline = _make_result(demand_met=False, demand_gap_units=95.0, wip=95)
        candidate = _make_result(demand_met=True, demand_gap_units=0.0, wip=0)
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        v1, r1 = evaluate_verdict(comparison)
        v2, r2 = evaluate_verdict(comparison)
        assert v1 == v2
        assert r1 == r2

    def test_mixed_change_adds_note_about_target_change(self):
        baseline = _make_result(demand_met=False, demand_gap_units=95.0, wip=95, target_units=1200)
        candidate = _make_result(demand_met=True, demand_gap_units=0.0, wip=0, target_units=1600)
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-1"),
            ChangeDemandAction(product_id="p-1", demand_per_day=1600.0),
        )
        comparison = compare_results(baseline, candidate, scenario, 0.0)
        verdict, reasons = evaluate_verdict(comparison)
        assert comparison.comparison_kind == ScenarioComparisonKind.MIXED_CHANGE
        assert any("MIXED_CHANGE" in r for r in reasons)


# 5. Per-pool comparison

class TestPerPoolComparison:
    def test_pool_matched_by_reference_id_with_deltas(self):
        baseline = _make_result(
            pool_kpis=[
                _make_pool_kpi(
                    reference_machine_id="m-screwdriving",
                    machine_ids=["m-screwdriving"],
                    utilization=0.9994,
                    average_queue_length=46.98,
                    max_queue_length=95,
                    average_wait_time_seconds=2257.39,
                )
            ]
        )
        candidate = _make_result(
            pool_kpis=[
                _make_pool_kpi(
                    reference_machine_id="m-screwdriving",
                    machine_ids=["m-screwdriving", "m-screwdriving-parallel-1"],
                    utilization=0.5417,
                    average_queue_length=0.0,
                    max_queue_length=0,
                    average_wait_time_seconds=0.0,
                )
            ]
        )
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        assert len(comparison.process_pool_comparisons) == 1
        pool = comparison.process_pool_comparisons[0]
        assert pool.reference_machine_id == "m-screwdriving"
        assert pool.machine_ids_before == ["m-screwdriving"]
        assert pool.machine_ids_after == ["m-screwdriving", "m-screwdriving-parallel-1"]
        assert pool.average_queue_before == pytest.approx(46.98)
        assert pool.average_queue_after == pytest.approx(0.0)
        assert pool.average_queue_delta == pytest.approx(-46.98)
        assert pool.average_wait_before == pytest.approx(2257.39)
        assert pool.average_wait_after == pytest.approx(0.0)

    def test_unmatched_pool_skipped_gracefully(self):
        baseline = _make_result(pool_kpis=[_make_pool_kpi(reference_machine_id="m-x")])
        candidate = _make_result(pool_kpis=[_make_pool_kpi(reference_machine_id="m-y")])
        comparison = compare_results(baseline, candidate, _scenario(AddParallelMachineAction(machine_id="m-1")), 0.0)
        assert comparison.process_pool_comparisons == []


# 6. run_scenario — orchestration

class TestRunScenario:
    def test_baseline_immutable_after_run_scenario(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"))
        run_scenario(electronics_factory, "p-electronics-widget", scenario)
        assert electronics_factory.model_dump() == before

    def test_repeated_scenario_result_identical(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"))
        r1 = run_scenario(electronics_factory, "p-electronics-widget", scenario)
        r2 = run_scenario(electronics_factory, "p-electronics-widget", scenario)
        assert r1.model_dump() == r2.model_dump()

    def test_scenario_result_has_scenario_id_and_name(self, electronics_factory: Factory):
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-screwdriving"), id="s-42", name="My Scenario"
        )
        result = run_scenario(electronics_factory, "p-electronics-widget", scenario)
        assert result.scenario_id == "s-42"
        assert result.scenario_name == "My Scenario"

    def test_missing_product_raises_value_error(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"))
        with pytest.raises(ValueError):
            run_scenario(electronics_factory, "does-not-exist", scenario)

    def test_invalid_action_raises_scenario_error(self, electronics_factory: Factory):
        from app.services.scenario import MachineNotFoundError

        scenario = _scenario(AddParallelMachineAction(machine_id="does-not-exist"))
        with pytest.raises(MachineNotFoundError):
            run_scenario(electronics_factory, "p-electronics-widget", scenario)


# 7. Required experiments A-E (electronics_line.json @ 1200/day)

class TestExperimentA_ParallelScrewdriving:
    @pytest.fixture
    def result(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-screwdriving"), id="exp-a", name="Parallel Screwdriving")
        return run_scenario(electronics_factory, "p-electronics-widget", scenario)

    def test_demand_becomes_met(self, result):
        assert result.comparison.demand_met_before is False
        assert result.comparison.demand_met_after is True

    def test_gap_closes_95_to_0(self, result):
        assert result.comparison.demand_gap_units_before == pytest.approx(95.0)
        assert result.comparison.demand_gap_units_after == pytest.approx(0.0)

    def test_wip_drops_95_to_0(self, result):
        assert result.comparison.wip_before == 95
        assert result.comparison.wip_after == 0

    def test_flow_time_falls_strongly(self, result):
        assert result.comparison.average_flow_time_after_seconds < result.comparison.average_flow_time_before_seconds / 2

    def test_screwdriving_pool_congestion_disappears(self, result):
        pool = next(
            p for p in result.comparison.process_pool_comparisons
            if p.reference_machine_id == "m-screwdriving"
        )
        assert pool.average_queue_before > 0
        assert pool.average_queue_after == pytest.approx(0.0)
        assert pool.average_wait_before > 0
        assert pool.average_wait_after == pytest.approx(0.0)

    def test_bottleneck_shifts(self, result):
        assert result.comparison.bottleneck_before == "m-screwdriving"
        assert result.comparison.bottleneck_after != "m-screwdriving"

    def test_verdict_improved(self, result):
        assert result.verdict == Verdict.IMPROVED
        assert result.comparison.comparison_kind == ScenarioComparisonKind.ENGINEERING_CHANGE


class TestExperimentB_ParallelPackaging:
    @pytest.fixture
    def result(self, electronics_factory: Factory):
        scenario = _scenario(AddParallelMachineAction(machine_id="m-packaging"), id="exp-b", name="Parallel Packaging")
        return run_scenario(electronics_factory, "p-electronics-widget", scenario)

    def test_no_material_operational_change(self, result):
        assert result.comparison.completed_units_delta == 0
        assert result.comparison.demand_gap_delta == pytest.approx(0.0)
        assert result.comparison.wip_delta == 0

    def test_capex_positive(self, result):
        assert result.comparison.capex_delta > 0

    def test_verdict_neutral_not_degraded_despite_capex(self, result):
        assert result.verdict == Verdict.NEUTRAL


class TestExperimentC_SlowerScrewdriving:
    @pytest.fixture
    def result(self, electronics_factory: Factory):
        scenario = _scenario(
            ChangeMachineCycleTimeAction(machine_id="m-screwdriving", cycle_time=70.0),
            id="exp-c", name="Slower Screwdriving",
        )
        return run_scenario(electronics_factory, "p-electronics-widget", scenario)

    def test_completed_output_does_not_increase(self, result):
        assert result.comparison.completed_units_after <= result.comparison.completed_units_before

    def test_gap_wip_increase(self, result):
        assert result.comparison.demand_gap_delta > 0
        assert result.comparison.wip_delta > 0

    def test_verdict_degraded(self, result):
        assert result.verdict == Verdict.DEGRADED


class TestExperimentD_ChangeDemandDown:
    @pytest.fixture
    def result(self, electronics_factory: Factory):
        scenario = _scenario(
            ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=800.0),
            id="exp-d", name="Lower demand",
        )
        return run_scenario(electronics_factory, "p-electronics-widget", scenario)

    def test_new_target_met(self, result):
        assert result.comparison.candidate_target_units == 800
        assert result.comparison.demand_met_after is True

    def test_comparison_kind_requirement_change(self, result):
        assert result.comparison.comparison_kind == ScenarioComparisonKind.REQUIREMENT_CHANGE

    def test_does_not_claim_engineering_improvement(self, result):
        assert result.verdict == Verdict.NEUTRAL
        assert not any("factory improved" in r.lower() for r in result.verdict_reasons)
        assert not any(r.lower().startswith("demand changed from unmet to met") for r in result.verdict_reasons)


class TestExperimentE_MixedChange:
    @pytest.fixture
    def result(self, electronics_factory: Factory):
        scenario = _scenario(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeDemandAction(product_id="p-electronics-widget", demand_per_day=1600.0),
            id="exp-e", name="Parallel screwdriving + higher demand",
        )
        return run_scenario(electronics_factory, "p-electronics-widget", scenario)

    def test_comparison_kind_mixed_change(self, result):
        assert result.comparison.comparison_kind == ScenarioComparisonKind.MIXED_CHANGE

    def test_target_units_changed(self, result):
        assert result.comparison.baseline_target_units == 1200
        assert result.comparison.candidate_target_units == 1600

    def test_simulation_determines_demand_met(self, result):
        # Not hard-coded — whatever the simulator measures is authoritative.
        assert isinstance(result.comparison.demand_met_after, bool)


# 8. API — POST /scenario/apply, POST /scenario/run

class TestScenarioApplyAPI:
    def test_valid_request_returns_200(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "scenario": {
                "id": "s-1", "name": "Add parallel screwdriving",
                "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "m-screwdriving"}],
            },
        }
        resp = client.post("/scenario/apply", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        machine_ids = [m["id"] for m in body["machines"]]
        assert "m-screwdriving-parallel-1" in machine_ids
        assert len(body["machines"]) == 5

    def test_bad_factory_returns_422(self, client: TestClient):
        payload = {"factory": {"name": ""}, "scenario": {"id": "s-1", "name": "x", "actions": []}}
        resp = client.post("/scenario/apply", json=payload)
        assert resp.status_code == 422

    def test_bad_scenario_action_returns_422(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "scenario": {"id": "s-1", "name": "x", "actions": [{"action_type": "NOT_A_REAL_ACTION"}]},
        }
        resp = client.post("/scenario/apply", json=payload)
        assert resp.status_code == 422

    def test_missing_machine_returns_400(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "scenario": {
                "id": "s-1", "name": "x",
                "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "does-not-exist"}],
            },
        }
        resp = client.post("/scenario/apply", json=payload)
        assert resp.status_code == 400
        assert "does-not-exist" in resp.json()["detail"]

    def test_error_response_has_no_stack_trace(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "scenario": {
                "id": "s-1", "name": "x",
                "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "does-not-exist"}],
            },
        }
        resp = client.post("/scenario/apply", json=payload)
        body_text = json.dumps(resp.json())
        assert "Traceback" not in body_text
        assert ".py\"" not in body_text


class TestScenarioRunAPI:
    def test_valid_request_returns_200(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "product_id": "p-electronics-widget",
            "scenario": {
                "id": "s-1", "name": "Add parallel screwdriving",
                "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "m-screwdriving"}],
            },
        }
        resp = client.post("/scenario/run", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "IMPROVED"
        assert body["comparison"]["comparison_kind"] == "ENGINEERING_CHANGE"
        assert "baseline_result" in body
        assert "candidate_result" in body

    def test_response_parses_as_scenario_result(self, client: TestClient, electronics_json: dict):
        from app.models.comparison import ScenarioResult

        payload = {
            "factory": electronics_json,
            "product_id": "p-electronics-widget",
            "scenario": {
                "id": "s-1", "name": "x",
                "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "m-packaging"}],
            },
        }
        resp = client.post("/scenario/run", json=payload)
        result = ScenarioResult.model_validate(resp.json())
        assert result.verdict == Verdict.NEUTRAL

    def test_bad_factory_returns_422(self, client: TestClient):
        payload = {
            "factory": {"name": ""},
            "product_id": "p-1",
            "scenario": {"id": "s-1", "name": "x", "actions": []},
        }
        resp = client.post("/scenario/run", json=payload)
        assert resp.status_code == 422

    def test_bad_scenario_returns_422(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "product_id": "p-electronics-widget",
            "scenario": {"id": "s-1", "name": "x", "actions": [{"action_type": "NOPE"}]},
        }
        resp = client.post("/scenario/run", json=payload)
        assert resp.status_code == 422

    def test_missing_product_id_returns_400(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "product_id": "does-not-exist",
            "scenario": {"id": "s-1", "name": "x", "actions": []},
        }
        resp = client.post("/scenario/run", json=payload)
        assert resp.status_code == 400

    def test_unsafe_machine_removal_returns_400(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "product_id": "p-electronics-widget",
            "scenario": {
                "id": "s-1", "name": "x",
                "actions": [{"action_type": "REMOVE_MACHINE", "machine_id": "m-screwdriving"}],
            },
        }
        resp = client.post("/scenario/run", json=payload)
        assert resp.status_code == 400

    def test_error_response_has_no_stack_trace(self, client: TestClient, electronics_json: dict):
        payload = {
            "factory": electronics_json,
            "product_id": "does-not-exist",
            "scenario": {"id": "s-1", "name": "x", "actions": []},
        }
        resp = client.post("/scenario/run", json=payload)
        body_text = json.dumps(resp.json())
        assert "Traceback" not in body_text
        assert ".py\"" not in body_text
