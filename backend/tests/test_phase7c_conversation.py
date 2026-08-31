"""Phase 7C tests — conversational engineering copilot."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.llm.errors import LLMTimeoutError, LLMUnavailableError
from app.llm.mock_provider import MockLLMProvider, MockOutcome
from app.models.agent import PlanningRequirements
from app.models.conversation import (
    ConversationSession,
    ConversationStatus,
    PlanningBaseMode,
    RequirementUpdate,
    TurnStatus,
    UpdateSource,
)
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.branch_comparison import compare_branches
from app.services.conversation_context import build_conversation_context
from app.services.conversation_orchestrator import ConversationOrchestrator, resolve_base_mode
from app.services.requirement_update import apply_requirement_update, resolve_machine_reference
from app.services.requirements_parser import USER_REQUEST_NOTE_PREFIX

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture(scope="module")
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def base_requirements() -> PlanningRequirements:
    """The state after "We need 1900 units/day, budget €220k, don't modify
    Packaging" — the situation every follow-up test starts from."""
    return PlanningRequirements(
        objective=OptimizationObjective.MEET_DEMAND,
        target_units_per_day=1900.0,
        max_capex=220_000.0,
        forbidden_machine_ids=["m-packaging"],
    )


def update_provider(*updates: dict) -> MockLLMProvider:
    """A provider that answers the UPDATE call with each scripted payload in turn."""
    return MockLLMProvider(outcomes=[MockOutcome.ok(u) for u in updates])


def run_conversation(factory: Factory, *messages: str, provider=None) -> ConversationSession:
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start(factory, PRODUCT_ID)
    for message in messages:
        session = orchestrator.run_turn(session, message, provider).session
    return session




