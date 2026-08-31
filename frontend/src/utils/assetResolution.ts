/**
 * Parallel asset-resolution track — deterministic, provenance-aware 3D
 * visualization resolution for one Machine.
 *
 * HARD RULE (non-negotiable, per the spec this module implements): this
 * file is VISUALIZATION ONLY. It reads `Machine.process_type`/`Machine.asset`
 * — both already fully typed and already shipped by the deterministic
 * engineering core (Phase 3A `EquipmentAsset`) — and NEVER writes back to
 * them, never touches cycle_time/capacity/routing/buffers/operators, and is
 * never imported by any simulation/optimization code path. No backend
 * changes were needed or made for this track.
 *
 * Real defect found and fixed here: `machineVisual.ts::assetVisualKind`
 * previously treated `asset_type: "LIBRARY"` identically to `"EXACT_CAD"` —
 * so a LIBRARY asset (per `EquipmentAssetType`'s own backend docstring, "a
 * reusable stock/library model (not the exact unit)") rendered with ZERO
 * disclosure that it wasn't the real machine. Confirmed live: the bundled
 * electronics_line.json's `m-screwdriving` has a LIBRARY asset pointing at
 * `/models/conveyor.glb` — a conveyor model standing in for a screwdriving
 * station — and it rendered as if it were exact CAD. This module's
 * resolution order fixes that: LIBRARY resolves to GENERIC, always badged.
 */

import type { Machine } from "../api/types";
import { resolveGltfUrl } from "../components/workspace/asset3d";

// Section 4 — the smallest useful generic taxonomy

export type MachineCategory =
  | "ASSEMBLY_STATION"
  | "SCREWDRIVING_STATION"
  | "INSPECTION_STATION"
  | "PACKAGING_STATION"
  | "GENERIC_PROCESSING_MACHINE";

/** Explicit, deterministic substring aliases (never LLM-generated — spec
 * section 4's explicit constraint), checked in order. Kept as its own
 * small table rather than reusing `machineVisual.ts::proxyFamily` — that
 * function drives which PROCEDURAL silhouette to draw (a stable, already
 * separately-tested concern) and has a narrower match list than this
 * taxonomy needs (e.g. it does not treat "automatic screw station" as a
 * screwdriving alias). Both independently agree on the flagship's four
 * stations; this table is free to be broader without risking that file's
 * own behaviour/tests. */
const CATEGORY_ALIASES: Array<[MachineCategory, string[]]> = [
  ["ASSEMBLY_STATION", ["assembly"]],
  ["SCREWDRIVING_STATION", ["screwdriv", "screw driving", "screw station", "screw cell", " screw ", "screw-"]],
  ["INSPECTION_STATION", ["inspect", "quality", "qc"]],
  ["PACKAGING_STATION", ["packag"]],
];

export function categoryForProcessType(processType: string): MachineCategory {
  const t = ` ${processType.toLowerCase()} `;
  for (const [category, aliases] of CATEGORY_ALIASES) {
    if (aliases.some((alias) => t.includes(alias))) return category;
  }
  return "GENERIC_PROCESSING_MACHINE";
}

// Section 6/7 — generic asset manifest (category-level, not machine-level)

export interface GenericAssetManifestEntry {
  id: string;
  displayName: string;
  uri: string;
  format: "GLB" | "GLTF";
  license: {
    name: string;
    attribution: string | null;
    sourceUri: string | null;
    redistributionAllowed: boolean;
  };
  defaultScale?: number;
  defaultRotationDeg?: number;
  defaultOffset?: [number, number, number];
}

/**
 * Section 5/7 — four flagship categories are wired to a real, license-clear
 * local asset pack (Kenney "Factory Kit" 3.0, CC0 — verified directly from
 * the archive's own License.txt before wiring: "You can use this content
 * for personal, educational, and commercial purposes... attribution is not
 * a requirement"). Files were extracted 1:1 (no re-encoding, byte-identical
 * to the archive source) into `frontend/public/assets/factory/stations/`.
 * GENERIC_PROCESSING_MACHINE has no flagship-specific model and stays
 * `null` — resolution falls through to PROCEDURAL for it, honestly, exactly
 * as it does for every category when no manifest entry exists.
 */
export const GENERIC_ASSET_MANIFEST: Record<MachineCategory, GenericAssetManifestEntry | null> = {
  ASSEMBLY_STATION: {
    id: "kenney-factory-kit-robot-arm-a",
    displayName: "Generic assembly station",
    uri: "/assets/factory/stations/assembly.glb",
    format: "GLB",
    license: { name: "CC0", attribution: "Kenney Factory Kit (kenney.nl)", sourceUri: "https://kenney.nl", redistributionAllowed: true },
  },
  SCREWDRIVING_STATION: {
    id: "kenney-factory-kit-machine-fortified",
    displayName: "Generic screwdriving cell",
    uri: "/assets/factory/stations/screwdriving.glb",
    format: "GLB",
    license: { name: "CC0", attribution: "Kenney Factory Kit (kenney.nl)", sourceUri: "https://kenney.nl", redistributionAllowed: true },
  },
  INSPECTION_STATION: {
    id: "kenney-factory-kit-scanner-high",
    displayName: "Generic inspection station",
    uri: "/assets/factory/stations/inspection.glb",
    format: "GLB",
    license: { name: "CC0", attribution: "Kenney Factory Kit (kenney.nl)", sourceUri: "https://kenney.nl", redistributionAllowed: true },
  },
  PACKAGING_STATION: {
    id: "kenney-factory-kit-machine-window",
    displayName: "Generic packaging station",
    uri: "/assets/factory/stations/packaging.glb",
    format: "GLB",
    license: { name: "CC0", attribution: "Kenney Factory Kit (kenney.nl)", sourceUri: "https://kenney.nl", redistributionAllowed: true },
  },
  GENERIC_PROCESSING_MACHINE: null,
};

