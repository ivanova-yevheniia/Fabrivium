import { describe, expect, it } from "vitest";
import type { PlanningProvenance } from "../api/types";
import { describeProvenance, requestInterpretedByGranite } from "./provenance";

function provenance(overrides: Partial<PlanningProvenance>): PlanningProvenance {
  return {
    requirements_source: "LLM",
    planning_source: "DETERMINISTIC",
    explanation_source: "NONE",
    fallback_used: false,
    provider_name: "watsonx",
    model_name: "ibm/granite-4-h-small",
    ...overrides,
  };
}

describe("describeProvenance — Phase 9A section 10/17", () => {
  it("credits Granite only when the LLM was actually used and did not fall back", () => {
    const p = provenance({ requirements_source: "LLM", fallback_used: false });
    expect(requestInterpretedByGranite(p)).toBe(true);
    const d = describeProvenance(p);
    expect(d.tone).toBe("verified");
    expect(d.label).toContain("IBM Granite");
    expect(d.label).toContain("ibm/granite-4-h-small");
  });

  it("NEVER credits Granite when fallback_used is true, even if requirements_source claims LLM", () => {
    // Defensive: even an inconsistent/unexpected combination must not
    // produce a false Granite claim — fallback_used is the authoritative
    // "was the LLM actually used" signal.
    const p = provenance({ requirements_source: "LLM", fallback_used: true });
    expect(requestInterpretedByGranite(p)).toBe(false);
    expect(describeProvenance(p).label).not.toContain("Granite");
  });

  it("keeps the provider outage out of the headline but never loses it — the real quota-blocked-account case", () => {
    // The invariant this test has always protected: the badge must not claim
    // Granite, and must be toned "unknown". Both still hold.
    //
    // What changed is WHERE the provider sentence lives. On a results screen
    // the headline is now the product fact — Fabrivium read the
    // requirements — while "watsonx was unavailable" moves to
    // `providerDetail`, which the badge renders as a title and Architecture
    // renders in full. Nothing is hidden; the emphasis is corrected.
    const p = provenance({ requirements_source: "DETERMINISTIC", fallback_used: true, provider_name: "watsonx" });
    const d = describeProvenance(p);
    expect(d.tone).toBe("unknown");
    expect(d.label).not.toContain("Granite");
    expect(d.label).toBe("Requirements read by Fabrivium");
    expect(d.providerDetail).toContain("watsonx");
    expect(d.providerDetail).toContain("unavailable");
  });

  it("says the same product thing when no provider is configured at all", () => {
    const p = provenance({ requirements_source: "DETERMINISTIC", fallback_used: false, provider_name: null, model_name: null });
    const d = describeProvenance(p);
    expect(d.tone).toBe("unknown");
    expect(d.label).toBe("Requirements read by Fabrivium");
    expect(d.providerDetail).toMatch(/no ai model configured/i);
  });
});
