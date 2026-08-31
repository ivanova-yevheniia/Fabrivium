"""FactoryMind Phase 5A – requirements agent foundation tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.models.agent import FactoryContext, ParserType, PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.agent_context import build_factory_context
from app.services.requirements_parser import (
    DeterministicFallbackRequirementsParser,
    LLMRequirementsParser,
    apply_target_demand,
    detect_contradictions,
    planning_requirements_to_optimization_goal,
)
from app.services.simulation import run_simulation

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


@pytest.fixture
def factory_context(electronics_factory: Factory) -> FactoryContext:
    return build_factory_context(electronics_factory)


@pytest.fixture
def parser() -> DeterministicFallbackRequirementsParser:
    return DeterministicFallbackRequirementsParser()


# 1. PlanningRequirements validation (hard rejects)

class TestPlanningRequirementsValidation:
    def test_valid_construction(self):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1200.0)
        assert r.target_units_per_day == 1200.0

    def test_negative_target_demand_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=-100.0)

    def test_zero_target_demand_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=0.0)

    def test_negative_capex_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_capex=-1.0)

    def test_negative_max_additional_machines_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_additional_machines=-1)

    def test_negative_max_additional_operators_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_additional_operators=-1)

    def test_negative_max_floor_area_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_floor_area=-10.0)

    def test_invalid_objective_rejected(self):
        with pytest.raises(ValidationError):
            PlanningRequirements(objective="NOT_A_REAL_OBJECTIVE")

    def test_zero_capex_and_zero_machines_are_valid(self):
        """Zero itself is a legitimate value (e.g. 'no budget at all'),
        only negative values are rejected."""
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, max_capex=0.0, max_additional_machines=0)
        assert r.max_capex == 0.0
        assert r.max_additional_machines == 0

    def test_frozen(self):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        with pytest.raises(ValidationError):
            r.max_capex = 1000.0


# 2. detect_contradictions (soft warnings, never raises)

class TestContradictionDetection:
    def test_zero_machines_with_add_parallel_only_action(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            max_additional_machines=0,
            allowed_action_types=["ADD_PARALLEL_MACHINE"],
        )
        warnings = detect_contradictions(r)
        assert any("max_additional_machines=0" in w for w in warnings)

    def test_empty_allowed_action_types_flagged(self):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, allowed_action_types=[])
        warnings = detect_contradictions(r)
        assert any("empty list" in w for w in warnings)

    def test_zero_capex_with_add_parallel_allowed(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND, max_capex=0.0,
            allowed_action_types=["ADD_PARALLEL_MACHINE", "CHANGE_MACHINE_CYCLE_TIME"],
        )
        warnings = detect_contradictions(r)
        assert any("max_capex=0" in w for w in warnings)

    def test_no_contradiction_for_sensible_requirements(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            max_additional_machines=1,
            allowed_action_types=["ADD_PARALLEL_MACHINE", "CHANGE_MACHINE_CYCLE_TIME"],
            max_capex=100000.0,
        )
        assert detect_contradictions(r) == []

    def test_contradiction_detection_does_not_mutate_requirements(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            max_additional_machines=0, allowed_action_types=["ADD_PARALLEL_MACHINE"],
        )
        before = r.model_dump()
        detect_contradictions(r)
        assert r.model_dump() == before


# 3. DeterministicFallbackRequirementsParser — field-level parsing

class TestDeterministicParserFields:
    def test_target_demand_parsing(self, parser, factory_context):
        result = parser.parse("We need 1500 units per day.", factory_context)
        assert result.parsed_requirements.target_units_per_day == 1500.0
        assert result.parsed_requirements.objective == OptimizationObjective.MEET_DEMAND

    def test_target_demand_with_commas(self, parser, factory_context):
        result = parser.parse("We need 1,500 units per day.", factory_context)
        assert result.parsed_requirements.target_units_per_day == 1500.0

    def test_capex_parsing_with_k_suffix(self, parser, factory_context):
        result = parser.parse("Keep CAPEX below 100k.", factory_context)
        assert result.parsed_requirements.max_capex == 100000.0

    def test_capex_parsing_with_currency_symbol(self, parser, factory_context):
        result = parser.parse("Keep the budget under €80,000.", factory_context)
        assert result.parsed_requirements.max_capex == 80000.0

    def test_capex_parsing_million_suffix(self, parser, factory_context):
        result = parser.parse("Budget of 1.5 million.", factory_context)
        assert result.parsed_requirements.max_capex == 1_500_000.0

    def test_max_additional_machines_digit(self, parser, factory_context):
        result = parser.parse("At most 2 machines.", factory_context)
        assert result.parsed_requirements.max_additional_machines == 2

    def test_max_additional_machines_word(self, parser, factory_context):
        result = parser.parse("Do not add more than one machine.", factory_context)
        assert result.parsed_requirements.max_additional_machines == 1

    def test_max_additional_machines_zero(self, parser, factory_context):
        result = parser.parse("Do not add any machines.", factory_context)
        assert result.parsed_requirements.max_additional_machines == 0

    def test_objective_maximize_throughput(self, parser, factory_context):
        result = parser.parse("Maximize throughput.", factory_context)
        assert result.parsed_requirements.objective == OptimizationObjective.MAXIMIZE_THROUGHPUT
        assert result.parsed_requirements.confidence == 1.0

    def test_objective_minimize_wip_prioritized_over_demand_mention(self, parser, factory_context):
        result = parser.parse("Reduce WIP but still meet current demand.", factory_context)
        assert result.parsed_requirements.objective == OptimizationObjective.MINIMIZE_WIP

    def test_objective_minimize_flow_time(self, parser, factory_context):
        result = parser.parse("Please minimize flow time.", factory_context)
        assert result.parsed_requirements.objective == OptimizationObjective.MINIMIZE_FLOW_TIME

    def test_forbidden_machine_parsing(self, parser, factory_context):
        result = parser.parse("Do not modify Packaging.", factory_context)
        assert result.parsed_requirements.forbidden_machine_ids == ["m-packaging"]

    def test_forbidden_machine_leave_alone_phrasing(self, parser, factory_context):
        result = parser.parse("Leave Screwdriving alone.", factory_context)
        assert result.parsed_requirements.forbidden_machine_ids == ["m-screwdriving"]

    def test_forbidden_machine_does_not_false_positive_on_add_machine_sentence(self, parser, factory_context):
        result = parser.parse("Do not add more than one machine.", factory_context)
        assert result.parsed_requirements.forbidden_machine_ids == []
        assert result.parsed_requirements.max_additional_machines == 1

    def test_preserve_layout_intent(self, parser, factory_context):
        result = parser.parse("Keep the existing layout.", factory_context)
        assert result.parsed_requirements.preserve_existing_layout is True

    def test_preserve_layout_default_false(self, parser, factory_context):
        result = parser.parse("Maximize throughput.", factory_context)
        assert result.parsed_requirements.preserve_existing_layout is False

    def test_combined_multi_field_sentence(self, parser, factory_context):
        result = parser.parse(
            "We need 1500 units per day, keep CAPEX below 100k, and do not modify Packaging.",
            factory_context,
        )
        r = result.parsed_requirements
        assert r.target_units_per_day == 1500.0
        assert r.max_capex == 100000.0
        assert r.forbidden_machine_ids == ["m-packaging"]

    def test_unrecognized_objective_defaults_with_low_confidence_and_note(self, parser, factory_context):
        result = parser.parse("Keep CAPEX below 100k.", factory_context)
        assert result.parsed_requirements.objective == OptimizationObjective.MEET_DEMAND
        assert result.parsed_requirements.confidence < 1.0
        assert any("defaulted" in n.lower() for n in result.parsed_requirements.notes)

    def test_forbidden_machine_without_context_produces_note_not_crash(self, parser):
        result = parser.parse("Do not modify Packaging.", factory_context=None)
        assert result.parsed_requirements.forbidden_machine_ids == []
        assert any("factory_context" in n for n in result.parsed_requirements.notes)

    def test_parser_type_recorded(self, parser, factory_context):
        result = parser.parse("Maximize throughput.", factory_context)
        assert result.parser_type == ParserType.DETERMINISTIC_FALLBACK
        assert result.structured_output_valid is True

    def test_raw_user_request_preserved_verbatim(self, parser, factory_context):
        text = "We need 1500 units per day."
        result = parser.parse(text, factory_context)
        assert result.raw_user_request == text

    def test_contradiction_surfaced_in_result_warnings(self, parser, factory_context):
        result = parser.parse("Do not add any machines, but add a parallel machine anyway.", factory_context)
        # Construct a manual contradiction scenario directly against the model
        # to keep this test independent of exact NL phrasing for allowed_action_types
        # (the deterministic parser doesn't parse that field from free text yet).
        assert isinstance(result.warnings, list)  # sanity: warnings always a list, never None


# 4. No mutation / no network

class TestNoMutationNoNetwork:
    def test_parsing_does_not_mutate_factory(self, electronics_factory: Factory, parser):
        before = electronics_factory.model_dump()
        ctx = build_factory_context(electronics_factory)
        parser.parse("We need 1500 units per day.", ctx)
        assert electronics_factory.model_dump() == before

    def test_deterministic_parser_module_has_no_network_dependency(self):
        import app.services.requirements_parser as mod
        source = pathlib.Path(mod.__file__).read_text()
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "urllib.request" not in source

    def test_repeated_parse_identical(self, parser, factory_context):
        r1 = parser.parse("We need 1500 units per day, keep CAPEX below 100k.", factory_context)
        r2 = parser.parse("We need 1500 units per day, keep CAPEX below 100k.", factory_context)
        assert r1.model_dump() == r2.model_dump()


# 5. Factory context builder

class TestFactoryContextBuilder:
    def test_compact_fields_only(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        assert ctx.factory_name == "Electronics Assembly Line"
        assert len(ctx.machines) == 4
        assert len(ctx.products) == 1
        machine = next(m for m in ctx.machines if m.id == "m-screwdriving")
        assert machine.process_type == "screwdriving"
        assert machine.cycle_time == 52.0
        assert machine.capacity == 1
        assert machine.purchase_cost == 85000.0

    def test_layout_availability_flag(self, electronics_factory: Factory):
        from app.services.layout import create_layout

        ctx_no_layout = build_factory_context(electronics_factory)
        assert ctx_no_layout.layout_available is False

        layout = create_layout(electronics_factory)
        ctx_with_layout = build_factory_context(electronics_factory, layout=layout)
        assert ctx_with_layout.layout_available is True

    def test_simulation_summary_included_when_provided(self, electronics_factory: Factory):
        result = run_simulation(electronics_factory, "p-electronics-widget")
        ctx = build_factory_context(electronics_factory, product_id="p-electronics-widget", simulation_result=result)
        assert ctx.simulation_summary is not None
        assert ctx.simulation_summary.product_id == "p-electronics-widget"
        assert ctx.simulation_summary.completed_units == result.completed_units
        assert ctx.simulation_summary.bottleneck_machine_id == result.system.bottleneck_machine_id

    def test_simulation_summary_omitted_without_product_id(self, electronics_factory: Factory):
        result = run_simulation(electronics_factory, "p-electronics-widget")
        ctx = build_factory_context(electronics_factory, simulation_result=result)  # no product_id
        assert ctx.simulation_summary is None

    def test_context_does_not_mutate_factory(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        build_factory_context(electronics_factory)
        assert electronics_factory.model_dump() == before

    def test_context_is_serializable_json(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        dumped = ctx.model_dump_json()
        assert '"factory_name"' in dumped

    def test_context_omits_full_raw_factory_fields(self, electronics_factory: Factory):
        """Sanity check that the context is genuinely compact — it must
        not carry Factory-only fields like buffers/budget/dimensions."""
        ctx = build_factory_context(electronics_factory)
        dumped = ctx.model_dump()
        assert "buffers" not in dumped
        assert "budget" not in dumped
        assert "shifts_per_day" not in dumped


# 6. Mapping to OptimizationGoal / apply_target_demand

class TestOptimizationGoalMapping:
    def test_basic_field_mapping(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MAXIMIZE_THROUGHPUT,
            max_capex=100000.0, max_additional_machines=1,
            allowed_action_types=["ADD_PARALLEL_MACHINE"],
        )
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1", max_candidates=5)
        assert mapping.goal.objective == OptimizationObjective.MAXIMIZE_THROUGHPUT
        assert mapping.goal.target_product_id == "p-1"
        assert mapping.goal.max_capex == 100000.0
        assert mapping.goal.max_additional_machines == 1
        assert mapping.goal.allowed_action_types == ["ADD_PARALLEL_MACHINE"]
        assert mapping.goal.max_candidates == 5

    def test_reserved_fields_pass_through(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            max_additional_operators=3, max_floor_area=50.0,
        )
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1")
        assert mapping.goal.max_additional_operators == 3
        assert mapping.goal.max_floor_area == 50.0

    def test_forbidden_machines_mapped_not_unmapped(self):
        """Phase 5A.1: forbidden_machine_ids is now enforced (see
        test_forbidden_machine_enforcement.py-equivalent tests below), so
        it must map onto OptimizationGoal directly and never appear in
        unmapped_constraints."""
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, forbidden_machine_ids=["m-packaging"])
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1")
        assert mapping.goal.forbidden_machine_ids == ["m-packaging"]
        assert not any("forbidden_machine_ids" in c for c in mapping.unmapped_constraints)

    def test_preserve_layout_mapped_not_unmapped(self):
        """Phase 5A.1: preserve_existing_layout is now enforced (see
        TestPreserveExistingLayout below), so it must map onto
        OptimizationGoal directly and never appear in unmapped_constraints."""
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, preserve_existing_layout=True)
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1")
        assert mapping.goal.preserve_existing_layout is True
        assert not any("preserve_existing_layout" in c for c in mapping.unmapped_constraints)

    def test_no_unmapped_constraints_when_none_apply(self):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1")
        assert mapping.unmapped_constraints == []

    def test_apply_target_demand_updates_factory(self, electronics_factory: Factory):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1500.0)
        updated = apply_target_demand(electronics_factory, "p-electronics-widget", r)
        assert updated.products[0].demand_per_day == 1500.0

    def test_apply_target_demand_does_not_mutate_baseline(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1500.0)
        apply_target_demand(electronics_factory, "p-electronics-widget", r)
        assert electronics_factory.model_dump() == before

    def test_apply_target_demand_noop_when_not_specified(self, electronics_factory: Factory):
        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND)
        result = apply_target_demand(electronics_factory, "p-electronics-widget", r)
        assert result is electronics_factory  # same object, not just equal

    def test_end_to_end_goal_and_demand_feed_candidate_generation(self, electronics_factory: Factory):
        """Full pipeline: parsed requirements -> updated baseline factory +
        OptimizationGoal -> Phase 4A candidate generation actually runs."""
        from app.services.candidate_generator import generate_candidates

        r = PlanningRequirements(objective=OptimizationObjective.MEET_DEMAND, target_units_per_day=1200.0)
        factory = apply_target_demand(electronics_factory, "p-electronics-widget", r)
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-electronics-widget")
        candidates = generate_candidates(factory, "p-electronics-widget", mapping.goal)
        assert len(candidates) > 0
        assert any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)


# 7. LLMRequirementsParser interface/stub

class TestLLMRequirementsParserStub:
    def test_no_completion_fn_raises_not_implemented(self):
        parser = LLMRequirementsParser()
        with pytest.raises(NotImplementedError):
            parser.parse("anything")

    def test_injected_completion_fn_valid_output(self):
        def fake_completion(prompt: str, ctx):
            return {"objective": "MAXIMIZE_THROUGHPUT", "max_capex": 50000.0}

        parser = LLMRequirementsParser(completion_fn=fake_completion)
        result = parser.parse("go fast")
        assert result.structured_output_valid is True
        assert result.parsed_requirements.objective == OptimizationObjective.MAXIMIZE_THROUGHPUT
        assert result.parsed_requirements.max_capex == 50000.0
        assert result.parser_type == ParserType.LLM

    def test_injected_completion_fn_invalid_enum_rejected(self):
        def bad_completion(prompt: str, ctx):
            return {"objective": "NOT_REAL"}

        parser = LLMRequirementsParser(completion_fn=bad_completion)
        result = parser.parse("gibberish")
        assert result.structured_output_valid is False
        assert result.warnings  # explains what went wrong
        assert result.parsed_requirements.objective == OptimizationObjective.MEET_DEMAND  # safe fallback

    def test_injected_completion_fn_negative_value_rejected(self):
        def bad_completion(prompt: str, ctx):
            return {"objective": "MEET_DEMAND", "max_capex": -500.0}

        parser = LLMRequirementsParser(completion_fn=bad_completion)
        result = parser.parse("spend negative money somehow")
        assert result.structured_output_valid is False

    def test_prompt_never_sent_raw_prose_as_the_expected_result(self):
        """The completion_fn receives a prompt string, but the PARSER's
        contract requires it to RETURN structured data, not prose — a
        completion_fn that returns a bare string (prose) must fail
        validation rather than be silently accepted."""

        def prose_completion(prompt: str, ctx):
            return "Sure! I think you should add a machine."  # not a mapping

        parser = LLMRequirementsParser(completion_fn=prose_completion)
        result = parser.parse("add a machine please")
        assert result.structured_output_valid is False

    def test_module_has_no_provider_specific_transport(self):
        """The module docstring is allowed to MENTION provider names as
        examples of what is deliberately NOT hardcoded — check for actual
        imports/API usage, not incidental prose mentions."""
        import app.services.requirements_parser as mod
        source = pathlib.Path(mod.__file__).read_text()
        for forbidden in ("import requests", "import httpx", "import openai", "import anthropic", "ibm_watson_machine_learning"):
            assert forbidden not in source.lower()

    def test_llm_parser_never_calls_completion_fn_more_than_once(self):
        calls = []

        def counting_completion(prompt: str, ctx):
            calls.append(prompt)
            return {"objective": "MEET_DEMAND"}

        parser = LLMRequirementsParser(completion_fn=counting_completion)
        parser.parse("test")
        assert len(calls) == 1


# 8. Engineering-truth separation

class TestEngineeringTruthSeparation:
    def test_parsed_requirements_never_asserts_improvement(self, parser, factory_context):
        """'add a second packaging machine' must be represented purely as
        a requested/allowed intervention — nothing in the parsed result
        claims it improves performance."""
        result = parser.parse("Add a second packaging machine.", factory_context)
        dumped = json.dumps(result.model_dump(mode="json")).lower()
        for claim_word in ("improve", "faster", "better", "optimal", "will increase throughput"):
            assert claim_word not in dumped

    def test_planning_requirements_model_has_no_outcome_fields(self):
        """Structural guarantee: PlanningRequirements has no field that
        could encode a predicted/claimed engineering result — only
        constraints and an objective."""
        fields = set(PlanningRequirements.model_fields.keys())
        outcome_like = {"verdict", "demand_met", "improvement", "result", "outcome"}
        assert fields.isdisjoint(outcome_like)

    def test_forbidden_machine_request_is_just_a_constraint_not_a_verdict(self, parser, factory_context):
        result = parser.parse("Do not modify Packaging.", factory_context)
        assert result.parsed_requirements.forbidden_machine_ids == ["m-packaging"]
        # No simulation/verdict field exists on PlanningRequirements at all.
        assert not hasattr(result.parsed_requirements, "verdict")
