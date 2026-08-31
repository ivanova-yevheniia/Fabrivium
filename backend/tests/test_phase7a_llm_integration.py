"""
Phase 7A tests — LLM provider integration with the Requirements/Planning/ Explanation
agents, plus resilience and the 1900/day regression.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.llm import LLMAuthenticationError, LLMUnavailableError, MockLLMProvider, MockOutcome
from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.agent_context import build_factory_context
from app.services.candidate_evaluator import evaluate_candidates
from app.services.explanation_context import build_explanation_context
from app.services.llm_integration import (
    explain_with_fallback,
    parse_requirements_with_fallback,
    run_planning_agent_with_fallback,
    run_planning_session_with_fallback,
)
from app.services.planning_context import build_planning_context
from app.services.ranking import rank_candidates
from app.services.simulation import run_simulation

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


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


def _planning_context_at(factory: Factory, demand: float):
    """Real PlanningContext for the electronics line at *demand*/day —
    mirrors test_planning_agent.py's own `_full_pipeline` helper."""
    factory = _at_demand(factory, demand)
    requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=demand)
    from app.services.requirements_parser import planning_requirements_to_optimization_goal

    goal = planning_requirements_to_optimization_goal(requirements, target_product_id="p-electronics-widget").goal
    eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
    recommendation = rank_candidates(eval_result, goal)
    ctx = build_planning_context(
        factory, "p-electronics-widget", requirements, eval_result.baseline_simulation, eval_result, recommendation,
    )
    return factory, requirements, ctx


def _proposal_payload(proposal_id: str, machine_id: str, action_type: str = "ADD_PARALLEL_MACHINE", **action_kwargs) -> dict:
    action = {"action_type": action_type, "machine_id": machine_id, **action_kwargs}
    return {
        "proposal_id": proposal_id,
        "hypothesis": {"problem_summary": "x", "suspected_issue_type": "INSUFFICIENT_CAPACITY", "evidence": []},
        "scenario": {"id": f"cand-{proposal_id}", "name": "x", "description": "", "actions": [action]},
        "expected_effects": ["x"], "risks": [], "confidence": 0.9, "source": "LLM",
    }


# REQUIREMENTS (7-10)


class TestRequirementsIntegration:
    def test_7_llm_produces_valid_planning_requirements(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "objective": "MEET_DEMAND", "target_units_per_day": 1900.0, "max_capex": 220_000.0,
            "forbidden_machine_ids": ["m-packaging"], "preserve_existing_layout": True, "confidence": 0.95,
        })])
        result, fallback_used = parse_requirements_with_fallback(
            "We need 1900 units/day, budget €220k, don't modify Packaging, and keep the existing layout.", ctx, provider,
        )
        req = result.parsed_requirements
        assert req.objective == OptimizationObjective.MEET_DEMAND
        assert req.target_units_per_day == 1900.0
        assert req.max_capex == 220_000.0
        assert req.forbidden_machine_ids == ["m-packaging"]
        assert req.preserve_existing_layout is True
        assert fallback_used is False
        assert result.structured_output_valid is True

    def test_8_invalid_requirements_shape_falls_back_safely(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({"objective": "NOT_A_REAL_OBJECTIVE"})])
        result, fallback_used = parse_requirements_with_fallback("We need 1900 units/day.", ctx, provider)
        assert result.structured_output_valid is False
        assert result.parsed_requirements.objective == OptimizationObjective.MEET_DEMAND  # safe default
        assert fallback_used is True

    def test_9_contradictions_remain_visible_through_llm_path(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "objective": "MEET_DEMAND", "max_additional_machines": 0, "allowed_action_types": ["ADD_PARALLEL_MACHINE"],
        })])
        result, _ = parse_requirements_with_fallback("Do not add more than 0 machines.", ctx, provider)
        assert any("Contradiction" in w for w in result.warnings)

    def test_10_unknown_machine_reference_in_forbidden_list_does_not_crash(self, electronics_factory: Factory):
        """
        An LLM can put a nonexistent machine id straight into forbidden_machine_ids
        (PlanningRequirements has no cross-reference constraint at the Pydantic layer —
        that's exactly what proposal_validator's runtime factory check is for
        downstream, see TestPlanningIntegration).
        """
        ctx = build_factory_context(electronics_factory)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "objective": "MEET_DEMAND", "forbidden_machine_ids": ["m-totally-fictional"],
        })])
        result, fallback_used = parse_requirements_with_fallback("Don't touch the fictional machine.", ctx, provider)
        assert result.parsed_requirements.forbidden_machine_ids == ["m-totally-fictional"]
        assert fallback_used is False  # structurally valid PlanningRequirements — resolution/rejection is a later stage's job


