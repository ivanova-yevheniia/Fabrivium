"""Cross-simulator validation harness — FactoryMind vs Siemens Plant Simulation."""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.integrations.plant_simulation import (  # noqa: E402
    PlantSimulationAdapter,
    PlantSimulationUnavailable,
    exchange_from_factory,
)
from app.models.factory import Factory  # noqa: E402
from app.services.capacity import (  # noqa: E402
    SATURATION_DEMAND_PER_DAY,
    CapacityNotMeasurable,
    _with_demand,
    measure_capacity,
)
from app.services.simulation import run_simulation  # noqa: E402

# The preregistered tolerance.
TOLERANCE_ABSOLUTE_UNITS = 1
TOLERANCE_RELATIVE = 0.001  # 0.1%


def within_tolerance(factorymind: int, plant_simulation: int) -> bool:
    absolute = abs(plant_simulation - factorymind)
    relative = absolute / factorymind if factorymind else math.inf
    return absolute <= TOLERANCE_ABSOLUTE_UNITS and relative <= TOLERANCE_RELATIVE


class Harness:
    """One Plant Simulation session, driven through the shipped adapter."""

    def __init__(self, out_dir: pathlib.Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.adapter = PlantSimulationAdapter()
        self.adapter.connect(visible=False)
        try:
            self.adapter.app.SetStopSimulationOnError(True)
        except Exception:  # noqa: BLE001 - optional hardening
            pass

    def close(self) -> None:
        self.adapter.close()

    def run(
        self,
        label: str,
        factory: Factory,
        product_id: str,
        *,
        release_interval_seconds: float,
        units_to_release: int,
        horizon_seconds: float,
    ) -> dict:
        """Generate, save, reopen, verify, execute, read back — one scenario."""
        package = exchange_from_factory(factory, product_id)
        path = self.out_dir / f"{label}.spp"
        if path.exists():
            path.unlink()

        # Plant Simulation refuses NewModel over a loaded model, and every
        # scenario after the first leaves one loaded.
        try:
            self.adapter.app.CloseModel()
        except Exception:  # noqa: BLE001
            pass

        handoff = self.adapter.build(package, save_path=str(path))
        record: dict = {"label": label, "handoff": handoff.summary()}
        if not handoff.fully_verified:
            record["status"] = "BUILD_FAILED"
            return record

        outcome = self.adapter.execute(
            package,
            release_interval_seconds=release_interval_seconds,
            units_to_release=units_to_release,
            horizon_seconds=horizon_seconds,
        )
        record["execution"] = outcome.summary()
        record["status"] = "OK" if outcome.executed else "RUN_FAILED"
        record["finished_units"] = outcome.finished_units if outcome.executed else None
        return record


def factorymind_run(factory: Factory, product_id: str) -> dict:
    result = run_simulation(factory, product_id)
    kpi = result.operator_kpi
    return {
        "completed_units": result.completed_units,
        "target_units": result.target_units,
        "release_interval_seconds": result.release_interval_seconds,
        "bottleneck": result.system.bottleneck_machine_id,
        "operator_constrained": kpi.operator_constrained if kpi else None,
        "operations_delayed_by_operators": (
            kpi.operations_delayed_by_operators if kpi else None
        ),
        "_result": result,
    }


#: S5 — a line that shares NOTHING with CEC-120: different station count,
#: different cycle times, a capacity-3 stage, a different shift pattern and a
#: different target. Its only purpose is to show the harness is not fitted to
#: the competition case. Every number here was chosen freely, before running it.
NON_CEC_LINE = {
    "name": "Generalisation check line",
    "width": 40.0,
    "length": 20.0,
    "shifts_per_day": 1,
    "hours_per_shift": 7.5,
    #: Deliberately generous, so the workforce is NOT the binding constraint
    #: and the comparison tests material flow, which is what transfers.
    "operators_available": 40,
    "machines": [
        {"id": "gx-cut", "name": "Laser cut", "process_type": "cutting",
         "cycle_time": 18.0, "capacity": 1, "operators_required": 1,
         "width": 3.0, "length": 2.0},
        {"id": "gx-bend", "name": "Press brake", "process_type": "forming",
         "cycle_time": 41.0, "capacity": 3, "operators_required": 1,
         "width": 3.0, "length": 2.0},
        {"id": "gx-weld", "name": "Robot weld", "process_type": "welding",
         "cycle_time": 23.0, "capacity": 1, "operators_required": 1,
         "width": 3.0, "length": 2.0},
        {"id": "gx-test", "name": "Leak test", "process_type": "inspection",
         "cycle_time": 12.5, "capacity": 1, "operators_required": 1,
         "width": 3.0, "length": 2.0},
    ],
    "products": [{
        "id": "gx-product", "name": "Generalisation widget", "demand_per_day": 700.0,
        "route": [
            {"name": "Cut", "machine_id": "gx-cut", "cycle_time": 18.0},
            {"name": "Bend", "machine_id": "gx-bend", "cycle_time": 41.0},
            {"name": "Weld", "machine_id": "gx-weld", "cycle_time": 23.0},
            {"name": "Test", "machine_id": "gx-test", "cycle_time": 12.5},
        ],
    }],
    "buffers": [
        {"id": "gx-b1", "name": "Cut to bend", "capacity": 12,
         "upstream_machine_id": "gx-cut", "downstream_machine_id": "gx-bend"},
        {"id": "gx-b2", "name": "Bend to weld", "capacity": 12,
         "upstream_machine_id": "gx-bend", "downstream_machine_id": "gx-weld"},
        {"id": "gx-b3", "name": "Weld to test", "capacity": 12,
         "upstream_machine_id": "gx-weld", "downstream_machine_id": "gx-test"},
    ],
}


def horizon_of(factory: Factory) -> float:
    return factory.shifts_per_day * factory.hours_per_shift * 3600.0


def exact_release_interval(result, horizon: float) -> float:
    """FactoryMind's release interval at FULL precision."""
    if result.target_units <= 1:
        return 0.0
    return (horizon - result.nominal_route_time_seconds) / (result.target_units - 1)


def compare(label: str, factorymind: int, plant_simulation: int | None, *, gated: bool) -> dict:
    if plant_simulation is None:
        return {"label": label, "gated": gated, "verdict": "NO_RESULT",
                "factorymind": factorymind, "plant_simulation": None}
    absolute = plant_simulation - factorymind
    relative = absolute / factorymind * 100.0 if factorymind else float("nan")
    row = {
        "label": label,
        "gated": gated,
        "factorymind": factorymind,
        "plant_simulation": plant_simulation,
        "absolute_difference": absolute,
        "relative_difference_pct": relative,
        "within_preregistered_tolerance": within_tolerance(factorymind, plant_simulation),
    }
    if gated:
        row["verdict"] = "PASS" if row["within_preregistered_tolerance"] else "FAIL"
    return row


def do_other(harness, factory: Factory, product_id: str, scenarios, comparisons, *, gated: bool):
    """S5 runs against its own product id, so it does not share `do`."""
    fm = factorymind_run(factory, product_id)
    horizon = horizon_of(factory)
    record = harness.run("S5_non_cec_line", factory, product_id,
                         release_interval_seconds=exact_release_interval(fm["_result"], horizon),
                         units_to_release=fm["_result"].target_units,
                         horizon_seconds=horizon)
    record["note"] = "independently specified line, no CEC-120 parameters"
    record["factorymind"] = {k: v for k, v in fm.items() if k != "_result"}
    scenarios.append(record)
    row = compare("S5_non_cec_line", fm["completed_units"], record.get("finished_units"), gated=gated)
    row["note"] = record["note"]
    comparisons.append(row)
    print(f"  {'S5_non_cec_line':26s} FM={fm['completed_units']:<7} "
          f"PS={str(record.get('finished_units')):<7} {row.get('verdict', 'reported')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=pathlib.Path, required=True,
                        help="JSON holding the CEC-120 factory and product_id")
    parser.add_argument("--out", type=pathlib.Path, default=BACKEND.parent / "exports" / "cross_simulator")
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    base_factory = Factory.model_validate(reference["factory"])
    product_id = reference["product_id"]

    try:
        harness = Harness(args.out)
    except PlantSimulationUnavailable as exc:
        print(f"UNAVAILABLE: {exc}")
        return 2

    scenarios: list[dict] = []
    comparisons: list[dict] = []

    def do(label, factory, *, gated, note, saturating=False, capacity_reference=None):
        fm = factorymind_run(factory, product_id)
        result = fm["_result"]
        horizon = horizon_of(factory)
        interval = exact_release_interval(result, horizon)
        number = result.target_units
        if saturating:
            interval, number = 1.0, -1
        record = harness.run(label, factory, product_id,
                             release_interval_seconds=interval,
                             units_to_release=number,
                             horizon_seconds=horizon)
        record["note"] = note
        record["factorymind"] = {k: v for k, v in fm.items() if k != "_result"}
        scenarios.append(record)
        x = capacity_reference if capacity_reference is not None else fm["completed_units"]
        row = compare(label, x, record.get("finished_units"), gated=gated)
        row["note"] = note
        comparisons.append(row)
        print(f"  {label:26s} FM={x:<7} PS={str(record.get('finished_units')):<7} "
              f"{row.get('verdict', 'reported')}")
        return fm

    print("S1/S1b/S2 — CEC-120 baseline family")
    neutral = base_factory.model_copy(update={"operators_available": 12})
    do("S1_workforce_neutral", neutral, gated=True,
       note="operators=12; FactoryMind reports operations_delayed_by_operators=0")
    do("S1b_saturating_source", neutral, gated=False, saturating=True,
       note="same line, saturating source; must not change the answer")
    do("S2_competition_baseline", base_factory, gated=False,
       note="operators=8 + 50-unit buffers; NEITHER is in the .spp — predicted mismatch")

    # Selected plan
    plan_path = args.reference.parent / "cec120_selected_plan.json"
    if plan_path.exists():
        print("S3/S4 — selected plan")
        plan_factory = Factory.model_validate(json.loads(plan_path.read_text(encoding="utf-8"))["factory"])
        target = float(next(p.demand_per_day for p in plan_factory.products if p.id == product_id))

        # S3 — DELIVERED output.
        do("S3_plan_delivered", plan_factory, gated=True,
           note="demand-capped delivered output; workforce non-binding on this run")

        # S4 — CAPACITY.
        try:
            cap = measure_capacity(plan_factory, product_id, target_units_per_day=target)
            do("S4a_plan_capacity_as_planned",
               _with_demand(plan_factory, product_id, SATURATION_DEMAND_PER_DAY),
               gated=False,
               note="saturated; FactoryMind's capacity run is workforce-constrained at 10 operators",
               capacity_reference=cap.capacity_units_per_day)
        except (CapacityNotMeasurable, ValueError) as exc:
            print(f"  S4a capacity not measurable: {exc}")

        # S4b raises the workforce until FactoryMind itself reports it is no
        # longer binding, which is the only staffing at which a capacity
        # comparison against a workforce-free model means anything.
        relaxed = plan_factory.model_copy(update={"operators_available": 14})
        try:
            cap_relaxed = measure_capacity(relaxed, product_id, target_units_per_day=target)
            do("S4b_plan_capacity_workforce_neutral",
               _with_demand(relaxed, product_id, SATURATION_DEMAND_PER_DAY),
               gated=True,
               note="saturated, operators=14; FactoryMind reports the workforce non-binding",
               capacity_reference=cap_relaxed.capacity_units_per_day)
        except (CapacityNotMeasurable, ValueError) as exc:
            print(f"  S4b capacity not measurable: {exc}")
    else:
        print(f"S3/S4 skipped — no selected plan at {plan_path}")

    # S5: generalisation
    print("S5 — non-CEC line (proves the harness is not fitted to CEC-120)")
    other = Factory.model_validate(NON_CEC_LINE)
    fm5 = factorymind_run(other, "gx-product")
    if fm5["operations_delayed_by_operators"]:
        print("  S5 line turned out workforce-constrained; reporting, not gating")
    do_other(harness, other, "gx-product", scenarios, comparisons,
             gated=not fm5["operations_delayed_by_operators"])

    harness.close()

    evidence = {"tolerance": {"absolute_units": TOLERANCE_ABSOLUTE_UNITS,
                              "relative": TOLERANCE_RELATIVE},
                "scenarios": scenarios, "comparisons": comparisons}
    out = args.out / "cross_simulator_evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(f"\nraw evidence: {out}")

    gated = [c for c in comparisons if c["gated"]]
    failed = [c for c in gated if c.get("verdict") != "PASS"]
    print(f"gated scenarios: {len(gated)}   failing: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
