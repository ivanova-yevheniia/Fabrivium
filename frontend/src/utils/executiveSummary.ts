/**
 * Phase 9A — thin adapters that normalize the TWO shapes Executive View can
 * receive a "how is production doing" summary from into ONE shape, purely
 * by picking existing fields — never computing a new number. This is what
 * lets Executive View present a single consistent story regardless of
 * whether the user took the EXPLORE OPTIONS path (StrategyMetrics, on
 * `arena.baseline_metrics` / `VerifiedStrategyOption.metrics`) or the SEND
 * path (a plain `SimulationResult` on a `PlanningStateSnapshot`).
 */

import type { SimulationResult, StrategyMetrics } from "../api/types";

export interface StageStats {
  completedUnits: number;
  targetUnits: number;
  gapUnits: number;
  met: boolean;
  bottleneckMachineId: string;
  /** What the line can actually sustain per day, and how that compares to the target. */
  capacityUnits?: number | null;
  capacityHeadroomPercent?: number | null;
  /** `false` means the plan reaches the target only at full speed: the
   * simulator released exactly the target and the line just kept up. It has
   * not achieved the target, whatever the paced run says. */
  sustainsTarget?: boolean | null;
}

export function statsFromStrategyMetrics(m: StrategyMetrics): StageStats {
  return {
    completedUnits: m.completed_units,
    targetUnits: m.target_units,
    gapUnits: m.demand_gap_units,
    met: m.goal_met,
    bottleneckMachineId: m.bottleneck_machine_id,
    capacityUnits: m.capacity_units_per_day ?? null,
    capacityHeadroomPercent: m.capacity_headroom_percent ?? null,
    sustainsTarget: m.sustains_target_at_capacity ?? null,
  };
}

export function statsFromSimulationResult(s: SimulationResult): StageStats {
  return {
    completedUnits: s.completed_units,
    targetUnits: s.target_units,
    gapUnits: s.demand_gap_units,
    met: s.demand_met,
    bottleneckMachineId: s.system.bottleneck_machine_id,
  };
}
