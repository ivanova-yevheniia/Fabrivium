"""Defects found during the first human golden run of the freeze candidate."""

from __future__ import annotations

import pathlib

import pytest

from app.models.product import ProductUnderstanding
from app.services.concept_builder import (
    _FLOOR_RE,
    concept_from_brief,
    production_values_in,
    unreadable_floor_phrase,
)
from app.services.concept_validation import concept_gaps
from app.services.input_adapters import ingest_pdf, ingest_text
from app.services.process_planning import plan_process
from app.services.product_extraction import extract_facts, gaps_for
from app.services.product_intelligence import understand_product
from app.services.product_to_concept import attribute_sources, concept_from_product

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPECIFICATION = ROOT / "examples" / "customer_docs" / "Compact_Electronics_Controller_Product_Specification.pdf"

# The sentence the production-requirements box offers as its own example.
UI_PLACEHOLDER = "1,900 units per day across 2 shifts of 8 hours. 30 by 18 meters. 8 operators."


@pytest.fixture(scope="module")
def cec120() -> ProductUnderstanding:
    """The real customer specification, read by the real extractor."""
    return understand_product(
        ingest_pdf(SPECIFICATION.read_bytes(), name=SPECIFICATION.name),
        None,
        product_name="CEC-120 Compact Electronics Controller",
    ).understanding


def _accepted(understanding: ProductUnderstanding):
    draft = plan_process(understanding)
    return draft.model_copy(update={"operations": [op.accept() for op in draft.operations]})


# G2 — "Screw type and thread" was wrong twice over

class TestScrewParametersAreNamedHonestly:
    def test_a_stated_thread_is_read_rather_than_reported_missing(self, cec120):
        # The specification says "6 x M3 screws" in its characteristics table
        # and "secured using six M3 screws" in its assembly requirements. The
        # screen said the thread was unknown while quoting the M3 back on the
        # line above it.
        thread = cec120.fact("fastener.screw.thread")
        assert thread is not None and thread.known
        assert thread.value == "M3"
        assert thread.evidence, "a stated fact with nothing to point at is indistinguishable from a guess"

    def test_the_gap_names_the_two_things_the_source_really_omits(self, cec120):
        gap = next(g for g in cec120.information_gaps if g.key == "fastener.screw.drive_torque")
        assert "drive type" in gap.label
        assert "fastening torque" in gap.label
        assert "thread" not in gap.label.lower()

    def test_the_gap_does_not_claim_to_block_equipment_selection(self, cec120):
        # Discovery runs on partial capability evidence and returns
        # candidates as "under consideration" — `MatchClaim` deliberately has
        # no COMPATIBLE member. Nothing is blocked; validation is what waits.
        gap = next(g for g in cec120.information_gaps if g.key == "fastener.screw.drive_torque")
        assert gap.severity == "LIMITS_EQUIPMENT_VALIDATION"

    def test_an_unstated_thread_is_still_reported_missing(self):
        # The distinction only means anything if it cuts both ways.
        facts = extract_facts(
            ingest_text("The lid is secured with six screws.", name="s.txt").evidence
        )
        assert not any(f.key == "fastener.screw.thread" for f in facts)
        gap = next(g for g in gaps_for(facts) if g.key == "fastener.screw.drive_torque")
        assert "thread size" in gap.label

    def test_a_source_that_states_everything_raises_no_gap_at_all(self):
        facts = extract_facts(
            ingest_text(
                "The lid is secured with six M3 Torx screws tightened to 2 Nm.",
                name="s.txt",
            ).evidence
        )
        by_key = {f.key: f for f in facts}
        assert by_key["fastener.screw.thread"].value == "M3"
        assert by_key["fastener.screw.drive"].value == "Torx"
        assert by_key["fastener.screw.torque"].value == "2 Nm"
        assert not any(g.key == "fastener.screw.drive_torque" for g in gaps_for(facts))


# G3 — the floor-area parser, and the silence when it cannot read one

