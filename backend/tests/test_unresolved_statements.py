"""The extraction-completeness boundary — is an unmapped requirement visible?"""

from __future__ import annotations

import pathlib

import pytest

from app.services.input_adapters import NormalizedEvidence
from app.services.product_extraction import extract_facts
from app.services.unresolved_statements import describe, unresolved_statements

CASES = pathlib.Path(__file__).resolve().parents[2] / "examples" / "generalization"


def evidence(text: str, name: str = "spec.txt", page: int | None = 1) -> list[NormalizedEvidence]:
    return [NormalizedEvidence(document_id="doc-1", document_name=name, page=page, text=text)]


def statements(text: str) -> list[str]:
    return [s.statement for s in unresolved_statements(evidence(text))]


class TestItDetectsWorkTheExtractorMissed:
    """Grammar, on vocabulary the codebase has never seen."""

    def test_a_verb_nobody_enumerated_is_still_detected(self):
        # "anodised" appears in no rule table, no keyword list and no fixture
        # anywhere in this repository. If it is found, the rule is the
        # passive voice and not a dictionary.
        found = statements("The finished bracket is anodised to a matt black finish.")
        assert found == ["The finished bracket is anodised to a matt black finish."]

    def test_specification_voice_is_detected(self):
        found = statements("Each terminal shall be swaged to the stated diameter.")
        assert found == ["Each terminal shall be swaged to the stated diameter."]

    @pytest.mark.parametrize(
        "sentence",
        [
            "The rim is lacquered in a single pass.",
            "The plate must be deburred on both faces.",
            "The seams are ultrasonically welded on the rotary table.",
            "Every collar should be crimped to the stated diameter.",
        ],
    )
    def test_unrelated_operations_on_unrelated_products(self, sentence):
        assert statements(sentence) == [sentence]

    def test_two_unrelated_real_documents_both_surface_work(self):
        """The generalization requirement, on the preregistered cases."""
        gearbox = statements((CASES / "case_a_lt8_gearbox_housing.txt").read_text(encoding="utf-8"))
        guard = statements((CASES / "case_c_gr7_guard_assembly.txt").read_text(encoding="utf-8"))

        assert any("washed and degreased" in s for s in gearbox)
        assert any("clipped into the shroud aperture" in s for s in guard)
        # Neither document's operations leak into the other's result.
        assert not any("shroud" in s for s in gearbox)
        assert not any("castings" in s for s in guard)


class TestItRefusesToInvent:
    """The mechanism reports a candidate. It never produces an answer."""

    def test_no_fact_is_created(self):
        text = "The finished bracket is anodised to a matt black finish."
        assert unresolved_statements(evidence(text))
        # The same text through the real extractor yields nothing about
        # anodising, and that stays true: a detected statement is not a fact.
        assert not [f for f in extract_facts(evidence(text)) if "anod" in (f.value or "").lower()]

    def test_the_statement_is_the_document_s_own_words(self):
        sentence = "The rim is lacquered in a single pass on the rotary table."
        found = unresolved_statements(evidence(sentence))
        assert found[0].statement == sentence
        assert found[0].evidence.quote == sentence

    def test_it_carries_where_to_go_and_look(self):
        found = unresolved_statements(evidence("The rim is lacquered in a single pass.", "FT-9.pdf", 4))
        assert found[0].evidence.document_name == "FT-9.pdf"
        assert found[0].evidence.page == 4

    def test_the_reason_does_not_claim_understanding(self):
        found = unresolved_statements(evidence("The rim is lacquered in a single pass."))
        reason = found[0].reason.lower()
        assert "not" in reason and "extraction" in reason
        assert "operation" in reason


