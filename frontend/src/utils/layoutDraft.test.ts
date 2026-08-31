import { describe, expect, it } from "vitest";
import type { FactoryLayout } from "../api/types";
import { sampleFactory } from "../test/fixtures";
import { createEmptyDraft, getPlacement, moveMachineDraft, placeMachineDraft, rotateMachineDraft, unplacedMachines } from "./layoutDraft";

function baseLayout(): FactoryLayout {
  return {
    factory_width: sampleFactory.width,
    factory_length: sampleFactory.length,
    placements: [{ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 }],
    reserved_zones: [],
    aisle_zones: [],
  };
}

describe("layoutDraft transforms", () => {
  it("createEmptyDraft sizes from the factory and starts with no placements", () => {
    const draft = createEmptyDraft(sampleFactory);
    expect(draft.factory_width).toBe(sampleFactory.width);
    expect(draft.factory_length).toBe(sampleFactory.length);
    expect(draft.placements).toEqual([]);
  });

  it("moveMachineDraft updates x/y, preserves rotation, and does not mutate the original layout", () => {
    const layout = baseLayout();
    const moved = moveMachineDraft(layout, "m-a", 20, 8);
    expect(getPlacement(moved, "m-a")).toEqual({ machine_id: "m-a", x: 20, y: 8, z: 0, rotation_deg: 0 });
    // Original untouched — a historical snapshot must never be mutated.
    expect(getPlacement(layout, "m-a")).toEqual({ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 });
  });

  it("rotateMachineDraft updates rotation_deg, preserves position, and does not mutate the original", () => {
    const layout = baseLayout();
    const rotated = rotateMachineDraft(layout, "m-a", 90);
    expect(getPlacement(rotated, "m-a")).toEqual({ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 90 });
    expect(getPlacement(layout, "m-a")?.rotation_deg).toBe(0);
  });

  it("placeMachineDraft adds a new placement without mutating the original layout", () => {
    const layout = baseLayout();
    const placed = placeMachineDraft(layout, "m-b", 15, 5, 0);
    expect(getPlacement(placed, "m-b")).toEqual({ machine_id: "m-b", x: 15, y: 5, z: 0, rotation_deg: 0 });
    expect(getPlacement(layout, "m-b")).toBeNull();
    expect(layout.placements).toHaveLength(1); // original unaffected
  });

  it("placeMachineDraft is a no-op when the machine already has a placement", () => {
    const layout = baseLayout();
    const result = placeMachineDraft(layout, "m-a", 99, 99, 0);
    expect(result).toBe(layout);
  });

  it("moveMachineDraft is a no-op when the machine has no placement", () => {
    const layout = baseLayout();
    const result = moveMachineDraft(layout, "m-nonexistent", 1, 1);
    expect(result).toBe(layout);
  });
});

describe("unplacedMachines", () => {
  it("lists every Factory machine without a placement", () => {
    const layout = baseLayout(); // only m-a placed
    const unplaced = unplacedMachines(sampleFactory, layout);
    expect(unplaced.map((m) => m.id)).toEqual(["m-b"]);
  });

  it("returns every machine when layout is null", () => {
    expect(unplacedMachines(sampleFactory, null).map((m) => m.id)).toEqual(["m-a", "m-b"]);
  });

  it("returns an empty list once every machine is placed", () => {
    const layout = placeMachineDraft(baseLayout(), "m-b", 1, 1, 0);
    expect(unplacedMachines(sampleFactory, layout)).toEqual([]);
  });
});
