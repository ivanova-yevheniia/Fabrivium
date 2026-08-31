import { describe, expect, it } from "vitest";
import { proxyFamily, proxyFamilyParts } from "./machineVisual";
import type { ProxyDims, ProxyPart } from "./machineVisual";

const dims: ProxyDims = { width: 2, height: 1.8, length: 2.4 };

describe("proxyFamily", () => {
  it("buckets assembly-ish process_types as assembly", () => {
    expect(proxyFamily("assembly")).toBe("assembly");
    expect(proxyFamily("Final Assembly")).toBe("assembly");
  });

  it("buckets screwdriving/workcell/robot process_types as workcell", () => {
    expect(proxyFamily("screwdriving")).toBe("workcell");
    expect(proxyFamily("robot_cell")).toBe("workcell");
    expect(proxyFamily("workcell")).toBe("workcell");
  });

  it("buckets inspection/qc process_types as inspection", () => {
    expect(proxyFamily("inspection")).toBe("inspection");
    expect(proxyFamily("quality_check")).toBe("inspection");
  });

  it("buckets packaging process_types as packaging", () => {
    expect(proxyFamily("packaging")).toBe("packaging");
  });

  it("is case-insensitive", () => {
    expect(proxyFamily("PACKAGING")).toBe("packaging");
  });

  it("falls back to generic for an unrecognized process_type, never throwing", () => {
    expect(proxyFamily("welding")).toBe("generic");
    expect(proxyFamily("")).toBe("generic");
  });
});

describe("proxyFamilyParts", () => {
  const families = ["assembly", "screwdriving", "inspection", "packaging", "welding"];

  it.each(families)("returns at least one part for process_type=%s", (processType) => {
    const parts = proxyFamilyParts(processType, dims);
    expect(parts.length).toBeGreaterThan(0);
  });

  it("keeps every part's footprint within the machine's engineering width/length envelope", () => {
    for (const processType of families) {
      const parts = proxyFamilyParts(processType, dims);
      for (const part of parts) {
        if (part.shape === "box") {
          const [pw, , pl] = part.args;
          expect(pw).toBeLessThanOrEqual(dims.width + 1e-9);
          expect(pl).toBeLessThanOrEqual(dims.length + 1e-9);
        } else {
          const [radiusTop, radiusBottom] = part.args;
          expect(radiusTop * 2).toBeLessThanOrEqual(Math.max(dims.width, dims.length) + 1e-9);
          expect(radiusBottom * 2).toBeLessThanOrEqual(Math.max(dims.width, dims.length) + 1e-9);
        }
      }
    }
  });

  it("keeps every part within the machine's engineering height envelope (never floats above the roof)", () => {
    // A cylinder rotated ~90deg about Z (e.g. a conveyor roller) lies on its
    // side: its vertical extent is its RADIUS, not half of its own
    // "height" arg (which now runs horizontally). Everything else's
    // vertical extent is just half its own height arg.
    const verticalHalfExtent = (part: ProxyPart): number => {
      if (part.shape === "cylinder") {
        const rotZ = part.rotation?.[2] ?? 0;
        const sideways = Math.abs(Math.abs(rotZ) - Math.PI / 2) < 0.01;
        return sideways ? Math.max(part.args[0], part.args[1]) : part.args[2] / 2;
      }
      return part.args[1] / 2;
    };

    const floorY = -dims.height / 2;
    const roofY = dims.height / 2;
    const allParts = families.flatMap((processType) => proxyFamilyParts(processType, dims));
    for (const part of allParts) {
      const halfExtent = verticalHalfExtent(part);
      const top = part.position[1] + halfExtent;
      const bottom = part.position[1] - halfExtent;
      expect(bottom).toBeGreaterThanOrEqual(floorY - 1e-9);
      expect(top).toBeLessThanOrEqual(roofY + 1e-9);
    }
  });

  it("produces visually distinct silhouettes across families (not all the same shape list)", () => {
    const shapesByFamily = families.map((processType) =>
      proxyFamilyParts(processType, dims).map((p) => p.shape).join(","),
    );
    const distinctFamilyCount = families.length - 1; // welding + inspection etc differ, generic reused only by unmatched
    const unique = new Set(shapesByFamily);
    expect(unique.size).toBeGreaterThan(1);
    expect(unique.size).toBeLessThanOrEqual(families.length);
    void distinctFamilyCount;
  });

  it("is deterministic for the same process_type and dims", () => {
    const a = proxyFamilyParts("packaging", dims);
    const b = proxyFamilyParts("packaging", dims);
    expect(a).toEqual(b);
  });
});
