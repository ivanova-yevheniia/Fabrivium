"""
Fabrivium domain to exchange model 

The ONE place that reads Fabrivium's domain objects for handoff purposes.
The Siemens adapter never sees a `Factory`; it sees a
:class:`FactoryMindExchange`, so a second tool adapter needs no new
translation and no Siemens assumption can leak back into the domain.

* Route order comes from ``Product.route``, and the flow links are built
  from that order.
* ``ProcessStep.cycle_time`` is the cycle time — the field the simulator
  actually reads. ``Machine.cycle_time`` is a fallback the route never lets
  it reach, and using it here would silently ship a different number.
* Layout coordinates are copied when a layout exists, and left absent when
  it does not. 
* An unknown purchase cost stays unknown, and now does so exactly.
  `Machine.purchase_cost` is nullable, so `None` exports as UNKNOWN and a
  genuine 0.0 exports as the price it is.
"""

from __future__ import annotations

from app.integrations.plant_simulation.exchange_schema import (
    ExchangeBuffer,
    ExchangeFlowLink,
    ExchangeResources,
    ExchangeSimulationSummary,
    ExchangeStation,
    ExchangeValue,
    ExchangeValueSource,
    FactoryMindExchange,
)
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.simulation import SimulationResult


def exchange_from_factory(
    factory: Factory,
    product_id: str,
    *,
    layout: FactoryLayout | None = None,
    simulation: SimulationResult | None = None,
    open_assumptions: list[str] | None = None,
    equipment_selections: dict[str, dict] | None = None,
) -> FactoryMindExchange:
    """Build the vendor-neutral package for one product of one factory.
    `equipment_selections` maps station id to the selected equipment's
    metadata (manufacturer, model, source_url). 
    """
    product = next((p for p in factory.products if p.id == product_id), None)
    if product is None:
        raise ValueError(f"Unknown product_id '{product_id}' for factory '{factory.name}'.")

    machines = {m.id: m for m in factory.machines}
    placements = {p.machine_id: p for p in (layout.placements if layout else [])}
    selections = equipment_selections or {}

    stations: list[ExchangeStation] = []
    seen: set[str] = set()
    for step in product.route:
        # A route may legitimately revisit a machine
        if step.machine_id in seen:
            continue
        seen.add(step.machine_id)
        machine = machines.get(step.machine_id)
        if machine is None:
            raise ValueError(
                f"Route step '{step.name}' references machine '{step.machine_id}', "
                f"which is not in factory '{factory.name}'."
            )
        placement = placements.get(machine.id)
        selection = selections.get(machine.id) or {}
        stations.append(
            ExchangeStation(
                id=machine.id,
                name=machine.name,
                selected_manufacturer=selection.get("manufacturer"),
                selected_model=selection.get("model"),
                selected_source_url=selection.get("source_url"),
                process_type=machine.process_type,
                cycle_time_seconds=step.cycle_time,
                capacity=machine.capacity,
                operators_required=machine.operators_required,
                x=placement.x if placement else None,
                y=placement.y if placement else None,
                width=machine.width,
                length=machine.length,
                rotation_deg=placement.rotation_deg if placement else 0.0,
                purchase_cost=(
                    ExchangeValue.of(
                        machine.purchase_cost, ExchangeValueSource.CUSTOMER, "Fabrivium factory model"
                    )
                    if machine.purchase_cost is not None
                    else ExchangeValue.unknown()
                ),
            )
        )

    ordered_ids = [s.id for s in stations]
    flow = [
        ExchangeFlowLink(from_id=a, to_id=b) for a, b in zip(ordered_ids, ordered_ids[1:])
    ]

    buffers = [
        ExchangeBuffer(
            id=buffer.id,
            name=buffer.name,
            upstream_station_id=buffer.upstream_machine_id or "",
            downstream_station_id=buffer.downstream_machine_id or "",
            capacity=buffer.capacity,
        )
        # Only wired buffers are exported: an unwired buffer has no effect in
        # Fabrivium's simulation either, and shipping it would suggest a
        # constraint that does not exist.
        for buffer in factory.buffers
        if buffer.is_wired
    ]

    summary = None
    if simulation is not None:
        summary = ExchangeSimulationSummary(
            target_units_per_day=simulation.target_units,
            completed_units_per_day=simulation.completed_units,
            demand_gap_units=simulation.demand_gap_units,
            bottleneck_station_id=simulation.system.bottleneck_machine_id,
        )

    assumptions = list(open_assumptions or [])
    if any(s.purchase_cost.value is None for s in stations):
        assumptions.append("Equipment purchase cost is unknown for at least one station.")
    # Only claim "no equipment selected" for the stations where that is
    # still true. 
    unselected = [s.name for s in stations if not s.selected_model]
    if len(unselected) == len(stations):
        assumptions.append(
            "Stations are generic process requirements — no specific equipment has been selected."
        )
    elif unselected:
        assumptions.append(
            "No specific equipment has been selected for: " + ", ".join(unselected) + "."
        )
    assumptions.append(
        "Layout is concept level. Fabrivium's simulation does not read placement, so coordinates "
        "describe arrangement only."
    )

    return FactoryMindExchange(
        project_name=factory.name,
        product_name=product.name,
        stations=stations,
        flow=flow,
        buffers=buffers,
        resources=ExchangeResources(
            operators_available=factory.operators_available,
            shifts_per_day=factory.shifts_per_day,
            hours_per_shift=factory.hours_per_shift,
        ),
        floor_width=factory.width,
        floor_length=factory.length,
        simulation_summary=summary,
        open_assumptions=assumptions,
    )
