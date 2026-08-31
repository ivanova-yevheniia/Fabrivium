import type { Machine } from "../../api/types";
import { resolveMachineAsset } from "../../utils/assetResolution";

/**
 * Visual-distinction rules for equipment asset representation (Phase 6B
 * section 10, corrected by the parallel asset-resolution track). Geometry
 * (footprint/envelope) always comes from Machine.width/length/physical_envelope
 * — this module ONLY decides fill pattern/opacity/label, never a dimension.
 *
 * "generic" is a distinct kind from "exact" — a LIBRARY asset on the machine
 * or a category match from the generic asset pack (assetResolution.ts) is a
 * real, renderable model, but it is NOT the specific unit's own CAD, so it
 * must always be disclosed as such. Previously LIBRARY was folded into
 * "exact" here (the real defect this track fixes — see assetResolution.ts's
 * header comment for the concrete case).
 */
export type AssetVisualKind = "exact" | "generic" | "proxy" | "missing";

export function assetVisualKind(machine: Machine): AssetVisualKind {
  // A backend-recorded PROXY is an explicit "no real geometry" signal —
  // takes precedence over any generic-manifest match the resolver might
  // otherwise find for this machine's category.
  if (machine.asset?.asset_type === "PROXY") return "proxy";
  const resolution = resolveMachineAsset(machine);
  if (resolution.status === "EXACT") return "exact";
  if (resolution.status === "GENERIC") return "generic";
  return "missing"; // PROCEDURAL — no machine asset and no manifest match
}

export function assetFillId(kind: AssetVisualKind): string {
  if (kind === "generic") return "url(#fm-generic-hatch)";
  if (kind === "proxy") return "url(#fm-proxy-hatch)";
  if (kind === "missing") return "url(#fm-missing-hatch)";
  return "var(--fm-panel)";
}

export function assetLabel(kind: AssetVisualKind): string | null {
  if (kind === "generic") return "GENERIC";
  if (kind === "proxy") return "PROXY";
  if (kind === "missing") return "NO ASSET";
  return null;
}

// Procedural proxy families (Phase 6C.1) — when no GLB is loaded (proxy,
// missing, or a real EXACT_CAD asset still in flight), the fallback box
// should read as "roughly what kind of machine this is", not as a raw debug
// cube. process_type ONLY selects which lightweight primitive silhouette to
// draw; it never changes the engineering footprint (width/length) or
// invents a simulation property. Every family's parts stay inside the
// machine's width x height x length envelope passed in.

export type ProxyFamily =
  | "assembly"
  | "workcell"
  | "inspection"
  | "packaging"
  | "generic";

/** Buckets a free-text process_type into one of the known visual families. */
export function proxyFamily(processType: string): ProxyFamily {
  const t = processType.toLowerCase();
  if (t.includes("assembly")) return "assembly";
  if (t.includes("screwdriv") || t.includes("workcell") || t.includes("robot") || t.includes("cell")) return "workcell";
  if (t.includes("inspect") || t.includes("qc") || t.includes("quality")) return "inspection";
  if (t.includes("packag")) return "packaging";
  return "generic";
}

export interface ProxyPart {
  shape: "box" | "cylinder";
  /** Geometry constructor args, matching Three.js's own (box: [w,h,d],
   * cylinder: [radiusTop, radiusBottom, height, radialSegments]). */
  args: number[];
  position: [number, number, number];
  rotation?: [number, number, number];
}

export interface ProxyDims {
  width: number;
  height: number;
  length: number;
}

/** Returns the primitive parts making up one family's silhouette, in local
 * space centered on the machine's engineering footprint (Y=0 is floor
 * level, matching Machine3D's group origin at height/2 above the floor —
 * see utils/geometry3d.placementToThreePosition). */
export function proxyFamilyParts(processType: string, dims: ProxyDims): ProxyPart[] {
  const family = proxyFamily(processType);
  const { width: w, height: h, length: l } = dims;
  const floorY = -h / 2;

  switch (family) {
    case "assembly": {
      // Flat workbench spanning the footprint, plus a fixture/jig block
      // toward the rear where a part would be held for assembly.
      const benchH = h * 0.22;
      const fixtureH = h * 0.62;
      return [
        { shape: "box", args: [w, benchH, l], position: [0, floorY + benchH / 2, 0] },
        {
          shape: "box",
          args: [w * 0.38, fixtureH, l * 0.32],
          position: [0, floorY + benchH + fixtureH / 2, l * 0.22],
        },
      ];
    }

    case "workcell": {
      // Pedestal base + a vertical arm post with a tool head reaching
      // forward — a simple robotic/screwdriving-cell silhouette.
      const baseH = h * 0.22;
      const postH = h * 0.6;
      const headH = h * 0.12;
      const baseR = Math.min(w, l) * 0.32;
      return [
        { shape: "cylinder", args: [baseR, baseR * 1.1, baseH, 16], position: [0, floorY + baseH / 2, 0] },
        {
          shape: "box",
          args: [w * 0.16, postH, l * 0.16],
          position: [0, floorY + baseH + postH / 2, 0],
        },
        {
          shape: "box",
          args: [w * 0.42, headH, l * 0.22],
          position: [0, floorY + baseH + postH, -l * 0.18],
        },
      ];
    }

    case "inspection": {
      // Low table + a slender post carrying an angled sensor/camera head.
      const tableH = h * 0.1;
      const postH = h * 0.62;
      const headH = h * 0.14;
      const postR = Math.min(w, l) * 0.07;
      return [
        { shape: "box", args: [w * 0.92, tableH, l * 0.92], position: [0, floorY + tableH / 2, 0] },
        {
          shape: "cylinder",
          args: [postR, postR, postH, 12],
          position: [0, floorY + tableH + postH / 2, l * 0.25],
        },
        {
          shape: "box",
          args: [w * 0.26, headH, l * 0.24],
          position: [0, floorY + tableH + postH, l * 0.02],
          rotation: [-0.35, 0, 0],
        },
      ];
    }

    case "packaging": {
      // Waist-height packing table topped with conveyor rollers.
      const tableH = h * 0.5;
      const rollerR = Math.min(h * 0.05, l * 0.06);
      const rollerCount: number = 5;
      const parts: ProxyPart[] = [
        { shape: "box", args: [w * 0.95, tableH, l * 0.95], position: [0, floorY + tableH / 2, 0] },
      ];
      for (let i = 0; i < rollerCount; i += 1) {
        const t = rollerCount === 1 ? 0.5 : i / (rollerCount - 1);
        const z = -l * 0.4 + t * l * 0.8;
        parts.push({
          shape: "cylinder",
          args: [rollerR, rollerR, w * 0.92, 10],
          position: [0, floorY + tableH + rollerR, z],
          rotation: [0, 0, Math.PI / 2],
        });
      }
      return parts;
    }

    case "generic":
    default: {
      // Plain industrial cabinet with a small control-panel block.
      const bodyH = h * 0.86;
      const panelH = h * 0.22;
      return [
        { shape: "box", args: [w * 0.92, bodyH, l * 0.92], position: [0, floorY + bodyH / 2, 0] },
        {
          shape: "box",
          args: [w * 0.3, panelH, l * 0.06],
          position: [0, floorY + bodyH * 0.55, -l * 0.46 - l * 0.03],
        },
      ];
    }
  }
}
