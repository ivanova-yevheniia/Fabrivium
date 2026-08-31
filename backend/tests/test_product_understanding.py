"""Phase 19 — product understanding and process planning."""

from __future__ import annotations

import io
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.llm.errors import LLMAuthenticationError, LLMMalformedResponseError
from app.main import app
from app.models.process_draft import ManufacturingProcessDraft, OperationStatus
from app.models.product import FactStatus, ProductFact, ProductUnderstanding
from app.services.concept_validation import concept_to_factory, validate_concept
from app.services.estimation import (
    AutomationLevel,
    EstimationMode,
    EstimationRequest,
    propose_station_assumptions,
)
from app.services.input_adapters import UnsupportedDocument, ingest, ingest_pdf, ingest_text
from app.services.process_planning import draft_to_stages, plan_process
from app.services.product_extraction import extract_facts, gaps_for
from app.services.product_intelligence import understand_product
from app.services.product_to_concept import (
    ProcessNotAcceptedError,
    concept_from_product,
    describe_for_estimator,
    concept_from_product as build_concept,
    station_context,
)
from app.services.simulation import run_simulation

REFERENCE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app" / "data" / "electronics_controller_reference_product.txt"
)
REQUIREMENTS = (
    "We need about 1,900 units per day across 2 shifts of 8 hours. The available production "
    "area is 30 by 18 meters. We have eight operators. We would prefer not to buy unnecessary "
    "equipment."
)


@pytest.fixture
def reference_text() -> str:
    return REFERENCE.read_text(encoding="utf-8")


@pytest.fixture
def understanding(reference_text) -> ProductUnderstanding:
    return understand_product(
        ingest_text(reference_text, name="reference.txt"), None,
        product_name="Compact electronics controller",
    ).understanding


@pytest.fixture
def accepted_process(understanding) -> ManufacturingProcessDraft:
    """A process an engineer has actually finished reviewing."""
    from app.services.process_editing import link_to_requirements
    from app.services.requirement_coverage import coverage_for

    draft = plan_process(understanding)
    draft = draft.model_copy(update={"operations": [op.accept() for op in draft.operations]})

    unresolved = [item.fact_key for item in coverage_for(understanding, draft).unresolved]
    if unresolved:
        # The first assembly operation is the one that receives the parts and
        # carries the labelling in this simplified route.
        target = next(op for op in draft.operations if op.process_type == "assembly")
        draft = link_to_requirements(draft, target.id, unresolved)
    return draft


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class Quota:
    """The account's real state."""

    provider_name, model_name = "watsonx", "granite"

    def generate_structured(self, *args, **kwargs):
        raise LLMAuthenticationError("HTTP 403 token_quota_reached")


# Input adapters

class TestIngestion:
    def test_text_ingestion_needs_nothing(self):
        result = ingest_text("A plastic enclosure with six screws.", name="d.txt")
        assert result.has_text
        assert result.evidence[0].page is None

    def test_a_pdf_is_read_page_by_page(self, reference_text):
        fitz = pytest.importorskip("fitz")
        document = fitz.open()
        for chunk in (reference_text[:1200], reference_text[1200:2400]):
            page = document.new_page()
            page.insert_textbox(fitz.Rect(40, 40, 550, 780), chunk, fontsize=9)
        payload = document.tobytes()
        document.close()

        result = ingest_pdf(payload, name="spec.pdf")

        assert result.pages == 2
        assert result.has_text
        assert [e.page for e in result.evidence] == [1, 2]

    def test_a_page_without_text_is_reported_not_guessed(self):
        fitz = pytest.importorskip("fitz")
        document = fitz.open()
        document.new_page()  # blank: a scan or a drawing
        payload = document.tobytes()
        document.close()

        result = ingest_pdf(payload, name="drawing.pdf")

        assert result.pages_without_text == [1]
        assert any("not interpreted in this version" in n for n in result.notes)
        # Crucially, nothing was invented to fill the page.
        assert not result.has_text

    def test_a_file_that_is_not_a_pdf_is_refused_by_content(self):
        # Named .pdf, but the bytes say otherwise.
        with pytest.raises(UnsupportedDocument, match="not a PDF"):
            ingest_pdf(b"\x89PNG\r\n\x1a\n rest of a png", name="drawing.pdf")

    def test_an_unreadable_binary_is_refused_with_a_reason(self):
        with pytest.raises(UnsupportedDocument) as exc:
            ingest(b"\x00\x01\x02\xff\xfe", name="model.step")
        assert "CAD are not read" in str(exc.value)

    def test_an_oversized_document_is_refused(self):
        from app.services.input_adapters import MAX_DOCUMENT_BYTES

        payload = b"%PDF-" + b"0" * (MAX_DOCUMENT_BYTES + 1)
        with pytest.raises(UnsupportedDocument, match="limit"):
            ingest_pdf(payload, name="huge.pdf")


