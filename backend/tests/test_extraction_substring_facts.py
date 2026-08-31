"""A marker inside a longer word is not a fact."""

from __future__ import annotations

import pytest

from app.services.input_adapters import ingest_text
from app.services.product_extraction import _marker_position, _tokens, extract_facts


def facts_for(text: str):
    return extract_facts([ingest_text(text, name="case document").evidence[0]])


def keys(text: str) -> set[str]:
    return {f.key for f in facts_for(text)}


def value_of(text: str, key: str):
    return next((f.value for f in facts_for(text) if f.key == key), None)


# The two measured fabrications


def test_absorbent_does_not_make_the_enclosure_abs():
    """The exact sentence that produced `material.enclosure = ABS` for a
    polypropylene product."""
    text = (
        "The nitrocellulose membrane strip and the absorbent pad are supplied "
        "pre-cut by the reagent supplier."
    )
    assert "material.enclosure" not in keys(text)


def test_validation_does_not_make_a_lid():
    """The exact sentence that produced an Enclosure closure station out of
    a document's disclaimer line."""
    text = "Synthetic case document written for Fabrivium generalization validation."
    assert "component.lid" not in keys(text)


def test_the_real_material_is_still_read():
    """The fix must not buy its precision by going blind."""
    assert value_of("The enclosure base and lid are moulded in ABS.", "material.enclosure") == "ABS"


def test_the_real_lid_is_still_read():
    assert "component.lid" in keys("The enclosure base and lid are moulded in ABS.")


# The matcher itself


@pytest.mark.parametrize("sentence,marker", [
    ("the absorbent pad are supplied", "abs"),
    ("for generalization validation", "lid"),
    ("a consolidated solid assembly", "lid"),
    ("the coverage of the report", "cover"),
    ("metallurgical analysis follows", "metal"),
])
def test_a_marker_inside_a_longer_word_is_not_a_match(sentence, marker):
    assert _marker_position(_tokens(sentence), marker) is None


@pytest.mark.parametrize("sentence,marker", [
    ("moulded in ABS", "abs"),
    ("moulded in PC/ABS", "pc/abs"),
    ("the enclosure base and lid", "lid"),
    ("a printed circuit board is fitted", "printed circuit board"),
    ("hex socket drive", "hex socket"),
    ("stainless steel body", "stainless"),
])
def test_a_whole_token_marker_still_matches(sentence, marker):
    assert _marker_position(_tokens(sentence), marker) is not None


@pytest.mark.parametrize("sentence,marker", [
    ("the housings are moulded", "housing"),
    ("two covers are fitted", "cover"),
])
def test_a_plural_is_the_same_word(sentence, marker):
    """A specification writes "two covers", and that is the same component."""
    assert _marker_position(_tokens(sentence), marker) is not None


def test_a_multi_word_marker_must_be_contiguous():
    """"hex" and "socket" in one sentence is not "hex socket"."""
    assert _marker_position(_tokens("a hex bolt in a socket head"), "hex socket") is None


# Negation still reaches the right word


def test_a_negated_material_is_still_not_recorded():
    assert "material.enclosure" not in keys("No metal housing parts are used.")


def test_negation_of_one_material_does_not_suppress_another():
    """The docstring case in `_negated`: the negation must not reach back
    past a conjunction to the material that IS used."""
    assert value_of("The lid is ABS, and no metal is used.", "material.enclosure") == "ABS"


# The production target is counted in whatever the product is


class TestTargetNoun:
    """A customer counts in bottles, cassettes or pallets — not in "units"."""

    @pytest.mark.parametrize("brief,expected", [
        ("We need 18,000 bottles per day across 2 shifts of 8 hours.", 18000),
        ("We need 4,000 cassettes per day across 3 shifts of 7.5 hours.", 4000),
        ("20 pallets a day", 20),
        ("We need about 1,900 units per day.", 1900),
        ("We need 1900 units/day, budget 220k.", 1900),
        ("We need 1,900 finished units/day.", 1900),
        ("about 1900 a day", 1900),
        ("900 units per day from a single cell", 900),
    ])
    def test_a_stated_target_is_read_whatever_the_product_is_called(self, brief, expected):
        from app.services.concept_builder import concept_from_brief

        assert concept_from_brief(brief).production_target.value == expected

    @pytest.mark.parametrize("brief", [
        "The line runs 24 hours a day.",
        "The line operates 16 hours per day.",
        "We run 2 shifts a day.",
        "We run two 8-hour shifts.",
    ])
    def test_a_unit_of_time_is_never_a_production_target(self, brief):
        """The trap the closed noun list existed to avoid, kept."""
        from app.services.concept_builder import concept_from_brief

        assert concept_from_brief(brief).production_target.value is None
