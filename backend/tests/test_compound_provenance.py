"""G12 — one requirement, one answer to "who required this?"."""

from __future__ import annotations

import pytest

from app.models.concept import ValueSource
from app.models.product import EvidenceRef, ProductUnderstanding, SourceProductionRequirement
from app.services.concept_builder import concept_from_brief
from app.services.input_resolution import resolution_plan, write_input
from app.services.product_to_concept import attribute_sources

BRIEF = (
    "We need about 1,900 units per day. The available production area is 30 by 18 meters. "
    "We have eight operators."
)


def floor_statement(value: str, quantity: float, secondary: float | None) -> SourceProductionRequirement:
    return SourceProductionRequirement(
        key="production.floor_area",
        label="Available production area",
        value=value,
        quantity=quantity,
        quantity_secondary=secondary,
        evidence=EvidenceRef(
            document_id="d1",
            document_name="Compact_Electronics_Controller_Product_Specification.pdf",
            page=2,
            quote=f"The available production area is {value}.",
        ),
    )


def understanding_with(*requirements: SourceProductionRequirement) -> ProductUnderstanding:
    return ProductUnderstanding(
        product_name="Compact electronics controller",
        source_production_requirements=list(requirements),
    )


def floor_of(draft):
    return (draft.floor_width.source, draft.floor_length.source)


class TestTheFloorIsOneRequirement:
    def test_a_customer_stated_floor_makes_both_dimensions_customer(self):
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("30 × 18 m", 30.0, 18.0))
        )

        assert draft.floor_width.value == 30.0
        assert draft.floor_length.value == 18.0
        assert floor_of(draft) == (ValueSource.CUSTOMER, ValueSource.CUSTOMER)

    def test_the_order_the_document_wrote_the_sides_in_is_not_provenance(self):
        """The regression. Same rectangle, sides written the other way round."""
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("18 × 30 m", 18.0, 30.0))
        )

        assert floor_of(draft) == (ValueSource.CUSTOMER, ValueSource.CUSTOMER)

    def test_a_floor_the_source_does_not_state_is_the_engineers_on_both_sides(self):
        # The honest opposite case, and it is just as important that the two
        # halves agree here: half a floor cannot be the customer's.
        draft = attribute_sources(concept_from_brief(BRIEF), understanding_with())

        assert floor_of(draft) == (ValueSource.ENGINEER, ValueSource.ENGINEER)

    def test_a_source_stating_a_different_floor_corroborates_neither_half(self):
        # 30 × 20 is not the floor the concept holds.
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("30 × 20 m", 30.0, 20.0))
        )

        assert floor_of(draft) == (ValueSource.ENGINEER, ValueSource.ENGINEER)

    def test_a_source_that_states_only_one_number_does_not_half_corroborate(self):
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("540 m²", 540.0, None))
        )

        assert floor_of(draft) == (ValueSource.ENGINEER, ValueSource.ENGINEER)

    def test_single_valued_requirements_are_unaffected(self):
        # The compound rule must not change how an ordinary requirement is
        # attributed: one number, one field, matched as it always was.
        draft = attribute_sources(
            concept_from_brief(BRIEF),
            understanding_with(
                SourceProductionRequirement(
                    key="production.target_per_day",
                    label="Production target",
                    value="1900 units/day",
                    quantity=1900.0,
                    quantity_secondary=None,
                    evidence=EvidenceRef(document_id="d1", document_name="spec.pdf", page=2, quote="1,900 a day"),
                )
            ),
        )

        assert draft.production_target.source is ValueSource.CUSTOMER
        assert draft.operators_available.source is ValueSource.ENGINEER


