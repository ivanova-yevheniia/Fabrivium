"""Phase 8A tests — shifts, operators, finite buffers."""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.models.factory import Buffer, Factory
from app.models.optimization import GenerationSource, OptimizationGoal, OptimizationObjective
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeBufferCapacityAction,
    ChangeOperatorCapacityAction,
    ChangeShiftConfigurationAction,
    Scenario,
)
from app.services.candidate_generator import generate_candidates
from app.services.scenario import ScenarioError, apply_scenario
from app.services.simulation import run_simulation

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"
PRODUCT_ID = "p-electronics-widget"


@pytest.fixture(scope="module")
def electronics_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


def at_demand(factory: Factory, demand: float) -> Factory:
    return factory.model_copy(
        update={"products": [p.model_copy(update={"demand_per_day": demand}) for p in factory.products]}
    )


def with_actions(factory: Factory, *actions) -> Factory:
    return apply_scenario(factory, Scenario(id="s", name="n", description="", actions=list(actions)))


def simulate(factory: Factory):
    return run_simulation(factory, PRODUCT_ID)


# SHIFTS


class TestShiftSemantics:
    def test_the_horizon_reflects_the_new_shift_configuration(self, electronics_factory):
        """The whole point: a shift change lengthens the simulated window."""
        baseline = simulate(electronics_factory)
        assert baseline.simulation_time_seconds == pytest.approx(2 * 8.0 * 3600.0)

        candidate = simulate(with_actions(electronics_factory, ChangeShiftConfigurationAction(shifts_per_day=3)))
        assert candidate.simulation_time_seconds == pytest.approx(3 * 8.0 * 3600.0)

    def test_two_to_three_shifts_raises_daily_output(self, electronics_factory):
        factory = at_demand(electronics_factory, 1900.0)
        before = simulate(factory)
        after = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=3)))

        assert before.completed_units == 1105
        assert after.completed_units > before.completed_units
        assert after.demand_gap_units < before.demand_gap_units

    def test_throughput_per_hour_is_essentially_unchanged_by_extra_time(self, electronics_factory):
        """THE shift-semantics distinction (Phase 8A section 3)."""
        factory = at_demand(electronics_factory, 1900.0)
        before = simulate(factory)
        after = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=3)))

        assert after.throughput_per_hour == pytest.approx(before.throughput_per_hour, rel=0.02)
        assert after.completed_units / before.completed_units > 1.4

    def test_hours_per_shift_alone_also_works(self, electronics_factory):
        candidate = with_actions(electronics_factory, ChangeShiftConfigurationAction(hours_per_shift=12.0))
        assert candidate.shifts_per_day == 2  # carried over
        assert candidate.hours_per_shift == 12.0
        assert simulate(candidate).simulation_time_seconds == pytest.approx(24 * 3600.0)

    def test_demand_stays_a_per_day_target_across_a_shift_change(self, electronics_factory):
        factory = at_demand(electronics_factory, 1900.0)
        after = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=3)))
        assert after.target_units == 1900
        assert after.demand_per_day == 1900.0

    def test_release_schedule_stays_consistent_with_the_longer_horizon(self, electronics_factory):
        """The last unit must still be released exactly one nominal route
        time before the (new) horizon ends — the schedule is re-derived, not
        stretched."""
        factory = at_demand(electronics_factory, 1900.0)
        after = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=3)))
        expected_latest = after.simulation_time_seconds - after.nominal_route_time_seconds
        assert after.release_interval_seconds == pytest.approx(expected_latest / (after.target_units - 1))

    def test_shortening_the_day_reduces_output(self, electronics_factory):
        factory = at_demand(electronics_factory, 1900.0)
        before = simulate(factory)
        after = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=1)))
        assert after.completed_units < before.completed_units

    def test_a_horizon_shorter_than_the_route_is_refused_not_simulated(self, electronics_factory):
        """Boundary behaviour: 142 s of route cannot fit in a horizon of
        seconds, and the existing infeasibility guard must still fire."""
        tiny = electronics_factory.model_copy(update={"shifts_per_day": 1, "hours_per_shift": 0.01})
        with pytest.raises(ValueError, match="nominal route time"):
            simulate(tiny)

    @pytest.mark.parametrize("kwargs", [
        {},                                              # neither field
        {"shifts_per_day": 0},                           # zero shifts
        {"hours_per_shift": 0.0},                        # zero hours
        {"shifts_per_day": -1},                          # negative
        {"shifts_per_day": 4, "hours_per_shift": 8.0},   # 32-hour day
    ])
    def test_invalid_shift_values_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            ChangeShiftConfigurationAction(**kwargs)

    def test_a_day_longer_than_24_hours_is_refused_against_the_baseline(self, electronics_factory):
        """Only the combination with the baseline can be checked at apply
        time: 3 shifts is fine on an 8-hour factory and impossible on a
        10-hour one."""
        ten_hour = electronics_factory.model_copy(update={"hours_per_shift": 10.0})
        with pytest.raises(ScenarioError, match="24-hour day"):
            with_actions(ten_hour, ChangeShiftConfigurationAction(shifts_per_day=3))

    def test_baseline_is_immutable_under_a_shift_change(self, electronics_factory):
        before = electronics_factory.model_dump_json()
        with_actions(electronics_factory, ChangeShiftConfigurationAction(shifts_per_day=3, hours_per_shift=7.0))
        assert electronics_factory.model_dump_json() == before


