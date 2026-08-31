"""Phase 8B tests — multi-strategy optimization arena."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.models.strategy import (
    CostCategory,
    CostComponent,
    InformationGapType,
    OptimizationStrategyFamily,
    StrategyCostProfile,
    StrategyQueryIntent,
    StrategySearchBudget,
    UserCostInput,
)
from app.services.strategy_language import known_cost_phrase
from app.services.requirements_parser import DeterministicFallbackRequirementsParser
from app.services.strategy_arena import StrategyArena, compute_frontiers, recommend
from app.services.strategy_comparison import compare_strategies
from app.services.strategy_query import (
    answer_strategy_query,
    detect_intent,
    parse_cost_inputs,
    reprice_arena,
)

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture(scope="module")
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


def reqs(**overrides) -> PlanningRequirements:
    base = dict(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1900.0)
    base.update(overrides)
    return PlanningRequirements(**base)


@pytest.fixture(scope="module")
def arena_result(electronics_factory):
    """The primary 1900/day exploration, run ONCE and shared — it is the
    most expensive fixture in this file."""
    result, sessions = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
    return result, sessions


def by_family(result, family: OptimizationStrategyFamily):
    return next((o for o in result.strategies if o.family is family), None)


# STRATEGY GENERATION


class TestStrategyGeneration:
    def test_several_distinct_families_are_produced(self, arena_result):
        result, _ = arena_result
        families = {o.family for o in result.strategies}
        assert len(result.strategies) >= 3
        assert OptimizationStrategyFamily.EQUIPMENT_EXPANSION in families
        assert OptimizationStrategyFamily.SHIFT_EXPANSION in families
        assert OptimizationStrategyFamily.HYBRID in families

    def test_every_strategy_is_operationally_verified(self, arena_result):
        """The core promise: each option is a real simulation, not a
        projection."""
        result, sessions = arena_result
        for option in result.strategies:
            assert option.operationally_verified is True
            assert option.strategy_id in sessions
            assert sessions[option.strategy_id].iterations

    def test_each_strategy_uses_only_its_family_levers(self, arena_result):
        """A family is DEFINED by its permitted actions, and the underlying
        Phase 4 machinery must actually honour that."""
        from app.services.strategy_arena import FAMILY_ACTION_TYPES

        result, _ = arena_result
        for option in result.strategies:
            allowed = FAMILY_ACTION_TYPES[option.family]
            if allowed is None:
                continue  # HYBRID is unrestricted by design
            assert set(option.actions.action_types) <= set(allowed), option.label

    def test_the_search_is_deterministic(self, electronics_factory):
        """Same inputs, same options, same order, same ids — nothing here
        samples or shuffles."""
        first, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        second, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        assert [o.strategy_id for o in first.strategies] == [o.strategy_id for o in second.strategies]
        assert first.model_dump(exclude={"stats"}) == second.model_dump(exclude={"stats"})

    def test_no_duplicate_strategies_are_shown(self, arena_result):
        """HYBRID frequently rediscovers a single-lever plan; showing it
        twice would be fake diversity."""
        result, _ = arena_result
        signatures = {
            (
                tuple(sorted(o.actions.added_machine_ids)),
                o.actions.added_shift_count,
                o.actions.operator_delta,
                tuple(sorted(o.actions.buffer_changes)),
                o.metrics.completed_units,
            )
            for o in result.strategies
        }
        assert len(signatures) == len(result.strategies)

    def test_a_family_the_user_excluded_says_so_rather_than_blaming_evidence(self, electronics_factory):
        """
        `families_without_options` is user-facing, so its wording is a factual claim.
        """
        result, _ = StrategyArena(budget=StrategySearchBudget(include_hybrid=False)).explore(
            electronics_factory, PRODUCT_ID,
            reqs(allowed_action_types=["ADD_PARALLEL_MACHINE"]),
        )

        excluded = [e for e in result.families_without_options if "excluded by the request" in e]
        assert excluded, result.families_without_options
        assert not any(
            "no evidence" in e and "SHIFT_EXPANSION" in e for e in result.families_without_options
        )

    def test_families_without_evidence_are_reported_not_hidden(self, arena_result):
        """A family that had nothing to offer must say so — silence would
        read as 'not considered'."""
        result, _ = arena_result
        assert result.families_without_options
        assert any("WORKFORCE_EXPANSION" in entry for entry in result.families_without_options)

    def test_action_count_respects_the_budget(self, electronics_factory):
        budget = StrategySearchBudget(max_actions_per_strategy=1)
        result, _ = StrategyArena(budget=budget).explore(electronics_factory, PRODUCT_ID, reqs())
        assert result.strategies
        for option in result.strategies:
            assert option.actions.action_count <= 1, option.label

    def test_a_tight_simulation_budget_stops_early_rather_than_half_exploring(self, electronics_factory):
        """A truncated strategy would be an UNVERIFIED strategy on screen,
        so the search declines to start a family it cannot finish."""
        budget = StrategySearchBudget(max_total_simulations=20)
        result, _ = StrategyArena(budget=budget).explore(electronics_factory, PRODUCT_ID, reqs())
        assert result.stats.budget_exhausted is True
        assert any("budget exhausted" in entry for entry in result.families_without_options)
        # Whatever survived is still fully verified.
        for option in result.strategies:
            assert option.operationally_verified is True

    def test_max_strategy_families_is_honoured(self, electronics_factory):
        budget = StrategySearchBudget(max_strategy_families=2)
        result, _ = StrategyArena(budget=budget).explore(electronics_factory, PRODUCT_ID, reqs())
        assert result.stats.families_attempted <= 2

    def test_hybrid_can_be_disabled(self, electronics_factory):
        budget = StrategySearchBudget(include_hybrid=False)
        result, _ = StrategyArena(budget=budget).explore(electronics_factory, PRODUCT_ID, reqs())
        assert all(o.family is not OptimizationStrategyFamily.HYBRID for o in result.strategies)

    def test_the_baseline_factory_is_never_mutated(self, electronics_factory):
        before = electronics_factory.model_dump_json()
        StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        assert electronics_factory.model_dump_json() == before

    def test_the_memo_saves_repeated_work_without_changing_answers(self, electronics_factory):
        """The cache is an optimisation, never a semantic change."""
        cached, _ = StrategyArena(use_cache=True).explore(electronics_factory, PRODUCT_ID, reqs())
        uncached, _ = StrategyArena(use_cache=False).explore(electronics_factory, PRODUCT_ID, reqs())

        assert cached.model_dump(exclude={"stats"}) == uncached.model_dump(exclude={"stats"})
        assert cached.stats.cache_hits > 0
        assert cached.stats.simulations_run < uncached.stats.simulations_run

    def test_simulations_are_counted_even_with_the_cache_off(self, electronics_factory):
        """Counting is measurement; reuse is the optimisation."""
        result, _ = StrategyArena(use_cache=False).explore(electronics_factory, PRODUCT_ID, reqs())
        assert result.stats.simulations_run > 0
        assert result.stats.cache_hits == 0

    def test_the_simulation_budget_is_enforced_with_the_cache_off(self, electronics_factory):
        result, _ = StrategyArena(
            budget=StrategySearchBudget(max_total_simulations=20), use_cache=False,
        ).explore(electronics_factory, PRODUCT_ID, reqs())

        assert result.stats.budget_exhausted
        assert any("budget exhausted" in entry for entry in result.families_without_options)


# COST SEMANTICS


class TestCostSemantics:
    def test_machine_capex_is_known_and_taken_from_factory_data(self, arena_result):
        result, _ = arena_result
        equipment = by_family(result, OptimizationStrategyFamily.EQUIPMENT_EXPANSION)
        assert equipment is not None
        assert equipment.cost.known_capex > 0
        assert equipment.commercially_complete is True
        assert equipment.cost.information_gaps == []

    def test_a_shift_costs_something_unknown_never_zero(self, arena_result):
        """The headline rule. EUR 0 of KNOWN CAPEX is not a price."""
        result, _ = arena_result
        shift = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        assert shift is not None
        assert shift.commercially_complete is False
        assert [g.gap_type for g in shift.cost.information_gaps] == [InformationGapType.SHIFT_COST]
        unknown = [c for c in shift.cost.components if c.amount is None]
        assert unknown, "the shift must appear as an unpriced component, not be absent"

    def test_an_unknown_cost_is_never_described_as_cheaper(self, arena_result):
        """Wording matters: 'lowest known CAPEX' is true; 'cheapest' is not."""
        result, _ = arena_result
        for option in result.strategies:
            if option.commercially_complete:
                continue
            blob = " ".join([option.rationale, *option.tradeoffs]).lower()
            assert "cheapest" not in blob
            assert "cheaper" not in blob
            assert "incomplete" in blob or "unpriced" in blob

    def test_nothing_priced_means_nobody_is_the_lowest(self, electronics_factory):
        """A concept whose equipment has no price yet must not rank on price."""
        unpriced = electronics_factory.model_copy(
            update={
                "machines": [m.model_copy(update={"purchase_cost": None}) for m in electronics_factory.machines],
                "budget": None,
            }
        )
        result, _ = StrategyArena().explore(unpriced, PRODUCT_ID, reqs())

        assert result.strategies, "the fixture is only meaningful with options to compare"
        assert {o.cost.known_capex for o in result.strategies} == {0.0}
        for option in result.strategies:
            assert not any("lowest known capex" in t.lower() for t in option.tradeoffs), (
                f"{option.strategy_id} claims to be the lowest when nothing is priced"
            )
            assert option.commercially_complete is False
            assert any("cannot be ranked on cost" in w.lower() for w in option.warnings)

    def test_a_real_price_difference_is_still_stated(self, arena_result):
        """The suppression above must not silence a genuine comparison."""
        result, _ = arena_result
        if len({o.cost.known_capex for o in result.strategies}) <= 1:
            pytest.skip("this fixture happens not to separate the options on cost")
        cheapest = min(result.strategies, key=lambda o: o.cost.known_capex)
        assert any("lowest known capex" in t.lower() for t in cheapest.tradeoffs)

    def test_cost_components_carry_a_category(self, arena_result):
        result, _ = arena_result
        for option in result.strategies:
            for component in option.cost.components:
                assert isinstance(component.category, CostCategory)

    def test_shift_is_opex_per_day_and_operators_opex_per_year(self, arena_result):
        """CAPEX and OPEX are different kinds of number (section 19)."""
        result, _ = arena_result
        shift = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        assert any(c.category is CostCategory.OPEX_PER_DAY for c in shift.cost.components)

        hybrid = by_family(result, OptimizationStrategyFamily.HYBRID)
        if hybrid and hybrid.actions.operator_delta:
            assert any(c.category is CostCategory.OPEX_PER_YEAR for c in hybrid.cost.components)

    def test_known_capex_sums_only_capex(self, arena_result):
        """A per-day operating cost must never leak into a CAPEX figure."""
        result, _ = arena_result
        for option in result.strategies:
            capex_components = [
                c.amount for c in option.cost.components
                if c.category is CostCategory.CAPEX and c.amount is not None
            ]
            assert option.cost.known_capex == pytest.approx(sum(capex_components))

    def test_a_user_supplied_cost_fills_the_gap(self, electronics_factory):
        costs = [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0, category=CostCategory.OPEX_PER_DAY,
        )]
        result, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs(), user_costs=costs)
        shift = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        assert shift is not None
        assert shift.commercially_complete is True
        assert shift.cost.information_gaps == []
        supplied = [c for c in shift.cost.components if c.source == "USER"]
        assert supplied and supplied[0].amount == 18_000.0

    def test_supplying_a_cost_never_changes_the_engineering(self, electronics_factory):
        """A price cannot move a machine."""
        plain, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        priced, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, reqs(),
            user_costs=[UserCostInput(
                gap_type=InformationGapType.SHIFT_COST, amount=18_000.0, category=CostCategory.OPEX_PER_DAY,
            )],
        )
        assert [o.metrics.model_dump() for o in plain.strategies] == [o.metrics.model_dump() for o in priced.strategies]
        assert [o.actions.model_dump() for o in plain.strategies] == [o.actions.model_dump() for o in priced.strategies]

    def test_information_gaps_say_exactly_what_is_needed(self, arena_result):
        result, _ = arena_result
        gaps = [g for o in result.strategies for g in o.cost.information_gaps]
        assert gaps
        for gap in gaps:
            assert gap.description
            assert gap.expected_category in set(CostCategory)
            assert gap.required_for == "commercial comparison"
            assert gap.severity == "BLOCKING"


# PARETO


class TestParetoFrontiers:
    def test_two_separate_frontiers_are_produced(self, arena_result):
        result, _ = arena_result
        assert result.frontiers.operational_frontier
        assert "known_capex" in result.frontiers.commercial_dimensions
        assert "known_capex" not in result.frontiers.operational_dimensions

    def test_only_fully_priced_strategies_reach_the_commercial_frontier(self, arena_result):
        """Structurally why an unpriced option can never dominate on cost:
        it is never compared on cost at all."""
        result, _ = arena_result
        complete_ids = {o.strategy_id for o in result.strategies if o.commercially_complete}
        assert set(result.frontiers.commercially_complete_frontier) <= complete_ids

    def test_an_unpriced_strategy_never_dominates_a_priced_one_on_cost(self, arena_result):
        result, _ = arena_result
        incomplete = [o for o in result.strategies if not o.commercially_complete]
        assert incomplete, "fixture should contain at least one unpriced option"
        for option in incomplete:
            assert option.strategy_id not in result.frontiers.commercially_complete_frontier

    def test_a_dominated_strategy_is_recorded_as_dominated(self, arena_result):
        """Plan C (process improvement) is worse on gap AND uses more
        changes, so something must dominate it."""
        result, _ = arena_result
        dominated = [
            sid for sid, dominators in result.frontiers.dominated_by.items() if dominators
        ]
        assert dominated
        for sid in dominated:
            assert sid not in result.frontiers.operational_frontier

    def test_frontier_membership_is_deterministic(self, electronics_factory):
        first, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        second, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        assert first.frontiers.model_dump() == second.frontiers.model_dump()

    def test_an_empty_arena_produces_empty_frontiers_not_a_crash(self):
        frontiers = compute_frontiers([])
        assert frontiers.operational_frontier == []
        assert frontiers.commercially_complete_frontier == []


# PREFERENCES — soft vs hard (section 13)


class TestPreferences:
    @pytest.fixture
    def parser(self):
        return DeterministicFallbackRequirementsParser()

    def test_do_not_buy_is_a_hard_constraint(self, parser):
        requirements = parser.parse("We need 1900 units/day. Do not buy another machine.").parsed_requirements
        assert requirements.allowed_action_types is not None
        assert "ADD_PARALLEL_MACHINE" not in requirements.allowed_action_types
        assert requirements.prefer_no_new_machines is False

    def test_avoid_if_possible_is_a_soft_preference(self, parser):
        """The distinction that matters: a preference must never remove an
        option from consideration."""
        requirements = parser.parse(
            "We need 1900 units/day but avoid buying another machine if possible."
        ).parsed_requirements
        assert requirements.allowed_action_types is None
        assert requirements.prefer_no_new_machines is True

    def test_a_hard_constraint_produces_no_new_machines_anywhere(self, electronics_factory):
        requirements = reqs(allowed_action_types=sorted(
            {"CHANGE_SHIFT_CONFIGURATION", "CHANGE_OPERATOR_CAPACITY", "CHANGE_BUFFER_CAPACITY",
             "CHANGE_MACHINE_CYCLE_TIME", "CHANGE_MACHINE_CAPACITY"}
        ))
        result, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, requirements)
        assert result.strategies
        for option in result.strategies:
            assert option.actions.added_machine_count == 0, option.label

    def test_a_soft_preference_still_explores_equipment(self, electronics_factory):
        """It orders; it does not hide."""
        result, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, reqs(prefer_no_new_machines=True),
        )
        assert any(o.actions.added_machine_count > 0 for o in result.strategies)

    def test_a_soft_preference_surfaces_a_machine_free_alternative(self, electronics_factory):
        """Section 11: asking to avoid equipment must actually explore a
        machine-free combination, not just rank the ones already found."""
        result, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, reqs(prefer_no_new_machines=True),
        )
        machine_free = [o for o in result.strategies if o.actions.added_machine_count == 0 and o.actions.action_count]
        assert machine_free
        recommended = next(o for o in result.strategies if o.strategy_id == result.recommended_strategy_id)
        # If a machine-free option reaches the target, it should be the one
        # offered first under this preference.
        if any(o.metrics.goal_met for o in machine_free):
            assert recommended.actions.added_machine_count == 0

    def test_a_preference_never_beats_actually_reaching_the_target(self, electronics_factory):
        """Soft means soft: an option that misses the goal must not be
        recommended over one that meets it just because it avoids
        machines."""
        result, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, reqs(prefer_no_new_machines=True, prefer_few_changes=True),
        )
        recommended = next(o for o in result.strategies if o.strategy_id == result.recommended_strategy_id)
        if any(o.metrics.goal_met for o in result.strategies):
            assert recommended.metrics.goal_met is True

    def test_family_restriction_limits_exploration(self, electronics_factory):
        requirements = reqs(allowed_strategy_families=["SHIFT_EXPANSION", "WORKFORCE_EXPANSION"])
        result, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, requirements)
        assert {o.family for o in result.strategies} <= {
            OptimizationStrategyFamily.SHIFT_EXPANSION,
            OptimizationStrategyFamily.WORKFORCE_EXPANSION,
        }

    def test_fewest_changes_preference_orders_but_does_not_sacrifice_the_target(self, electronics_factory):
        """Section 12 explicitly: do not trade demand fulfilment for a
        smaller change count."""
        result, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs(prefer_few_changes=True))
        recommended = next(o for o in result.strategies if o.strategy_id == result.recommended_strategy_id)
        one_action_misses = [o for o in result.strategies if o.actions.action_count == 1 and not o.metrics.goal_met]
        assert one_action_misses, "fixture should contain a cheap option that misses"
        if any(o.metrics.goal_met for o in result.strategies):
            assert recommended.metrics.goal_met is True

    def test_recommendation_is_deterministic(self, electronics_factory):
        a, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        b, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, reqs())
        assert a.recommended_strategy_id == b.recommended_strategy_id

    def test_no_options_means_no_recommendation(self):
        assert recommend([], reqs()) is None


# COMPARISON


class TestStrategyComparison:
    def test_exact_kpi_comparison(self, arena_result):
        result, _ = arena_result
        a, b = result.strategies[0], result.strategies[1]
        comparison = compare_strategies(a, b)

        completed = next(m for m in comparison.metrics if m.metric == "completed_units")
        assert completed.value_a == a.metrics.completed_units
        assert completed.value_b == b.metrics.completed_units
        assert completed.delta == b.metrics.completed_units - a.metrics.completed_units

    def test_costs_are_compared_by_category_and_never_summed(self, arena_result):
        result, _ = arena_result
        a = by_family(result, OptimizationStrategyFamily.EQUIPMENT_EXPANSION)
        b = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        comparison = compare_strategies(a, b)

        categories = [row.metric for row in comparison.cost_rows]
        assert len(categories) == len(set(categories))
        assert any(row.metric == "cost_capex" for row in comparison.cost_rows)
        # No row aggregates across categories.
        assert not any(row.metric == "cost_total" for row in comparison.cost_rows)

    def test_an_unknown_cost_produces_a_null_delta_not_a_zero(self, arena_result):
        result, _ = arena_result
        a = by_family(result, OptimizationStrategyFamily.EQUIPMENT_EXPANSION)
        b = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        comparison = compare_strategies(a, b)

        opex = next(row for row in comparison.cost_rows if row.metric == "cost_opex_per_day")
        assert opex.value_b is None
        assert opex.delta is None

    def test_comparability_on_cost_is_stated_explicitly(self, arena_result):
        result, _ = arena_result
        a = by_family(result, OptimizationStrategyFamily.EQUIPMENT_EXPANSION)
        b = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        comparison = compare_strategies(a, b)

        assert comparison.comparable_on_cost is False
        assert any("not comparable on cost" in n.lower() for n in comparison.notes)
        assert any("does not mean cheaper" in n.lower() for n in comparison.notes)

    def test_the_headline_leads_with_reaching_the_target(self, arena_result):
        result, _ = arena_result
        reached = next(o for o in result.strategies if o.metrics.goal_met)
        missed = next(o for o in result.strategies if not o.metrics.goal_met)
        comparison = compare_strategies(missed, reached)
        assert comparison.headline.startswith(f"{reached.label} reaches the target")

    def test_information_gaps_travel_with_the_comparison(self, arena_result):
        result, _ = arena_result
        a = by_family(result, OptimizationStrategyFamily.EQUIPMENT_EXPANSION)
        b = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        comparison = compare_strategies(a, b)
        assert comparison.information_gaps_a == []
        assert comparison.information_gaps_b

    def test_comparison_uses_no_network(self, arena_result, monkeypatch):
        """Not a config assertion: block every outbound socket and compare."""
        import socket

        def _blocked(self, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) and address else ""
            if host not in ("127.0.0.1", "::1", "localhost", ""):
                raise AssertionError("Strategy comparison must be pure arithmetic — no network.")
            return None

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        result, _ = arena_result
        comparison = compare_strategies(result.strategies[0], result.strategies[1])
        assert comparison.headline
        assert comparison.metrics


# API


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app)


@pytest.fixture
def factory_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


class TestStrategyApi:
    def test_explore_returns_verified_options_and_their_sessions(self, client, factory_json):
        response = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID,
            "user_request": "We need 1900 units/day. Show me the best options.",
        })
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["arena"]["strategies"]
        for option in body["arena"]["strategies"]:
            # Section 22: the exact verified session must travel with it, so
            # opening a card needs no recomputation.
            assert option["strategy_id"] in body["sessions"]
            session = body["sessions"][option["strategy_id"]]
            assert session["iterations"]
            assert session["final_snapshot"]["simulation"]["completed_units"] == option["metrics"]["completed_units"]

    def test_planning_source_is_always_deterministic(self, client, factory_json):
        """Strategy KPIs come from the simulator no matter who read the
        sentence."""
        response = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID, "user_request": "We need 1900 units/day.",
        })
        assert response.json()["provenance"]["planning_source"] == "DETERMINISTIC"

    def test_unknown_product_is_a_400(self, client, factory_json):
        response = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": "p-nope", "user_request": "We need 1900 units/day.",
        })
        assert response.status_code == 400

    def test_invalid_factory_is_a_422(self, client):
        response = client.post("/strategies/explore", json={
            "factory": {"name": "broken"}, "product_id": PRODUCT_ID, "user_request": "We need 1900 units/day.",
        })
        assert response.status_code == 422

    def test_compare_endpoint_is_pure(self, client, factory_json):
        explored = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID, "user_request": "We need 1900 units/day.",
        }).json()
        strategies = explored["arena"]["strategies"]

        response = client.post("/strategies/compare", json={
            "strategy_a": strategies[0], "strategy_b": strategies[1],
        })
        assert response.status_code == 200, response.text
        comparison = response.json()
        assert comparison["headline"]
        assert comparison["metrics"]
        assert comparison["strategy_a_id"] == strategies[0]["strategy_id"]

    def test_user_costs_reach_the_arena_through_the_api(self, client, factory_json):
        response = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID,
            "user_request": "We need 1900 units/day.",
            "user_costs": [{"gap_type": "SHIFT_COST", "amount": 18000.0, "category": "OPEX_PER_DAY"}],
        })
        body = response.json()
        shift = next(
            (o for o in body["arena"]["strategies"] if o["family"] == "SHIFT_EXPANSION"), None,
        )
        assert shift is not None
        assert shift["commercially_complete"] is True
        assert shift["cost"]["information_gaps"] == []


# CONVERSATION (section 15) Follow-ups are answered from the arena the user is already
# looking at.


class TestStrategyConversation:
    def test_show_me_a_cheaper_option(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "Show me a cheaper option.")

        assert answer.intent is StrategyQueryIntent.CHEAPER_OPTION
        assert answer.strategy_ids
        assert answer.simulations_run == 0

    def test_a_cheaper_answer_never_calls_an_unpriced_plan_cheaper(self, arena_result):
        result, _ = arena_result
        incomplete = [o for o in result.strategies if not o.commercially_complete]
        assert incomplete, "fixture must contain an unpriced option for this to mean anything"

        answer = answer_strategy_query(result, "Show me a cheaper option.")
        text = answer.answer.lower()

        # The distinction the whole phase exists for: a known figure is a
        # fact; "cheaper" would be a claim nobody has established.
        assert "not a full price" in text or "is fully priced" in text

        # G14 changed what this line pins.
        for option in result.strategies:
            if option.commercially_complete or option.cost.known_by_category:
                continue
            assert f"{option.label.lower()} shows no established cost yet" in text or (
                f"{option.label.lower()} cannot be ranked financially" in text
            ), f"{option.label} has no established cost and must not be quoted a figure"
        assert "eur 0" not in text or any(o.commercially_complete for o in result.strategies)

        # A comparative needs something to compare against.
        if "a lower known capital cost" in text:
            priced = [o for o in result.strategies if o.commercially_complete]
            assert priced and min(o.cost.known_capex for o in incomplete) < max(
                o.cost.known_capex for o in priced
            )

    def test_without_another_machine(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "Can we do it without another machine?")

        assert answer.intent is StrategyQueryIntent.NO_NEW_MACHINE
        if answer.strategy_ids:
            named = next(o for o in result.strategies if o.strategy_id == answer.strategy_ids[0])
            assert named.actions.added_machine_count == 0

    def test_a_machine_free_answer_is_scoped_to_what_was_explored(self, electronics_factory):
        # With equipment as the ONLY permitted family there is by
        # construction no machine-free option. The answer must say the
        # search found none, not that none exists.
        result, _ = StrategyArena(
            budget=StrategySearchBudget(include_hybrid=False),
        ).explore(
            electronics_factory, PRODUCT_ID,
            reqs(allowed_strategy_families=["EQUIPMENT_EXPANSION"]),
        )
        answer = answer_strategy_query(result, "Can we do it without another machine?")
        assert "explored" in answer.answer.lower()

    def test_which_plan_uses_the_fewest_changes(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "Which plan uses the fewest changes?")

        assert answer.intent is StrategyQueryIntent.FEWEST_CHANGES
        named = next(o for o in result.strategies if o.strategy_id == answer.strategy_ids[0])

        # Fewest changes AMONG THOSE THAT REACH THE TARGET: a one-action
        # plan that misses the goal is not a simpler way to do the job.
        reaching = [o for o in result.strategies if o.metrics.goal_met]
        pool = reaching or result.strategies
        assert named.actions.action_count == min(o.actions.action_count for o in pool)
        # str.capitalize() lowercases everything after the first character,
        # which once turned "Plan D" into "Plan d" mid-sentence.
        assert named.label in answer.answer
        assert named.label.lower() not in answer.answer.replace(named.label, "")

    def test_compare_two_named_plans(self, arena_result):
        result, _ = arena_result
        a, b = result.strategies[0], result.strategies[1]
        answer = answer_strategy_query(result, f"Compare {a.label} and {b.label}.")

        assert answer.intent is StrategyQueryIntent.COMPARE
        assert answer.comparison is not None
        assert answer.comparison.strategy_a_id == a.strategy_id
        assert answer.comparison.strategy_b_id == b.strategy_id

    def test_compare_with_one_named_plan_asks_rather_than_guesses(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, f"Compare {result.strategies[0].label} with the rest.")

        assert answer.comparison is None
        assert "two options" in answer.answer.lower()

    def test_what_information_do_we_still_need(self, arena_result):
        result, _ = arena_result
        incomplete = next(o for o in result.strategies if not o.commercially_complete)
        answer = answer_strategy_query(
            result, f"What information do we still need before choosing {incomplete.label}?"
        )

        assert answer.intent is StrategyQueryIntent.INFORMATION_NEEDED
        assert answer.information_gaps
        assert answer.strategy_ids == [incomplete.strategy_id]
        # Section 17: name the missing input, do not merely flag it.
        assert any(g.description.rstrip(".") in answer.answer for g in incomplete.cost.information_gaps)

    @pytest.mark.parametrize(
        "text,gap,amount,category",
        [
            ("An extra shift costs EUR 18k/day.", InformationGapType.SHIFT_COST, 18_000.0, CostCategory.OPEX_PER_DAY),
            ("Two additional operators cost 90k/year.", InformationGapType.OPERATOR_COST, 90_000.0, CostCategory.OPEX_PER_YEAR),
            ("Buffer extension costs 6k.", InformationGapType.BUFFER_MODIFICATION_COST, 6_000.0, CostCategory.ONE_TIME_OTHER),
        ],
    )
    def test_a_cost_statement_is_parsed_into_a_typed_input(self, text, gap, amount, category):
        inputs = parse_cost_inputs(text)
        assert len(inputs) == 1
        assert inputs[0].gap_type is gap
        assert inputs[0].amount == amount
        # Section 19: the time basis the user gave is preserved, never
        # converted into some other basis they did not state.
        assert inputs[0].category is category

    def test_two_costs_in_one_sentence_stay_separate(self):
        inputs = parse_cost_inputs("A shift costs 18k/day and two operators cost 90k/year.")
        assert {i.gap_type for i in inputs} == {InformationGapType.SHIFT_COST, InformationGapType.OPERATOR_COST}
        assert {i.category for i in inputs} == {CostCategory.OPEX_PER_DAY, CostCategory.OPEX_PER_YEAR}

    def test_a_planning_request_is_not_mistaken_for_a_cost_statement(self):
        assert detect_intent("We need 1900 units/day, budget 220k.") is StrategyQueryIntent.UNRECOGNIZED

    def test_an_unrelated_question_is_not_answered_with_the_nearest_match(self, arena_result):
        result, _ = arena_result
        answer = answer_strategy_query(result, "What is the weather in Berlin?")
        assert answer.intent is StrategyQueryIntent.UNRECOGNIZED
        assert not answer.strategy_ids

    def test_providing_a_cost_re_evaluates_the_commercial_ranking(self, arena_result):
        result, sessions = arena_result
        assert [o for o in result.strategies if not o.commercially_complete]

        answer = answer_strategy_query(
            result, "An extra shift costs 18k/day and two operators cost 90k/year."
        )
        assert answer.requires_repricing

        repriced = reprice_arena(result, sessions, answer.cost_inputs)
        newly_complete = [
            o for o in repriced.strategies
            if o.commercially_complete
            and not next(s for s in result.strategies if s.strategy_id == o.strategy_id).commercially_complete
        ]
        assert newly_complete, "supplying shift and operator costs must complete at least one profile"

        # The commercial frontier could not have admitted them before.
        for option in newly_complete:
            assert option.strategy_id not in result.frontiers.commercially_complete_frontier

    def test_repricing_never_changes_the_engineering(self, arena_result):
        result, sessions = arena_result
        repriced = reprice_arena(result, sessions, [
            UserCostInput(gap_type=InformationGapType.SHIFT_COST, amount=18_000, category=CostCategory.OPEX_PER_DAY),
            UserCostInput(gap_type=InformationGapType.OPERATOR_COST, amount=90_000, category=CostCategory.OPEX_PER_YEAR),
        ])

        for after in repriced.strategies:
            before = next(o for o in result.strategies if o.strategy_id == after.strategy_id)
            # A price cannot move a machine. Every verified number is
            # identical; only money changed.
            assert after.metrics == before.metrics
            assert after.actions == before.actions
            assert after.operationally_verified is True
        assert repriced.baseline_metrics == result.baseline_metrics

    def test_repricing_with_no_costs_is_a_no_op(self, arena_result):
        result, sessions = arena_result
        assert reprice_arena(result, sessions, []) is result

    def test_answering_never_touches_the_network(self, arena_result, monkeypatch):
        import socket

        def _blocked(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("strategy follow-ups must be answered from existing data")

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        result, _ = arena_result
        for question in (
            "Show me a cheaper option.",
            "Can we do it without another machine?",
            "Which plan uses the fewest changes?",
            "What information do we still need?",
        ):
            assert answer_strategy_query(result, question).simulations_run == 0

    def test_ask_endpoint_answers_without_replanning(self, client, arena_result):
        result, _ = arena_result
        response = client.post("/strategies/ask", json={
            "arena": result.model_dump(mode="json"),
            "question": "Which plan uses the fewest changes?",
        })
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["answer"]["intent"] == "FEWEST_CHANGES"
        assert body["repriced"] is False
        # Untouched: same options, same order, same numbers.
        assert body["arena"]["strategies"] == result.model_dump(mode="json")["strategies"]

    def test_ask_endpoint_reprices_when_a_cost_is_supplied(self, client, arena_result):
        result, sessions = arena_result
        response = client.post("/strategies/ask", json={
            "arena": result.model_dump(mode="json"),
            "question": "An extra shift costs 18k/day and two operators cost 90k/year.",
            "sessions": {k: v.model_dump(mode="json") for k, v in sessions.items()},
        })
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["answer"]["intent"] == "PROVIDE_COST"
        assert body["repriced"] is True
        assert body["arena"]["baseline_metrics"] == result.model_dump(mode="json")["baseline_metrics"]
        assert any(o["commercially_complete"] for o in body["arena"]["strategies"])


# G13 - ESTABLISHED INPUTS SURVIVE REFINEMENT From the human golden run.

SHIFT_18K = {"gap_type": "SHIFT_COST", "amount": 18_000.0, "category": "OPEX_PER_DAY"}


class TestEstablishedCostsSurviveRefinement:
    """G13. A rebuild is entitled to derived state, not to stated facts."""

    def test_refinement_carrying_the_cost_keeps_the_plan_priced(self, client, factory_json):
        """A. The reproduced defect, as the fixed client now drives it."""
        first = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID,
            "user_request": "We need 1900 units/day.",
            "user_costs": [SHIFT_18K],
        })
        assert first.status_code == 200, first.text
        before = next(
            o for o in first.json()["arena"]["strategies"] if o["family"] == "SHIFT_EXPANSION"
        )
        assert before["commercially_complete"] is True

        refined = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID,
            "user_request": "Do it without buying another machine.",
            "prior_requests": ["We need 1900 units/day."],
            "user_costs": [SHIFT_18K],
        })
        assert refined.status_code == 200, refined.text
        strategies = refined.json()["arena"]["strategies"]
        after = next((o for o in strategies if o["family"] == "SHIFT_EXPANSION"), None)
        assert after is not None, "the shift plan must survive a no-new-machines constraint"
        assert after["commercially_complete"] is True
        assert after["cost"]["information_gaps"] == []
        assert not any(
            gap["gap_type"] == "SHIFT_COST"
            for option in strategies for gap in option["cost"]["information_gaps"]
        ), "the shift cost was established; no option may report it as unknown again"

    def test_refinement_without_the_cost_reproduces_the_defect(self, client, factory_json):
        """A, from the other side: the bug was real, and this is its shape."""
        refined = client.post("/strategies/explore", json={
            "factory": factory_json, "product_id": PRODUCT_ID,
            "user_request": "Do it without buying another machine.",
            "prior_requests": ["We need 1900 units/day."],
        })
        assert refined.status_code == 200, refined.text
        shift = next(
            (o for o in refined.json()["arena"]["strategies"] if o["family"] == "SHIFT_EXPANSION"),
            None,
        )
        assert shift is not None
        assert shift["commercially_complete"] is False
        assert [g["gap_type"] for g in shift["cost"]["information_gaps"]] == ["SHIFT_COST"]

    def test_provenance_survives_the_rebuild(self, electronics_factory):
        """B. The figure comes back attributed to the engineer, not invented."""
        costs = [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
            category=CostCategory.OPEX_PER_DAY, note="An extra shift costs EUR 18k/day.",
        )]
        result, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID,
            reqs(prefer_no_new_machines=True), user_costs=costs,
        )
        shift = by_family(result, OptimizationStrategyFamily.SHIFT_EXPANSION)
        assert shift is not None

        supplied = [c for c in shift.cost.components if c.amount == 18_000.0]
        assert supplied, "the established figure must appear in the rebuilt profile"
        for component in supplied:
            assert component.source == "USER"
            assert component.category is CostCategory.OPEX_PER_DAY

    def test_an_established_cost_is_not_charged_to_a_plan_that_does_not_use_it(
        self, electronics_factory,
    ):
        """D. Established is not the same as charged."""
        result, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, reqs(),
            user_costs=[UserCostInput(
                gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
                category=CostCategory.OPEX_PER_DAY,
            )],
        )
        for option in result.strategies:
            if option.actions.added_shift_count != 0:
                continue
            assert not any(c.amount == 18_000.0 for c in option.cost.components), (
                f"{option.label} adds no shift and must not be charged for one"
            )

    def test_established_costs_do_not_alter_the_engineering_of_a_refinement(
        self, electronics_factory,
    ):
        """E, the half that must NOT come out different."""
        constraint = reqs(prefer_no_new_machines=True)
        plain, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, constraint)
        priced, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, constraint,
            user_costs=[UserCostInput(
                gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
                category=CostCategory.OPEX_PER_DAY,
            )],
        )
        assert [o.strategy_id for o in plain.strategies] == [o.strategy_id for o in priced.strategies]
        assert (
            [o.metrics.model_dump() for o in plain.strategies]
            == [o.metrics.model_dump() for o in priced.strategies]
        )
        assert (
            [o.actions.model_dump() for o in plain.strategies]
            == [o.actions.model_dump() for o in priced.strategies]
        )

    def test_a_second_cost_statement_does_not_re_open_the_first_gap(self, client, arena_result):
        """A second Ask adds to what is established; it does not replace it."""
        result, sessions = arena_result
        response = client.post("/strategies/ask", json={
            "arena": result.model_dump(mode="json"),
            "question": "Two operators cost 90k/year.",
            "sessions": {k: v.model_dump(mode="json") for k, v in sessions.items()},
            "established_costs": [SHIFT_18K],
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["repriced"] is True

        gaps = {
            gap["gap_type"]
            for option in body["arena"]["strategies"] for gap in option["cost"]["information_gaps"]
        }
        assert "SHIFT_COST" not in gaps, "the earlier statement must still hold"

    def test_restating_a_cost_supersedes_the_earlier_figure(self, client, arena_result):
        """Two sentences about one cost are one fact, and the newer wins."""
        result, sessions = arena_result
        response = client.post("/strategies/ask", json={
            "arena": result.model_dump(mode="json"),
            "question": "An extra shift costs 21k/day.",
            "sessions": {k: v.model_dump(mode="json") for k, v in sessions.items()},
            "established_costs": [SHIFT_18K],
        })
        assert response.status_code == 200, response.text

        amounts = {
            component["amount"]
            for option in response.json()["arena"]["strategies"]
            for component in option["cost"]["components"]
        }
        assert 21_000.0 in amounts
        assert 18_000.0 not in amounts, "a superseded figure must not survive beside its replacement"


# G14 - A CAPEX-FREE PLAN IS NOT A FREE PLAN From the human golden run, one turn after
# G13.


def _shift_only_profile(amount: float = 18_000.0) -> StrategyCostProfile:
    """A fully-priced plan that buys nothing and runs an extra shift."""
    return StrategyCostProfile(
        known_capex=0.0,
        components=[CostComponent(
            label="Operating cost of the changed shift pattern (changing the shift pattern)",
            category=CostCategory.OPEX_PER_DAY, amount=amount, source="USER",
        )],
    )


class TestKnownCostDimensions:
    """G14.1 - the money `known_capex` does not describe has somewhere to live."""

    def test_a_shift_plan_reports_its_operating_cost(self):
        profile = _shift_only_profile()
        assert profile.known_capex == 0.0
        assert profile.known_by_category == {CostCategory.OPEX_PER_DAY: 18_000.0}
        assert profile.known_non_capex == {CostCategory.OPEX_PER_DAY: 18_000.0}

    def test_categories_are_summed_within_but_never_across(self):
        profile = StrategyCostProfile(
            known_capex=205_000.0,
            components=[
                CostComponent(label="machine a", category=CostCategory.CAPEX, amount=200_000.0),
                CostComponent(label="machine b", category=CostCategory.CAPEX, amount=5_000.0),
                CostComponent(label="shift", category=CostCategory.OPEX_PER_DAY, amount=18_000.0),
            ],
        )
        assert profile.known_by_category == {
            CostCategory.CAPEX: 205_000.0,
            CostCategory.OPEX_PER_DAY: 18_000.0,
        }
        # No key anywhere holds 223,000. That number would mean nothing.
        assert 223_000.0 not in profile.known_by_category.values()

    def test_an_unknown_amount_is_absent_not_zero(self):
        profile = StrategyCostProfile(
            known_capex=0.0,
            components=[CostComponent(
                label="capacity", category=CostCategory.ONE_TIME_OTHER, amount=None,
            )],
        )
        assert profile.known_by_category == {}
        assert profile.known_non_capex == {}

    def test_the_breakdown_is_serialized_for_the_client(self):
        # The card reads this rather than re-deriving its own, so the figure
        # on screen and the figure in the sentence cannot drift apart.
        dumped = _shift_only_profile().model_dump(mode="json")
        assert dumped["known_by_category"] == {"OPEX_PER_DAY": 18_000.0}


class TestCostLanguage:
    """G14.2 - what the prose is allowed to say about a zero."""

    def test_a_priced_shift_plan_never_reads_as_zero(self):
        phrase = known_cost_phrase(_shift_only_profile())
        assert "18,000" in phrase
        assert "/day" in phrase, "a recurring figure must carry its period"

    def test_a_complete_profile_states_capex_zero_alongside_the_real_cost(self):
        # Both dimensions, because "EUR 0" alone was the defect and dropping
        # the zero entirely would lose a fact we actually established.
        phrase = known_cost_phrase(_shift_only_profile())
        assert "EUR 0 CAPEX" in phrase
        assert "EUR 18,000/day operating cost" in phrase

    def test_an_incomplete_profile_never_claims_zero_capex(self):
        # The other zero: nothing established yet, which must not borrow the
        # formatting of a plan that genuinely buys nothing.
        profile = StrategyCostProfile(
            known_capex=0.0,
            components=[CostComponent(
                label="capacity", category=CostCategory.ONE_TIME_OTHER, amount=None,
            )],
        )
        assert profile.commercially_complete is False
        assert known_cost_phrase(profile) == ""

    def test_no_phrase_sums_across_categories(self):
        profile = StrategyCostProfile(
            known_capex=205_000.0,
            components=[
                CostComponent(label="machine", category=CostCategory.CAPEX, amount=205_000.0),
                CostComponent(label="shift", category=CostCategory.OPEX_PER_DAY, amount=18_000.0),
            ],
        )
        phrase = known_cost_phrase(profile)
        assert "205,000" in phrase and "18,000" in phrase
        assert "223,000" not in phrase


class TestCheaperOptionIsFinanciallyHonest:
    """G14.2 - the answer that reached the human."""

    def test_the_cheaper_answer_does_not_imply_a_free_plan(self, arena_result):
        """The exact reproduced sentence, pinned against its own defect."""
        result, sessions = arena_result
        priced = reprice_arena(result, sessions, [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
            category=CostCategory.OPEX_PER_DAY,
        )])

        answer = answer_strategy_query(priced, "Show me a cheaper option.")

        # The defect verbatim: a money answer whose only figure was a zero.
        assert "at EUR 0 known CAPEX" not in answer.answer
        assert "18,000" in answer.answer, "the cost the engineer supplied must be in the answer"
        assert "/day" in answer.answer

    def test_the_cheaper_answer_names_the_unrankable_plan(self, arena_result):
        """A ranking over one plan is not a ranking, and must not read as one."""
        result, sessions = arena_result
        priced = reprice_arena(result, sessions, [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
            category=CostCategory.OPEX_PER_DAY,
        )])
        unpriced = [o for o in priced.strategies if not o.commercially_complete]
        assert unpriced, "this fixture must still have a partially-priced option"

        answer = answer_strategy_query(priced, "Show me a cheaper option.")
        for option in unpriced:
            assert option.label in answer.answer, (
                f"{option.label} cannot be priced, and an answer that omits it "
                f"presents a settled ranking that does not exist"
            )

    def test_an_unpriced_plan_is_never_quoted_as_eur_zero(self, arena_result):
        """The original honesty rule, restated at the sentence level."""
        result, _ = arena_result
        answer = answer_strategy_query(result, "Show me a cheaper option.")
        assert "EUR 0" not in answer.answer, (
            "no option is priced here, so no figure may be quoted for any of them"
        )

    def test_information_needed_quotes_every_priced_dimension(self, arena_result):
        result, sessions = arena_result
        priced = reprice_arena(result, sessions, [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
            category=CostCategory.OPEX_PER_DAY,
        )])
        answer = answer_strategy_query(priced, "What information do we still need?")
        if "fully priced at" in answer.answer:
            assert "18,000" in answer.answer


class TestG14DoesNotDisturbTheEngineering:
    """G14.4 - a presentation fix that reruns nothing."""

    def test_pricing_language_changes_no_verified_number(self, arena_result):
        result, sessions = arena_result
        priced = reprice_arena(result, sessions, [UserCostInput(
            gap_type=InformationGapType.SHIFT_COST, amount=18_000.0,
            category=CostCategory.OPEX_PER_DAY,
        )])

        assert priced.baseline_metrics == result.baseline_metrics
        for after in priced.strategies:
            before = next(o for o in result.strategies if o.strategy_id == after.strategy_id)
            assert after.metrics == before.metrics
            assert after.actions == before.actions
        assert answer_strategy_query(priced, "Show me a cheaper option.").simulations_run == 0
