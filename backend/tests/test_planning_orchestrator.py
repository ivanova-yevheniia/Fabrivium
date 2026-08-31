"""FactoryMind Phase 5C - iterative planning orchestrator tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.models.orchestrator import PlanningStopReason
from app.services.constraints import validate_layout
from app.services.layout import create_layout, place_machine
from app.services.planning_orchestrator import PlanningOrchestrator, render_trace

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


def _reqs(**overrides) -> PlanningRequirements:
    base = dict(objective=OptimizationObjective.MEET_DEMAND)
    base.update(overrides)
    return PlanningRequirements(**base)


def _cramped_layout(factory: Factory):
    """A 10x2 factory with all 4 existing machines packed tightly along
    the aisle, leaving no free space for a 5th machine (mirrors Phase 4B's
    own PLACEMENT_NOT_FOUND fixture)."""
    factory = factory.model_copy(update={"width": 10.0, "length": 2.0})
    layout = create_layout(factory)
    layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
    layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
    layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
    layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)
    return factory, layout


# 1. Demonstration A: one-step goal success

class TestDemonstrationA:
    def test_single_iteration_meets_demand(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1200.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)

        assert state.stop_reason == PlanningStopReason.GOAL_REACHED
        assert state.goal_reached is True
        assert len(state.iterations) == 1
        assert state.iterations[0].accepted is True
        assert state.current_simulation.demand_met is True

    def test_accepted_scenario_adds_parallel_screwdriving(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1200.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        actions = state.iterations[0].selected_proposal.scenario.actions
        assert actions[0].action_type == "ADD_PARALLEL_MACHINE"
        assert actions[0].machine_id == "m-screwdriving"


# 2. Demonstration B: genuine multi-iteration planning

class TestDemonstrationB:
    """The 1900/day demonstration."""

    def test_goal_is_still_reached_at_the_same_known_capex(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)

        assert state.stop_reason == PlanningStopReason.GOAL_REACHED
        assert state.goal_reached is True
        assert state.final_snapshot.simulation.completed_units >= 1900
        assert state.cumulative_known_capex == pytest.approx(205_000.0)

    def test_it_now_takes_three_steps_and_every_one_is_accepted(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert len(state.iterations) == 3
        assert all(it.accepted for it in state.iterations)

    def test_first_iteration_relieves_screwdriving(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        first_actions = state.iterations[0].selected_proposal.scenario.actions
        assert first_actions[0].machine_id == "m-screwdriving"
        # Genuine improvement, but demand not yet fully met after step 1.
        assert state.iterations[0].scenario_result.candidate_result.demand_met is False

    def test_the_workforce_constraint_is_diagnosed_before_the_machine_that_needs_it(
        self, electronics_factory: Factory
    ):
        """The Phase 8A headline."""
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)

        second = state.iterations[1].selected_proposal.scenario.actions
        assert [a.action_type for a in second] == ["CHANGE_OPERATOR_CAPACITY"]
        assert second[0].operators_available > electronics_factory.operators_available

        # The staffing step is genuinely unknown-cost, not silently free.
        assert state.iterations[1].requires_cost_estimate is True
        assert state.iterations[1].known_capex == pytest.approx(0.0)

    def test_third_iteration_buys_the_machine_that_is_now_staffable(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        third = state.iterations[2].selected_proposal.scenario.actions
        assert third[0].machine_id == "m-assembly"
        assert state.iterations[2].scenario_result.candidate_result.demand_met is True

    def test_the_final_verified_state_is_not_starved_of_staff(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        operator_kpi = state.final_snapshot.simulation.operator_kpi
        assert operator_kpi is not None
        assert operator_kpi.operator_constrained is False
        assert state.current_factory.operators_available > electronics_factory.operators_available

    def test_demand_gap_strictly_decreases_across_iterations(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        gaps = [it.scenario_result.candidate_result.demand_gap_units for it in state.iterations]
        assert gaps == sorted(gaps, reverse=True)
        assert gaps[-1] == 0.0

    def test_current_state_updates_after_accepted_proposal(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        screwdriving_clones = [m for m in state.current_factory.machines if m.parallel_of_machine_id == "m-screwdriving"]
        assembly_clones = [m for m in state.current_factory.machines if m.parallel_of_machine_id == "m-assembly"]
        assert len(screwdriving_clones) == 1
        assert len(assembly_clones) == 1

    def test_stale_baseline_candidates_not_reused(self, electronics_factory: Factory):
        """The candidate universe considered in iteration 2 is generated
        fresh from the POST-iteration-1 factory — it must not be the same
        object/values as iteration 1's, proving no stale reuse."""
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        rec_1 = state.iterations[0].recommendation_snapshot
        rec_2 = state.iterations[1].recommendation_snapshot
        # Phase 8A: the top-ranked candidate ID is no longer a reliable proof of
        # freshness.
        assert rec_2.baseline_result.demand_gap_units < rec_1.baseline_result.demand_gap_units
        assert {c.candidate_id for c in rec_1.rankings} != {c.candidate_id for c in rec_2.rankings}