# OPERATORS


class TestOperatorResource:
    def test_operators_are_a_shared_finite_resource(self, electronics_factory):
        """Four machines needing 2 each cannot all run on 4 operators."""
        constrained = with_actions(at_demand(electronics_factory, 1200.0), ChangeOperatorCapacityAction(operators_available=4))
        result = simulate(constrained)
        assert result.operator_kpi.peak_operators_in_use <= 4

    def test_a_shortage_makes_units_wait_and_degrades_output(self, electronics_factory):
        factory = at_demand(electronics_factory, 1200.0)
        plenty = simulate(factory)
        starved = simulate(with_actions(factory, ChangeOperatorCapacityAction(operators_available=4)))

        assert plenty.operator_kpi.operator_constrained is False
        assert starved.operator_kpi.operator_constrained is True
        assert starved.operator_kpi.average_operator_wait_seconds > 0
        assert starved.completed_units < plenty.completed_units

    def test_utilization_rises_as_the_pool_shrinks(self, electronics_factory):
        factory = at_demand(electronics_factory, 1200.0)
        utilizations = [
            simulate(with_actions(factory, ChangeOperatorCapacityAction(operators_available=staff))).operator_kpi.utilization
            for staff in (8, 6, 4)
        ]
        assert utilizations == sorted(utilizations)

    def test_adding_operators_helps_a_constrained_line(self, electronics_factory):
        """Phase 8A experiment C: staff are the binding constraint once five
        machines share eight operators, and hiring relieves it."""
        factory = at_demand(electronics_factory, 1900.0)
        expansion = (
            AddParallelMachineAction(machine_id="m-screwdriving"),
            AddParallelMachineAction(machine_id="m-assembly"),
        )
        starved = simulate(with_actions(factory, *expansion))
        staffed = simulate(with_actions(factory, *expansion, ChangeOperatorCapacityAction(operators_available=10)))

        assert starved.operator_kpi.operator_constrained is True
        assert staffed.operator_kpi.operator_constrained is False
        assert staffed.completed_units > starved.completed_units

    def test_adding_operators_changes_nothing_when_they_were_never_the_limit(self, electronics_factory):
        """The other half of the guarantee: staff do not create capacity."""
        factory = at_demand(electronics_factory, 1900.0)
        before = simulate(factory)
        after = simulate(with_actions(factory, ChangeOperatorCapacityAction(operators_available=40)))

        assert before.operator_kpi.operator_constrained is False
        assert after.completed_units == before.completed_units
        assert after.throughput_per_hour == pytest.approx(before.throughput_per_hour)
        assert after.system.bottleneck_machine_id == before.system.bottleneck_machine_id

    def test_zero_operator_machines_do_not_interact_with_the_pool_at_all(self, electronics_factory):
        """The backward-compatibility guarantee: a factory whose machines
        declare no operators is byte-identical to the pre-Phase-8A engine,
        no matter how small the pool."""
        no_ops = electronics_factory.model_copy(
            update={
                "machines": [m.model_copy(update={"operators_required": 0}) for m in electronics_factory.machines],
                "operators_available": 0,
            }
        )
        result = simulate(at_demand(no_ops, 1200.0))
        reference = simulate(at_demand(electronics_factory, 1200.0))

        assert result.completed_units == reference.completed_units
        assert result.operator_kpi.operator_constrained is False
        assert result.operator_kpi.peak_operators_in_use == 0
        assert result.operator_kpi.utilization == 0.0

    def test_a_stage_needing_more_staff_than_exist_is_refused_not_hung(self, electronics_factory):
        """Structural infeasibility must fail fast."""
        understaffed = electronics_factory.model_copy(update={"operators_available": 1})
        with pytest.raises(ValueError, match="No unit could ever start"):
            simulate(understaffed)

    def test_no_deadlock_under_severe_contention(self, electronics_factory):
        """
        Every unit takes a machine and then operators, so a unit holding operators is
        always already processing.
        """
        tight = with_actions(at_demand(electronics_factory, 600.0), ChangeOperatorCapacityAction(operators_available=2))
        result = simulate(tight)
        assert result.completed_units > 0
        assert result.operator_kpi.operator_constrained is True

    def test_operator_wait_is_reported_separately_from_machine_wait(self, electronics_factory):
        """Phase 8A section 7: a workforce problem must not masquerade as a
        machine problem."""
        starved = simulate(with_actions(at_demand(electronics_factory, 1200.0), ChangeOperatorCapacityAction(operators_available=4)))
        assert starved.operator_kpi.total_operator_wait_seconds > 0
        assert starved.operator_kpi.operations_delayed_by_operators > 0
        # Machine KPIs remain their own measurement, not a merged total.
        assert all(kpi.average_wait_time_seconds >= 0 for kpi in starved.machine_kpis)

    def test_peak_never_exceeds_the_pool(self, electronics_factory):
        for staff in (2, 4, 6, 8, 20):
            result = simulate(with_actions(at_demand(electronics_factory, 900.0), ChangeOperatorCapacityAction(operators_available=staff)))
            assert result.operator_kpi.peak_operators_in_use <= staff
            assert result.operator_kpi.average_operators_in_use <= staff

    def test_baseline_is_immutable_under_an_operator_change(self, electronics_factory):
        before = electronics_factory.model_dump_json()
        with_actions(electronics_factory, ChangeOperatorCapacityAction(operators_available=99))
        assert electronics_factory.model_dump_json() == before

    @pytest.mark.parametrize("value", [0, -1, -100])
    def test_invalid_operator_counts_are_rejected(self, value):
        with pytest.raises(ValidationError):
            ChangeOperatorCapacityAction(operators_available=value)


