import { describe, expect, it } from "vitest";
import type { Factory } from "../api/types";
import { buildInboundBufferByMachine, machineFlowState, queueIsOwnedByInboundBuffer, unitIsOwnedByMachineProcessing } from "./machineFlowState";
import type { UnitVisualState } from "./traceIndex";

const factory: Factory = {
  name: "F",
  width: 10,
  length: 10,
  shifts_per_day: 1,
  hours_per_shift: 8,
  operators_available: 0,
  budget: 0,
  machines: [],
  products: [],
  buffers: [
    { id: "b-1", name: "buf", capacity: 5, upstream_machine_id: "m-1", downstream_machine_id: "m-2", position_x: 0, position_y: 0 },
    { id: "b-unwired", name: "buf2", capacity: 5, upstream_machine_id: null, downstream_machine_id: null, position_x: 0, position_y: 0 },
  ],
};

describe("machineFlowState — Phase 9B", () => {
  const inbound = buildInboundBufferByMachine(factory);

  it("maps a wired buffer to its downstream machine only", () => {
    expect(inbound.get("m-2")).toBe("b-1");
    expect(inbound.has("m-1")).toBe(false);
  });

  it("is BLOCKED when the sample says so, regardless of anything else", () => {
    const sample = { timestamp: 0, machine_id: "m-2", queue_length: 0, processing_count: 0, blocked: true, utilization_so_far: 0 };
    expect(machineFlowState("m-2", sample, inbound, new Map())).toBe("blocked");
  });

  it("is PROCESSING when actively running a unit", () => {
    const sample = { timestamp: 0, machine_id: "m-2", queue_length: 0, processing_count: 1, blocked: false, utilization_so_far: 0.5 };
    expect(machineFlowState("m-2", sample, inbound, new Map())).toBe("processing");
  });

  it("is STARVED when idle with a wired inbound buffer at level 0", () => {
    const sample = { timestamp: 0, machine_id: "m-2", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0 };
    const buffers = new Map([["b-1", { timestamp: 0, buffer_id: "b-1", level: 0, capacity: 5, blocked_upstream: false }]]);
    expect(machineFlowState("m-2", sample, inbound, buffers)).toBe("starved");
  });

  it("is IDLE (not fabricated STARVED) when the inbound buffer actually has stock", () => {
    const sample = { timestamp: 0, machine_id: "m-2", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0 };
    const buffers = new Map([["b-1", { timestamp: 0, buffer_id: "b-1", level: 3, capacity: 5, blocked_upstream: false }]]);
    expect(machineFlowState("m-2", sample, inbound, buffers)).toBe("idle");
  });

  it("is IDLE (never guesses STARVED) for a machine with no wired inbound buffer", () => {
    const sample = { timestamp: 0, machine_id: "m-1", queue_length: 0, processing_count: 0, blocked: false, utilization_so_far: 0 };
    expect(machineFlowState("m-1", sample, inbound, new Map())).toBe("idle");
  });

  it("is IDLE when there is no sample at all (machine not yet in the trace)", () => {
    expect(machineFlowState("m-x", undefined, inbound, new Map())).toBe("idle");
  });
});

describe("queueIsOwnedByInboundBuffer — double-WIP ownership", () => {
  const inbound = buildInboundBufferByMachine(factory);

  it("a machine fed by a wired buffer has its waiting units owned by that buffer", () => {
    // m-2's queue_length and b-1's level are the same physical units (the
    // simulator puts a unit in the buffer and enqueues it at the downstream
    // machine at the same instant), so only the buffer gauge draws them.
    expect(queueIsOwnedByInboundBuffer("m-2", inbound)).toBe(true);
  });

  it("a machine with NO wired inbound buffer keeps its own queue markers", () => {
    // m-1 is the head of the line: nothing else represents its waiting
    // units, so suppressing its markers would hide real WIP.
    expect(queueIsOwnedByInboundBuffer("m-1", inbound)).toBe(false);
  });

  it("an unwired buffer never claims ownership of any machine's queue", () => {
    expect(queueIsOwnedByInboundBuffer("b-unwired", inbound)).toBe(false);
    expect(inbound.size).toBe(1);
  });

  it("an unknown machine id is never treated as buffer-owned", () => {
    expect(queueIsOwnedByInboundBuffer("m-does-not-exist", inbound)).toBe(false);
  });
});

describe("unitIsOwnedByMachineProcessing — activity ownership", () => {
  const unit = (status: UnitVisualState["status"]): UnitVisualState => ({
    unitId: 1,
    status,
    atMachineId: "m-1",
    atBufferId: null,
    progress: 0,
  });

  it("a unit INSIDE a machine is owned by that machine's processing token", () => {
    // processing_count already counts it, so drawing a travelling marker
    // too would show the same physical unit twice at the same point.
    expect(unitIsOwnedByMachineProcessing(unit("processing"))).toBe(true);
  });

  it("keeps every status that is NOT inside a machine as its own moving marker", () => {
    for (const status of ["released", "queued", "buffered"] as const) {
      expect(unitIsOwnedByMachineProcessing(unit(status))).toBe(false);
    }
  });

  it("keeps a FINISHED unit visible — it is no longer in processing_count", () => {
    // The simulator decrements machine_processing immediately BEFORE
    // emitting UNIT_FINISHED_PROCESSING, so a finished unit is counted
    // nowhere else; suppressing it here would make it vanish.
    expect(unitIsOwnedByMachineProcessing(unit("finished"))).toBe(false);
  });
});