class TestFloorAreaParsing:
    @pytest.mark.parametrize(
        "phrase",
        [
            "30 by 18 meters",
            "30 by 18 metres",
            "30 by 18 meter",
            "30 by 18 metre",
            "30 by 18 m",
            "30 x 18 meters",
            "30 x 18 m",
            "30 × 18 meters",
            "30 × 18 m",
            "30x18 m",
            "30×18 m",
            "30 m x 18 m",
            "30 m × 18 m",
            "30m x 18m",
            "30 X 18 M",
            "the hall is 30 by 18 metres wide",
        ],
    )
    def test_every_advertised_form_is_read(self, phrase):
        draft = concept_from_brief(f"1,900 units per day. {phrase}. 8 operators.")
        assert (draft.floor_width.value, draft.floor_length.value) == (30.0, 18.0), phrase

    def test_the_exact_sentence_the_ui_offers_as_an_example_parses(self):
        # A product must never advertise an input format it cannot consume.
        draft = concept_from_brief(UI_PLACEHOLDER)
        assert draft.production_target.value == 1900
        assert draft.operators_available.value == 8
        assert draft.shifts_per_day.value == 2
        assert draft.hours_per_shift.value == 8
        assert (draft.floor_width.value, draft.floor_length.value) == (30.0, 18.0)

    def test_a_dimension_it_cannot_read_is_reported_rather_than_ignored(self):
        # THE ACTUAL GOLDEN-RUN DEFECT.
        typo = "1,900 units per day across 2 shifts of 8 hours. 30 by 18 metes. 8 operators."
        assert _FLOOR_RE.search(typo) is None
        assert unreadable_floor_phrase(typo) == "30 by 18 metes"

        gap = next(g for g in concept_gaps(concept_from_brief(typo)) if g.key == "floor_dimensions")
        assert "30 by 18 metes" in gap.reason
        assert "could not read" in gap.reason

    def test_a_brief_that_states_no_floor_is_not_accused_of_a_typo(self):
        brief = "1,900 units per day. 8 operators."
        assert unreadable_floor_phrase(brief) is None
        gap = next(g for g in concept_gaps(concept_from_brief(brief)) if g.key == "floor_dimensions")
        assert "could not read" not in gap.reason

    def test_a_production_volume_written_the_way_a_specification_writes_it(self):
        # "1,900 finished units/day" is how the CEC-120 document states it,
        # and the reader has to manage the adjective in the middle.
        assert production_values_in("Required production volume 1,900 finished units/day")[
            "production.target_per_day"
        ][1] == 1900.0

    def test_an_hours_per_day_phrase_is_not_read_as_a_production_target(self):
        # The widening above must not turn "8 hours a day" into eight units.
        assert "production.target_per_day" not in production_values_in("The line runs 8 hours a day")


# G4 — who actually stated the operating model

