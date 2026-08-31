"""Replaying a verified scenario from a SAVED project."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.factory import Factory
from app.models.strategy import StrategyActionSummary, StrategyMetrics
from app.services.playback_reconstruction import (
    PlaybackNotReplayable,
    reconstruct_factory,
    replay_support,
    verify_reproduces,
)
from app.services.simulation import run_simulation, run_simulation_traced

EXAMPLES_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture(scope="module")
def base_factory() -> Factory:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture(scope="module")
def product_id(base_factory: Factory) -> str:
    return base_factory.products[0].id


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def summary(**overrides) -> StrategyActionSummary:
    return StrategyActionSummary(**overrides)


def metrics_of(result) -> StrategyMetrics:
    """The subset of a run a project stores for a strategy."""
    return StrategyMetrics(
        goal_met=result.demand_met,
        stop_reason="GOAL_REACHED" if result.demand_met else "BASELINE",
        completed_units=result.completed_units,
        target_units=result.target_units,
        demand_gap_units=result.demand_gap_units,
        throughput_per_hour=result.throughput_per_hour,
        work_in_progress=result.system.work_in_progress,
        average_flow_time_seconds=result.system.average_flow_time_seconds,
        bottleneck_machine_id=result.system.bottleneck_machine_id,
    )


# What the summary can and cannot rebuild

class TestReplaySupport:
    def test_the_baseline_needs_no_reconstruction(self):
        # The concept factory IS the factory the baseline was verified on.
        assert replay_support(None).replayable is True

    @pytest.mark.parametrize("action_type", [
        "CHANGE_SHIFT_CONFIGURATION",
        "CHANGE_OPERATOR_CAPACITY",
        "ADD_PARALLEL_MACHINE",
    ])
    def test_levers_the_summary_determines_exactly_are_replayable(self, action_type):
        assert replay_support(summary(action_count=1, action_types=[action_type])).replayable

    @pytest.mark.parametrize("action_type", [
        "CHANGE_MACHINE_CAPACITY",
        "CHANGE_MACHINE_CYCLE_TIME",
        "CHANGE_BUFFER_CAPACITY",
        "CHANGE_DEMAND",
        "REMOVE_MACHINE",
    ])
    def test_levers_the_summary_does_not_record_fail_closed(self, action_type):
        """A missing figure is refused, never guessed."""
        check = replay_support(summary(action_count=1, action_types=[action_type]))
        assert check.replayable is False
        assert check.reason and "cannot be replayed" in check.reason

    def test_the_reason_is_a_sentence_not_an_identifier(self):
        check = replay_support(summary(action_count=1, action_types=["CHANGE_MACHINE_CYCLE_TIME"]))
        assert "cycle time" in check.reason
        assert "CHANGE_MACHINE_CYCLE_TIME" not in check.reason

    def test_unaccounted_machines_fail_closed(self):
        """More machines than the summary can name is a different factory."""
        check = replay_support(summary(
            action_count=1, action_types=["ADD_PARALLEL_MACHINE"],
            added_machine_ids=["m-assembly"], added_machine_count=2,
        ))
        assert check.replayable is False

    def test_a_buffer_change_is_not_parsed_out_of_its_sentence(self):
        """`buffer_changes` holds "buf-1: 50 -> 100" — prose, for a reader."""
        check = replay_support(summary(
            action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"],
            buffer_changes=["buf-1: 50 -> 100"],
        ))
        assert check.replayable is False


class TestReconstructFactory:
    def test_shift_expansion_rebuilds_the_operating_model(self, base_factory):
        rebuilt = reconstruct_factory(
            base_factory,
            summary(action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=1),
        )
        assert rebuilt.shifts_per_day == base_factory.shifts_per_day + 1
        assert rebuilt.hours_per_shift == base_factory.hours_per_shift
        assert len(rebuilt.machines) == len(base_factory.machines)

    def test_parallel_machines_are_rebuilt_through_the_canonical_primitive(self, base_factory):
        """Same clone ids as the arena produced, not merely the same count."""
        source = base_factory.machines[0].id
        rebuilt = reconstruct_factory(
            base_factory,
            summary(
                action_count=1, action_types=["ADD_PARALLEL_MACHINE"],
                added_machine_ids=[source], added_machine_count=1,
            ),
        )
        assert len(rebuilt.machines) == len(base_factory.machines) + 1
        clone = rebuilt.machines[-1]
        assert clone.id == f"{source}-parallel-1"
        assert clone.parallel_of_machine_id == source

    def test_reconstruction_does_not_mutate_the_baseline(self, base_factory):
        before = base_factory.model_dump()
        reconstruct_factory(
            base_factory,
            summary(action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=2),
        )
        assert base_factory.model_dump() == before

    def test_the_baseline_is_returned_unchanged(self, base_factory):
        assert reconstruct_factory(base_factory, None) is base_factory

    def test_an_unreplayable_plan_raises_rather_than_approximating(self, base_factory):
        with pytest.raises(PlaybackNotReplayable):
            reconstruct_factory(
                base_factory,
                summary(action_count=1, action_types=["CHANGE_MACHINE_CYCLE_TIME"]),
            )


class TestVerificationGate:
    def test_a_run_that_reproduces_the_stored_metrics_passes(self, base_factory, product_id):
        result = run_simulation(base_factory, product_id)
        verify_reproduces(result, metrics_of(result))  # does not raise

    def test_a_run_that_lands_elsewhere_is_refused(self, base_factory, product_id):
        """Stale verification cannot be replayed."""
        result = run_simulation(base_factory, product_id)
        stale = metrics_of(result).model_copy(update={"completed_units": result.completed_units + 25})
        with pytest.raises(PlaybackNotReplayable) as exc:
            verify_reproduces(result, stale)
        assert "no longer" in str(exc.value)


# The endpoint a reopened project actually calls

class TestVerifiedPlaybackEndpoint:
    def test_baseline_replays_without_any_session(self, client, base_factory, product_id):
        verified = run_simulation(base_factory, product_id)
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": None,
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        assert response.status_code == 200, response.text
        trace = response.json()
        assert trace["summary"]["completed_units"] == verified.completed_units

    def test_a_plan_replays_from_its_saved_summary_alone(self, client, base_factory, product_id):
        """The whole point: no session, no snapshot, no stored factory."""
        planned = reconstruct_factory(
            base_factory,
            summary(action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=1),
        )
        verified = run_simulation(planned, product_id)

        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": summary(
                action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=1,
            ).model_dump(mode="json"),
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        assert response.status_code == 200, response.text
        trace = response.json()
        assert trace["summary"]["completed_units"] == verified.completed_units
        # The plan's own horizon, not the baseline's.
        assert trace["horizon_seconds"] > base_factory.shifts_per_day * base_factory.hours_per_shift * 3600

    def test_the_terminal_frame_equals_the_verified_output(self, client, base_factory, product_id):
        """The invariant from the previous fix, now guaranteed structurally."""
        verified = run_simulation(base_factory, product_id)
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": None,
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        trace = response.json()
        terminal = max(trace["system_series"], key=lambda s: s["timestamp"])
        assert terminal["timestamp"] == pytest.approx(trace["horizon_seconds"])
        assert terminal["completed_units"] == verified.completed_units

    def test_an_unreplayable_plan_is_refused_with_a_reason(self, client, base_factory, product_id):
        verified = run_simulation(base_factory, product_id)
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": summary(
                action_count=1, action_types=["CHANGE_MACHINE_CAPACITY"],
            ).model_dump(mode="json"),
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        assert response.status_code == 409
        assert "cannot be replayed" in response.json()["detail"]

    def test_stale_verification_is_refused_by_the_endpoint(self, client, base_factory, product_id):
        verified = run_simulation(base_factory, product_id)
        stale = metrics_of(verified).model_copy(
            update={"completed_units": verified.completed_units + 100}
        )
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": None,
            "expected": stale.model_dump(mode="json"),
        })
        assert response.status_code == 409
        assert "no longer" in response.json()["detail"]

    def test_an_unknown_product_is_a_400(self, client, base_factory, product_id):
        verified = run_simulation(base_factory, product_id)
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": "p-does-not-exist",
            "actions": None,
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        assert response.status_code == 400

    def test_replaying_runs_the_real_simulator(self, client, base_factory, product_id):
        """Not a cache, not a KPI dressed as frames."""
        verified = run_simulation(base_factory, product_id)
        response = client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": None,
            "expected": metrics_of(verified).model_dump(mode="json"),
        })
        trace = response.json()
        assert len(trace["system_series"]) > 2
        assert trace["summary"] == json.loads(verified.model_dump_json())

    def test_replaying_is_observational(self, client, base_factory, product_id):
        """Playing changes nothing about the factory it played."""
        before = base_factory.model_dump()
        verified = run_simulation(base_factory, product_id)
        client.post("/simulation/playback/verified", json={
            "factory": base_factory.model_dump(mode="json"),
            "product_id": product_id,
            "actions": summary(
                action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=1,
            ).model_dump(mode="json"),
            "expected": metrics_of(run_simulation(
                reconstruct_factory(base_factory, summary(
                    action_count=1, action_types=["CHANGE_SHIFT_CONFIGURATION"], added_shift_count=1,
                )), product_id,
            )).model_dump(mode="json"),
        })
        assert base_factory.model_dump() == before
        assert run_simulation(base_factory, product_id).completed_units == verified.completed_units
