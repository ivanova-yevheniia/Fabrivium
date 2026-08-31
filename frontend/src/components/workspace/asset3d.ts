import type { Machine } from "../../api/types";

/**
 * Formats GLTFLoader can actually render (Phase 6C section 4) — a
 * deliberately NARROWER, DIFFERENT concern from the backend's
 * KNOWN_CAD_FILE_FORMATS list (which documents recognized CAD-provenance
 * formats generally, including ones like STEP/IGES that need a totally
 * different, non-Three pipeline to render at all). This is not a
 * duplicate of that list — it answers "can the 3D viewer load this file",
 * not "is this a recognized CAD format".
 */
const GLTF_LOADABLE_FORMATS = new Set(["GLB", "GLTF"]);

/** Returns the asset_uri to load via GLTFLoader, or null if this machine
 * has no loadable 3D asset (falls back to the proxy/missing box — Phase
 * 6C section 4/5). Never fabricates a URL. */
export function resolveGltfUrl(machine: Machine): string | null {
  const asset = machine.asset;
  if (!asset) return null;
  if (asset.asset_type !== "EXACT_CAD" && asset.asset_type !== "LIBRARY") return null;
  if (!asset.asset_uri) return null;
  const format = asset.file_format?.toUpperCase() ?? null;
  if (format && !GLTF_LOADABLE_FORMATS.has(format)) return null;
  // No file_format recorded at all: still attempt the load (asset_uri's
  // own extension is the loader's problem, not ours to pre-judge) unless
  // a DIFFERENT, non-loadable format was explicitly recorded above.
  return asset.asset_uri;
}
