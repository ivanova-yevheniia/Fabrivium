"""Phase 13 — factory concept builder."""

from __future__ import annotations

import pytest

from app.models.concept import (
    ConceptBuffer,
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.services.concept_builder import (
    buffers_between_stages,
    concept_from_brief,
    generate_initial_layout,
    stage_id_for,
)
from app.services.concept_example_data import (
    EXAMPLE_DATASET_NAME,
    apply_example_engineering_data,
)
from app.services.concept_validation import (
    ConceptNotReadyError,
    GapSeverity,
    concept_gaps,
    concept_to_factory,
    validate_concept,
)
from app.services.constraints import validate_layout
from app.services.simulation import run_simulation

FLAGSHIP_BRIEF = (
    "We need a new electronics assembly line. "
    "The product goes through assembly, screwdriving, inspection and packaging. "
    "We need about 1,900 units per day. "
    "The available production area is 30 by 18 meters. "
    "We have eight operators. "
    "We would prefer not to buy unnecessary equipment."
)


# 1. Extraction

class TestBriefExtraction:
    def test_extracts_the_route_in_the_order_the_brief_states_it(self):
        draft = concept_from_brief(FLAGSHIP_BRIEF)
        assert [s.name for s in draft.stages] == [
            "Assembly",
            "Screwdriving",
            "Inspection",
            "Packaging",
        ]

    def test_route_order_follows_the_sentence_not_a_fixed_vocabulary_order(self):
        # Reversed in the brief: the route must reverse with it.
        draft = concept_from_brief(
            "Parts are packaged after inspection, which follows screwdriving, which follows assembly."
        )
        assert [s.name for s in draft.stages] == [
            "Packaging",
            "Inspection",
            "Screwdriving",
            "Assembly",
        ]

    def test_extracts_target_operators_and_floor_as_customer_values(self):
        draft = concept_from_brief(FLAGSHIP_BRIEF)

        assert draft.production_target.value == 1900.0
        assert draft.production_target.source is ValueSource.CUSTOMER

        assert draft.operators_available.value == 8
        assert draft.operators_available.source is ValueSource.CUSTOMER

        assert draft.floor_width.value == 30.0
        assert draft.floor_length.value == 18.0
        assert draft.floor_width.source is ValueSource.CUSTOMER

    def test_extracts_the_no_new_equipment_preference(self):
        assert concept_from_brief(FLAGSHIP_BRIEF).prefer_no_new_machines is True
        assert concept_from_brief("We need 500 units per day.").prefer_no_new_machines is False

    def test_never_invents_engineering_physics(self):
        # The single most important assertion in this file.
        draft = concept_from_brief(FLAGSHIP_BRIEF)
        for stage in draft.stages:
            assert stage.cycle_time.value is None
            assert stage.cycle_time.source is ValueSource.UNKNOWN
            assert stage.capacity.value is None
            assert stage.purchase_cost.value is None

    def test_unknown_process_words_do_not_become_stages(self):
        draft = concept_from_brief("We need 100 units per day of something.")
        assert draft.stages == []

    def test_stage_ids_are_deterministic(self):
        assert stage_id_for("Screwdriving") == "m-screwdriving"
        assert stage_id_for("Screwdriving") == stage_id_for("screwdriving")


# 2. Information gaps

class TestInformationGaps:
    def test_missing_cycle_time_blocks_simulation(self):
        draft = concept_from_brief(FLAGSHIP_BRIEF)
        result = validate_concept(draft)

        assert result.simulation_ready is False
        blocking = {g.key for g in result.blocking_gaps}
        assert "stage.m-screwdriving.cycle_time" in blocking

    def test_missing_schedule_and_workforce_block_simulation(self):
        draft = concept_from_brief(
            "Assembly then packaging. 900 units per day."
        )
        blocking = {g.key for g in validate_concept(draft).blocking_gaps}
        assert {"shifts_per_day", "hours_per_shift", "operators_available"} <= blocking

    def test_missing_price_does_not_block_simulation(self):
        # The simulator reads no price (domain audit §1).
        draft = _complete_draft()
        result = validate_concept(draft)

        assert result.simulation_ready is True
        optional = {g.key for g in result.optional_gaps}
        assert "stage.m-assembly.purchase_cost" in optional

    def test_missing_floor_size_does_not_block_simulation(self):
        draft = _complete_draft().model_copy(
            update={"floor_width": SourcedFloat.unknown(), "floor_length": SourcedFloat.unknown()}
        )
        result = validate_concept(draft)

        assert result.simulation_ready is True
        assert "floor_dimensions" in {g.key for g in result.optional_gaps}

    def test_gap_list_is_stable_and_ordered_required_first(self):
        draft = concept_from_brief(FLAGSHIP_BRIEF)
        gaps = concept_gaps(draft)

        severities = [g.severity for g in gaps]
        first_optional = severities.index(GapSeverity.OPTIONAL)
        assert all(s is GapSeverity.REQUIRED for s in severities[:first_optional])
        assert concept_gaps(draft) == gaps  # deterministic

    def test_a_buffer_naming_a_missing_stage_is_an_error_not_a_gap(self):
        draft = _complete_draft().model_copy(
            update={
                "buffers": [
                    ConceptBuffer(
                        id="buf-x",
                        name="ghost",
                        upstream_stage_id="m-assembly",
                        downstream_stage_id="m-nonexistent",
                        capacity=SourcedInt.of(50, ValueSource.CATALOG_DEFAULT),
                    )
                ]
            }
        )
        result = validate_concept(draft)
        assert result.simulation_ready is False
        assert any("m-nonexistent" in e for e in result.errors)


# 3. Example data provenance

class TestExampleData:
    def test_filled_values_are_attributed_to_the_named_dataset(self):
        draft = apply_example_engineering_data(concept_from_brief(FLAGSHIP_BRIEF))

        screwdriving = draft.stage_by_id("m-screwdriving")
        assert screwdriving is not None
        assert screwdriving.cycle_time.value == 52.0
        assert screwdriving.cycle_time.source is ValueSource.EXAMPLE_DATA
        assert screwdriving.cycle_time.detail == EXAMPLE_DATASET_NAME

    def test_customer_values_are_never_overwritten(self):
        draft = concept_from_brief(FLAGSHIP_BRIEF)
        filled = apply_example_engineering_data(draft)

        # The customer said 8 operators and 1,900/day; the dataset also has
        # figures for both. The customer's must win, and must still read as
        # theirs.
        assert filled.operators_available.value == 8
        assert filled.operators_available.source is ValueSource.CUSTOMER
        assert filled.production_target.value == 1900.0
        assert filled.production_target.source is ValueSource.CUSTOMER

    def test_a_stage_the_dataset_does_not_know_stays_a_gap(self):
        draft = concept_from_brief(
            "Assembly, welding and packaging. 1,000 units per day. Two 8-hour shifts. 6 operators."
        )
        filled = apply_example_engineering_data(draft)

        welding = filled.stage_by_id("m-welding")
        assert welding is not None
        assert welding.cycle_time.value is None
        assert "stage.m-welding.cycle_time" in {
            g.key for g in validate_concept(filled).blocking_gaps
        }

    def test_cycle_times_come_from_the_route_not_the_machine_field(self):
        # ProcessStep.cycle_time is what the simulator reads; Machine.cycle_time
        # is a fallback it never reaches. Reading the wrong one would be
        # invisible today (they agree) and wrong the moment they diverge.
        filled = apply_example_engineering_data(concept_from_brief(FLAGSHIP_BRIEF))
        factory, product_id = concept_to_factory(filled)
        product = next(p for p in factory.products if p.id == product_id)

        for step in product.route:
            machine = next(m for m in factory.machines if m.id == step.machine_id)
            assert step.cycle_time == machine.cycle_time


# 4. Conversion

class TestConversion:
    def test_refuses_to_convert_while_a_required_gap_remains(self):
        with pytest.raises(ConceptNotReadyError) as exc:
            concept_to_factory(concept_from_brief(FLAGSHIP_BRIEF))
        assert "cycle time" in str(exc.value).lower()

    def test_the_stated_target_becomes_product_demand(self):
        factory, product_id = concept_to_factory(_complete_draft())
        product = next(p for p in factory.products if p.id == product_id)
        # This is the field the existing planning pipeline reads as the goal.
        assert product.demand_per_day == 1900.0

    def test_conversion_is_deterministic(self):
        draft = _complete_draft()
        first, _ = concept_to_factory(draft)
        second, _ = concept_to_factory(draft)
        assert first.model_dump_json() == second.model_dump_json()

    def test_buffers_are_wired_so_they_actually_affect_the_simulation(self):
        factory, _ = concept_to_factory(_complete_draft())
        assert factory.buffers
        for buffer in factory.buffers:
            assert buffer.is_wired

    def test_unknown_station_footprint_uses_a_planning_default(self):
        # Machine.width/length are required by the model but never read by
        # the simulator, so a default here cannot change any KPI.
        draft = _complete_draft()
        for stage in draft.stages:
            assert stage.width.value is None
        factory, _ = concept_to_factory(draft)
        assert all(m.width > 0 and m.length > 0 for m in factory.machines)


# 5. Initial layout

class TestInitialLayout:
    def test_places_every_stage_in_route_order_along_the_line(self):
        draft = _complete_draft()
        layout = generate_initial_layout(draft)

        assert [p.machine_id for p in layout.placements] == [s.id for s in draft.stages]
        xs = [p.x for p in layout.placements]
        assert xs == sorted(xs), "route order must read left to right"

    def test_the_generated_layout_passes_the_existing_validator(self):
        draft = _complete_draft()
        factory, _ = concept_to_factory(draft)
        layout = generate_initial_layout(draft)

        result = validate_layout(factory, layout)
        assert result.error_count == 0, [v.message for v in result.violations]

    def test_layout_generation_is_deterministic(self):
        draft = _complete_draft()
        assert generate_initial_layout(draft) == generate_initial_layout(draft)

    def test_a_concept_with_no_floor_size_still_gets_a_valid_layout(self):
        draft = _complete_draft().model_copy(
            update={"floor_width": SourcedFloat.unknown(), "floor_length": SourcedFloat.unknown()}
        )
        factory, _ = concept_to_factory(draft)
        layout = generate_initial_layout(draft)
        assert validate_layout(factory, layout).error_count == 0


# 6. GOLDEN REGRESSION

class TestGoldenRegression:
    """A concept built from the customer brief must reach the frozen result."""

    def test_brief_to_baseline_reproduces_the_frozen_values(self):
        draft = apply_example_engineering_data(
            concept_from_brief(FLAGSHIP_BRIEF, name="Electronics Assembly Concept")
        )
        assert validate_concept(draft).simulation_ready is True

        factory, product_id = concept_to_factory(draft)
        result = run_simulation(factory, product_id)

        assert result.target_units == 1900
        assert result.completed_units == 1105
        assert result.demand_gap_units == 795
        assert result.demand_met is False
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    def test_the_concept_route_matches_the_demo_line(self):
        draft = apply_example_engineering_data(concept_from_brief(FLAGSHIP_BRIEF))
        factory, product_id = concept_to_factory(draft)
        product = next(p for p in factory.products if p.id == product_id)

        assert [(s.name, s.cycle_time) for s in product.route] == [
            ("Assembly", 35.0),
            ("Screwdriving", 52.0),
            ("Inspection", 30.0),
            ("Packaging", 25.0),
        ]


# Helpers

def _complete_draft() -> FactoryConceptDraft:
    """A concept with exactly the physics a simulation needs, and nothing
    commercial — so "ready to simulate" and "commercially complete" can be
    told apart in tests."""
    draft = concept_from_brief(FLAGSHIP_BRIEF)
    stages = [
        stage.model_copy(
            update={
                "cycle_time": SourcedFloat.of(cycle, ValueSource.CUSTOMER, "Stated by the engineer"),
                "capacity": SourcedInt.of(1, ValueSource.CATALOG_DEFAULT, "FactoryMind planning default"),
                "operators_required": SourcedInt.of(2, ValueSource.CUSTOMER, "Stated by the engineer"),
            }
        )
        for stage, cycle in zip(draft.stages, [35.0, 52.0, 30.0, 25.0])
    ]
    draft = draft.model_copy(
        update={
            "stages": stages,
            "shifts_per_day": SourcedInt.of(2, ValueSource.CUSTOMER, "Stated by the engineer"),
            "hours_per_shift": SourcedFloat.of(8.0, ValueSource.CUSTOMER, "Stated by the engineer"),
        }
    )
    return draft.model_copy(update={"buffers": buffers_between_stages(draft)})
