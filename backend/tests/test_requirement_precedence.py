"""Precedence between requirements accumulated across conversation turns."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.services.agent_context import build_factory_context
from app.services.requirement_precedence import (
    merge_requirements_sequence,
    relaxes_equipment_ban,
)
from app.services.requirements_parser import DeterministicFallbackRequirementsParser

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


@pytest.fixture()
def context():
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        factory = Factory.model_validate(json.load(fh))
    return build_factory_context(factory)


def parse_one(text: str, context):
    return DeterministicFallbackRequirementsParser().parse(text, context).parsed_requirements


def fold(context, *turns: str):
    """Parse each turn ALONE, then merge — the real request path."""
    return merge_requirements_sequence([parse_one(t, context) for t in turns], list(turns))


def bans_equipment(requirements) -> bool:
    allowed = requirements.allowed_action_types
    return allowed is not None and not any(a.startswith("ADD_") for a in allowed)


# Parser layer — a softener governs its own clause, not the whole message


class TestSoftenerLocality:
    def test_a_softened_restriction_alone_is_still_only_a_preference(self, context):
        req = parse_one("Avoid buying new machines if possible.", context)
        assert not bans_equipment(req)
        assert req.prefer_no_new_machines is True

    def test_an_absolute_restriction_alone_is_still_hard(self, context):
        req = parse_one("Do not buy any new machines.", context)
        assert bans_equipment(req)

    def test_an_unrelated_softener_does_not_downgrade_a_hard_ban(self, context):
        """One message, one turn, no concatenation — this was wrong before
        the accumulation path even existed."""
        req = parse_one("Use more operators if possible, but do not buy any new machines.", context)
        assert bans_equipment(req)

    def test_a_hard_ban_supersedes_the_soft_preference_about_the_same_thing(self, context):
        req = parse_one("Avoid new machines if possible. Do not buy any new machines.", context)
        assert bans_equipment(req)
        # Reporting both would show the same wish as a rule AND a preference.
        assert req.prefer_no_new_machines is False

    def test_the_flagship_request_is_unchanged(self, context):
        """The Phase 11 golden values depend on this staying SOFT."""
        req = parse_one("We need 1900 units/day. Avoid buying new machines if possible.", context)
        assert not bans_equipment(req)
        assert req.prefer_no_new_machines is True
        assert req.target_units_per_day == 1900.0


# Sequence merge — precedence between turns


class TestSoftThenHard:
    def test_a_later_hard_constraint_overrides_an_earlier_soft_preference(self, context):
        merged = fold(
            context,
            "We need 1900 units/day. Avoid buying new machines if possible.",
            "Do not buy any new machines.",
        )
        assert bans_equipment(merged)
        assert merged.prefer_no_new_machines is False

    def test_the_earlier_target_survives_the_refinement(self, context):
        merged = fold(
            context,
            "We need 1900 units/day. Avoid buying new machines if possible.",
            "Do not buy any new machines.",
        )
        assert merged.target_units_per_day == 1900.0

    def test_order_does_not_matter_for_hard_versus_soft(self, context):
        """Whichever order they arrive in, the absolute statement governs —
        precedence is about hardness, not position."""
        assert bans_equipment(fold(context, "Do not buy any new machines.", "Avoid new machines if possible."))


class TestExplicitRelaxation:
    @pytest.mark.parametrize(
        "release",
        [
            "Actually, new machines are allowed.",
            "New equipment is fine.",
            "You can buy machines now.",
            "Lift the machine ban.",
        ],
    )
    def test_an_explicit_release_clears_an_earlier_ban(self, context, release):
        merged = fold(context, "Do not buy any new machines.", release)
        assert not bans_equipment(merged)

    def test_silence_never_clears_a_ban(self, context):
        """A hard constraint must not be weakened just because a later turn
        talks about something else."""
        merged = fold(context, "Do not buy any new machines.", "Keep it below €150k.")
        assert bans_equipment(merged)
        assert merged.max_capex == 150_000.0

    def test_relaxation_detector_is_narrow(self):
        assert relaxes_equipment_ban("new machines are allowed") is True
        assert relaxes_equipment_ban("make it better") is False
        assert relaxes_equipment_ban("do not buy any new machines") is False


class TestBudgetReplacement:
    def test_a_lower_later_budget_replaces_the_earlier_one(self, context):
        merged = fold(context, "Keep CAPEX below €220k.", "Actually keep it below €150k.")
        assert merged.max_capex == 150_000.0

    def test_a_higher_later_budget_also_replaces_it(self, context):
        """Replacement, not a running minimum — the newest statement is the
        user's current intent in both directions."""
        merged = fold(context, "Keep CAPEX below €150k.", "We can spend up to €220k.")
        assert merged.max_capex == 220_000.0

    def test_a_turn_that_does_not_mention_the_budget_carries_it_forward(self, context):
        merged = fold(context, "Keep CAPEX below €150k.", "Do not buy any new machines.")
        assert merged.max_capex == 150_000.0


