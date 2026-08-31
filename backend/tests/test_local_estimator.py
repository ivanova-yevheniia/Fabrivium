"""Phase 18B — the deterministic estimator and its reference data."""

from __future__ import annotations

import pytest

from app.data.engineering_reference_data import (
    AUTOMATION_FACTORS,
    PROCESS_PROFILES,
    SANITY_CHECKS,
    ReferenceClass,
    covered_categories,
    profile_for,
)
from app.models.uncertainty import Confidence, EstimateMethod
from app.services.local_estimator import (
    MissingInformation,
    count_operations,
    detect_contradiction,
    estimate,
)


# Reference data is declared, not assumed

class TestReferenceData:
    @pytest.mark.parametrize("category", covered_categories())
    def test_every_band_declares_its_provenance(self, category):
        profile = PROCESS_PROFILES[category]
        for band in (profile.handling, profile.per_operation):
            assert band.meaning
            assert band.unit == "s"
            assert band.rationale
            assert band.applicability
            assert isinstance(band.source_class, ReferenceClass)

    def test_nothing_claims_to_be_an_industry_standard(self):
        # Every constant is either from our own bundled dataset or our own
        # stated assumption. Presenting either as a standard would be the
        # easiest lie in this whole feature.
        for profile in PROCESS_PROFILES.values():
            for band in (profile.handling, profile.per_operation):
                assert band.source_class in (
                    ReferenceClass.REFERENCE_DATASET,
                    ReferenceClass.STATED_ASSUMPTION,
                )

    @pytest.mark.parametrize("category,operations,dataset_value", SANITY_CHECKS)
    def test_the_composed_band_contains_the_dataset_value(self, category, operations, dataset_value):
        """The anchor. Composition must span the one real number we have."""
        result = estimate(
            process_category=category,
            description="",
            automation_level="MANUAL",
            operations_per_unit=operations,
        )
        assert not isinstance(result, MissingInformation)
        assert result.low <= dataset_value <= result.high, (
            f"{category}: composed {result.low}-{result.high} s does not contain the "
            f"dataset's {dataset_value} s"
        )

    def test_automation_factors_are_ordered(self):
        manual = AUTOMATION_FACTORS["MANUAL"]
        assisted = AUTOMATION_FACTORS["ASSISTED"]
        automatic = AUTOMATION_FACTORS["AUTOMATIC"]
        # A machine should not be slower than a hand tool in this model.
        assert automatic.high <= assisted.high <= manual.high

    def test_uncovered_families_have_no_profile(self):
        # Eight of the twelve families the concept builder recognises are
        # deliberately absent rather than extrapolated.
        for absent in ("welding", "soldering", "painting", "machining"):
            assert profile_for(absent) is None


# Composition

class TestComposition:
    def test_more_operations_produce_a_longer_cycle(self):
        few = estimate(process_category="screwdriving", description="", automation_level="MANUAL", operations_per_unit=2)
        many = estimate(process_category="screwdriving", description="", automation_level="MANUAL", operations_per_unit=8)
        assert many.low > few.low and many.high > few.high

    def test_automation_shortens_the_operation_part(self):
        manual = estimate(process_category="screwdriving", description="", automation_level="MANUAL", operations_per_unit=6)
        auto = estimate(process_category="screwdriving", description="", automation_level="AUTOMATIC", operations_per_unit=6)
        assert auto.high < manual.high

    def test_an_unstated_automation_level_widens_rather_than_shifts(self):
        known = estimate(process_category="screwdriving", description="", automation_level="MANUAL", operations_per_unit=6)
        unknown = estimate(process_category="screwdriving", description="", automation_level="UNKNOWN", operations_per_unit=6)
        # Not knowing should make the answer less precise, not differently
        # precise: the top stays put and the bottom drops.
        assert unknown.high == known.high
        assert unknown.low < known.low

    def test_the_basis_states_the_arithmetic(self):
        result = estimate(
            process_category="screwdriving", description="", automation_level="ASSISTED", operations_per_unit=6
        )
        assert "handling" in result.basis
        assert "6 ×" in result.basis
        assert "assisted factor" in result.basis
        # And says whose assumptions these are.
        assert "not an industry standard" in result.basis

    def test_the_method_is_recorded_as_local(self):
        result = estimate(process_category="packaging", description="", automation_level="MANUAL", operations_per_unit=2)
        assert result.method is EstimateMethod.LOCAL_HEURISTIC
        assert result.model_name is None

    def test_confidence_is_never_high(self):
        # The bands are our own assumptions anchored to a single demo dataset.
        for level in ("MANUAL", "ASSISTED", "AUTOMATIC", "UNKNOWN"):
            result = estimate(
                process_category="assembly", description="", automation_level=level, operations_per_unit=3
            )
            assert result.confidence in (Confidence.LOW, Confidence.MEDIUM)

    def test_a_stated_count_earns_more_confidence_than_an_inferred_one(self):
        stated = estimate(
            process_category="screwdriving", description="", automation_level="MANUAL", operations_per_unit=6
        )
        inferred = estimate(
            process_category="screwdriving", description="drive the screws", automation_level="MANUAL",
            operations_per_unit=None,
        )
        assert stated.confidence is Confidence.MEDIUM
        assert inferred.confidence is Confidence.LOW

    def test_the_working_value_sits_inside_the_range(self):
        result = estimate(process_category="inspection", description="", automation_level="MANUAL", operations_per_unit=1)
        assert result.low <= result.working_value <= result.high