# Deterministic extraction

class TestExtraction:
    def test_the_reference_document_yields_the_expected_facts(self, understanding):
        assert understanding.fact("fastener.screw.count").quantity == 6
        assert understanding.fact("connection.cable.count").quantity == 2
        assert understanding.fact("material.enclosure").value == "ABS"
        assert understanding.fact("dimensions.overall").value == "120 × 80 × 40 mm"
        assert understanding.fact("component.pcb").known
        assert understanding.fact("requirement.inspection").known

    def test_every_extracted_fact_cites_a_sentence(self, understanding):
        for fact in understanding.facts:
            if fact.status is FactStatus.EXTRACTED:
                assert fact.evidence, f"{fact.key} claims EXTRACTED with no evidence"
                assert fact.evidence[0].quote

    def test_a_negated_material_is_not_extracted(self):
        # "No metal housing parts are used" was extracted as material=Metal
        # in the first live run — a fact taken from a sentence asserting its
        # opposite, arriving with a citation that contradicts it.
        facts = extract_facts(ingest_text("No metal parts are used.", name="d").evidence)
        assert not any(f.key == "material.enclosure" for f in facts)

    def test_negation_does_not_reach_past_a_conjunction(self):
        facts = extract_facts(
            ingest_text("The lid is ABS, and no metal is used.", name="d").evidence
        )
        material = next(f for f in facts if f.key == "material.enclosure")
        assert material.value == "ABS"

    def test_a_specific_material_supersedes_its_family(self):
        # "plastic enclosure" in one section and "moulded in ABS" in another
        # is one source being more precise, not two sources disagreeing.
        facts = extract_facts(
            ingest_text("A plastic enclosure. The enclosure is moulded in ABS.", name="d").evidence
        )
        material = next(f for f in facts if f.key == "material.enclosure")
        assert material.status is FactStatus.EXTRACTED
        assert material.value == "ABS"

    def test_genuinely_conflicting_counts_are_kept_unresolved(self):
        facts = extract_facts(
            [
                *ingest_text("The lid is secured with six screws.", name="drawing.pdf").evidence,
                *ingest_text("Fasteners: 8 screws per unit.", name="bom.txt").evidence,
            ]
        )
        screws = next(f for f in facts if f.key == "fastener.screw.count")

        # FactoryMind is not better placed than the engineer to know which
        # document is right, so it keeps both.
        assert screws.status is FactStatus.CONFLICT
        assert screws.value is None
        assert {a.value for a in screws.alternatives} == {"6", "8"}

    def test_unknown_carries_no_value(self):
        with pytest.raises(ValueError, match="UNKNOWN but carries a value"):
            ProductFact(key="k", category="c", label="L", value="6", status=FactStatus.UNKNOWN)

    def test_extracted_without_evidence_is_rejected(self):
        with pytest.raises(ValueError, match="cites no evidence"):
            ProductFact(key="k", category="c", label="L", value="6", status=FactStatus.EXTRACTED)


# Information gaps

