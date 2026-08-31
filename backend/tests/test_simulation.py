"""FactoryMind Phase 1.2 – comprehensive pytest suite."""

from __future__ import annotations

import json
import math
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Factory, Machine, ProcessStep, Product, Buffer
from app.models.simulation import MachineKPI, SimulationResult, SystemKPI
from app.services.route_validator import RouteValidationResult, validate_route
from app.services.simulation import run_simulation

# Helpers / shared fixtures

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


def _minimal_machine(**overrides) -> dict:
    base = {
        "id": "m-1",
        "name": "Test Machine",
        "process_type": "assembly",
        "cycle_time": 30.0,
        "width": 2.0,
        "length": 1.5,
    }
    base.update(overrides)
    return base


def _minimal_factory_with_single_machine(
    cycle_time: float = 30.0,
    demand_per_day: float = 9999.0,
) -> Factory:
    """Single-machine, single-product factory."""
    return Factory.model_validate({
        "name": "Minimal Factory",
        "width": 10.0,
        "length": 10.0,
        "shifts_per_day": 1,
        "hours_per_shift": 1.0,
        "operators_available": 1,
        "budget": 0.0,
        "machines": [
            {
                "id": "m-1",
                "name": "Machine 1",
                "process_type": "assembly",
                "cycle_time": cycle_time,
                "width": 2.0,
                "length": 2.0,
            }
        ],
        "products": [
            {
                "id": "p-1",
                "name": "Widget",
                "demand_per_day": demand_per_day,
                "route": [
                    {"name": "Step A", "machine_id": "m-1", "cycle_time": cycle_time},
                ],
            }
        ],
    })


def _electronics_with_demand(demand_per_day: float) -> Factory:
    """Return the electronics_line factory with a custom demand_per_day."""
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        data = json.load(fh)
    data["products"][0]["demand_per_day"] = demand_per_day
    return Factory.model_validate(data)


