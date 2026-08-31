"""Cross-simulator EXECUTION — the contract, pinned without Siemens installed."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.integrations.plant_simulation.adapter import (
    HORIZON_EPSILON,
    ExecutionResult,
    PlantSimulationAdapter,
)
from app.integrations.plant_simulation.adapter import simtalk_identifier
from app.integrations.plant_simulation.from_factory import exchange_from_factory
from app.models.factory import Factory
from tests.test_plant_simulation_adapter import FakePlantSim

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def package():
    factory = Factory.model_validate(
        json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8"))
    )
    return exchange_from_factory(factory, factory.products[0].id)


class ExecutingFake(FakePlantSim):
    """A fake that can also be RUN."""

    def __init__(self, *, finished: int = 1105, running_forever: bool = False,
                 errored: bool = False, short_horizon: bool = False,
                 drain_unreadable: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.finished = finished
        self.running_forever = running_forever
        self.errored = errored
        self.short_horizon = short_horizon
        self.drain_unreadable = drain_unreadable
        self.settings: dict[str, str] = {}
        self.reset_called = False

    def IsSimulationRunning(self):
        return self.running_forever

    def HasSimulationError(self):
        return self.errored

    def ResetSimulation(self, *_):
        self.reset_called = True

    def StopSimulation(self, *_):
        self.running_forever = False

    def ExecuteSimTalk(self, expr: str):
        # Record the three execution settings verbatim so a test can assert
        # exactly what was written into the model.
        for key in ("End", "Interval", "Number"):
            marker = f".{key} := "
            if marker in expr:
                self.settings[key] = expr.split(marker)[1].split(";")[0]
        if ".SimTime >=" in expr:
            return "no" if self.short_horizon else "yes"
        if "SimTime" in expr:
            return "16:00:00.0000"
        if "Drain.StatNumIn" in expr:
            return "not-a-number" if self.drain_unreadable else str(self.finished)
        if "Source.StatNumOut" in expr:
            return str(self.finished + 5)
        if "StatWorkingPortion" in expr:
            return "0.9994"
        if "StatBlockingPortion" in expr or "StatWaitingPortion" in expr:
            return "0.0"
        return super().ExecuteSimTalk(expr)


def executed(fake: ExecutingFake, **kwargs) -> ExecutionResult:
    adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
    adapter.connect()
    pkg = package()
    adapter.build(pkg, verify_traversal=False)
    return adapter.execute(
        pkg,
        release_interval_seconds=kwargs.pop("release_interval_seconds", 30.220116),
        units_to_release=kwargs.pop("units_to_release", 1900),
        horizon_seconds=kwargs.pop("horizon_seconds", 57600.0),
        **kwargs,
    )


# The horizon is aligned to FactoryMind's, not to Plant Simulation's default

class TestHorizonSemantics:
    def test_the_horizon_carries_factorymind_s_own_epsilon(self):
        # Plant Simulation terminates STRICTLY BEFORE End; FactoryMind runs to
        # horizon + 1e-6. Without the epsilon a completion landing exactly on
        # the horizon is silently dropped. Measured: 359 vs 360 on the control
        # model. See docs/CROSS_SIMULATOR_SEMANTICS.md section 1.
        assert HORIZON_EPSILON == 1e-6

    def test_the_epsilon_is_actually_written_into_the_model(self):
        fake = ExecutingFake()
        executed(fake)
        assert fake.settings["End"] == f"57600.0 + {HORIZON_EPSILON}"

    def test_a_run_that_stops_short_of_the_horizon_is_not_a_result(self):
        result = executed(ExecutingFake(short_horizon=True))
        assert result.executed is False
        assert result.reached_horizon is False
        assert any("without reaching" in e for e in result.errors)


# No fake success

class TestARunThatDidNotFinishIsNeverAResult:
    def test_a_timeout_is_reported_as_a_failed_run(self):
        result = executed(ExecutingFake(running_forever=True), timeout_seconds=0.5)
        assert result.timed_out is True
        assert result.executed is False
        assert result.finished_units is None
        assert any("still running" in e for e in result.errors)

    def test_a_simulation_error_is_not_reported_as_a_number(self):
        result = executed(ExecutingFake(errored=True))
        assert result.had_error is True
        assert result.executed is False

    def test_an_unreadable_drain_is_reported_rather_than_defaulted(self):
        result = executed(ExecutingFake(drain_unreadable=True))
        assert result.finished_units is None
        assert result.executed is False
        assert any("drain" in e.lower() for e in result.errors)

    def test_an_unconnected_adapter_refuses_to_execute(self):
        adapter = PlantSimulationAdapter(dispatch=lambda _p: ExecutingFake())
        result = adapter.execute(package(), release_interval_seconds=1.0, units_to_release=10)
        assert result.executed is False
        assert any("Not connected" in e for e in result.errors)

    def test_a_good_run_is_reported_as_executed(self):
        result = executed(ExecutingFake(finished=1104))
        assert result.executed is True
        assert result.finished_units == 1104
        assert result.reached_horizon is True
        assert result.errors == []


# Demand-capped and capacity runs must stay distinguishable

class TestDemandCappedIsNotCapacity:
    def test_a_capped_run_records_the_cap_it_was_given(self):
        fake = ExecutingFake()
        result = executed(fake, units_to_release=1900, release_interval_seconds=30.220116)
        assert result.units_to_release == 1900
        assert fake.settings["Number"] == "1900"
        assert fake.settings["Interval"] == "30.220116"

    def test_an_uncapped_capacity_run_is_recorded_as_uncapped(self):
        fake = ExecutingFake()
        result = executed(fake, units_to_release=-1, release_interval_seconds=1.0)
        assert result.units_to_release == -1
        assert fake.settings["Number"] == "-1"

    def test_the_two_are_not_interchangeable_in_the_record(self):
        capped = executed(ExecutingFake(), units_to_release=1900)
        uncapped = executed(ExecutingFake(), units_to_release=-1)
        assert capped.units_to_release != uncapped.units_to_release


# The preregistered tolerance, applied exactly as written

class TestPreregisteredTolerance:
    """`within_tolerance` is the gate. Both conditions must hold:
    |X-Y| <= 1 unit AND |X-Y|/X <= 0.1%.
    """

    @staticmethod
    def gate(x: int, y: int) -> bool:
        import importlib.util

        path = (
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "cross_simulator_validation.py"
        )
        spec = importlib.util.spec_from_file_location("xsim_harness", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.within_tolerance(x, y)

    def test_exact_agreement_passes(self):
        assert self.gate(1104, 1104) is True

    def test_one_unit_apart_passes_at_the_boundary(self):
        # S1/S3/S4b live here: 1900 vs 1899 is 0.053%.
        assert self.gate(1900, 1899) is True
        assert self.gate(2463, 2462) is True

    def test_two_units_apart_fails(self):
        # S5 lives here: 700 vs 698 is 0.286%, outside BOTH conditions.
        assert self.gate(700, 698) is False

    def test_one_unit_apart_still_fails_when_the_relative_bound_is_breached(self):
        # The relative condition is not decoration: on a small line one unit
        # is a large fraction, and the gate must refuse it.
        assert self.gate(500, 499) is False

    def test_the_predicted_workforce_mismatch_is_nowhere_near_passing(self):
        # S2: FactoryMind 1058 against a workforce-free 1104.
        assert self.gate(1058, 1104) is False


# The result carries evidence, not a verdict

class TestTheResultIsEvidence:
    def test_the_limiting_station_is_derived_from_measured_utilisation(self):
        result = ExecutionResult()
        result.station_utilisation = {"A": 0.41, "Screwdriving": 0.99, "B": 0.57}
        assert result.limiting_station == "Screwdriving"

    def test_no_utilisation_means_no_limiting_station_rather_than_a_guess(self):
        assert ExecutionResult().limiting_station is None

    def test_the_summary_reports_the_release_policy_that_was_used(self):
        summary = executed(ExecutingFake()).summary()
        assert summary["release_interval_seconds"] == 30.220116
        assert summary["units_to_release"] == 1900
        assert summary["horizon_seconds"] == 57600.0

    def test_a_fresh_result_claims_nothing(self):
        blank = ExecutionResult()
        assert blank.executed is False
        assert blank.finished_units is None
        assert blank.summary()["executed"] is False


# Station capacity — the read-back gap this phase closed

class TestStationCapacityIsVerified:
    def test_a_capacity_that_does_not_survive_transfer_is_not_verified(self):
        # Before this phase, Capacity was written and never read back: a stage
        # whose capacity silently stayed 1 still reported as verified.
        fake = FakePlantSim(fail_on="verify_capacity")
        adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
        adapter.connect()
        result = adapter.build(package())
        assert result.fully_verified is False
        assert all(s.capacity_actual == 99 for s in result.stations)

    def test_a_multi_unit_stage_cannot_be_a_single_proc(self, tmp_path):
        # The live product refuses `Capacity := N` on a SingleProc, so a
        # stage with capacity > 1 must be built from a different class, or
        # the handoff is silently wrong. The fake reproduces the refusal.
        #
        # It used to be a ParallelProc with XDim = N, chosen on a SATURATED
        # throughput measurement. Re-measured at LOW LOAD against 2404, a
        # ParallelProc is a BATCH of N: it does not start processing until
        # all N places fill, so three units released into a six-place stage
        # reach the drain never. A Buffer with Capacity = N and
        # ProcTime = the cycle time is N independent servers — 3 of 3
        # delivered at low load, and the same 714 units/hour saturated.
        factory = Factory.model_validate(
            json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8"))
        )
        machines = [
            m.model_copy(update={"capacity": 3}) if m.id == factory.machines[0].id else m
            for m in factory.machines
        ]
        parallel = factory.model_copy(update={"machines": machines})
        pkg = exchange_from_factory(parallel, parallel.products[0].id)
        assert any(s.capacity == 3 for s in pkg.stations)

        fake = FakePlantSim()
        adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
        adapter.connect()
        result = adapter.build(pkg, save_path=str(tmp_path / "parallel.spp"))

        assert result.fully_verified is True
        create = next(
            e for e in fake.executed
            if "createObject" in e and f'o.Name := "{simtalk_identifier(pkg.stations[0].name)}"' in e
        )
        assert "Einzelstation" not in create, "a SingleProc cannot hold three units"
        assert "Parallelstation" not in create, "a ParallelProc batches; it is not three servers"
        assert "Puffer" in create and "o.Capacity := 3" in create
        multi = next(s for s in result.stations if s.capacity_expected == 3)
        assert multi.capacity_actual == 3


# Buffers — transferred because omitting them changes the physics

class TestBuffersAreTransferredAndVerified:
    def test_wired_buffers_reach_the_model_and_are_read_back(self, tmp_path):
        fake = FakePlantSim()
        adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
        adapter.connect()
        result = adapter.build(package(), save_path=str(tmp_path / "b.spp"))
        assert result.buffers, "the demo line wires buffers; none reached the model"
        assert result.buffers_verified == len(result.buffers)
        assert result.fully_verified is True

    def test_a_buffer_sits_between_the_stations_it_connects(self, tmp_path):
        # A buffer that exists but is not in the chain changes nothing, which
        # would be the worst outcome: present in the file, absent from the
        # physics.
        fake = FakePlantSim()
        adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
        adapter.connect()
        result = adapter.build(package(), save_path=str(tmp_path / "b.spp"))
        names = {b.name_expected for b in result.buffers}
        linked = {link.from_name for link in result.links} | {link.to_name for link in result.links}
        assert names <= linked, "a transferred buffer was left out of the material flow"

    def test_a_buffer_that_loses_its_capacity_is_not_verified(self, tmp_path):
        fake = FakePlantSim(fail_on="verify_capacity")
        adapter = PlantSimulationAdapter(dispatch=lambda _p: fake)
        adapter.connect()
        result = adapter.build(package(), save_path=str(tmp_path / "b.spp"))
        assert result.fully_verified is False


# Raw evidence survives

class TestEvidenceIsPersistable:
    def test_the_execution_summary_round_trips_through_json(self, tmp_path):
        result = executed(ExecutingFake(finished=1104))
        destination = tmp_path / "evidence.json"
        destination.write_text(json.dumps(result.summary(), default=str), encoding="utf-8")
        restored = json.loads(destination.read_text(encoding="utf-8"))
        assert restored["finished_units"] == 1104
        assert restored["executed"] is True
        assert restored["horizon_seconds"] == 57600.0

    @pytest.mark.parametrize("field", ["executed", "finished_units", "horizon_seconds",
                                       "release_interval_seconds", "units_to_release",
                                       "limiting_station", "errors"])
    def test_the_summary_carries_what_a_reader_needs_to_check_the_claim(self, field):
        assert field in executed(ExecutingFake()).summary()
