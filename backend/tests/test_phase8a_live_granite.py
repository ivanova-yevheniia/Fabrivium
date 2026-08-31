"""Phase 8A REAL-provider test — can Granite actually reach for the new levers?"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.llm import RetryPolicy, load_dotenv_file
from app.models.conversation import TurnStatus
from app.models.factory import Factory
from app.models.scenario import SUPPORTED_ACTION_TYPES
from app.services.conversation_orchestrator import ConversationOrchestrator

load_dotenv_file()

_ENABLED = os.environ.get("FACTORYMIND_RUN_WATSONX_INTEGRATION_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason=(
        "Live IBM watsonx.ai tests are opt-in: they make real, billable API calls. "
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
def lever_conversation(electronics_factory, live_provider) -> dict:
    """One live conversation exercising both Phase 8A phrasings, run once."""
    orchestrator = ConversationOrchestrator()
    session = orchestrator.start(electronics_factory, PRODUCT_ID)

    results = []
    for message in (
        "We need 1900 units/day.",
        "Can we reach 1900/day without buying another machine? Try an extra shift.",
        "Try adding two operators instead.",
    ):
        result = orchestrator.run_turn(session, message, live_provider)
        session = result.session
        results.append(result)
        requirements = result.turn.requirements_after
        print(
            f"\n[live 8A turn {result.turn.turn_index}] {message}"
            f"\n   status={result.turn.status.value}"
            f"\n   allowed_action_types={requirements.allowed_action_types if requirements else None}"
            f"\n   max_additional_operators={requirements.max_additional_operators if requirements else None}"
            f"\n   changes={result.turn.changes}"
            f"\n   tokens={result.turn.provenance.total_tokens}"
        )
        if result.session.active_branch is not None:
            branch = result.session.active_branch
            print(
                f"   branch={branch.label} goal={branch.metrics.goal_reached} "
                f"capex={branch.metrics.cumulative_known_capex:,.0f} "
                f"done={branch.metrics.completed_units} "
                f"added={branch.metrics.added_machine_ids}"
            )
    return {"session": session, "results": results}


class TestLiveLeverInterpretation:
    def test_every_turn_resolves_without_corrupting_the_session(self, lever_conversation):
        for result in lever_conversation["results"]:
            assert result.turn.status in (
                TurnStatus.APPLIED, TurnStatus.NO_CHANGE,
                TurnStatus.CLARIFICATION_REQUIRED, TurnStatus.REJECTED,
                TurnStatus.PROVIDER_UNAVAILABLE,
            )

    def test_granite_never_invents_an_unsupported_action_type(self, lever_conversation):
        """The one hard requirement (Phase 8A section 21)."""
        for result in lever_conversation["results"]:
            requirements = result.turn.requirements_after
            if requirements is None or requirements.allowed_action_types is None:
                continue
            unknown = set(requirements.allowed_action_types) - SUPPORTED_ACTION_TYPES
            assert not unknown, f"turn {result.turn.turn_index} invented action type(s): {sorted(unknown)}"

    def test_the_target_survives_both_lever_follow_ups(self, lever_conversation):
        """Phase 7C's PATCH guarantee still holds when the follow-up is about
        shifts or staff rather than budget."""
        for result in lever_conversation["results"][1:]:
            requirements = result.turn.requirements_after
            if requirements is not None and result.turn.status is TurnStatus.APPLIED:
                assert requirements.target_units_per_day == pytest.approx(1900.0)

    def test_no_branch_ever_touches_a_machine_the_user_excluded(self, lever_conversation):
        """If a turn restricted planning away from equipment, the resulting
        branch must contain no machine purchase — enforced deterministically,
        not by trusting the model."""
        for result in lever_conversation["results"]:
            requirements = result.turn.requirements_after
            branch = result.session.branch(result.turn.branch_id)
            if branch is None or requirements is None or requirements.allowed_action_types is None:
                continue
            if "ADD_PARALLEL_MACHINE" not in requirements.allowed_action_types:
                for machine_id in branch.metrics.added_machine_ids:
                    original = {m.id for m in result.session.baseline_factory.machines}
                    assert machine_id in original, f"a new machine {machine_id} was added despite being excluded"

    def test_the_report_records_what_granite_actually_did(self, lever_conversation):
        """Not an assertion about a desired answer — a printed record of the
        real interpretation, for the Phase 8A report."""
        session = lever_conversation["session"]
        print("\n[live 8A summary]")
        for branch in session.branches:
            print(
                f"   {branch.label}: goal={branch.metrics.goal_reached} "
                f"capex={branch.metrics.cumulative_known_capex:,.0f} "
                f"completed={branch.metrics.completed_units} "
                f"allowed={branch.active_requirements.allowed_action_types}"
            )
        assert session.turns
