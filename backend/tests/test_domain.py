"""Comprehensive pytest suite for FactoryMind Phase 0 domain models."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Buffer, Factory, Machine, ProcessStep, Product

# Helpers / fixtures

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


def minimal_machine(**overrides) -> dict:
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


def minimal_step(**overrides) -> dict:
    # Matches `minimal_machine`'s cycle_time on purpose.
    base = {"name": "Step A", "machine_id": "m-1", "cycle_time": 30.0}
    base.update(overrides)
    return base


def minimal_product(**overrides) -> dict:
    base = {
        "id": "p-1",
        "name": "Widget",
        "demand_per_day": 100.0,
        "route": [minimal_step()],
    }
    base.update(overrides)
    return base


def minimal_buffer(**overrides) -> dict:
    base = {"id": "b-1", "name": "Buffer A", "capacity": 20}
    base.update(overrides)
    return base


def minimal_factory(**overrides) -> dict:
    base = {
        "name": "Test Factory",
        "width": 100.0,
        "length": 50.0,
        "shifts_per_day": 2,
        "hours_per_shift": 8.0,
        "operators_available": 10,
        "budget": 0.0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# 1. ProcessStep

class TestProcessStep:
    def test_valid(self):
        step = ProcessStep(**minimal_step())
        assert step.name == "Step A"
        assert step.machine_id == "m-1"
        assert step.cycle_time == 30.0

    def test_cycle_time_zero_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ProcessStep(**minimal_step(cycle_time=0.0))
        assert "cycle_time" in str(exc.value)

    def test_cycle_time_negative_rejected(self):
        with pytest.raises(ValidationError):
            ProcessStep(**minimal_step(cycle_time=-5.0))

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProcessStep(**minimal_step(name=""))

    def test_empty_machine_id_rejected(self):
        with pytest.raises(ValidationError):
            ProcessStep(**minimal_step(machine_id=""))

    def test_fractional_cycle_time_accepted(self):
        step = ProcessStep(**minimal_step(cycle_time=0.001))
        assert step.cycle_time == pytest.approx(0.001)

    def test_immutable(self):
        """ProcessStep is frozen; direct attribute assignment must raise."""
        step = ProcessStep(**minimal_step())
        with pytest.raises(Exception):
            step.name = "Changed"  # type: ignore[misc]


# 2. Machine

class TestMachine:
    def test_valid_minimal(self):
        m = Machine(**minimal_machine())
        assert m.id == "m-1"
        assert m.capacity == 1          # default
        assert m.failure_rate == 0.0    # default
        assert m.operators_required == 0  # default

    def test_cycle_time_must_be_positive(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(cycle_time=0.0))

    def test_cycle_time_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(cycle_time=-1.0))

    def test_setup_time_zero_accepted(self):
        m = Machine(**minimal_machine(setup_time=0.0))
        assert m.setup_time == 0.0

    def test_setup_time_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(setup_time=-10.0))

    def test_width_must_be_positive(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(width=0.0))

    def test_length_must_be_positive(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(length=0.0))

    def test_capacity_zero_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(capacity=0))

    def test_capacity_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(capacity=-1))

    def test_failure_rate_zero_accepted(self):
        m = Machine(**minimal_machine(failure_rate=0.0))
        assert m.failure_rate == 0.0

    def test_failure_rate_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(failure_rate=-0.1))

    def test_mean_repair_time_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(mean_repair_time=-1.0))

    def test_operators_required_zero_accepted(self):
        m = Machine(**minimal_machine(operators_required=0))
        assert m.operators_required == 0

    def test_operators_required_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(operators_required=-1))

    def test_purchase_cost_zero_accepted(self):
        m = Machine(**minimal_machine(purchase_cost=0.0))
        assert m.purchase_cost == 0.0

    def test_purchase_cost_negative_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(purchase_cost=-100.0))

    def test_position_can_be_negative(self):
        """Positions represent coordinates – negative values are valid."""
        m = Machine(**minimal_machine(position_x=-5.0, position_y=-3.0))
        assert m.position_x == -5.0

    def test_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(id=""))

    def test_empty_process_type_rejected(self):
        with pytest.raises(ValidationError):
            Machine(**minimal_machine(process_type=""))

    def test_immutable(self):
        m = Machine(**minimal_machine())
        with pytest.raises(Exception):
            m.cycle_time = 99.0  # type: ignore[misc]


# 3. Product

class TestProduct:
    def test_valid(self):
        p = Product(**minimal_product())
        assert p.demand_per_day == 100.0
        assert len(p.route) == 1

    def test_demand_zero_rejected(self):
        with pytest.raises(ValidationError):
            Product(**minimal_product(demand_per_day=0.0))

    def test_demand_negative_rejected(self):
        with pytest.raises(ValidationError):
            Product(**minimal_product(demand_per_day=-10.0))

    def test_empty_route_rejected(self):
        with pytest.raises(ValidationError):
            Product(**minimal_product(route=[]))

    def test_multi_step_route(self):
        route = [
            minimal_step(name="Step A", machine_id="m-1", cycle_time=10.0),
            minimal_step(name="Step B", machine_id="m-2", cycle_time=20.0),
        ]
        p = Product(**minimal_product(route=route))
        assert len(p.route) == 2

    def test_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            Product(**minimal_product(id=""))


# 4. Buffer

class TestBuffer:
    def test_valid(self):
        b = Buffer(**minimal_buffer())
        assert b.capacity == 20

    def test_capacity_zero_rejected(self):
        with pytest.raises(ValidationError):
            Buffer(**minimal_buffer(capacity=0))

    def test_capacity_negative_rejected(self):
        with pytest.raises(ValidationError):
            Buffer(**minimal_buffer(capacity=-5))

    def test_position_defaults_to_zero(self):
        b = Buffer(**minimal_buffer())
        assert b.position_x == 0.0
        assert b.position_y == 0.0

    def test_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            Buffer(**minimal_buffer(id=""))


# 5. Factory

class TestFactory:
    def test_valid_empty_factory(self):
        f = Factory(**minimal_factory())
        assert f.machines == []
        assert f.products == []
        assert f.buffers == []

    def test_valid_with_children(self):
        f = Factory(
            **minimal_factory(),
            machines=[Machine(**minimal_machine())],
            products=[Product(**minimal_product())],
            buffers=[Buffer(**minimal_buffer())],
        )
        assert len(f.machines) == 1

    def test_width_zero_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(width=0.0))

    def test_length_zero_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(length=0.0))

    def test_shifts_per_day_zero_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(shifts_per_day=0))

    def test_hours_per_shift_zero_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(hours_per_shift=0.0))

    def test_operators_available_zero_accepted(self):
        f = Factory(**minimal_factory(operators_available=0))
        assert f.operators_available == 0

    def test_operators_available_negative_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(operators_available=-1))

    def test_budget_zero_accepted(self):
        f = Factory(**minimal_factory(budget=0.0))
        assert f.budget == 0.0

    def test_budget_negative_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(budget=-1.0))

    def test_duplicate_machine_ids_rejected(self):
        m1 = Machine(**minimal_machine(id="dup"))
        m2 = Machine(**minimal_machine(id="dup"))
        with pytest.raises(ValidationError) as exc:
            Factory(**minimal_factory(), machines=[m1, m2])
        assert "dup" in str(exc.value)

    def test_duplicate_product_ids_rejected(self):
        p1 = Product(**minimal_product(id="dup-p"))
        p2 = Product(**minimal_product(id="dup-p"))
        with pytest.raises(ValidationError) as exc:
            Factory(**minimal_factory(), products=[p1, p2])
        assert "dup-p" in str(exc.value)

    def test_duplicate_buffer_ids_rejected(self):
        b1 = Buffer(**minimal_buffer(id="dup-b"))
        b2 = Buffer(**minimal_buffer(id="dup-b"))
        with pytest.raises(ValidationError) as exc:
            Factory(**minimal_factory(), buffers=[b1, b2])
        assert "dup-b" in str(exc.value)

    def test_unique_machine_ids_accepted(self):
        m1 = Machine(**minimal_machine(id="m-a"))
        m2 = Machine(**minimal_machine(id="m-b"))
        f = Factory(**minimal_factory(), machines=[m1, m2])
        assert len(f.machines) == 2

    def test_empty_factory_name_rejected(self):
        with pytest.raises(ValidationError):
            Factory(**minimal_factory(name=""))

    def test_model_dump_round_trip(self):
        """model_dump() → model_validate() must reproduce the same object."""
        original = Factory(**minimal_factory())
        dumped = original.model_dump()
        restored = Factory.model_validate(dumped)
        assert restored.name == original.name

    def test_total_available_hours_calculation(self):
        f = Factory(**minimal_factory(shifts_per_day=2, hours_per_shift=8.0))
        total = f.shifts_per_day * f.hours_per_shift
        assert total == 16.0


# 6. API – /health

class TestHealthEndpoint:
    def test_health_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# 7. API – /factory/validate

class TestValidateEndpoint:
    def test_valid_payload(self, client: TestClient):
        payload = minimal_factory()
        resp = client.post("/factory/validate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["summary"]["name"] == "Test Factory"
        assert body["summary"]["schedule"]["total_hours_per_day"] == 16.0

    def test_invalid_payload_returns_errors(self, client: TestClient):
        payload = minimal_factory(width=-10.0)
        resp = client.post("/factory/validate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert len(body["errors"]) > 0

    def test_duplicate_machine_ids_via_api(self, client: TestClient):
        payload = minimal_factory()
        payload["machines"] = [
            minimal_machine(id="dup"),
            minimal_machine(id="dup"),
        ]
        resp = client.post("/factory/validate", json=payload)
        body = resp.json()
        assert body["valid"] is False

    def test_summary_counts(self, client: TestClient):
        payload = minimal_factory()
        payload["machines"] = [minimal_machine(id="m-a"), minimal_machine(id="m-b")]
        payload["products"] = [minimal_product()]
        payload["buffers"] = [minimal_buffer()]
        resp = client.post("/factory/validate", json=payload)
        body = resp.json()
        assert body["valid"] is True
        assert body["summary"]["machines_count"] == 2
        assert body["summary"]["products_count"] == 1
        assert body["summary"]["buffers_count"] == 1


# 8. Integration – electronics_line.json round-trip

class TestElectronicsLineIntegration:
    @pytest.fixture
    def electronics_data(self) -> dict:
        with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
            return json.load(fh)

    def test_json_loads_as_valid_factory(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        assert factory.name == "Electronics Assembly Line"

    def test_schedule_matches_spec(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        assert factory.shifts_per_day == 2
        assert factory.hours_per_shift == 8.0
        assert factory.operators_available == 8

    def test_four_machines_present(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        assert len(factory.machines) == 4

    def test_machine_ids_are_unique(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        ids = [m.id for m in factory.machines]
        assert len(ids) == len(set(ids))

    def test_product_demand(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        assert len(factory.products) == 1
        assert factory.products[0].demand_per_day == 1200.0

    def test_route_order(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        route_names = [s.name for s in factory.products[0].route]
        assert route_names == ["Assembly", "Screwdriving", "Inspection", "Packaging"]

    def test_cycle_times(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        ct_map = {s.name: s.cycle_time for s in factory.products[0].route}
        assert ct_map["Assembly"] == 35.0
        assert ct_map["Screwdriving"] == 52.0
        assert ct_map["Inspection"] == 30.0
        assert ct_map["Packaging"] == 25.0

    def test_bottleneck_is_screwdriving(self, electronics_data: dict):
        """Screwdriving has the longest cycle time and is the bottleneck step."""
        factory = Factory.model_validate(electronics_data)
        bottleneck = max(factory.products[0].route, key=lambda s: s.cycle_time)
        assert bottleneck.name == "Screwdriving"

    def test_three_buffers(self, electronics_data: dict):
        factory = Factory.model_validate(electronics_data)
        assert len(factory.buffers) == 3

    def test_round_trip_via_api(self, client: TestClient, electronics_data: dict):
        resp = client.post("/factory/validate", json=electronics_data)
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["summary"]["machines_count"] == 4
        assert body["summary"]["products_count"] == 1
