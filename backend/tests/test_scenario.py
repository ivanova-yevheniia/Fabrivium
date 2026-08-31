"""Pytest suite for FactoryMind Phase 2A – Scenario domain and application service."""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.models.factory import Factory
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeDemandAction,
    ChangeMachineCapacityAction,
    ChangeMachineCycleTimeAction,
    RemoveMachineAction,
    Scenario,
)
from app.services.scenario import (
    InvalidScenarioResultError,
    MachineNotFoundError,
    MachineRemovalError,
    ProductNotFoundError,
    apply_scenario,
)

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def minimal_machine(**overrides) -> dict:
    base = {
        "id": "m-1",
        "name": "Test Machine",
        "process_type": "assembly",
        "cycle_time": 30.0,
        "capacity": 1,
        "width": 2.0,
        "length": 1.5,
        "position_x": 0.0,
        "position_y": 0.0,
    }
    base.update(overrides)
    return base


def minimal_step(**overrides) -> dict:
    # Matches `minimal_machine`'s cycle_time.
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


def minimal_factory(**overrides) -> dict:
    base = {
        "name": "Test Factory",
        "width": 100.0,
        "length": 50.0,
        "shifts_per_day": 2,
        "hours_per_shift": 8.0,
        "operators_available": 10,
        "budget": 0.0,
        "machines": [minimal_machine()],
        "products": [minimal_product()],
        "buffers": [],
    }
    base.update(overrides)
    return base


@pytest.fixture
def factory() -> Factory:
    return Factory(**minimal_factory())


@pytest.fixture
def two_machine_factory() -> Factory:
    """A factory where two machines share the same process_type so that
    REMOVE_MACHINE has a compatible fallback available."""
    return Factory(
        **minimal_factory(
            machines=[
                minimal_machine(id="m-1", name="Machine One"),
                minimal_machine(id="m-2", name="Machine Two", position_x=10.0),
            ],
            products=[
                minimal_product(route=[minimal_step(machine_id="m-1")]),
            ],
        )
    )


@pytest.fixture
def electronics_factory() -> Factory:
    data = json.loads((EXAMPLES_DIR / "electronics_line.json").read_text())
    return Factory(**data)


def scenario_of(*actions, id: str = "s-1", name: str = "Test Scenario") -> Scenario:
    return Scenario(id=id, name=name, description="", actions=list(actions))


# 1. Scenario / action model validation

class TestActionModels:
    def test_add_parallel_machine_valid(self):
        action = AddParallelMachineAction(machine_id="m-1")
        assert action.action_type == "ADD_PARALLEL_MACHINE"

    def test_add_parallel_machine_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            AddParallelMachineAction(machine_id="")

    def test_change_cycle_time_valid(self):
        action = ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=12.5)
        assert action.cycle_time == 12.5

    def test_change_cycle_time_zero_rejected(self):
        with pytest.raises(ValidationError):
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=0.0)

    def test_change_cycle_time_negative_rejected(self):
        with pytest.raises(ValidationError):
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=-1.0)

    def test_change_capacity_valid(self):
        action = ChangeMachineCapacityAction(machine_id="m-1", capacity=3)
        assert action.capacity == 3

    def test_change_capacity_zero_rejected(self):
        with pytest.raises(ValidationError):
            ChangeMachineCapacityAction(machine_id="m-1", capacity=0)

    def test_change_demand_valid(self):
        action = ChangeDemandAction(product_id="p-1", demand_per_day=50.0)
        assert action.demand_per_day == 50.0

    def test_change_demand_zero_rejected(self):
        with pytest.raises(ValidationError):
            ChangeDemandAction(product_id="p-1", demand_per_day=0.0)

    def test_remove_machine_valid(self):
        action = RemoveMachineAction(machine_id="m-1")
        assert action.action_type == "REMOVE_MACHINE"

    def test_actions_are_frozen(self):
        action = ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=12.5)
        with pytest.raises(ValidationError):
            action.cycle_time = 99.0

    def test_scenario_discriminated_union_from_dict(self):
        scenario = Scenario(
            id="s-1",
            name="Mixed",
            actions=[
                {"action_type": "CHANGE_MACHINE_CYCLE_TIME", "machine_id": "m-1", "cycle_time": 5.0},
                {"action_type": "REMOVE_MACHINE", "machine_id": "m-1"},
            ],
        )
        assert isinstance(scenario.actions[0], ChangeMachineCycleTimeAction)
        assert isinstance(scenario.actions[1], RemoveMachineAction)

    def test_scenario_unknown_action_type_rejected(self):
        with pytest.raises(ValidationError):
            Scenario(
                id="s-1",
                name="Bad",
                actions=[{"action_type": "DELETE_EVERYTHING", "machine_id": "m-1"}],
            )

    def test_scenario_requires_id_and_name(self):
        with pytest.raises(ValidationError):
            Scenario(id="", name="X", actions=[])
        with pytest.raises(ValidationError):
            Scenario(id="s-1", name="", actions=[])

    def test_scenario_frozen(self):
        scenario = scenario_of()
        with pytest.raises(ValidationError):
            scenario.name = "renamed"


