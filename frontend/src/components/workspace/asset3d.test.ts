import { describe, expect, it } from "vitest";
import type { EquipmentAsset, Machine } from "../../api/types";
import { sampleFactory } from "../../test/fixtures";
import { resolveGltfUrl } from "./asset3d";

const [baseMachine] = sampleFactory.machines;

function withAsset(asset: EquipmentAsset | null): Machine {
  return { ...baseMachine, asset };
}

function asset(overrides: Partial<EquipmentAsset>): EquipmentAsset {
  return {
    asset_type: "EXACT_CAD", status: "AVAILABLE", asset_uri: "https://example.com/m.glb",
    source_uri: null, manufacturer: null, model_number: null, license_name: null, attribution: null, file_format: "GLB", notes: null,
    ...overrides,
  };
}

describe("resolveGltfUrl", () => {
  it("returns null when the machine has no asset at all", () => {
    expect(resolveGltfUrl(withAsset(null))).toBeNull();
  });

  it("returns null for a PROXY asset (renders as a box, never attempts a load)", () => {
    expect(resolveGltfUrl(withAsset(asset({ asset_type: "PROXY", asset_uri: null, file_format: null })))).toBeNull();
  });

  it("returns null when EXACT_CAD/LIBRARY has no asset_uri", () => {
    expect(resolveGltfUrl(withAsset(asset({ asset_uri: null })))).toBeNull();
  });

  it("returns the URL for EXACT_CAD with a GLB file_format", () => {
    expect(resolveGltfUrl(withAsset(asset({ asset_type: "EXACT_CAD", file_format: "GLB" })))).toBe("https://example.com/m.glb");
  });

  it("returns the URL for LIBRARY with a GLTF file_format", () => {
    expect(resolveGltfUrl(withAsset(asset({ asset_type: "LIBRARY", file_format: "GLTF" })))).toBe("https://example.com/m.glb");
  });

  it("returns null for a recognized-but-non-loadable CAD format (e.g. STEP) — a genuinely different concern from GLTF-loadability", () => {
    expect(resolveGltfUrl(withAsset(asset({ file_format: "STEP" })))).toBeNull();
  });

  it("attempts the load when file_format is not recorded at all — the loader decides, not a pre-judgement here", () => {
    expect(resolveGltfUrl(withAsset(asset({ file_format: null })))).toBe("https://example.com/m.glb");
  });
});
