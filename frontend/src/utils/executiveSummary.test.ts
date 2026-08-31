import { describe, expect, it } from "vitest";
import type { SimulationResult, StrategyMetrics } from "../api/types";
import { statsFromSimulationResult, statsFromStrategyMetrics } from "./executiveSummary";

describe("executiveSummary adapters — Phase 9A", () => {
  it("normalizes StrategyMetrics (arena path) without inventing any value", () => {
    const m: StrategyMetrics = {
      goal_met: true,
      stop_reason: "GOAL_REACHED",
      completed_units: 1900,
      target_units: 1900,
      demand_gap_units: 0,
      throughput_per_hour: 79.2,
      work_in_progress: 0,
      average_flow_time_seconds: 142,
      bottleneck_machine_id: "m-assembly",
      operator_utilization: 0.78,
      operator_constrained: false,
      max_buffer_full_fraction: 0,
      total_upstream_blocked_seconds: 0,
    };
    expect(statsFromStrategyMetrics(m)).toEqual({
      completedUnits: 1900,
      targetUnits: 1900,
      gapUnits: 0,
      met: true,
      bottleneckMachineId: "m-assembly",
      // Capacity was not measured for this option, so it is null — the point
      // of this test. A missing capacity must not arrive as 0 or as the paced
      // figure: either would let "target achieved" be asserted on evidence
      // nobody produced.
      capacityUnits: null,
      capacityHeadroomPercent: null,
      sustainsTarget: null,
    });
  });

  it("normalizes a plain SimulationResult (SEND path) without inventing any value", () => {
    const s: SimulationResult = {
      simulation_time_seconds: 100,
      target_units: 500,
      completed_units: 300,
      throughput_per_hour: 3,
      demand_per_day: 500,
      demand_met: false,
      demand_gap_units: 200,
      machine_kpis: [],
      system: { average_flow_time_seconds: 0, max_flow_time_seconds: 0, work_in_progress: 5, bottleneck_machine_id: "m-x" },
      process_pool_kpis: [],
    };
    expect(statsFromSimulationResult(s)).toEqual({
      completedUnits: 300,
      targetUnits: 500,
      gapUnits: 200,
      met: false,
      bottleneckMachineId: "m-x",
    });
  });
});