class TestGaps:
    def test_no_product_gap_blocks_concept_simulation(self, understanding):
        # The simulator reads no product fact, so none may block it.
        for gap in understanding.information_gaps:
            assert gap.severity != "BLOCKS_CONCEPT_SIMULATION"

    def test_the_screw_gap_names_what_is_missing_and_claims_no_more_than_it_should(
        self, understanding
    ):
        # This gap used to be called "Screw type and thread — Blocks equipment
        # selection", and it was wrong twice over.
        gap = next(
            g for g in understanding.information_gaps if g.key == "fastener.screw.drive_torque"
        )
        assert gap.severity == "LIMITS_EQUIPMENT_VALIDATION"
        assert "drive type" in gap.label and "fastening torque" in gap.label

    def test_a_stated_thread_is_not_reported_as_unknown(self):
        # The defect this replaces: a source stating "6 x M3 screws" was told
        # its thread was unknown, on a screen that quoted the M3 back on the
        # line above.
        facts = extract_facts(
            ingest_text("The lid is secured with six M3 screws.", name="s.txt").evidence
        )
        thread = next(f for f in facts if f.key == "fastener.screw.thread")
        assert thread.value == "M3"

        gap = next(g for g in gaps_for(facts) if g.key == "fastener.screw.drive_torque")
        assert "thread" not in gap.label
        assert "drive type" in gap.label and "fastening torque" in gap.label

    def test_gaps_are_not_duplicated_per_key(self, understanding):
        keys = [g.key for g in understanding.information_gaps]
        assert len(keys) == len(set(keys))


# The provider matrix (§29)

class TestProviderMatrix:
    def _ingested(self, reference_text):
        return ingest_text(reference_text, name="reference.txt")

    def test_a_model_adds_facts_without_overwriting_extracted_ones(self, reference_text):
        class Granite:
            provider_name, model_name = "watsonx", "ibm/granite-3-8b-instruct"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "facts": [
                            # Tries to overwrite a fact the extractor cited.
                            {"key": "fastener.screw.count", "label": "Screws",
                             "category": "quantity", "value": "99", "quantity": 99},
                            {"key": "component.terminal", "label": "External terminals",
                             "category": "component", "value": "present"},
                        ]
                    }

                return R()

        outcome = understand_product(self._ingested(reference_text), Granite())

        assert outcome.model_used is True
        # The cited reading wins. A model paraphrasing the document is not the document.
        assert outcome.understanding.fact("fastener.screw.count").quantity == 6
        assert outcome.understanding.fact("fastener.screw.count").status is FactStatus.EXTRACTED
        # What it genuinely added is kept, and marked as inference.
        added = outcome.understanding.fact("component.terminal")
        assert added.status is FactStatus.AI_INFERRED
        assert added.status is not FactStatus.EXTRACTED

    def test_quota_exhaustion_leaves_the_deterministic_facts_intact(self, reference_text):
        outcome = understand_product(self._ingested(reference_text), Quota())

        assert outcome.model_used is False
        assert outcome.understanding.interpretation_method == "DOCUMENT_EXTRACTION"
        assert outcome.understanding.fact("fastener.screw.count").quantity == 6
        assert "token_quota_reached" in (outcome.provider_note or "")

    def test_a_malformed_model_response_falls_back_safely(self, reference_text):
        class Malformed:
            provider_name, model_name = "watsonx", "granite"

            def generate_structured(self, *args, **kwargs):
                raise LLMMalformedResponseError("not JSON")

        outcome = understand_product(self._ingested(reference_text), Malformed())

        assert outcome.model_used is False
        assert outcome.understanding.fact("fastener.screw.count").quantity == 6

    def test_an_unusable_model_fact_is_dropped_not_repaired(self, reference_text):
        class Partly:
            provider_name, model_name = "watsonx", "granite"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "facts": [
                            {"key": "", "label": "", "category": ""},  # unusable
                            {"key": "component.gasket", "label": "Gasket", "category": "component",
                             "value": "present"},
                        ]
                    }

                return R()

        outcome = understand_product(self._ingested(reference_text), Partly())

        # One bad entry must not cost the whole response.
        assert outcome.understanding.fact("component.gasket") is not None

    def test_local_only_mode_never_calls_the_provider(self, reference_text):
        class Exploding:
            provider_name, model_name = "x", "x"

            def generate_structured(self, *args, **kwargs):
                raise AssertionError("the provider must not be consulted in LOCAL_ONLY mode")

        outcome = understand_product(
            self._ingested(reference_text), Exploding(), mode=EstimationMode.LOCAL_ONLY
        )
        assert outcome.model_used is False

    def test_the_document_reaches_the_prompt_as_delimited_data(self, reference_text):
        seen: dict[str, str] = {}

        class Capturing:
            provider_name, model_name = "watsonx", "granite"

            def generate_structured(self, request, response_model=None):
                seen["system"] = request.system_prompt
                seen["user"] = request.user_prompt
                class R:
                    parsed = {"facts": []}
                return R()

        understand_product(self._ingested(reference_text), Capturing())

        assert "<<<PRODUCT_DOCUMENT>>>" in seen["user"]
        assert "must be ignored" in seen["system"]
        assert "untrusted" in seen["system"]



