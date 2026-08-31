import type { Factory } from "../../api/types";
import { GENERIC_ASSET_MANIFEST, resolveMachineAsset } from "../../utils/assetResolution";
import type { AssetResolutionStatus } from "../../utils/assetResolution";

/** Phase 10 — one honest, scene-level statement of where the 3D models came from. */

/** What each resolution status IS, in the words the plaque uses. */
const STATUS_NOUN: Record<AssetResolutionStatus, string> = {
  EXACT: "the machine's own CAD",
  GENERIC: "generic station models",
  USER_UPLOADED: "models supplied for this project",
  PROCEDURAL: "footprint placeholders",
};

/** The distinct licences behind whatever GENERIC models this scene actually uses. */
function creditsInUse(factory: Factory): Array<{ pack: string; license: string }> {
  const credits = new Map<string, { pack: string; license: string }>();

  for (const machine of factory.machines) {
    const resolution = resolveMachineAsset(machine);
    if (resolution.status !== "GENERIC" || resolution.provenance.source !== "GENERIC_MANIFEST") continue;
    const entry = resolution.resolvedCategory ? GENERIC_ASSET_MANIFEST[resolution.resolvedCategory] : null;
    if (!entry) continue;
    const pack = entry.license.attribution ?? "Unattributed pack";
    credits.set(`${pack}|${entry.license.name}`, { pack, license: entry.license.name });
  }

  return [...credits.values()];
}

export function AssetProvenanceLegend({ factory }: { factory: Factory | null }) {
  if (!factory || factory.machines.length === 0) return null;

  const counts = new Map<AssetResolutionStatus, number>();
  for (const machine of factory.machines) {
    const { status } = resolveMachineAsset(machine);
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }

  const rows = [...counts.entries()].filter(([, count]) => count > 0);
  if (rows.length === 0) return null;

  const total = factory.machines.length;
  // One status covering every station reads as a plain statement; a mix is
  // enumerated, because "6 stations use generic models" would be false of a
  // scene where one of them has real CAD.
  const mix =
    rows.length === 1
      ? `${STATUS_NOUN[rows[0][0]]}`
      : rows.map(([status, count]) => `${count} of ${total} ${STATUS_NOUN[status]}`).join(", ");

  const credits = creditsInUse(factory);

  return (
    <div className="scene-plaque" data-testid="asset-provenance-legend">
      <p className="scene-plaque__title">Concept visualization</p>
      <p className="scene-plaque__body">
        {/* The two facts a viewer needs, in the order they need them: what
            the shapes are, and what has NOT been decided. The second is the
            one silence would be read as answered. */}
        <span data-testid="asset-provenance-mix">
          {rows.length === 1 ? `Stations are drawn with ${mix}.` : `Stations are drawn with ${mix}.`}
        </span>{" "}
        Exact supplier equipment has not been selected.
        {credits.map((credit) => (
          <span
            className="scene-plaque__credit"
            key={`${credit.pack}|${credit.license}`}
            data-testid="asset-provenance-credit"
          >
            {credit.pack} · {credit.license}
          </span>
        ))}
      </p>
    </div>
  );
}