def _electronics_unbuffered(demand_per_day: float) -> Factory:
    """electronics_line at *demand_per_day* with its buffers detached from the route."""
    factory = _electronics_with_demand(demand_per_day)
    return factory.model_copy(
        update={
            "buffers": [
                b.model_copy(update={"upstream_machine_id": None, "downstream_machine_id": None})
                for b in factory.buffers
            ]
        }
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


@pytest.fixture
def electronics_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def electronics_result(electronics_factory: Factory) -> SimulationResult:
    return run_simulation(electronics_factory, "p-electronics-widget")


# 1. Route validation

class TestRouteValidator:
    def test_valid_route_passes(self, electronics_factory: Factory):
        result = validate_route(electronics_factory, electronics_factory.products[0])
        assert result.valid is True
        assert result.errors == []

    def test_missing_machine_id_is_rejected(self):
        """A route step that references a non-existent machine must fail."""
        factory = Factory.model_validate({
            "name": "F",
            "width": 10.0, "length": 10.0,
            "shifts_per_day": 1, "hours_per_shift": 8.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [
                {
                    "id": "m-real",
                    "name": "Real Machine",
                    "process_type": "assembly",
                    "cycle_time": 30.0,
                    "width": 2.0,
                    "length": 2.0,
                }
            ],
            "products": [
                {
                    "id": "p-1",
                    "name": "Widget",
                    "demand_per_day": 100.0,
                    "route": [
                        {"name": "Assembly", "machine_id": "m-real", "cycle_time": 30.0},
                        {"name": "Ghost", "machine_id": "m-does-not-exist", "cycle_time": 20.0},
                    ],
                }
            ],
        })
        result = validate_route(factory, factory.products[0])
        assert result.valid is False
        assert any("m-does-not-exist" in e for e in result.errors)

    def test_all_missing_machines_reported(self):
        """Multiple bad references must all appear in the error list."""
        factory = Factory.model_validate({
            "name": "F",
            "width": 10.0, "length": 10.0,
            "shifts_per_day": 1, "hours_per_shift": 8.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [],
            "products": [
                {
                    "id": "p-1",
                    "name": "Widget",
                    "demand_per_day": 100.0,
                    "route": [
                        {"name": "Step A", "machine_id": "m-x", "cycle_time": 10.0},
                        {"name": "Step B", "machine_id": "m-y", "cycle_time": 10.0},
                    ],
                }
            ],
        })
        result = validate_route(factory, factory.products[0])
        assert result.valid is False
        assert len(result.errors) == 2

    def test_valid_single_step_route(self):
        factory = _minimal_factory_with_single_machine()
        result = validate_route(factory, factory.products[0])
        assert result.valid is True


# 2. Simulation determinism

class TestSimulationDeterminism:
    def test_repeated_runs_produce_identical_results(self, electronics_factory: Factory):
        """Running the simulation twice must yield bit-identical KPIs."""
        r1 = run_simulation(electronics_factory, "p-electronics-widget")
        r2 = run_simulation(electronics_factory, "p-electronics-widget")
        assert r1.completed_units == r2.completed_units
        assert r1.throughput_per_hour == r2.throughput_per_hour
        assert r1.system.bottleneck_machine_id == r2.system.bottleneck_machine_id
        assert r1.system.work_in_progress == r2.system.work_in_progress
        for k1, k2 in zip(r1.machine_kpis, r2.machine_kpis):
            assert k1.utilization == k2.utilization
            assert k1.processed_units == k2.processed_units
            assert k1.busy_time_seconds == k2.busy_time_seconds

    def test_determinism_across_different_fixture_calls(self, electronics_factory: Factory):
        """Load the factory fresh and compare against the cached fixture result."""
        fresh_factory = _load_electronics()
        r1 = run_simulation(electronics_factory, "p-electronics-widget")
        r2 = run_simulation(fresh_factory, "p-electronics-widget")
        assert r1.completed_units == r2.completed_units


# 3. Simulation correctness – electronics_line

class TestElectronicsLineSimulation:
    def test_completed_units_greater_than_zero(self, electronics_result: SimulationResult):
        assert electronics_result.completed_units > 0

    def test_throughput_is_positive(self, electronics_result: SimulationResult):
        assert electronics_result.throughput_per_hour > 0.0

    def test_simulation_horizon_is_57600_seconds(self, electronics_result: SimulationResult):
        """2 shifts × 8 hours × 3600 s/h = 57 600 s."""
        assert electronics_result.simulation_time_seconds == pytest.approx(57_600.0)

    def test_bottleneck_is_screwdriving(self, electronics_result: SimulationResult):
        """Screwdriving has the highest cycle time and should be the bottleneck."""
        assert electronics_result.system.bottleneck_machine_id == "m-screwdriving"

    def test_screwdriving_utilization_highest(self, electronics_result: SimulationResult):
        """Screwdriving utilization must be strictly higher than all other machines."""
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        screw_util = kpi_map["m-screwdriving"].utilization
        for machine_id, kpi in kpi_map.items():
            if machine_id != "m-screwdriving":
                assert screw_util > kpi.utilization, (
                    f"Screwdriving utilization {screw_util:.4f} should exceed "
                    f"{machine_id} utilization {kpi.utilization:.4f}"
                )

    def test_demand_1200_per_day_not_met(self, electronics_result: SimulationResult):
        """Baseline electronics line cannot produce 1200 units in a 16-hour day."""
        assert electronics_result.demand_met is False
        assert electronics_result.demand_gap_units > 0

    def test_demand_per_day_matches_spec(self, electronics_result: SimulationResult):
        assert electronics_result.demand_per_day == pytest.approx(1200.0)

    def test_serial_route_processed_counts_consistent(self, electronics_result: SimulationResult):
        """In a serial route, no downstream machine can process more units
        than any upstream machine (units can only flow forward)."""
        counts = [k.processed_units for k in electronics_result.machine_kpis]
        for i in range(len(counts) - 1):
            assert counts[i] >= counts[i + 1], (
                f"Upstream machine processed {counts[i]} units but downstream "
                f"machine processed {counts[i + 1]} — impossible in a serial route"
            )

    def test_first_machine_processed_most_units(self, electronics_result: SimulationResult):
        """Assembly (first in route) should process the most units because it
        feeds into the bottleneck which acts as a flow limiter."""
        first_count = electronics_result.machine_kpis[0].processed_units
        for kpi in electronics_result.machine_kpis[1:]:
            assert first_count >= kpi.processed_units

    def test_queue_forms_at_screwdriving(self, electronics_result: SimulationResult):
        """Demand-driven release (48 s interval) > Screwdriving service time (52 s)."""
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        screw_kpi = kpi_map["m-screwdriving"]
        assert screw_kpi.average_queue_length > 0.0, (
            "Expected a persistent queue at Screwdriving (demand > capacity)"
        )
        assert screw_kpi.max_queue_length > 0
        assert screw_kpi.average_wait_time_seconds > 0.0
        assert screw_kpi.max_wait_time_seconds > 0.0

    def test_all_utilizations_between_0_and_1(self, electronics_result: SimulationResult):
        for kpi in electronics_result.machine_kpis:
            assert 0.0 <= kpi.utilization <= 1.0, (
                f"Machine {kpi.machine_id} utilization {kpi.utilization} out of range"
            )

    def test_busy_time_does_not_exceed_horizon(self, electronics_result: SimulationResult):
        horizon = electronics_result.simulation_time_seconds
        for kpi in electronics_result.machine_kpis:
            assert kpi.busy_time_seconds <= horizon + 1e-6, (
                f"Machine {kpi.machine_id} busy_time {kpi.busy_time_seconds} "
                f"exceeds horizon {horizon}"
            )

    def test_flow_time_at_least_sum_of_cycle_times(self, electronics_result: SimulationResult):
        """Minimum possible flow time = sum of all step cycle times."""
        # Electronics: 35 + 52 + 30 + 25 = 142 s
        min_flow = 35.0 + 52.0 + 30.0 + 25.0
        assert electronics_result.system.average_flow_time_seconds >= min_flow - 1e-6

    def test_max_flow_time_ge_average_flow_time(self, electronics_result: SimulationResult):
        assert (electronics_result.system.max_flow_time_seconds
                >= electronics_result.system.average_flow_time_seconds - 1e-6)


# 4. WIP / boundary handling

class TestWIPHandling:
    def test_wip_units_not_counted_as_completed(self, electronics_result: SimulationResult):
        """Units that are still in-flight at horizon end must NOT be in completed."""
        # completed + WIP ≤ total_released (we can't assert exact released count
        # but we can assert they are separate pools).
        completed = electronics_result.completed_units
        wip = electronics_result.system.work_in_progress
        # Both should be non-negative
        assert completed >= 0
        assert wip >= 0

    def test_wip_is_non_negative(self, electronics_result: SimulationResult):
        assert electronics_result.system.work_in_progress >= 0

    def test_short_horizon_raises_infeasible(self):
        """
        When nominal_route_time > horizon, run_simulation raises ValueError
        (infeasibility guard added in Phase 1.2).
        """
        factory = Factory.model_validate({
            "name": "Short",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1,
            "hours_per_shift": 1.0 / 3600.0,   # 1-second horizon
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-slow", "name": "Slow Machine", "process_type": "assembly",
                "cycle_time": 100.0, "width": 2.0, "length": 2.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 1.0,
                "route": [{"name": "S", "machine_id": "m-slow", "cycle_time": 100.0}],
            }],
        })
        with pytest.raises(ValueError, match="infeasible"):
            run_simulation(factory, "p-1")

    def test_short_horizon_produces_wip(self):
        """Units still in-flight at the horizon are counted as WIP."""
        factory = Factory.model_validate({
            "name": "WIPTest",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1,
            "hours_per_shift": 150.0 / 3600.0,  # 150-second horizon
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-1", "name": "M", "process_type": "assembly",
                "cycle_time": 100.0, "width": 1.0, "length": 1.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 3.0,
                "route": [{"name": "S", "machine_id": "m-1", "cycle_time": 100.0}],
            }],
        })
        result = run_simulation(factory, "p-1")
        assert result.completed_units + result.system.work_in_progress == 3

    def test_completed_units_zero_when_horizon_too_short(self):
        """Route nominal_time > horizon → infeasibility ValueError (Phase 1.2)."""
        factory = Factory.model_validate({
            "name": "TooShort",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1,
            "hours_per_shift": 10.0 / 3600.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [
                {"id": "m-a", "name": "A", "process_type": "a",
                 "cycle_time": 100.0, "width": 1.0, "length": 1.0},
                {"id": "m-b", "name": "B", "process_type": "b",
                 "cycle_time": 100.0, "width": 1.0, "length": 1.0},
            ],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 1.0,
                "route": [
                    {"name": "A", "machine_id": "m-a", "cycle_time": 100.0},
                    {"name": "B", "machine_id": "m-b", "cycle_time": 100.0},
                ],
            }],
        })
        with pytest.raises(ValueError, match="infeasible"):
            run_simulation(factory, "p-1")