# 2. apply_scenario – ADD_PARALLEL_MACHINE

class TestAddParallelMachine:
    def test_creates_distinct_machine(self, factory: Factory):
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result = apply_scenario(factory, scenario)

        assert len(result.machines) == 2
        clone = next(m for m in result.machines if m.id == "m-1-parallel-1")
        assert clone.id != "m-1"
        assert clone.name != "Test Machine"

    def test_clones_engineering_properties(self, factory: Factory):
        source = factory.machines[0]
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result = apply_scenario(factory, scenario)
        clone = next(m for m in result.machines if m.id == "m-1-parallel-1")

        assert clone.process_type == source.process_type
        assert clone.cycle_time == source.cycle_time
        assert clone.setup_time == source.setup_time
        assert clone.capacity == source.capacity
        assert clone.failure_rate == source.failure_rate
        assert clone.mean_repair_time == source.mean_repair_time
        assert clone.operators_required == source.operators_required
        assert clone.purchase_cost == source.purchase_cost
        assert clone.width == source.width
        assert clone.length == source.length

    def test_does_not_increase_source_capacity(self, factory: Factory):
        source = factory.machines[0]
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result = apply_scenario(factory, scenario)
        original = next(m for m in result.machines if m.id == "m-1")
        assert original.capacity == source.capacity

    def test_independent_position(self, factory: Factory):
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result = apply_scenario(factory, scenario)
        source = next(m for m in result.machines if m.id == "m-1")
        clone = next(m for m in result.machines if m.id == "m-1-parallel-1")
        assert (clone.position_x, clone.position_y) != (source.position_x, source.position_y)

    def test_deterministic_incrementing_ids(self, factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            AddParallelMachineAction(machine_id="m-1"),
            AddParallelMachineAction(machine_id="m-1"),
        )
        result = apply_scenario(factory, scenario)
        ids = sorted(m.id for m in result.machines)
        assert ids == ["m-1", "m-1-parallel-1", "m-1-parallel-2", "m-1-parallel-3"]

    def test_repeated_application_is_deterministic(self, factory: Factory):
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result_a = apply_scenario(factory, scenario)
        result_b = apply_scenario(factory, scenario)
        assert result_a.model_dump() == result_b.model_dump()

    def test_missing_machine_rejected(self, factory: Factory):
        scenario = scenario_of(AddParallelMachineAction(machine_id="does-not-exist"))
        with pytest.raises(MachineNotFoundError):
            apply_scenario(factory, scenario)


# 3. apply_scenario – CHANGE_MACHINE_CYCLE_TIME

class TestChangeMachineCycleTime:
    def test_updates_candidate_only(self, factory: Factory):
        scenario = scenario_of(ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=99.0))
        result = apply_scenario(factory, scenario)
        assert result.machines[0].cycle_time == 99.0
        assert factory.machines[0].cycle_time == 30.0  # baseline untouched

    def test_missing_machine_rejected(self, factory: Factory):
        scenario = scenario_of(ChangeMachineCycleTimeAction(machine_id="nope", cycle_time=5.0))
        with pytest.raises(MachineNotFoundError):
            apply_scenario(factory, scenario)

    def test_non_positive_value_rejected_at_construction(self):
        with pytest.raises(ValidationError):
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=0.0)


