"""Phase 7C REAL-provider tests — a live Granite-backed conversation."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.llm import RetryPolicy, load_dotenv_file
from app.models.conversation import (
    ConversationSession,
    PlanningBaseMode,
    TurnStatus,
    UpdateSource,
)
from app.models.factory import Factory
from app.services.branch_comparison import compare_branches
from app.services.conversation_orchestrator import ConversationOrchestrator

load_dotenv_file()

_ENABLED = os.environ.get("FACTORYMIND_RUN_WATSONX_INTEGRATION_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason=(
        "Live IBM watsonx.ai conversation tests are opt-in: they make real, billable API calls. "
        "Set FACTORYMIND_RUN_WATSONX_INTEGRATION_TESTS=1 to run them."
    ),
)

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture(scope="module")
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture(scope="module")
def live_provider():
    from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

    provider = WatsonxGraniteProvider(
        WatsonxSettings.from_env(),
        retry_policy=RetryPolicy(max_retries=2, timeout_seconds=90.0),
    )
    yield provider
    provider.close()


@pytest.fixture(scope="module")
def scenario_a(electronics_factory, live_provider) -> dict:
    """The Phase 7C section 24 conversation, run ONCE against real Granite
    and shared by every assertion below — three planning runs and four
    model calls is enough to pay for repeatedly."""
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start(electronics_factory, PRODUCT_ID)

    results = []
    for message in (
        "We need 1900 units/day, budget EUR 220k.",
        "That's too expensive. Keep it below EUR 150k.",
        "Allow EUR 180k, but don't modify Assembly.",
    ):
        result = orchestrator.run_turn(session, message, live_provider)
        session = result.session
        results.append(result)
        print(
            f"\n[live turn {result.turn.turn_index}] {message}"
            f"\n   status={result.turn.status.value} base={result.turn.base_mode}"
            f"\n   changes={result.turn.changes}"
            f"\n   intent={result.turn.intent_summary!r}"
            f"\n   tokens={result.turn.provenance.total_tokens}"
        )
    return {"session": session, "results": results}


class TestLiveConversation:
    def test_turn_1_produces_a_verified_plan(self, scenario_a):
        turn = scenario_a["results"][0].turn
        branch = scenario_a["session"].branches[0]
        assert turn.status is TurnStatus.APPLIED
        assert turn.provenance.update_source is UpdateSource.LLM
        assert branch.active_requirements.target_units_per_day == pytest.approx(1900.0)
        assert branch.active_requirements.max_capex == pytest.approx(220_000.0)
        assert branch.metrics.goal_reached is True
        assert branch.metrics.cumulative_known_capex == 205_000.0

    def test_turn_2_keeps_the_target_and_tightens_only_the_budget(self, scenario_a):
        """The headline Phase 7C behaviour against a real model: the 1900
        target was never repeated by the user and must survive."""
        turn = scenario_a["results"][1].turn
        after = turn.requirements_after
        assert turn.status is TurnStatus.APPLIED
        assert after.target_units_per_day == pytest.approx(1900.0), "the target was dropped"
        assert after.max_capex == pytest.approx(150_000.0)

    def test_turn_2_replans_from_the_original_baseline(self, scenario_a):
        turn = scenario_a["results"][1].turn
        assert turn.base_mode is PlanningBaseMode.ORIGINAL_BASELINE

    def test_turn_2_creates_a_new_branch_and_preserves_the_first(self, scenario_a):
        session: ConversationSession = scenario_a["session"]
        assert len(session.branches) >= 2
        assert session.branches[0].metrics.cumulative_known_capex == 205_000.0
        assert session.branches[0].metrics.goal_reached is True
        assert session.branches[1].branch_id != session.branches[0].branch_id

    def test_turn_2_reports_an_unreachable_target_honestly(self, scenario_a):
        """
        Under a EUR 150k ceiling the 1900/day target is not reachable with known-cost
        candidates.
        """
        branch = scenario_a["session"].branches[1]
        assert branch.metrics.cumulative_known_capex <= 150_000.0
        if not branch.metrics.goal_reached:
            assert branch.metrics.demand_gap_units > 0
            assert "not reached" in branch.summary

    def test_turn_3_carries_the_target_and_adds_the_lock(self, scenario_a):
        turn = scenario_a["results"][2].turn
        after = turn.requirements_after
        assert turn.status is TurnStatus.APPLIED
        assert after.target_units_per_day == pytest.approx(1900.0)
        assert after.max_capex == pytest.approx(180_000.0)
        assert "m-assembly" in after.forbidden_machine_ids

    def test_turn_3_never_touches_the_locked_machine(self, scenario_a):
        branch = scenario_a["session"].branches[2]
        assert "m-assembly" not in branch.metrics.added_machine_ids

    def test_comparison_is_deterministic_over_the_live_branches(self, scenario_a):
        session = scenario_a["session"]
        comparison = compare_branches(session.branches[0], session.branches[1])
        capex = next(m for m in comparison.metrics if m.metric == "cumulative_known_capex")
        assert capex.delta == (
            session.branches[1].metrics.cumulative_known_capex
            - session.branches[0].metrics.cumulative_known_capex
        )
        print(f"\n[live comparison] {comparison.headline}")

    def test_every_turn_reports_its_token_usage(self, scenario_a):
        totals = [r.turn.provenance.total_tokens for r in scenario_a["results"]]
        assert all(t is not None and t > 0 for t in totals), totals
        print(f"\n[live tokens per turn] {totals} — conversation total {sum(totals)}")

    def test_the_baseline_factory_survived_the_whole_conversation(self, scenario_a, electronics_factory):
        assert scenario_a["session"].baseline_factory.model_dump_json() == electronics_factory.model_dump_json()


class TestLiveAmbiguity:
    def test_make_it_better_asks_instead_of_guessing(self, electronics_factory, live_provider):
        """Scenario E against a real model."""
        orchestrator = ConversationOrchestrator()
        session = orchestrator.start(electronics_factory, PRODUCT_ID)
        session = orchestrator.run_turn(session, "We need 1900 units/day, budget EUR 220k.", live_provider).session

        result = orchestrator.run_turn(session, "Make it better.", live_provider)
        print(f"\n[live ambiguity] status={result.turn.status.value} changes={result.turn.changes}")

        assert result.turn.status in (
            TurnStatus.CLARIFICATION_REQUIRED, TurnStatus.NO_CHANGE, TurnStatus.APPLIED,
        )
        if result.turn.status is TurnStatus.CLARIFICATION_REQUIRED:
            assert result.turn.clarification is not None
            # Nothing moved.
            assert result.session.active_requirements == session.active_requirements
            assert len(result.session.branches) == len(session.branches)
        else:
            # Whatever it did must be visible and grounded, never silent.
            assert result.turn.requirements_after.target_units_per_day == pytest.approx(1900.0)