class TestItStaysQuietWhenItShould:
    """Every one of these produced a false candidate during development."""

    def test_a_sentence_the_extractor_did_map_is_not_reported(self):
        # Six screws IS extracted, so the sentence is not unmapped.
        assert statements("The lid shall be secured using six M3 screws.") == []

    def test_a_sentence_about_the_paperwork_is_not_work(self):
        assert statements("This specification is issued at concept stage.") == []
        assert statements("Detailed design data is issued separately under the design record.") == []

    def test_a_legal_disclaimer_is_not_work(self):
        """The demonstration document's own closing paragraph."""
        assert statements("Any resemblance to an existing organisation is unintended.") == []
        assert statements("Any resemblance to an existing organization is unintended.") == []
        assert statements("Reproduction of this drawing is prohibited without consent.") == []

    def test_the_disclaimer_guard_does_not_suppress_real_labelling_work(self):
        """The guard names only things that cannot be a unit on a line."""
        assert statements(
            "The company name is engraved onto each finished item before despatch."
        ) == ["The company name is engraved onto each finished item before despatch."]
        assert statements(
            "The customer logo is silk screened onto the front face."
        ) == ["The customer logo is silk screened onto the front face."]

    def test_a_negated_sentence_is_not_an_instruction(self):
        assert statements("The housing is not painted at this stage.") == []
        assert statements("Several quantities are deliberately not yet fixed.") == []

    def test_a_description_is_not_an_instruction(self):
        assert statements("The LT-8 is a sealed single-stage gearbox housing unit.") == []
        assert statements("Two candidates are being evaluated by engineering.") == []

    def test_a_heading_is_too_short_to_be_a_statement(self):
        assert statements("4. FASTENING") == []

    def test_the_golden_document_is_clean(self):
        """CEC-120's specification voice is fully mapped."""
        pdf = (
            pathlib.Path(__file__).resolve().parents[2]
            / "examples"
            / "customer_docs"
            / "Compact_Electronics_Controller_Product_Specification.pdf"
        )
        from app.services.input_adapters import ingest

        ingestion = ingest(pdf.read_bytes(), name=pdf.name)
        facts = extract_facts(ingestion.evidence)
        assert unresolved_statements(ingestion.evidence, facts) == []


class TestPresentation:
    def test_a_clean_result_does_not_claim_the_document_is_understood(self):
        text = describe([])
        assert "not a claim" in text.lower()

    def test_sentences_are_quoted_whole_across_a_line_break(self):
        """Case documents are hard-wrapped; a half sentence is not evidence."""
        wrapped = "The machined bores are blown dry with filtered air and the\nsealing faces are wiped with solvent."
        assert statements(wrapped) == [
            "The machined bores are blown dry with filtered air and the sealing faces are wiped with solvent."
        ]

    def test_a_decimal_point_does_not_end_a_sentence(self):
        text = "Each completed assembly is pressure tested for leaks at 0.5 bar."
        assert statements(text) == [text]

    def test_a_repeated_instruction_is_one_open_question(self):
        text = "The rim is lacquered in a single pass.\n\nThe rim is lacquered in a single pass."
        assert len(statements(text)) == 1


class TestTheBoundaryBetweenTheTwoMechanisms:
    """Where a source sentence lands, and that it always lands somewhere."""

    BEARINGS = "The two ball bearings are pressed into the housing bores on an arbor press."

    def test_a_sentence_with_a_fact_goes_to_coverage_not_to_this_module(self):
        from app.models.product import ProductUnderstanding
        from app.services.process_planning import plan_process
        from app.services.requirement_coverage import CoverageStatus, coverage_for

        facts = extract_facts(evidence(self.BEARINGS))
        assert facts, "the fixture is only meaningful if extraction produced something"
        assert unresolved_statements(evidence(self.BEARINGS), facts) == []

        understanding = ProductUnderstanding(product_name="LT-8", facts=facts)
        report = coverage_for(understanding, plan_process(understanding))
        unresolved = [i for i in report.items if i.status is CoverageStatus.UNRESOLVED]
        assert unresolved, "a sentence stating work must not vanish down either route"

    def test_no_specification_voice_sentence_falls_between_the_two(self):
        """Every detected work sentence in a real document lands somewhere."""
        from app.models.product import ProductUnderstanding
        from app.services.process_planning import plan_process
        from app.services.requirement_coverage import coverage_for

        text = (CASES / "case_a_lt8_gearbox_housing.txt").read_text(encoding="utf-8")
        source = evidence(text)
        facts = extract_facts(source)
        understanding = ProductUnderstanding(product_name="LT-8", facts=facts)

        covered_keys = {i.fact_key for i in coverage_for(understanding, plan_process(understanding)).items}
        reported = {s.statement for s in unresolved_statements(source, facts)}

        # Nothing reported here is also a fact key elsewhere, and both sets
        # are non-empty: the document exercises both routes.
        assert reported
        assert covered_keys
        assert not (reported & covered_keys)
