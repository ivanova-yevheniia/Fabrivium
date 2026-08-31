import { describe, expect, it } from "vitest";
import type { EquipmentAsset, Machine } from "../api/types";
import { GENERIC_ASSET_MANIFEST, categoryForProcessType, resolveMachineAsset, visualTransformFor } from "./assetResolution";

function machine(overrides: Partial<Machine> = {}): Machine {
  return {
    id: "m-1",
    name: "M1",
    process_type: "assembly",
    cycle_time: 10,
    setup_time: 0,
    capacity: 1,
    operators_required: 0,
    purchase_cost: 0,
    position_x: 0,
    position_y: 0,
    width: 2,
    length: 2,
    parallel_of_machine_id: null,
    asset: null,
    lifecycle_status: "EXISTING",
    physical_envelope: null,
    ...overrides,
  };
}

function exactAsset(overrides: Partial<EquipmentAsset> = {}): EquipmentAsset {
  return {
    asset_type: "EXACT_CAD",
    status: "AVAILABLE",
    asset_uri: "/models/real.glb",
    source_uri: null,
    manufacturer: null,
    model_number: null,
    license_name: "Proprietary",
    attribution: null,
    file_format: "GLB",
    notes: null,
    ...overrides,
  };
}

describe("categoryForProcessType — Phase 9B/asset track section 4", () => {
  it("maps the four flagship process types to their categories", () => {
    expect(categoryForProcessType("assembly")).toBe("ASSEMBLY_STATION");
    expect(categoryForProcessType("screwdriving")).toBe("SCREWDRIVING_STATION");
    expect(categoryForProcessType("inspection")).toBe("INSPECTION_STATION");
    expect(categoryForProcessType("packaging")).toBe("PACKAGING_STATION");
  });

  it("resolves aliases deterministically (never guesses beyond explicit word matches)", () => {
    expect(categoryForProcessType("automatic screw station")).toBe("SCREWDRIVING_STATION");
    expect(categoryForProcessType("quality inspection cell")).toBe("INSPECTION_STATION");
  });

  it("falls back to a generic category for an unrecognized process type", () => {
    expect(categoryForProcessType("laser welding")).toBe("GENERIC_PROCESSING_MACHINE");
  });
});