# 4. apply_scenario – CHANGE_MACHINE_CAPACITY

class TestChangeMachineCapacity:
    def test_updates_candidate_only(self, factory: Factory):
        scenario = scenario_of(ChangeMachineCapacityAction(machine_id="m-1", capacity=4))
        result = apply_scenario(factory, scenario)
        assert result.machines[0].capacity == 4
        assert factory.machines[0].capacity == 1  # baseline untouched

    def test_missing_machine_rejected(self, factory: Factory):
        scenario = scenario_of(ChangeMachineCapacityAction(machine_id="nope", capacity=2))
        with pytest.raises(MachineNotFoundError):
            apply_scenario(factory, scenario)

    def test_non_positive_value_rejected_at_construction(self):
        with pytest.raises(ValidationError):
            ChangeMachineCapacityAction(machine_id="m-1", capacity=0)


# 5. apply_scenario – CHANGE_DEMAND

class TestChangeDemand:
    def test_updates_candidate_only(self, factory: Factory):
        scenario = scenario_of(ChangeDemandAction(product_id="p-1", demand_per_day=250.0))
        result = apply_scenario(factory, scenario)
        assert result.products[0].demand_per_day == 250.0
        assert factory.products[0].demand_per_day == 100.0  # baseline untouched

    def test_missing_product_rejected(self, factory: Factory):
        scenario = scenario_of(ChangeDemandAction(product_id="nope", demand_per_day=10.0))
        with pytest.raises(ProductNotFoundError):
            apply_scenario(factory, scenario)

    def test_non_positive_value_rejected_at_construction(self):
        with pytest.raises(ValidationError):
            ChangeDemandAction(product_id="p-1", demand_per_day=0.0)


# 6. apply_scenario – REMOVE_MACHINE

class TestRemoveMachine:
    def test_removes_machine(self, two_machine_factory: Factory):
        # m-2 is not referenced by any route, so it is always safely removable.
        scenario = scenario_of(RemoveMachineAction(machine_id="m-2"))
        result = apply_scenario(two_machine_factory, scenario)
        assert [m.id for m in result.machines] == ["m-1"]

    def test_missing_machine_rejected(self, factory: Factory):
        scenario = scenario_of(RemoveMachineAction(machine_id="nope"))
        with pytest.raises(MachineNotFoundError):
            apply_scenario(factory, scenario)

    def test_removing_last_required_machine_rejected(self, factory: Factory):
        # factory has exactly one machine (m-1), referenced by the product route.
        scenario = scenario_of(RemoveMachineAction(machine_id="m-1"))
        with pytest.raises(MachineRemovalError):
            apply_scenario(factory, scenario)
        # baseline untouched even on failure
        assert len(factory.machines) == 1

    def test_removal_allowed_when_compatible_machine_remains(self):
        # Two machines with the SAME process_type; route references m-1.
        fac = Factory(
            **minimal_factory(
                machines=[
                    minimal_machine(id="m-1", name="Machine One", process_type="assembly"),
                    minimal_machine(id="m-2", name="Machine Two", process_type="assembly", position_x=10.0),
                ],
                products=[minimal_product(route=[minimal_step(machine_id="m-1")])],
            )
        )
        scenario = scenario_of(RemoveMachineAction(machine_id="m-1"))
        result = apply_scenario(fac, scenario)
        assert [m.id for m in result.machines] == ["m-2"]

    def test_removal_after_adding_parallel_machine_is_allowed(self, factory: Factory):
        # Demonstrates the intended workflow: clone m-1, then remove the
        # original since the parallel clone (same process_type) covers it.
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            RemoveMachineAction(machine_id="m-1"),
        )
        result = apply_scenario(factory, scenario)
        assert [m.id for m in result.machines] == ["m-1-parallel-1"]


# 7. Baseline immutability

