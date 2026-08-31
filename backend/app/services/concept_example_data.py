"""Example engineering data for a factory concept — Phase 13."""

from __future__ import annotations

import json
import pathlib

from app.models.concept import (
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)

# Shown next to every value this module fills in.
EXAMPLE_DATASET_NAME = "Electronics Assembly Demo Dataset"

_EXAMPLES_DIR = pathlib.Path(__file__).resolve().parents[3] / "examples"
_EXAMPLE_FACTORY_FILE = _EXAMPLES_DIR / "electronics_line.json"


def _load_example_factory() -> dict:
    """The bundled demo factory, as raw JSON."""
    if not _EXAMPLE_FACTORY_FILE.exists():
        raise FileNotFoundError(
            f"Example engineering dataset not found at {_EXAMPLE_FACTORY_FILE}."
        )
    return json.loads(_EXAMPLE_FACTORY_FILE.read_text(encoding="utf-8"))


def _example_machines_by_process_type(data: dict) -> dict[str, dict]:
    return {m["process_type"].lower(): m for m in data.get("machines", [])}


def _example_route_cycle_times(data: dict) -> dict[str, float]:
    """Cycle time per machine id, taken from the ROUTE."""
    result: dict[str, float] = {}
    for product in data.get("products", []):
        for step in product.get("route", []):
            result[step["machine_id"]] = float(step["cycle_time"])
    return result


def apply_example_engineering_data(draft: FactoryConceptDraft) -> FactoryConceptDraft:
    """Fill this concept's missing ENGINEERING values from the demo dataset."""
    data = _load_example_factory()
    by_type = _example_machines_by_process_type(data)
    route_cycles = _example_route_cycle_times(data)

    def sourced_float(value: float) -> SourcedFloat:
        return SourcedFloat.of(value, ValueSource.EXAMPLE_DATA, EXAMPLE_DATASET_NAME)

    def sourced_int(value: int) -> SourcedInt:
        return SourcedInt.of(value, ValueSource.EXAMPLE_DATA, EXAMPLE_DATASET_NAME)

    new_stages: list[ConceptStage] = []
    for stage in draft.stages:
        example = by_type.get(stage.process_type.lower())
        if example is None:
            # Nothing in the dataset describes this process. It stays a gap.
            new_stages.append(stage)
            continue

        cycle = route_cycles.get(example["id"])
        new_stages.append(
            stage.model_copy(
                update={
                    "cycle_time": stage.cycle_time if stage.cycle_time.known or cycle is None else sourced_float(cycle),
                    "capacity": stage.capacity if stage.capacity.known else sourced_int(int(example["capacity"])),
                    "operators_required": (
                        stage.operators_required
                        if stage.operators_required.known
                        else sourced_int(int(example.get("operators_required", 0)))
                    ),
                    "width": stage.width if stage.width.known else sourced_float(float(example["width"])),
                    "length": stage.length if stage.length.known else sourced_float(float(example["length"])),
                    "purchase_cost": (
                        stage.purchase_cost
                        if stage.purchase_cost.known
                        else sourced_float(float(example.get("purchase_cost", 0.0)))
                    ),
                }
            )
        )

    # Buffers: the dataset wires one between each consecutive pair.
    new_buffers = list(draft.buffers)
    if not new_buffers and len(new_stages) > 1:
        example_capacities = [int(b["capacity"]) for b in data.get("buffers", [])]
        default_capacity = example_capacities[0] if example_capacities else 50
        from app.models.concept import ConceptBuffer

        new_buffers = [
            ConceptBuffer(
                id=f"buf-{upstream.id}-{downstream.id}",
                name=f"{upstream.name} → {downstream.name}",
                upstream_stage_id=upstream.id,
                downstream_stage_id=downstream.id,
                capacity=sourced_int(default_capacity),
            )
            for upstream, downstream in zip(new_stages, new_stages[1:])
        ]

    return draft.model_copy(
        update={
            "stages": new_stages,
            "buffers": new_buffers,
            "shifts_per_day": (
                draft.shifts_per_day
                if draft.shifts_per_day.known
                else sourced_int(int(data["shifts_per_day"]))
            ),
            "hours_per_shift": (
                draft.hours_per_shift
                if draft.hours_per_shift.known
                else sourced_float(float(data["hours_per_shift"]))
            ),
            "operators_available": (
                draft.operators_available
                if draft.operators_available.known
                else sourced_int(int(data["operators_available"]))
            ),
            "budget": draft.budget if draft.budget.known else sourced_float(float(data.get("budget", 0.0))),
        }
    )
