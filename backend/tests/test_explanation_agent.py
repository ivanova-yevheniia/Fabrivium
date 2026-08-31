"""FactoryMind Phase 5D - explanation agent tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.agent import PlanningRequirements
from app.models.explanation import ExplanationSourceType, PlanningExplanation
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.explanation_agent import (
    DeterministicExplanationAgent,
    LLMExplanationAgent,
    generate_explanation,
)
from app.services.explanation_context import build_explanation_context
from app.services.explanation_validator import validate_explanation
from app.services.planning_orchestrator import PlanningOrchestrator

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


def _run(factory: Factory, reqs: PlanningRequirements, **kwargs):
    kwargs.setdefault("max_iterations", 5)
    return PlanningOrchestrator().run(factory, PRODUCT_ID, reqs, **kwargs)


# Phase 8A note.
MACHINE_ACTIONS_ONLY = ["ADD_PARALLEL_MACHINE"]

REQS_A = lambda: _reqs(target_units_per_day=1200.0)
REQS_B = lambda: _reqs(target_units_per_day=1900.0)
REQS_C = lambda: _reqs(target_units_per_day=1200.0, max_capex=80_000.0)
REQS_D = lambda: _reqs(
    target_units_per_day=1200.0,
    forbidden_machine_ids=["m-screwdriving"],
    allowed_action_types=MACHINE_ACTIONS_ONLY,
)
REQS_E = lambda: _reqs(
    target_units_per_day=1200.0,
    forbidden_machine_ids=["m-screwdriving", "m-assembly", "m-inspection"],
    notes=["User explicitly requested: ADD_PARALLEL_MACHINE at m-packaging."],
    allowed_action_types=MACHINE_ACTIONS_ONLY,
)


# 1. build_explanation_context

class TestExplanationContext:
    def test_baseline_and_final_facts_present(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        assert ctx.baseline_demand_gap == 95.0
        assert ctx.baseline_demand_met is False
        assert ctx.final_demand_met is True
        assert ctx.final_demand_gap == 0.0
        assert ctx.goal_reached is True
        assert ctx.stop_reason == "GOAL_REACHED"

    def test_accepted_and_rejected_iteration_split(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_E())
        ctx = build_explanation_context(state)
        assert len(ctx.accepted_iterations) == 0
        assert len(ctx.rejected_iterations) >= 1

    def test_known_machine_ids_cover_factory(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        assert "m-screwdriving" in ctx.known_machine_ids
        assert "m-assembly" in ctx.known_machine_ids

    def test_budget_facts_reflect_session_state(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        assert ctx.budget.cumulative_known_capex == state.cumulative_known_capex
        assert ctx.budget.remaining_known_capex == state.remaining_known_capex

    def test_does_not_mutate_session_state(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        before = state.model_dump()
        build_explanation_context(state)
        assert state.model_dump() == before


# 2. Deterministic explanation — determinism, structure

class TestDeterministicExplanation:
    def test_identical_across_runs(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        exp_a = DeterministicExplanationAgent().explain(ctx)
        exp_b = DeterministicExplanationAgent().explain(ctx)
        assert exp_a.model_dump() == exp_b.model_dump()

    def test_source_type_is_deterministic(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert exp.source_type == ExplanationSourceType.DETERMINISTIC

    def test_minimum_sections_present(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        titles = {s.title for s in exp.sections}
        assert {
            "Executive Summary", "Goal Status", "What Changed",
            "Tradeoffs", "Why Planning Stopped", "Next Information Needed",
        } <= titles

    def test_all_accepted_iterations_represented(self, electronics_factory: Factory):
        """
        Phase 8A: the 1900/day plan is three accepted steps now, not two — relieve
        Screwdriving, hire the staff that the next machine needs, then buy it.
        """
        state = _run(electronics_factory, REQS_B(), max_iterations=6)
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert len(exp.recommended_changes) == len(ctx.accepted_iterations) == 3
        for fact in ctx.accepted_iterations:
            assert f"Iteration {fact.iteration_number}" in exp.verified_effects[0] or any(
                f"Iteration {fact.iteration_number}" in e for e in exp.verified_effects
            )


# 3. Numeric fidelity

class TestNumericFidelity:
    def test_demand_gap_numbers_match_session_state(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert "795" in exp.executive_summary
        assert "258" in exp.executive_summary
        assert str(state.iterations[0].scenario_result.candidate_result.demand_gap_units).split(".")[0] in exp.executive_summary

    def test_capex_number_matches_cumulative_capex(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert f"{state.cumulative_known_capex:,.0f}" in " ".join(exp.tradeoffs)


# 4. Budget / forbidden / neutral-proposal correctness

class TestScenarioCorrectness:
    def test_budget_stop_explanation_mentions_budget(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_C())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert "budget" in exp.stop_explanation.lower()
        assert "CAPEX" in exp.stop_explanation
        assert ctx.goal_reached is False

    def test_forbidden_constraint_explanation_names_machine(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_D())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert "Screwdriving" in exp.stop_explanation
        assert any("m-screwdriving" in item for item in exp.constraints_and_risks)

    def test_neutral_proposal_never_described_as_improvement(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_E())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert exp.recommended_changes == []
        blob = " ".join(exp.verified_effects).lower()
        assert "improved" not in blob

    def test_unmet_target_never_described_as_met(self, electronics_factory: Factory):
        for reqs in (REQS_C(), REQS_D(), REQS_E()):
            state = _run(electronics_factory, reqs)
            ctx = build_explanation_context(state)
            exp = DeterministicExplanationAgent().explain(ctx)
            assert ctx.final_demand_met is False
            assert validate_explanation(exp, ctx) == []


# 5. Evidence references

class TestEvidenceRefs:
    def test_sections_carry_evidence_refs(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        for section in exp.sections:
            if section.title in ("Executive Summary", "Goal Status", "Why Planning Stopped"):
                assert section.evidence_refs

    def test_accepted_iteration_facts_have_evidence_refs(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        for fact in ctx.accepted_iterations:
            assert any(ref.startswith(f"iteration:{fact.iteration_number}:") for ref in fact.evidence_refs)
            assert f"iteration:{fact.iteration_number}:scenario_result" in fact.evidence_refs

    def test_no_stack_trace_or_python_object_paths_leak(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        blob = exp.executive_summary + " ".join(exp.tradeoffs) + " ".join(exp.verified_effects)
        assert "Traceback" not in blob
        assert "0x" not in blob
        assert "app.models" not in blob
        assert "app.services" not in blob


# 6. Hallucination guard

class TestHallucinationGuard:
    def test_false_demand_met_claim_rejected(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_C())
        ctx = build_explanation_context(state)
        assert ctx.final_demand_met is False

        det = DeterministicExplanationAgent().explain(ctx)
        bad = det.model_copy(update={
            "executive_summary": "Demand is met and the target was reached.",
            "source_type": ExplanationSourceType.LLM,
        })
        violations = validate_explanation(bad, ctx)
        assert any("demand" in v.lower() for v in violations)

    def test_unknown_machine_id_rejected(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        det = DeterministicExplanationAgent().explain(ctx)
        bad = det.model_copy(update={"recommended_changes": ["Added parallel machine at m-does-not-exist."]})
        violations = validate_explanation(bad, ctx)
        assert any("unknown machine id" in v.lower() for v in violations)

    def test_fabricated_numeric_value_rejected(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        det = DeterministicExplanationAgent().explain(ctx)
        bad = det.model_copy(update={"tradeoffs": ["Total spend was €4,321,000."]})
        violations = validate_explanation(bad, ctx)
        assert any("numeric" in v.lower() for v in violations)

    def test_valid_deterministic_explanation_has_no_violations(self, electronics_factory: Factory):
        for reqs in (REQS_A(), REQS_B(), REQS_C(), REQS_D(), REQS_E()):
            state = _run(electronics_factory, reqs)
            ctx = build_explanation_context(state)
            exp = DeterministicExplanationAgent().explain(ctx)
            assert validate_explanation(exp, ctx) == []

    def test_generate_explanation_falls_back_on_hallucination(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_C())
        ctx = build_explanation_context(state)

        def hallucinating(_prompt, _ctx):
            return {
                "executive_summary": "Demand is met.",
                "goal_status": "Goal reached.",
                "recommended_changes": [],
                "verified_effects": [],
                "tradeoffs": [],
                "constraints_and_risks": [],
                "stop_explanation": "Stopped: demand met.",
                "sections": [],
            }

        agent = LLMExplanationAgent(completion_fn=hallucinating)
        result = generate_explanation(agent, ctx)
        assert result.llm_attempted is True
        assert result.used_fallback is True
        assert result.llm_validation_errors
        assert result.explanation.source_type == ExplanationSourceType.DETERMINISTIC

    def test_generate_explanation_deterministic_fallback_matches_direct_call(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)

        def hallucinating(_prompt, _ctx):
            return {
                "executive_summary": "x", "goal_status": "x", "recommended_changes": [],
                "verified_effects": [], "tradeoffs": [], "constraints_and_risks": [],
                "stop_explanation": "Referencing m-fake-machine.", "sections": [],
            }

        agent = LLMExplanationAgent(completion_fn=hallucinating)
        result = generate_explanation(agent, ctx)
        direct = DeterministicExplanationAgent().explain(ctx)
        assert result.explanation.model_dump() == direct.model_dump()

    def test_valid_llm_explanation_passes_through(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        det = DeterministicExplanationAgent().explain(ctx)

        def honest(_prompt, _ctx):
            d = det.model_dump()
            d.pop("source_type", None)
            return d

        agent = LLMExplanationAgent(completion_fn=honest)
        result = generate_explanation(agent, ctx)
        assert result.used_fallback is False
        assert result.explanation.source_type == ExplanationSourceType.LLM


# 7. LLM explanation agent interface/stub

class TestLLMExplanationAgentInterface:
    def test_raises_without_completion_fn(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        agent = LLMExplanationAgent()
        with pytest.raises(NotImplementedError):
            agent.explain(ctx)

    def test_malformed_structured_output_falls_back(self, electronics_factory: Factory):
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)

        def malformed(_prompt, _ctx):
            return {"executive_summary": "x"}  # missing required fields

        agent = LLMExplanationAgent(completion_fn=malformed)
        result = generate_explanation(agent, ctx)
        assert result.used_fallback is True
        assert result.explanation.source_type == ExplanationSourceType.DETERMINISTIC

    def test_no_network_calls(self, electronics_factory: Factory):
        # DeterministicExplanationAgent and the validator are pure/offline by
        # construction — this test just exercises the full path with no
        # completion_fn configured at all, proving no transport is required.
        state = _run(electronics_factory, REQS_A())
        ctx = build_explanation_context(state)
        result = generate_explanation(DeterministicExplanationAgent(), ctx)
        assert result.llm_attempted is False


# 8. Immutability

class TestImmutability:
    def test_baseline_factory_untouched(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        state = _run(electronics_factory, REQS_B())
        ctx = build_explanation_context(state)
        DeterministicExplanationAgent().explain(ctx)
        assert electronics_factory.model_dump() == before
        assert state.baseline_factory.model_dump() == before


# 9.

class TestDemonstrations:
    @pytest.mark.parametrize("reqs_factory", [REQS_A, REQS_B, REQS_C, REQS_D, REQS_E])
    def test_produces_complete_explanation(self, electronics_factory: Factory, reqs_factory):
        state = _run(electronics_factory, reqs_factory())
        ctx = build_explanation_context(state)
        exp = DeterministicExplanationAgent().explain(ctx)
        assert isinstance(exp, PlanningExplanation)
        assert exp.executive_summary
        assert exp.goal_status
        assert exp.stop_explanation
        assert exp.sections
        assert validate_explanation(exp, ctx) == []