class TestBaselineImmutability:
    def test_baseline_unchanged_after_all_action_types(self, two_machine_factory: Factory):
        before = two_machine_factory.model_dump()
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=77.0),
            ChangeMachineCapacityAction(machine_id="m-1", capacity=9),
            ChangeDemandAction(product_id="p-1", demand_per_day=500.0),
            RemoveMachineAction(machine_id="m-2"),
        )
        apply_scenario(two_machine_factory, scenario)
        assert two_machine_factory.model_dump() == before

    def test_result_is_not_the_same_object(self, factory: Factory):
        scenario = scenario_of(ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=1.0))
        result = apply_scenario(factory, scenario)
        assert result is not factory


# 8. Sequential multi-action scenarios

class TestSequentialActions:
    def test_actions_apply_in_order(self, factory: Factory):
        scenario = scenario_of(
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=20.0),
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=40.0),
        )
        result = apply_scenario(factory, scenario)
        assert result.machines[0].cycle_time == 40.0

    def test_mixed_action_sequence(self, factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            ChangeMachineCapacityAction(machine_id="m-1-parallel-1", capacity=2),
            ChangeDemandAction(product_id="p-1", demand_per_day=300.0),
        )
        result = apply_scenario(factory, scenario)
        clone = next(m for m in result.machines if m.id == "m-1-parallel-1")
        assert clone.capacity == 2
        assert result.products[0].demand_per_day == 300.0

    def test_failure_partway_through_does_not_apply_later_actions(self, factory: Factory):
        scenario = scenario_of(
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=15.0),
            ChangeMachineCapacityAction(machine_id="does-not-exist", capacity=2),
        )
        with pytest.raises(MachineNotFoundError):
            apply_scenario(factory, scenario)


# 9. Determinism / repeated application

class TestDeterminism:
    def test_repeated_apply_scenario_identical(self, two_machine_factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            ChangeMachineCycleTimeAction(machine_id="m-1", cycle_time=42.0),
        )
        result_a = apply_scenario(two_machine_factory, scenario)
        result_b = apply_scenario(two_machine_factory, scenario)
        assert result_a.model_dump() == result_b.model_dump()


# 10. Resulting Factory validity

class TestResultingFactoryValidity:
    def test_result_is_valid_factory_instance(self, factory: Factory):
        scenario = scenario_of(AddParallelMachineAction(machine_id="m-1"))
        result = apply_scenario(factory, scenario)
        assert isinstance(result, Factory)
        # Re-validating an already-valid Factory must succeed without error.
        Factory.model_validate(result.model_dump())

    def test_no_duplicate_ids_after_parallel_add(self, factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-1"),
            AddParallelMachineAction(machine_id="m-1"),
        )
        result = apply_scenario(factory, scenario)
        ids = [m.id for m in result.machines]
        assert len(ids) == len(set(ids))


# 11. Integration – electronics_line.json

class TestElectronicsLineIntegration:
    def test_add_parallel_screwdriving_machine(self, electronics_factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            id="s-parallel-screwdriving",
            name="Add parallel screwdriving station",
        )
        result = apply_scenario(electronics_factory, scenario)

        assert len(result.machines) == len(electronics_factory.machines) + 1
        clone = next(m for m in result.machines if m.id == "m-screwdriving-parallel-1")
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")

        assert clone.process_type == source.process_type == "screwdriving"
        assert clone.cycle_time == source.cycle_time == 52.0
        assert clone.capacity == source.capacity
        # Baseline factory is untouched
        assert len(electronics_factory.machines) == 4

    def test_remove_screwdriving_rejected_without_parallel(self, electronics_factory: Factory):
        scenario = scenario_of(RemoveMachineAction(machine_id="m-screwdriving"))
        with pytest.raises(MachineRemovalError):
            apply_scenario(electronics_factory, scenario)

    def test_remove_screwdriving_allowed_after_parallel_added(self, electronics_factory: Factory):
        scenario = scenario_of(
            AddParallelMachineAction(machine_id="m-screwdriving"),
            RemoveMachineAction(machine_id="m-screwdriving"),
        )
        result = apply_scenario(electronics_factory, scenario)
        ids = {m.id for m in result.machines}
        assert "m-screwdriving" not in ids
        assert "m-screwdriving-parallel-1" in ids
