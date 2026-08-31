"""Playback trace audit — tracked-unit SELECTION policy."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.models.factory import Factory
from app.models.simulation_trace import TracePlaybackConfig, UnitEventType
from app.services.simulation import run_simulation, run_simulation_traced

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"

#: The audit's acceptance bar: tracked events must cover at least this much
#: of the simulated horizon (was 2.2 % before the fix).
_MIN_HORIZON_COVERAGE = 0.80


def _load_electronics() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture()
def factory() -> Factory:
    return _load_electronics()


@pytest.fixture()
def product_id(factory: Factory) -> str:
    return factory.products[0].id


@pytest.fixture()
def flagship_factory(factory: Factory) -> Factory:
    """The flagship demo day: 1900 units/day over a 3x8h (24 h) horizon."""
    product = factory.products[0].model_copy(update={"demand_per_day": 1900.0})
    return factory.model_copy(update={"shifts_per_day": 3, "products": [product]})


def _coverage(trace) -> float:
    """Fraction of the horizon spanned by tracked-unit events."""
    if not trace.events:
        return 0.0
    timestamps = [e.timestamp for e in trace.events]
    return (max(timestamps) - min(timestamps)) / trace.horizon_seconds


# 1. Horizon coverage — the actual regression


class TestHorizonCoverage:
    def test_flagship_day_tracked_events_span_at_least_80_percent_of_horizon(
        self, flagship_factory, product_id
    ):
        trace = run_simulation_traced(flagship_factory, product_id)
        assert trace.horizon_seconds == pytest.approx(86400.0)

        coverage = _coverage(trace)
        assert coverage >= _MIN_HORIZON_COVERAGE, (
            f"tracked events span only {coverage:.1%} of the {trace.horizon_seconds:.0f}s "
            "horizon — playback would show no workpieces for the rest of the day "
            "(the prefix-tracking defect this test exists to prevent)"
        )

    def test_baseline_day_tracked_events_span_at_least_80_percent_of_horizon(
        self, factory, product_id
    ):
        """The congested BEFORE case must stay covered too — it is the half
        of the demo that has a story to tell."""
        trace = run_simulation_traced(factory, product_id)
        assert _coverage(trace) >= _MIN_HORIZON_COVERAGE

    def test_tracked_units_are_spread_not_clustered_at_the_start(
        self, flagship_factory, product_id
    ):
        """Coverage alone could be satisfied by one very late unit."""
        trace = run_simulation_traced(flagship_factory, product_id)
        horizon = trace.horizon_seconds
        for quarter in range(4):
            lo, hi = horizon * quarter / 4, horizon * (quarter + 1) / 4
            in_quarter = [e for e in trace.events if lo <= e.timestamp < hi]
            assert in_quarter, f"no tracked-unit event in horizon quarter {quarter + 1}/4"

    def test_last_tracked_unit_is_released_late_in_the_run(self, flagship_factory, product_id):
        trace = run_simulation_traced(flagship_factory, product_id)
        released = [
            e.timestamp for e in trace.events if e.event_type == UnitEventType.UNIT_RELEASED
        ]
        assert released, "no UNIT_RELEASED events captured"
        assert max(released) >= 0.5 * trace.horizon_seconds


# 2. The bound is still the bound


class TestTrackedUnitBound:
    def test_unique_tracked_units_never_exceed_max_tracked_units(
        self, flagship_factory, product_id
    ):
        trace = run_simulation_traced(flagship_factory, product_id)
        unique = {e.unit_id for e in trace.events}
        assert len(unique) <= trace.config.max_tracked_units
        assert trace.tracked_unit_count == len(unique)

    @pytest.mark.parametrize("max_tracked", [1, 3, 7, 40, 137])
    def test_bound_holds_across_configurations(self, flagship_factory, product_id, max_tracked):
        cfg = TracePlaybackConfig(max_tracked_units=max_tracked, sample_count_target=60)
        trace = run_simulation_traced(flagship_factory, product_id, cfg)
        unique = {e.unit_id for e in trace.events}
        assert len(unique) <= max_tracked, f"{len(unique)} tracked units exceeds bound {max_tracked}"

    def test_bound_holds_when_demand_is_far_larger_than_the_bound(self, factory, product_id):
        product = factory.products[0].model_copy(update={"demand_per_day": 900.0})
        big = factory.model_copy(update={"products": [product]})
        trace = run_simulation_traced(big, product_id)
        assert trace.tracked_unit_count <= TracePlaybackConfig().max_tracked_units
        assert trace.total_unit_count > TracePlaybackConfig().max_tracked_units

    def test_tiny_run_with_fewer_units_than_the_bound_still_works(self, factory, product_id):
        """
        total_units < max_tracked_units => stride collapses to 1 and every unit is
        tracked.
        """
        product = factory.products[0].model_copy(update={"demand_per_day": 5.0})
        tiny = factory.model_copy(update={"products": [product]})
        trace = run_simulation_traced(tiny, product_id)
        assert trace.tracked_unit_count <= TracePlaybackConfig().max_tracked_units
        assert trace.tracked_unit_count == trace.total_unit_count


# 3. Determinism


class TestDeterminism:
    def test_repeated_runs_produce_identical_tracked_unit_ids(
        self, flagship_factory, product_id
    ):
        a = run_simulation_traced(flagship_factory, product_id)
        b = run_simulation_traced(flagship_factory, product_id)
        assert {e.unit_id for e in a.events} == {e.unit_id for e in b.events}

    def test_repeated_runs_produce_identical_event_streams(self, flagship_factory, product_id):
        a = run_simulation_traced(flagship_factory, product_id)
        b = run_simulation_traced(flagship_factory, product_id)
        assert a.events == b.events

    def test_repeated_runs_serialize_identically(self, flagship_factory, product_id):
        a = run_simulation_traced(flagship_factory, product_id)
        b = run_simulation_traced(flagship_factory, product_id)
        assert a.model_dump_json() == b.model_dump_json()

    def test_selection_is_a_pure_function_of_the_inputs_not_of_call_order(
        self, flagship_factory, factory, product_id
    ):
        """Running a DIFFERENT factory in between must not shift which units
        the flagship run tracks — no hidden global or cross-run state."""
        first = run_simulation_traced(flagship_factory, product_id)
        run_simulation_traced(factory, product_id)
        second = run_simulation_traced(flagship_factory, product_id)
        assert {e.unit_id for e in first.events} == {e.unit_id for e in second.events}


# 4. The policy is capture-only — simulation results are untouched


class TestPolicyDoesNotAffectSimulation:
    def test_traced_and_untraced_runs_agree_on_every_kpi(self, flagship_factory, product_id):
        plain = run_simulation(flagship_factory, product_id)
        traced = run_simulation_traced(flagship_factory, product_id).summary
        assert traced.model_dump_json() == plain.model_dump_json()

    def test_baseline_traced_and_untraced_runs_agree_on_every_kpi(self, factory, product_id):
        plain = run_simulation(factory, product_id)
        traced = run_simulation_traced(factory, product_id).summary
        assert traced.model_dump_json() == plain.model_dump_json()

    @pytest.mark.parametrize("max_tracked", [1, 5, 40, 500])
    def test_kpis_are_identical_regardless_of_how_many_units_are_tracked(
        self, flagship_factory, product_id, max_tracked
    ):
        """
        The strongest form of "capture-only": changing the selection policy's only
        tuning knob must not move a single KPI digit.
        """
        reference = run_simulation(flagship_factory, product_id).model_dump_json()
        cfg = TracePlaybackConfig(max_tracked_units=max_tracked, sample_count_target=60)
        traced = run_simulation_traced(flagship_factory, product_id, cfg).summary
        assert traced.model_dump_json() == reference

    def test_sampled_series_cover_all_units_not_just_tracked_ones(
        self, flagship_factory, product_id
    ):
        """The aggregate series stay authoritative for the whole population
        — that is what makes bounding the event log safe in the first
        place."""
        cfg = TracePlaybackConfig(max_tracked_units=1, sample_count_target=60)
        trace = run_simulation_traced(flagship_factory, product_id, cfg)
        assert trace.tracked_unit_count <= 1
        assert trace.system_series[-1].completed_units == trace.summary.completed_units
        assert trace.total_unit_count == trace.summary.target_units


# 5. Payload size stays bounded


class TestPayloadBounded:
    def test_flagship_trace_payload_stays_under_1_mb(self, flagship_factory, product_id):
        trace = run_simulation_traced(flagship_factory, product_id)
        size = len(trace.model_dump_json().encode("utf-8"))
        assert size < 1_000_000, f"trace payload grew to {size / 1024:.0f} KB"

    def test_event_count_does_not_grow_with_demand(self, factory, product_id):
        """Spreading tracked units must not reintroduce demand-proportional
        growth: 10x the units, same bounded event log."""
        small = factory.model_copy(
            update={"products": [factory.products[0].model_copy(update={"demand_per_day": 120.0})]}
        )
        large = factory.model_copy(
            update={"products": [factory.products[0].model_copy(update={"demand_per_day": 1200.0})]}
        )
        small_trace = run_simulation_traced(small, product_id)
        large_trace = run_simulation_traced(large, product_id)

        assert large_trace.total_unit_count == 10 * small_trace.total_unit_count
        # Both are capped by the same bound; the larger run must not carry
        # anywhere near 10x the events.
        assert large_trace.tracked_unit_count <= TracePlaybackConfig().max_tracked_units
        assert len(large_trace.events) < 3 * len(small_trace.events)

    def test_events_per_tracked_unit_stay_small(self, flagship_factory, product_id):
        """Each tracked unit contributes a bounded number of milestones
        (route length x events-per-stage), so the total event log is
        bounded by max_tracked_units x that constant."""
        trace = run_simulation_traced(flagship_factory, product_id)
        if trace.tracked_unit_count:
            per_unit = len(trace.events) / trace.tracked_unit_count
            assert per_unit < 40, f"{per_unit:.1f} events per tracked unit is unexpectedly high"