class TestUpdateSemantics:
    def test_1_unspecified_fields_are_preserved(self, electronics_factory, base_requirements):
        """The defining behaviour of Phase 7C: a follow-up that mentions
        only the budget must not silently drop the target or the lock the
        user set two turns ago."""
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(max_capex=150_000.0), electronics_factory,
        )
        after = result.requirements
        assert after.max_capex == 150_000.0
        assert after.target_units_per_day == 1900.0
        assert after.forbidden_machine_ids == ["m-packaging"]
        assert after.objective is OptimizationObjective.MEET_DEMAND

    def test_2_capex_update(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(max_capex=150_000.0), electronics_factory,
        )
        assert result.changes == ["Max CAPEX: EUR 220,000 -> EUR 150,000"]

    def test_3_target_update(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(target_units_per_day=2200.0), electronics_factory,
        )
        assert result.requirements.target_units_per_day == 2200.0
        assert result.requirements.max_capex == 220_000.0

    def test_4_objective_update_preserves_hard_constraints(self, electronics_factory, base_requirements):
        """Scenario C: 'actually throughput matters more' changes what to
        optimise for without releasing any constraint."""
        result = apply_requirement_update(
            base_requirements,
            RequirementUpdate(objective=OptimizationObjective.MAXIMIZE_THROUGHPUT),
            electronics_factory,
        )
        after = result.requirements
        assert after.objective is OptimizationObjective.MAXIMIZE_THROUGHPUT
        assert after.max_capex == 220_000.0
        assert after.forbidden_machine_ids == ["m-packaging"]

    def test_5_forbidden_machine_add_by_name(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(forbidden_machine_ids_add=["Assembly"]), electronics_factory,
        )
        assert set(result.requirements.forbidden_machine_ids) == {"m-packaging", "m-assembly"}

    def test_5b_forbidden_machine_add_is_deduplicated(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements,
            RequirementUpdate(forbidden_machine_ids_add=["Packaging", "m-packaging"]),
            electronics_factory,
        )
        assert result.requirements.forbidden_machine_ids == ["m-packaging"]

    def test_6_forbidden_machine_remove(self, electronics_factory, base_requirements):
        """Scenario D: 'Packaging is allowed again.'"""
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(forbidden_machine_ids_remove=["Packaging"]), electronics_factory,
        )
        assert result.requirements.forbidden_machine_ids == []
        assert result.changes == ["Unlocked: m-packaging may be modified again"]

    def test_6b_removing_something_not_locked_warns_and_changes_nothing(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(forbidden_machine_ids_remove=["Assembly"]), electronics_factory,
        )
        assert result.requirements.forbidden_machine_ids == ["m-packaging"]
        assert any("was not locked" in w for w in result.warnings)

    def test_7_preserve_layout_update_both_ways(self, electronics_factory, base_requirements):
        on = apply_requirement_update(
            base_requirements, RequirementUpdate(preserve_existing_layout=True), electronics_factory,
        ).requirements
        assert on.preserve_existing_layout is True
        off = apply_requirement_update(
            on, RequirementUpdate(preserve_existing_layout=False), electronics_factory,
        ).requirements
        assert off.preserve_existing_layout is False

    def test_8_reset_constraint_clears_it(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(reset_constraints=["max_capex"]), electronics_factory,
        )
        assert result.requirements.max_capex is None
        assert result.requirements.target_units_per_day == 1900.0

    def test_8b_an_explicit_value_beats_a_reset_of_the_same_field(self, electronics_factory, base_requirements):
        """'Drop the budget cap and use €180k instead' must end at 180k,
        not unlimited."""
        result = apply_requirement_update(
            base_requirements,
            RequirementUpdate(reset_constraints=["max_capex"], max_capex=180_000.0),
            electronics_factory,
        )
        assert result.requirements.max_capex == 180_000.0

    def test_8c_an_unknown_reset_name_is_ignored_with_a_warning(self, electronics_factory, base_requirements):
        """``reset_constraints`` comes from a language model; an
        unrecognised name must never be reflected onto an attribute."""
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(reset_constraints=["baseline_factory"]), electronics_factory,
        )
        assert result.requirements == base_requirements
        assert any("unknown constraint" in w for w in result.warnings)

    def test_9_contradiction_is_detected_and_reported_not_resolved(self, electronics_factory, base_requirements):
        result = apply_requirement_update(
            base_requirements,
            RequirementUpdate(max_additional_machines=0, allowed_action_types=["ADD_PARALLEL_MACHINE"]),
            electronics_factory,
        )
        assert any("Contradiction" in w for w in result.warnings)
        # Reported, not silently fixed: the constraints stay exactly as asked.
        assert result.requirements.max_additional_machines == 0
        assert result.requirements.allowed_action_types == ["ADD_PARALLEL_MACHINE"]

    def test_10_the_original_requirements_object_is_never_mutated(self, electronics_factory, base_requirements):
        snapshot = base_requirements.model_dump_json()
        apply_requirement_update(
            base_requirements,
            RequirementUpdate(max_capex=1.0, forbidden_machine_ids_add=["Assembly"], reset_constraints=["target_units_per_day"]),
            electronics_factory,
        )
        assert base_requirements.model_dump_json() == snapshot

    def test_10b_an_empty_update_changes_nothing(self, electronics_factory, base_requirements):
        result = apply_requirement_update(base_requirements, RequirementUpdate(), electronics_factory)
        assert result.requirements is base_requirements
        assert result.changes == []

    def test_10c_explicit_intervention_uses_the_existing_user_request_channel(self, electronics_factory, base_requirements):
        """Reuses Phase 5B's note mechanism rather than inventing a new
        field, so the planning agent already treats it as grounded."""
        result = apply_requirement_update(
            base_requirements, RequirementUpdate(explicit_intervention="Packaging"), electronics_factory,
        )
        assert any(
            note.startswith(USER_REQUEST_NOTE_PREFIX) and "m-packaging" in note
            for note in result.requirements.notes
        )

    def test_10d_machine_references_resolve_by_id_name_and_substring(self, electronics_factory):
        assert resolve_machine_reference(electronics_factory, "m-packaging") == ["m-packaging"]
        assert resolve_machine_reference(electronics_factory, "Packaging") == ["m-packaging"]
        assert resolve_machine_reference(electronics_factory, "packag") == ["m-packaging"]
        assert resolve_machine_reference(electronics_factory, "teleporter") == []


