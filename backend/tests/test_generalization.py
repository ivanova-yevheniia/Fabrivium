"""Generalization regression tests."""

from __future__ import annotations

import pathlib

import pytest

from app.models.product import FactStatus
from app.services.concept_builder import concept_from_brief
from app.services.input_adapters import ingest_text
from app.services.local_estimator import estimate
from app.services.process_planning import plan_process
from app.services.product_extraction import extract_facts, gaps_for
from app.services.product_intelligence import understand_product
from app.services.product_to_concept import concept_from_product
from app.services.requirements_parser import DeterministicFallbackRequirementsParser

ROOT = pathlib.Path(__file__).resolve().parents[2]
CASES = ROOT / "examples" / "generalization"
CEC_PDF = ROOT / "examples" / "customer_docs" / "Compact_Electronics_Controller_Product_Specification.pdf"

CASE_DOCUMENTS = {
    "A": "case_a_lt8_gearbox_housing.txt",
    "B": "case_b_ft9_filter_head.txt",
    "C": "case_c_gr7_guard_assembly.txt",
}


def facts_for(text: str):
    return extract_facts([ingest_text(text, name="case document").evidence[0]])


def fact(facts, key):
    return next((f for f in facts if f.key == key), None)


# A named thing with no stated count


class TestCountIsSeparateFromPresence:
    """A source that names screws without counting them states something."""

    @pytest.mark.parametrize(
        "sentence",
        [
            "The cover is secured with screws that engage bosses in the body.",
            "The lid is held on by bolts.",
            "The sensor is attached with cables.",
            "Screws are driven from the inside face.",
        ],
    )
    def test_presence_is_recorded_without_a_quantity(self, sentence):
        facts = facts_for(sentence)
        counted = [f for f in facts if f.category == "quantity"]
        assert counted, f"nothing was extracted from: {sentence}"
        for found in counted:
            assert found.status is FactStatus.EXTRACTED
            assert found.value == "present"
            assert found.quantity is None
            assert found.evidence, "a fact with nothing to point at is indistinguishable from an invented one"

    @pytest.mark.parametrize(
        "sentence,key,expected",
        [
            ("The enclosure lid is secured with six screws.", "fastener.screw.count", 6.0),
            ("The cover plate is retained by twelve bolts.", "fastener.bolt.count", 12.0),
            ("Two cables connect the PCB to the external terminals.", "connection.cable.count", 2.0),
            ("The bracket is fixed to the shroud with four screws.", "fastener.screw.count", 4.0),
        ],
    )
    def test_a_stated_count_is_still_read(self, sentence, key, expected):
        found = fact(facts_for(sentence), key)
        assert found is not None and found.quantity == expected

    def test_a_counted_sentence_beats_an_uncounted_one_in_the_same_document(self):
        """CEC-120's own shape: one sentence counts the screws, two do not."""
        text = (
            "The enclosure lid is secured with six screws. "
            "The screws engage moulded bosses in the enclosure base. "
            "Screw specification is defined in a separate fastener drawing."
        )
        found = fact(facts_for(text), "fastener.screw.count")
        assert found.status is FactStatus.EXTRACTED
        assert found.quantity == 6.0
        assert len(found.evidence) >= 2, "every sentence that mentioned it should still be citable"

    def test_two_different_counts_are_still_a_conflict(self):
        text = "The lid is secured with six screws. The lid is secured with eight screws."
        found = fact(facts_for(text), "fastener.screw.count")
        assert found.status is FactStatus.CONFLICT
        assert found.quantity is None

    def test_an_absence_is_not_a_presence(self):
        found = fact(facts_for("No cables or electrical connections are present."), "connection.cable.count")
        assert found is None

    def test_a_stated_number_outranks_the_negation_window(self):
        """"no more than six screws" is a sentence about six screws."""
        found = fact(facts_for("The lid is secured with no more than six screws."), "fastener.screw.count")
        assert found is not None and found.quantity == 6.0

    def test_the_missing_count_is_declared_as_a_gap(self):
        facts = facts_for("The cover is secured with screws. The sensor is attached with cables.")
        keys = {gap.key for gap in gaps_for(facts)}
        assert "fastener.screw.count" in keys
        assert "connection.cable.count" in keys

    def test_the_operation_is_proposed_and_the_count_is_asked_for(self):
        """The operation exists either way; only the repeat count is missing."""
        understanding = understand_product(
            ingest_text(
                "The cover is secured with screws that engage bosses in the body. "
                "Each assembly is verified before release. "
                "Finished assemblies are packed individually.",
                name="case document",
            ),
            None,
            product_name="Uncounted product",
        ).understanding
        draft = plan_process(understanding)

        fastening = [op for op in draft.operations if op.process_type == "screwdriving"]
        assert fastening, "a stated fastening operation must not disappear because the count is missing"
        assert fastening[0].repeated_operations is None
        assert any("does not state how many" in q for q in draft.open_questions)


# The two regexes that read the same sentence must agree


class TestEquipmentRestrictionIsReadTheSameWayEverywhere:
    """
    ``concept_builder`` and ``requirements_parser`` both read "no new machines" out of
    customer prose.
    """

    FORBIDDING = [
        "Avoid buying new machines if possible.",
        "Do not buy a new machine.",
        "Do not buy any new machines.",
        "Do not add any new machines this year.",
        "We need 6,000 units per day without any additional equipment.",
        "No more stations can be added.",
    ]

    @pytest.mark.parametrize("brief", FORBIDDING)
    def test_the_concept_records_the_preference(self, brief):
        assert concept_from_brief(f"We need 900 units per day. {brief}").prefer_no_new_machines

    @pytest.mark.parametrize(
        "brief",
        [
            "We need 900 units per day from a single cell.",
            "A budget for one additional station has been approved if it is needed.",
        ],
    )
    def test_a_brief_that_forbids_nothing_records_nothing(self, brief):
        assert not concept_from_brief(brief).prefer_no_new_machines


