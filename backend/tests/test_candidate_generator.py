"""FactoryMind Phase 4A – deterministic optimization candidate generator tests."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.models.optimization import GenerationSource, OptimizationCandidate, OptimizationGoal, OptimizationObjective
from app.services.candidate_generator import generate_candidates
from app.services.scenario import apply_scenario
from app.services.simulation import run_simulation

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


def _action_types(candidate: OptimizationCandidate) -> list[str]:
    return [a.action_type for a in candidate.scenario.actions]


# 1. Model construction / defaults

class TestModels:
    def test_goal_defaults(self):
        goal = OptimizationGoal(objective=OptimizationObjective.MEET_DEMAND, target_product_id="p-1")
        assert goal.max_capex is None
        assert goal.max_additional_machines is None
        assert goal.allowed_action_types is None
        assert goal.max_candidates == 10
        assert goal.max_additional_operators is None
        assert goal.max_floor_area is None

    def test_goal_frozen(self):
        goal = _goal()
        with pytest.raises(Exception):
            goal.max_candidates = 5

    def test_all_objectives_constructible(self):
        for obj in OptimizationObjective:
            OptimizationGoal(objective=obj, target_product_id="p-1")

    def test_all_generation_sources_exist(self):
        assert {s.value for s in GenerationSource} == {
            "BOTTLENECK_RELIEF", "CAPACITY_EXPANSION", "CYCLE_TIME_IMPROVEMENT", "COMBINED",
            # Phase 8A: levers that are not "buy a machine".
            "SHIFT_EXPANSION", "OPERATOR_EXPANSION", "BUFFER_EXPANSION",
        }


# 2. Determinism

class TestDeterminism:
    def test_repeated_generation_identical(self, electronics_factory: Factory):
        goal = _goal()
        r1 = generate_candidates(electronics_factory, "p-electronics-widget", goal)
        r2 = generate_candidates(electronics_factory, "p-electronics-widget", goal)
        assert [c.model_dump() for c in r1] == [c.model_dump() for c in r2]

    def test_candidate_ids_stable_across_runs(self, electronics_factory: Factory):
        goal = _goal()
        r1 = generate_candidates(electronics_factory, "p-electronics-widget", goal)
        r2 = generate_candidates(electronics_factory, "p-electronics-widget", goal)
        assert [c.candidate_id for c in r1] == [c.candidate_id for c in r2]

    def test_baseline_factory_immutable(self, electronics_factory: Factory):
        before = electronics_factory.model_dump()
        generate_candidates(electronics_factory, "p-electronics-widget", _goal())
        assert electronics_factory.model_dump() == before

    def test_mismatched_product_id_raises(self, electronics_factory: Factory):
        goal = _goal(target_product_id="p-other")
        with pytest.raises(ValueError):
            generate_candidates(electronics_factory, "p-electronics-widget", goal)


# 3. Baseline (1200/day) — bottleneck-driven generation

class TestBaselineBottleneckDriven:
    @pytest.fixture
    def candidates(self, electronics_factory: Factory) -> list[OptimizationCandidate]:
        factory = _at_demand(electronics_factory, 1200.0)
        return generate_candidates(factory, "p-electronics-widget", _goal())

    def test_produces_candidates(self, candidates):
        assert len(candidates) > 0

    def test_all_candidates_target_screwdriving_or_assembly(self, candidates):
        """Screwdriving is the measured bottleneck; Assembly is the only
        other pool with meaningful utilization (72.9%) — nothing else
        should be targeted."""
        for c in candidates:
            assert set(c.affected_processes) <= {"m-screwdriving", "m-assembly"}

    def test_packaging_not_prioritized(self, candidates):
        """Packaging (~48% utilization, zero queue) must never appear —
        it is not congested, regardless of being a real machine in the
        route."""
        for c in candidates:
            assert "m-packaging" not in c.affected_processes
            for action in c.scenario.actions:
                assert getattr(action, "machine_id", None) != "m-packaging"

    def test_inspection_not_prioritized(self, candidates):
        for c in candidates:
            assert "m-inspection" not in c.affected_processes

    def test_add_parallel_screwdriving_present(self, candidates):
        ids = [c.candidate_id for c in candidates]
        assert "cand-add-parallel-m-screwdriving" in ids

    def test_add_parallel_rationale_matches_measured_data(self, candidates, electronics_factory):
        """
        The rationale must quote the ACTUAL measured baseline, not a remembered one.
        """
        from app.services.simulation import run_simulation

        baseline = run_simulation(_at_demand(electronics_factory, 1200.0), "p-electronics-widget")
        pool = next(p for p in baseline.process_pool_kpis if p.reference_machine_id == "m-screwdriving")

        cand = next(c for c in candidates if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert "Screwdriving" in cand.rationale
        assert "baseline bottleneck" in cand.rationale
        assert f"{pool.utilization:.2%}" in cand.rationale
        assert f"{pool.average_queue_length:.2f}" in cand.rationale

    def test_cycle_time_candidates_three_percentages(self, candidates):
        pct_ids = [c.candidate_id for c in candidates if c.generation_source == GenerationSource.CYCLE_TIME_IMPROVEMENT]
        assert pct_ids == [
            "cand-cycle-time-m-screwdriving-neg5pct",
            "cand-cycle-time-m-screwdriving-neg10pct",
            "cand-cycle-time-m-screwdriving-neg20pct",
        ]

    def test_cycle_time_candidates_require_cost_estimate(self, candidates):
        for c in candidates:
            if c.generation_source == GenerationSource.CYCLE_TIME_IMPROVEMENT:
                assert c.requires_cost_estimate is True
                assert c.estimated_capex == 0.0

    def test_capacity_candidate_present_and_uncosted(self, candidates):
        cand = next(c for c in candidates if c.candidate_id == "cand-capacity-m-screwdriving-plus1")
        assert cand.requires_cost_estimate is True
        assert cand.estimated_capex == 0.0
        action = cand.scenario.actions[0]
        assert action.capacity == 2  # 1 -> 2

    def test_combined_candidate_present(self, candidates):
        combined = [c for c in candidates if c.generation_source == GenerationSource.COMBINED]
        assert len(combined) == 1
        assert combined[0].candidate_id == "cand-combined-m-screwdriving-m-assembly"
        assert len(combined[0].scenario.actions) == 2

    def test_parallel_candidate_capex_matches_purchase_cost(self, candidates, electronics_factory: Factory):
        source = next(m for m in electronics_factory.machines if m.id == "m-screwdriving")
        cand = next(c for c in candidates if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert cand.estimated_capex == source.purchase_cost == 85000.0
        assert cand.requires_cost_estimate is False

    def test_add_parallel_requires_layout_placement(self, candidates):
        cand = next(c for c in candidates if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert cand.requires_layout_placement is True

    def test_cycle_time_and_capacity_do_not_require_layout_placement(self, candidates):
        for c in candidates:
            if c.generation_source in (GenerationSource.CYCLE_TIME_IMPROVEMENT, GenerationSource.CAPACITY_EXPANSION):
                assert c.requires_layout_placement is False

    def test_deterministic_type_priority_order(self, candidates):
        """ADD_PARALLEL_MACHINE candidates first, then cycle-time, then
        capacity, then combined — matches the documented generation order."""
        sources = [c.generation_source for c in candidates]
        first_capacity_idx = sources.index(GenerationSource.CAPACITY_EXPANSION)
        first_cycle_idx = sources.index(GenerationSource.CYCLE_TIME_IMPROVEMENT)
        first_bottleneck_idx = sources.index(GenerationSource.BOTTLENECK_RELIEF)
        assert first_bottleneck_idx < first_cycle_idx < first_capacity_idx


# 4. Low demand (800/day) — MEET_DEMAND control

class TestLowDemandControl:
    def test_meet_demand_zero_candidates(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 800.0)
        baseline = run_simulation(factory, "p-electronics-widget")
        assert baseline.demand_met is True  # sanity check on the premise

        candidates = generate_candidates(factory, "p-electronics-widget", _goal(OptimizationObjective.MEET_DEMAND))
        assert candidates == []

    def test_no_unnecessary_expansion_despite_a_relative_bottleneck(self, electronics_factory: Factory):
        """Some machine is always the relatively-highest-utilization one —
        that alone must never trigger a candidate when there's no queue."""
        factory = _at_demand(electronics_factory, 800.0)
        baseline = run_simulation(factory, "p-electronics-widget")
        assert baseline.system.bottleneck_machine_id is not None  # a "bottleneck" is always reported...
        for pool in baseline.process_pool_kpis:
            assert pool.average_queue_length == pytest.approx(0.0, abs=1e-6)  # ...but none are congested

        candidates = generate_candidates(factory, "p-electronics-widget", _goal(OptimizationObjective.MEET_DEMAND))
        assert len(candidates) == 0


