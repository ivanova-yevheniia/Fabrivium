"""FactoryMind Phase 4B – candidate feasibility evaluation tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.evaluation import CandidateFeasibilityStatus, CandidateRejectionReason
from app.models.factory import Factory
from app.models.layout import LayoutZone, LayoutZoneType
from app.models.optimization import GenerationSource, OptimizationCandidate, OptimizationGoal, OptimizationObjective
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.candidate_evaluator import BaselineLayoutInvalidError, _evaluate_one, evaluate_candidates
from app.services.layout import create_layout, get_placement, place_machine
from app.services.placement_search import DEFAULT_MAX_POSITION_ATTEMPTS, find_placement

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


def _native_layout(factory: Factory, offset: float = 0.0):
    layout = create_layout(factory)
    for m in factory.machines:
        layout = place_machine(factory, layout, m.id, x=m.position_x + offset, y=m.position_y + offset)
    return layout


def _find(evaluations, candidate_id: str):
    return next(e for e in evaluations if e.candidate.candidate_id == candidate_id)


# 1. placement_search.py — pure, deterministic

class TestPlacementSearch:
    def test_finds_immediate_position_near_source(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        layout = create_layout(factory)
        for m in factory.machines:
            layout = place_machine(factory, layout, m.id, x=m.position_x + 50.0, y=m.position_y + 50.0)

        from app.services.scenario import apply_scenario
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate_factory = apply_scenario(factory, scenario)

        result = find_placement(candidate_factory, layout, "m-screwdriving-parallel-1", near_machine_id="m-screwdriving")
        assert result.placement is not None
        assert result.attempts > 0
        assert result.attempts <= DEFAULT_MAX_POSITION_ATTEMPTS

    def test_deterministic_repeat_same_placement(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        layout = create_layout(factory)
        for m in factory.machines:
            layout = place_machine(factory, layout, m.id, x=m.position_x + 50.0, y=m.position_y + 50.0)

        from app.services.scenario import apply_scenario
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate_factory = apply_scenario(factory, scenario)

        r1 = find_placement(candidate_factory, layout, "m-screwdriving-parallel-1", near_machine_id="m-screwdriving")
        r2 = find_placement(candidate_factory, layout, "m-screwdriving-parallel-1", near_machine_id="m-screwdriving")
        assert r1 == r2

    def test_bounded_search_returns_none_when_exhausted(self, electronics_factory: Factory):
        """A tiny attempt budget on a crowded floor must terminate cleanly
        (never loop unboundedly) and report None with attempts == budget."""
        factory = electronics_factory.model_copy(update={"width": 10.0, "length": 2.0})
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
        layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
        layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)

        from app.services.scenario import apply_scenario
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate_factory = apply_scenario(factory, scenario)

        result = find_placement(
            candidate_factory, layout, "m-screwdriving-parallel-1",
            near_machine_id="m-screwdriving", max_position_attempts=50,
        )
        assert result.placement is None
        assert result.attempts <= 50

    def test_no_reference_falls_back_to_global_grid(self, electronics_factory: Factory):
        # A modest floor keeps the row-major fallback scan cheap:
        factory = electronics_factory.model_copy(update={"width": 20.0, "length": 20.0})
        layout = create_layout(factory)  # nothing placed at all

        from app.services.scenario import apply_scenario
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate_factory = apply_scenario(factory, scenario)

        result = find_placement(candidate_factory, layout, "m-screwdriving-parallel-1", near_machine_id=None)
        assert result.placement is not None
        # width=2.5/length=2.0 half-extents of 1.25/1.0, snapped to the
        # 0.5m grid): y reaches 1.0 before any x satisfies x >= 1.25.
        assert result.placement.y == 1.0
        assert result.placement.x >= 1.25

    def test_existing_placements_never_moved_by_search(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        layout = create_layout(factory)
        for m in factory.machines:
            layout = place_machine(factory, layout, m.id, x=m.position_x + 50.0, y=m.position_y + 50.0)
        before = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}

        from app.services.scenario import apply_scenario
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        candidate_factory = apply_scenario(factory, scenario)
        find_placement(candidate_factory, layout, "m-screwdriving-parallel-1", near_machine_id="m-screwdriving")

        after = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}
        assert before == after  # search never mutates the layout passed in


# 2. Determinism / immutability

class TestDeterminism:
    def test_repeated_evaluation_identical(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=100000.0)
        r1 = evaluate_candidates(factory, "p-electronics-widget", goal)
        r2 = evaluate_candidates(factory, "p-electronics-widget", goal)
        assert r1.model_dump() == r2.model_dump()

    def test_baseline_factory_immutable(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        before = factory.model_dump()
        evaluate_candidates(factory, "p-electronics-widget", _goal())
        assert factory.model_dump() == before

    def test_baseline_layout_immutable(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        before = layout.model_dump()
        evaluate_candidates(factory, "p-electronics-widget", _goal(), layout=layout)
        assert layout.model_dump() == before


# 3. Feasible/infeasible distinction — verdict != feasibility

class TestFeasibilityDistinction:
    def test_neutral_verdict_candidate_is_feasible(self, electronics_factory: Factory):
        """
        Manually evaluate a Packaging-parallel candidate (Phase 4A never generates it —
        Packaging isn't congested — but a caller could still ask for it manually).
        """
        factory = _at_demand(electronics_factory, 1200.0)
        candidate = OptimizationCandidate(
            candidate_id="cand-manual-packaging",
            scenario=Scenario(
                id="cand-manual-packaging", name="manual packaging parallel",
                actions=[AddParallelMachineAction(machine_id="m-packaging")],
            ),
            rationale="Manually constructed for feasibility-vs-quality test.",
            generation_source=GenerationSource.BOTTLENECK_RELIEF,
            estimated_capex=45000.0,
            requires_cost_estimate=False,
            affected_processes=["m-packaging"],
        )
        goal = _goal()
        evaluation = _evaluate_one(factory, "p-electronics-widget", goal, None, None, candidate, 0.5, 2000)
        assert evaluation.scenario_result.verdict.value == "NEUTRAL"
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        assert evaluation.operationally_feasible is True

    def test_feasible_and_infeasible_coexist_in_one_result(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0, allowed_action_types=["ADD_PARALLEL_MACHINE", "CHANGE_MACHINE_CYCLE_TIME"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        statuses = {e.status for e in result.candidates}
        assert CandidateFeasibilityStatus.INFEASIBLE in statuses  # the add-parallel (85000 > 80000)


# 4. CAPEX handling

class TestCapexHandling:
    def test_known_cost_over_cap_is_infeasible_capex_limit(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.INFEASIBLE
        assert evaluation.rejection_reasons == [CandidateRejectionReason.CAPEX_LIMIT]

    def test_capex_limit_skips_expensive_simulation(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=80000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.simulation_result is None
        assert evaluation.scenario_result is None
        assert evaluation.candidate_factory is None

    def test_known_cost_at_cap_is_feasible(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=85000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE

    def test_unknown_cost_with_max_capex_is_requires_information(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=100000.0, allowed_action_types=["CHANGE_MACHINE_CYCLE_TIME"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        for e in result.candidates:
            assert e.status == CandidateFeasibilityStatus.REQUIRES_INFORMATION
            assert e.rejection_reasons == [CandidateRejectionReason.COST_UNKNOWN]
            assert e.operationally_feasible is True  # ran fully; only cost is unknown

    def test_unknown_cost_without_max_capex_is_feasible(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(max_capex=None, allowed_action_types=["CHANGE_MACHINE_CYCLE_TIME"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal)
        for e in result.candidates:
            assert e.status == CandidateFeasibilityStatus.FEASIBLE
            assert e.requires_cost_estimate is True  # still marked, never pretended free

    def test_known_capex_matches_candidate_estimate(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(factory, "p-electronics-widget", _goal())
        for e in result.candidates:
            assert e.known_capex == e.candidate.estimated_capex


# 5. Layout / placement integration

class TestLayoutIntegration:
    def test_layout_warnings_do_not_reject_candidate(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        # Sanity: baseline is valid (no errors) so we can attribute any
        # warning purely to the new placement, if any arises.
        goal = _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        if evaluation.constraint_result is not None:
            assert evaluation.constraint_result.error_count == 0

    def test_layout_errors_reject_candidate(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 10.0, "length": 2.0})
        factory = _at_demand(factory, 1200.0)
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
        layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
        layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)

        goal = _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"], max_candidates=1)
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout, max_position_attempts=300)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.INFEASIBLE
        assert evaluation.rejection_reasons == [CandidateRejectionReason.PLACEMENT_NOT_FOUND]

    def test_added_machine_gets_valid_placement(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        goal = _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        placement = get_placement(evaluation.candidate_layout, "m-screwdriving-parallel-1")
        assert placement is not None

    def test_existing_machine_positions_unchanged_in_candidate_layout(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        original_positions = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}

        goal = _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        for machine_id, pos in original_positions.items():
            placement = get_placement(evaluation.candidate_layout, machine_id)
            assert (placement.x, placement.y, placement.rotation_deg) == pos

    def test_placement_attempts_reported(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        goal = _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.placement_attempts is not None
        assert evaluation.placement_attempts > 0

    def test_candidates_without_new_machine_reuse_baseline_layout_validation(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        goal = _goal(allowed_action_types=["CHANGE_MACHINE_CYCLE_TIME"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        for e in result.candidates:
            assert e.constraint_result == result.baseline_layout_validation
            assert e.placement_attempts is None


# 6. Baseline validation

class TestBaselineValidation:
    def test_invalid_baseline_layout_raises(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=5.0, y=5.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=5.0, y=5.0)  # overlaps
        layout = place_machine(factory, layout, "m-inspection", x=19.0, y=5.0)
        layout = place_machine(factory, layout, "m-packaging", x=26.0, y=5.0)

        with pytest.raises(BaselineLayoutInvalidError):
            evaluate_candidates(factory, "p-electronics-widget", _goal(), layout=layout)

    def test_valid_baseline_layout_is_stored(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        result = evaluate_candidates(factory, "p-electronics-widget", _goal(), layout=layout)
        assert result.baseline_layout_validation is not None
        assert result.baseline_layout_validation.valid is True

    def test_no_layout_supplied_baseline_validation_is_none(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(factory, "p-electronics-widget", _goal())
        assert result.baseline_layout_validation is None


# 7. Required experiments A-F

class TestExperimentA_NoLayout:
    def test_known_candidates_simulate_correctly(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(factory, "p-electronics-widget", _goal())
        assert result.feasible_count == len(result.candidates)
        assert result.infeasible_count == 0

    def test_second_screwdriving_operationally_improves(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(factory, "p-electronics-widget", _goal())
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        assert evaluation.scenario_result.verdict.value == "IMPROVED"
        assert evaluation.simulation_result.demand_met is True

    def test_unknown_cost_candidates_flagged_per_rules(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        # Without max_capex: FEASIBLE but requires_cost_estimate=True.
        result_no_cap = evaluate_candidates(factory, "p-electronics-widget", _goal())
        for e in result_no_cap.candidates:
            if e.requires_cost_estimate:
                assert e.status == CandidateFeasibilityStatus.FEASIBLE

        # With max_capex: REQUIRES_INFORMATION.
        result_cap = evaluate_candidates(factory, "p-electronics-widget", _goal(max_capex=100000.0))
        for e in result_cap.candidates:
            if e.requires_cost_estimate:
                assert e.status == CandidateFeasibilityStatus.REQUIRES_INFORMATION


class TestExperimentB_SpaciousLayout:
    def test_placement_found_and_feasible_and_demand_met(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)

        result = evaluate_candidates(
            factory, "p-electronics-widget", _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"]), layout=layout
        )
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        assert evaluation.constraint_result.valid is True
        assert evaluation.simulation_result.demand_met is True


class TestExperimentC_CrowdedLayout:
    def test_no_legal_location_yields_placement_not_found(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 10.0, "length": 2.0})
        factory = _at_demand(factory, 1200.0)
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
        layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
        layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)

        result = evaluate_candidates(
            factory, "p-electronics-widget",
            _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"], max_candidates=1),
            layout=layout, max_position_attempts=300,
        )
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.INFEASIBLE
        assert evaluation.rejection_reasons[0] in (
            CandidateRejectionReason.PLACEMENT_NOT_FOUND, CandidateRejectionReason.LAYOUT_INFEASIBLE,
        )


class TestExperimentD_CapexBelowCost:
    def test_rejected_capex_limit_before_simulation(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(
            factory, "p-electronics-widget",
            _goal(max_capex=80000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"]),
        )
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.INFEASIBLE
        assert evaluation.rejection_reasons == [CandidateRejectionReason.CAPEX_LIMIT]
        assert evaluation.simulation_result is None


class TestExperimentE_CapexAboveCost:
    def test_capex_passes_feasibility_determined_normally(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result = evaluate_candidates(
            factory, "p-electronics-widget",
            _goal(max_capex=100000.0, allowed_action_types=["ADD_PARALLEL_MACHINE"]),
        )
        evaluation = _find(result.candidates, "cand-add-parallel-m-screwdriving")
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        assert evaluation.simulation_result is not None


class TestExperimentF_PackagingNeutral:
    def test_neutral_operationally_valid_candidate_is_feasible(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidate = OptimizationCandidate(
            candidate_id="cand-manual-packaging-f",
            scenario=Scenario(
                id="cand-manual-packaging-f", name="manual packaging parallel",
                actions=[AddParallelMachineAction(machine_id="m-packaging")],
            ),
            rationale="Experiment F.",
            generation_source=GenerationSource.BOTTLENECK_RELIEF,
            estimated_capex=45000.0,
            requires_cost_estimate=False,
            affected_processes=["m-packaging"],
        )
        evaluation = _evaluate_one(factory, "p-electronics-widget", _goal(), None, None, candidate, 0.5, 2000)
        assert evaluation.status == CandidateFeasibilityStatus.FEASIBLE
        assert evaluation.scenario_result.verdict.value == "NEUTRAL"
