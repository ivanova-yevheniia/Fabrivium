/** Phase 9A section 8 — bottleneck/limiting-stage terminology decision. */

import type { SimulationResult } from "../api/types";

/** True only when the named stage is an ALARM-worthy bottleneck — i.e. */
export function isAlarmBottleneck(sim: Pick<SimulationResult, "demand_met">): boolean {
  return !sim.demand_met;
}

/** The label to use for `SystemKPI.bottleneck_machine_id` given the same
 * simulation's `demand_met` — "Bottleneck" only when it is genuinely one. */
export function limitingStageLabel(sim: Pick<SimulationResult, "demand_met">): string {
  return sim.demand_met ? "Limiting stage" : "Bottleneck";
}