# BUFFERS


class TestFiniteBuffers:
    def test_the_bundled_fixture_wires_its_buffers_explicitly(self, electronics_factory):
        """Phase 8A section 14: the stage relationship is DATA, never parsed
        from the buffer's display name at runtime."""
        by_id = {b.id: b for b in electronics_factory.buffers}
        assert by_id["buf-1"].upstream_machine_id == "m-assembly"
        assert by_id["buf-1"].downstream_machine_id == "m-screwdriving"
        assert by_id["buf-2"].upstream_machine_id == "m-screwdriving"
        assert by_id["buf-3"].downstream_machine_id == "m-packaging"
        assert all(b.is_wired for b in electronics_factory.buffers)

    def test_an_unwired_buffer_has_no_simulation_effect(self, electronics_factory):
        """Backward compatibility: a buffer that does not say where it sits
        is inert, exactly as every buffer was before Phase 8A."""
        unwired = electronics_factory.model_copy(
            update={
                "buffers": [
                    Buffer(id=b.id, name=b.name, capacity=1, position_x=b.position_x, position_y=b.position_y)
                    for b in electronics_factory.buffers
                ]
            }
        )
        result = simulate(at_demand(unwired, 1200.0))
        assert result.buffer_kpis == []
        # Capacity 1 everywhere would throttle the line severely if it were
        assert result.completed_units == simulate(at_demand(electronics_factory, 1200.0)).completed_units

    def test_no_runtime_name_inference(self, electronics_factory):
        """Renaming a buffer must not change the physics."""
        renamed = electronics_factory.model_copy(
            update={"buffers": [b.model_copy(update={"name": "Totally Unrelated Label"}) for b in electronics_factory.buffers]}
        )
        assert simulate(at_demand(renamed, 1200.0)).completed_units == simulate(at_demand(electronics_factory, 1200.0)).completed_units

    def test_a_buffer_not_between_consecutive_stages_is_ignored(self, electronics_factory):
        """Wired, but naming a non-adjacent pair — correctly ignored rather
        than guessed at or treated as an error."""
        odd = electronics_factory.model_copy(
            update={
                "buffers": [
                    electronics_factory.buffers[0].model_copy(
                        update={"upstream_machine_id": "m-assembly", "downstream_machine_id": "m-packaging"}
                    )
                ]
            }
        )
        assert simulate(at_demand(odd, 1200.0)).buffer_kpis == []

    def test_a_small_buffer_fills_and_blocks_upstream(self, electronics_factory):
        """Phase 8A experiment D."""
        factory = at_demand(electronics_factory, 1200.0)
        small = simulate(with_actions(factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=2)))
        kpi = next(k for k in small.buffer_kpis if k.buffer_id == "buf-1")

        assert kpi.max_level == 2
        assert kpi.full_fraction > 0.9
        assert kpi.blocking_observed is True
        assert kpi.upstream_blocked_seconds > 0
        assert kpi.upstream_blocked_events > 0

    def test_a_larger_buffer_reduces_blocking(self, electronics_factory):
        factory = at_demand(electronics_factory, 1200.0)
        small = simulate(with_actions(factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=2)))
        large = simulate(with_actions(factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=500)))

        blocked_small = next(k for k in small.buffer_kpis if k.buffer_id == "buf-1").upstream_blocked_seconds
        blocked_large = next(k for k in large.buffer_kpis if k.buffer_id == "buf-1").upstream_blocked_seconds
        assert blocked_large < blocked_small

    def test_a_larger_buffer_does_not_create_processing_capacity(self, electronics_factory):
        """Phase 8A experiment E — the most important buffer guarantee."""
        factory = at_demand(electronics_factory, 1900.0)
        results = {
            cap: simulate(with_actions(factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=cap)))
            for cap in (50, 200, 2000)
        }
        completed = {cap: r.completed_units for cap, r in results.items()}
        assert len(set(completed.values())) == 1, completed
        # ...while the blocking really did disappear.
        assert next(k for k in results[2000].buffer_kpis if k.buffer_id == "buf-1").upstream_blocked_seconds == 0
        assert next(k for k in results[50].buffer_kpis if k.buffer_id == "buf-1").upstream_blocked_seconds > 0

    def test_buffer_level_never_leaves_its_bounds(self, electronics_factory):
        for cap in (1, 3, 25):
            result = simulate(with_actions(at_demand(electronics_factory, 1200.0), ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=cap)))
            for kpi in result.buffer_kpis:
                assert 0 <= kpi.max_level <= kpi.capacity
                assert 0.0 <= kpi.average_level <= kpi.capacity
                assert 0.0 <= kpi.utilization <= 1.0

    def test_time_full_and_time_empty_are_within_the_horizon(self, electronics_factory):
        result = simulate(at_demand(electronics_factory, 1200.0))
        for kpi in result.buffer_kpis:
            assert 0.0 <= kpi.time_full_seconds <= result.simulation_time_seconds
            assert 0.0 <= kpi.time_empty_seconds <= result.simulation_time_seconds
            assert 0.0 <= kpi.full_fraction <= 1.0
            assert 0.0 <= kpi.empty_fraction <= 1.0

    def test_a_downstream_buffer_that_never_fills_reports_no_blocking(self, electronics_factory):
        """buf-2/buf-3 sit after the bottleneck and are always drained, so
        they must report empty and un-blocked rather than plausible noise."""
        result = simulate(at_demand(electronics_factory, 1200.0))
        for buffer_id in ("buf-2", "buf-3"):
            kpi = next(k for k in result.buffer_kpis if k.buffer_id == buffer_id)
            assert kpi.blocking_observed is False
            assert kpi.upstream_blocked_seconds == 0.0
            assert kpi.empty_fraction > 0.9

    def test_capacity_change_requires_an_existing_buffer(self, electronics_factory):
        with pytest.raises(ScenarioError, match="not found"):
            with_actions(electronics_factory, ChangeBufferCapacityAction(buffer_id="buf-nope", new_capacity=10))

    @pytest.mark.parametrize("value", [0, -1])
    def test_zero_or_negative_capacity_is_rejected(self, value):
        """Deliberate semantics (section 13): capacity is always >= 1, and
        'no intermediate storage' means having no buffer between two stages
        rather than a zero-capacity one."""
        with pytest.raises(ValidationError):
            ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=value)
        with pytest.raises(ValidationError):
            Buffer(id="b", name="n", capacity=value)

    def test_baseline_is_immutable_under_a_buffer_change(self, electronics_factory):
        before = electronics_factory.model_dump_json()
        with_actions(electronics_factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=7))
        assert electronics_factory.model_dump_json() == before

    def test_only_the_named_buffer_changes(self, electronics_factory):
        candidate = with_actions(electronics_factory, ChangeBufferCapacityAction(buffer_id="buf-2", new_capacity=9))
        by_id = {b.id: b.capacity for b in candidate.buffers}
        assert by_id == {"buf-1": 50, "buf-2": 9, "buf-3": 50}


