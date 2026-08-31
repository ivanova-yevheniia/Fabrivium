import { describe, expect, it } from "vitest";
import type { Machine, MachinePlacement } from "../api/types";
import { axisAlignedRectangle, machineFootprint, machineSafetyEnvelope, orientedRectangle, previewOverlap, zoneRectangle } from "./geometry";

function machine(overrides: Partial<Machine> = {}): Machine {
  return {
    id: "m-x",
    name: "Machine X",
    process_type: "assembly",
    cycle_time: 10,
    setup_time: 0,
    capacity: 1,
    operators_required: 0,
    purchase_cost: 0,
    position_x: 0,
    position_y: 0,
    width: 4,
    length: 2,
    asset: null,
    lifecycle_status: "EXISTING",
    physical_envelope: null,
    ...overrides,
  };
}

function placement(overrides: Partial<MachinePlacement> = {}): MachinePlacement {
  return { machine_id: "m-x", x: 10, y: 5, z: 0, rotation_deg: 0, ...overrides };
}

describe("machineFootprint — coordinate mapping (Phase 6B section 1)", () => {
  it("uses placement x/y as the footprint CENTER, not a corner", () => {
    const corners = machineFootprint(machine(), placement({ x: 10, y: 5, rotation_deg: 0 }));
    const xs = corners.map((c) => c.x);
    const ys = corners.map((c) => c.y);
    // width=4 -> half=2, length=2 -> half=1, centered on (10,5)
    expect(Math.min(...xs)).toBeCloseTo(8);
    expect(Math.max(...xs)).toBeCloseTo(12);
    expect(Math.min(...ys)).toBeCloseTo(4);
    expect(Math.max(...ys)).toBeCloseTo(6);
  });

  it("machine dimensions (width/length) directly size the footprint", () => {
    const wide = machineFootprint(machine({ width: 10, length: 2 }), placement({ x: 0, y: 0, rotation_deg: 0 }));
    const xs = wide.map((c) => c.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(10);
  });

  it("supports arbitrary (non-90°) rotation angles", () => {
    const corners = machineFootprint(machine({ width: 4, length: 2 }), placement({ x: 0, y: 0, rotation_deg: 30 }));
    // At 30°, the bounding box is neither the unrotated footprint's
    // width/length nor a 90°-swapped one — verify it's genuinely rotated
    // by checking no corner sits exactly on an axis-aligned extreme.
    const xs = corners.map((c) => c.x);
    expect(Math.max(...xs)).not.toBeCloseTo(2, 5);
    expect(Math.max(...xs)).not.toBeCloseTo(1, 5);
  });

  it("a 90° rotation swaps the effective width/length extents", () => {
    const at0 = machineFootprint(machine({ width: 4, length: 2 }), placement({ x: 0, y: 0, rotation_deg: 0 }));
    const at90 = machineFootprint(machine({ width: 4, length: 2 }), placement({ x: 0, y: 0, rotation_deg: 90 }));
    const spanX = (pts: { x: number }[]) => Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x));
    const spanY = (pts: { y: number }[]) => Math.max(...pts.map((p) => p.y)) - Math.min(...pts.map((p) => p.y));
    expect(spanX(at0)).toBeCloseTo(4);
    expect(spanY(at0)).toBeCloseTo(2);
    expect(spanX(at90)).toBeCloseTo(2);
    expect(spanY(at90)).toBeCloseTo(4);
  });
});

