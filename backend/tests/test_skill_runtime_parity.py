"""Skill runtime integration — the invariants."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.factory import Factory
from app.services.input_adapters import ingest_pdf
from app.services.process_planning import plan_process
from app.services.product_intelligence import understand_product
from app.services.simulation import run_simulation
from app.skills.contract import SkillStatus
from app.skills.runtime import SkillExecutionError, SkillRuntime, RuntimeTrace, get_runtime

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "electronics_line.json"
PDF = ROOT / "examples" / "customer_docs" / "Compact_Electronics_Controller_Product_Specification.pdf"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def runtime() -> SkillRuntime:
    return get_runtime()


@pytest.fixture(scope="module")
def understanding():
    return understand_product(
        ingest_pdf(PDF.read_bytes(), name=PDF.name), None, product_name="CEC-120"
    ).understanding


@pytest.fixture
def demo_factory() -> Factory:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["products"][0]["demand_per_day"] = 1900.0
    return Factory.model_validate(data)


class _CountingSimulation:
    """Counts how many times the simulator is actually entered."""

    def __init__(self, monkeypatch):
        import app.services.simulation as simulation_module

        self.count = 0
        real = simulation_module.run_simulation

        def counted(*args, **kwargs):
            self.count += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(simulation_module, "run_simulation", counted)


# I1 — response parity

class TestI1ResponseParity:
    def test_process_planning_is_identical_through_the_runtime(self, runtime, understanding):
        direct = plan_process(understanding)
        routed = runtime.unwrap("process_planning", {"understanding": understanding})

        # Whole object, not a field selection.
        assert routed.model_dump_json() == direct.model_dump_json()

    def test_simulation_is_identical_through_the_runtime(self, runtime, demo_factory):
        product_id = demo_factory.products[0].id
        direct = run_simulation(demo_factory, product_id)
        routed = runtime.unwrap(
            "factory_simulation", {"factory": demo_factory, "product_id": product_id}
        )

        assert routed.model_dump_json() == direct.model_dump_json()

    def test_product_understanding_is_identical_through_the_runtime(self, runtime):
        ingestion = ingest_pdf(PDF.read_bytes(), name=PDF.name)
        direct = understand_product(ingestion, None, product_name="CEC-120").understanding
        routed = runtime.unwrap(
            "product_understanding", {"ingestion": ingestion, "product_name": "CEC-120"}
        )

        assert routed.model_dump_json() == direct.model_dump_json()

    def test_the_endpoint_response_is_unchanged(self, client, understanding):
        # The observable contract: what a browser receives.
        body = client.post(
            "/product/plan-process",
            json={"understanding": json.loads(understanding.model_dump_json())},
        )
        assert body.status_code == 200

        direct = plan_process(understanding)
        assert body.json()["draft"] == json.loads(direct.model_dump_json())


# I2 — simulation count parity

class TestI2SimulationCount:
    def test_the_runtime_runs_the_simulator_exactly_once(
        self, runtime, demo_factory, monkeypatch
    ):
        counter = _CountingSimulation(monkeypatch)
        product_id = demo_factory.products[0].id

        runtime.unwrap("factory_simulation", {"factory": demo_factory, "product_id": product_id})
        assert counter.count == 1

    def test_bottleneck_analysis_consumes_the_result_and_never_re_runs(
        self, runtime, demo_factory, monkeypatch
    ):
        # The invariant the phase called out by name.
        result = run_simulation(demo_factory, demo_factory.products[0].id)

        counter = _CountingSimulation(monkeypatch)
        stage = runtime.unwrap("bottleneck_analysis", {"simulation": result})

        assert counter.count == 0
        assert stage == result.system.bottleneck_machine_id

    def test_a_workflow_costs_the_same_simulations_as_the_direct_sequence(
        self, demo_factory, monkeypatch
    ):
        from app.skills.orchestrator import EngineeringSkillOrchestrator
        from app.skills.workflows import VERIFY_CONCEPT

        import app.services.simulation as simulation_module

        product_id = demo_factory.products[0].id

        # of this file.
        direct_counter = _CountingSimulation(monkeypatch)
        result = simulation_module.run_simulation(demo_factory, product_id)
        _ = result.system.bottleneck_machine_id
        direct_count = direct_counter.count

        workflow_counter = _CountingSimulation(monkeypatch)
        EngineeringSkillOrchestrator(get_runtime().registry).run(
            VERIFY_CONCEPT, {"factory": demo_factory, "product_id": product_id}
        )

        assert workflow_counter.count == direct_count == 1

    def test_the_runtime_trace_reports_the_simulation_count(self, runtime, demo_factory):
        trace = RuntimeTrace()
        runtime.unwrap(
            "factory_simulation",
            {"factory": demo_factory, "product_id": demo_factory.products[0].id},
            trace=trace,
        )
        assert trace.simulations_run == 1


# I3 — provenance parity

class TestI3ProvenanceParity:
    def test_rule_derived_stays_rule_derived(self, runtime, understanding):
        from app.models.product import FactStatus

        direct = plan_process(understanding)
        routed = runtime.unwrap("process_planning", {"understanding": understanding})

        assert [op.fact_status for op in routed.operations] == [
            op.fact_status for op in direct.operations
        ]
        assert all(op.fact_status is FactStatus.RULE_DERIVED for op in routed.operations)

    def test_evidence_and_source_facts_survive_the_runtime(self, runtime, understanding):
        direct = plan_process(understanding)
        routed = runtime.unwrap("process_planning", {"understanding": understanding})

        for a, b in zip(direct.operations, routed.operations):
            assert a.source_fact_keys == b.source_fact_keys
            assert [e.quote for e in a.evidence] == [e.quote for e in b.evidence]
            assert [e.page for e in a.evidence] == [e.page for e in b.evidence]

    def test_customer_values_keep_their_source(self, runtime):
        from app.models.concept import ValueSource

        brief = (
            "We need 1,900 units per day through assembly and packaging. "
            "30 by 18 meters. We have eight operators."
        )
        draft = runtime.unwrap("requirements_extraction", {"brief": brief})

        assert draft.production_target.value == 1900
        assert draft.production_target.source is ValueSource.CUSTOMER
        assert draft.operators_available.source is ValueSource.CUSTOMER

    def test_unknown_stays_unknown_through_the_runtime(self, runtime):
        from app.models.concept import ValueSource

        draft = runtime.unwrap("requirements_extraction", {"brief": "We need 1,900 units per day."})
        # The brief states no schedule. Nothing may fill it.
        assert draft.shifts_per_day.value is None
        assert draft.shifts_per_day.source is ValueSource.UNKNOWN


# I4 — error parity

class TestI4ErrorParity:
    def test_missing_input_blocks_rather_than_inventing_one(self, runtime):
        result = runtime.execute("factory_simulation", {})
        assert result.status is SkillStatus.BLOCKED
        assert result.data is None

    def test_unwrap_raises_rather_than_returning_a_substitute(self, runtime):
        with pytest.raises(SkillExecutionError) as raised:
            runtime.unwrap("factory_simulation", {})
        assert raised.value.status is SkillStatus.BLOCKED
        assert "factory" in raised.value.unresolved_inputs

    def test_an_empty_brief_fails_the_same_way_on_both_paths(self, runtime):
        from app.services.concept_builder import concept_from_brief

        # Direct: produces a draft with everything unknown, no exception.
        direct = concept_from_brief("")
        assert direct.production_target.value is None

        # Runtime: BLOCKED, because a skill declares what it needs.
        result = runtime.execute("requirements_extraction", {"brief": ""})
        assert result.status is SkillStatus.BLOCKED

    def test_the_runtime_never_substitutes_demo_data(self, runtime):
        from app.services.concept_example_data import EXAMPLE_DATASET_NAME

        result = runtime.execute("requirements_extraction", {"brief": "   "})
        assert EXAMPLE_DATASET_NAME not in json.dumps(result.warnings)
        assert result.data is None

    def test_an_unknown_skill_raises_a_programming_error_not_a_blocked_result(self, runtime):
        from app.skills.registry import SkillNotFound

        # Asking for a skill that does not exist is a bug in the caller, not
        # a missing engineering input.
        with pytest.raises(SkillNotFound):
            runtime.execute("no_such_skill", {})

    def test_an_unsupported_version_raises(self, runtime):
        from app.skills.registry import SkillNotFound

        with pytest.raises(SkillNotFound, match="no version"):
            runtime.execute("factory_simulation", {}, version="99.0.0")

    def test_a_simulator_failure_is_reported_not_swallowed(self, runtime, demo_factory, monkeypatch):
        import app.services.simulation as simulation_module

        def boom(*args, **kwargs):
            raise RuntimeError("simulator exploded")

        monkeypatch.setattr(simulation_module, "run_simulation", boom)
        result = runtime.execute(
            "factory_simulation",
            {"factory": demo_factory, "product_id": demo_factory.products[0].id},
        )
        assert result.status is SkillStatus.FAILED
        assert result.data is None
        assert "exploded" in result.warnings[0]


# I5 — determinism

class TestI5Determinism:
    def test_repeated_runtime_execution_is_identical(self, runtime, demo_factory):
        payload = {"factory": demo_factory, "product_id": demo_factory.products[0].id}
        first = runtime.unwrap("factory_simulation", payload)
        second = runtime.unwrap("factory_simulation", payload)
        assert first.model_dump_json() == second.model_dump_json()

    def test_repeated_endpoint_calls_are_identical(self, client, understanding):
        body = {"understanding": json.loads(understanding.model_dump_json())}
        first = client.post("/product/plan-process", json=body).json()
        second = client.post("/product/plan-process", json=body).json()
        assert first == second


# I6 — no golden regression

class TestI6GoldenValues:
    def test_the_golden_case_is_unchanged_through_the_runtime(self, runtime, demo_factory):
        result = runtime.unwrap(
            "factory_simulation",
            {"factory": demo_factory, "product_id": demo_factory.products[0].id},
        )
        assert result.completed_units == 1105
        assert result.target_units == 1900
        assert result.demand_gap_units == 795
        assert result.system.bottleneck_machine_id == "m-screwdriving"


# Runtime trace — orchestration metadata, not engineering evidence

class TestRuntimeTrace:
    def test_the_trace_records_skill_and_version(self, runtime, demo_factory):
        trace = RuntimeTrace()
        runtime.unwrap(
            "factory_simulation",
            {"factory": demo_factory, "product_id": demo_factory.products[0].id},
            trace=trace,
        )
        record = trace.records[0]
        assert record.skill_id == "factory_simulation"
        assert record.version == "1.0.0"
        assert record.status == "SUCCESS"

    def test_the_trace_carries_no_payload_content(self, runtime, understanding):
        # Orchestration metadata only.
        trace = RuntimeTrace()
        runtime.unwrap("process_planning", {"understanding": understanding}, trace=trace)

        blob = json.dumps([record.__dict__ for record in trace.records])
        assert "enclosure" not in blob.lower()
        assert "M3" not in blob
        assert len(blob) < 1000


# POST /concept/build — the multi-stage workflow migration

CONCEPT_BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, "
    "screwdriving, inspection and packaging. We need about 1,900 units per day. "
    "The available production area is 30 by 18 meters. We have eight operators."
)


@pytest.fixture
def resolved_draft():
    from app.services.concept_builder import concept_from_brief
    from app.services.concept_example_data import apply_example_engineering_data

    return apply_example_engineering_data(concept_from_brief(CONCEPT_BRIEF))


@pytest.fixture
def unresolved_draft():
    from app.services.concept_builder import concept_from_brief

    return concept_from_brief(CONCEPT_BRIEF)


class TestConceptBuildWorkflowParity:
    """`/concept/build` runs BUILD_CONCEPT rather than calling two services."""

    def test_whole_object_parity_against_the_direct_calls(self, client, resolved_draft):
        from app.services.concept_builder import generate_initial_layout
        from app.services.concept_validation import concept_to_factory

        factory, product_id = concept_to_factory(resolved_draft)
        layout = generate_initial_layout(resolved_draft)

        response = client.post(
            "/concept/build", json={"draft": json.loads(resolved_draft.model_dump_json())}
        )
        assert response.status_code == 200
        body = response.json()

        assert body["factory"] == json.loads(factory.model_dump_json())
        assert body["product_id"] == product_id
        assert body["layout"] == json.loads(layout.model_dump_json())

    def test_the_workflow_runs_no_simulations(self, client, resolved_draft, monkeypatch):
        # Building a concept must not simulate.
        counter = _CountingSimulation(monkeypatch)
        response = client.post(
            "/concept/build",
            json={"draft": json.loads(resolved_draft.model_dump_json())},
        )
        assert response.status_code == 200
        assert counter.count == 0

    def test_an_unresolved_draft_keeps_the_domain_message_verbatim(
        self, client, unresolved_draft
    ):
        # The regression this test exists for: the skill originally summarised
        # the refusal as "6 value(s) ... missing" while the direct path named
        # them — "Shifts per day, Assembly cycle time". That text reaches the
        # engineer, so a reworded version is a user-visible change, not an
        # internal detail.
        from app.services.concept_validation import ConceptNotReadyError, concept_to_factory

        with pytest.raises(ConceptNotReadyError) as direct:
            concept_to_factory(unresolved_draft)

        response = client.post(
            "/concept/build", json={"draft": json.loads(unresolved_draft.model_dump_json())}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == str(direct.value)

    def test_the_refusal_names_the_missing_values(self, client, unresolved_draft):
        response = client.post(
            "/concept/build", json={"draft": json.loads(unresolved_draft.model_dump_json())}
        )
        detail = response.json()["detail"]
        assert "Screwdriving cycle time" in detail
        assert "Shifts per day" in detail

    def test_a_missing_draft_blocks_rather_than_raising(self):
        # Contract check on the stage skill itself: a skill reports, it does not raise.
        from app.skills import SkillContext
        from app.skills.builtin import register_builtin_skills

        result = register_builtin_skills().get("factory_concept_builder").execute(
            {"draft": None}, SkillContext()
        )
        assert result.status is SkillStatus.BLOCKED
        assert "draft" in result.unresolved_inputs

    def test_a_layout_problem_does_not_block_the_concept(self, resolved_draft):
        # `layout_generation` is an OPTIONAL stage.
        from app.skills.orchestrator import EngineeringSkillOrchestrator
        from app.skills.workflows import BUILD_CONCEPT

        stage = BUILD_CONCEPT.stages[1]
        assert stage.skill_id == "layout_generation"
        assert stage.required is False

        run = EngineeringSkillOrchestrator(get_runtime().registry).run(
            BUILD_CONCEPT, {"draft": resolved_draft}
        )
        assert run.completed
        assert run.outputs["factory_and_product"] is not None


# POST /product/upload and /product/describe — the adapter shape

class TestProductUnderstandingAdapterParity:
    """Ingestion stays in the handler; understanding goes through the skill."""

    def test_upload_response_matches_the_direct_call(self, client):
        from app.main import _estimation_mode, _llm_provider_or_none
        from app.services.product_intelligence import understand_product

        direct = understand_product(
            ingest_pdf(PDF.read_bytes(), name=PDF.name),
            _llm_provider_or_none(),
            product_name="CEC-120",
            mode=_estimation_mode(None),
        )
        response = client.post(
            "/product/upload",
            files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
            data={"product_name": "CEC-120"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["understanding"] == json.loads(direct.understanding.model_dump_json())
        assert body["model_used"] is direct.model_used
        assert body["provider_note"] == direct.provider_note

    def test_describe_forwards_the_description_kwarg(self, client):
        # `description` is not the same as the ingested text: the extractor
        # receives both. A skill that dropped it would silently change what
        # this endpoint understands, which is why parity is asserted on the
        # whole understanding rather than on a fact count.
        from app.main import _estimation_mode, _llm_provider_or_none
        from app.services.input_adapters import ingest_text
        from app.services.product_intelligence import understand_product

        description = (
            "A compact controller enclosure, 120 x 80 x 35 mm, with four M3 "
            "screws and a PCB."
        )
        direct = understand_product(
            ingest_text(description, name="Product description"),
            _llm_provider_or_none(),
            product_name="CEC-120",
            description=description,
            mode=_estimation_mode(None),
        )
        response = client.post(
            "/product/describe",
            json={"description": description, "product_name": "CEC-120"},
        )
        assert response.status_code == 200
        assert response.json()["understanding"] == json.loads(
            direct.understanding.model_dump_json()
        )

    def test_the_skill_forwards_mode(self, runtime):
        # LOCAL_ONLY must reach `understand_product`.
        import app.services.product_intelligence as pi
        from app.main import _estimation_mode
        from app.skills import SkillContext

        seen = {}
        real = pi.understand_product

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        pi.understand_product = spy
        try:
            runtime.execute(
                "product_understanding",
                {
                    "ingestion": ingest_pdf(PDF.read_bytes(), name=PDF.name),
                    "product_name": "CEC-120",
                    "mode": _estimation_mode("LOCAL_ONLY"),
                },
                context=SkillContext(),
            )
        finally:
            pi.understand_product = real

        assert seen.get("mode") == _estimation_mode("LOCAL_ONLY")

    @pytest.mark.parametrize(
        "call, expected",
        [
            (lambda c: c.post("/product/describe", json={"description": "   "}), 400),
            (
                lambda c: c.post(
                    "/product/upload", files={"file": ("x.txt", b"", "text/plain")}
                ),
                400,
            ),
            (
                lambda c: c.post(
                    "/product/upload",
                    files={"file": ("x.exe", b"MZ\x90\x00" * 50, "application/octet-stream")},
                ),
                400,
            ),
        ],
    )
    def test_transport_errors_keep_their_status(self, client, call, expected):
        # These are rejected BEFORE the skill runs.
        assert call(client).status_code == expected

    def test_declared_gaps_still_return_the_understanding(self, client):
        # PARTIAL is the normal state.
        response = client.post(
            "/product/upload",
            files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")},
            data={"product_name": "CEC-120"},
        )
        assert response.status_code == 200
        assert response.json()["understanding"]["facts"]