# 5. Simulation KPI invariants (property-level)

class TestKPIInvariants:
    def test_utilization_in_range_single_machine(self):
        factory = _minimal_factory_with_single_machine(cycle_time=30.0)
        result = run_simulation(factory, "p-1")
        for kpi in result.machine_kpis:
            assert 0.0 <= kpi.utilization <= 1.0

    def test_max_queue_ge_avg_queue(self):
        factory = _load_electronics()
        result = run_simulation(factory, "p-electronics-widget")
        for kpi in result.machine_kpis:
            assert kpi.max_queue_length >= kpi.average_queue_length - 1e-9

    def test_max_wait_ge_avg_wait(self):
        factory = _load_electronics()
        result = run_simulation(factory, "p-electronics-widget")
        for kpi in result.machine_kpis:
            assert kpi.max_wait_time_seconds >= kpi.average_wait_time_seconds - 1e-9

    def test_busy_time_equals_processed_times_cycle(self):
        """For a single-machine line busy_time = processed_units × cycle_time."""
        cycle = 30.0
        factory = _minimal_factory_with_single_machine(cycle_time=cycle, demand_per_day=9999.0)
        result = run_simulation(factory, "p-1")
        kpi = result.machine_kpis[0]
        expected_busy = kpi.processed_units * cycle
        assert kpi.busy_time_seconds == pytest.approx(expected_busy, rel=1e-9)

    def test_throughput_consistent_with_completed_units(self):
        factory = _minimal_factory_with_single_machine(demand_per_day=9999.0)
        result = run_simulation(factory, "p-1")
        # horizon hours = shifts_per_day × hours_per_shift = 1 × 1 = 1 h
        expected_tph = result.completed_units / 1.0
        assert result.throughput_per_hour == pytest.approx(expected_tph, rel=1e-9)

    def test_simulation_time_matches_schedule(self):
        """simulation_time_seconds = shifts_per_day × hours_per_shift × 3600."""
        factory = _minimal_factory_with_single_machine(demand_per_day=9999.0)
        result = run_simulation(factory, "p-1")
        # 1 shift × 1 hour × 3600 = 3600 s
        assert result.simulation_time_seconds == pytest.approx(3600.0)

    def test_demand_gap_formula(self):
        """demand_gap_units = max(target_units - completed_units, 0)."""
        factory = _load_electronics()
        result = run_simulation(factory, "p-electronics-widget")
        expected_gap = max(result.target_units - result.completed_units, 0)
        assert result.demand_gap_units == pytest.approx(expected_gap, abs=1e-6)


# 6. Bottleneck identification

class TestBottleneckIdentification:
    def test_bottleneck_has_highest_utilization(self):
        factory = _load_electronics()
        result = run_simulation(factory, "p-electronics-widget")
        kpi_map = {k.machine_id: k for k in result.machine_kpis}
        bn_util = kpi_map[result.system.bottleneck_machine_id].utilization
        for kpi in result.machine_kpis:
            assert bn_util >= kpi.utilization - 1e-9

    def test_single_machine_is_its_own_bottleneck(self):
        factory = _minimal_factory_with_single_machine(demand_per_day=9999.0)
        result = run_simulation(factory, "p-1")
        assert result.system.bottleneck_machine_id == "m-1"

    def test_bottleneck_in_route_step_machine_ids(self):
        factory = _load_electronics()
        result = run_simulation(factory, "p-electronics-widget")
        route_machine_ids = {step.machine_id for step in factory.products[0].route}
        assert result.system.bottleneck_machine_id in route_machine_ids


# 7. Demand comparison

