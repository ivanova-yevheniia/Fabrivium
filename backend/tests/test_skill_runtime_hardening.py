"""Skill runtime hardening — persistence, versioning, company skills, failure."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.factory import Factory
from app.skills.contract import (
    ExecutionMode,
    Skill,
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)
from app.skills.registry import SkillNotFound, SkillRegistrationError, SkillRegistry
from app.skills.runtime import SkillExecutionError, SkillRuntime

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "electronics_line.json"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def demo_factory() -> Factory:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    data["products"][0]["demand_per_day"] = 1900.0
    return Factory.model_validate(data)


# §6 — persistence compatibility

class TestPersistedDataStillLoads:
    """Data written before the skill layer existed must still work."""

    def test_the_frozen_example_factory_still_simulates_to_the_golden_values(
        self, client, demo_factory
    ):
        # `examples/electronics_line.json` is checked in and predates the skill layer.
        response = client.post(
            "/simulation/run",
            json={
                "factory": json.loads(demo_factory.model_dump_json()),
                "product_id": demo_factory.products[0].id,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert round(body["completed_units"]) == 1105
        assert body["system"]["bottleneck_machine_id"] == "m-screwdriving"

    def test_a_factory_persisted_and_reloaded_is_unchanged_through_the_runtime(
        self, client, demo_factory, tmp_path
    ):
        # Round trip: dump, write, read, load, simulate.
        saved = tmp_path / "factory.json"
        saved.write_text(demo_factory.model_dump_json(), encoding="utf-8")
        reloaded = Factory.model_validate_json(saved.read_text(encoding="utf-8"))

        assert reloaded.model_dump_json() == demo_factory.model_dump_json()

        first, second = (
            client.post(
                "/simulation/run",
                json={
                    "factory": json.loads(f.model_dump_json()),
                    "product_id": f.products[0].id,
                },
            ).json()
            for f in (demo_factory, reloaded)
        )
        assert first == second

    def test_the_runtime_writes_nothing_to_disk(self, demo_factory, tmp_path, monkeypatch):
        # A runtime that persisted traces would create files nobody asked
        # for, in a directory nobody chose.
        monkeypatch.chdir(tmp_path)
        before = set(tmp_path.iterdir())

        SkillRuntime().execute(
            "factory_simulation",
            {"factory": demo_factory, "product_id": demo_factory.products[0].id},
        )
        assert set(tmp_path.iterdir()) == before


# §7 — versioning

class _V1(Skill):
    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="demo_versioned",
            version="1.0.0",
            name="Demo versioned skill",
            description="Returns the version that produced the answer.",
            category=SkillCategory.VALIDATION,
        )

    def execute(self, payload, context) -> SkillResult:
        return SkillResult(status=SkillStatus.SUCCESS, data={"from": "1.0.0"})


class _V2(_V1):
    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="demo_versioned",
            version="2.0.0",
            name="Demo versioned skill",
            description="A different answer, on purpose.",
            category=SkillCategory.VALIDATION,
        )

    def execute(self, payload, context) -> SkillResult:
        return SkillResult(status=SkillStatus.SUCCESS, data={"from": "2.0.0"})


@pytest.fixture
def versioned_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(_V1())
    registry.register(_V2())
    return registry


class TestVersioningIsIdentityNotLabel:
    def test_the_newest_version_answers_when_none_is_asked_for(self, versioned_registry):
        runtime = SkillRuntime(versioned_registry)
        assert runtime.unwrap("demo_versioned", {}) == {"from": "2.0.0"}

    def test_an_exact_version_is_addressable(self, versioned_registry):
        runtime = SkillRuntime(versioned_registry)
        assert runtime.unwrap("demo_versioned", {}, version="1.0.0") == {"from": "1.0.0"}

    def test_a_result_recorded_against_v1_does_not_become_a_v2_result(
        self, versioned_registry
    ):
        """The property that matters for a saved project."""
        runtime = SkillRuntime(versioned_registry)
        from app.skills.runtime import RuntimeTrace

        trace = RuntimeTrace()
        recorded = runtime.unwrap("demo_versioned", {}, version="1.0.0", trace=trace)
        assert trace.records[0].version == "1.0.0"

        # v3 arrives after the result was recorded.
        class _V3(_V1):
            @property
            def definition(self) -> SkillDefinition:
                return SkillDefinition(
                    id="demo_versioned",
                    version="3.0.0",
                    name="Demo versioned skill",
                    description="Newer still.",
                    category=SkillCategory.VALIDATION,
                )

            def execute(self, payload, context) -> SkillResult:
                return SkillResult(status=SkillStatus.SUCCESS, data={"from": "3.0.0"})

        versioned_registry.register(_V3())

        assert runtime.unwrap("demo_versioned", {}, version="1.0.0") == recorded
        assert runtime.unwrap("demo_versioned", {}) == {"from": "3.0.0"}

    def test_registering_the_same_id_and_version_twice_is_refused(self, versioned_registry):
        # Two skills answering to one identity would make a recorded version
        # ambiguous, which is the same as not recording it.
        with pytest.raises(SkillRegistrationError):
            versioned_registry.register(_V1())

    def test_an_unknown_version_is_an_error_not_a_silent_fallback(self, versioned_registry):
        with pytest.raises(SkillNotFound):
            versioned_registry.get("demo_versioned", "9.9.9")

    def test_every_first_party_skill_declares_a_version(self):
        from app.skills.builtin import register_builtin_skills

        for definition in register_builtin_skills().list_all():
            assert definition.version, definition.id


# §8 — company skill safety

class TestCompanySkillSafety:
    """A company skill may add a constraint. It may not rewrite a fact."""

    def test_an_unpriced_plan_is_cost_unknown_never_within_budget(self):
        """A policy check against a number nobody has has no answer."""
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        class _Unpriced:
            strategy_id = "add-second-screwdriver"
            cost = None
            commercially_complete = False

        result = AvoidHighCapexPreferenceSkill().execute(
            {"strategies": [_Unpriced()]}, SkillContext()
        )

        assert result.status is SkillStatus.PARTIAL
        assert [a.verdict for a in result.data] == ["COST_UNKNOWN"]
        assert result.unresolved_inputs == ["price:add-second-screwdriver"]

        blob = json.dumps([a.__dict__ for a in result.data], default=str).lower()
        assert "within" not in blob

    def test_a_company_skill_runs_in_its_own_namespace(self):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        definition = AvoidHighCapexPreferenceSkill().definition
        assert definition.namespace == "acme"
        # A namespaced skill must not collide with a first-party id.
        from app.skills.builtin import register_builtin_skills

        first_party = {d.id for d in register_builtin_skills().list_all()}
        assert definition.id not in first_party

    def test_registering_a_company_skill_changes_no_first_party_definition(self):
        from app.skills.builtin import register_builtin_skills
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        registry = register_builtin_skills(SkillRegistry())
        before = {d.id: d.version for d in registry.list_all()}
        registry.register(AvoidHighCapexPreferenceSkill())
        after = {d.id: d.version for d in registry.list_all()}

        assert before.items() <= after.items()

    def test_a_company_skill_cannot_change_the_simulated_throughput(
        self, client, demo_factory
    ):
        # The decisive safety property.
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill
        from app.skills.runtime import get_runtime

        runtime = get_runtime()
        try:
            runtime.registry.register(AvoidHighCapexPreferenceSkill())
        except SkillRegistrationError:
            pass  # already registered by another test

        response = client.post(
            "/simulation/run",
            json={
                "factory": json.loads(demo_factory.model_dump_json()),
                "product_id": demo_factory.products[0].id,
            },
        )
        assert round(response.json()["completed_units"]) == 1105

    def test_there_is_no_endpoint_that_executes_an_arbitrary_skill(self, client):
        # Running a caller-named skill over HTTP would make the framework a
        # remote-execution surface. The inspection endpoints are GET only.
        paths = client.get("/openapi.json").json()["paths"]
        skill_paths = {p: set(m.upper() for m in v) for p, v in paths.items() if "/skills" in p}
        assert skill_paths
        for path, methods in skill_paths.items():
            assert methods <= {"GET"}, f"{path} exposes {methods}"


# §10 — failure injection

class _Exploding(Skill):
    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="exploding_skill",
            version="1.0.0",
            name="Exploding skill",
            description="Raises, to prove the runtime does not swallow it.",
            category=SkillCategory.VALIDATION,
        )

    def execute(self, payload, context) -> SkillResult:
        raise RuntimeError("detonated")


class TestFailureIsVisible:
    def test_a_blocked_skill_never_yields_a_value(self):
        from app.skills.builtin import register_builtin_skills

        runtime = SkillRuntime(register_builtin_skills(SkillRegistry()))
        with pytest.raises(SkillExecutionError) as exc:
            runtime.unwrap("factory_concept_builder", {"draft": None})

        assert exc.value.status is SkillStatus.BLOCKED
        assert "draft" in exc.value.unresolved_inputs

    def test_a_raising_skill_is_not_turned_into_an_empty_success(self):
        # The runtime does not catch.
        registry = SkillRegistry()
        registry.register(_Exploding())
        with pytest.raises(RuntimeError, match="detonated"):
            SkillRuntime(registry).execute("exploding_skill", {})

    def test_an_unknown_skill_id_raises_rather_than_returning_nothing(self):
        with pytest.raises(SkillNotFound):
            SkillRuntime(SkillRegistry()).execute("no_such_skill", {})

    def test_a_simulation_failure_reaches_the_client_as_400_with_its_reason(
        self, client, demo_factory, monkeypatch
    ):
        import app.services.simulation as simulation_module

        def broken(*args, **kwargs):
            raise ValueError("the simulator refused this factory")

        monkeypatch.setattr(simulation_module, "run_simulation", broken)

        response = client.post(
            "/simulation/run",
            json={
                "factory": json.loads(demo_factory.model_dump_json()),
                "product_id": demo_factory.products[0].id,
            },
        )
        assert response.status_code == 400
        # The reason survives.
        assert "the simulator refused this factory" in response.json()["detail"]

    def test_a_failed_required_stage_stops_the_workflow_and_says_why(self):
        from app.skills.builtin import register_builtin_skills
        from app.skills.orchestrator import EngineeringSkillOrchestrator
        from app.skills.workflows import BUILD_CONCEPT

        registry = register_builtin_skills(SkillRegistry())
        run = EngineeringSkillOrchestrator(registry).run(BUILD_CONCEPT, {"draft": None})

        assert not run.completed
        assert run.stopped_because
        assert "factory_and_product" not in run.outputs

    def test_the_error_carries_no_document_content(self, client):
        # An error message is a place customer text leaks.
        from app.services.concept_builder import concept_from_brief

        secret = "Project Nightingale confidential enclosure"
        draft = concept_from_brief(
            f"{secret}. We need 1,900 units per day with assembly and packaging."
        )
        response = client.post(
            "/concept/build", json={"draft": json.loads(draft.model_dump_json())}
        )
        assert response.status_code == 400
        assert "Nightingale" not in response.json()["detail"]


# §5 — execution trace exposure

class TestSkillTraceHeader:
    """Which skills produced this response — reported without touching it."""

    def test_a_routed_endpoint_names_the_skill_and_version(self, client, demo_factory):
        response = client.post(
            "/simulation/run",
            json={
                "factory": json.loads(demo_factory.model_dump_json()),
                "product_id": demo_factory.products[0].id,
            },
        )
        assert response.headers["X-FactoryMind-Skills"] == "factory_simulation@1.0.0:SUCCESS"

    def test_a_workflow_endpoint_names_every_stage_in_order(self, client):
        from app.services.concept_builder import concept_from_brief
        from app.services.concept_example_data import apply_example_engineering_data

        draft = apply_example_engineering_data(
            concept_from_brief(
                "We need a line making 1,900 units per day with assembly, "
                "screwdriving, inspection and packaging in a 30 by 18 meter hall "
                "with eight operators."
            )
        )
        response = client.post(
            "/concept/build", json={"draft": json.loads(draft.model_dump_json())}
        )
        assert response.headers["X-FactoryMind-Skills"] == (
            "factory_concept_builder@1.0.0:SUCCESS, layout_generation@1.0.0:SUCCESS"
        )

    def test_an_unrouted_endpoint_reports_no_skills(self, client):
        # The header is evidence, not decoration.
        assert "X-FactoryMind-Skills" not in client.get("/health").headers

    def test_the_header_does_not_change_the_body(self, client, demo_factory):
        payload = {
            "factory": json.loads(demo_factory.model_dump_json()),
            "product_id": demo_factory.products[0].id,
        }
        body = client.post("/simulation/run", json=payload).json()
        assert "trace" not in body
        assert "skills" not in body

    def test_the_header_carries_no_document_content(self, client):
        # Identifiers, versions and statuses only.
        from app.services.input_adapters import ingest_text

        response = client.post(
            "/product/describe",
            json={
                "description": "A Nightingale enclosure, 120 x 80 x 35 mm, four M3 screws.",
                "product_name": "CEC-120",
            },
        )
        header = response.headers["X-FactoryMind-Skills"]
        assert "Nightingale" not in header
        assert "M3" not in header
        assert header.startswith("product_understanding@")

    def test_concurrent_requests_do_not_share_a_trace(self, client, demo_factory):
        # The recorder is a context variable, not a global.
        import concurrent.futures

        def run_sim():
            return client.post(
                "/simulation/run",
                json={
                    "factory": json.loads(demo_factory.model_dump_json()),
                    "product_id": demo_factory.products[0].id,
                },
            ).headers["X-FactoryMind-Skills"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            headers = list(pool.map(lambda _: run_sim(), range(4)))

        assert headers == ["factory_simulation@1.0.0:SUCCESS"] * 4