# SCENARIO COMPOSITION


class TestScenarioComposition:
    def test_all_three_new_actions_compose_with_each_other(self, electronics_factory):
        candidate = with_actions(
            electronics_factory,
            ChangeShiftConfigurationAction(shifts_per_day=3),
            ChangeOperatorCapacityAction(operators_available=12),
            ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=100),
        )
        assert candidate.shifts_per_day == 3
        assert candidate.operators_available == 12
        assert next(b.capacity for b in candidate.buffers if b.id == "buf-1") == 100

    def test_they_compose_with_existing_machine_actions(self, electronics_factory):
        candidate = with_actions(
            electronics_factory,
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeOperatorCapacityAction(operators_available=12),
            ChangeShiftConfigurationAction(shifts_per_day=3),
        )
        assert any(m.parallel_of_machine_id == "m-screwdriving" for m in candidate.machines)
        assert candidate.operators_available == 12
        assert candidate.shifts_per_day == 3

    def test_a_combined_scenario_produces_a_non_trivial_interaction(self, electronics_factory):
        """Phase 8A experiment F: the levers are not independent."""
        factory = at_demand(electronics_factory, 1900.0)
        shift_only = simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=3)))
        everything = simulate(with_actions(
            factory,
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeShiftConfigurationAction(shifts_per_day=3),
            ChangeOperatorCapacityAction(operators_available=12),
        ))
        assert shift_only.demand_met is False
        assert everything.demand_met is True

    def test_the_whole_baseline_survives_a_combined_scenario(self, electronics_factory):
        before = electronics_factory.model_dump_json()
        with_actions(
            electronics_factory,
            AddParallelMachineAction(machine_id="m-assembly"),
            ChangeShiftConfigurationAction(shifts_per_day=3, hours_per_shift=7.5),
            ChangeOperatorCapacityAction(operators_available=30),
            ChangeBufferCapacityAction(buffer_id="buf-3", new_capacity=1),
        )
        assert electronics_factory.model_dump_json() == before


