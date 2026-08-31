"""FactoryMind Phase 5A.1 – planning constraint propagation tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationGoal, OptimizationObjective
from app.services.agent_context import build_factory_context
from app.services.candidate_evaluator import evaluate_candidates
from app.services.candidate_generator import generate_candidates
from app.services.layout import create_layout, get_placement, place_machine
from app.services.requirements_parser import (
    DeterministicFallbackRequirementsParser,
    apply_target_demand,
    planning_requirements_to_optimization_goal,
)
from app.services.scenario import apply_scenario
from app.models.scenario import AddParallelMachineAction, Scenario

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


# Helpers / fixtures

def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture
def electronics_factory() -> Factory:
    return _load_electronics()


def _at_demand(factory: Factory, demand: float) -> Factory:
    return factory.model_copy(update={
        "products": [p.model_copy(update={"demand_per_day": demand}) for p in factory.products]
    })


def _goal(objective=OptimizationObjective.MEET_DEMAND, **overrides) -> OptimizationGoal:
    base = dict(objective=objective, target_product_id="p-electronics-widget")
    base.update(overrides)
    return OptimizationGoal(**base)


def _native_layout(factory: Factory, offset: float = 0.0):
    layout = create_layout(factory)
    for m in factory.machines:
        layout = place_machine(factory, layout, m.id, x=m.position_x + offset, y=m.position_y + offset)
    return layout


# 1. Forbidden machine enforcement (generation-level)

class TestForbiddenMachineEnforcement:
    def test_forbidden_bottleneck_machine_excluded(self, electronics_factory: Factory):
        """PHASE 8A CHANGE."""
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["m-screwdriving"])
        candidates = generate_candidates(factory, "p-electronics-widget", goal)

        assert candidates, "expected the machine-free levers to survive the forbidden list"
        for candidate in candidates:
            for action in candidate.scenario.actions:
                assert getattr(action, "machine_id", None) != "m-screwdriving"
        # Every survivor is a lever that targets no machine whatsoever.
        assert all(
            getattr(action, "machine_id", None) is None
            for candidate in candidates
            for action in candidate.scenario.actions
        )

    def test_forbidden_bottleneck_no_action_references_it(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["m-screwdriving"], allowed_action_types=None)
        candidates = generate_candidates(factory, "p-electronics-widget", goal)
        for c in candidates:
            for action in c.scenario.actions:
                assert getattr(action, "machine_id", None) != "m-screwdriving"

    def test_forbidden_non_bottleneck_machine_does_not_affect_unrelated_candidates(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        baseline_ids = {c.candidate_id for c in generate_candidates(factory, "p-electronics-widget", _goal())}
        goal_forbid_packaging = _goal(forbidden_machine_ids=["m-packaging"])
        forbidden_ids = {c.candidate_id for c in generate_candidates(factory, "p-electronics-widget", goal_forbid_packaging)}
        # Packaging isn't congested anyway (no candidate targets it), so the
        # candidate SET is identical either way.
        assert baseline_ids == forbidden_ids
        assert "cand-add-parallel-m-screwdriving" in forbidden_ids

    def test_combined_candidate_removed_when_primary_action_forbidden(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["m-screwdriving"])
        candidates = generate_candidates(factory, "p-electronics-widget", goal)
        assert not any(c.generation_source.value == "COMBINED" for c in candidates)

    def test_combined_candidate_removed_when_secondary_action_forbidden(self, electronics_factory: Factory):
        """The combined candidate at 1200/day pairs Screwdriving (primary)
        with Assembly (secondary, cycle-time action) — forbidding Assembly
        alone must still drop the whole combined candidate, even though
        Screwdriving itself remains fully permitted."""
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["m-assembly"])
        candidates = generate_candidates(factory, "p-electronics-widget", goal)
        assert not any(c.candidate_id == "cand-combined-m-screwdriving-m-assembly" for c in candidates)
        # Screwdriving-only candidates remain unaffected.
        assert any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)

    def test_baseline_factory_immutable(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        before = factory.model_dump()
        generate_candidates(factory, "p-electronics-widget", _goal(forbidden_machine_ids=["m-screwdriving"]))
        assert factory.model_dump() == before

    def test_deterministic_with_forbidden_ids(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["m-assembly"])
        r1 = generate_candidates(factory, "p-electronics-widget", goal)
        r2 = generate_candidates(factory, "p-electronics-widget", goal)
        assert [c.model_dump() for c in r1] == [c.model_dump() for c in r2]

    def test_nonexistent_forbidden_id_is_harmless(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        goal = _goal(forbidden_machine_ids=["does-not-exist"])
        candidates = generate_candidates(factory, "p-electronics-widget", goal)
        assert any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)


# 2. Process-pool expansion semantics

class TestForbiddenPoolExpansion:
    def test_forbidding_root_covers_existing_clone(self, electronics_factory: Factory):
        """Add a parallel Screwdriving clone first, then forbid the ROOT
        machine — the clone must ALSO be off-limits to any new candidate
        action, since forbidding the logical process forbids every
        physical machine currently serving it."""
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        factory = apply_scenario(_at_demand(electronics_factory, 1600.0), scenario)

        goal = _goal(forbidden_machine_ids=["m-screwdriving"], allowed_action_types=["CHANGE_MACHINE_CYCLE_TIME", "CHANGE_MACHINE_CAPACITY"])
        candidates = generate_candidates(factory, "p-electronics-widget", goal)
        for c in candidates:
            for action in c.scenario.actions:
                assert getattr(action, "machine_id", None) not in ("m-screwdriving", "m-screwdriving-parallel-1")

    def test_forbidding_specific_clone_does_not_forbid_root(self, electronics_factory: Factory):
        """Forbidding an EXPLICITLY-named clone id does not expand to the
        whole pool — the root machine remains eligible."""
        scenario = Scenario(id="s", name="x", actions=[AddParallelMachineAction(machine_id="m-screwdriving")])
        factory = apply_scenario(_at_demand(electronics_factory, 1600.0), scenario)

        from app.services.candidate_generator import _expand_forbidden_machine_ids

        expanded = _expand_forbidden_machine_ids(factory, ["m-screwdriving-parallel-1"])
        assert expanded == frozenset({"m-screwdriving-parallel-1"})
        assert "m-screwdriving" not in expanded

    def test_expand_root_returns_whole_pool(self, electronics_factory: Factory):
        scenario = Scenario(
            id="s", name="x",
            actions=[
                AddParallelMachineAction(machine_id="m-screwdriving"),
                AddParallelMachineAction(machine_id="m-screwdriving"),
            ],
        )
        factory = apply_scenario(_at_demand(electronics_factory, 1600.0), scenario)

        from app.services.candidate_generator import _expand_forbidden_machine_ids

        expanded = _expand_forbidden_machine_ids(factory, ["m-screwdriving"])
        assert expanded == frozenset({
            "m-screwdriving", "m-screwdriving-parallel-1", "m-screwdriving-parallel-2",
        })

    def test_expand_standalone_machine_with_no_clones_is_itself(self, electronics_factory: Factory):
        from app.services.candidate_generator import _expand_forbidden_machine_ids

        expanded = _expand_forbidden_machine_ids(electronics_factory, ["m-packaging"])
        assert expanded == frozenset({"m-packaging"})


# 3. Preserve-existing-layout enforcement (evaluation-level)

class TestPreserveExistingLayout:
    def test_existing_placements_unchanged_when_new_machine_added(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        original = {p.machine_id: (p.x, p.y, p.z, p.rotation_deg) for p in layout.placements}

        goal = _goal(preserve_existing_layout=True, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = next(e for e in result.candidates if e.candidate.candidate_id == "cand-add-parallel-m-screwdriving")

        assert evaluation.status.value == "FEASIBLE"
        for machine_id, pos in original.items():
            placement = get_placement(evaluation.candidate_layout, machine_id)
            assert (placement.x, placement.y, placement.z, placement.rotation_deg) == pos

    def test_new_machine_still_placed(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)

        goal = _goal(preserve_existing_layout=True, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = next(e for e in result.candidates if e.candidate.candidate_id == "cand-add-parallel-m-screwdriving")

        assert evaluation.status.value == "FEASIBLE"
        placement = get_placement(evaluation.candidate_layout, "m-screwdriving-parallel-1")
        assert placement is not None

    def test_crowded_preserved_layout_rejects_rather_than_rearranges(self, electronics_factory: Factory):
        factory = electronics_factory.model_copy(update={"width": 10.0, "length": 2.0})
        factory = _at_demand(factory, 1200.0)
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
        layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
        layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)
        before = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}

        goal = _goal(preserve_existing_layout=True, allowed_action_types=["ADD_PARALLEL_MACHINE"], max_candidates=1)
        result = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout, max_position_attempts=300)
        evaluation = next(e for e in result.candidates if e.candidate.candidate_id == "cand-add-parallel-m-screwdriving")

        assert evaluation.status.value == "INFEASIBLE"
        assert evaluation.rejection_reasons[0].value == "PLACEMENT_NOT_FOUND"
        # Baseline layout object itself is untouched regardless.
        assert {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements} == before

    def test_preserve_layout_false_behaves_identically_today(self, electronics_factory: Factory):
        """No Phase 4A action type currently repositions an existing
        machine, so preserve_existing_layout=False must produce the exact
        same result as True today — the flag only matters once a future
        action type could rearrange things."""
        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)

        goal_true = _goal(preserve_existing_layout=True, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        goal_false = _goal(preserve_existing_layout=False, allowed_action_types=["ADD_PARALLEL_MACHINE"])
        result_true = evaluate_candidates(factory, "p-electronics-widget", goal_true, layout=layout)
        result_false = evaluate_candidates(factory, "p-electronics-widget", goal_false, layout=layout)

        statuses_true = [e.status for e in result_true.candidates]
        statuses_false = [e.status for e in result_false.candidates]
        assert statuses_true == statuses_false

    def test_verification_helper_detects_moved_placement(self):
        from app.models.layout import FactoryLayout, MachinePlacement
        from app.services.candidate_evaluator import _verify_existing_placements_preserved

        baseline = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[MachinePlacement(machine_id="m-1", x=5.0, y=5.0, rotation_deg=0.0)],
        )
        moved = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[MachinePlacement(machine_id="m-1", x=6.0, y=5.0, rotation_deg=0.0)],
        )
        assert _verify_existing_placements_preserved(baseline, moved) is False

    def test_verification_helper_allows_new_placement(self):
        from app.models.layout import FactoryLayout, MachinePlacement
        from app.services.candidate_evaluator import _verify_existing_placements_preserved

        baseline = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[MachinePlacement(machine_id="m-1", x=5.0, y=5.0, rotation_deg=0.0)],
        )
        with_new = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            placements=[
                MachinePlacement(machine_id="m-1", x=5.0, y=5.0, rotation_deg=0.0),
                MachinePlacement(machine_id="m-2", x=10.0, y=10.0, rotation_deg=0.0),
            ],
        )
        assert _verify_existing_placements_preserved(baseline, with_new) is True

    def test_verification_helper_detects_moved_zone(self):
        from app.models.layout import FactoryLayout, LayoutZone, LayoutZoneType
        from app.services.candidate_evaluator import _verify_existing_placements_preserved

        baseline = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            aisle_zones=[LayoutZone(id="a-1", name="Aisle", x=0.0, y=8.0, width=20.0, length=2.0, zone_type=LayoutZoneType.AISLE)],
        )
        moved_zone = FactoryLayout(
            factory_width=20.0, factory_length=20.0,
            aisle_zones=[LayoutZone(id="a-1", name="Aisle", x=0.0, y=9.0, width=20.0, length=2.0, zone_type=LayoutZoneType.AISLE)],
        )
        assert _verify_existing_placements_preserved(baseline, moved_zone) is False


# 4. Mapping no longer reports these as unmapped

class TestMappingCoverage:
    def test_forbidden_and_preserve_layout_never_unmapped(self):
        r = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            forbidden_machine_ids=["m-packaging"],
            preserve_existing_layout=True,
        )
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-1")
        assert mapping.unmapped_constraints == []
        assert mapping.goal.forbidden_machine_ids == ["m-packaging"]
        assert mapping.goal.preserve_existing_layout is True


# 5. Required end-to-end controls A-D

class TestControlA_ForbidBottleneckWithDemandTarget:
    def test_full_pipeline(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        parser = DeterministicFallbackRequirementsParser()
        result = parser.parse("We need 1500 units per day, but do not modify Screwdriving.", ctx)
        r = result.parsed_requirements
        assert r.target_units_per_day == 1500.0
        assert r.forbidden_machine_ids == ["m-screwdriving"]

        factory = apply_target_demand(electronics_factory, "p-electronics-widget", r)
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-electronics-widget")
        candidates = generate_candidates(factory, "p-electronics-widget", mapping.goal)

        # Phase 8A: see TestForbiddenMachineEnforcement
        # .test_forbidden_bottleneck_machine_excluded for why this is no
        # longer an empty list. The point of the control is that the
        # forbidden machine is never silently redirected around — which is
        # exactly what is asserted here.
        assert all(
            getattr(action, "machine_id", None) != "m-screwdriving"
            for candidate in candidates
            for action in candidate.scenario.actions
        )
        assert "cand-add-parallel-m-screwdriving" not in {c.candidate_id for c in candidates}
        assert electronics_factory.model_dump() == _load_electronics().model_dump()


class TestControlB_ForbidNonBottleneck:
    def test_screwdriving_recommendations_remain(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        parser = DeterministicFallbackRequirementsParser()
        result = parser.parse("Do not modify Packaging.", ctx)
        r = result.parsed_requirements
        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-electronics-widget")

        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", mapping.goal)
        assert any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)


class TestControlC_PreserveLayoutSpacious:
    def test_new_machine_placed_existing_unchanged(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        parser = DeterministicFallbackRequirementsParser()
        result = parser.parse("Keep the existing layout.", ctx)
        r = result.parsed_requirements
        assert r.preserve_existing_layout is True

        factory = electronics_factory.model_copy(update={"width": 200.0, "length": 100.0})
        factory = _at_demand(factory, 1200.0)
        layout = _native_layout(factory, offset=50.0)
        original = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}

        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-electronics-widget")
        goal = mapping.goal.model_copy(update={"allowed_action_types": ["ADD_PARALLEL_MACHINE"]})
        result_eval = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout)
        evaluation = next(e for e in result_eval.candidates if e.candidate.candidate_id == "cand-add-parallel-m-screwdriving")

        assert evaluation.status.value == "FEASIBLE"
        for machine_id, pos in original.items():
            placement = get_placement(evaluation.candidate_layout, machine_id)
            assert (placement.x, placement.y, placement.rotation_deg) == pos
        assert get_placement(evaluation.candidate_layout, "m-screwdriving-parallel-1") is not None


class TestControlD_PreserveLayoutCrowded:
    def test_candidate_infeasible_baseline_not_rearranged(self, electronics_factory: Factory):
        ctx = build_factory_context(electronics_factory)
        parser = DeterministicFallbackRequirementsParser()
        result = parser.parse("Keep the existing layout.", ctx)
        r = result.parsed_requirements

        factory = electronics_factory.model_copy(update={"width": 10.0, "length": 2.0})
        factory = _at_demand(factory, 1200.0)
        layout = create_layout(factory)
        layout = place_machine(factory, layout, "m-assembly", x=1.5, y=1.0)
        layout = place_machine(factory, layout, "m-screwdriving", x=4.25, y=1.0)
        layout = place_machine(factory, layout, "m-inspection", x=6.5, y=1.0)
        layout = place_machine(factory, layout, "m-packaging", x=8.75, y=1.0)
        before = {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements}

        mapping = planning_requirements_to_optimization_goal(r, target_product_id="p-electronics-widget")
        goal = mapping.goal.model_copy(update={"allowed_action_types": ["ADD_PARALLEL_MACHINE"], "max_candidates": 1})
        result_eval = evaluate_candidates(factory, "p-electronics-widget", goal, layout=layout, max_position_attempts=300)
        evaluation = next(e for e in result_eval.candidates if e.candidate.candidate_id == "cand-add-parallel-m-screwdriving")

        assert evaluation.status.value == "INFEASIBLE"
        assert {p.machine_id: (p.x, p.y, p.rotation_deg) for p in layout.placements} == before