class TestProcessPlanning:
    def test_the_route_is_derived_from_the_facts(self, understanding):
        draft = plan_process(understanding)
        names = [op.name for op in draft.operations]

        # Closure precedes the fastening that secures it — the source says
        # the screws hold the lid, so the lid goes on first. See
        # `process_planning._order_by_precedence`.
        assert names == [
            "PCB placement",
            "Cable connection ×2",
            "Enclosure closure",
            "Screw fastening ×6",
            "Product labelling",
            "Visual inspection",
            "Packaging",
        ]

    def test_removing_a_fact_removes_its_operation(self, understanding):
        # The proof that this is derivation and not a hard-coded demo route.
        without_screws = understanding.model_copy(
            update={"facts": [f for f in understanding.facts if f.key != "fastener.screw.count"]}
        )
        draft = plan_process(without_screws)
        assert not any(op.process_type == "screwdriving" for op in draft.operations)

    def test_the_repeat_count_follows_the_fact(self, understanding):
        facts = [
            f.model_copy(update={"value": "4", "quantity": 4.0})
            if f.key == "fastener.screw.count"
            else f
            for f in understanding.facts
        ]
        draft = plan_process(understanding.model_copy(update={"facts": facts}))
        screwdriving = next(op for op in draft.operations if op.process_type == "screwdriving")

        assert screwdriving.repeated_operations == 4
        assert "×4" in screwdriving.name

    def test_every_operation_says_why_it_exists(self, understanding):
        for operation in plan_process(understanding).operations:
            assert operation.basis
            assert operation.source_fact_keys
            assert operation.evidence

    def test_a_conflicting_count_does_not_get_silently_resolved(self):
        facts = extract_facts(
            [
                *ingest_text("The lid is secured with six screws.", name="a.pdf").evidence,
                *ingest_text("Fasteners: 8 screws per unit.", name="b.txt").evidence,
            ]
        )
        draft = plan_process(ProductUnderstanding(facts=facts))
        screwdriving = next(op for op in draft.operations if op.process_type == "screwdriving")

        # The operation exists either way; how many times it happens is not
        # settled, and the planner says so rather than picking one.
        assert screwdriving.repeated_operations is None
        assert any("disagree" in q for q in draft.open_questions)

    def test_a_proposal_is_never_born_accepted(self, understanding):
        for operation in plan_process(understanding).operations:
            assert operation.status is OperationStatus.PROPOSED
            # RULE_DERIVED, not AI_INFERRED: plan_process is a rule table and
            # no model is involved. Crediting the AI with deterministic work
            # is the error a reviewer is most entitled to object to.
            assert operation.fact_status is FactStatus.RULE_DERIVED

    def test_accepting_sets_both_fields_together(self, understanding):
        # `model_copy` does not re-run validators, so the invariant is kept
        # by making the inconsistent state unreachable rather than by
        # catching it afterwards.
        operation = plan_process(understanding).operations[0].accept()

        assert operation.status is OperationStatus.ACCEPTED
        assert operation.fact_status is FactStatus.ENGINEER_VERIFIED

    def test_constructing_an_inconsistent_operation_is_rejected(self, understanding):
        proposed = plan_process(understanding).operations[0]
        with pytest.raises(ValueError, match="ACCEPTED but still marked AI_INFERRED"):
            type(proposed)(
                **{**proposed.model_dump(), "status": OperationStatus.ACCEPTED,
                   "fact_status": FactStatus.AI_INFERRED}
            )

    def test_the_draft_carries_no_simulation_fields(self, understanding):
        # The rival-model risk the audit named.
        from app.models.process_draft import ProposedOperation

        for forbidden in ("cycle_time", "capacity", "operators_required", "throughput"):
            assert forbidden not in ProposedOperation.model_fields
            assert forbidden not in ManufacturingProcessDraft.model_fields


# Editing

