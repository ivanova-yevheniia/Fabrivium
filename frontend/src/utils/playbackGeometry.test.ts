import { describe, expect, it } from "vitest";
import type { Buffer, Factory } from "../api/types";
import { buildPlaybackPositions, buildRouteSegments, segmentDirection, unitPlaybackPosition } from "./playbackGeometry";

function machine(id: string, x: number, y: number) {
  return {
    id,
    name: id,
    process_type: "assembly",
    cycle_time: 10,
    setup_time: 0,
    capacity: 1,
    operators_required: 0,
    purchase_cost: 0,
    position_x: x,
    position_y: y,
    width: 1,
    length: 1,
    parallel_of_machine_id: null,
    asset: null,
    lifecycle_status: "EXISTING" as const,
    physical_envelope: null,
  };
}

function buffer(id: string, x: number, y: number, upstream: string | null, downstream: string | null): Buffer {
  return { id, name: id, capacity: 5, upstream_machine_id: upstream, downstream_machine_id: downstream, position_x: x, position_y: y };
}

const factory: Factory = {
  name: "F",
  width: 20,
  length: 10,
  shifts_per_day: 1,
  hours_per_shift: 8,
  operators_available: 0,
  budget: 0,
  machines: [machine("m-1", 0, 0), machine("m-2", 10, 0), machine("m-3", 20, 0)],
  products: [
    {
      id: "p-1",
      name: "Widget",
      demand_per_day: 10,
      route: [
        { name: "Step 1", machine_id: "m-1", cycle_time: 10 },
        { name: "Step 2", machine_id: "m-2", cycle_time: 10 },
        { name: "Step 3", machine_id: "m-3", cycle_time: 10 },
      ],
    },
  ],
  buffers: [buffer("b-1", 5, 0, "m-1", "m-2")], // wired between m-1 -> m-2 only; m-2 -> m-3 has no buffer
};

describe("buildRouteSegments — Phase 8C section 10", () => {
  it("inserts machine -> buffer -> machine when a wired buffer names that exact pair", () => {
    const positions = buildPlaybackPositions(factory, null);
    const segments = buildRouteSegments(factory, "p-1", positions);

    const m1ToB1 = segments.find((s) => s.fromId === "m-1" && s.toId === "b-1");
    const b1ToM2 = segments.find((s) => s.fromId === "b-1" && s.toId === "m-2");
    expect(m1ToB1).toBeDefined();
    expect(b1ToM2).toBeDefined();
    expect(m1ToB1!.to).toEqual({ x: 5, y: 0 });
  });

  it("falls back to machine -> machine when no wired buffer names the pair", () => {
    const positions = buildPlaybackPositions(factory, null);
    const segments = buildRouteSegments(factory, "p-1", positions);
    const m2ToM3 = segments.find((s) => s.fromId === "m-2" && s.toId === "m-3");
    expect(m2ToM3).toBeDefined();
    expect(m2ToM3!.from).toEqual({ x: 10, y: 0 });
    expect(m2ToM3!.to).toEqual({ x: 20, y: 0 });
  });

  it("never infers a segment from spatial proximity alone — an unwired buffer sitting between two stages is ignored", () => {
    const withUnwiredBuffer: Factory = {
      ...factory,
      buffers: [...factory.buffers, buffer("b-2", 15, 0, null, null)], // sits geometrically between m-2/m-3 but is NOT wired
    };
    const positions = buildPlaybackPositions(withUnwiredBuffer, null);
    const segments = buildRouteSegments(withUnwiredBuffer, "p-1", positions);
    expect(segments.some((s) => s.fromId === "b-2" || s.toId === "b-2")).toBe(false);
  });

  it("returns an empty list for an unknown product_id", () => {
    const positions = buildPlaybackPositions(factory, null);
    expect(buildRouteSegments(factory, "does-not-exist", positions)).toEqual([]);
  });
});

describe("buildPlaybackPositions", () => {
  it("falls back to Machine.position_x/y when no layout is loaded", () => {
    const positions = buildPlaybackPositions(factory, null);
    expect(positions.machines.get("m-2")).toEqual({ x: 10, y: 0 });
  });

  it("prefers the FactoryLayout placement over the machine's own position fields", () => {
    const positions = buildPlaybackPositions(factory, {
      factory_width: 20,
      factory_length: 10,
      placements: [{ machine_id: "m-2", x: 99, y: 5, z: 0, rotation_deg: 0 }],
      reserved_zones: [],
      aisle_zones: [],
    });
    expect(positions.machines.get("m-2")).toEqual({ x: 99, y: 5 });
  });
});

describe("unitPlaybackPosition", () => {
  const positions = buildPlaybackPositions(factory, null);

  it("resolves a QUEUED unit as an interpolation between its departure buffer and target machine", () => {
    const pos = unitPlaybackPosition({ status: "queued", atMachineId: "m-2", atBufferId: "b-1", progress: 0.5 }, positions);
    expect(pos).toEqual({ x: 7.5, y: 0 }); // halfway between b-1 (5,0) and m-2 (10,0)
  });

  it("resolves a PROCESSING unit at its machine, ignoring progress", () => {
    const pos = unitPlaybackPosition({ status: "processing", atMachineId: "m-1", atBufferId: null, progress: 0.9 }, positions);
    expect(pos).toEqual({ x: 0, y: 0 });
  });

  it("resolves a BUFFERED unit at its buffer", () => {
    const pos = unitPlaybackPosition({ status: "buffered", atMachineId: null, atBufferId: "b-1", progress: 0 }, positions);
    expect(pos).toEqual({ x: 5, y: 0 });
  });

  it("returns null for a COMPLETED unit (no position input for it)", () => {
    const pos = unitPlaybackPosition({ status: "completed", atMachineId: null, atBufferId: null, progress: 0 }, positions);
    expect(pos).toBeNull();
  });
});

describe("segmentDirection — Phase 9B route arrows", () => {
  it("computes the midpoint and pointing angle of a real segment, nothing fabricated", () => {
    const dir = segmentDirection({ from: { x: 0, y: 0 }, to: { x: 10, y: 0 }, fromId: "a", toId: "b" });
    expect(dir.midX).toBe(5);
    expect(dir.midY).toBe(0);
    expect(dir.angleRad).toBeCloseTo(0, 10); // pointing along +X
    expect(dir.length).toBe(10);
  });

  it("points the other way for a reversed segment", () => {
    const dir = segmentDirection({ from: { x: 10, y: 0 }, to: { x: 0, y: 0 }, fromId: "b", toId: "a" });
    expect(dir.angleRad).toBeCloseTo(Math.PI, 10);
  });
});
