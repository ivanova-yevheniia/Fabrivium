"""Phase 11 — spending ceilings expressed as a LIMIT phrase."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.services.agent_context import build_factory_context
from app.services.requirements_parser import DeterministicFallbackRequirementsParser

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


@pytest.fixture()
def context():
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        factory = Factory.model_validate(json.load(fh))
    return build_factory_context(factory)


def parse(text: str, context):
    return DeterministicFallbackRequirementsParser().parse(text, context).parsed_requirements


class TestLimitPhraseBudget:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("That's too expensive. Keep it below €150k.", 150_000.0),
            ("Keep it below €150k", 150_000.0),
            ("keep it under 150k", 150_000.0),
            ("no more than €1.5m", 1_500_000.0),
            ("at most $250k", 250_000.0),
            ("cap it at €90k", 90_000.0),
            ("up to €1.2 million", 1_200_000.0),
        ],
    )
    def test_limit_phrases_yield_a_ceiling(self, context, text, expected):
        assert parse(text, context).max_capex == expected

    def test_the_exact_suggested_refinement_from_the_ui_parses(self, context):
        """
        This precise sentence is rendered as a clickable suggestion on the entry screen.
        """
        req = parse("That's too expensive. Keep it below €150k.", context)
        assert req.max_capex == 150_000.0

    def test_explicit_budget_keyword_still_wins(self, context):
        assert parse("We need 1900 units/day, budget €220k.", context).max_capex == 220_000.0

    def test_explicit_keyword_preferred_over_a_later_limit_phrase(self, context):
        """Both patterns can match one sentence; the explicit statement of a
        budget is the more direct one and must take precedence."""
        req = parse("Budget €200k, and keep tooling under €20k.", context)
        assert req.max_capex == 200_000.0


class TestNoFalsePositives:
    @pytest.mark.parametrize(
        "text",
        [
            "no more than 2 machines",
            "at most 3 operators",
            "maximum of 2 new machines",
            "We need 1900 units per day",
            "We need 1900 units/day. Avoid buying new machines if possible.",
            "keep it under 3 shifts",
        ],
    )
    def test_counts_are_never_read_as_money(self, context, text):
        assert parse(text, context).max_capex is None

    def test_a_machine_limit_still_parses_as_a_machine_limit(self, context):
        req = parse("no more than 2 machines", context)
        assert req.max_capex is None
        assert req.max_additional_machines == 2


class TestHardVersusSoftUnaffected:
    """The budget fix must not disturb the preference/constraint split the
    strategy arena depends on."""

    def test_soft_preference_stays_soft(self, context):
        req = parse("We need 1900 units/day. Avoid buying new machines if possible.", context)
        assert req.prefer_no_new_machines is True
        assert req.allowed_action_types is None

    def test_hard_ban_stays_hard(self, context):
        req = parse("We need 1900 units/day. Do not buy any new machines.", context)
        assert req.allowed_action_types is not None
        assert not any(a.startswith("ADD_") for a in req.allowed_action_types)

    def test_a_budget_and_a_hard_ban_can_coexist(self, context):
        req = parse("Keep it below €150k. Do not buy any new machines.", context)
        assert req.max_capex == 150_000.0
        assert req.allowed_action_types is not None
        assert not any(a.startswith("ADD_") for a in req.allowed_action_types)