# CONVERSATION (11-20)


class TestConversation:
    def test_11_turns_chain_and_are_recorded_in_order(self, electronics_factory):
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k.",
            "Keep it below 150k.",
        )
        assert [t.turn_index for t in session.turns] == [0, 1]
        assert all(t.status is TurnStatus.APPLIED for t in session.turns)

    def test_12_active_requirements_are_carried_forward_across_turns(self, electronics_factory):
        """Scenario A end to end: the target set in turn 1 survives turns
        2 and 3 without ever being repeated by the user."""
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k.",
            "Keep it below 150k.",
            "Allow 180k, but don't modify Assembly.",
        )
        active = session.active_requirements
        assert active.target_units_per_day == 1900.0
        assert active.max_capex == 180_000.0
        assert "m-assembly" in active.forbidden_machine_ids

    def test_13_each_applied_turn_creates_a_new_branch(self, electronics_factory):
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k.",
            "Keep it below 150k.",
        )
        assert [b.label for b in session.branches] == ["Plan A", "Plan B"]
        assert session.branches[1].parent_branch_id == session.branches[0].branch_id
        assert session.active_branch_id == session.branches[1].branch_id

    def test_14_a_previous_branch_is_never_modified_by_a_later_turn(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        plan_a_snapshot = session.branches[0].model_dump_json()

        session = orchestrator.run_turn(session, "Keep it below 150k.", None).session
        session = orchestrator.run_turn(session, "Allow 180k.", None).session

        assert session.branches[0].model_dump_json() == plan_a_snapshot
        # PHASE 8A: under a HARD EUR 220k ceiling this branch now commits
        # EUR 85,000 and stops short, because the step that would unlock the
        # selectable against a hard budget (the pre-existing Phase 4
        # REQUIRES_INFORMATION rule). The property under test is unchanged:
        # whatever Plan A was, later turns must never alter it.
        assert session.branches[0].metrics.cumulative_known_capex == 85_000.0
        assert session.branches[0].metrics.goal_reached is False

    def test_14b_run_turn_never_mutates_the_session_it_was_given(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        before = session.model_dump_json()

        orchestrator.run_turn(session, "Keep it below 150k.", None)

        assert session.model_dump_json() == before

    def test_15_the_active_branch_advances_to_the_newest_plan(self, electronics_factory):
        session = run_conversation(
            electronics_factory, "We need 1900 units/day, budget 220k.", "Keep it below 150k.",
        )
        assert session.active_branch.label == "Plan B"
        assert session.active_branch.metrics.max_capex == 150_000.0

    def test_16_a_constraint_refinement_replans_from_the_original_baseline(self, electronics_factory):
        """Scenario A turn 2: tightening the budget below what is already
        committed can only mean 'find a different plan'."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        result = orchestrator.run_turn(session, "Keep it below 150k.", None)

        assert result.turn.base_mode is PlanningBaseMode.ORIGINAL_BASELINE
        # And the new branch really did start from scratch, not from the
        # 205k plan: its spend is lower, not higher.
        assert result.session.active_branch.metrics.cumulative_known_capex < 205_000.0

    def test_17_an_incremental_request_continues_from_the_current_verified_state(self, electronics_factory):
        """Scenario B: 'now increase it further' builds on what was already
        accepted, and the spend already committed is carried forward rather
        than restarting at zero."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day.", None).session
        committed = session.active_branch.metrics.cumulative_known_capex
        assert committed > 0

        provider = update_provider({
            "target_units_per_day": 2200.0,
            "base_mode": "CURRENT_VERIFIED_STATE",
            "intent_summary": "Raise the target further.",
        })
        result = orchestrator.run_turn(session, "Now increase it further to 2200/day.", provider)

        assert result.turn.base_mode is PlanningBaseMode.CURRENT_VERIFIED_STATE
        assert result.session.active_requirements.target_units_per_day == 2200.0
        # Carried spend: the continuation's total includes what Plan A cost.
        assert result.session.active_branch.metrics.cumulative_known_capex >= committed

    def test_17b_a_continuation_is_overridden_when_the_new_budget_is_already_exceeded(self, electronics_factory):
        """
        A model hint of CURRENT_VERIFIED_STATE must be overruled when continuing is
        arithmetically impossible — you cannot un-spend.
        """
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        assert session.active_branch.metrics.cumulative_known_capex > 50_000.0

        provider = update_provider({"max_capex": 50_000.0, "base_mode": "CURRENT_VERIFIED_STATE"})
        result = orchestrator.run_turn(session, "Keep it below 50k.", provider)

        assert result.turn.base_mode is PlanningBaseMode.ORIGINAL_BASELINE
        assert any("cannot be undone" in w for w in result.turn.warnings)

    def test_17c_a_continuation_is_overridden_when_it_would_lock_an_already_modified_machine(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day.", None).session
        modified = session.active_branch.metrics.added_machine_ids
        assert modified

        provider = update_provider({
            "forbidden_machine_ids_add": [modified[0]], "base_mode": "CURRENT_VERIFIED_STATE",
        })
        result = orchestrator.run_turn(session, f"Don't modify {modified[0]}.", provider)

        assert result.turn.base_mode is PlanningBaseMode.ORIGINAL_BASELINE
        assert any("already modified" in w for w in result.turn.warnings)

    def test_18_an_ambiguous_request_asks_instead_of_guessing(self, electronics_factory):
        """Scenario E: 'make it better' has no unique engineering meaning."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session

        provider = update_provider({
            "clarification_required": True,
            "clarification": {
                "question": "Should I optimise for lower CAPEX, higher throughput, lower WIP, or shorter flow time?",
                "ambiguous_fields": ["objective"],
                "safe_options": ["Lower CAPEX", "Higher throughput", "Lower WIP", "Shorter flow time"],
            },
        })
        result = orchestrator.run_turn(session, "Make it better.", provider)

        assert result.turn.status is TurnStatus.CLARIFICATION_REQUIRED
        assert result.turn.clarification is not None
        assert result.turn.clarification.safe_options
        assert result.session.status is ConversationStatus.AWAITING_CLARIFICATION

    def test_19_a_clarification_mutates_no_engineering_state(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        requirements_before = session.active_requirements
        branches_before = [b.branch_id for b in session.branches]

        provider = update_provider({"clarification_required": True, "clarification": {"question": "What exactly?"}})
        result = orchestrator.run_turn(session, "Make it better.", provider)

        assert result.session.active_requirements == requirements_before
        assert [b.branch_id for b in result.session.branches] == branches_before
        assert result.session.active_branch_id == session.active_branch_id
        assert result.planning_session is None
        assert result.turn.branch_id is None

    def test_20_an_invalid_update_is_rejected_without_changing_state(self, electronics_factory):
        """Structurally valid JSON that fails RequirementUpdate validation
        (negative CAPEX) must not become a half-applied edit."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        before = session.active_requirements

        provider = update_provider({"max_capex": -5000.0})
        result = orchestrator.run_turn(session, "Set the budget to minus five thousand.", provider)

        assert result.turn.status is TurnStatus.PROVIDER_UNAVAILABLE
        assert result.session.active_requirements == before
        assert len(result.session.branches) == len(session.branches)

    def test_20b_a_no_op_update_does_not_create_a_branch(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session

        provider = update_provider({"max_capex": 220_000.0, "intent_summary": "Keep the budget where it is."})
        result = orchestrator.run_turn(session, "Keep the budget at 220k.", provider)

        assert result.turn.status is TurnStatus.NO_CHANGE
        assert len(result.session.branches) == 1
        assert result.planning_session is None

    def test_20c_conversation_context_stays_bounded(self, electronics_factory):
        """Prompt size must not grow with conversation length (Phase 7C
        sections 6 and 21)."""
        orchestrator = ConversationOrchestrator(max_context_turns=3)
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        for capex in (200_000, 190_000, 180_000, 170_000, 160_000):
            session = orchestrator.run_turn(session, f"Keep it below {capex // 1000}k.", None).session

        assert len(session.turns) == 6
        context = build_conversation_context(session, max_turns=3)
        assert len(context.recent_turns) == 3
        assert context.recent_turns[-1].turn == 5
        # The raw factory never travels in the prompt — only machine refs.
        assert "purchase_cost" not in context.model_dump_json()


# GROUNDING (21-25)


class TestGrounding:
    def test_21_a_fabricated_machine_id_is_rejected_and_nothing_changes(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session
        before = session.active_requirements

        provider = update_provider({"forbidden_machine_ids_add": ["m-teleporter"]})
        result = orchestrator.run_turn(session, "Don't modify the teleporter.", provider)

        assert result.turn.status is TurnStatus.REJECTED
        assert any("no such machine" in e for e in result.turn.errors)
        assert result.session.active_requirements == before
        assert len(result.session.branches) == 1

    def test_22_a_forbidden_machine_is_never_touched_by_any_branch(self, electronics_factory):
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k, don't modify Packaging.",
            "Allow 180k.",
        )
        for branch in session.branches:
            assert "m-packaging" not in branch.metrics.added_machine_ids

    def test_23_the_capex_ceiling_cannot_be_bypassed_by_a_conversation(self, electronics_factory):
        session = run_conversation(
            electronics_factory, "We need 1900 units/day, budget 220k.", "Keep it below 150k.",
        )
        cheap_branch = session.branches[1]
        assert cheap_branch.metrics.max_capex == 150_000.0
        assert cheap_branch.metrics.cumulative_known_capex <= 150_000.0

    def test_23b_an_unreachable_target_is_reported_honestly_not_faked(self, electronics_factory):
        session = run_conversation(
            electronics_factory, "We need 1900 units/day, budget 220k.", "Keep it below 150k.",
        )
        cheap_branch = session.branches[1]
        assert cheap_branch.metrics.goal_reached is False
        assert cheap_branch.metrics.demand_gap_units > 0
        assert "not reached" in cheap_branch.summary

    def test_24_optimizer_grounding_is_still_enforced_inside_a_conversation(self, electronics_factory):
        """A fabricated proposal must be rejected by the unchanged Phase 5B
        validator even when it arrives via a conversational turn."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)

        provider = MockLLMProvider(outcomes=[
            MockOutcome.ok({"target_units_per_day": 1900.0, "max_capex": 220_000.0}),
            MockOutcome.ok([{
                "proposal_id": "fabricated",
                "hypothesis": {"problem_summary": "x", "suspected_issue_type": "UNKNOWN", "evidence": []},
                "scenario": {"id": "s", "name": "n", "description": "", "actions": [
                    {"action_type": "ADD_PARALLEL_MACHINE", "machine_id": "m-does-not-exist"}]},
                "expected_effects": [], "risks": [], "confidence": 0.99, "source": "LLM",
            }]),
        ])
        result = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", provider)

        assert result.planning_session is not None
        reasons = [
            reason
            for iteration in result.planning_session.iterations
            for rejection in iteration.planning_agent_result.rejected_proposals
            for reason in rejection.reasons
        ]
        assert any("unknown machine_id" in r for r in reasons)
        assert "m-does-not-exist" not in json.dumps(result.session.active_branch.metrics.added_machine_ids)

    def test_25_the_baseline_factory_is_never_mutated_by_any_turn(self, electronics_factory):
        original = electronics_factory.model_dump_json()
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k.",
            "Keep it below 150k.",
            "Allow 180k, but don't modify Assembly.",
        )
        assert electronics_factory.model_dump_json() == original
        assert session.baseline_factory.model_dump_json() == original

    def test_25b_every_branch_records_the_exact_requirements_it_was_planned_under(self, electronics_factory):
        session = run_conversation(
            electronics_factory, "We need 1900 units/day, budget 220k.", "Keep it below 150k.",
        )
        assert session.branches[0].active_requirements.max_capex == 220_000.0
        assert session.branches[1].active_requirements.max_capex == 150_000.0


# COMPARISON (26-29)


class TestComparison:
    @pytest.fixture
    def two_branch_session(self, electronics_factory) -> ConversationSession:
        return run_conversation(
            electronics_factory, "We need 1900 units/day, budget 220k.", "Keep it below 150k.",
        )

    def test_26_comparison_reports_both_branches_exactly(self, two_branch_session):
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        assert comparison.branch_a_id == a.branch_id
        assert comparison.branch_b_id == b.branch_id
        assert comparison.label_a == "Plan A"
        assert comparison.label_b == "Plan B"

    def test_27_capex_comparison_is_exact_arithmetic(self, two_branch_session):
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        capex = next(m for m in comparison.metrics if m.metric == "cumulative_known_capex")
        assert capex.value_a == a.metrics.cumulative_known_capex
        assert capex.value_b == b.metrics.cumulative_known_capex
        assert capex.delta == b.metrics.cumulative_known_capex - a.metrics.cumulative_known_capex

    def test_28_every_kpi_delta_matches_the_verified_metrics(self, two_branch_session):
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        for metric in comparison.metrics:
            if metric.delta is None:
                continue
            expected = float(getattr(b.metrics, metric.metric)) - float(getattr(a.metrics, metric.metric))
            assert metric.delta == pytest.approx(expected), metric.metric

    def test_29_comparison_involves_no_llm_at_all(self, two_branch_session, monkeypatch):
        """Not a config assertion: block every socket and compare anyway."""
        import socket

        def _blocked(*args, **kwargs):
            raise AssertionError("Comparison must be pure arithmetic — no network.")

        monkeypatch.setattr(socket.socket, "connect", _blocked)
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        assert comparison.headline
        assert comparison.metrics

    def test_29b_the_headline_leads_with_whether_the_target_was_reached(self, two_branch_session):
        """
        PHASE 8A: both branches in this fixture now fall short, so the headline
        correctly says so instead of contrasting a winner with a loser.
        """
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        assert comparison.headline.startswith("Neither option reaches the target")

    def test_29b2_the_headline_names_the_winner_when_one_reaches_the_target(
        self, two_branch_session,
    ):
        """The other half of the rule, on a deliberately contrasting pair:
        when exactly one option reaches the target, the headline must lead
        with that — never with which one was cheaper."""
        a, b = two_branch_session.branches
        reached = a.model_copy(
            update={"metrics": a.metrics.model_copy(update={"goal_reached": True, "demand_met": True})}
        )
        comparison = compare_branches(reached, b)
        assert comparison.headline.startswith(f"{reached.label} reaches the target")
        assert f"{b.label} does not" in comparison.headline

    def test_29c_constraint_differences_are_reported_separately_from_outcomes(self, two_branch_session):
        a, b = two_branch_session.branches
        comparison = compare_branches(a, b)
        assert any("Budget" in d for d in comparison.constraint_differences)

    def test_29d_an_unknown_never_becomes_a_zero(self, electronics_factory):
        """Comparing a budgeted branch with an unbudgeted one must say the
        remaining CAPEX is not comparable, not report a delta of 0."""
        session = run_conversation(
            electronics_factory, "We need 1900 units/day.", "Keep it below 150k.",
        )
        a, b = session.branches
        comparison = compare_branches(a, b)
        assert a.metrics.remaining_known_capex is None
        assert not any(m.metric == "remaining_known_capex" for m in comparison.metrics)
        assert any("not comparable" in u for u in comparison.unknown_information)


# FALLBACK (30-33)


class TestFallback:
    def _seeded(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        return orchestrator, orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None).session

    def test_30_a_provider_timeout_does_not_corrupt_the_session(self, electronics_factory):
        """A context-sensitive follow-up plus a dead provider must leave
        every constraint exactly as it was."""
        orchestrator, session = self._seeded(electronics_factory)
        before = session.model_dump_json()

        provider = MockLLMProvider(outcomes=[MockOutcome.timeout()])
        result = orchestrator.run_turn(session, "Make it cheaper.", provider)

        assert result.turn.status is TurnStatus.PROVIDER_UNAVAILABLE
        assert result.session.active_requirements == session.active_requirements
        assert len(result.session.branches) == 1
        assert result.turn.errors
        # The submitted session itself is untouched.
        assert session.model_dump_json() == before

    def test_30b_a_provider_outage_never_silently_applies_a_replacement_parse(self, electronics_factory):
        """
        The dangerous failure mode: reusing the Phase 5A REPLACEMENT parser on a follow-
        up would drop the target and the locks.
        """
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(
            session, "We need 1900 units/day, budget 220k, don't modify Packaging.", None,
        ).session
        assert session.active_requirements.target_units_per_day == 1900.0

        provider = MockLLMProvider(outcomes=[MockOutcome.failure(LLMUnavailableError("down"))])
        result = orchestrator.run_turn(session, "Keep it below 150k.", provider)

        after = result.session.active_requirements
        assert after.target_units_per_day == 1900.0
        assert after.forbidden_machine_ids == ["m-packaging"]
        assert after.max_capex == 150_000.0
        assert result.turn.provenance.update_source is UpdateSource.DETERMINISTIC

    def test_31_a_malformed_response_does_not_corrupt_the_session(self, electronics_factory):
        orchestrator, session = self._seeded(electronics_factory)
        provider = MockLLMProvider(outcomes=[MockOutcome.malformed("definitely not json {")])
        result = orchestrator.run_turn(session, "Make it cheaper somehow.", provider)

        assert result.turn.status is TurnStatus.PROVIDER_UNAVAILABLE
        assert result.session.active_requirements == session.active_requirements

    def test_31b_an_update_of_the_wrong_shape_is_refused(self, electronics_factory):
        orchestrator, session = self._seeded(electronics_factory)
        provider = update_provider({"max_capex": "quite a lot, really"})
        result = orchestrator.run_turn(session, "Spend a bit less.", provider)
        assert result.turn.status is TurnStatus.PROVIDER_UNAVAILABLE
        assert result.session.active_requirements == session.active_requirements

    def test_32_explanation_still_falls_back_deterministically(self, electronics_factory):
        """A hallucinated explanation must be replaced, exactly as in Phase
        7B — conversation changes nothing about that guard."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)

        provider = MockLLMProvider(outcomes=[
            MockOutcome.ok({"target_units_per_day": 1900.0, "max_capex": 220_000.0}),
            MockOutcome.malformed("not proposals"),
            MockOutcome.ok({
                "executive_summary": "We hit 9999 units/day for EUR 3 using machine m-teleporter.",
                "goal_status": "Goal reached.", "recommended_changes": [], "verified_effects": [],
                "tradeoffs": [], "constraints_and_risks": [], "stop_explanation": "Done.", "sections": [],
            }),
        ])
        result = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", provider)

        assert result.turn.explanation is not None
        rendered = result.turn.explanation.model_dump_json()
        assert "m-teleporter" not in rendered
        assert "9999" not in rendered
        assert result.turn.provenance.explanation_source == "DETERMINISTIC"

    def test_33_a_confidently_supported_update_still_works_without_any_provider(self, electronics_factory):
        """The conservative parser handles explicit values, so the copilot
        keeps working end to end with no LLM at all."""
        session = run_conversation(
            electronics_factory,
            "We need 1900 units/day, budget 220k.",
            "Keep it below 150k.",
            "Packaging is allowed again.",
        )
        assert [t.status for t in session.turns] == [TurnStatus.APPLIED, TurnStatus.APPLIED, TurnStatus.NO_CHANGE]
        assert session.active_requirements.max_capex == 150_000.0
        assert all(t.provenance.update_source is UpdateSource.DETERMINISTIC for t in session.turns)

    def test_33b_provenance_reports_each_stage_honestly(self, electronics_factory):
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        result = orchestrator.run_turn(session, "We need 1900 units/day, budget 220k.", None)

        provenance = result.turn.provenance
        assert provenance.update_source is UpdateSource.DETERMINISTIC
        assert provenance.planning_source == "DETERMINISTIC"
        assert provenance.explanation_source == "DETERMINISTIC"
        assert provenance.provider_name is None
        # No provider reported usage, so nothing is invented.
        assert provenance.total_tokens is None