// Section 2 — typed resolution result

export type AssetResolutionStatus = "EXACT" | "GENERIC" | "PROCEDURAL" | "USER_UPLOADED";

export interface AssetResolution {
  status: AssetResolutionStatus;
  /** Renderable GLB/GLTF uri, or null when PROCEDURAL (no file to load). */
  assetUri: string | null;
  requestedCategory: MachineCategory;
  /** The category the resolved asset actually belongs to — always equal to
   * requestedCategory for EXACT/machine-attached GENERIC; may differ if a
   * future resolution tier matches a compatible-but-different category
   * (not used by any tier implemented today, reserved for that case). */
  resolvedCategory: MachineCategory | null;
  provenance: {
    source: "MACHINE_ASSET" | "GENERIC_MANIFEST" | "PROCEDURAL" | "USER_UPLOAD";
    license: string | null;
    attribution: string | null;
  };
  /** 1.0 = machine's own exact CAD. */
  confidence: number;
  reason: string;
}

function procedural(category: MachineCategory, reason: string): AssetResolution {
  return {
    status: "PROCEDURAL",
    assetUri: null,
    requestedCategory: category,
    resolvedCategory: null,
    provenance: { source: "PROCEDURAL", license: null, attribution: null },
    confidence: 0,
    reason,
  };
}

// Section 3 — deterministic resolution order

/**
 * machine-specific exact asset → machine-attached library/generic asset →
 * category generic-manifest match → procedural placeholder.
 *
 * Every branch is a pure function of already-real, already-typed data
 * (`Machine.asset`, `Machine.process_type`) — nothing here invents a URL,
 * a category, or a confidence value not derivable from that input.
 */
export function resolveMachineAsset(machine: Machine): AssetResolution {
  const category = categoryForProcessType(machine.process_type);
  const asset = machine.asset;

  if (asset && asset.asset_type === "EXACT_CAD") {
    const uri = resolveGltfUrl(machine);
    if (uri) {
      return {
        status: "EXACT",
        assetUri: uri,
        requestedCategory: category,
        resolvedCategory: category,
        provenance: {
          source: "MACHINE_ASSET",
          license: asset.license_name ?? null,
          attribution: asset.attribution ?? null,
        },
        confidence: 1,
        reason: "Machine has its own EXACT_CAD asset with a loadable GLB/GLTF uri.",
      };
    }
    // EXACT_CAD recorded but not actually loadable (wrong format / no uri /
    // not yet AVAILABLE) — falls through rather than lying about status.
  }

  if (asset && asset.asset_type === "LIBRARY") {
    const uri = resolveGltfUrl(machine);
    if (uri) {
      return {
        status: "GENERIC",
        assetUri: uri,
        requestedCategory: category,
        resolvedCategory: category,
        provenance: {
          source: "MACHINE_ASSET",
          license: asset.license_name ?? null,
          attribution: asset.attribution ?? null,
        },
        confidence: 0.6,
        reason: "Machine has a LIBRARY (stock, not-exact-unit) asset attached directly.",
      };
    }
  }

  const manifestEntry = GENERIC_ASSET_MANIFEST[category];
  if (manifestEntry) {
    return {
      status: "GENERIC",
      assetUri: manifestEntry.uri,
      requestedCategory: category,
      resolvedCategory: category,
      provenance: {
        source: "GENERIC_MANIFEST",
        license: manifestEntry.license.name,
        attribution: manifestEntry.license.attribution,
      },
      confidence: 0.4,
      reason: `Matched the local generic asset pack for ${category}.`,
    };
  }

  return procedural(
    category,
    asset
      ? `Machine's recorded asset (${asset.asset_type}) is not currently loadable; no generic asset pack entry exists for ${category} either.`
      : `No machine asset recorded, and no generic asset pack entry exists yet for ${category}.`,
  );
}

// Section 15 — future external search, architecture only. Not called from
// anywhere; no network dependency is introduced by defining this interface.

export interface AssetProviderSearchResult {
  externalId: string;
  title: string;
  category: MachineCategory;
  license: string | null;
}

export interface AssetProvider {
  readonly providerName: string;
  search(query: string, category?: MachineCategory): Promise<AssetProviderSearchResult[]>;
  getMetadata(externalId: string): Promise<GenericAssetManifestEntry | null>;
  resolve(externalId: string): Promise<AssetResolution>;
}

// Section 11 — visualization transform metadata lives with the asset, never
// mutates factory layout coordinates. Exposed here so Machine3D can apply a
// manifest/machine-asset's scale/rotation/offset without Scene3D needing to
// know where those numbers came from.

export interface AssetVisualTransform {
  scale: number;
  rotationDeg: number;
  offset: [number, number, number];
}

export const IDENTITY_TRANSFORM: AssetVisualTransform = { scale: 1, rotationDeg: 0, offset: [0, 0, 0] };

export function visualTransformFor(resolution: AssetResolution): AssetVisualTransform {
  if (resolution.status !== "GENERIC" || resolution.resolvedCategory === null) return IDENTITY_TRANSFORM;
  const entry = GENERIC_ASSET_MANIFEST[resolution.resolvedCategory];
  if (!entry) return IDENTITY_TRANSFORM;
  return {
    scale: entry.defaultScale ?? 1,
    rotationDeg: entry.defaultRotationDeg ?? 0,
    offset: entry.defaultOffset ?? [0, 0, 0],
  };
}
