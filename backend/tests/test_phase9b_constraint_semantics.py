"""Phase 9B section 17 — "avoid ..."""

from __future__ import annotations

import pytest

from app.models.scenario import SUPPORTED_ACTION_TYPES
from app.services.requirements_parser import DeterministicFallbackRequirementsParser

SOFT_REQUEST = "We need 1900 units/day. Avoid buying new machines if possible."
HARD_REQUEST = "We need 1900 units/day. Do not buy any new machines."


@pytest.fixture
def parser() -> DeterministicFallbackRequirementsParser:
    return DeterministicFallbackRequirementsParser()


def parse(parser: DeterministicFallbackRequirementsParser, text: str):
    return parser.parse(text, None).parsed_requirements


def forbids_equipment(requirements) -> bool:
    """True only when the optimizer is actually barred from buying."""
    allowed = requirements.allowed_action_types
    return allowed is not None and "ADD_PARALLEL_MACHINE" not in allowed


class TestSoftPreference:
    def test_avoid_if_possible_never_becomes_a_hard_rule(self, parser):
        """The whole point of the flagship demo: FactoryMind must still be
        free to find, and recommend, an equipment plan — otherwise a
        preference silently hides the only answer that works."""
        requirements = parse(parser, SOFT_REQUEST)

        assert forbids_equipment(requirements) is False
        assert requirements.allowed_action_types is None
        assert requirements.max_additional_machines is None

    def test_the_preference_is_still_recorded(self, parser):
        assert parse(parser, SOFT_REQUEST).prefer_no_new_machines is True

    def test_the_numeric_target_survives_alongside_the_preference(self, parser):
        assert parse(parser, SOFT_REQUEST).target_units_per_day == 1900.0

    @pytest.mark.parametrize("text", [
        "We need 1900 units/day. Avoid buying new machines if possible.",
        "We need 1900 units/day but avoid buying another machine if possible.",
        "Reach 1900 units/day, preferably without adding a machine.",
        "Get to 1900 units/day — I'd rather not add another machine.",
    ])
    def test_softened_phrasings_all_stay_soft(self, parser, text: str):
        requirements = parse(parser, text)
        assert forbids_equipment(requirements) is False


class TestHardConstraint:
    def test_do_not_buy_any_new_machines_removes_the_lever(self, parser):
        """The Phase 9B regression."""
        requirements = parse(parser, HARD_REQUEST)

        assert forbids_equipment(requirements) is True
        assert "ADD_PARALLEL_MACHINE" not in requirements.allowed_action_types

    def test_the_other_levers_stay_open(self, parser):
        """"Do not buy machines" restricts ONE lever, not the whole search:
        shifts, operators and buffers must remain available or the request
        becomes unanswerable for no reason."""
        allowed = set(parse(parser, HARD_REQUEST).allowed_action_types)

        assert allowed == set(SUPPORTED_ACTION_TYPES) - {"ADD_PARALLEL_MACHINE"}
        assert "CHANGE_SHIFT_CONFIGURATION" in allowed
        assert "CHANGE_OPERATOR_CAPACITY" in allowed

    def test_the_numeric_target_survives_alongside_the_rule(self, parser):
        assert parse(parser, HARD_REQUEST).target_units_per_day == 1900.0

    @pytest.mark.parametrize("text", [
        "We need 1900 units/day. Do not buy any new machines.",
        "We need 1900 units/day. Don't purchase any new machines.",
        "Can we reach 1900 units/day without buying any new machines?",
        "Can we reach 1900 units/day without buying another machine?",
        "Reach 1900 units/day. Do not add more new machines.",
    ])
    def test_stacked_qualifiers_no_longer_break_the_match(self, parser, text: str):
        """
        Each of these stacks qualifiers ("any new", "more new") or uses a single one.
        """
        assert forbids_equipment(parse(parser, text)) is True


class TestTheTwoAreNeverConfused:
    def test_the_same_sentence_shape_yields_opposite_semantics(self, parser):
        """Same topic, same lever, opposite force."""
        soft = parse(parser, SOFT_REQUEST)
        hard = parse(parser, HARD_REQUEST)

        assert forbids_equipment(soft) is False
        assert forbids_equipment(hard) is True
        assert soft.target_units_per_day == hard.target_units_per_day == 1900.0

    def test_a_hard_prohibition_is_not_ALSO_reported_as_a_preference(self, parser):
        """A rule and a ranking hint are different things."""
        assert parse(parser, HARD_REQUEST).prefer_no_new_machines is False

    def test_neither_instruction_is_ever_silently_dropped(self, parser):
        """The exact failure mode the fix addresses: an equipment
        instruction that produces no rule AND no preference."""
        for text in (SOFT_REQUEST, HARD_REQUEST):
            requirements = parse(parser, text)
            recorded = forbids_equipment(requirements) or requirements.prefer_no_new_machines
            assert recorded, f"{text!r} produced neither a constraint nor a preference"