describe("machineSafetyEnvelope — asymmetric clearances (Phase 6B section 2)", () => {
  it("expands each side independently, never symmetrized", () => {
    const m = machine({
      width: 2, length: 2,
      physical_envelope: { height: null, safety_clearance_front: 3, safety_clearance_back: 0.5, safety_clearance_left: 1, safety_clearance_right: 0 },
    });
    const footprint = machineFootprint(m, placement({ x: 0, y: 0, rotation_deg: 0 }));
    const envelope = machineSafetyEnvelope(m, placement({ x: 0, y: 0, rotation_deg: 0 }));
    const fXs = footprint.map((p) => p.x);
    const eXs = envelope.map((p) => p.x);
    const fYs = footprint.map((p) => p.y);
    const eYs = envelope.map((p) => p.y);

    // front = local +Y, back = local -Y, left = local -X, right = local +X
    expect(Math.max(...eYs)).toBeCloseTo(Math.max(...fYs) + 3); // front
    expect(Math.min(...eYs)).toBeCloseTo(Math.min(...fYs) - 0.5); // back
    expect(Math.min(...eXs)).toBeCloseTo(Math.min(...fXs) - 1); // left
    expect(Math.max(...eXs)).toBeCloseTo(Math.max(...fXs) + 0); // right (no clearance)
  });

  it("rotates the asymmetric envelope rigidly with the machine (not re-derived per axis)", () => {
    const m = machine({
      width: 2, length: 2,
      physical_envelope: { height: null, safety_clearance_front: 3, safety_clearance_back: 0, safety_clearance_left: 0, safety_clearance_right: 0 },
    });
    // At 0°: front clearance extends +Y. At 90°: "front" (local +Y) now
    // points along global +X — the clearance must move with it.
    const at0 = machineSafetyEnvelope(m, placement({ x: 0, y: 0, rotation_deg: 0 }));
    const at90 = machineSafetyEnvelope(m, placement({ x: 0, y: 0, rotation_deg: 90 }));
    expect(Math.max(...at0.map((p) => p.y))).toBeCloseTo(4); // 1 (half-length) + 3 front clearance
    expect(Math.max(...at0.map((p) => p.x))).toBeCloseTo(1);
    // Rotating 90° CCW maps local +Y (front) to global -X, not +X.
    expect(Math.min(...at90.map((p) => p.x))).toBeCloseTo(-4);
    expect(Math.max(...at90.map((p) => p.y))).toBeCloseTo(1);
  });

  it("defaults to zero clearance on every side when physical_envelope is null", () => {
    const m = machine({ width: 2, length: 2, physical_envelope: null });
    const footprint = machineFootprint(m, placement({ x: 0, y: 0 }));
    const envelope = machineSafetyEnvelope(m, placement({ x: 0, y: 0 }));
    expect(envelope).toEqual(footprint);
  });
});

describe("zoneRectangle — lower-left corner convention", () => {
  it("treats zone x/y as the LOWER-LEFT corner, not the center", () => {
    const corners = zoneRectangle({ id: "z-1", name: "Aisle", x: 5, y: 2, width: 10, length: 4, zone_type: "AISLE" });
    const xs = corners.map((c) => c.x);
    const ys = corners.map((c) => c.y);
    expect(Math.min(...xs)).toBeCloseTo(5);
    expect(Math.max(...xs)).toBeCloseTo(15);
    expect(Math.min(...ys)).toBeCloseTo(2);
    expect(Math.max(...ys)).toBeCloseTo(6);
  });
});

describe("orientedRectangle / axisAlignedRectangle building blocks", () => {
  it("axisAlignedRectangle is a plain corner rectangle from (x,y)", () => {
    const r = axisAlignedRectangle(0, 0, 3, 4);
    expect(r).toEqual([{ x: 0, y: 0 }, { x: 3, y: 0 }, { x: 3, y: 4 }, { x: 0, y: 4 }]);
  });

  it("orientedRectangle at rotation 0 matches a plain centered rectangle", () => {
    const r = orientedRectangle(0, 0, 0, -1, 1, -2, 2);
    const xs = r.map((p) => p.x);
    const ys = r.map((p) => p.y);
    expect(Math.min(...xs)).toBeCloseTo(-1);
    expect(Math.max(...xs)).toBeCloseTo(1);
    expect(Math.min(...ys)).toBeCloseTo(-2);
    expect(Math.max(...ys)).toBeCloseTo(2);
  });
});

describe("previewOverlap — cheap, non-authoritative drag hint", () => {
  it("detects an obvious bounding-box overlap", () => {
    const a = axisAlignedRectangle(0, 0, 2, 2);
    const b = axisAlignedRectangle(1, 1, 2, 2);
    expect(previewOverlap(a, b)).toBe(true);
  });

  it("does not flag clearly separated rectangles", () => {
    const a = axisAlignedRectangle(0, 0, 2, 2);
    const b = axisAlignedRectangle(10, 10, 2, 2);
    expect(previewOverlap(a, b)).toBe(false);
  });
});
