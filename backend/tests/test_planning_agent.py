"""FactoryMind Phase 5B – planning agent foundation tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.models.optimization import OptimizationGoal, OptimizationObjective
from app.models.planning_agent import PlanningProposal, ProposalSource
from app.services.agent_context import build_factory_context
from app.services.candidate_evaluator import evaluate_candidates
from app.services.planning_agent import (
    DeterministicPlanningAgent,
    LLMPlanningAgent,
    run_planning_agent,
)
from app.services.planning_context import build_planning_context
from app.services.proposal_validator import validate_planning_proposal
from app.services.ranking import rank_candidates
from app.services.requirements_parser import (
    DeterministicFallbackRequirementsParser,
    planning_requirements_to_optimization_goal,
)

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


def _full_pipeline(factory: Factory, nl_request: str, goal_overrides: dict | None = None):
    """End-to-end: parse -> map -> evaluate -> rank -> context -> propose."""
    ctx = build_factory_context(factory)
    parser = DeterministicFallbackRequirementsParser()
    parsed = parser.parse(nl_request, ctx)
    requirements = parsed.parsed_requirements
    mapping = planning_requirements_to_optimization_goal(requirements, target_product_id="p-electronics-widget")
    goal = mapping.goal.model_copy(update=goal_overrides) if goal_overrides else mapping.goal
    eval_result = evaluate_candidates(factory, "p-electronics-widget", goal)
    recommendation = rank_candidates(eval_result, goal)
    planning_context = build_planning_context(
        factory, "p-electronics-widget", requirements, eval_result.baseline_simulation, eval_result, recommendation,
    )
    agent = DeterministicPlanningAgent()
    result = run_planning_agent(agent, planning_context, requirements, factory, optimizer_grounded=True)
    return result, requirements, planning_context


# 1. PlanningContext builder

class TestPlanningContextBuilder:
    def test_compact_fields(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        _, _, ctx = _full_pipeline(factory, "We need 1500 units per day.")
        assert ctx.simulation_summary.product_id == "p-electronics-widget"
        assert ctx.simulation_summary.bottleneck_machine_id == "m-screwdriving"
        assert len(ctx.machines) == 4
        assert len(ctx.pool_summaries) == 4
        assert ctx.proposal_history == []

    def test_candidate_summaries_carry_full_scenario(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        _, _, ctx = _full_pipeline(factory, "We need 1500 units per day.")
        cand = next(c for c in ctx.candidate_summaries if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert cand.scenario.actions[0].action_type == "ADD_PARALLEL_MACHINE"
        assert cand.scenario.actions[0].machine_id == "m-screwdriving"

    def test_no_layout_summary_when_not_supplied(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        _, _, ctx = _full_pipeline(factory, "We need 1500 units per day.")
        assert ctx.layout_validation_summary is None

    def test_context_builder_does_not_mutate_factory(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        before = factory.model_dump()
        _full_pipeline(factory, "We need 1500 units per day.")
        assert factory.model_dump() == before

    def test_empty_candidate_summaries_when_no_evaluation_supplied(self, electronics_factory: Factory):
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        parser = DeterministicFallbackRequirementsParser()
        requirements = parser.parse("Maximize throughput.", build_factory_context(factory)).parsed_requirements
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)
        assert ctx.candidate_summaries == []


# 2. Deterministic proposal generation

class TestDeterministicProposalGeneration:
    def test_screwdriving_proposal_present_with_measured_evidence(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert "Screwdriving" in proposal.hypothesis.problem_summary
        # "bottleneck" is asserted as measured EVIDENCE, not folded into the
        # summary sentence itself — matches the spec's own example exactly
        # (hypothesis: "Current demand shortfall is primarily constrained
        # by Screwdriving capacity."; evidence: "Screwdriving is the
        # measured bottleneck.").
        assert any("bottleneck" in e.lower() for e in proposal.hypothesis.evidence)

        # Phase 8A note: the queue literal that used to be pinned here (46.98) predates
        # finite buffers.
        from app.services.simulation import run_simulation

        # The evidence describes the factory AS IT IS (1200/day here), which
        # is the baseline the planning context was built from — not the
        # 1500/day target the request asks for.
        baseline = run_simulation(factory, "p-electronics-widget")
        pool = next(p for p in baseline.process_pool_kpis if p.reference_machine_id == "m-screwdriving")
        assert any(f"{pool.utilization:.2%}" in e for e in proposal.hypothesis.evidence)
        assert any(f"{pool.average_queue_length:.2f}" in e for e in proposal.hypothesis.evidence)
        assert any(f"{baseline.demand_gap_units:g}" in e for e in proposal.hypothesis.evidence)

    def test_proposal_scenario_is_typed_and_valid(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        for proposal in result.proposals:
            assert isinstance(proposal, PlanningProposal)
            assert len(proposal.scenario.actions) > 0

    def test_optimizer_grounded_preserves_scenario_exactly(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, ctx = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        candidate = next(c for c in ctx.candidate_summaries if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert proposal.scenario.model_dump() == candidate.scenario.model_dump()

    def test_expected_effects_are_directional_not_verified(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert any("capacity" in e.lower() for e in proposal.expected_effects)
        assert any("queue" in e.lower() for e in proposal.expected_effects)

    def test_risks_include_new_bottleneck_and_cost(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert any("new bottleneck" in r.lower() for r in proposal.risks)
        assert any("85,000" in r or "85000" in r for r in proposal.risks)

    def test_source_is_deterministic(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        for p in result.proposals:
            assert p.source == ProposalSource.DETERMINISTIC
        assert result.agent_type == ProposalSource.DETERMINISTIC

    def test_no_field_claims_verified_outcome(self):
        fields = set(PlanningProposal.model_fields.keys())
        forbidden = {"demand_will_be_met", "verified_improvement", "guaranteed_outcome"}
        assert fields.isdisjoint(forbidden)


# 3. Proposal validator

class TestProposalValidator:
    def test_valid_proposal_passes(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, requirements, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert validate_planning_proposal(proposal, requirements, factory) == []

    def test_unknown_machine_id_rejected(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import AddParallelMachineAction, Scenario

        factory = _at_demand(electronics_factory, 1200.0)
        proposal = PlanningProposal(
            proposal_id="p-1",
            hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
            scenario=Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="does-not-exist")]),
            confidence=0.5,
            source=ProposalSource.LLM,
        )
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        reasons = validate_planning_proposal(proposal, requirements, factory)
        assert any("unknown machine_id" in r for r in reasons)

    def test_forbidden_machine_rejected(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import AddParallelMachineAction, Scenario

        factory = _at_demand(electronics_factory, 1200.0)
        proposal = PlanningProposal(
            proposal_id="p-1",
            hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
            scenario=Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")]),
            confidence=0.5,
            source=ProposalSource.LLM,
        )
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, forbidden_machine_ids=["m-screwdriving"])
        reasons = validate_planning_proposal(proposal, requirements, factory)
        assert any("forbidden" in r.lower() for r in reasons)

    def test_forbidden_pool_expansion_reused(self, electronics_factory: Factory):
        """Forbidding the ROOT must also catch a proposal targeting an
        existing clone — reuses Phase 5A.1's process-pool expansion."""
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import ChangeMachineCycleTimeAction, Scenario
        from app.services.scenario import apply_scenario
        from app.models.scenario import AddParallelMachineAction, Scenario as ScenarioModel

        base = _at_demand(electronics_factory, 1600.0)
        factory = apply_scenario(base, ScenarioModel(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")]))
        proposal = PlanningProposal(
            proposal_id="p-1",
            hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
            scenario=Scenario(id="s2", name="x", actions=[ChangeMachineCycleTimeAction(machine_id="m-screwdriving-parallel-1", cycle_time=40.0)]),
            confidence=0.5,
            source=ProposalSource.LLM,
        )
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, forbidden_machine_ids=["m-screwdriving"])
        reasons = validate_planning_proposal(proposal, requirements, factory)
        assert any("forbidden" in r.lower() for r in reasons)

    def test_disallowed_action_type_rejected(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import ChangeMachineCycleTimeAction, Scenario

        factory = _at_demand(electronics_factory, 1200.0)
        proposal = PlanningProposal(
            proposal_id="p-1",
            hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
            scenario=Scenario(id="s", name="x", actions=[ChangeMachineCycleTimeAction(machine_id="m-screwdriving", cycle_time=40.0)]),
            confidence=0.5,
            source=ProposalSource.LLM,
        )
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        reasons = validate_planning_proposal(proposal, requirements, factory)
        assert any("disallowed" in r.lower() for r in reasons)

    def test_max_additional_machines_exceeded_rejected(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import AddParallelMachineAction, Scenario

        factory = _at_demand(electronics_factory, 1200.0)
        proposal = PlanningProposal(
            proposal_id="p-1",
            hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
            scenario=Scenario(
                id="s", name="x",
                actions=[
                    AddParallelMachineAction(machine_id="m-screwdriving"),
                    AddParallelMachineAction(machine_id="m-packaging"),
                ],
            ),
            confidence=0.5,
            source=ProposalSource.LLM,
        )
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_additional_machines=1)
        reasons = validate_planning_proposal(proposal, requirements, factory)
        assert any("max_additional_machines" in r for r in reasons)

    def test_validator_does_not_mutate_anything(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, requirements, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = result.proposals[0]
        before_factory = factory.model_dump()
        before_req = requirements.model_dump()
        validate_planning_proposal(proposal, requirements, factory)
        assert factory.model_dump() == before_factory
        assert requirements.model_dump() == before_req


# 4. Optimizer-grounded mode

class TestOptimizerGroundedMode:
    def test_novel_scenario_rejected_when_grounded(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningContext, PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import ChangeMachineCycleTimeAction, Scenario
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)  # no candidates at all

        class NovelAgent:
            def propose(self, context: PlanningContext) -> list[PlanningProposal]:
                return [PlanningProposal(
                    proposal_id="novel-1",
                    hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
                    scenario=Scenario(id="s", name="x", actions=[ChangeMachineCycleTimeAction(machine_id="m-inspection", cycle_time=20.0)]),
                    confidence=0.5,
                    source=ProposalSource.LLM,
                )]

        result = run_planning_agent(NovelAgent(), ctx, requirements, factory, optimizer_grounded=True)
        assert result.proposals == []
        assert len(result.rejected_proposals) == 1
        assert any("optimizer_grounded" in r for r in result.rejected_proposals[0].reasons)

    def test_novel_scenario_allowed_when_not_grounded(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.models.planning_agent import PlanningContext, PlanningHypothesis, SuspectedIssueType
        from app.models.scenario import ChangeMachineCycleTimeAction, Scenario
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)

        class NovelAgent:
            def propose(self, context: PlanningContext) -> list[PlanningProposal]:
                return [PlanningProposal(
                    proposal_id="novel-1",
                    hypothesis=PlanningHypothesis(problem_summary="x", suspected_issue_type=SuspectedIssueType.UNKNOWN),
                    scenario=Scenario(id="s", name="x", actions=[ChangeMachineCycleTimeAction(machine_id="m-inspection", cycle_time=20.0)]),
                    confidence=0.5,
                    source=ProposalSource.LLM,
                )]

        result = run_planning_agent(NovelAgent(), ctx, requirements, factory, optimizer_grounded=False)
        assert len(result.proposals) == 1
        assert result.optimizer_grounded is False

    def test_deterministic_agent_always_passes_grounding(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        assert len(result.proposals) > 0
        assert result.rejected_proposals == [] or all(
            "optimizer_grounded" not in r for rej in result.rejected_proposals for r in rej.reasons
        )


# 5. User-requested interventions

class TestUserRequestedInterventions:
    def test_packaging_request_surfaced(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, requirements, _ = _full_pipeline(factory, "Add a second Packaging machine.")
        assert requirements.notes  # captured the request
        assert any("packaging" in p.proposal_id.lower() for p in result.proposals)

    def test_user_requested_not_claimed_beneficial(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "Add a second Packaging machine.")
        proposal = next(p for p in result.proposals if "packaging" in p.proposal_id.lower())
        combined_text = " ".join(proposal.expected_effects).lower()
        for claim_word in ("improve", "faster", "better", "optimal", "will increase throughput"):
            assert claim_word not in combined_text
        assert "user" in proposal.hypothesis.problem_summary.lower() or "requested" in proposal.hypothesis.problem_summary.lower()

    def test_user_requested_has_lower_confidence_than_evidence_based(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "Add a second Packaging machine.")
        packaging = next(p for p in result.proposals if "packaging" in p.proposal_id.lower())
        screwdriving = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert packaging.confidence < screwdriving.confidence

    def test_user_requested_passes_optimizer_grounding_despite_not_being_a_candidate(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "Add a second Packaging machine.")
        packaging_proposals = [p for p in result.proposals if "packaging" in p.proposal_id.lower()]
        assert len(packaging_proposals) == 1  # accepted, not rejected by grounding


# 6. LLM planning agent interface/stub

class TestLLMPlanningAgentStub:
    def test_no_completion_fn_raises(self):
        agent = LLMPlanningAgent()
        with pytest.raises(NotImplementedError):
            agent.propose(None)

    def test_injected_completion_fn_returns_proposals(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)

        def fake_completion(prompt, context):
            return [{
                "proposal_id": "llm-1",
                "hypothesis": {"problem_summary": "x", "suspected_issue_type": "UNKNOWN"},
                "scenario": {"id": "s", "name": "x", "actions": [{"action_type": "CHANGE_MACHINE_CYCLE_TIME", "machine_id": "m-screwdriving", "cycle_time": 40.0}]},
                "confidence": 0.6,
                "source": "LLM",
            }]

        agent = LLMPlanningAgent(completion_fn=fake_completion)
        proposals = agent.propose(ctx)
        assert len(proposals) == 1
        assert proposals[0].proposal_id == "llm-1"

    def test_invalid_raw_output_becomes_rejection_not_crash(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)

        def bad_completion(prompt, context):
            return [{"proposal_id": "bad-1", "confidence": 2.0}]  # confidence out of [0,1], missing fields

        agent = LLMPlanningAgent(completion_fn=bad_completion)
        proposals, rejections = agent.propose_with_rejections(ctx)
        assert proposals == []
        assert len(rejections) == 1
        assert rejections[0].raw_proposal == {"proposal_id": "bad-1", "confidence": 2.0}

    def test_unsupported_action_type_rejected_before_execution(self, electronics_factory: Factory):
        from app.models.agent import PlanningRequirements
        from app.models.optimization import OptimizationObjective
        from app.services.simulation import run_simulation

        factory = _at_demand(electronics_factory, 1200.0)
        sim = run_simulation(factory, "p-electronics-widget")
        requirements = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        ctx = build_planning_context(factory, "p-electronics-widget", requirements, sim)

        def bad_completion(prompt, context):
            return [{
                "proposal_id": "bad-2",
                "hypothesis": {"problem_summary": "x", "suspected_issue_type": "UNKNOWN"},
                "scenario": {"id": "s", "name": "x", "actions": [{"action_type": "DELETE_EVERYTHING", "machine_id": "m-1"}]},
                "confidence": 0.5,
                "source": "LLM",
            }]

        agent = LLMPlanningAgent(completion_fn=bad_completion)
        result = run_planning_agent(agent, ctx, requirements, factory, optimizer_grounded=True)
        assert result.proposals == []
        assert len(result.rejected_proposals) == 1
        assert result.rejected_proposals[0].proposal is None
        assert result.rejected_proposals[0].raw_proposal is not None

    def test_module_has_no_provider_specific_transport(self):
        import app.services.planning_agent as mod
        source = pathlib.Path(mod.__file__).read_text()
        for forbidden in ("import requests", "import httpx", "import openai", "import anthropic"):
            assert forbidden not in source.lower()


# 7. Determinism / immutability

class TestDeterminismAndImmutability:
    def test_repeated_result_identical(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result1, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        result2, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        assert result1.model_dump() == result2.model_dump()

    def test_baseline_factory_never_mutated(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        factory = _at_demand(electronics_factory, 1200.0)
        _full_pipeline(factory, "We need 1500 units per day, but do not modify Screwdriving.")
        assert electronics_factory.model_dump() == before


# 8. Required demonstrations A-E

class TestDemonstrationA_Baseline1200:
    def test_screwdriving_proposal_with_bottleneck_evidence(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.")
        proposal = next(p for p in result.proposals if p.proposal_id == "proposal-cand-add-parallel-m-screwdriving")
        assert proposal.scenario.actions[0].action_type == "ADD_PARALLEL_MACHINE"
        assert proposal.scenario.actions[0].machine_id == "m-screwdriving"


class TestDemonstrationB_ForbiddenScrewdriving:
    def test_no_screwdriving_proposal(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, requirements, _ = _full_pipeline(factory, "We need 1500 units per day, but do not modify Screwdriving.")
        assert requirements.forbidden_machine_ids == ["m-screwdriving"]
        for p in result.proposals:
            assert "screwdriving" not in p.proposal_id.lower() or "user-requested" in p.proposal_id


class TestDemonstrationC_LowDemand:
    def test_no_unnecessary_expansion_proposal(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 800.0)
        result, _, _ = _full_pipeline(factory, "We need 800 units per day.")
        assert result.proposals == []


class TestDemonstrationD_BudgetControl:
    def test_known_85k_proposal_absent(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "We need 1500 units per day.", goal_overrides={"max_capex": 80000.0})
        for p in result.proposals:
            for r in p.risks:
                assert "85,000" not in r  # no proposal carries the known-85k action at all
            for action in p.scenario.actions:
                if action.action_type == "ADD_PARALLEL_MACHINE":
                    assert action.machine_id != "m-screwdriving"


class TestDemonstrationE_UserRequestedPackaging:
    def test_represented_without_improvement_claim(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        result, _, _ = _full_pipeline(factory, "Add a second Packaging machine.")
        proposal = next(p for p in result.proposals if "packaging" in p.proposal_id.lower())
        text = json.dumps(proposal.model_dump(mode="json")).lower()
        # Note: "not verified" legitimately appears as an honest disclaimer
        # ("Actual impact is not verified until simulated and evaluated.")
        # — check for POSITIVE improvement claims specifically, not the
        # word "verified" in isolation (which would false-positive on the
        # very disclaimer this test wants to confirm IS present).
        for claim_phrase in ("guaranteed", "is verified", "will improve", "will increase throughput", "this improves"):
            assert claim_phrase not in text
        assert "not verified" in text  # the honest disclaimer IS present
