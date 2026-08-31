"""The invariants the Final Competition Integrity phase established."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Buffer, Factory, Machine, ProcessStep, Product
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.capacity import CapacityNotMeasurable, measure_capacity
from app.services.comparison import calculate_capex_delta
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.concept_validation import (
    ConceptNotReadyError,
    concept_gaps,
    concept_to_factory,
)
from app.services.simulation import run_simulation

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "electronics_line.json"

BRIEF = (
    "We need a line making 1,900 units per day with assembly, screwdriving, "
    "inspection and packaging in a 30 by 18 meter hall with eight operators."
)


@pytest.fixture
def resolved_draft():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


@pytest.fixture
def demo_factory() -> Factory:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["products"][0]["demand_per_day"] = 1900.0
    return Factory.model_validate(data)


def _restate(draft, index: int, field: str, value):
    """Return the draft with one stage's ConceptValue set to `value`."""
    stage = draft.stages[index]
    sourced = getattr(stage, field).model_copy(update={"value": value})
    stages = list(draft.stages)
    stages[index] = stage.model_copy(update={field: sourced})
    return draft.model_copy(update={"stages": tuple(stages)})


# R1 — an unknown price is not a price

class TestUnknownCostIsNotZero:
    def test_an_unpriced_stage_reaches_the_factory_as_unknown(self, resolved_draft):
        factory, _ = concept_to_factory(_restate(resolved_draft, 1, "purchase_cost", None))
        assert factory.machines[1].purchase_cost is None

    def test_an_engineer_entered_zero_survives_as_zero(self, resolved_draft):
        """The reverse guard."""
        factory, _ = concept_to_factory(_restate(resolved_draft, 1, "purchase_cost", 0.0))
        assert factory.machines[1].purchase_cost == 0.0
        assert factory.machines[1].purchase_cost is not None

    def test_the_two_are_distinguishable_in_the_model(self, resolved_draft):
        unknown, _ = concept_to_factory(_restate(resolved_draft, 1, "purchase_cost", None))
        zero, _ = concept_to_factory(_restate(resolved_draft, 1, "purchase_cost", 0.0))
        assert unknown.machines[1].purchase_cost != zero.machines[1].purchase_cost

    def test_an_unset_budget_is_not_a_budget_of_zero(self, resolved_draft):
        draft = resolved_draft.model_copy(
            update={"budget": resolved_draft.budget.model_copy(update={"value": None})}
        )
        factory, _ = concept_to_factory(draft)
        assert factory.budget is None

    def test_a_scenario_over_an_unpriced_machine_has_no_capex_figure(self, resolved_draft):
        """A partial sum is not a price, and 0.0 would read as free."""
        factory, _ = concept_to_factory(_restate(resolved_draft, 1, "purchase_cost", None))
        scenario = Scenario(
            id="s",
            name="s",
            actions=[AddParallelMachineAction(machine_id=factory.machines[1].id)],
        )
        assert calculate_capex_delta(factory, scenario) is None

    def test_a_scenario_over_a_priced_machine_still_reports_its_capex(self, resolved_draft):
        factory, _ = concept_to_factory(resolved_draft)
        scenario = Scenario(
            id="s",
            name="s",
            actions=[AddParallelMachineAction(machine_id=factory.machines[1].id)],
        )
        assert calculate_capex_delta(factory, scenario) == factory.machines[1].purchase_cost


# R2 — an unknown operator requirement is not "nobody"

