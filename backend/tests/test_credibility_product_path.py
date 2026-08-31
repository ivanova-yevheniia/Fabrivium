"""The uploaded-product path, audited the way a jury would audit it."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.product import FactStatus
from app.services.concept_example_data import EXAMPLE_DATASET_NAME
from app.services.input_adapters import ingest_pdf
from app.services.process_planning import plan_process
from app.services.product_intelligence import understand_product
from app.services.product_to_concept import concept_from_product
from app.services.requirement_coverage import (
    CoverageSeverity,
    CoverageStatus,
    coverage_for,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
PDF = ROOT / "examples" / "customer_docs" / "Compact_Electronics_Controller_Product_Specification.pdf"
DEMO_FACTORY = ROOT / "examples" / "electronics_line.json"


@pytest.fixture(scope="module")
def understanding():
    assert PDF.exists(), f"the golden specification is missing at {PDF}"
    document = ingest_pdf(PDF.read_bytes(), name=PDF.name)
    # None = no LLM. The golden path must not need one.
    return understand_product(document, None, product_name="CEC-120").understanding


@pytest.fixture(scope="module")
def draft(understanding):
    return plan_process(understanding)


@pytest.fixture(scope="module")
def demo_values() -> dict:
    data = json.loads(DEMO_FACTORY.read_text(encoding="utf-8"))
    cycles = {
        step["machine_id"]: float(step["cycle_time"])
        for product in data.get("products", [])
        for step in product.get("route", [])
    }
    return {
        "cycle_times": set(cycles.values()),
        "costs": {float(m.get("purchase_cost", 0.0)) for m in data.get("machines", [])},
        "buffer_sizes": {int(b["capacity"]) for b in data.get("buffers", [])},
        "shifts": int(data["shifts_per_day"]),
        "hours": float(data["hours_per_shift"]),
        "budget": float(data.get("budget", 0.0)),
    }


# What the document actually says

class TestExtraction:
    def test_the_stated_product_structure_is_read_out_of_the_document(self, understanding):
        facts = {f.key: f for f in understanding.facts}
        assert facts["fastener.screw.count"].quantity == 6
        assert facts["connection.cable.count"].quantity == 2
        for key in ("component.pcb", "component.lid", "component.label", "component.enclosure"):
            assert key in facts, f"{key} is stated by the document"
        assert "requirement.inspection" in facts
        assert "requirement.packaging" in facts

    def test_every_extracted_fact_cites_the_document(self, understanding):
        # A fact without a citation cannot be checked by the person who has
        # to sign off on it.
        for fact in understanding.facts:
            if fact.status is FactStatus.EXTRACTED:
                assert fact.evidence, f"{fact.key} claims extraction with no evidence"
                assert all(e.quote for e in fact.evidence)

    def test_what_the_document_does_not_say_stays_unknown(self, understanding):
        # The source states no process data at all. Nothing may appear.
        keys = {f.key for f in understanding.facts}
        for absent in ("cycle_time", "capacity", "operators", "cost", "price", "shift", "buffer"):
            assert not any(absent in key for key in keys), (
                f"the source states nothing about {absent}, so no fact may mention it"
            )


# Traceability

class TestTraceability:
    def test_every_operation_names_the_facts_that_caused_it(self, draft):
        for operation in draft.operations:
            assert operation.source_fact_keys, f"{operation.name} has no derivation"
            assert operation.basis

    def test_every_operation_carries_the_source_sentence(self, draft):
        # "Show me the sentence in the PDF that put this station here" has to
        # be answerable from the operation itself.
        for operation in draft.operations:
            assert operation.evidence, f"{operation.name} cites no document text"
            assert all(e.quote for e in operation.evidence)
            assert all(e.page is not None for e in operation.evidence)

    def test_the_screw_operation_traces_to_the_screw_sentence(self, draft):
        screwing = next(op for op in draft.operations if op.process_type == "screwdriving")
        assert screwing.repeated_operations == 6
        assert "fastener.screw.count" in screwing.source_fact_keys
        quotes = " ".join(e.quote.lower() for e in screwing.evidence)
        assert "screw" in quotes

    def test_a_deterministic_proposal_is_not_credited_to_the_ai(self, draft):
        # plan_process is a rule table and the draft records method LOCAL_RULES.
        assert draft.method == "LOCAL_RULES"
        for operation in draft.operations:
            assert operation.fact_status is FactStatus.RULE_DERIVED
            assert operation.fact_status is not FactStatus.AI_INFERRED


# Requirement coverage

class TestRequirementCoverage:
    def test_an_unanswered_requirement_is_reported_not_dropped(self, understanding, draft):
        # The document names an enclosure.
        report = coverage_for(understanding, draft)
        unresolved = {item.fact_key for item in report.unresolved}
        assert "component.enclosure" in unresolved

    def test_an_unanswered_requirement_keeps_its_source_evidence(self, understanding, draft):
        report = coverage_for(understanding, draft)
        item = next(i for i in report.unresolved if i.fact_key == "component.enclosure")
        assert item.evidence
        assert item.severity is CoverageSeverity.CRITICAL

    def test_addressed_requirements_name_the_operation_that_answers_them(
        self, understanding, draft
    ):
        report = coverage_for(understanding, draft)
        screws = next(i for i in report.items if i.fact_key == "fastener.screw.count")
        assert screws.status is CoverageStatus.ADDRESSED
        assert any("Screw fastening" in name for name in screws.addressed_by)

    def test_a_critical_unresolved_requirement_blocks_approval(self, understanding, draft):
        report = coverage_for(understanding, draft)
        assert report.approval_blocked is True
        assert not report.complete

    def test_product_description_is_not_treated_as_a_requirement(self, understanding, draft):
        # A material or a dimension implies no operation, so it can never be
        # "unresolved". Counting it would manufacture a permanent false gap.
        report = coverage_for(understanding, draft)
        for key in ("material.enclosure", "dimensions.overall"):
            item = next(i for i in report.items if i.fact_key == key)
            assert item.status is CoverageStatus.NOT_A_REQUIREMENT

    def test_coverage_is_not_reported_as_a_pass_mark(self, understanding, draft):
        # A percentage invites "91% — good enough" and lets one unaddressed
        # "shall" hide behind ten addressed conveniences.
        report = coverage_for(understanding, draft)
        assert "%" not in report.summary()


# Information leakage — the mandatory one

class TestNoDemoDataLeakage:
    def test_no_demo_cycle_time_reaches_the_concept(self, understanding, draft, demo_values):
        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        concept = concept_from_product(
            understanding,
            accepted,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            # These tests are about leakage, not coverage.
            allow_unresolved_requirements=True,
        )
        for stage in concept.stages:
            assert stage.cycle_time.value is None, (
                f"{stage.name} arrived with a cycle time the document never stated"
            )

    def test_no_demo_cost_or_budget_reaches_the_concept(self, understanding, draft, demo_values):
        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        concept = concept_from_product(
            understanding,
            accepted,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            # These tests are about leakage, not coverage.
            allow_unresolved_requirements=True,
        )
        assert concept.budget.value is None
        for stage in concept.stages:
            assert stage.purchase_cost.value is None

    def test_no_demo_schedule_reaches_the_concept(self, understanding, draft, demo_values):
        # The document states no shift pattern.
        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        concept = concept_from_product(
            understanding,
            accepted,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            # These tests are about leakage, not coverage.
            allow_unresolved_requirements=True,
        )
        assert concept.shifts_per_day.value is None
        assert concept.hours_per_shift.value is None

    def test_the_demo_dataset_is_never_named_on_this_path(self, understanding, draft):
        blob = understanding.model_dump_json() + draft.model_dump_json()
        assert EXAMPLE_DATASET_NAME not in blob

    def test_customer_boundary_conditions_do_come_through(self, understanding, draft):
        # The counterpart to leakage: what the customer DID state must
        # survive, or the test above would pass on an empty concept.
        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        concept = concept_from_product(
            understanding,
            accepted,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            # These tests are about leakage, not coverage.
            allow_unresolved_requirements=True,
        )
        assert concept.production_target.value == 1900
        assert concept.operators_available.value == 8
        assert concept.floor_width.value in (30.0, 18.0)


# The process itself

class TestProposedProcess:
    def test_the_document_produces_a_plausible_route(self, draft):
        types = [op.process_type for op in draft.operations]
        # Not an exact-wording assertion: several decompositions are valid.
        assert "screwdriving" in types
        assert "inspection" in types
        assert "packaging" in types
        assert types.count("assembly") >= 2

    def test_inspection_appears_only_because_the_document_asks_for_it(self, understanding, draft):
        inspection = next(op for op in draft.operations if op.process_type == "inspection")
        assert "requirement.inspection" in inspection.source_fact_keys

    def test_no_operation_is_accepted_without_an_engineer(self, draft):
        from app.models.process_draft import OperationStatus

        assert all(op.status is OperationStatus.PROPOSED for op in draft.operations)


# The approval gate

class TestApprovalGate:
    """A stated requirement with nothing behind it must not pass silently."""

    def test_building_is_refused_while_a_stated_requirement_is_unanswered(
        self, understanding, draft
    ):
        from app.services.product_to_concept import RequirementsUnresolvedError

        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        with pytest.raises(RequirementsUnresolvedError) as raised:
            concept_from_product(
                understanding, accepted, "1,900 units per day. 30 by 18 meters. 8 operators."
            )
        # The message has to name what is missing, or the engineer cannot act.
        assert "Enclosure" in str(raised.value)

    def test_adding_the_missing_operation_unblocks_the_build(self, understanding, draft):
        from app.services.process_editing import add_operation, link_to_requirements
        from app.services.requirement_coverage import coverage_for

        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        resolved = add_operation(
            accepted,
            name="Enclosure handling",
            process_type="assembly",
            basis="The specification requires the unit to be assembled into its enclosure.",
            source_fact_keys=["component.enclosure"],
        )
        still_open = [i.fact_key for i in coverage_for(understanding, resolved).unresolved]
        resolved = link_to_requirements(resolved, resolved.operations[0].id, still_open)

        report = coverage_for(understanding, resolved)
        assert report.complete
        assert report.approval_blocked is False

        # And the build now succeeds without the override.
        concept = concept_from_product(
            understanding, resolved, "1,900 units per day. 30 by 18 meters. 8 operators."
        )
        assert any("Enclosure handling" in stage.name for stage in concept.stages)

    def test_an_explicit_override_is_possible_but_never_the_default(self, understanding, draft):
        # "We know, and we are proceeding" is a legitimate engineering position.
        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        concept = concept_from_product(
            understanding,
            accepted,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            allow_unresolved_requirements=True,
        )
        assert concept.stages


class TestEngineerOverridesTheProcess:
    def test_an_added_operation_is_stated_not_rule_derived(self, draft):
        from app.services.process_editing import add_operation

        edited = add_operation(
            draft, name="Label application", process_type="assembly", basis="Spec requires a label."
        )
        added = edited.operations[-1]
        assert added.fact_status is FactStatus.STATED
        assert added.fact_status is not FactStatus.RULE_DERIVED

    def test_an_edit_keeps_the_original_proposal_visible(self, draft):
        from app.services.process_editing import edit_operation

        original = draft.operations[0]
        edited = edit_operation(draft, original.id, basis="Measured on the pilot cell")
        changed = edited.operations[0]

        assert "engineer edit" in changed.basis
        assert original.basis in changed.basis
        assert changed.status.value == "MODIFIED"

    def test_a_removed_operation_is_rejected_not_deleted(self, draft):
        from app.services.process_editing import remove_operation

        removed = remove_operation(draft, draft.operations[0].id)
        assert len(removed.operations) == len(draft.operations)
        assert removed.operations[0].status.value == "REJECTED"

    def test_an_operation_needs_a_stated_reason(self, draft):
        from app.services.process_editing import add_operation

        with pytest.raises(ValueError, match="reason"):
            add_operation(draft, name="Mystery step", process_type="assembly", basis="   ")

    def test_an_engineer_edit_survives_into_the_concept(self, understanding, draft):
        # MODIFIED must count as accepted, or the engineer's own correction
        # is silently dropped from the built concept.
        from app.services.process_editing import edit_operation

        accepted = draft.model_copy(update={"operations": [o.accept() for o in draft.operations]})
        renamed = edit_operation(accepted, accepted.operations[0].id, name="PCB load and place")
        concept = concept_from_product(
            understanding,
            renamed,
            "1,900 units per day. 30 by 18 meters. 8 operators.",
            allow_unresolved_requirements=True,
        )
        assert any(stage.name == "PCB load and place" for stage in concept.stages)