class TestProcessEditing:
    def test_operations_can_be_reordered(self, understanding):
        draft = plan_process(understanding)
        reversed_ops = list(reversed(draft.operations))
        edited = draft.model_copy(update={"operations": reversed_ops})
        assert [op.id for op in edited.operations] == [op.id for op in reversed_ops]

    def test_a_rejected_operation_does_not_reach_the_concept(self, understanding):
        draft = plan_process(understanding)
        operations = []
        for op in draft.operations:
            operations.append(op.reject() if op.process_type == "packaging" else op.accept())
        edited = draft.model_copy(update={"operations": operations})

        stages = draft_to_stages(edited)
        assert not any(s["process_type"] == "packaging" for s in stages)

    def test_building_refuses_while_operations_are_unreviewed(self, understanding):
        draft = plan_process(understanding)
        with pytest.raises(ProcessNotAcceptedError, match="No manufacturing operations"):
            concept_from_product(understanding, draft, REQUIREMENTS)

    def test_building_refuses_with_a_partly_reviewed_draft(self, understanding):
        draft = plan_process(understanding)
        first, *rest = draft.operations
        partly = draft.model_copy(
            update={
                "operations": [
                    first.accept(),
                    *rest,
                ]
            }
        )
        with pytest.raises(ProcessNotAcceptedError, match="still unreviewed"):
            concept_from_product(understanding, partly, REQUIREMENTS)


# Into the existing core

class TestConceptIntegration:
    def test_the_concept_uses_the_existing_type(self, understanding, accepted_process):
        from app.models.concept import FactoryConceptDraft

        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        assert isinstance(draft, FactoryConceptDraft)
        assert len(draft.stages) == 7

    def test_production_requirements_come_from_the_existing_extractor(
        self, understanding, accepted_process
    ):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)

        assert draft.production_target.value == 1900
        assert draft.operators_available.value == 8
        assert draft.floor_width.value == 30
        assert draft.prefer_no_new_machines is True

    def test_every_simulation_parameter_starts_unknown(self, understanding, accepted_process):
        # Phase 19 decides which operations exist.
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        for stage in draft.stages:
            assert stage.cycle_time.value is None
            assert stage.capacity.value is None
            assert stage.operators_required.value is None

    def test_the_concept_is_not_simulation_ready_until_18b_fills_it(
        self, understanding, accepted_process
    ):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        validation = validate_concept(draft)

        assert validation.simulation_ready is False
        # Fourteen: seven cycle times and seven operator counts, one pair per station.
        assert len(validation.blocking_gaps) == 14
        keys = {g.key for g in validation.blocking_gaps}
        assert sum(1 for k in keys if k.endswith(".cycle_time")) == 7
        assert sum(1 for k in keys if k.endswith(".operators_required")) == 7

    def test_the_product_route_reaches_a_running_simulation(self, understanding, accepted_process):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)

        # Fill the gaps the way the product does: through Phase 18B.
        for stage in draft.stages:
            context = station_context(understanding, accepted_process, stage.id)
            request = EstimationRequest(
                stage_id=stage.id, stage_name=stage.name, process_category=stage.process_type,
                description=describe_for_estimator(context),
                automation_level=AutomationLevel.MANUAL,
                operations_per_unit=context.get("repeated_operations"),
            )
            outcome = propose_station_assumptions(request, None)
            from app.services.estimation import apply_station_assumptions

            if outcome.proposal is not None:
                draft, _ = apply_station_assumptions(
                    draft, outcome.proposal, ["cycle_time", "capacity", "operators"]
                )

        # Every station on the product route is estimable, labelling
        # included: its bands are the packaging family's own, whose
        # documented scope already names label application as one of the
        # steps it covers. See `engineering_reference_data.PROCESS_PROFILES`.
        assert all(stage.cycle_time.value is not None for stage in draft.stages)

        factory, product_id = concept_to_factory(draft)
        result = run_simulation(factory, product_id)

        # No second simulator, no second factory model: the existing one ran.
        assert result.target_units == 1900
        assert result.completed_units > 0


# Downstream context

