import { describe, expect, it } from "vitest";
import type { Machine, MachinePlacement } from "../api/types";
import { sampleFactory } from "../test/fixtures";
import {
  DEFAULT_MACHINE_HEIGHT_M,
  factoryBoundingBox,
  machineBoxDimensions,
  placementToThreePosition,
  rotationDegToThreeY, threePositionToFactoryPoint } from "./geometry3d";

const [machineA] = sampleFactory.machines;

function withHeight(machine: Machine, height: number | null): Machine {
  return { ...machine, physical_envelope: { height, safety_clearance_front: 0, safety_clearance_back: 0, safety_clearance_left: 0, safety_clearance_right: 0 } };
}

describe("machineBoxDimensions", () => {
  it("uses width/length directly from Machine — the same source of truth as 2D", () => {
    const dims = machineBoxDimensions(machineA);
    expect(dims.width).toBe(machineA.width);
    expect(dims.length).toBe(machineA.length);
  });

  it("uses the real measured height when physical_envelope.height is set", () => {
    const dims = machineBoxDimensions(withHeight(machineA, 2.4));
    expect(dims.height).toBe(2.4);
    expect(dims.heightIsMeasured).toBe(true);
  });

  it("falls back to the documented default height, marked as NOT measured, when absent", () => {
    const dims = machineBoxDimensions(machineA); // physical_envelope: null
    expect(dims.height).toBe(DEFAULT_MACHINE_HEIGHT_M);
    expect(dims.heightIsMeasured).toBe(false);
  });

  it("still uses the default when physical_envelope exists but height is null", () => {
    const dims = machineBoxDimensions(withHeight(machineA, null));
    expect(dims.height).toBe(DEFAULT_MACHINE_HEIGHT_M);
    expect(dims.heightIsMeasured).toBe(false);
  });
});

describe("placementToThreePosition — coordinate mapping", () => {
  it("maps factory X/Y directly to three X/Z, and centers height on Y", () => {
    const placement: MachinePlacement = { machine_id: "m-a", x: 7, y: 3, z: 0, rotation_deg: 0 };
    const pos = placementToThreePosition(placement, 2);
    expect(pos).toEqual({ x: 7, y: 1, z: 3 });
  });
});

describe("rotationDegToThreeY", () => {
  it("is a direct degrees-to-radians conversion of rotation_deg", () => {
    expect(rotationDegToThreeY(0)).toBeCloseTo(0);
    expect(rotationDegToThreeY(90)).toBeCloseTo(Math.PI / 2);
    expect(rotationDegToThreeY(180)).toBeCloseTo(Math.PI);
    expect(rotationDegToThreeY(-90)).toBeCloseTo(-Math.PI / 2);
  });
});

describe("factoryBoundingBox", () => {
  it("falls back to the factory floor size when there are no placements", () => {
    const bbox = factoryBoundingBox({ factory_width: 20, factory_length: 10, placements: [], reserved_zones: [], aisle_zones: [] });
    expect(bbox).toEqual({ minX: 0, maxX: 20, minY: 0, maxY: 10 });
  });

  it("expands to cover every placement while never shrinking below the floor size", () => {
    const bbox = factoryBoundingBox({
      factory_width: 20, factory_length: 10,
      placements: [{ machine_id: "m-a", x: 25, y: 5, z: 0, rotation_deg: 0 }],
      reserved_zones: [], aisle_zones: [],
    });
    expect(bbox.maxX).toBeGreaterThanOrEqual(25);
    expect(bbox.minX).toBeLessThanOrEqual(0);
  });
});

describe("threePositionToFactoryPoint", () => {
  it("is the exact inverse of placementToThreePosition", () => {
    // Pins the round trip rather than the formula, so a future change to the
    // axis convention has to keep both directions in step.
    const placement = { machine_id: "m-a", x: 7.5, y: 3.25, z: 0, rotation_deg: 90 };
    const three = placementToThreePosition(placement, 2);
    expect(threePositionToFactoryPoint(three.x, three.z)).toEqual({ x: placement.x, y: placement.y });
  });

  it("ignores height — a floor drag never changes it", () => {
    expect(threePositionToFactoryPoint(4, 9)).toEqual({ x: 4, y: 9 });
  });
});