class TestEditingOneSideEditsTheFloor:
    @pytest.fixture
    def customer_floor(self):
        return attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("30 × 18 m", 30.0, 18.0))
        )

    def test_entering_a_width_makes_the_whole_floor_the_engineers(self, customer_floor):
        # The engineer changed the floor.
        edited = write_input(customer_floor, "floor_width", 28.0, ValueSource.ENGINEER, "Measured on site")

        assert floor_of(edited) == (ValueSource.ENGINEER, ValueSource.ENGINEER)
        # The untouched number is re-attributed, never re-valued.
        assert edited.floor_length.value == 18.0
        assert "floor" in (edited.floor_length.detail or "").lower()

    def test_entering_a_length_does_the_same_from_the_other_side(self, customer_floor):
        edited = write_input(customer_floor, "floor_length", 16.0, ValueSource.ENGINEER, "Measured on site")

        assert floor_of(edited) == (ValueSource.ENGINEER, ValueSource.ENGINEER)
        assert edited.floor_width.value == 30.0

    def test_clearing_one_side_claims_nothing_about_the_other(self, customer_floor):
        # There is no complete floor left to attribute.
        cleared = write_input(customer_floor, "floor_width", None, ValueSource.ENGINEER, None)

        assert cleared.floor_width.value is None
        assert cleared.floor_length.source is ValueSource.CUSTOMER

    def test_rewriting_a_value_unchanged_promotes_nothing(self, customer_floor):
        """The bulk demo fill re-writes protected values exactly as they were."""
        mixed = customer_floor.model_copy(
            update={
                "floor_length": customer_floor.floor_length.model_copy(
                    update={"source": ValueSource.EXAMPLE_DATA, "detail": "Demonstration dataset"}
                )
            }
        )
        rewritten = write_input(mixed, "floor_width", 30.0, ValueSource.CUSTOMER, mixed.floor_width.detail)

        assert rewritten.floor_length.source is ValueSource.EXAMPLE_DATA


class TestTheModalCannotDisagreeWithTheConcept:
    def test_the_resolution_plan_reports_what_the_concept_holds(self):
        """The Resolve panel and the Concept screen read one draft."""
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("18 × 30 m", 18.0, 30.0))
        )
        rows = {row.key: row for row in resolution_plan(draft).inputs}

        assert rows["floor_width"].source is draft.floor_width.source
        assert rows["floor_length"].source is draft.floor_length.source
        assert rows["floor_width"].source is rows["floor_length"].source is ValueSource.CUSTOMER

    def test_it_still_agrees_after_the_floor_is_edited(self):
        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("30 × 18 m", 30.0, 18.0))
        )
        edited = write_input(draft, "floor_width", 26.0, ValueSource.ENGINEER, "Site survey")
        rows = {row.key: row for row in resolution_plan(edited).inputs}

        assert rows["floor_width"].source is rows["floor_length"].source is ValueSource.ENGINEER

    def test_the_floor_rows_never_claim_to_block_a_simulation(self):
        # Preserved classification: the simulator reads no layout.
        draft = concept_from_brief(BRIEF)
        rows = {row.key: row for row in resolution_plan(draft).inputs}

        assert rows["floor_width"].necessity.value == "AFFECTS_LAYOUT"
        assert rows["floor_length"].necessity.value == "AFFECTS_LAYOUT"


class TestSaveAndReload:
    def test_the_pair_keeps_its_provenance_across_a_round_trip(self):
        """A project is stored as the draft's JSON and read back into it."""
        from app.models.concept import FactoryConceptDraft

        draft = attribute_sources(
            concept_from_brief(BRIEF), understanding_with(floor_statement("18 × 30 m", 18.0, 30.0))
        )
        reloaded = FactoryConceptDraft.model_validate(draft.model_dump(mode="json"))

        assert floor_of(reloaded) == (ValueSource.CUSTOMER, ValueSource.CUSTOMER)
        assert reloaded.floor_width.detail == draft.floor_width.detail
        assert reloaded.floor_length.detail == draft.floor_length.detail

    def test_an_engineer_entered_floor_survives_as_the_engineers(self):
        from app.models.concept import FactoryConceptDraft

        draft = write_input(
            concept_from_brief(BRIEF), "floor_width", 28.0, ValueSource.ENGINEER, "Measured on site"
        )
        reloaded = FactoryConceptDraft.model_validate(draft.model_dump(mode="json"))

        assert floor_of(reloaded) == (ValueSource.ENGINEER, ValueSource.ENGINEER)