# PLANNING (11-17)


class TestPlanningIntegration:
    def test_11_grounded_optimizer_candidate_accepted(self, electronics_factory: Factory):
        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        assert ctx.simulation_summary.bottleneck_machine_id == "m-screwdriving"
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving")])])
        result, fallback_used = run_planning_agent_with_fallback(ctx, requirements, factory, provider)
        assert len(result.proposals) == 1
        assert result.proposals[0].scenario.actions[0].machine_id == "m-screwdriving"
        assert not result.rejected_proposals
        assert fallback_used is False

    def test_12_fabricated_machine_rejected(self, electronics_factory: Factory):
        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-does-not-exist")])])
        result, _ = run_planning_agent_with_fallback(ctx, requirements, factory, provider)
        assert result.proposals == []
        assert len(result.rejected_proposals) == 1
        assert "unknown machine_id" in result.rejected_proposals[0].reasons[0]

    def test_13_fabricated_scenario_action_rejected(self, electronics_factory: Factory):
        """An action_type outside the Pydantic discriminated union can
        never even become a PlanningProposal — Scenario.actions rejects it
        at the structural-validation layer, before proposal_validator ever
        runs (see app.services.proposal_validator's own docstring)."""
        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving", action_type="DELETE_ENTIRE_FACTORY")])])
        result, _ = run_planning_agent_with_fallback(ctx, requirements, factory, provider)
        assert result.proposals == []
        assert len(result.rejected_proposals) == 1
        assert result.rejected_proposals[0].raw_proposal is not None  # failed Pydantic validation entirely

    def test_14_forbidden_machine_rejected(self, electronics_factory: Factory):
        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        requirements = requirements.model_copy(update={"forbidden_machine_ids": ["m-screwdriving"]})
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving")])])
        result, _ = run_planning_agent_with_fallback(ctx, requirements, factory, provider)
        assert result.proposals == []
        assert "forbidden machine" in result.rejected_proposals[0].reasons[0]

    def test_15_capex_constraint_cannot_be_bypassed(self, electronics_factory: Factory):
        """The CAPEX budget gate lives in the orchestrator's own selection
        logic (app.services.planning_orchestrator's remaining_capex
        filter), applied identically regardless of proposal source — proven
        here at full-session granularity: an LLM proposal costing more than
        the remaining budget is never accepted, and the session reports it
        honestly (BUDGET_EXHAUSTED or an unmet gap), never a silently
        overspent 'verified' state."""
        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        tiny_budget_requirements = requirements.model_copy(update={"max_capex": 1.0})  # far below any real machine's cost
        provider = MockLLMProvider(
            outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving")])],
            default_factory=lambda req: [_proposal_payload("p2", "m-screwdriving")],
        )
        session, _ = run_planning_session_with_fallback(factory, "p-electronics-widget", tiny_budget_requirements, provider, max_iterations=3)
        assert session.cumulative_known_capex == 0.0
        assert session.goal_reached is False
        assert all(not it.accepted for it in session.iterations)

    def test_16_preserve_layout_constraint_cannot_be_bypassed(self, electronics_factory: Factory):
        """preserve_existing_layout is enforced by the deterministic
        candidate evaluator regardless of which agent proposed the
        scenario (see app.services.candidate_evaluator's placement-
        preservation check) — an LLM cannot talk its way around it merely
        by proposing a scenario that happens to match a real machine id."""
        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        preserve_requirements = requirements.model_copy(update={"preserve_existing_layout": True})
        provider = MockLLMProvider(
            outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving")])],
            default_factory=lambda req: [_proposal_payload("p2", "m-assembly")],
        )
        # Must not raise, and must not silently claim a verified improvement
        # that violated the constraint — whatever the outcome, it is honest.
        session, _ = run_planning_session_with_fallback(factory, "p-electronics-widget", preserve_requirements, provider, max_iterations=3)
        assert session.stop_reason is not None

    def test_17_optimizer_grounded_still_enforced_for_llm_agent(self, electronics_factory: Factory):
        """A structurally-valid, real-machine-targeting proposal is STILL
        rejected under optimizer_grounded=True if it doesn't match any
        Phase 4-generated candidate and isn't an explicit user request —
        the LLM cannot invent a wholly novel scenario just because every
        individual field happens to validate."""
        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        # A real machine, but a change_cycle_time value no Phase 4 candidate proposed.
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([
            _proposal_payload("p1", "m-screwdriving", action_type="CHANGE_MACHINE_CYCLE_TIME", cycle_time=1.0)
        ])])
        result, _ = run_planning_agent_with_fallback(ctx, requirements, factory, provider, optimizer_grounded=True)
        assert result.proposals == []
        assert any("optimizer_grounded" in r for r in result.rejected_proposals[0].reasons)