# 5. High demand (1600/day) — stronger relief options

class TestHighDemandControl:
    @pytest.fixture
    def candidates(self, electronics_factory: Factory) -> list[OptimizationCandidate]:
        factory = _at_demand(electronics_factory, 1600.0)
        return generate_candidates(factory, "p-electronics-widget", _goal())

    def test_meaningful_relief_options_present(self, candidates):
        sources = {c.generation_source for c in candidates}
        assert GenerationSource.BOTTLENECK_RELIEF in sources
        assert GenerationSource.CYCLE_TIME_IMPROVEMENT in sources
        assert GenerationSource.COMBINED in sources

    def test_queue_larger_than_baseline_still_targets_screwdriving(self, electronics_factory: Factory, candidates):
        base_candidates = generate_candidates(
            _at_demand(electronics_factory, 1200.0), "p-electronics-widget", _goal()
        )
        high_add_parallel = next(c for c in candidates if c.candidate_id == "cand-add-parallel-m-screwdriving")
        base_add_parallel = next(c for c in base_candidates if c.candidate_id == "cand-add-parallel-m-screwdriving")
        assert "Screwdriving" in high_add_parallel.rationale

        # known formatting; high demand must show a LARGER measured queue.
        def _queue_from_rationale(text: str) -> float:
            return float(text.split("and ")[1].split(" average")[0])

        assert _queue_from_rationale(high_add_parallel.rationale) > _queue_from_rationale(base_add_parallel.rationale)

    def test_respects_max_candidates_bound(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_candidates=3))
        assert len(candidates) == 3
        # Truncation keeps the highest-priority (bottleneck relief) candidates.
        assert candidates[0].generation_source == GenerationSource.BOTTLENECK_RELIEF

    def test_max_candidates_zero_yields_empty(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_candidates=0))
        assert candidates == []