# OPTIMIZER — evidence gating


def sources(factory: Factory, **goal_kwargs) -> set[str]:
    goal = OptimizationGoal(
        objective=OptimizationObjective.MEET_DEMAND,
        target_product_id=PRODUCT_ID,
        max_candidates=30,
        **goal_kwargs,
    )
    return {c.generation_source.value for c in generate_candidates(factory, PRODUCT_ID, goal)}


class TestOptimizerEvidenceGating:
    def test_a_shift_is_proposed_only_while_demand_is_unmet(self, electronics_factory):
        assert GenerationSource.SHIFT_EXPANSION.value in sources(at_demand(electronics_factory, 1900.0))
        # Demand comfortably met -> no reason to buy time.
        assert GenerationSource.SHIFT_EXPANSION.value not in sources(at_demand(electronics_factory, 100.0))

    def test_no_shift_is_proposed_when_the_day_is_already_full(self, electronics_factory):
        full_day = electronics_factory.model_copy(update={"shifts_per_day": 3, "hours_per_shift": 8.0})
        assert GenerationSource.SHIFT_EXPANSION.value not in sources(at_demand(full_day, 5000.0))

    def test_operators_are_proposed_only_when_staff_actually_waited(self, electronics_factory):
        """The baseline is machine-bound, so no operator candidate."""
        assert GenerationSource.OPERATOR_EXPANSION.value not in sources(at_demand(electronics_factory, 1900.0))

        constrained = with_actions(
            at_demand(electronics_factory, 1900.0),
            AddParallelMachineAction(machine_id="m-screwdriving"),
        )
        assert simulate(constrained).operator_kpi.operator_constrained is True
        assert GenerationSource.OPERATOR_EXPANSION.value in sources(constrained)

    def test_operator_candidates_respect_a_hiring_limit(self, electronics_factory):
        constrained = with_actions(
            at_demand(electronics_factory, 1900.0),
            AddParallelMachineAction(machine_id="m-screwdriving"),
        )
        assert GenerationSource.OPERATOR_EXPANSION.value in sources(constrained)
        assert GenerationSource.OPERATOR_EXPANSION.value not in sources(constrained, max_additional_operators=0)

    def test_a_buffer_feeding_the_bottleneck_is_never_proposed(self, electronics_factory):
        """
        buf-1 is measurably full and blocking, yet enlarging it cannot help because its
        downstream stage IS the bottleneck.
        """
        factory = at_demand(electronics_factory, 1900.0)
        kpi = next(k for k in simulate(factory).buffer_kpis if k.buffer_id == "buf-1")
        assert kpi.blocking_observed is True  # the evidence exists...
        assert simulate(factory).system.bottleneck_machine_id == "m-screwdriving"
        assert GenerationSource.BUFFER_EXPANSION.value not in sources(factory)  # ...and is correctly not enough

    def test_a_buffer_is_never_proposed_just_because_it_exists(self, electronics_factory):
        """buf-2 and buf-3 never block at all."""
        factory = at_demand(electronics_factory, 1200.0)
        for buffer_id in ("buf-2", "buf-3"):
            kpi = next(k for k in simulate(factory).buffer_kpis if k.buffer_id == buffer_id)
            assert kpi.blocking_observed is False
        assert GenerationSource.BUFFER_EXPANSION.value not in sources(factory)

    def test_every_new_lever_is_marked_unknown_cost_never_free(self, electronics_factory):
        """Phase 8A section 19."""
        goal = OptimizationGoal(
            objective=OptimizationObjective.MEET_DEMAND, target_product_id=PRODUCT_ID, max_candidates=30,
        )
        constrained = with_actions(
            at_demand(electronics_factory, 1900.0), AddParallelMachineAction(machine_id="m-screwdriving"),
        )
        new_sources = {
            GenerationSource.SHIFT_EXPANSION,
            GenerationSource.OPERATOR_EXPANSION,
            GenerationSource.BUFFER_EXPANSION,
        }
        produced = [c for c in generate_candidates(constrained, PRODUCT_ID, goal) if c.generation_source in new_sources]
        assert produced, "expected at least one Phase 8A candidate for a constrained line"
        for candidate in produced:
            assert candidate.requires_cost_estimate is True
            assert candidate.estimated_capex == 0.0
            assert candidate.requires_layout_placement is False

    def test_known_cost_machine_candidates_still_come_first(self, electronics_factory):
        """Ordering is load-bearing under truncation: an unknown-cost lever
        must never displace a known-cost machine option."""
        goal = OptimizationGoal(
            objective=OptimizationObjective.MEET_DEMAND, target_product_id=PRODUCT_ID, max_candidates=30,
        )
        candidates = generate_candidates(at_demand(electronics_factory, 1900.0), PRODUCT_ID, goal)
        known_cost_positions = [i for i, c in enumerate(candidates) if not c.requires_cost_estimate]
        unknown_cost_positions = [i for i, c in enumerate(candidates) if c.requires_cost_estimate]
        assert known_cost_positions
        assert max(known_cost_positions) < min(unknown_cost_positions)

    def test_forbidden_machines_still_filter_the_new_candidates(self, electronics_factory):
        """A shift/operator candidate touches no machine, so it must survive
        a forbidden list — while machine candidates for that machine do not."""
        factory = at_demand(electronics_factory, 1900.0)
        with_forbidden = sources(factory, forbidden_machine_ids=["m-screwdriving", "m-assembly"])
        assert GenerationSource.SHIFT_EXPANSION.value in with_forbidden
        assert GenerationSource.BOTTLENECK_RELIEF.value not in with_forbidden


