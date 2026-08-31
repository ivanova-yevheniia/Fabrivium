"""Line capacity — what a plan can actually make, not what it was asked to make."""

from __future__ import annotations

from dataclasses import dataclass

import app.services.simulation as simulation_module
from app.models.factory import Factory

#: A demand no concept-stage line can satisfy, so the run measures the line
#: rather than the schedule. Deliberately far above any plausible target: the
#: measurement is only valid while the line is the binding constraint, and a
#: value close to the target would silently measure the pacing again.
SATURATION_DEMAND_PER_DAY = 100_000.0


class CapacityNotMeasurable(ValueError):
    """The saturated run did not saturate — the figure would not be a capacity."""


@dataclass(frozen=True)
class CapacityMeasurement:
    """What a line can produce per day, and how that compares to the target."""

    # Units per day at continuous demand. The line's own ceiling.
    capacity_units_per_day: int
    # The target this capacity was measured against.
    target_units_per_day: float
    # ``capacity / target - 1``. Negative means the plan cannot hold target.
    headroom_fraction: float
    # Simulation runs consumed by this measurement. Always 1.
    simulations_run: int = 1

    @property
    def meets_target_at_capacity(self) -> bool:
        """True when the line can sustain the target under continuous demand."""
        return self.capacity_units_per_day >= self.target_units_per_day

    @property
    def headroom_percent(self) -> int:
        """Whole percent, and no finer."""
        return round(self.headroom_fraction * 100)


def _with_demand(factory: Factory, product_id: str, demand: float) -> Factory:
    products = [
        p.model_copy(update={"demand_per_day": demand}) if p.id == product_id else p
        for p in factory.products
    ]
    return factory.model_copy(update={"products": products})


def measure_capacity(
    factory: Factory,
    product_id: str,
    *,
    target_units_per_day: float | None = None,
) -> CapacityMeasurement:
    """Measure what *factory* can produce per day, against its target."""
    product = next((p for p in factory.products if p.id == product_id), None)
    if product is None:
        raise ValueError(f"No product '{product_id}' in this factory.")

    target = target_units_per_day if target_units_per_day is not None else product.demand_per_day
    if target <= 0:
        raise ValueError("A capacity headroom against a non-positive target has no meaning.")

    # Called through the MODULE, not through a name bound at import time, so
    # the simulation-count harness sees this run. A capacity measurement is a
    # real simulation and must be counted as one; a version that hid from the
    # counter would make "this plan costs one extra run" unverifiable.
    saturated = simulation_module.run_simulation(
        _with_demand(factory, product_id, SATURATION_DEMAND_PER_DAY), product_id
    )

    # If the line satisfied the saturation demand, it was never the binding
    # constraint and the number is still a cap, not a capacity. Reporting it
    # as headroom would overstate the line by whatever margin was left.
    if saturated.demand_met:
        raise CapacityNotMeasurable(
            f"The line completed all {SATURATION_DEMAND_PER_DAY:,.0f} released units, "
            f"so this run measured the schedule rather than the line."
        )

    capacity = int(saturated.completed_units)
    return CapacityMeasurement(
        capacity_units_per_day=capacity,
        target_units_per_day=target,
        headroom_fraction=capacity / target - 1.0,
    )


__all__ = [
    "SATURATION_DEMAND_PER_DAY",
    "CapacityMeasurement",
    "CapacityNotMeasurable",
    "measure_capacity",
]
