/** Phase 9A section 10/17 — honest IBM Granite provenance presentation. */

import type { PlanningProvenance } from "../api/types";

export type ProvenanceTone = "verified" | "unknown";

export interface ProvenanceDisplay {
  label: string;
  detail: string;
  tone: ProvenanceTone;
  /** Which provider actually served the request. */
  providerDetail?: string;
}

/** True only when the request text was ACTUALLY interpreted by the configured LLM — i.e. */
export function requestInterpretedByGranite(p: Pick<PlanningProvenance, "requirements_source" | "fallback_used">): boolean {
  return p.requirements_source === "LLM" && !p.fallback_used;
}

export function describeProvenance(p: PlanningProvenance): ProvenanceDisplay {
  if (requestInterpretedByGranite(p)) {
    return {
      label: p.model_name ? `IBM Granite (${p.model_name})` : "IBM Granite",
      detail: "Interpreted this request",
      tone: "verified",
    };
  }
  // BOTH non-Granite branches say the same PRODUCT thing — Fabrivium read
  // the requirements itself — because that is the fact an engineer can act on.
  // Which provider was reachable is a fact about our account, not about the
  // engineering, and it belongs in Architecture (where `providerDetail` below
  // still carries it verbatim) rather than on the screen showing throughput.
  //
  // The distinction itself is NOT hidden: `tone: "unknown"` is unchanged, so
  // the badge still reads differently from the Granite branch and stays
  // machine-checkable. What changed is only which sentence is the headline.
  if (p.fallback_used && p.provider_name) {
    return {
      label: "Requirements read by Fabrivium",
      detail: "",
      tone: "unknown",
      providerDetail: `${p.provider_name} was unavailable for this request — a deterministic parser handled it instead`,
    };
  }
  return {
    label: "Requirements read by Fabrivium",
    detail: "",
    tone: "unknown",
    providerDetail: "No AI model configured for this request",
  };
}
