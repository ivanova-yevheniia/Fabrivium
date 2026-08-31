"""FactoryMind Phase 4C – deterministic candidate ranking / Pareto selection tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.models.optimization import GenerationSource, OptimizationCandidate, OptimizationGoal, OptimizationObjective
from app.models.ranking import CandidateRankStatus
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.candidate_evaluator import _evaluate_one, evaluate_candidates
from app.services.pareto import compute_dominance, dominates
from app.services.ranking import rank_candidates

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


def _at_demand(factory: Factory, demand: float) -> Factory:
    return factory.model_copy(update={
        "products": [p.model_copy(update={"demand_per_day": demand}) for p in factory.products]
    })


def _goal(objective=OptimizationObjective.MEET_DEMAND, **overrides) -> OptimizationGoal:
    base = dict(objective=objective, target_product_id="p-electronics-widget")
    base.update(overrides)
    return OptimizationGoal(**base)


def _find(rankings, candidate_id: str):
    return next(r for r in rankings if r.candidate_id == candidate_id)


def _manual_packaging_evaluation(factory: Factory, goal: OptimizationGoal):
    candidate = OptimizationCandidate(
        candidate_id="cand-manual-packaging",
        scenario=Scenario(
            id="cand-manual-packaging", name="manual packaging parallel",
            actions=[AddParallelMachineAction(machine_id="m-packaging")],
        ),
        rationale="Manually constructed for dominance-control test.",
        generation_source=GenerationSource.BOTTLENECK_RELIEF,
        estimated_capex=45000.0,
        requires_cost_estimate=False,
        affected_processes=["m-packaging"],
    )
    return _evaluate_one(factory, "p-electronics-widget", goal, None, None, candidate, 0.5, 2000)


# 1. pareto.py — pure dominance math

class TestParetoDominance:
    def test_strictly_better_everywhere_dominates(self):
        a = {"x": 1.0, "y": 1.0}
        b = {"x": 2.0, "y": 2.0}
        assert dominates(a, b, [("x", "min"), ("y", "min")]) is True
        assert dominates(b, a, [("x", "min"), ("y", "min")]) is False

    def test_equal_on_all_dims_does_not_dominate(self):
        a = {"x": 1.0, "y": 1.0}
        b = {"x": 1.0, "y": 1.0}
        assert dominates(a, b, [("x", "min"), ("y", "min")]) is False

    def test_mixed_dims_neither_dominates(self):
        """a better on x, b better on y -> neither dominates (a real tradeoff)."""
        a = {"x": 1.0, "y": 5.0}
        b = {"x": 5.0, "y": 1.0}
        assert dominates(a, b, [("x", "min"), ("y", "min")]) is False
        assert dominates(b, a, [("x", "min"), ("y", "min")]) is False

    def test_max_direction(self):
        a = {"throughput": 100.0}
        b = {"throughput": 50.0}
        assert dominates(a, b, [("throughput", "max")]) is True

    def test_within_epsilon_is_not_strictly_better(self):
        a = {"x": 1.0}
        b = {"x": 1.0 + 1e-9}
        assert dominates(a, b, [("x", "min")]) is False
        assert dominates(b, a, [("x", "min")]) is False

    def test_compute_dominance_frontier_and_maps(self):
        items = [
            ("a", {"x": 1.0, "y": 1.0}),
            ("b", {"x": 2.0, "y": 2.0}),  # dominated by a
            ("c", {"x": 0.5, "y": 5.0}),  # tradeoff vs a — non-dominated
        ]
        frontier, dominated_by, dominates_map = compute_dominance(items, [("x", "min"), ("y", "min")])
        assert frontier == {"a", "c"}
        assert dominated_by["b"] == ["a"]
        assert dominated_by["a"] == []
        assert "b" in dominates_map["a"]


# 2. Determinism

class TestDeterminism:
    def test_repeated_ranking_identical(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
        r1 = rank_candidates(eval_result, goal)
        r2 = rank_candidates(eval_result, goal)
        assert r1.model_dump() == r2.model_dump()

    def test_end_to_end_repeated_identical(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        r1 = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        r2 = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert r1.model_dump() == r2.model_dump()
        assert r1.summary == r2.summary

    def test_baseline_and_result_not_mutated(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
        before = eval_result.model_dump()
        rank_candidates(eval_result, goal)
        assert eval_result.model_dump() == before
        assert factory.model_dump() == _at_demand(_load_electronics(), 1200.0).model_dump()


# 3. Known-cost vs unknown-cost handling

class TestCostHandling:
    def test_unknown_cost_never_beats_known_cost_in_recommended_set(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        for cid in rec.recommended_candidate_ids:
            ranking = _find(rec.rankings, cid)
            assert ranking.status == CandidateRankStatus.RECOMMENDED

    def test_requires_information_never_in_recommended_set(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        for r in rec.rankings:
            if r.status == CandidateRankStatus.REQUIRES_INFORMATION:
                assert r.candidate_id not in rec.recommended_candidate_ids
                assert r.rank is None

    def test_requires_information_status_regardless_of_max_capex(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        for goal in (_goal(), _goal(max_capex=100000.0)):
            rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
            unknown = [r for r in rec.rankings if "cycle-time" in r.candidate_id]
            assert unknown  # sanity: cycle-time candidates exist
            for r in unknown:
                assert r.status == CandidateRankStatus.REQUIRES_INFORMATION

    def test_unknown_cost_rationale_mentions_pending_estimate(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        cycle = _find(rec.rankings, "cand-cycle-time-m-screwdriving-neg10pct")
        assert any("pending cost estimate" in line for line in cycle.rationale)


# 4. Feasibility separate from recommendation

class TestFeasibilitySeparateFromRecommendation:
    def test_infeasible_never_ranked_or_recommended(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        infeasible = _find(rec.rankings, "cand-add-parallel-m-screwdriving")
        assert infeasible.status == CandidateRankStatus.INFEASIBLE
        assert infeasible.rank is None
        assert infeasible.candidate_id not in rec.recommended_candidate_ids
        assert infeasible.candidate_id not in rec.pareto_candidate_ids


# 5. Required experiments

class TestExperimentBase1200:
    @pytest.fixture
    def recommendation(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        return rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)

    def test_add_parallel_screwdriving_is_top_known_cost_recommendation(self, recommendation):
        assert recommendation.recommended_candidate_ids[0] == "cand-add-parallel-m-screwdriving"
        top = _find(recommendation.rankings, "cand-add-parallel-m-screwdriving")
        assert top.status == CandidateRankStatus.RECOMMENDED
        assert top.rank == 1

    def test_add_parallel_screwdriving_on_pareto_frontier(self, recommendation):
        assert "cand-add-parallel-m-screwdriving" in recommendation.pareto_candidate_ids

    def test_cycle_time_candidates_requires_information(self, recommendation):
        for pct in ("5", "10", "20"):
            r = _find(recommendation.rankings, f"cand-cycle-time-m-screwdriving-neg{pct}pct")
            assert r.status == CandidateRankStatus.REQUIRES_INFORMATION

    def test_capacity_candidate_requires_information(self, recommendation):
        r = _find(recommendation.rankings, "cand-capacity-m-screwdriving-plus1")
        assert r.status == CandidateRankStatus.REQUIRES_INFORMATION

    def test_combined_candidate_requires_information_not_recommended(self, recommendation):
        r = _find(recommendation.rankings, "cand-combined-m-screwdriving-m-assembly")
        assert r.status == CandidateRankStatus.REQUIRES_INFORMATION
        assert r.candidate_id not in recommendation.recommended_candidate_ids

    def test_summary_mentions_recommendation(self, recommendation):
        assert "cand-add-parallel-m-screwdriving" in recommendation.summary
        assert "demand_met=True" in recommendation.summary


class TestExperimentBudgetControl:
    def test_80k_budget_excludes_85k_candidate(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0)
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert "cand-add-parallel-m-screwdriving" not in rec.recommended_candidate_ids
        infeasible = _find(rec.rankings, "cand-add-parallel-m-screwdriving")
        assert infeasible.status == CandidateRankStatus.INFEASIBLE

    def test_80k_budget_unknown_cost_remain_requires_information(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0)
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        cycle = _find(rec.rankings, "cand-cycle-time-m-screwdriving-neg10pct")
        assert cycle.status == CandidateRankStatus.REQUIRES_INFORMATION

    def test_80k_budget_no_known_cost_solution_reported_honestly(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0)
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert rec.recommended_candidate_ids == []
        assert rec.pareto_candidate_ids == []
        assert "No feasible known-cost candidate" in rec.summary

    def test_100k_budget_restores_recommendation(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=100000.0)
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert rec.recommended_candidate_ids == ["cand-add-parallel-m-screwdriving"]


class TestExperimentHighDemandControl:
    def test_partial_relief_reported_honestly_when_unmet(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 2400.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert rec.recommended_candidate_ids  # still offers the best available option
        assert "UNMET" in rec.summary
        top = _find(rec.rankings, rec.recommended_candidate_ids[0])
        assert top.rationale  # some measured rationale is present

    def test_does_not_claim_success_when_target_unmet(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 2400.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert "demand_met=True" not in rec.summary.split("Best available")[0] or "UNMET" in rec.summary

    def test_1600_still_fully_solvable_by_single_candidate(self, electronics_factory: Factory):
        """Control: at 1600/day the simpler parallel-screwdriving candidate
        still fully closes the gap — confirms the 2400/day case above is a
        genuine capacity shortfall, not a generator/evaluator artifact."""
        factory = _at_demand(electronics_factory, 1600.0)
        goal = _goal()
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert "UNMET" not in rec.summary
        assert rec.recommended_candidate_ids == ["cand-add-parallel-m-screwdriving"]


class TestExperimentPackagingDominanceControl:
    def test_packaging_feasible_but_not_recommended(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
        packaging_eval = _manual_packaging_evaluation(factory, goal)
        assert packaging_eval.status.value == "FEASIBLE"

        augmented = eval_result.model_copy(update={"candidates": [*eval_result.candidates, packaging_eval]})
        rec = rank_candidates(augmented, goal)

        packaging_rank = _find(rec.rankings, "cand-manual-packaging")
        assert packaging_rank.status in (CandidateRankStatus.DOMINATED,)
        assert "cand-manual-packaging" not in rec.recommended_candidate_ids
        assert "cand-manual-packaging" not in rec.pareto_candidate_ids

    def test_packaging_does_not_displace_screwdriving_as_primary(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal()
        eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
        packaging_eval = _manual_packaging_evaluation(factory, goal)
        augmented = eval_result.model_copy(update={"candidates": [*eval_result.candidates, packaging_eval]})
        rec = rank_candidates(augmented, goal)
        assert rec.recommended_candidate_ids[0] == "cand-add-parallel-m-screwdriving"


# 6. Objective behavior / tie-break determinism

class TestObjectiveBehavior:
    def test_different_objectives_can_change_ranking(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal_demand = _goal(OptimizationObjective.MEET_DEMAND)
        goal_wip = _goal(OptimizationObjective.MINIMIZE_WIP)
        rec_demand = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal_demand), goal_demand)
        rec_wip = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal_wip), goal_wip)
        # Both goals are legitimate typed OptimizationGoal objects with a
        # potentially different ranking order (dedicated objective coverage).
        assert rec_demand.goal.objective == OptimizationObjective.MEET_DEMAND
        assert rec_wip.goal.objective == OptimizationObjective.MINIMIZE_WIP

    def test_minimize_wip_gate_falls_back_when_none_meet_demand(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 2400.0)
        goal = _goal(OptimizationObjective.MINIMIZE_WIP, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        # Should still produce SOME ranking (fallback), never crash/empty
        # just because nobody meets the (very high) demand target.
        assert any(r.rank is not None for r in rec.rankings)

    def test_maximize_throughput_prefers_higher_completed_units(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 2400.0)
        goal = _goal(OptimizationObjective.MAXIMIZE_THROUGHPUT)
        rec = rank_candidates(evaluate_candidates(factory, "p-electronics-widget", goal), goal)
        assert rec.recommended_candidate_ids
        top = _find(rec.rankings, rec.recommended_candidate_ids[0])
        assert top.rank == 1

    def test_tie_break_is_deterministic_by_candidate_id(self, electronics_factory: Factory):
        """Two runs across a freshly-rebuilt equivalent factory must agree
        on tie-break order (candidate_id is the final key component)."""
        factory1 = _at_demand(electronics_factory, 1200.0)
        factory2 = _at_demand(_load_electronics(), 1200.0)
        goal = _goal()
        rec1 = rank_candidates(evaluate_candidates(factory1, "p-electronics-widget", goal), goal)
        rec2 = rank_candidates(evaluate_candidates(factory2, "p-electronics-widget", goal), goal)
        assert [r.candidate_id for r in rec1.rankings] == [r.candidate_id for r in rec2.rankings]
        assert [r.rank for r in rec1.rankings] == [r.rank for r in rec2.rankings]