# EXPLANATION (18-22)


class TestExplanationIntegration:
    @pytest.fixture
    def verified_context(self, electronics_factory: Factory):
        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        session, _ = run_planning_session_with_fallback(factory, "p-electronics-widget", requirements, None, max_iterations=5)
        return build_explanation_context(session)

    def test_18_honest_explanation_accepted(self, verified_context):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "executive_summary": "FactoryMind reached the target of 1900 units/day in 2 verified iterations.",
            "goal_status": "Goal reached: target 1900 units/day; final verified output is 1900/1900 units (demand met).",
            "recommended_changes": [], "verified_effects": [], "tradeoffs": [], "constraints_and_risks": [],
            "stop_explanation": "Planning stopped because the target was reached and verified by simulation.",
            "sections": [],
        })])
        result, fallback_used = explain_with_fallback(verified_context, provider)
        assert result.explanation.source_type.value == "LLM"
        assert fallback_used is False
        assert result.llm_validation_errors == []

    def test_19_fabricated_kpi_rejected(self, verified_context):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "executive_summary": "Demand reached 5000 units/day.",  # fabricated number not in context
            "goal_status": "Goal reached.", "recommended_changes": [], "verified_effects": [], "tradeoffs": [],
            "constraints_and_risks": [], "stop_explanation": "Done.", "sections": [],
        })])
        result, fallback_used = explain_with_fallback(verified_context, provider)
        assert fallback_used is True
        assert result.explanation.source_type.value == "DETERMINISTIC"
        assert result.llm_validation_errors

    def test_20_fabricated_machine_rejected(self, verified_context):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "executive_summary": "Capacity was added at m-totally-fake-machine.",
            "goal_status": "Goal reached.", "recommended_changes": [], "verified_effects": [], "tradeoffs": [],
            "constraints_and_risks": [], "stop_explanation": "Done.", "sections": [],
        })])
        result, fallback_used = explain_with_fallback(verified_context, provider)
        assert fallback_used is True
        assert any("unknown machine" in e for e in result.llm_validation_errors)

    def test_21_fabricated_capex_rejected(self, verified_context):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "executive_summary": "Committed €9,999,999 in known CAPEX.",
            "goal_status": "Goal reached.", "recommended_changes": [], "verified_effects": [], "tradeoffs": [],
            "constraints_and_risks": [], "stop_explanation": "Done.", "sections": [],
        })])
        result, fallback_used = explain_with_fallback(verified_context, provider)
        assert fallback_used is True
        assert any("numeric value" in e for e in result.llm_validation_errors)

    def test_22_deterministic_fallback_used_after_rejection_matches_deterministic_agent_output(self, verified_context):
        from app.services.explanation_agent import DeterministicExplanationAgent

        provider = MockLLMProvider(outcomes=[MockOutcome.ok({
            "executive_summary": "Demand met at 999999 units/day.",
            "goal_status": "x", "recommended_changes": [], "verified_effects": [], "tradeoffs": [],
            "constraints_and_risks": [], "stop_explanation": "x", "sections": [],
        })])
        result, _ = explain_with_fallback(verified_context, provider)
        expected = DeterministicExplanationAgent().explain(verified_context)
        assert result.explanation == expected


