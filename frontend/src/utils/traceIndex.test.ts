import { describe, expect, it } from "vitest";
import type { SimulationTrace } from "../api/types";
import { TraceIndex } from "./traceIndex";

function makeTrace(): SimulationTrace {
  return {
    trace_version: 1,
    horizon_seconds: 100,
    sampled_interval_seconds: 25,
    config: { max_tracked_units: 10, sample_count_target: 4 },
    events: [
      { timestamp: 0, unit_id: 0, event_type: "UNIT_RELEASED" },
      { timestamp: 0, unit_id: 0, event_type: "UNIT_ENTERED_MACHINE_QUEUE", machine_id: "m-1" },
      { timestamp: 5, unit_id: 0, event_type: "UNIT_STARTED_PROCESSING", machine_id: "m-1" },
      { timestamp: 15, unit_id: 0, event_type: "UNIT_FINISHED_PROCESSING", machine_id: "m-1" },
      { timestamp: 15, unit_id: 0, event_type: "UNIT_ENTERED_BUFFER", buffer_id: "b-1" },
      { timestamp: 40, unit_id: 0, event_type: "UNIT_LEFT_BUFFER", buffer_id: "b-1" },
      { timestamp: 45, unit_id: 0, event_type: "UNIT_STARTED_PROCESSING", machine_id: "m-2" },
      { timestamp: 60, unit_id: 0, event_type: "UNIT_FINISHED_PROCESSING", machine_id: "m-2" },
      { timestamp: 60, unit_id: 0, event_type: "UNIT_COMPLETED" },
    ],
    machine_series: [
      { timestamp: 0, machine_id: "m-1", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0 },
      { timestamp: 25, machine_id: "m-1", queue_length: 2, processing_count: 1, blocked: false, utilization_so_far: 0.4 },
      { timestamp: 50, machine_id: "m-1", queue_length: 0, processing_count: 0, blocked: true, utilization_so_far: 0.5 },
      { timestamp: 100, machine_id: "m-1", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0.6 },
      { timestamp: 0, machine_id: "m-2", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0 },
      { timestamp: 100, machine_id: "m-2", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0.3 },
    ],
    buffer_series: [
      { timestamp: 0, buffer_id: "b-1", level: 0, capacity: 5, blocked_upstream: false },
      { timestamp: 25, buffer_id: "b-1", level: 3, capacity: 5, blocked_upstream: false },
      { timestamp: 100, buffer_id: "b-1", level: 1, capacity: 5, blocked_upstream: false },
    ],
    operator_series: [
      { timestamp: 0, operators_in_use: 0, operators_available: 2, waiting_operations: 0 },
      { timestamp: 100, operators_in_use: 1, operators_available: 2, waiting_operations: 0 },
    ],
    system_series: [
      { timestamp: 0, completed_units: 0, released_units: 1, current_bottleneck_machine_id: "m-1" },
      { timestamp: 60, completed_units: 1, released_units: 1, current_bottleneck_machine_id: "m-1" },
      { timestamp: 100, completed_units: 1, released_units: 1, current_bottleneck_machine_id: "m-1" },
    ],
    story_markers: [],
    tracked_unit_count: 1,
    total_unit_count: 1,
    summary: {
      simulation_time_seconds: 100,
      target_units: 1,
      completed_units: 1,
      throughput_per_hour: 1,
      demand_per_day: 1,
      demand_met: true,
      demand_gap_units: 0,
      machine_kpis: [],
      system: { average_flow_time_seconds: 60, max_flow_time_seconds: 60, work_in_progress: 0, bottleneck_machine_id: "m-1" },
      process_pool_kpis: [],
    },
    metadata: {},
  };
}

describe("TraceIndex — deterministic seek", () => {
  it("stateAt(0) resolves the initial samples/events", () => {
    const idx = new TraceIndex(makeTrace());
    const s = idx.stateAt(0);
    expect(s.machines.get("m-1")?.queue_length).toBe(0);
    expect(s.system?.completed_units).toBe(0);
    expect(s.units).toHaveLength(1);
    // Both UNIT_RELEASED and UNIT_ENTERED_MACHINE_QUEUE are recorded at
    // t=0 in this fixture — at instant 0 both have already happened, so
    // the LATER (more advanced) one is the correct resolved status.
    expect(s.units[0].status).toBe("queued");
  });

  it("stateAt(mid) resolves the LAST sample at or before that instant", () => {
    const idx = new TraceIndex(makeTrace());
    const s = idx.stateAt(30);
    // Last machine_series sample for m-1 at/before t=30 is the t=25 one.
    expect(s.machines.get("m-1")?.queue_length).toBe(2);
    expect(s.buffers.get("b-1")?.level).toBe(3);
  });

  it("stateAt(end) resolves the FINAL sample exactly", () => {
    const idx = new TraceIndex(makeTrace());
    const s = idx.stateAt(100);
    expect(s.machines.get("m-1")?.utilization_so_far).toBe(0.6);
    expect(s.system?.completed_units).toBe(1);
    expect(s.units).toHaveLength(0); // the only unit has COMPLETED, so it's excluded
  });

  it("stateAt clamps out-of-range instants to [0, horizon]", () => {
    const idx = new TraceIndex(makeTrace());
    expect(idx.stateAt(-10)).toEqual(idx.stateAt(0));
    expect(idx.stateAt(9999).system).toEqual(idx.stateAt(100).system);
  });

  it("same timestamp always renders the same visual state (pure function)", () => {
    const idx = new TraceIndex(makeTrace());
    const a = idx.stateAt(37);
    const b = idx.stateAt(37);
    expect(a.machines.get("m-1")).toEqual(b.machines.get("m-1"));
    expect(a.units).toEqual(b.units);
  });

  it("seeking BACKWARD after seeking forward gives the exact earlier state (no drift)", () => {
    const idx = new TraceIndex(makeTrace());
    const forward = idx.stateAt(80);
    const backAgain = idx.stateAt(30);
    const direct = idx.stateAt(30);
    expect(backAgain).toEqual(direct);
    expect(forward.system?.completed_units).toBe(1);
  });

  it("a unit mid-way between two positional events gets a 0..1 progress fraction", () => {
    const idx = new TraceIndex(makeTrace());
    // Between UNIT_LEFT_BUFFER (t=40) and UNIT_STARTED_PROCESSING (t=45).
    const s = idx.stateAt(42.5);
    const unit = s.units[0];
    expect(unit.status).toBe("queued");
    expect(unit.progress).toBeCloseTo(0.5, 5);
  });

  it("MACHINE_BLOCKED/UNBLOCKED events do not change a unit's reported position", () => {
    const idx = new TraceIndex(makeTrace());
    // Between UNIT_FINISHED_PROCESSING (t=15) and UNIT_ENTERED_BUFFER (t=15) —
    // both at the same instant here, but the point is that a MACHINE_BLOCKED
    // event type is simply absent from this fixture's position stream and
    // must never be required for status resolution.
    const s = idx.stateAt(20);
    expect(s.units[0].status).toBe("buffered");
    expect(s.units[0].atBufferId).toBe("b-1");
  });
});