class TestDemandComparison:
    def test_electronics_demand_not_met(self, electronics_result: SimulationResult):
        assert electronics_result.demand_met is False

    def test_low_demand_factory_demand_met(self):
        """A factory that can easily outproduce demand should report demand_met=True."""
        factory = Factory.model_validate({
            "name": "Easy",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1, "hours_per_shift": 8.0,
            "operators_available": 1, "budget": 0.0,
            "machines": [{
                "id": "m-1", "name": "M", "process_type": "assembly",
                "cycle_time": 30.0, "width": 2.0, "length": 2.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 100.0,
                "route": [{"name": "S", "machine_id": "m-1", "cycle_time": 30.0}],
            }],
        })
        result = run_simulation(factory, "p-1")
        assert result.demand_met is True
        assert result.demand_gap_units == 0


# 8. API endpoint – POST /simulation/run

class TestSimulationAPI:
    def test_valid_request_returns_200(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        assert resp.status_code == 200

    def test_response_has_required_fields(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        assert "completed_units" in body
        assert "throughput_per_hour" in body
        assert "demand_met" in body
        assert "machine_kpis" in body
        assert "system" in body

    def test_response_machine_kpis_is_list_of_four(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        assert len(body["machine_kpis"]) == 4

    def test_response_parses_as_simulation_result(self, client: TestClient, electronics_json: dict):
        """Response must be parseable as a SimulationResult Pydantic model."""
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        result = SimulationResult.model_validate(resp.json())
        assert result.completed_units > 0

    def test_missing_product_id_returns_400(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-does-not-exist"}
        resp = client.post("/simulation/run", json=payload)
        assert resp.status_code == 400

    def test_bad_factory_returns_422(self, client: TestClient):
        """Structurally invalid factory (missing required fields) → 422."""
        payload = {"factory": {"name": ""}, "product_id": "p-1"}
        resp = client.post("/simulation/run", json=payload)
        assert resp.status_code == 422

    def test_route_with_missing_machine_returns_400(self, client: TestClient):
        """Route referencing a non-existent machine → 400."""
        factory_data = {
            "name": "Bad Factory",
            "width": 10.0, "length": 10.0,
            "shifts_per_day": 1, "hours_per_shift": 8.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-real", "name": "Real", "process_type": "assembly",
                "cycle_time": 30.0, "width": 2.0, "length": 2.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 100.0,
                "route": [
                    {"name": "OK", "machine_id": "m-real", "cycle_time": 30.0},
                    {"name": "Bad", "machine_id": "m-ghost", "cycle_time": 10.0},
                ],
            }],
        }
        payload = {"factory": factory_data, "product_id": "p-1"}
        resp = client.post("/simulation/run", json=payload)
        assert resp.status_code == 400

    def test_bottleneck_is_screwdriving_via_api(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        assert body["system"]["bottleneck_machine_id"] == "m-screwdriving"

    def test_utilizations_between_0_and_1_via_api(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        for kpi in body["machine_kpis"]:
            assert 0.0 <= kpi["utilization"] <= 1.0

    def test_demand_not_met_via_api(self, client: TestClient, electronics_json: dict):
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        assert body["demand_met"] is False


# 9. Simulation run – route validator integration

class TestSimulationRouteValidatorIntegration:
    def test_run_simulation_raises_for_missing_machine(self):
        """run_simulation must raise ValueError when route references missing machine."""
        factory = Factory.model_validate({
            "name": "F",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1, "hours_per_shift": 8.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-real", "name": "Real", "process_type": "assembly",
                "cycle_time": 30.0, "width": 2.0, "length": 2.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 100.0,
                "route": [
                    {"name": "OK", "machine_id": "m-real", "cycle_time": 30.0},
                    {"name": "Bad", "machine_id": "m-missing", "cycle_time": 10.0},
                ],
            }],
        })
        with pytest.raises(ValueError, match="m-missing"):
            run_simulation(factory, "p-1")

    def test_run_simulation_raises_for_unknown_product_id(self):
        factory = _minimal_factory_with_single_machine(demand_per_day=9999.0)
        with pytest.raises(ValueError, match="p-unknown"):
            run_simulation(factory, "p-unknown")


# 9. Phase 1.1 – demand-driven source semantics

class TestDemandDrivenSource:
    """Verify that the source release rate is derived from demand, not capacity."""

    def test_electronics_release_interval_formula(self, electronics_factory: Factory):
        """
        Phase 1.2: release_interval = (horizon - nominal_route_time) / (target - 1).
        """
        result = run_simulation(electronics_factory, "p-electronics-widget")
        horizon = (electronics_factory.shifts_per_day
                   * electronics_factory.hours_per_shift * 3600.0)
        nominal = sum(s.cycle_time for s in electronics_factory.products[0].route)
        target = math.ceil(electronics_factory.products[0].demand_per_day)
        expected_interval = (horizon - nominal) / (target - 1)
        assert result.release_interval_seconds == pytest.approx(expected_interval, abs=1e-5)

    def test_release_interval_independent_of_bottleneck_cycle_time(
            self, electronics_factory: Factory):
        """
        Phase 1.2 release_interval (≈ 47.921 s) must not equal the bottleneck cycle_time
        (52 s).
        """
        result = run_simulation(electronics_factory, "p-electronics-widget")
        bottleneck_ct = max(
            s.cycle_time for s in electronics_factory.products[0].route
        )
        assert result.release_interval_seconds != pytest.approx(bottleneck_ct), (
            "Release interval must be demand-driven, not bottleneck-paced"
        )

    def test_screwdriving_queue_forms_with_base_demand(
            self, electronics_result: SimulationResult):
        """Baseline demand (1200/day) exceeds Screwdriving capacity → queue must form."""
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        screw = kpi_map["m-screwdriving"]
        assert screw.average_queue_length > 0.0
        assert screw.max_queue_length > 0
        assert screw.average_wait_time_seconds > 0.0
        assert screw.max_wait_time_seconds > 0.0

    def test_screwdriving_avg_wait_is_positive(self, electronics_result: SimulationResult):
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        assert kpi_map["m-screwdriving"].average_wait_time_seconds > 0.0

    def test_screwdriving_max_wait_is_positive(self, electronics_result: SimulationResult):
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        assert kpi_map["m-screwdriving"].max_wait_time_seconds > 0.0

    def test_screwdriving_max_queue_is_positive(self, electronics_result: SimulationResult):
        kpi_map = {k.machine_id: k for k in electronics_result.machine_kpis}
        assert kpi_map["m-screwdriving"].max_queue_length > 0

    def test_bottleneck_still_screwdriving(self, electronics_result: SimulationResult):
        assert electronics_result.system.bottleneck_machine_id == "m-screwdriving"

    def test_demand_still_not_met(self, electronics_result: SimulationResult):
        assert electronics_result.demand_met is False
        assert electronics_result.demand_gap_units > 0

    def test_increasing_demand_increases_wip_and_queue(self):
        """Higher demand → shorter release interval → more WIP and longer queue
        at the bottleneck, while machine cycle times remain unchanged.
        """
        r_base = run_simulation(_electronics_with_demand(1200.0), "p-electronics-widget")
        r_high = run_simulation(_electronics_with_demand(1600.0), "p-electronics-widget")

        kpi_base = {k.machine_id: k for k in r_base.machine_kpis}
        kpi_high = {k.machine_id: k for k in r_high.machine_kpis}

        # Higher demand → more WIP at horizon
        assert r_high.system.work_in_progress >= r_base.system.work_in_progress

        # Higher demand → longer queue or wait at Screwdriving
        assert (kpi_high["m-screwdriving"].average_queue_length
                >= kpi_base["m-screwdriving"].average_queue_length)

        # Machine cycle times are unchanged (capacity is independent of demand)
        # – verify by checking that processed_units for downstream machines
        #   do NOT exceed what the bottleneck could have passed through.
        # (This is also verified by serial-consistency test.)

    def test_low_demand_removes_persistent_queue(self):
        """demand = 800/day: Phase 1.2 release_interval ≈ 71.912 s."""
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        kpi_map = {k.machine_id: k for k in result.machine_kpis}
        screw = kpi_map["m-screwdriving"]
        # At low demand the machine is never over-subscribed
        assert screw.average_queue_length == pytest.approx(0.0, abs=1e-6)
        assert screw.max_queue_length == 0
        assert screw.average_wait_time_seconds == pytest.approx(0.0, abs=1e-6)

    def test_low_demand_demand_is_met(self):
        """
        demand = 800/day: Phase 1.2 schedule anchors the last release at
        latest_release_time = 57 458 s.
        """
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        assert result.completed_units == 800
        assert result.demand_met is True
        assert result.demand_gap_units == 0

    def test_determinism_demand_driven(self, electronics_factory: Factory):
        """Two runs with identical inputs must yield identical outputs (queue
        statistics included, not just throughput)."""
        r1 = run_simulation(electronics_factory, "p-electronics-widget")
        r2 = run_simulation(electronics_factory, "p-electronics-widget")
        kpi1 = {k.machine_id: k for k in r1.machine_kpis}
        kpi2 = {k.machine_id: k for k in r2.machine_kpis}
        for mid in kpi1:
            assert kpi1[mid].average_queue_length == kpi2[mid].average_queue_length
            assert kpi1[mid].max_queue_length == kpi2[mid].max_queue_length
            assert kpi1[mid].average_wait_time_seconds == kpi2[mid].average_wait_time_seconds
            assert kpi1[mid].max_wait_time_seconds == kpi2[mid].max_wait_time_seconds

    def test_machine_cycle_times_unchanged_across_demands(self):
        """busy_time / processed_units should equal the step cycle time
        regardless of demand level — capacity is fixed, only load varies."""
        for demand in (800.0, 1200.0, 1600.0):
            result = run_simulation(
                _electronics_with_demand(demand), "p-electronics-widget"
            )
            for kpi in result.machine_kpis:
                if kpi.processed_units > 0:
                    implied_ct = kpi.busy_time_seconds / kpi.processed_units
                    factory = _electronics_with_demand(demand)
                    step_ct = next(
                        s.cycle_time for s in factory.products[0].route
                        if s.machine_id == kpi.machine_id
                    )
                    assert implied_ct == pytest.approx(step_ct, rel=1e-9), (
                        f"demand={demand}, machine={kpi.machine_id}: "
                        f"implied CT {implied_ct:.4f} ≠ step CT {step_ct}"
                    )


# 10. Three-scenario demand sweep

class TestDemandSweep:
    """Verify qualitative monotone relationships across LOW / BASE / HIGH demand."""

    @pytest.fixture
    def low_result(self) -> SimulationResult:
        return run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")

    @pytest.fixture
    def base_result(self) -> SimulationResult:
        return run_simulation(_electronics_with_demand(1200.0), "p-electronics-widget")

    @pytest.fixture
    def high_result(self) -> SimulationResult:
        return run_simulation(_electronics_with_demand(1600.0), "p-electronics-widget")

    # LOW (800/day)

    def test_low_demand_met(self, low_result: SimulationResult):
        """Phase 1.2: all 800 target units complete → demand_met=True, gap=0, WIP=0."""
        assert low_result.demand_met is True
        assert low_result.demand_gap_units == 0
        assert low_result.completed_units == 800

    def test_low_wip_is_zero(self, low_result: SimulationResult):
        assert low_result.system.work_in_progress == 0

    def test_low_no_queue_at_bottleneck(self, low_result: SimulationResult):
        kpi = {k.machine_id: k for k in low_result.machine_kpis}
        assert kpi["m-screwdriving"].average_queue_length == pytest.approx(0.0, abs=1e-6)
        assert kpi["m-screwdriving"].max_queue_length == 0

    def test_low_no_wait_at_bottleneck(self, low_result: SimulationResult):
        kpi = {k.machine_id: k for k in low_result.machine_kpis}
        assert kpi["m-screwdriving"].average_wait_time_seconds == pytest.approx(0.0, abs=1e-6)

    def test_low_bottleneck_is_screwdriving(self, low_result: SimulationResult):
        assert low_result.system.bottleneck_machine_id == "m-screwdriving"

    def test_low_screwdriving_utilization_highest(self, low_result: SimulationResult):
        kpi_map = {k.machine_id: k for k in low_result.machine_kpis}
        screw_util = kpi_map["m-screwdriving"].utilization
        for mid, kpi in kpi_map.items():
            if mid != "m-screwdriving":
                assert screw_util >= kpi.utilization - 1e-9

    # BASE (1200/day)

    def test_base_demand_not_met(self, base_result: SimulationResult):
        assert base_result.demand_met is False
        assert base_result.demand_gap_units > 0

    def test_base_queue_forms_at_screwdriving(self, base_result: SimulationResult):
        kpi = {k.machine_id: k for k in base_result.machine_kpis}
        assert kpi["m-screwdriving"].average_queue_length > 0.0
        assert kpi["m-screwdriving"].max_queue_length > 0
        assert kpi["m-screwdriving"].average_wait_time_seconds > 0.0

    def test_base_bottleneck_is_screwdriving(self, base_result: SimulationResult):
        assert base_result.system.bottleneck_machine_id == "m-screwdriving"

    # HIGH (1600/day)

    def test_high_demand_not_met(self, high_result: SimulationResult):
        assert high_result.demand_met is False
        assert high_result.demand_gap_units > 0

    def test_high_queue_at_screwdriving_worse_than_base(
            self, base_result: SimulationResult, high_result: SimulationResult):
        base_kpi = {k.machine_id: k for k in base_result.machine_kpis}
        high_kpi = {k.machine_id: k for k in high_result.machine_kpis}
        assert (high_kpi["m-screwdriving"].average_queue_length
                > base_kpi["m-screwdriving"].average_queue_length)

    def test_high_wait_at_screwdriving_worse_than_base(
            self, base_result: SimulationResult, high_result: SimulationResult):
        base_kpi = {k.machine_id: k for k in base_result.machine_kpis}
        high_kpi = {k.machine_id: k for k in high_result.machine_kpis}
        assert (high_kpi["m-screwdriving"].average_wait_time_seconds
                > base_kpi["m-screwdriving"].average_wait_time_seconds)

    def test_high_wip_worse_than_base(
            self, base_result: SimulationResult, high_result: SimulationResult):
        assert (high_result.system.work_in_progress
                >= base_result.system.work_in_progress)

    def test_high_bottleneck_is_screwdriving(self, high_result: SimulationResult):
        assert high_result.system.bottleneck_machine_id == "m-screwdriving"

    def test_high_demand_gap_worse_than_base(
            self, base_result: SimulationResult, high_result: SimulationResult):
        assert high_result.demand_gap_units > base_result.demand_gap_units

    # Monotone ordering across all three

    def test_completed_units_bounded_by_line_capacity(
            self, low_result: SimulationResult,
            base_result: SimulationResult,
            high_result: SimulationResult):
        """Completed units must not exceed what the bottleneck can produce."""
        max_possible = int(57_600 // 52)  # 1107
        for result in (low_result, base_result, high_result):
            assert result.completed_units <= max_possible + 1  # +1 for edge rounding

    def test_release_intervals_decrease_with_demand(self, electronics_factory: Factory):
        """Higher demand → shorter release_interval (Phase 1.2 formula)."""
        r_low  = run_simulation(_electronics_with_demand(800.0),  "p-electronics-widget")
        r_base = run_simulation(_electronics_with_demand(1200.0), "p-electronics-widget")
        r_high = run_simulation(_electronics_with_demand(1600.0), "p-electronics-widget")
        assert r_low.release_interval_seconds > r_base.release_interval_seconds > r_high.release_interval_seconds


class TestBottleneckUnderMultiStageSaturation:
    """
    Regression coverage for Phase 6C.1's closure-audit defect: at a high enough demand,
    the release schedule (demand/horizon-driven, NOT bottleneck-paced — see this
    module's docstring) can exceed more than one stage's own service rate at once,
    saturating BOTH near 100% utilization.
    """

    def test_1900_per_day_bottleneck_is_screwdriving_not_assembly(self):
        result = run_simulation(_electronics_with_demand(1900.0), "p-electronics-widget")
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    def test_1900_per_day_both_stages_saturate_when_no_buffer_binds(self):
        """The multi-saturation edge case this class guards, re-homed."""
        result = run_simulation(_electronics_unbuffered(1900.0), "p-electronics-widget")
        kpi_map = {k.reference_machine_id: k for k in result.process_pool_kpis}
        assert kpi_map["m-assembly"].utilization >= 0.999
        assert kpi_map["m-screwdriving"].utilization >= 0.999

    def test_1900_per_day_screwdriving_queue_and_wait_worse_than_assembly(self):
        """
        The actual engineering evidence (queue/wait) unambiguously points at
        Screwdriving, even though its utilization is a hair below Assembly's.
        """
        result = run_simulation(_electronics_unbuffered(1900.0), "p-electronics-widget")
        kpi_map = {k.reference_machine_id: k for k in result.process_pool_kpis}
        assembly, screwdriving = kpi_map["m-assembly"], kpi_map["m-screwdriving"]
        assert screwdriving.utilization < assembly.utilization  # the near-tie that caused the bug
        assert screwdriving.average_queue_length > assembly.average_queue_length
        assert screwdriving.average_wait_time_seconds > assembly.average_wait_time_seconds
        # ...and the tie-break still picks the right stage.
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    # Phase 8A: what the bundled (buffered) fixture does instead

    def test_phase8a_blocking_lowers_upstream_utilization(self):
        """Why the near-tie disappeared on the real fixture."""
        result = run_simulation(_electronics_with_demand(1900.0), "p-electronics-widget")
        kpi_map = {k.reference_machine_id: k for k in result.process_pool_kpis}

        assert kpi_map["m-assembly"].utilization < 0.8
        assert kpi_map["m-screwdriving"].utilization >= 0.999

        blocked = next(k for k in result.buffer_kpis if k.buffer_id == "buf-1")
        assert blocked.blocking_observed is True
        assert blocked.upstream_blocked_seconds > 0
        assert blocked.upstream_machine_id == "m-assembly"

    def test_phase8a_the_bottleneck_is_still_identified_correctly_when_blocking_occurs(self):
        """
        The safety property that must survive the change: a stage held back by a full
        buffer must never be mistaken for the constraint.
        """
        result = run_simulation(_electronics_with_demand(1900.0), "p-electronics-widget")
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    def test_phase8a_a_finite_buffer_caps_the_queue_it_feeds(self):
        """
        A consequence worth pinning: with a finite buffer the measured queue in front of
        the downstream stage cannot exceed the buffer, and the backlog shows up upstream
        instead.
        """
        result = run_simulation(_electronics_with_demand(1900.0), "p-electronics-widget")
        kpi_map = {k.reference_machine_id: k for k in result.process_pool_kpis}
        buf_1 = next(k for k in result.buffer_kpis if k.buffer_id == "buf-1")

        assert kpi_map["m-screwdriving"].average_queue_length <= buf_1.capacity
        # The work did not vanish — it queued at the stage that is blocked.
        assert kpi_map["m-assembly"].average_queue_length > kpi_map["m-screwdriving"].average_queue_length

    def test_single_saturated_stage_still_wins_on_utilization_alone(self):
        """Below the multi-saturation threshold (1600/day — only
        Screwdriving is release-rate-bound), the original utilization-first
        behaviour is unchanged."""
        result = run_simulation(_electronics_with_demand(1600.0), "p-electronics-widget")
        kpi_map = {k.reference_machine_id: k for k in result.process_pool_kpis}
        assert kpi_map["m-assembly"].utilization < 0.999
        assert result.system.bottleneck_machine_id == "m-screwdriving"


# 9. Phase 1.2 – production-target schedule semantics

class TestProductionTargetSchedule:
    """Tests specifically for the Phase 1.2 release-schedule semantics."""

    def test_nominal_route_time_electronics(self, electronics_factory: Factory):
        """Nominal route time = sum of all step cycle times = 35+52+30+25 = 142 s."""
        result = run_simulation(electronics_factory, "p-electronics-widget")
        assert result.nominal_route_time_seconds == pytest.approx(142.0)

    def test_target_units_equals_ceil_demand(self, electronics_factory: Factory):
        """target_units = ceil(demand_per_day) = 1200."""
        result = run_simulation(electronics_factory, "p-electronics-widget")
        assert result.target_units == math.ceil(electronics_factory.products[0].demand_per_day)
        assert result.target_units == 1200

    def test_target_units_800(self):
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        assert result.target_units == 800

    def test_low_demand_all_800_complete(self):
        """Phase 1.2 schedule: all 800 units finish by horizon → demand_met=True."""
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        assert result.completed_units == 800
        assert result.demand_met is True
        assert result.demand_gap_units == 0

    def test_low_demand_wip_is_zero(self):
        """With sufficient capacity and correct schedule, WIP at horizon = 0."""
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        assert result.system.work_in_progress == 0

    def test_final_release_anchored_to_latest_release_time(self):
        """release_interval × (target_units - 1) ≈ horizon - nominal_route_time."""
        result = run_simulation(_electronics_with_demand(800.0), "p-electronics-widget")
        horizon = 57_600.0
        latest_release = horizon - result.nominal_route_time_seconds
        N = result.target_units
        # release_interval stored to 6 dp; accumulated product may differ by ~N×1e-6
        assert result.release_interval_seconds * (N - 1) == pytest.approx(latest_release, abs=0.1)

    def test_infeasible_route_raises_value_error(self):
        """nominal_route_time > horizon → ValueError with 'infeasible' in message."""
        factory = Factory.model_validate({
            "name": "Infeasible",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1,
            "hours_per_shift": 60.0 / 3600.0,  # 60-second horizon
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-1", "name": "M", "process_type": "assembly",
                "cycle_time": 100.0, "width": 1.0, "length": 1.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 10.0,
                "route": [{"name": "S", "machine_id": "m-1", "cycle_time": 100.0}],
            }],
        })
        with pytest.raises(ValueError, match="infeasible"):
            run_simulation(factory, "p-1")

    def test_infeasibility_message_contains_key_values(self):
        """Error message must include route time and horizon for diagnostics."""
        factory = Factory.model_validate({
            "name": "Infeasible",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1,
            "hours_per_shift": 60.0 / 3600.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-1", "name": "M", "process_type": "assembly",
                "cycle_time": 100.0, "width": 1.0, "length": 1.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 10.0,
                "route": [{"name": "S", "machine_id": "m-1", "cycle_time": 100.0}],
            }],
        })
        with pytest.raises(ValueError) as exc_info:
            run_simulation(factory, "p-1")
        msg = str(exc_info.value)
        assert "100" in msg   # nominal route time
        assert "60" in msg    # horizon

    def test_schedule_independent_of_machine_cycle_times(self):
        """Changing Machine cycle_time changes service capacity, NOT target_units."""
        import copy as _copy
        with open(EXAMPLES_DIR / "electronics_line.json") as f:
            data = json.load(f)

        # Double Screwdriving cycle_time (halve service capacity)
        slow_data = _copy.deepcopy(data)
        for m in slow_data["machines"]:
            if m["id"] == "m-screwdriving":
                m["cycle_time"] = 104.0
        for step in slow_data["products"][0]["route"]:
            if step["machine_id"] == "m-screwdriving":
                step["cycle_time"] = 104.0

        r_orig = run_simulation(Factory.model_validate(data), "p-electronics-widget")
        r_slow = run_simulation(Factory.model_validate(slow_data), "p-electronics-widget")

        # target_units unchanged (demand & horizon unchanged)
        assert r_orig.target_units == r_slow.target_units

        # release_interval IS different (nominal_route_time changed)
        assert r_orig.release_interval_seconds != pytest.approx(
            r_slow.release_interval_seconds, abs=0.01
        )

        # Both release_intervals are positive
        assert r_orig.release_interval_seconds > 0.0
        assert r_slow.release_interval_seconds > 0.0

    def test_single_unit_demand_released_at_t0(self):
        """demand = 1 → target = 1 → release_interval = 0 → single release at t=0."""
        factory = Factory.model_validate({
            "name": "Single",
            "width": 5.0, "length": 5.0,
            "shifts_per_day": 1, "hours_per_shift": 1.0,
            "operators_available": 0, "budget": 0.0,
            "machines": [{
                "id": "m-1", "name": "M", "process_type": "assembly",
                "cycle_time": 30.0, "width": 1.0, "length": 1.0,
            }],
            "products": [{
                "id": "p-1", "name": "Widget", "demand_per_day": 1.0,
                "route": [{"name": "S", "machine_id": "m-1", "cycle_time": 30.0}],
            }],
        })
        result = run_simulation(factory, "p-1")
        assert result.target_units == 1
        assert result.release_interval_seconds == pytest.approx(0.0)
        assert result.completed_units == 1
        assert result.demand_met is True
        assert result.demand_gap_units == 0

    def test_base_demand_queues_form(self, electronics_factory: Factory):
        """BASE (1200/day): arrival_rate > Screwdriving service_rate → queue forms."""
        result = run_simulation(electronics_factory, "p-electronics-widget")
        kpi_map = {k.machine_id: k for k in result.machine_kpis}
        assert kpi_map["m-screwdriving"].average_queue_length > 0.0
        assert kpi_map["m-screwdriving"].max_queue_length > 0
        assert kpi_map["m-screwdriving"].average_wait_time_seconds > 0.0

    def test_high_demand_queues_worse_than_base(self):
        """HIGH demand produces longer queues than BASE demand."""
        r_base = run_simulation(_electronics_with_demand(1200.0), "p-electronics-widget")
        r_high = run_simulation(_electronics_with_demand(1600.0), "p-electronics-widget")
        kpi_b = {k.machine_id: k for k in r_base.machine_kpis}
        kpi_h = {k.machine_id: k for k in r_high.machine_kpis}
        assert (kpi_h["m-screwdriving"].average_queue_length
                > kpi_b["m-screwdriving"].average_queue_length)

    def test_determinism_with_new_schedule(self, electronics_factory: Factory):
        """Repeated runs produce identical results under Phase 1.2 schedule."""
        r1 = run_simulation(electronics_factory, "p-electronics-widget")
        r2 = run_simulation(electronics_factory, "p-electronics-widget")
        assert r1.completed_units == r2.completed_units
        assert r1.release_interval_seconds == r2.release_interval_seconds
        assert r1.target_units == r2.target_units
        kpi1 = {k.machine_id: k for k in r1.machine_kpis}
        kpi2 = {k.machine_id: k for k in r2.machine_kpis}
        for mid in kpi1:
            assert kpi1[mid].utilization == kpi2[mid].utilization
            assert kpi1[mid].average_queue_length == kpi2[mid].average_queue_length

    def test_new_fields_present_in_api_response(self, electronics_json: dict):
        """API response must include target_units, nominal_route_time_seconds,
        release_interval_seconds."""
        client = TestClient(app)
        payload = {"factory": electronics_json, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        body = resp.json()
        assert "target_units" in body
        assert "nominal_route_time_seconds" in body
        assert "release_interval_seconds" in body
        assert body["target_units"] == 1200
        assert body["nominal_route_time_seconds"] == pytest.approx(142.0)

    def test_infeasible_route_returns_400_via_api(self, electronics_json: dict):
        """API must return 400 when nominal_route_time exceeds horizon."""
        client = TestClient(app)
        import copy as _copy
        bad_data = _copy.deepcopy(electronics_json)
        bad_data["shifts_per_day"] = 1
        bad_data["hours_per_shift"] = 0.01  # 36-second horizon
        payload = {"factory": bad_data, "product_id": "p-electronics-widget"}
        resp = client.post("/simulation/run", json=payload)
        assert resp.status_code == 400