class TestUnknownOperatorsBlockTheBuild:
    def test_an_unknown_operator_count_refuses_to_build(self, resolved_draft):
        draft = _restate(resolved_draft, 1, "operators_required", None)
        with pytest.raises(ConceptNotReadyError) as exc:
            concept_to_factory(draft)
        assert "operators required" in str(exc.value).lower()

    def test_it_is_a_required_gap_not_an_optional_one(self):
        gaps = {g.key: g.severity.name for g in concept_gaps(concept_from_brief(BRIEF))}
        operator_gaps = {k: v for k, v in gaps.items() if k.endswith(".operators_required")}
        assert operator_gaps, "no operator gap is declared at all"
        assert set(operator_gaps.values()) == {"REQUIRED"}

    def test_an_engineer_entered_zero_is_a_fully_automatic_station(self, resolved_draft):
        """The reverse guard. Zero operators is a real engineering answer."""
        factory, _ = concept_to_factory(_restate(resolved_draft, 1, "operators_required", 0))
        assert factory.machines[1].operators_required == 0

    @pytest.mark.parametrize(
        "available, expected",
        [(8, 1105), (4, 797), (2, 404)],
    )
    def test_operator_scarcity_changes_throughput(self, demo_factory, available, expected):
        """The regression that would have caught the defect."""
        factory = demo_factory.model_copy(update={"operators_available": available})
        result = run_simulation(factory, factory.products[0].id)
        assert result.completed_units == expected

    def test_zeroed_operators_would_overstate_output(self, demo_factory):
        """Pins the size of the error the fix prevents."""
        scarce = demo_factory.model_copy(update={"operators_available": 4})
        honest = run_simulation(scarce, scarce.products[0].id).completed_units

        zeroed = scarce.model_copy(
            update={"machines": [m.model_copy(update={"operators_required": 0}) for m in scarce.machines]}
        )
        optimistic = run_simulation(zeroed, zeroed.products[0].id).completed_units

        assert optimistic > honest
        assert optimistic / honest > 1.3  # ~39% on this line


# R3 — one authoritative cycle time

class TestOneAuthoritativeCycleTime:
    def _factory(self, machine_cycle: float, route_cycle: float) -> dict:
        return {
            "name": "T",
            "width": 10.0,
            "length": 10.0,
            "shifts_per_day": 1,
            "hours_per_shift": 8.0,
            "operators_available": 1,
            "machines": [
                {
                    "id": "m-1",
                    "name": "M",
                    "process_type": "assembly",
                    "cycle_time": machine_cycle,
                    "width": 2.0,
                    "length": 2.0,
                }
            ],
            "products": [
                {
                    "id": "p-1",
                    "name": "P",
                    "demand_per_day": 10.0,
                    "route": [{"name": "S", "machine_id": "m-1", "cycle_time": route_cycle}],
                }
            ],
            "buffers": [],
        }

    def test_a_divergence_is_refused(self):
        with pytest.raises(Exception) as exc:
            Factory.model_validate(self._factory(30.0, 10.0))
        assert "disagrees" in str(exc.value)

    def test_the_message_names_both_numbers(self):
        with pytest.raises(Exception) as exc:
            Factory.model_validate(self._factory(30.0, 10.0))
        message = str(exc.value)
        assert "30.0" in message and "10.0" in message

    def test_agreement_is_accepted(self):
        factory = Factory.model_validate(self._factory(30.0, 30.0))
        assert factory.machines[0].cycle_time == 30.0

    def test_the_bundled_fixture_satisfies_the_contract(self, demo_factory):
        by_id = {m.id: m for m in demo_factory.machines}
        for product in demo_factory.products:
            for step in product.route:
                assert step.cycle_time == by_id[step.machine_id].cycle_time

    def test_every_concept_built_from_a_draft_satisfies_it(self, resolved_draft):
        factory, _ = concept_to_factory(resolved_draft)
        by_id = {m.id: m for m in factory.machines}
        for product in factory.products:
            for step in product.route:
                assert step.cycle_time == by_id[step.machine_id].cycle_time


# R4 / R5 — capacity, not pacing