class TestOperatingModelProvenance:
    @staticmethod
    @pytest.fixture(scope="class")
    def concept(cec120):
        return concept_from_product(
            cec120,
            _accepted(cec120),
            UI_PLACEHOLDER,
            name="CEC-120 Production Concept",
            allow_unresolved_requirements=True,
        )

    def test_the_source_states_the_volume_the_area_and_the_workforce(self, cec120):
        stated = {item.key: item for item in cec120.source_production_requirements}
        assert stated["production.target_per_day"].quantity == 1900.0
        assert (
            stated["production.floor_area"].quantity,
            stated["production.floor_area"].quantity_secondary,
        ) == (30.0, 18.0)
        assert stated["production.operators"].quantity == 8.0
        # And every one of them can be gone and looked at.
        for item in stated.values():
            assert item.evidence.quote and item.evidence.page

    def test_the_source_states_nothing_about_the_shift_pattern(self, cec120):
        keys = {item.key for item in cec120.source_production_requirements}
        assert "production.shifts_per_day" not in keys
        assert "production.hours_per_shift" not in keys

    @pytest.mark.parametrize(
        "field", ["production_target", "operators_available", "floor_width", "floor_length"]
    )
    def test_a_source_backed_value_is_the_customers(self, concept, field):
        value = getattr(concept, field)
        assert value.source.value == "CUSTOMER"
        assert "Compact_Electronics_Controller_Product_Specification.pdf" in (value.detail or "")

    @pytest.mark.parametrize("field", ["shifts_per_day", "hours_per_shift"])
    def test_a_value_the_source_never_states_is_the_engineers(self, concept, field):
        # Typing "2 shifts of 8 hours" into the production-requirements box is
        # an engineering assumption about how the line will be run. The
        # document says nothing about shifts, and presenting the assumption as
        # a customer requirement is how an engineer's decision ends up being
        # defended in a review as something the customer asked for.
        value = getattr(concept, field)
        assert value.source.value == "ENGINEER"
        assert "does not state it" in (value.detail or "")

    def test_a_typed_value_that_contradicts_the_source_stays_the_engineers(self, cec120):
        # A person overriding a document is normal and legitimate.
        concept = concept_from_product(
            cec120,
            _accepted(cec120),
            "2,400 units per day. 30 by 18 meters. 8 operators.",
            allow_unresolved_requirements=True,
        )
        assert concept.production_target.value == 2400
        assert concept.production_target.source.value == "ENGINEER"
        # The values the source DOES back are unaffected.
        assert concept.floor_width.source.value == "CUSTOMER"

    def test_with_no_source_evidence_nothing_is_attributed_to_the_customer(self):
        # A product described in the engineer's own words carries no customer
        # document, so no typed number can be blamed on one.
        understanding = understand_product(
            ingest_text("A controller. The lid is secured with six screws.", name="d.txt"),
            None,
            product_name="Controller",
        ).understanding
        assert understanding.source_production_requirements == []

        concept = attribute_sources(concept_from_brief(UI_PLACEHOLDER), understanding)
        for field in ("production_target", "operators_available", "floor_width", "shifts_per_day"):
            assert getattr(concept, field).source.value == "ENGINEER", field

    def test_mixed_provenance_survives_a_save_and_reload(self, concept):
        from app.models.concept import FactoryConceptDraft

        reloaded = FactoryConceptDraft.model_validate(concept.model_dump(mode="json"))
        assert reloaded.production_target.source.value == "CUSTOMER"
        assert reloaded.floor_length.source.value == "CUSTOMER"
        assert reloaded.shifts_per_day.source.value == "ENGINEER"
        assert reloaded.hours_per_shift.source.value == "ENGINEER"


# G5 — which sentence gets quoted as evidence

class TestEvidenceQuality:
    def test_packaging_cites_the_requirement_not_the_table_heading(self, cec120):
        # The specification says "Packaging" in a characteristics table and
        # "Finished product shall be placed in an individual cardboard
        # carton." in its assembly requirements. Both are real evidence; only
        # one of them tells a reader what is required, and the panel shows
        # exactly one.
        packaging = cec120.fact("requirement.packaging")
        quote = packaging.evidence[0].quote
        assert "cardboard carton" in quote
        assert quote.strip().strip("•· ") != "Packaging"

    def test_the_same_citation_is_not_kept_twice(self, cec120):
        # "Individual cardboard carton" appears in the characteristics table
        # and again in the bill of materials. Keeping both spent two of the
        # four slots saying one thing.
        packaging = cec120.fact("requirement.packaging")
        quotes = [(e.page, (e.quote or "").strip()) for e in packaging.evidence]
        assert len(quotes) == len(set(quotes))

    def test_a_heading_is_still_kept_as_evidence_just_not_first(self, cec120):
        # Ranking is not censorship — the table row is a true citation and it
        # stays available.
        quotes = [(e.quote or "").strip() for e in cec120.fact("requirement.packaging").evidence]
        assert "Packaging" in quotes

    def test_the_screwdriving_operation_still_cites_a_sentence_about_screws(self, cec120):
        # An operation carries only its fact's first two citations, so
        # re-ranking must not push every screw sentence out of reach.
        screwdriving = next(
            op for op in plan_process(cec120).operations if op.process_type == "screwdriving"
        )
        assert any("screw" in (e.quote or "").lower() for e in screwdriving.evidence)


# G6 — a lid cannot be screwed down before it is fitted

