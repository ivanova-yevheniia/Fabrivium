import { describeProvenance } from "../../utils/provenance";
import type { PlanningProvenance } from "../../api/types";

/** Phase 9A — honest, reusable IBM Granite provenance display. */
export function ProvenanceBadge({
  provenance,
  compact = false,
}: {
  provenance: PlanningProvenance | null;
  compact?: boolean;
}) {
  if (!provenance) return null;
  const { label, detail, tone, providerDetail } = describeProvenance(provenance);

  return (
    <div
      className={`provenance-badge${compact ? " provenance-badge--compact" : ""}`}
      data-testid="provenance-badge"
      data-tone={tone}
      data-compact={compact}
      // Which provider served the request stays reachable on hover and to a
      // screen reader, and is rendered in full in the Architecture panel. It
      // is not the headline on a results screen — that screen is about the
      // engineering, and an account's quota state is not engineering.
      title={providerDetail || (compact ? detail : undefined)}
    >
      <span className={`fm-badge fm-badge--${tone === "verified" ? "verified" : "unknown"}`}>{label}</span>
      {!compact && detail && <span className="provenance-badge__detail">{detail}</span>}
    </div>
  );
}