class TestCapacityIsMeasuredNotAssumed:
    def test_the_saturated_run_is_actually_saturated(self, demo_factory):
        measurement = measure_capacity(demo_factory, demo_factory.products[0].id)
        # If the line had satisfied the saturation demand, the figure would be
        # the schedule again rather than the line's ceiling.
        assert measurement.capacity_units_per_day < 100_000

    def test_a_line_that_cannot_be_saturated_refuses_to_report_a_capacity(self, demo_factory):
        trivial = demo_factory.model_copy(
            update={
                "products": [
                    demo_factory.products[0].model_copy(update={"demand_per_day": 1.0})
                ],
                "machines": [
                    m.model_copy(update={"cycle_time": 0.001}) for m in demo_factory.machines
                ],
            }
        )
        # Route steps must agree with the machines they point at.
        trivial = trivial.model_copy(
            update={
                "products": [
                    trivial.products[0].model_copy(
                        update={
                            "route": [
                                s.model_copy(update={"cycle_time": 0.001})
                                for s in trivial.products[0].route
                            ]
                        }
                    )
                ]
            }
        )
        with pytest.raises(CapacityNotMeasurable):
            measure_capacity(trivial, trivial.products[0].id, target_units_per_day=1.0)

    def test_a_baseline_with_no_changes_reports_no_phantom_headroom(self, demo_factory):
        paced = run_simulation(demo_factory, demo_factory.products[0].id)
        measurement = measure_capacity(demo_factory, demo_factory.products[0].id)
        assert measurement.capacity_units_per_day == paced.completed_units

    def test_a_paced_target_is_not_a_sustained_target(self, demo_factory):
        """The defect Audit B found, pinned."""
        machines = [
            m.model_copy(update={"capacity": m.capacity + 1})
            if m.id in ("m-screwdriving", "m-assembly")
            else m
            for m in demo_factory.machines
        ]
        plan_d = demo_factory.model_copy(
            update={"machines": machines, "operators_available": demo_factory.operators_available + 2}
        )

        paced = run_simulation(plan_d, plan_d.products[0].id)
        assert paced.demand_met is True
        assert paced.completed_units == 1900

        measurement = measure_capacity(plan_d, plan_d.products[0].id, target_units_per_day=1900.0)
        assert measurement.capacity_units_per_day < 1900
        assert measurement.meets_target_at_capacity is False

    def test_headroom_is_reported_in_whole_percent(self, demo_factory):
        measurement = measure_capacity(demo_factory, demo_factory.products[0].id)
        assert measurement.headroom_percent == int(measurement.headroom_percent)

    def test_capacity_costs_exactly_one_simulation(self, demo_factory, monkeypatch):
        import app.services.simulation as simulation_module

        calls = {"n": 0}
        real = simulation_module.run_simulation

        def counted(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(simulation_module, "run_simulation", counted)
        measure_capacity(demo_factory, demo_factory.products[0].id)
        assert calls["n"] == 1

    def test_the_measurement_is_deterministic(self, demo_factory):
        results = [
            measure_capacity(demo_factory, demo_factory.products[0].id).capacity_units_per_day
            for _ in range(3)
        ]
        assert len(set(results)) == 1


# R6 — ranking must not reward missing information

class TestRankingIsEpistemicallySafe:
    def _metrics(self, candidate_id: str, capex: float, complete: bool):
        from app.services.ranking import _Metrics

        return _Metrics(
            candidate_id=candidate_id,
            demand_met=True,
            demand_gap=0.0,
            completed_units=1900,
            known_capex=capex,
            commercially_complete=complete,
            wip=0,
            avg_flow_time=142.0,
            added_machine_count=0,
            action_count=1,
        )

    def test_an_unknown_cost_does_not_sort_ahead_of_a_known_one(self):
        from app.models.optimization import OptimizationObjective
        from app.services.ranking import _ranking_key

        key = _ranking_key(OptimizationObjective.MEET_DEMAND)
        priced = self._metrics("priced", 80_000.0, True)
        unpriced = self._metrics("unpriced", 0.0, False)

        assert key(priced) < key(unpriced), (
            "a plan with an unknown cost sorted ahead of a fully-costed one"
        )

    def test_between_two_costed_plans_the_cheaper_still_wins(self):
        from app.models.optimization import OptimizationObjective
        from app.services.ranking import _ranking_key

        key = _ranking_key(OptimizationObjective.MEET_DEMAND)
        cheap = self._metrics("cheap", 10_000.0, True)
        dear = self._metrics("dear", 80_000.0, True)
        assert key(cheap) < key(dear)

    def test_between_two_incomplete_plans_cost_does_not_decide(self):
        """A partial sum against a partial sum is not a comparison."""
        small_partial = self._metrics("small", 0.0, False)
        large_partial = self._metrics("large", 205_000.0, False)
        assert small_partial.comparable_capex == large_partial.comparable_capex == 0.0

    def test_a_genuine_zero_on_a_complete_plan_is_still_zero(self):
        free_and_known = self._metrics("free", 0.0, True)
        assert free_and_known.comparable_capex == 0.0
        assert free_and_known.cost_incomplete == 0.0