class TestUnrelatedConstraintsAccumulate:
    def test_a_budget_and_a_ban_both_survive(self, context):
        merged = fold(context, "Keep CAPEX below €150k.", "Do not buy new machines.")
        assert merged.max_capex == 150_000.0
        assert bans_equipment(merged)

    def test_target_budget_and_ban_all_survive_three_turns(self, context):
        merged = fold(
            context,
            "We need 1900 units/day.",
            "Keep it below €150k.",
            "Do not buy any new machines.",
        )
        assert merged.target_units_per_day == 1900.0
        assert merged.max_capex == 150_000.0
        assert bans_equipment(merged)

    def test_a_first_turn_constraint_survives_a_third_turn(self, context):
        """The regression behind carrying EVERY prior turn, not just the
        most recent one."""
        merged = fold(
            context,
            "We need 1900 units/day.",
            "Do not buy any new machines.",
            "Keep it below €150k.",
        )
        assert merged.target_units_per_day == 1900.0
        assert bans_equipment(merged)


class TestIdempotenceAndDeterminism:
    def test_repeating_an_equivalent_constraint_changes_nothing(self, context):
        once = fold(context, "Do not buy any new machines.")
        twice = fold(context, "Do not buy any new machines.", "Do not buy any new machines.")
        assert bans_equipment(twice)
        assert twice.allowed_action_types == once.allowed_action_types

    def test_repeating_the_same_budget_changes_nothing(self, context):
        merged = fold(context, "Keep it below €150k.", "Keep it below €150k.")
        assert merged.max_capex == 150_000.0

    def test_merging_is_deterministic(self, context):
        turns = ("We need 1900 units/day. Avoid buying new machines if possible.", "Do not buy any new machines.")
        assert fold(context, *turns).model_dump_json() == fold(context, *turns).model_dump_json()

    def test_a_single_turn_merges_to_itself(self, context):
        text = "We need 1900 units/day. Avoid buying new machines if possible."
        assert fold(context, text).model_dump_json() == parse_one(text, context).model_dump_json()

    def test_an_empty_sequence_is_refused_rather_than_invented(self):
        with pytest.raises(ValueError):
            merge_requirements_sequence([])


# Endpoint wiring — prior_requests must actually reach the merge


class TestExploreEndpointPrecedence:
    """
    Uses the real API surface, so a wiring mistake between the request model and the
    merge cannot pass silently.
    """

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    @pytest.fixture()
    def factory_payload(self):
        with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_later_hard_ban_overrides_an_earlier_soft_preference(self, client, factory_payload):
        response = client.post("/strategies/explore", json={
            "factory": factory_payload,
            "product_id": factory_payload["products"][0]["id"],
            "prior_requests": ["We need 1900 units/day. Avoid buying new machines if possible."],
            "user_request": "Do not buy any new machines.",
        })
        assert response.status_code == 200
        req = response.json()["parse_result"]["parsed_requirements"]

        assert req["target_units_per_day"] == 1900.0, "the earlier target was dropped"
        assert req["allowed_action_types"] is not None
        assert not any(a.startswith("ADD_") for a in req["allowed_action_types"])
        assert req["prefer_no_new_machines"] is False

    def test_no_returned_strategy_adds_a_machine_under_a_hard_ban(self, client, factory_payload):
        response = client.post("/strategies/explore", json={
            "factory": factory_payload,
            "product_id": factory_payload["products"][0]["id"],
            "prior_requests": ["We need 1900 units/day. Avoid buying new machines if possible."],
            "user_request": "Do not buy any new machines.",
        })
        assert response.status_code == 200
        strategies = response.json()["arena"]["strategies"]
        assert strategies, "the ban must not eliminate every option"
        offenders = [s["label"] for s in strategies if s["actions"]["added_machine_count"] > 0]
        assert not offenders, f"hard ban violated by: {offenders}"

    def test_omitting_prior_requests_preserves_single_request_behaviour(self, client, factory_payload):
        response = client.post("/strategies/explore", json={
            "factory": factory_payload,
            "product_id": factory_payload["products"][0]["id"],
            "user_request": "We need 1900 units/day. Avoid buying new machines if possible.",
        })
        assert response.status_code == 200
        req = response.json()["parse_result"]["parsed_requirements"]
        assert req["target_units_per_day"] == 1900.0
        assert req["allowed_action_types"] is None
        assert req["prefer_no_new_machines"] is True