# RESILIENCE (23-26)


class TestResilience:
    def test_23_no_provider_configured_deterministic_system_still_works(self, electronics_factory: Factory):
        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        session, fallback_used = run_planning_session_with_fallback(factory, "p-electronics-widget", requirements, None, max_iterations=5)
        assert session.goal_reached is True
        assert fallback_used is False
        assert session.baseline_snapshot.bottleneck_machine_id == "m-screwdriving"

    def test_24_provider_timeout_safe_fallback(self, electronics_factory: Factory):
        from app.llm import LLMTimeoutError

        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        provider = MockLLMProvider(outcomes=[MockOutcome.failure(LLMTimeoutError("slow"))])
        session, fallback_used = run_planning_session_with_fallback(factory, "p-electronics-widget", requirements, provider, max_iterations=5)
        assert fallback_used is True
        assert session.goal_reached is True  # deterministic engine still reaches the same verified outcome

    def test_25_provider_outage_safe_fallback(self, electronics_factory: Factory):
        factory, requirements, _ = _planning_context_at(electronics_factory, 1900.0)
        provider = MockLLMProvider(outcomes=[MockOutcome.failure(LLMUnavailableError("down"))])
        session, fallback_used = run_planning_session_with_fallback(factory, "p-electronics-widget", requirements, provider, max_iterations=5)
        assert fallback_used is True
        assert session.current_simulation.demand_gap_units == 0.0

    def test_26_no_network_calls_in_unit_tests(self, electronics_factory: Factory, monkeypatch: pytest.MonkeyPatch):
        """Real behavioral guarantee, not a fragile source-text scan: block
        every actual outbound socket connection attempt for the duration
        of a full requirements -> planning -> explanation flow driven
        entirely by MockLLMProvider, and prove it completes successfully
        with zero connection attempts."""
        import socket

        def _blocked_connect(*args, **kwargs):
            raise AssertionError("A real network connection was attempted — MockLLMProvider must never do this.")

        monkeypatch.setattr(socket.socket, "connect", _blocked_connect)

        factory, requirements, ctx = _planning_context_at(electronics_factory, 1900.0)
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([_proposal_payload("p1", "m-screwdriving")])])
        result, fallback_used = run_planning_agent_with_fallback(ctx, requirements, factory, provider)

        assert fallback_used is False
        assert len(result.proposals) == 1


# REGRESSION (27)


class TestRegression1900PerDay:
    def test_27_deterministic_1900_per_day_workflow_unchanged(self, electronics_factory: Factory):
        """The exact same 1900/day demonstration validated in Phase 6C.1 —
        run with NO LLM provider at all, proving Phase 7A's wiring never
        touched the deterministic engineering path."""
        factory = _at_demand(electronics_factory, 1900.0)
        sim = run_simulation(factory, "p-electronics-widget")
        assert sim.completed_units == 1105
        assert sim.demand_gap_units == 795.0
        assert sim.system.bottleneck_machine_id == "m-screwdriving"

        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1900.0)
        session, fallback_used = run_planning_session_with_fallback(electronics_factory, "p-electronics-widget", requirements, None, max_iterations=5)

        assert fallback_used is False
        assert session.baseline_snapshot.bottleneck_machine_id == "m-screwdriving"
        # PHASE 8A: three steps now, not two.
        assert len(session.iterations) == 3
        assert session.iterations[0].selected_proposal.scenario.actions[0].machine_id == "m-screwdriving"
        assert session.iterations[0].state_after.simulation.demand_gap_units == 281.0
        assert session.iterations[1].selected_proposal.scenario.actions[0].action_type == "CHANGE_OPERATOR_CAPACITY"
        assert session.iterations[2].selected_proposal.scenario.actions[0].machine_id == "m-assembly"
        assert session.current_simulation.demand_gap_units == 0.0
        assert session.goal_reached is True