class TestClosurePrecedesTheFasteningThatSecuresIt:
    def test_the_cec120_route_closes_the_enclosure_before_driving_its_screws(self, cec120):
        names = [op.name for op in plan_process(cec120).operations]
        assert names.index("Enclosure closure") < names.index("Screw fastening ×6")

    def test_the_ordering_comes_from_the_source_saying_the_screws_hold_the_lid(self):
        understanding = understand_product(
            ingest_text(
                "The PCB is placed in the housing. "
                "The lid shall be secured using six screws.",
                name="d.txt",
            ),
            None,
            product_name="Widget",
        ).understanding
        names = [op.name for op in plan_process(understanding).operations]
        assert names.index("Enclosure closure") < names.index("Screw fastening ×6")

    def test_a_fastening_the_source_never_ties_to_a_closure_is_left_where_it_was(self):
        # The failure mode of a blunt fix: every screwdriving operation
        # shoved behind every closure, whatever it fastens. Here the screws
        # hold the PCB down and the cover goes on afterwards, so the route
        # the rule table proposes is already right and must be left alone.
        understanding = understand_product(
            ingest_text(
                "The PCB is fixed to the base with four screws. "
                "A cover is then fitted over the assembly.",
                name="d.txt",
            ),
            None,
            product_name="Widget",
        ).understanding
        names = [op.name for op in plan_process(understanding).operations]
        assert names.index("Screw fastening ×4") < names.index("Enclosure closure")


# G7 — a label that must be APPLIED implies work; a label in a parts list does not

class TestLabellingIsProposedFromARequirement:
    def test_the_cec120_route_includes_product_labelling(self, cec120):
        names = [op.name for op in plan_process(cec120).operations]
        assert "Product labelling" in names

    def test_labelling_precedes_the_inspection_that_checks_for_it(self, cec120):
        # The source's own acceptance criteria include "Product
        # identification label shall be present and readable", so inspecting
        # before the label is applied would check for something that cannot
        # be there yet.
        names = [op.name for op in plan_process(cec120).operations]
        assert names.index("Product labelling") < names.index("Visual inspection")

    def test_the_operation_answers_the_label_requirement_by_itself(self, cec120):
        from app.services.requirement_coverage import coverage_for

        report = coverage_for(cec120, plan_process(cec120))
        label = next(item for item in report.items if item.fact_key == "component.label")
        assert label.status.value == "ADDRESSED"
        assert "Product labelling" in label.addressed_by

    def test_a_label_the_source_only_lists_proposes_nothing(self):
        # A bill of materials saying the product HAS a label is not a
        # statement that anybody applies one — it might arrive pre-labelled.
        # Proposing a station from it would invent work.
        understanding = understand_product(
            ingest_text(
                "The unit consists of a PCB, an enclosure and one identification label.",
                name="d.txt",
            ),
            None,
            product_name="Widget",
        ).understanding
        assert understanding.fact("component.label") is not None
        assert not any(
            op.process_type == "labelling" for op in plan_process(understanding).operations
        )

    def test_an_unproposed_label_requirement_is_still_reported_as_unanswered(self):
        # And when nothing is proposed, the requirement does not vanish: it
        # comes back as the engineer's to answer, which is the fallback the
        # golden run exercised by hand.
        from app.services.requirement_coverage import coverage_for

        understanding = understand_product(
            ingest_text(
                "The unit consists of a PCB, an enclosure and one identification label.",
                name="d.txt",
            ),
            None,
            product_name="Widget",
        ).understanding
        report = coverage_for(understanding, plan_process(understanding))
        assert "component.label" in {item.fact_key for item in report.unresolved}


# G1 — renaming a product is not re-sourcing it

class TestRenamingDoesNotInvalidateTheReading:
    def _state(self):
        from app.models.project import ProjectState

        state = ProjectState()
        state.product.name = "Product"
        state.product.description = "The lid is secured with six screws."
        state.product.understanding = {
            "facts": [{"key": "fastener.screw.count", "value": "6", "status": "EXTRACTED"}]
        }
        return state

    def test_a_rename_changes_no_input_channel(self):
        from app.models.project import Channel
        from app.services.project_revisions import describe_changes

        before = self._state()
        after = before.model_copy(deep=True)
        after.product.name = "CEC-120 Compact Electronics Controller"

        changed = {channel for channel, _ in describe_changes(before, after)}
        assert Channel.PRODUCT_SOURCE not in changed
        assert changed == set(), "renaming a product invalidates nothing it was read from"

    def test_changing_the_source_text_still_does(self):
        from app.models.project import Channel
        from app.services.project_revisions import describe_changes

        before = self._state()
        after = before.model_copy(deep=True)
        after.product.description = "The lid is secured with eight screws."

        changed = {channel for channel, _ in describe_changes(before, after)}
        assert Channel.PRODUCT_SOURCE in changed
