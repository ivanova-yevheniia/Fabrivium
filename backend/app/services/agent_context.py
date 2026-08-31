"""Compact factory-context builder for Fabrivium Phase 5A."""

from __future__ import annotations

from app.models.agent import (
    FactoryContext,
    FactoryContextMachine,
    FactoryContextProduct,
    FactoryContextSimulationSummary,
)
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.simulation import SimulationResult


def build_factory_context(
    factory: Factory,
    product_id: str | None = None,
    layout: FactoryLayout | None = None,
    simulation_result: SimulationResult | None = None,
) -> FactoryContext:
    """Build a compact ``FactoryContext`` from *factory*."""
    products = [
        FactoryContextProduct(id=p.id, name=p.name, demand_per_day=p.demand_per_day)
        for p in factory.products
    ]
    machines = [
        FactoryContextMachine(
            id=m.id, name=m.name, process_type=m.process_type,
            cycle_time=m.cycle_time, capacity=m.capacity, purchase_cost=m.purchase_cost,
        )
        for m in factory.machines
    ]

    simulation_summary = None
    if simulation_result is not None and product_id is not None:
        simulation_summary = FactoryContextSimulationSummary(
            product_id=product_id,
            completed_units=simulation_result.completed_units,
            target_units=simulation_result.target_units,
            demand_met=simulation_result.demand_met,
            bottleneck_machine_id=simulation_result.system.bottleneck_machine_id,
        )

    return FactoryContext(
        factory_name=factory.name,
        products=products,
        machines=machines,
        layout_available=layout is not None,
        simulation_summary=simulation_summary,
    )
