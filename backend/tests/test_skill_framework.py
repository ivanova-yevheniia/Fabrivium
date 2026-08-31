"""The skill framework."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.services.simulation import run_simulation
from app.skills import (
    ExecutionMode,
    SideEffect,
    Skill,
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillRegistrationError,
    SkillNotFound,
    SkillRegistry,
    SkillResult,
    SkillStatus,
)
from app.skills.builtin import BUILTIN_SKILLS, register_builtin_skills
from app.skills.orchestrator import (
    EngineeringSkillOrchestrator,
    WorkflowDefinition,
    WorkflowStage,
)
from app.skills.workflows import ALL_WORKFLOWS, VERIFY_CONCEPT, workflow_by_id

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "electronics_line.json"
PDF = ROOT / "examples" / "customer_docs" / "Compact_Electronics_Controller_Product_Specification.pdf"


@pytest.fixture
def registry() -> SkillRegistry:
    return register_builtin_skills(SkillRegistry())


@pytest.fixture
def orchestrator(registry) -> EngineeringSkillOrchestrator:
    return EngineeringSkillOrchestrator(registry)


@pytest.fixture
def demo_factory() -> tuple[Factory, str]:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    # The demo goal states 1,900/day; the file itself says 1,200.
    data["products"][0]["demand_per_day"] = 1900.0
    factory = Factory.model_validate(data)
    return factory, factory.products[0].id


# The parity regression

class TestGoldenPathParity:
    """The framework must be behaviour-preserving."""

    def test_the_simulation_result_is_identical_through_the_skill_layer(
        self, registry, demo_factory
    ):
        factory, product_id = demo_factory
        direct = run_simulation(factory, product_id)

        result = registry.get("factory_simulation").execute(
            {"factory": factory, "product_id": product_id}, SkillContext()
        )

        # Not "close enough" — the same object, field for field.
        assert result.data.model_dump_json() == direct.model_dump_json()

    def test_the_golden_values_survive_the_workflow(self, orchestrator, demo_factory):
        factory, product_id = demo_factory
        run = orchestrator.run(VERIFY_CONCEPT, {"factory": factory, "product_id": product_id})

        simulation = run.outputs["simulation"]
        assert simulation.completed_units == 1105
        assert simulation.target_units == 1900
        assert simulation.demand_gap_units == 795
        assert run.outputs["limiting_stage"] == "m-screwdriving"

    def test_the_bottleneck_is_read_not_recomputed(self, registry, demo_factory):
        # A second derivation could disagree with the first.
        factory, product_id = demo_factory
        direct = run_simulation(factory, product_id)

        result = registry.get("bottleneck_analysis").execute({"simulation": direct}, SkillContext())
        assert result.data == direct.system.bottleneck_machine_id

    def test_the_skill_layer_adds_no_simulation_runs(self, orchestrator, demo_factory):
        # Wrapping must not cost an extra run of a 1,700-line engine.
        factory, product_id = demo_factory
        run = orchestrator.run(VERIFY_CONCEPT, {"factory": factory, "product_id": product_id})
        assert sum(entry.simulations_run for entry in run.trace) == 1


# Registry

class TestRegistry:
    def test_every_builtin_skill_registers(self, registry):
        assert len(registry.list_enabled()) == len(BUILTIN_SKILLS)

    def test_a_duplicate_id_and_version_is_refused(self, registry):
        # Two skills sharing an id and version makes behaviour depend on
        # registration order — usually a copied module nobody renamed.
        from app.skills.builtin import FactorySimulationSkill

        with pytest.raises(SkillRegistrationError, match="already registered"):
            registry.register(FactorySimulationSkill())

    def test_registering_builtins_twice_is_a_no_op(self):
        registry = register_builtin_skills(SkillRegistry())
        before = len(registry.list_enabled())
        register_builtin_skills(registry)
        assert len(registry.list_enabled()) == before

    def test_an_unknown_skill_raises_rather_than_returning_none(self, registry):
        with pytest.raises(SkillNotFound):
            registry.get("no_such_skill")

    def test_skills_are_found_by_capability_not_only_by_id(self, registry):
        # A workflow asks for a capability so a company skill can supersede
        # a first-party one without the workflow changing.
        found = registry.find_by_capability("simulate_factory")
        assert [d.id for d in found] == ["factory_simulation"]

    def test_skills_are_found_by_category(self, registry):
        simulation = registry.find_by_category(SkillCategory.SIMULATION)
        assert {d.id for d in simulation} == {"factory_simulation", "bottleneck_analysis"}

    def test_a_disabled_skill_disappears_from_lookup(self, registry):
        registry.set_enabled("equipment_discovery", False)
        assert not registry.has("equipment_discovery")
        assert "equipment_discovery" not in {d.id for d in registry.list_enabled()}
        # Still registered, just off — list_all shows it.
        assert "equipment_discovery" in {d.id for d in registry.list_all()}

    def test_the_newest_version_wins_by_default(self):
        registry = SkillRegistry()

        class V1(_MinimalSkill):
            version = "1.0.0"

        class V2(_MinimalSkill):
            version = "1.2.0"

        registry.register(V1())
        registry.register(V2())
        assert registry.definition("minimal").version == "1.2.0"
        # And an exact version can still be asked for — that is what makes a
        # version in a trace reproducible later.
        assert registry.definition("minimal", "1.0.0").version == "1.0.0"

    def test_missing_prerequisites_are_reported(self, registry):
        registry.unregister("factory_simulation")
        assert registry.missing_prerequisites("bottleneck_analysis") == ["factory_simulation"]

    def test_prerequisite_ordering_is_resolved(self, registry):
        ordered = registry.resolve_order(["bottleneck_analysis", "factory_simulation"])
        assert ordered.index("factory_simulation") < ordered.index("bottleneck_analysis")


# The contract itself

class TestSkillContract:
    def test_a_result_with_unresolved_inputs_cannot_be_success(self):
        # The rule the whole status enum exists for.
        with pytest.raises(ValueError, match="cannot be SUCCESS"):
            SkillResult(status=SkillStatus.SUCCESS, data="x", unresolved_inputs=["price"])

    def test_a_success_must_carry_data(self):
        with pytest.raises(ValueError, match="promises output"):
            SkillResult(status=SkillStatus.SUCCESS, data=None)

    def test_blocked_and_failed_need_no_data(self):
        assert SkillResult(status=SkillStatus.BLOCKED).usable is False
        assert SkillResult(status=SkillStatus.FAILED).usable is False
        assert SkillResult(status=SkillStatus.NOT_APPLICABLE).usable is False

    def test_a_skill_declaring_an_llm_cannot_claim_to_be_deterministic(self):
        with pytest.raises(ValueError, match="uses_llm"):
            SkillDefinition(
                id="x",
                version="1.0.0",
                name="x",
                description="x",
                category=SkillCategory.ESTIMATION,
                uses_llm=True,
                execution_mode=ExecutionMode.DETERMINISTIC,
            )

    def test_a_skill_needs_a_version(self):
        with pytest.raises(ValueError, match="version"):
            SkillDefinition(
                id="x", version="", name="x", description="x", category=SkillCategory.PLANNING
            )

    def test_every_builtin_declares_its_side_effects_honestly(self, registry):
        by_id = {d.id: d for d in registry.list_enabled()}
        # The two capabilities that genuinely touch the world.
        assert SideEffect.WRITES_FILE in by_id["siemens_handoff"].side_effects
        assert SideEffect.CONTROLS_EXTERNAL_TOOL in by_id["siemens_handoff"].side_effects
        assert SideEffect.READS_LOCAL_DATA in by_id["equipment_discovery"].side_effects
        # And the pure one that must never claim otherwise.
        assert by_id["factory_simulation"].side_effects == (SideEffect.NONE,)

    def test_the_simulation_skill_declares_no_model(self, registry):
        simulation = registry.definition("factory_simulation")
        assert simulation.deterministic is True
        assert simulation.uses_llm is False
        assert simulation.execution_mode is ExecutionMode.DETERMINISTIC

    def test_every_builtin_has_a_stable_qualified_id(self, registry):
        for definition in registry.list_enabled():
            assert definition.qualified_id.startswith("factorymind/")
            assert "@" in definition.qualified_id


# Skill behaviour

class TestSkillBehaviour:
    def test_a_skill_reports_missing_input_rather_than_raising(self, registry):
        # A skill that raises makes every caller responsible for its failure
        # modes, which defeats declaring them.
        result = registry.get("factory_simulation").execute({}, SkillContext())
        assert result.status is SkillStatus.BLOCKED
        assert "factory" in result.unresolved_inputs

    def test_an_inapplicable_input_is_not_a_failure(self, registry):
        # names no components implies no operations, which is an answer
        # rather than an error.
        from app.services.input_adapters import ingest_text
        from app.services.product_intelligence import understand_product

        understanding = understand_product(
            ingest_text("A short note about nothing in particular.", name="note.txt"),
            None,
            product_name="Nothing",
        ).understanding

        result = registry.get("process_planning").execute(
            {"understanding": understanding}, SkillContext()
        )
        assert result.status is SkillStatus.NOT_APPLICABLE
        assert result.data is None

    def test_a_completed_run_always_has_a_limiting_stage(self, registry, demo_factory):
        # SystemKPI.bottleneck_machine_id is a required str, so the skill
        # needs no None branch — and this pins the guarantee it relies on.
        from app.models.simulation import SystemKPI

        assert SystemKPI.model_fields["bottleneck_machine_id"].is_required()

        factory, product_id = demo_factory
        result = registry.get("factory_simulation").execute(
            {"factory": factory, "product_id": product_id}, SkillContext()
        )
        assert result.data.system.bottleneck_machine_id

    def test_process_planning_is_partial_when_a_requirement_is_unanswered(self, registry):
        from app.services.input_adapters import ingest_pdf
        from app.services.product_intelligence import understand_product

        understanding = understand_product(
            ingest_pdf(PDF.read_bytes(), name=PDF.name), None, product_name="CEC-120"
        ).understanding

        result = registry.get("process_planning").execute(
            {"understanding": understanding}, SkillContext()
        )
        # The document names an enclosure and no rule proposes an operation for it — the
        # closure operation is derived from the LID.
        assert result.status is SkillStatus.PARTIAL
        assert "component.enclosure" in result.unresolved_inputs

    def test_a_deterministic_skill_works_with_no_model(self, registry):
        from app.services.input_adapters import ingest_pdf

        result = registry.get("product_understanding").execute(
            {"ingestion": ingest_pdf(PDF.read_bytes(), name=PDF.name)},
            SkillContext(llm_provider=None),  # the golden path
        )
        assert result.usable
        assert result.data.facts


# Orchestration

class TestOrchestrator:
    def test_a_workflow_records_the_versions_it_used(self, orchestrator, demo_factory):
        factory, product_id = demo_factory
        run = orchestrator.run(VERIFY_CONCEPT, {"factory": factory, "product_id": product_id})
        assert run.versions == {"factory_simulation": "1.0.0", "bottleneck_analysis": "1.0.0"}

    def test_a_blocked_required_stage_stops_the_run(self, orchestrator):
        # And does NOT invent a factory to keep going.
        run = orchestrator.run(VERIFY_CONCEPT, {})
        assert run.completed is False
        assert run.stopped_at == "factory_simulation"
        assert run.status is SkillStatus.BLOCKED

    def test_an_optional_stage_that_cannot_run_does_not_stop_the_run(self, registry):
        orchestrator = EngineeringSkillOrchestrator(registry)
        workflow = WorkflowDefinition(
            id="TEST",
            name="test",
            description="test",
            stages=(
                WorkflowStage(
                    skill_id="equipment_discovery",
                    payload=lambda bag: {"requirement": None},
                    output_key="equipment",
                    required=False,
                ),
            ),
        )
        run = orchestrator.run(workflow, {})
        assert run.completed is True

    def test_a_workflow_naming_an_unregistered_skill_is_refused_before_running(self, registry):
        orchestrator = EngineeringSkillOrchestrator(registry)
        workflow = WorkflowDefinition(
            id="BAD",
            name="bad",
            description="bad",
            stages=(WorkflowStage(skill_id="nope", payload=lambda bag: {}, output_key="x"),),
        )
        assert orchestrator.validate(workflow)
        run = orchestrator.run(workflow, {})
        assert run.completed is False

    def test_a_stage_running_before_its_prerequisite_is_caught(self, registry):
        orchestrator = EngineeringSkillOrchestrator(registry)
        workflow = WorkflowDefinition(
            id="OUT_OF_ORDER",
            name="out of order",
            description="bottleneck before simulation",
            stages=(
                WorkflowStage(
                    skill_id="bottleneck_analysis", payload=lambda bag: {}, output_key="b"
                ),
                WorkflowStage(
                    skill_id="factory_simulation", payload=lambda bag: {}, output_key="s"
                ),
            ),
        )
        problems = orchestrator.validate(workflow)
        assert any("prerequisite" in p for p in problems)

    def test_a_run_with_unresolved_inputs_is_partial_not_success(self, orchestrator):
        from app.services.input_adapters import ingest_pdf

        run = orchestrator.run(
            workflow_by_id("PRODUCT_TO_PROCESS"),
            {"ingestion": ingest_pdf(PDF.read_bytes(), name=PDF.name), "product_name": "CEC-120"},
        )
        assert run.completed is True
        assert run.status is SkillStatus.PARTIAL
        assert run.unresolved_inputs

    def test_the_trace_reads_as_an_account_of_what_happened(self, orchestrator, demo_factory):
        factory, product_id = demo_factory
        run = orchestrator.run(VERIFY_CONCEPT, {"factory": factory, "product_id": product_id})
        summary = run.summary()

        assert "factory_simulation@1.0.0" in summary
        assert "1,105 of 1,900" in summary
        assert "m-screwdriving" in summary

    def test_every_declared_workflow_validates(self, orchestrator):
        # A workflow nobody can run is worse than no workflow.
        for workflow in ALL_WORKFLOWS:
            assert orchestrator.validate(workflow) == [], workflow.id

    def test_the_orchestrator_never_substitutes_example_data(self, orchestrator):
        # The single most important thing it must not do.
        run = orchestrator.run(workflow_by_id("FACTORY_REQUIREMENTS_TO_CONCEPT"), {"brief": ""})
        assert run.completed is False
        blob = json.dumps(run.warnings)
        assert "Demo Dataset" not in blob


# Provenance across skill boundaries

class TestProvenanceSurvives:
    def test_document_to_process_keeps_the_evidence_chain(self, orchestrator):
        from app.services.input_adapters import ingest_pdf

        run = orchestrator.run(
            workflow_by_id("PRODUCT_TO_PROCESS"),
            {"ingestion": ingest_pdf(PDF.read_bytes(), name=PDF.name), "product_name": "CEC-120"},
        )

        draft = run.outputs["process_draft"]
        for operation in draft.operations:
            assert operation.source_fact_keys
            assert operation.evidence
            assert all(e.quote and e.page is not None for e in operation.evidence)

    def test_a_rule_derived_operation_is_not_relabelled_by_the_framework(self, orchestrator):
        from app.models.product import FactStatus
        from app.services.input_adapters import ingest_pdf

        run = orchestrator.run(
            workflow_by_id("PRODUCT_TO_PROCESS"),
            {"ingestion": ingest_pdf(PDF.read_bytes(), name=PDF.name), "product_name": "CEC-120"},
        )
        for operation in run.outputs["process_draft"].operations:
            assert operation.fact_status is FactStatus.RULE_DERIVED

    def test_a_simulated_value_is_labelled_simulated(self, registry, demo_factory):
        factory, product_id = demo_factory
        result = registry.get("factory_simulation").execute(
            {"factory": factory, "product_id": product_id}, SkillContext()
        )
        assert result.provenance["throughput"] == "SIMULATED"

    def test_the_framework_defines_no_provenance_of_its_own(self, registry):
        # Every value a skill declares must already exist in the domain's vocabulary.
        from app.models.concept import ValueSource
        from app.models.product import FactStatus

        known = {v.value for v in ValueSource} | {f.value for f in FactStatus}
        for definition in registry.list_enabled():
            for value in definition.supported_provenance:
                assert value in known, f"{definition.id} invents provenance '{value}'"


# Custom skills

class TestCustomSkillExtension:
    def test_a_company_skill_registers_without_touching_anything_else(self, registry):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        before = len(registry.list_enabled())
        registry.register(AvoidHighCapexPreferenceSkill())

        assert len(registry.list_enabled()) == before + 1
        definition = registry.definition("avoid_high_capex_preference")
        assert definition.namespace == "acme"
        assert definition.qualified_id.startswith("acme/")

    def test_a_company_skill_cannot_outrank_a_first_party_capability(self, registry):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        registry.register(AvoidHighCapexPreferenceSkill())
        assert registry.definition("avoid_high_capex_preference").priority < 50

    def test_the_policy_annotates_without_altering_any_verified_value(self, registry):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        skill = AvoidHighCapexPreferenceSkill()

        class Cost:
            known_capex = 205_000.0

        class Option:
            strategy_id = "s1"
            cost = Cost()
            commercially_complete = True
            metrics = "UNTOUCHED"

        option = Option()
        result = skill.execute({"strategies": [option]}, SkillContext())

        assert result.data[0].verdict == "ABOVE_THRESHOLD"
        # The plan itself is unchanged: a preference annotates, never edits.
        assert option.metrics == "UNTOUCHED"
        assert option.cost.known_capex == 205_000.0

    def test_the_policy_refuses_to_judge_an_unpriced_plan(self, registry):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        class Cost:
            known_capex = 0.0

        class Unpriced:
            strategy_id = "s2"
            cost = Cost()
            commercially_complete = False

        result = AvoidHighCapexPreferenceSkill().execute(
            {"strategies": [Unpriced()]}, SkillContext()
        )
        # A €0 known sum is not "within budget" — it is an unanswered
        # question, and the policy says so.
        assert result.data[0].verdict == "COST_UNKNOWN"
        assert result.status is SkillStatus.PARTIAL

    def test_the_threshold_comes_from_configuration_not_from_source(self, registry):
        from app.skills.custom_example import AvoidHighCapexPreferenceSkill

        class Cost:
            known_capex = 90_000.0

        class Option:
            strategy_id = "s3"
            cost = Cost()
            commercially_complete = True

        skill = AvoidHighCapexPreferenceSkill()
        strict = SkillContext(settings={"avoid_high_capex_preference": {"threshold_eur": 50_000}})
        assert skill.execute({"strategies": [Option()]}, strict).data[0].verdict == "ABOVE_THRESHOLD"
        assert (
            skill.execute({"strategies": [Option()]}, SkillContext()).data[0].verdict
            == "WITHIN_POLICY"
        )


# A minimal skill, used by the version tests above

class _MinimalSkill(Skill):
    version = "1.0.0"

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="minimal",
            version=self.version,
            name="Minimal",
            description="A skill that does nothing, for registry tests.",
            category=SkillCategory.VALIDATION,
        )

    def execute(self, payload, context) -> SkillResult:
        return SkillResult(status=SkillStatus.SUCCESS, data=payload)
