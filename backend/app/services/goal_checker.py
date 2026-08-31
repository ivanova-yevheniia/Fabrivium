"""
Deterministic goal / acceptance rules for Fabrivium Phase 5C's iterative planning
orchestrator.
"""

from __future__ import annotations

from app.models.optimization import OptimizationObjective
from app.models.simulation import SimulationResult

#: Below this, a demand-gap change is not considered "material" — guards
#: against floating-point noise being read as a genuine improvement.
DEMAND_GAP_TOLERANCE_UNITS = 0.5

# Below this, a flow-time change is not considered a genuine improvement.
FLOW_TIME_TOLERANCE_SECONDS = 1.0


def is_goal_reached(objective: OptimizationObjective, simulation: SimulationResult) -> bool:
    """Deterministic goal check (Phase 5C section 7)."""
    if objective == OptimizationObjective.MEET_DEMAND:
        return simulation.demand_met
    return False


def is_acceptable_improvement(
    objective: OptimizationObjective,
    before: SimulationResult,
    after: SimulationResult,
    *,
    demand_gap_tolerance: float = DEMAND_GAP_TOLERANCE_UNITS,
    flow_time_tolerance: float = FLOW_TIME_TOLERANCE_SECONDS,
) -> bool:
    """
    Deterministic acceptance rule (Phase 5C section 6): should *after* replace *before*
    as the orchestrator's current verified state?
    """
    if objective == OptimizationObjective.MEET_DEMAND:
        if not before.demand_met and after.demand_met:
            return True
        if before.demand_met and not after.demand_met:
            return False
        return (before.demand_gap_units - after.demand_gap_units) > demand_gap_tolerance

    if objective == OptimizationObjective.MAXIMIZE_THROUGHPUT:
        return after.completed_units > before.completed_units

    if objective in (OptimizationObjective.MINIMIZE_WIP, OptimizationObjective.MINIMIZE_FLOW_TIME):
        if before.demand_met and not after.demand_met:
            return False
        if objective == OptimizationObjective.MINIMIZE_WIP:
            return after.system.work_in_progress < before.system.work_in_progress
        return (before.system.average_flow_time_seconds - after.system.average_flow_time_seconds) > flow_time_tolerance

    return False