# INVARIANTS (Phase 8A section 25)


class TestInvariants:
    @pytest.mark.parametrize("demand", [400.0, 900.0, 1200.0, 1900.0])
    @pytest.mark.parametrize("staff", [2, 4, 8, 20])
    def test_core_invariants_hold_across_the_grid(self, electronics_factory, demand, staff):
        result = simulate(with_actions(at_demand(electronics_factory, demand), ChangeOperatorCapacityAction(operators_available=staff)))
        operator_kpi = result.operator_kpi

        assert 0.0 <= operator_kpi.utilization <= 1.0
        assert operator_kpi.peak_operators_in_use >= 0
        assert operator_kpi.average_operators_in_use >= 0.0
        assert operator_kpi.peak_operators_in_use <= staff
        assert operator_kpi.total_operator_wait_seconds >= 0.0
        assert operator_kpi.max_operator_wait_seconds >= operator_kpi.average_operator_wait_seconds
        assert result.completed_units >= 0
        assert result.demand_gap_units >= 0.0
        assert result.system.work_in_progress >= 0

        for buffer_kpi in result.buffer_kpis:
            assert 0 <= buffer_kpi.max_level <= buffer_kpi.capacity
            assert 0.0 <= buffer_kpi.average_level <= buffer_kpi.capacity
            assert 0.0 <= buffer_kpi.utilization <= 1.0
            assert buffer_kpi.upstream_blocked_seconds >= 0.0
            assert buffer_kpi.time_full_seconds + buffer_kpi.time_empty_seconds <= result.simulation_time_seconds + 1e-6

    def test_repeated_runs_are_bit_identical(self, electronics_factory):
        factory = with_actions(
            at_demand(electronics_factory, 1900.0),
            AddParallelMachineAction(machine_id="m-screwdriving"),
            ChangeOperatorCapacityAction(operators_available=9),
            ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=7),
        )
        assert simulate(factory).model_dump() == simulate(factory).model_dump()

    def test_more_operators_never_makes_operator_waiting_worse(self, electronics_factory):
        """Monotonicity on an otherwise identical deterministic fixture
        (Phase 8A section 25)."""
        factory = with_actions(at_demand(electronics_factory, 1900.0), AddParallelMachineAction(machine_id="m-screwdriving"))
        waits = [
            simulate(with_actions(factory, ChangeOperatorCapacityAction(operators_available=staff))).operator_kpi.total_operator_wait_seconds
            for staff in (4, 6, 8, 10, 14)
        ]
        assert waits == sorted(waits, reverse=True), waits

    def test_more_buffer_never_makes_upstream_blocking_worse(self, electronics_factory):
        factory = at_demand(electronics_factory, 1200.0)
        blocked = [
            next(
                k.upstream_blocked_seconds
                for k in simulate(with_actions(factory, ChangeBufferCapacityAction(buffer_id="buf-1", new_capacity=cap))).buffer_kpis
                if k.buffer_id == "buf-1"
            )
            for cap in (1, 5, 25, 100, 1000)
        ]
        assert blocked == sorted(blocked, reverse=True), blocked

    def test_a_longer_day_never_reduces_completed_units(self, electronics_factory):
        factory = at_demand(electronics_factory, 1900.0)
        completed = [
            simulate(with_actions(factory, ChangeShiftConfigurationAction(shifts_per_day=shifts))).completed_units
            for shifts in (1, 2, 3)
        ]
        assert completed == sorted(completed), completed


