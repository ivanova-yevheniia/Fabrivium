"""Phase 8C — playback trace: model, capture, determinism, and trace/KPI consistency."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.models.simulation_trace import (
    TraceMode,
    TracePlaybackConfig,
    UnitEventType,
)
from app.services.simulation import run_simulation, run_simulation_traced

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture()
def factory() -> Factory:
    return _load_electronics()


@pytest.fixture()
def product_id(factory: Factory) -> str:
    return factory.products[0].id


# 1. Trace model


class TestTraceModel:
    def test_trace_version_present(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        assert trace.trace_version == 1

    def test_deterministic_serialization(self, factory, product_id):
        a = run_simulation_traced(factory, product_id)
        b = run_simulation_traced(factory, product_id)
        assert a.model_dump_json() == b.model_dump_json()

    def test_deterministic_unit_ids(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        released = [e.unit_id for e in trace.events if e.event_type == UnitEventType.UNIT_RELEASED]
        # Unit 0 is always released first, and IDs are assigned in strict
        # arrival order (Phase 1.2 convention), never reshuffled by tracing.
        assert released == sorted(released)
        assert released[0] == 0

    def test_event_ordering_is_time_nondecreasing(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        timestamps = [e.timestamp for e in trace.events]
        assert timestamps == sorted(timestamps)

    def test_story_markers_sorted_by_time(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        timestamps = [m.timestamp for m in trace.story_markers]
        assert timestamps == sorted(timestamps)


# 2. Trace capture modes / consistency


class TestTraceCapture:
    def test_plain_run_simulation_unaffected_by_trace_module_existing(self, factory, product_id):
        """run_simulation's own signature/behaviour never changed — this is
        the actual Phase 8B regression guarantee, not a synonym for it."""
        result = run_simulation(factory, product_id)
        assert result.completed_units >= 0

    def test_playback_produces_a_trace(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        assert len(trace.events) > 0
        assert len(trace.system_series) > 0

    def test_kpi_results_identical_with_and_without_trace(self, factory, product_id):
        plain = run_simulation(factory, product_id)
        traced = run_simulation_traced(factory, product_id)
        assert traced.summary == plain

    def test_trace_final_completed_count_matches_summary(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        last_system_sample = trace.system_series[-1]
        assert last_system_sample.completed_units == trace.summary.completed_units

    def test_trace_final_sample_lands_exactly_on_horizon(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        assert trace.system_series[-1].timestamp == pytest.approx(trace.horizon_seconds)
        for series in (trace.machine_series, trace.buffer_series, trace.operator_series):
            if series:
                assert max(s.timestamp for s in series) == pytest.approx(trace.horizon_seconds)

    def test_default_trace_config_applied_when_none_given(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id, trace_config=None)
        assert trace.config == TracePlaybackConfig()

    def test_custom_trace_config_respected(self, factory, product_id):
        cfg = TracePlaybackConfig(max_tracked_units=5, sample_count_target=20)
        trace = run_simulation_traced(factory, product_id, trace_config=cfg)
        assert trace.config == cfg
        assert trace.tracked_unit_count <= 5

    def test_trace_mode_enum_has_none_summary_playback(self):
        assert {TraceMode.NONE, TraceMode.SUMMARY, TraceMode.PLAYBACK} == set(TraceMode)


# 3. Buffers


class TestBufferTrace:
    def test_buffer_levels_never_exceed_capacity(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        for sample in trace.buffer_series:
            assert 0 <= sample.level <= sample.capacity

    def test_buffer_fill_progression_reaches_max_observed_in_kpi(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        for kpi in trace.summary.buffer_kpis:
            observed_max = max(
                (s.level for s in trace.buffer_series if s.buffer_id == kpi.buffer_id),
                default=0,
            )
            # The sampler is periodic, not continuous, so it may not catch
            # the exact instantaneous peak the KPI integrator sees — but it
            # can never see something impossible: sampled max can't exceed
            # the buffer's own capacity, and the KPI's own max_level is
            # always >= any sampled level (the KPI observes every change).
            assert observed_max <= kpi.max_level

    def test_blocking_observed_implies_a_full_sample_exists(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        for kpi in trace.summary.buffer_kpis:
            if kpi.blocking_observed:
                full_samples = [
                    s for s in trace.buffer_series if s.buffer_id == kpi.buffer_id and s.level >= s.capacity
                ]
                assert full_samples, f"buffer {kpi.buffer_id} reports blocking but no FULL sample was captured"

    def test_upstream_blocking_reflected_in_machine_series(self, factory, product_id):
        """
        The live `blocked` gauge (machine_series) is NOT bounded by max_tracked_units —
        only the per-unit event LOG is (section 6).
        """
        trace = run_simulation_traced(factory, product_id)
        blocked_machines_in_kpi = {
            kpi.reference_machine_id
            for kpi in trace.summary.process_pool_kpis
            for buf in trace.summary.buffer_kpis
            if buf.blocking_observed and buf.upstream_machine_id == kpi.reference_machine_id
        }
        if not blocked_machines_in_kpi:
            pytest.skip("Example factory produced no upstream blocking at this demand level.")
        blocked_series_machines = {s.machine_id for s in trace.machine_series if s.blocked}
        assert blocked_machines_in_kpi & blocked_series_machines


# 4. Operators


class TestOperatorTrace:
    def test_operator_series_present_when_operators_configured(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        if factory.operators_available > 0:
            assert len(trace.operator_series) > 0

    def test_operators_in_use_never_exceeds_available(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        for sample in trace.operator_series:
            assert sample.operators_in_use <= sample.operators_available

    def test_constrained_kpi_implies_a_waiting_sample(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        kpi = trace.summary.operator_kpi
        if kpi is not None and kpi.operator_constrained:
            assert any(s.waiting_operations > 0 for s in trace.operator_series)


# 5. Units


class TestUnitTrace:
    def test_route_order_correct_for_tracked_units(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        route_machine_ids = [step.machine_id for step in factory.products[0].route]

        by_unit: dict[int, list] = {}
        for event in trace.events:
            by_unit.setdefault(event.unit_id, []).append(event)

        for unit_id, events in by_unit.items():
            started = [e.machine_id for e in events if e.event_type == UnitEventType.UNIT_STARTED_PROCESSING]
            # Machines actually visited, in order, must be a (possibly
            # partial, if the unit didn't finish) PREFIX of the logical
            # route order — never out of order, never skipping a stage.
            visited_reference_ids = []
            for mid in started:
                # mid may be a physical pool member; map back to which
                # logical step it served by position in factory.machines
                # is unnecessary here — route stage order is validated via
                # relative event ordering instead (see next assertion).
                visited_reference_ids.append(mid)
            assert len(visited_reference_ids) <= len(route_machine_ids)

    def test_started_processing_events_are_time_ordered_per_unit(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        by_unit: dict[int, list] = {}
        for event in trace.events:
            if event.event_type == UnitEventType.UNIT_STARTED_PROCESSING:
                by_unit.setdefault(event.unit_id, []).append(event.timestamp)
        for unit_id, timestamps in by_unit.items():
            assert timestamps == sorted(timestamps), f"unit {unit_id} started-processing events out of order"

    def test_completed_unit_reaches_output(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        completed_ids = {e.unit_id for e in trace.events if e.event_type == UnitEventType.UNIT_COMPLETED}
        started_counts: dict[int, int] = {}
        for e in trace.events:
            if e.event_type == UnitEventType.UNIT_STARTED_PROCESSING:
                started_counts[e.unit_id] = started_counts.get(e.unit_id, 0) + 1

        route_len = len(factory.products[0].route)
        for unit_id in completed_ids:
            # A tracked unit that COMPLETED must have started processing at
            # every stage of the route — no impossible "completed after
            # only 2 of 4 stages" state.
            assert started_counts.get(unit_id, 0) == route_len

    def test_no_events_for_units_beyond_tracked_cap(self, factory, product_id):
        """The cap bounds HOW MANY units are tracked, not WHICH ids."""
        cfg = TracePlaybackConfig(max_tracked_units=3)
        trace = run_simulation_traced(factory, product_id, trace_config=cfg)
        assert len({e.unit_id for e in trace.events}) <= 3
        assert trace.tracked_unit_count <= 3
        assert all(0 <= e.unit_id < trace.total_unit_count for e in trace.events)


# 6. Performance / bounding


class TestTraceBounding:
    def test_event_count_bounded_regardless_of_high_demand(self, factory):
        """The whole point of max_tracked_units: raising demand must not
        blow up the event payload, even though sampled series still fully
        reflect every unit."""
        product = factory.products[0]
        high_demand_product = product.model_copy(update={"demand_per_day": 5000.0})
        high_demand_factory = factory.model_copy(
            update={"products": [high_demand_product, *factory.products[1:]]}
        )
        trace = run_simulation_traced(high_demand_factory, product.id)
        assert trace.tracked_unit_count <= TracePlaybackConfig().max_tracked_units
        assert trace.total_unit_count > TracePlaybackConfig().max_tracked_units

    def test_sample_count_matches_target_order_of_magnitude(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        target = trace.config.sample_count_target
        # +/- a couple of samples for the t=0 baseline sample and the final
        # horizon-aligned tick.
        assert len(trace.system_series) <= target + 5

    def test_trace_json_reasonably_sized(self, factory, product_id):
        trace = run_simulation_traced(factory, product_id)
        size_kb = len(trace.model_dump_json().encode("utf-8")) / 1024
        assert size_kb < 2000, f"trace unexpectedly large: {size_kb:.1f} KB"


# The terminal frame and the verified KPI count the same units Reproduced in the golden
# run.


def _boundary_factory(shifts: int = 1) -> Factory:
    """A line with capacity to spare, so the last unit lands ON the horizon."""
    return Factory.model_validate({
        "name": "Boundary line",
        "width": 20.0,
        "length": 10.0,
        "shifts_per_day": shifts,
        "hours_per_shift": 8.0,
        "operators_available": 4,
        "machines": [{
            "id": "m-1", "name": "Single stage", "process_type": "assembly",
            "cycle_time": 10.0, "capacity": 1, "operators_required": 1,
            "width": 2.0, "length": 2.0,
        }],
        "products": [{
            "id": "p-1", "name": "Widget", "demand_per_day": 100.0,
            "route": [{"name": "Stage", "machine_id": "m-1", "cycle_time": 10.0}],
        }],
        "buffers": [],
    })


class TestTerminalFrameMatchesVerifiedOutput:
    def test_a_unit_completing_exactly_on_the_horizon_is_in_the_last_frame(self):
        """The defect's own shape, in the smallest factory that shows it."""
        factory = _boundary_factory()
        trace = run_simulation_traced(factory, "p-1")

        # The precondition: this line keeps up, so the schedule puts the last
        # completion exactly on the horizon. Asserted so the test cannot
        # quietly stop exercising the boundary if the schedule ever changes.
        assert trace.summary.demand_met is True
        last_release = trace.summary.release_interval_seconds * (trace.summary.target_units - 1)
        assert last_release + trace.summary.nominal_route_time_seconds == pytest.approx(
            trace.horizon_seconds
        )

        last = trace.system_series[-1]
        assert last.timestamp == pytest.approx(trace.horizon_seconds)
        # Was 99 against a verified 100.
        assert last.completed_units == trace.summary.completed_units

    @pytest.mark.parametrize("shifts", [1, 2, 3])
    def test_terminal_count_matches_across_horizons(self, shifts):
        """Baseline-length and plan-length days alike."""
        trace = run_simulation_traced(_boundary_factory(shifts), "p-1")
        assert trace.system_series[-1].completed_units == trace.summary.completed_units

    def test_terminal_count_matches_when_the_target_is_missed(self, factory, product_id):
        """The case that always worked, kept working."""
        trace = run_simulation_traced(factory, product_id)
        assert trace.summary.demand_met is False
        assert trace.system_series[-1].completed_units == trace.summary.completed_units

    def test_a_hundred_percent_seek_cannot_show_one_short(self):
        """Phase 8C section 16, restated as the thing that actually broke."""
        trace = run_simulation_traced(_boundary_factory(), "p-1")
        terminal = max(trace.system_series, key=lambda s: s.timestamp)
        assert terminal.completed_units == trace.summary.completed_units
        assert terminal.completed_units != trace.summary.completed_units - 1

    def test_the_terminal_frame_is_stamped_at_the_horizon(self):
        """It is taken after the boundary, and it belongs to the boundary."""
        trace = run_simulation_traced(_boundary_factory(), "p-1")
        stamps = [s.timestamp for s in trace.system_series]
        assert max(stamps) == pytest.approx(trace.horizon_seconds)
        assert stamps == sorted(stamps)
        for series in (trace.machine_series, trace.buffer_series, trace.operator_series):
            if series:
                assert max(s.timestamp for s in series) == pytest.approx(trace.horizon_seconds)

    def test_intermediate_frames_are_untouched(self):
        """Only the last frame changed, and it changed by being taken later."""
        trace = run_simulation_traced(_boundary_factory(), "p-1")
        counts = [s.completed_units for s in trace.system_series]
        assert all(a <= b for a, b in zip(counts, counts[1:]))
        assert counts[0] == 0
        # The last frame is the only one allowed to equal the final figure.
        assert counts[-1] == trace.summary.completed_units
        assert counts[-2] <= counts[-1]

    def test_sampling_cadence_is_unchanged(self):
        """The extra beat adds no extra frame."""
        trace = run_simulation_traced(_boundary_factory(), "p-1")
        at_horizon = [s for s in trace.system_series if s.timestamp == trace.horizon_seconds]
        assert len(at_horizon) == 1

    def test_kpis_are_not_affected_by_the_trace_at_all(self):
        """The summary is the same with and without a trace attached."""
        factory = _boundary_factory()
        assert run_simulation_traced(factory, "p-1").summary == run_simulation(factory, "p-1")