describe("resolveMachineAsset — Phase 9B/asset track section 3 (resolution order)", () => {
  it("EXACT: a machine with a loadable EXACT_CAD asset resolves to EXACT, preferred over generic/procedural", () => {
    const m = machine({ asset: exactAsset() });
    const res = resolveMachineAsset(m);
    expect(res.status).toBe("EXACT");
    expect(res.assetUri).toBe("/models/real.glb");
    expect(res.confidence).toBe(1);
    expect(res.provenance.source).toBe("MACHINE_ASSET");
  });

  it("real defect regression: a LIBRARY asset (e.g. electronics_line's m-screwdriving/conveyor.glb) resolves to GENERIC, never EXACT — must always disclose it is not the real machine", () => {
    const m = machine({
      process_type: "screwdriving",
      asset: exactAsset({ asset_type: "LIBRARY", asset_uri: "/models/conveyor.glb", license_name: "CC BY", attribution: "test" }),
    });
    const res = resolveMachineAsset(m);
    expect(res.status).toBe("GENERIC");
    expect(res.assetUri).toBe("/models/conveyor.glb");
    expect(res.provenance.license).toBe("CC BY");
    expect(res.provenance.attribution).toBe("test");
  });

  it("GENERIC (manifest) is preferred over PROCEDURAL when a category entry exists", () => {
    const original = GENERIC_ASSET_MANIFEST.ASSEMBLY_STATION;
    GENERIC_ASSET_MANIFEST.ASSEMBLY_STATION = {
      id: "generic-assembly",
      displayName: "Generic assembly station",
      uri: "/assets/machines/assembly/generic.glb",
      format: "GLB",
      license: { name: "CC0", attribution: null, sourceUri: null, redistributionAllowed: true },
    };
    try {
      const res = resolveMachineAsset(machine({ process_type: "assembly", asset: null }));
      expect(res.status).toBe("GENERIC");
      expect(res.assetUri).toBe("/assets/machines/assembly/generic.glb");
      expect(res.provenance.source).toBe("GENERIC_MANIFEST");
    } finally {
      GENERIC_ASSET_MANIFEST.ASSEMBLY_STATION = original;
    }
  });

  it("resolves the real flagship generic manifest for the four station categories (Kenney Factory Kit, CC0)", () => {
    const res = resolveMachineAsset(machine({ process_type: "assembly", asset: null }));
    expect(res.status).toBe("GENERIC");
    expect(res.assetUri).toBe("/assets/factory/stations/assembly.glb");
    expect(res.provenance.source).toBe("GENERIC_MANIFEST");
    expect(res.provenance.license).toBe("CC0");
  });

  it("PROCEDURAL is the final, always-available fallback with no manifest entry and no machine asset", () => {
    const res = resolveMachineAsset(machine({ process_type: "laser welding", asset: null }));
    expect(res.status).toBe("PROCEDURAL");
    expect(res.assetUri).toBeNull();
    expect(res.confidence).toBe(0);
  });

  it("falls through past a non-loadable EXACT_CAD asset (never fabricates a uri), landing on GENERIC when a manifest entry exists for the category", () => {
    const res = resolveMachineAsset(machine({ process_type: "assembly", asset: exactAsset({ asset_uri: null }) }));
    expect(res.status).toBe("GENERIC");
    expect(res.provenance.source).toBe("GENERIC_MANIFEST");
  });

  it("falls through to PROCEDURAL (never fabricates a uri) when EXACT_CAD is recorded but not actually loadable and no manifest entry exists either", () => {
    const res = resolveMachineAsset(machine({ process_type: "laser welding", asset: exactAsset({ asset_uri: null }) }));
    expect(res.status).toBe("PROCEDURAL");
  });

  it("is deterministic — same machine resolves identically on repeated calls", () => {
    const m = machine({ asset: exactAsset() });
    const a = resolveMachineAsset(m);
    const b = resolveMachineAsset(m);
    expect(a).toEqual(b);
  });

  it("different machines can safely share the same generic category without interfering", () => {
    const original = GENERIC_ASSET_MANIFEST.SCREWDRIVING_STATION;
    GENERIC_ASSET_MANIFEST.SCREWDRIVING_STATION = {
      id: "generic-screw",
      displayName: "Generic screwdriving cell",
      uri: "/assets/machines/screwdriving/generic.glb",
      format: "GLB",
      license: { name: "CC0", attribution: null, sourceUri: null, redistributionAllowed: true },
    };
    try {
      const m1 = machine({ id: "m-1", process_type: "screwdriving" });
      const m2 = machine({ id: "m-2", process_type: "screwdriving" });
      const r1 = resolveMachineAsset(m1);
      const r2 = resolveMachineAsset(m2);
      expect(r1.assetUri).toBe(r2.assetUri);
      expect(r1).not.toBe(r2); // distinct result objects, not aliased
    } finally {
      GENERIC_ASSET_MANIFEST.SCREWDRIVING_STATION = original;
    }
  });
});

describe("visualTransformFor — Phase 9B/asset track section 11", () => {
  it("returns the identity transform for PROCEDURAL/EXACT (no manifest metadata involved)", () => {
    const res = resolveMachineAsset(machine({ asset: null }));
    expect(visualTransformFor(res)).toEqual({ scale: 1, rotationDeg: 0, offset: [0, 0, 0] });
  });

  it("applies a manifest entry's own scale/rotation/offset for a GENERIC resolution, never touching factory coordinates", () => {
    const original = GENERIC_ASSET_MANIFEST.PACKAGING_STATION;
    GENERIC_ASSET_MANIFEST.PACKAGING_STATION = {
      id: "generic-packaging",
      displayName: "Generic packaging line",
      uri: "/assets/machines/packaging/generic.glb",
      format: "GLB",
      license: { name: "CC0", attribution: null, sourceUri: null, redistributionAllowed: true },
      defaultScale: 1.2,
      defaultRotationDeg: 90,
      defaultOffset: [0, 0.1, 0],
    };
    try {
      const res = resolveMachineAsset(machine({ process_type: "packaging", asset: null }));
      expect(visualTransformFor(res)).toEqual({ scale: 1.2, rotationDeg: 90, offset: [0, 0.1, 0] });
    } finally {
      GENERIC_ASSET_MANIFEST.PACKAGING_STATION = original;
    }
  });
});
