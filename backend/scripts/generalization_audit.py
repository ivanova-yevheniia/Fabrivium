"""Provenance and leakage audit over the three generalization case results."""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
RESULTS = ROOT / "examples" / "generalization" / "results"
DEMO = ROOT / "examples" / "electronics_line.json"


def demo_values() -> dict[str, set[float]]:
    data = json.loads(DEMO.read_text(encoding="utf-8"))
    cycles = {
        float(step["cycle_time"])
        for product in data.get("products", [])
        for step in product.get("route", [])
    }
    return {
        "cycle_times": cycles,
        "costs": {float(m.get("purchase_cost", 0.0)) for m in data.get("machines", [])},
        "capacities": {float(m.get("capacity", 0)) for m in data.get("machines", [])},
        "buffers": {float(b["capacity"]) for b in data.get("buffers", [])},
        "target": {float(p.get("demand_per_day", 0)) for p in data.get("products", [])},
        "schedule": {float(data["shifts_per_day"]), float(data["hours_per_shift"])},
    }


STAGE_FIELDS = (
    "cycle_time",
    "capacity",
    "operators_required",
    "width",
    "length",
    "purchase_cost",
)
DRAFT_FIELDS = (
    "production_target",
    "shifts_per_day",
    "hours_per_shift",
    "operators_available",
    "floor_width",
    "floor_length",
    "budget",
)


def audit(case_path: pathlib.Path, demo: dict[str, set[float]]) -> dict:
    data = json.loads(case_path.read_text(encoding="utf-8"))
    draft = data.get("final_draft")
    report: dict = {"case": data["case"], "product": data["product_name"], "findings": []}
    if draft is None:
        report["findings"].append("NO FINAL CONCEPT — the case stopped before one was built.")
        return report

    by_source: dict[str, list[str]] = {}

    def record(label: str, sourced: dict | None) -> None:
        if sourced is None:
            return
        by_source.setdefault(sourced.get("source", "MISSING"), []).append(
            f"{label}={sourced.get('value')}"
        )

    for field in DRAFT_FIELDS:
        record(field, draft.get(field))
    for stage in draft.get("stages", []):
        for field in STAGE_FIELDS:
            record(f"{stage['id']}.{field}", stage.get(field))
    for buffer in draft.get("buffers", []):
        record(f"{buffer['id']}.capacity", buffer.get("capacity"))

    report["provenance"] = {k: sorted(v) for k, v in sorted(by_source.items())}

    # 1. no example data
    if "EXAMPLE_DATA" in by_source:
        report["findings"].append(
            f"EXAMPLE_DATA reached this concept: {by_source['EXAMPLE_DATA']}"
        )

    # 2.
    leaks: list[str] = []
    coincidences: list[str] = []

    def classify(label: str, sourced: dict, matched: str) -> None:
        source = sourced.get("source")
        line = f"{label}={sourced.get('value')} matches {matched} (source={source}, detail={sourced.get('detail')!r})"
        (leaks if source == "EXAMPLE_DATA" else coincidences).append(line)

    for stage in draft.get("stages", []):
        cycle = stage.get("cycle_time") or {}
        if cycle.get("value") is not None and float(cycle["value"]) in demo["cycle_times"]:
            classify(f"{stage['id']}.cycle_time", cycle, "a demo cycle time")
        cost = stage.get("purchase_cost") or {}
        if cost.get("value") not in (None, 0.0) and float(cost["value"]) in demo["costs"]:
            classify(f"{stage['id']}.purchase_cost", cost, "a demo purchase cost")
    target = draft.get("production_target") or {}
    if target.get("value") is not None and float(target["value"]) in demo["target"]:
        classify("production_target", target, "the demo target")

    report["leaks"] = leaks
    report["value_coincidences"] = coincidences
    report["findings"].extend(leaks)

    # 3. unknown never became a number
    understanding = data["steps"]["describe"]["body"]["understanding"]
    numeric_unknowns = [
        f["key"]
        for f in understanding["facts"]
        if f["status"] in ("UNKNOWN", "CONFLICT") and f.get("quantity") is not None
    ]
    if numeric_unknowns:
        report["findings"].append(
            f"a fact left UNKNOWN/CONFLICT by the source carries a quantity: {numeric_unknowns}"
        )

    # Context
    simulation = data["steps"].get("simulation", {}).get("body", {})
    report["simulation"] = {
        "completed_units": simulation.get("completed_units"),
        "target_units": simulation.get("target_units"),
        "demand_met": simulation.get("demand_met"),
        "demand_gap_units": simulation.get("demand_gap_units"),
        "bottleneck": (simulation.get("system") or {}).get("bottleneck_machine_id"),
    }
    arena = data["steps"].get("strategies", {}).get("body", {}).get("arena", {})
    report["arena"] = {
        "recommended": arena.get("recommended_strategy_id"),
        "summary": arena.get("summary"),
        "families_without_options": arena.get("families_without_options"),
        "strategies": [
            {
                "id": s["strategy_id"],
                "family": s["family"],
                "goal_met": s["metrics"]["goal_met"],
                "completed_units": s["metrics"]["completed_units"],
                "gap": s["metrics"]["demand_gap_units"],
                "actions": s["actions"]["action_types"],
            }
            for s in arena.get("strategies", [])
        ],
    }
    return report


def main() -> int:
    demo = demo_values()
    out = []
    for path in sorted(RESULTS.glob("case_*.json")):
        report = audit(path, demo)
        out.append(report)
        print(f"=== CASE {report['case']} — {report['product']}")
        for source, values in report.get("provenance", {}).items():
            print(f"    {source:22} {len(values):3}  {', '.join(values[:6])}")
        print(f"    simulation: {report.get('simulation')}")
        print(f"    arena:      {json.dumps(report.get('arena'), ensure_ascii=False)[:400]}")
        for line in report.get("value_coincidences", []):
            print(f"    ~~ coincidence, not leakage: {line}")
        if report["findings"]:
            for finding in report["findings"]:
                print(f"    !! {finding}")
        else:
            print("    no leakage or unknown-substitution finding")
        print()
    (RESULTS / "audit.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