# A refusal of a lever is not a request for it


class TestLeverRefusalsAreNotReadAsRequests:
    """
    "We cannot hire additional operators" contains *hire*, *additional* and *operators*,
    so the positive operator-lever pattern matched it and the optimizer was told the
    customer WANTED that lever.
    """

    def parse(self, text):
        return DeterministicFallbackRequirementsParser().parse(text).parsed_requirements

    @pytest.mark.parametrize(
        "text,forbidden",
        [
            ("We need 6,000 units per day. No second shift is available.", "CHANGE_SHIFT_CONFIGURATION"),
            ("We need 6,000 units per day. We cannot hire additional operators.", "CHANGE_OPERATOR_CAPACITY"),
            ("Reach 900 a day. Do not add another shift.", "CHANGE_SHIFT_CONFIGURATION"),
            ("Reach 900 a day. Do not add any more operators.", "CHANGE_OPERATOR_CAPACITY"),
            ("Reach 900 a day. No extra staff is available.", "CHANGE_OPERATOR_CAPACITY"),
        ],
    )
    def test_a_refused_lever_is_excluded(self, text, forbidden):
        allowed = self.parse(text).allowed_action_types
        assert allowed is not None, "a stated refusal must reach the optimizer as a constraint"
        assert forbidden not in allowed

    @pytest.mark.parametrize(
        "text,wanted",
        [
            ("Try an extra shift to reach 900 a day.", "CHANGE_SHIFT_CONFIGURATION"),
            ("Add two operators to reach 900 a day.", "CHANGE_OPERATOR_CAPACITY"),
        ],
    )
    def test_a_requested_lever_is_still_requested(self, text, wanted):
        assert self.parse(text).allowed_action_types == [wanted]

    def test_a_softened_refusal_stays_a_preference(self):
        """
        Softening is what separates a rule from a wish, and the existing machine rule
        already works this way.
        """
        allowed = self.parse("Reach 900 a day. Avoid a second shift if possible.").allowed_action_types
        assert allowed is None or "CHANGE_SHIFT_CONFIGURATION" in allowed

    def test_refusals_compose_with_the_equipment_ban(self):
        allowed = self.parse(
            "We need 6,000 units per day. Do not buy any new machines. "
            "No second shift is available and we cannot hire additional operators."
        ).allowed_action_types
        assert allowed is not None
        for forbidden in (
            "ADD_PARALLEL_MACHINE",
            "CHANGE_SHIFT_CONFIGURATION",
            "CHANGE_OPERATOR_CAPACITY",
        ):
            assert forbidden not in allowed


# A band carries its own limits wherever it is used


class TestApplicabilityTravelsWithTheNumber:
    """Every reference band declares where it is valid."""

    @pytest.mark.parametrize(
        "category,description",
        [
            ("screwdriving", "Bolt fastening, 12 times per unit."),
            ("assembly", "Place the cover onto the housing."),
            ("inspection", "Inspect the unit."),
            ("packaging", "Pack the unit."),
        ],
    )
    def test_the_basis_states_the_limits(self, category, description):
        result = estimate(
            process_category=category,
            description=description,
            automation_level="MANUAL",
            operations_per_unit=1,
        )
        assert "They apply to:" in result.basis
        assert "Check this station against that" in result.basis


# The cross-product claim


@pytest.fixture(scope="module")
def understandings():
    found = {}
    for case_id, filename in CASE_DOCUMENTS.items():
        text = (CASES / filename).read_text(encoding="utf-8")
        found[case_id] = understand_product(
            ingest_text(text, name=filename), None, product_name=f"Case {case_id}"
        ).understanding
    return found


class TestTheProductPathGeneralises:
    @pytest.mark.parametrize("case_id", sorted(CASE_DOCUMENTS))
    def test_every_case_yields_a_route(self, understandings, case_id):
        draft = plan_process(understandings[case_id])
        assert draft.operations, f"case {case_id} produced no manufacturing operations"

    @pytest.mark.parametrize("case_id", sorted(CASE_DOCUMENTS))
    def test_every_operation_cites_the_fact_that_produced_it(self, understandings, case_id):
        draft = plan_process(understandings[case_id])
        for operation in draft.operations:
            assert operation.source_fact_keys, f"{operation.id} exists for no stated reason"
            assert operation.basis

    @pytest.mark.parametrize("case_id", sorted(CASE_DOCUMENTS))
    def test_no_simulation_parameter_is_invented_for_any_product(self, understandings, case_id):
        """The concept comes out of the product path with every simulation
        input UNKNOWN — for every product, not just the demo one."""
        understanding = understandings[case_id]
        draft = plan_process(understanding)
        accepted = draft.model_copy(
            update={"operations": [op.accept() for op in draft.operations]}
        )
        concept = concept_from_product(
            understanding,
            accepted,
            "We need 900 units per day.",
            allow_unresolved_requirements=True,
        )
        assert concept.stages
        for stage in concept.stages:
            assert stage.cycle_time.value is None
            assert stage.capacity.value is None
            assert stage.operators_required.value is None
            assert stage.purchase_cost.value is None