# Reading the description

class TestOperationCounting:
    def test_a_numeral_multiplies_its_operation(self):
        assert count_operations("drive six screws into the housing", "screwdriving") == 6

    def test_distinct_actions_are_counted_separately(self):
        # "place PCB, connect two cables, close the enclosure" = 1 + 2 + 1.
        assert count_operations(
            "place PCB into housing, connect two cables and close the enclosure", "assembly"
        ) == 4

    def test_no_recognised_action_returns_none_not_zero(self):
        # An absent count is not a count of zero, and the caller treats the
        # two differently.
        assert count_operations("something happens", "assembly") is None

    def test_an_uncovered_family_counts_nothing(self):
        assert count_operations("weld two brackets", "welding") is None

    # An outright statement of repetition These exist because FactoryMind's OWN
    # generated description defeated the proximity reading.

    def test_a_stated_repetition_is_read_from_factorymind_s_own_phrasing(self):
        assert count_operations(
            "Screw fastening, 6 times per unit, implied by screws.", "screwdriving"
        ) == 6

    def test_it_reads_the_shorthand_an_engineer_types(self):
        assert count_operations("Screw fastening 6x", "screwdriving") == 6
        assert count_operations("Screw fastening 6 ×", "screwdriving") == 6

    def test_a_written_number_states_a_repetition_too(self):
        assert count_operations("cable connection, two times per unit", "assembly") == 2

    def test_a_dimension_is_not_a_repetition(self):
        """The trap this rule had to avoid."""
        assert count_operations("Enclosure 120 x 80 x 35 mm", "screwdriving") is None
        assert count_operations(
            "PCB placement, implied by pcb. Product dimensions 120 x 80 x 35 mm", "assembly"
        ) == 1

    def test_an_explicit_count_still_wins_over_the_stated_phrase(self):
        """The caller's own number is not overridden by anything in the text."""
        result = estimate(
            description="Screw fastening, 6 times per unit, implied by screws.",
            process_category="screwdriving",
            automation_level="MANUAL",
            operations_per_unit=2,
        )
        assert not isinstance(result, MissingInformation)
        assert result.basis.startswith("Local engineering heuristic")
        assert "2 " in result.basis and "6 " not in result.basis.split(".")[0]

    def test_the_stated_phrase_reaches_the_band_when_the_caller_gives_none(self):
        """End to end: the six-screw band, not the one-screw band."""
        six = estimate(
            description="Screw fastening, 6 times per unit, implied by screws.",
            process_category="screwdriving",
            automation_level="MANUAL",
            operations_per_unit=None,
        )
        one = estimate(
            description="Screw fastening, implied by screws.",
            process_category="screwdriving",
            automation_level="MANUAL",
            operations_per_unit=None,
        )
        assert not isinstance(six, MissingInformation)
        assert not isinstance(one, MissingInformation)
        assert six.working_value > one.working_value * 2


# Contradictions

class TestContradictionDetection:
    def test_manual_wording_against_automatic_selection_is_flagged(self):
        found = detect_contradiction("Manual assembly of an enclosure", "AUTOMATIC")
        assert found is not None
        assert found.described_as == "MANUAL"
        assert found.selected_as == "AUTOMATIC"

    def test_robot_wording_against_manual_selection_is_flagged(self):
        found = detect_contradiction("A robot places the PCB into the housing", "MANUAL")
        assert found is not None
        assert found.described_as == "AUTOMATIC"

    def test_agreement_is_not_flagged(self):
        assert detect_contradiction("Manual assembly of an enclosure", "MANUAL") is None

    def test_assisted_cannot_contradict(self):
        # ASSISTED sits legitimately between the two readings.
        assert detect_contradiction("Manual assembly of an enclosure", "ASSISTED") is None

    def test_unknown_cannot_contradict(self):
        assert detect_contradiction("A robot places the PCB", "UNKNOWN") is None

    def test_a_vague_description_is_not_flagged(self):
        # Noisy warnings on ambiguous text would train the engineer to
        # dismiss the one that matters.
        assert detect_contradiction("Assembly of an electronics enclosure", "AUTOMATIC") is None

    def test_a_description_containing_both_readings_is_not_flagged(self):
        # "manual loading of an automatic station" is a real sentence, not a
        # contradiction, and low-confidence cases must stay silent.
        assert detect_contradiction(
            "Manual loading of an automatic screwdriving station", "AUTOMATIC"
        ) is None


# Refusal

class TestRefusal:
    def test_an_uncovered_family_asks_instead_of_extrapolating(self):
        result = estimate(
            process_category="welding", description="Weld two brackets", automation_level="MANUAL",
            operations_per_unit=2,
        )
        assert isinstance(result, MissingInformation)
        assert "no engineering reference data" in result.reason
        assert result.questions

    def test_too_little_information_asks_specific_questions(self):
        result = estimate(
            process_category="assembly", description="Work happens", automation_level="UNKNOWN",
            operations_per_unit=None,
        )
        assert isinstance(result, MissingInformation)
        # Specific, because "not enough information" alone leaves the
        # engineer nowhere to go.
        assert any("how many" in q.lower() for q in result.questions)
        assert any("manual" in q.lower() and "automatic" in q.lower() for q in result.questions)

    def test_an_automation_level_alone_is_enough_to_proceed(self):
        result = estimate(
            process_category="assembly", description="Work happens", automation_level="MANUAL",
            operations_per_unit=None,
        )
        assert not isinstance(result, MissingInformation)
