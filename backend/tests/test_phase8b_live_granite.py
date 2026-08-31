"""Phase 8B REAL-provider test — Granite interprets, the simulator decides."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.llm import RetryPolicy, load_dotenv_file
from app.models.factory import Factory
from app.models.scenario import SUPPORTED_ACTION_TYPES
from app.models.strategy import StrategyQueryIntent
from app.services.agent_context import build_factory_context
from app.services.llm_integration import parse_requirements_with_fallback
from app.services.strategy_arena import StrategyArena
from app.services.strategy_query import answer_strategy_query, detect_intent

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
def live_exploration(electronics_factory, live_provider) -> dict:
    """One live-interpreted exploration, run once — it is expensive twice
    over: real tokens AND a full multi-family strategy search."""
    context = build_factory_context(electronics_factory)
    parse_result, fallback = parse_requirements_with_fallback(
        "Show me options for reaching 1900/day.", context, live_provider,
    )
    requirements = parse_result.parsed_requirements
    arena, sessions = StrategyArena().explore(electronics_factory, PRODUCT_ID, requirements)

    print(
        f"\n[live 8B] interpreted target={requirements.target_units_per_day} "
        f"capex={requirements.max_capex} fallback={fallback}"
    )
    for option in arena.strategies:
        print(
            f"   {option.label} {option.family.value}: {option.metrics.completed_units}/day "
            f"goal={option.metrics.goal_met} capex={option.cost.known_capex:,.0f} "
            f"complete={option.commercially_complete} actions={option.actions.action_count}"
        )
    return {
        "requirements": requirements,
        "arena": arena,
        "sessions": sessions,
        "fallback": fallback,
        "provider": live_provider,
    }


class TestLiveStrategyExploration:
    def test_granite_reads_the_target_out_of_the_sentence(self, live_exploration):
        assert live_exploration["requirements"].target_units_per_day == pytest.approx(1900.0)

    def test_granite_never_invents_an_unsupported_action_type(self, live_exploration):
        """A model may decline to restrict the levers, but naming a lever
        FactoryMind cannot execute would silently block all planning."""
        allowed = live_exploration["requirements"].allowed_action_types
        if allowed is None:
            return
        unknown = set(allowed) - SUPPORTED_ACTION_TYPES
        assert not unknown, f"invented action type(s): {sorted(unknown)}"

    def test_several_verified_options_come_back(self, live_exploration):
        arena = live_exploration["arena"]
        assert arena.strategies
        assert all(o.operationally_verified for o in arena.strategies)

    def test_every_strategy_value_is_deterministic(self, live_exploration, electronics_factory):
        """The heart of section 28."""
        offline_arena, _ = StrategyArena().explore(
            electronics_factory, PRODUCT_ID, live_exploration["requirements"],
        )

        assert [o.strategy_id for o in offline_arena.strategies] == [
            o.strategy_id for o in live_exploration["arena"].strategies
        ]
        for offline, live in zip(offline_arena.strategies, live_exploration["arena"].strategies):
            assert offline.metrics == live.metrics
            assert offline.actions == live.actions
            assert offline.cost == live.cost
        assert offline_arena.baseline_metrics == live_exploration["arena"].baseline_metrics


class TestLiveFollowUps:
    def test_avoid_buying_another_machine(self, live_exploration, live_provider, electronics_factory):
        """"Can we avoid buying another machine?"""
        context = build_factory_context(electronics_factory)
        parse_result, _ = parse_requirements_with_fallback(
            "We need 1900 units/day. Can we avoid buying another machine?", context, live_provider,
        )
        requirements = parse_result.parsed_requirements
        arena, _ = StrategyArena().explore(electronics_factory, PRODUCT_ID, requirements)

        hard = requirements.allowed_action_types is not None and (
            "ADD_PARALLEL_MACHINE" not in requirements.allowed_action_types
        )
        print(
            f"\n[live 8B] avoid-machine read as {'HARD constraint' if hard else 'soft preference'}"
            f" (prefer_no_new_machines={requirements.prefer_no_new_machines})"
        )

        if hard:
            # A hard reading must be obeyed absolutely.
            for option in arena.strategies:
                assert option.actions.added_machine_count == 0
        else:
            # A soft reading must never hide the equipment answer.
            assert arena.strategies

    def test_compare_two_named_plans_uses_no_model_arithmetic(self, live_exploration):
        """"Compare the machine-heavy and shift-heavy options."""
        arena = live_exploration["arena"]
        if len(arena.strategies) < 2:
            pytest.skip("live exploration produced fewer than two options to compare")

        a, b = arena.strategies[0], arena.strategies[1]
        answer = answer_strategy_query(arena, f"Compare {a.label} and {b.label}.")

        assert answer.intent is StrategyQueryIntent.COMPARE
        assert answer.simulations_run == 0
        comparison = answer.comparison
        assert comparison is not None

        completed = next(r for r in comparison.metrics if r.metric == "completed_units")
        assert completed.value_a == a.metrics.completed_units
        assert completed.value_b == b.metrics.completed_units
        print(f"\n[live 8B] {comparison.headline}")

    def test_follow_up_intents_are_detected_without_a_model(self):
        """Section 15's routing is deterministic on purpose: it must behave
        identically whether or not a provider is configured."""
        assert detect_intent("Show me a cheaper option.") is StrategyQueryIntent.CHEAPER_OPTION
        assert detect_intent("Can we avoid buying another machine?") is StrategyQueryIntent.NO_NEW_MACHINE
        assert detect_intent("Compare the machine-heavy and shift-heavy options.") is StrategyQueryIntent.COMPARE

    def test_the_report_records_what_granite_actually_did(self, live_exploration):
        """A printed record for the Phase 8B report rather than an assertion
        about a desired answer."""
        arena = live_exploration["arena"]
        print("\n[live 8B summary]")
        print(f"   fallback_used={live_exploration['fallback']}")
        print(f"   {arena.summary}")
        print(f"   recommended={arena.recommended_strategy_id}")
        for option in arena.strategies:
            print(f"   {option.label}: {option.rationale}")
        assert arena.stats.simulations_run > 0