# REQUIREMENTS / AGENT MAPPING (Phase 8A section 21)


class TestRequirementsMapping:
    """How "solve it without buying a machine" reaches the optimizer."""

    @pytest.fixture
    def parser(self):
        from app.services.requirements_parser import DeterministicFallbackRequirementsParser

        return DeterministicFallbackRequirementsParser()

    @pytest.mark.parametrize("text,expected", [
        ("Can we reach 1900 units/day with an extra shift?", ["CHANGE_SHIFT_CONFIGURATION"]),
        ("Try adding two operators instead.", ["CHANGE_OPERATOR_CAPACITY"]),
        ("Increase the buffer before Screwdriving.", ["CHANGE_BUFFER_CAPACITY"]),
        ("What if we double the Screwdriving buffer?", ["CHANGE_BUFFER_CAPACITY"]),
    ])
    def test_an_explicitly_named_lever_restricts_planning_to_it(self, parser, text, expected):
        assert parser.parse(text).parsed_requirements.allowed_action_types == expected

    def test_do_not_buy_a_machine_leaves_every_other_lever_open(self, parser):
        """Saying what to AVOID must not collapse to saying what to use."""
        from app.models.scenario import SUPPORTED_ACTION_TYPES

        allowed = parser.parse("Can we reach 1900 units/day without buying another machine?").parsed_requirements.allowed_action_types
        assert allowed is not None
        assert "ADD_PARALLEL_MACHINE" not in allowed
        assert set(allowed) == SUPPORTED_ACTION_TYPES - {"ADD_PARALLEL_MACHINE"}

    @pytest.mark.parametrize("text", [
        "We need 1900 units/day.",
        "Make it better.",
        "That's too expensive.",
    ])
    def test_a_request_that_names_no_lever_restricts_nothing(self, parser, text):
        """A vague request must never be turned into a workforce or shift
        decision — that is a guess dressed as a constraint."""
        assert parser.parse(text).parsed_requirements.allowed_action_types is None

    def test_an_unsupported_action_type_is_reported_not_silently_ignored(self):
        """The dangerous failure: an invented action type filters every
        candidate out and the session blames the engineering, not the typo."""
        from app.models.agent import PlanningRequirements
        from app.services.requirements_parser import detect_contradictions

        requirements = PlanningRequirements(
            objective=OptimizationObjective.MEET_DEMAND,
            allowed_action_types=["HIRE_STAFF", "ADD_ROBOT"],
        )
        warnings = detect_contradictions(requirements)
        assert any("Unsupported action type" in w for w in warnings)
        assert any("HIRE_STAFF" in w for w in warnings)

    def test_supported_action_types_is_derived_from_the_union_not_hand_written(self):
        """A hand-written list would drift from what apply_scenario can
        actually execute."""
        from app.models.scenario import SUPPORTED_ACTION_TYPES

        assert SUPPORTED_ACTION_TYPES == {
            "ADD_PARALLEL_MACHINE", "CHANGE_MACHINE_CYCLE_TIME", "CHANGE_MACHINE_CAPACITY",
            "CHANGE_DEMAND", "REMOVE_MACHINE",
            "CHANGE_SHIFT_CONFIGURATION", "CHANGE_OPERATOR_CAPACITY", "CHANGE_BUFFER_CAPACITY",
        }

    def test_restricting_to_a_lever_really_restricts_the_optimizer(self, electronics_factory):
        """End to end: the restriction the parser produces is honoured by
        candidate generation."""
        goal = OptimizationGoal(
            objective=OptimizationObjective.MEET_DEMAND,
            target_product_id=PRODUCT_ID,
            max_candidates=30,
            allowed_action_types=["CHANGE_SHIFT_CONFIGURATION"],
        )
        candidates = generate_candidates(at_demand(electronics_factory, 1900.0), PRODUCT_ID, goal)
        assert candidates
        for candidate in candidates:
            assert {a.action_type for a in candidate.scenario.actions} == {"CHANGE_SHIFT_CONFIGURATION"}