class TestDownstreamContext:
    def test_phase_18b_receives_the_repeat_count_and_material(
        self, understanding, accepted_process
    ):
        context = station_context(understanding, accepted_process, "m-screwdriving")

        assert context["repeated_operations"] == 6
        assert context["material"] == "ABS"
        assert "6 × screws" in context["why_this_station_exists"]

    def test_the_estimator_description_carries_the_product_facts(
        self, understanding, accepted_process
    ):
        description = describe_for_estimator(
            station_context(understanding, accepted_process, "m-screwdriving")
        )
        assert "ABS" in description
        assert "6 times per unit" in description

    def test_a_hand_built_stage_simply_gets_no_context(self, understanding, accepted_process):
        assert station_context(understanding, accepted_process, "m-not-from-product") == {}


# Regression

class TestRegression:
    def test_the_golden_brief_path_is_untouched(self):
        from app.services.concept_builder import concept_from_brief
        from app.services.concept_example_data import apply_example_engineering_data

        brief = (
            "We need a new electronics assembly line. The product goes through assembly, "
            "screwdriving, inspection and packaging. We need about 1,900 units per day. "
            "The available production area is 30 by 18 meters. We have eight operators."
        )
        draft = apply_example_engineering_data(concept_from_brief(brief))
        factory, product_id = concept_to_factory(draft)
        result = run_simulation(factory, product_id)

        assert result.target_units == 1900
        assert result.completed_units == 1105
        assert result.demand_gap_units == 795.0
        assert result.system.bottleneck_machine_id == "m-screwdriving"


# HTTP surface

class TestApi:
    def test_describe_returns_facts_with_provenance(self, client):
        body = client.post(
            "/product/describe",
            json={"description": "A plastic enclosure closed with six screws.", "product_name": "Controller"},
        ).json()

        screws = next(f for f in body["understanding"]["facts"] if f["key"] == "fastener.screw.count")
        assert screws["quantity"] == 6
        assert screws["status"] == "EXTRACTED"
        assert screws["evidence"][0]["quote"]

    def test_an_empty_description_is_refused(self, client):
        assert client.post("/product/describe", json={"description": "   "}).status_code == 400

    def test_upload_reads_a_text_file(self, client, reference_text):
        response = client.post(
            "/product/upload",
            files={"file": ("spec.txt", io.BytesIO(reference_text.encode()), "text/plain")},
            data={"product_name": "Controller"},
        )
        body = response.json()

        assert response.status_code == 200
        assert body["understanding"]["fact" if False else "facts"]
        assert any(f["key"] == "fastener.screw.count" for f in body["understanding"]["facts"])

    def test_upload_refuses_an_unreadable_binary(self, client):
        response = client.post(
            "/product/upload",
            files={"file": ("model.step", io.BytesIO(b"\x00\x01\xff\xfe"), "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "CAD are not read" in response.json()["detail"]

    def test_upload_refuses_an_empty_file(self, client):
        response = client.post(
            "/product/upload", files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")}
        )
        assert response.status_code == 400

    def test_plan_process_returns_a_proposal(self, client, understanding):
        body = client.post(
            "/product/plan-process",
            json={"understanding": json.loads(understanding.model_dump_json())},
        ).json()

        assert len(body["draft"]["operations"]) == 7
        assert all(op["status"] == "PROPOSED" for op in body["draft"]["operations"])

    def test_build_concept_refuses_an_unreviewed_process(self, client, understanding):
        draft = plan_process(understanding)
        response = client.post(
            "/product/build-concept",
            json={
                "understanding": json.loads(understanding.model_dump_json()),
                "process": json.loads(draft.model_dump_json()),
                "requirements_brief": REQUIREMENTS,
            },
        )
        assert response.status_code == 400

    def test_build_concept_returns_the_station_context(self, client, understanding, accepted_process):
        body = client.post(
            "/product/build-concept",
            json={
                "understanding": json.loads(understanding.model_dump_json()),
                "process": json.loads(accepted_process.model_dump_json()),
                "requirements_brief": REQUIREMENTS,
            },
        ).json()

        assert body["validation"]["simulation_ready"] is False
        context = body["station_context"]["m-screwdriving"]
        assert context["repeated_operations"] == 6
        assert "ABS" in context["estimator_description"]

    def test_the_reference_document_is_labelled_as_example_data(self, client):
        body = client.get("/product/reference").json()
        assert body["classification"] == "EXAMPLE / REFERENCE DATA"
        assert "six screws" in body["text"]
