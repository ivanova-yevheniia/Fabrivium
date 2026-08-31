"""Ground truth for the Siemens handoff, read out of Plant Simulation itself."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.integrations.plant_simulation.adapter import PlantSimulationAdapter  # noqa: E402
from app.integrations.plant_simulation.from_factory import exchange_from_factory  # noqa: E402
from app.models.factory import Factory  # noqa: E402
from app.models.layout import FactoryLayout  # noqa: E402

API = "http://localhost:8000"


def load_project(project_id: str) -> dict:
    with urllib.request.urlopen(f"{API}/projects/{project_id}") as response:
        return json.load(response)["project"]["state"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="bc4f970cd40d4438")
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    state = load_project(args.project)
    concept = state["concept"]
    factory = Factory.model_validate(concept["factory"])
    layout = FactoryLayout.model_validate(concept["layout"]) if concept.get("layout") else None
    selections = state.get("equipment", {}).get("selections") or None

    package = exchange_from_factory(
        factory,
        concept["product_id"],
        layout=layout,
        equipment_selections=selections,
    )

    print("=" * 72)
    print("PACKAGE (what FactoryMind is sending)")
    print("=" * 72)
    for station in package.stations:
        print(
            f"  {station.id:16} {station.name[:26]:28} "
            f"cycle={station.cycle_time_seconds:>6} cap={station.capacity} "
            f"xy=({station.x}, {station.y}) "
            f"equip={station.selected_model or '-'}"
        )
    print(f"  flows: {len(package.flow)}")

    adapter = PlantSimulationAdapter()
    print()
    print("=" * 72)
    print("CONNECTING")
    print("=" * 72)
    adapter.connect(visible=args.visible)
    print(f"  version : {adapter.product_version}")
    print(f"  prog_id : {adapter.prog_id}")

    plan = adapter.plan_for(package)
    print()
    print("PLANNED LAYOUT")
    print(f"  mode           : {plan.mode}")
    print(f"  reason         : {plan.reason}")
    print(f"  min separation : {plan.min_separation}")
    for name, (x, y) in plan.positions.items():
        print(f"    {name:28} ({x:>6}, {y:>6})")

    out = pathlib.Path(os.environ.get("TEMP", ".")) / "fm-probe" / "probe.spp"
    out.parent.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 72)
    print("BUILD + READ-BACK")
    print("=" * 72)
    result = adapter.build(package, save_path=str(out))

    print(f"  ok               : {result.ok}")
    print(f"  model_path       : {result.model_path}")
    print(f"  model_bytes      : {result.model_bytes}")
    print(f"  layout_mode      : {result.layout_mode}")
    print(f"  layout_reason    : {result.layout_reason}")
    print(f"  min separation   : {result.layout_min_separation}")
    print(f"  overlaps         : {result.overlaps or 'none'}")
    print(f"  route_complete   : {result.route_complete}")
    print(f"  route_walked     : {' -> '.join(result.route_walked)}")
    print(f"  disconnected     : {result.disconnected or 'none'}")
    print(f"  traversal_units  : {result.traversal_units}")
    print(f"  traversal_verified: {result.traversal_verified}")
    print(f"  errors           : {result.errors or 'none'}")

    print()
    print("  POSITIONS READ BACK OUT OF THE MODEL")
    for position in result.positions:
        print(
            f"    {position.name:28} asked=({position.x_expected:>6},{position.y_expected:>6}) "
            f"got=({position.x_actual},{position.y_actual}) verified={position.verified}"
            f"{' ERR=' + position.error if position.error else ''}"
        )

    print()
    print("  STATIONS")
    for station in result.stations:
        print(
            f"    {station.name_expected:28} actual={station.name_actual} "
            f"cycle {station.cycle_time_expected} -> {station.cycle_time_actual} "
            f"cap {station.capacity_expected} -> {station.capacity_actual}"
        )

    print()
    print("  LINKS")
    for link in result.links:
        print(f"    {link.from_name:24} -> {link.to_name:24} got={link.actual_successor} verified={link.verified}")

    if not args.keep_open:
        adapter.close()
    else:
        print()
        print(f"  LEFT OPEN for manual inspection. Model saved at: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