# 3. Demonstration C: budget tracking

class TestDemonstrationC:
    def test_insufficient_budget_stops_honestly(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1200.0, max_capex=80_000.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.stop_reason == PlanningStopReason.BUDGET_EXHAUSTED
        assert state.goal_reached is False
        assert state.cumulative_known_capex == 0.0

    def test_cumulative_capex_tracked_and_remaining_decreases(self, electronics_factory: Factory):
        """
        Phase 8A: under a HARD ceiling this session now stops at EUR 85,000 rather than
        reaching EUR 205,000.
        """
        reqs = _reqs(target_units_per_day=1900.0, max_capex=250_000.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert state.cumulative_known_capex == pytest.approx(85_000.0)
        assert state.remaining_known_capex == pytest.approx(250_000.0 - state.cumulative_known_capex)
        assert state.remaining_known_capex >= 0.0
        assert state.stop_reason == PlanningStopReason.BUDGET_EXHAUSTED

    def test_budget_never_exceeded(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0, max_capex=100_000.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.cumulative_known_capex <= 100_000.0

    def test_remaining_budget_used_for_next_context_not_original(self, electronics_factory: Factory):
        # 85k (screwdriving) leaves 35k remaining out of 120k — not enough
        # for assembly's 120k second fix, so the session must stop without
        # spending more than the original cap, honestly reporting why.
        reqs = _reqs(target_units_per_day=1900.0, max_capex=120_000.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.cumulative_known_capex == pytest.approx(85_000.0)
        assert state.remaining_known_capex == pytest.approx(35_000.0)
        assert state.stop_reason == PlanningStopReason.BUDGET_EXHAUSTED
        assert state.goal_reached is False


# Phase 8A note for the demonstrations below
#
# Several of these were written when the ONLY levers were machine actions,
# so "no machine fix works" and "the session is blocked" were the same
# statement. Phase 8A adds shifts/operators/buffers, and for some of these
# fixtures adding a third shift genuinely does reach the target — which is a
# better answer, not a broken test.
#
# To keep testing what each one was written to test, the affected cases now
# say so explicitly via allowed_action_types=["ADD_PARALLEL_MACHINE"]. The
# NEW behaviour (time as an alternative to equipment) gets its own coverage
# in TestPhase8AAlternativesToBuying below, so nothing is lost either way.

MACHINE_ACTIONS_ONLY = ["ADD_PARALLEL_MACHINE"]


# 4. Demonstration D: forbidden machine respected

class TestDemonstrationD:
    def test_forbidden_screwdriving_blocks_progress(self, electronics_factory: Factory):
        # Machine actions only — see the Phase 8A note above.
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving"],
            allowed_action_types=MACHINE_ACTIONS_ONLY,
        )
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        # Phase 8A: this outcome is UNCHANGED, but only because a real defect was fixed
        # along the way.
        assert state.stop_reason == PlanningStopReason.USER_CONSTRAINTS_BLOCK_PROGRESS
        assert state.goal_reached is False
        assert not any(m.parallel_of_machine_id == "m-screwdriving" for m in state.current_factory.machines)

    def test_forbidden_machine_never_modified_across_any_iteration(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0, forbidden_machine_ids=["m-screwdriving"])
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        for iteration in state.iterations:
            if iteration.selected_proposal is not None:
                machine_ids = {getattr(a, "machine_id", None) for a in iteration.selected_proposal.scenario.actions}
                assert "m-screwdriving" not in machine_ids
        # Never cloned, either.
        assert not any(m.parallel_of_machine_id == "m-screwdriving" for m in state.current_factory.machines)


# 5. Demonstration E: irrelevant proposal never adopted, no infinite loop

class TestDemonstrationE:
    def test_neutral_user_requested_proposal_not_accepted(self, electronics_factory: Factory):
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)

        assert state.iterations[0].accepted is False
        assert state.iterations[0].scenario_result.verdict.value == "NEUTRAL"
        # Never adopted as the new current/best engineering state.
        assert state.current_factory == electronics_factory
        assert state.goal_reached is False

    def test_does_not_loop_forever_on_rejected_proposal(self, electronics_factory: Factory):
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.stop_reason == PlanningStopReason.REPEATED_PROPOSAL
        # Bounded well under max_iterations — it did not spin until the cap.
        assert len(state.iterations) < 5


# 6. State / immutability

class TestStateAndImmutability:
    def test_original_factory_never_mutated(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        reqs = _reqs(target_units_per_day=1900.0)
        PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert electronics_factory.model_dump() == before

    def test_baseline_factory_on_state_is_untouched_original(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert state.baseline_factory.model_dump() == electronics_factory.model_dump()
        assert state.current_factory.model_dump() != state.baseline_factory.model_dump()

    def test_explicit_stop_reason_always_present(self, electronics_factory: Factory):
        for target, kwargs in [
            (1200.0, {}),
            (1900.0, {}),
            (1200.0, {"max_capex": 80_000.0}),
            (1200.0, {"forbidden_machine_ids": ["m-screwdriving"]}),
        ]:
            reqs = _reqs(target_units_per_day=target, **kwargs)
            state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
            assert state.stop_reason is not None
            assert isinstance(state.stop_reason, PlanningStopReason)

    def test_current_best_result_matches_current_simulation(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert state.current_best_result == state.current_simulation


# 7. Acceptance rule

class TestAcceptanceRule:
    def test_infeasible_proposal_not_accepted(self, electronics_factory: Factory):
        factory, layout = _cramped_layout(electronics_factory)
        factory = factory.model_copy(update={"products": [p.model_copy(update={"demand_per_day": 1200.0}) for p in factory.products]})
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state = PlanningOrchestrator().run(factory, PRODUCT_ID, reqs, layout=layout, max_iterations=5, max_position_attempts=300)
        assert state.stop_reason == PlanningStopReason.CONSTRAINT_BLOCKED
        assert state.iterations[-1].accepted is False
        assert state.goal_reached is False

    def test_degraded_or_neutral_never_accepted_for_meet_demand(self, electronics_factory: Factory):
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        for iteration in state.iterations:
            if iteration.scenario_result is not None and iteration.scenario_result.verdict.value != "IMPROVED":
                assert iteration.accepted is False

    def test_max_iterations_hard_stop(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=1)
        assert state.stop_reason == PlanningStopReason.MAX_ITERATIONS
        assert len(state.iterations) == 1
        assert state.goal_reached is False

    def test_error_stop_reason_on_invalid_baseline_layout(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"products": [p.model_copy(update={"demand_per_day": 1200.0}) for p in electronics_factory.products]})
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.0, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=1.0, y=1.0)  # overlaps -> ERROR violation
        assert validate_layout(factory, layout, PRODUCT_ID).error_count > 0

        reqs = _reqs(target_units_per_day=1200.0)
        state = PlanningOrchestrator().run(factory, PRODUCT_ID, reqs, layout=layout, max_iterations=5)
        assert state.stop_reason == PlanningStopReason.ERROR
        assert state.iterations == []


# 8. Repeated-proposal / loop prevention

class TestLoopPrevention:
    def test_repeated_proposal_detected_and_stops(self, electronics_factory: Factory):
        reqs = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.stop_reason == PlanningStopReason.REPEATED_PROPOSAL

    def test_session_history_records_accepted_and_rejected_branches(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert all(it.accepted for it in state.iterations)  # demonstration B has no rejections
        # Rejected-branch coverage comes from demonstration E instead:
        reqs_e = _reqs(
            target_units_per_day=1200.0,
            forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
            notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
            allowed_action_types=MACHINE_ACTIONS_ONLY,  # Phase 8A: see note above
        )
        state_e = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs_e, max_iterations=5)
        assert state_e.iterations[0].accepted is False
        assert state_e.iterations[0].rejection_reason is not None


# 9. Determinism

class TestDeterminism:
    def test_repeated_orchestrator_run_is_deterministic(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state_a = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        state_b = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        assert state_a.model_dump() == state_b.model_dump()

    def test_render_trace_is_deterministic_and_templated(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1900.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=6)
        trace_a = render_trace(state)
        trace_b = render_trace(state)
        assert trace_a == trace_b
        assert "Iteration 0:" in trace_a
        assert "Stop reason: GOAL_REACHED." in trace_a


# 10. NO_FEASIBLE_IMPROVEMENT (open-ended objectives)

class TestOpenEndedObjectives:
    def test_maximize_throughput_stops_no_feasible_improvement_when_nothing_congested(self, electronics_factory: Factory):
        reqs = _reqs(objective=OptimizationObjective.MAXIMIZE_THROUGHPUT, target_units_per_day=1.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.stop_reason == PlanningStopReason.NO_FEASIBLE_IMPROVEMENT
        assert state.goal_reached is False

    def test_maximize_throughput_never_claims_goal_reached(self, electronics_factory: Factory):
        reqs = _reqs(objective=OptimizationObjective.MAXIMIZE_THROUGHPUT, target_units_per_day=1200.0)
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)
        assert state.goal_reached is False
        assert state.stop_reason in (
            PlanningStopReason.NO_FEASIBLE_IMPROVEMENT,
            PlanningStopReason.MAX_ITERATIONS,
            PlanningStopReason.REPEATED_PROPOSAL,
        )


# Phase 8A: time and staff as alternatives to buying equipment

class TestPhase8AAlternativesToBuying:
    """What the demonstrations above deliberately exclude."""

    def test_a_third_shift_reaches_the_target_when_the_bottleneck_is_forbidden(
        self, electronics_factory: Factory
    ):
        """
        Screwdriving may not be touched, yet the target is still met — by running 3 x 8h
        instead of 2 x 8h.
        """
        reqs = _reqs(target_units_per_day=1200.0, forbidden_machine_ids=["m-screwdriving"])
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)

        assert state.goal_reached is True
        assert state.stop_reason == PlanningStopReason.GOAL_REACHED
        accepted_types = {
            a.action_type
            for it in state.iterations if it.accepted and it.selected_proposal is not None
            for a in it.selected_proposal.scenario.actions
        }
        assert "CHANGE_SHIFT_CONFIGURATION" in accepted_types
        # The forbidden machine was never cloned.
        assert not any(m.parallel_of_machine_id == "m-screwdriving" for m in state.current_factory.machines)

    def test_reaching_the_target_by_time_costs_no_known_capex(self, electronics_factory: Factory):
        """A shift is not free — its cost is UNKNOWN, which is a different
        thing and must be reported as such (Phase 8A section 4)."""
        reqs = _reqs(target_units_per_day=1200.0, forbidden_machine_ids=["m-screwdriving"])
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)

        assert state.cumulative_known_capex == pytest.approx(0.0)
        shift_iterations = [
            it for it in state.iterations
            if it.accepted and it.selected_proposal is not None
            and any(a.action_type == "CHANGE_SHIFT_CONFIGURATION" for a in it.selected_proposal.scenario.actions)
        ]
        assert shift_iterations
        assert all(it.requires_cost_estimate for it in shift_iterations)

    def test_the_production_horizon_really_changed(self, electronics_factory: Factory):
        reqs = _reqs(target_units_per_day=1200.0, forbidden_machine_ids=["m-screwdriving"])
        state = PlanningOrchestrator().run(electronics_factory, PRODUCT_ID, reqs, max_iterations=5)

        baseline_hours = electronics_factory.shifts_per_day * electronics_factory.hours_per_shift
        final_hours = state.current_factory.shifts_per_day * state.current_factory.hours_per_shift
        assert final_hours > baseline_hours
        # And the simulation was genuinely run over the longer window.
        assert state.final_snapshot.simulation.simulation_time_seconds == pytest.approx(final_hours * 3600.0)