# 6. CAPEX pre-filter

class TestCapexPrefilter:
    def test_low_cap_filters_out_add_parallel_and_combined(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_capex=50000.0))
        sources = {c.generation_source for c in candidates}
        assert GenerationSource.BOTTLENECK_RELIEF not in sources
        assert GenerationSource.COMBINED not in sources
        assert GenerationSource.CYCLE_TIME_IMPROVEMENT in sources
        assert GenerationSource.CAPACITY_EXPANSION in sources

    def test_cap_exactly_at_purchase_cost_keeps_add_parallel(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_capex=85000.0))
        assert any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)

    def test_cap_one_below_purchase_cost_excludes_add_parallel(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_capex=84999.0))
        assert not any(c.candidate_id == "cand-add-parallel-m-screwdriving" for c in candidates)

    def test_unknown_cost_candidates_never_filtered_by_capex(self, electronics_factory: Factory):
        """Cycle-time/capacity candidates have estimated_capex=0.0 — never
        pretending to be free elsewhere, but also never unfairly blocked
        by a budget cap on a genuinely unknown cost."""
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_capex=0.01))
        assert any(c.generation_source == GenerationSource.CYCLE_TIME_IMPROVEMENT for c in candidates)
        assert any(c.generation_source == GenerationSource.CAPACITY_EXPANSION for c in candidates)

    def test_high_cap_keeps_everything(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        unfiltered = generate_candidates(factory, "p-electronics-widget", _goal())
        capped = generate_candidates(factory, "p-electronics-widget", _goal(max_capex=1_000_000.0))
        assert [c.candidate_id for c in unfiltered] == [c.candidate_id for c in capped]


# 7. Other filters

class TestOtherFilters:
    def test_max_additional_machines_zero_excludes_new_machine_candidates(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal(max_additional_machines=0))
        for c in candidates:
            assert "ADD_PARALLEL_MACHINE" not in _action_types(c)

    def test_allowed_action_types_restricts_generation(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(
            factory, "p-electronics-widget",
            _goal(allowed_action_types=["ADD_PARALLEL_MACHINE"]),
        )
        assert len(candidates) == 1
        assert candidates[0].candidate_id == "cand-add-parallel-m-screwdriving"

    def test_allowed_action_types_excludes_combined_when_only_one_type_permitted(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(
            factory, "p-electronics-widget",
            _goal(allowed_action_types=["CHANGE_MACHINE_CYCLE_TIME"]),
        )
        assert all(c.generation_source != GenerationSource.COMBINED for c in candidates)
        assert all(c.generation_source != GenerationSource.BOTTLENECK_RELIEF for c in candidates)


# 8. Duplicate control

class TestDuplicateControl:
    def test_no_duplicate_candidate_ids(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        ids = [c.candidate_id for c in candidates]
        assert len(ids) == len(set(ids))

    def test_no_semantically_duplicate_action_sequences(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        seen = set()
        for c in candidates:
            key = tuple(
                (a.action_type, getattr(a, "machine_id", None), getattr(a, "cycle_time", None), getattr(a, "capacity", None))
                for a in c.scenario.actions
            )
            assert key not in seen
            seen.add(key)


# 9. Candidate scenario validity / immutability

class TestCandidateScenarioValidity:
    def test_every_candidate_scenario_applies_cleanly(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        for c in candidates:
            candidate_factory = apply_scenario(factory, c.scenario)
            assert candidate_factory is not factory

    def test_every_candidate_scenario_simulates_cleanly(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        for c in candidates:
            candidate_factory = apply_scenario(factory, c.scenario)
            result = run_simulation(candidate_factory, "p-electronics-widget")
            assert result.completed_units >= 0

    def test_candidates_do_not_mutate_baseline_when_applied(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1600.0)
        before = factory.model_dump()
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        for c in candidates:
            apply_scenario(factory, c.scenario)
        assert factory.model_dump() == before

    def test_candidate_scenario_id_matches_candidate_id(self, electronics_factory: Factory):
        factory = _at_demand(electronics_factory, 1200.0)
        candidates = generate_candidates(factory, "p-electronics-widget", _goal())
        for c in candidates:
            assert c.scenario.id == c.candidate_id
