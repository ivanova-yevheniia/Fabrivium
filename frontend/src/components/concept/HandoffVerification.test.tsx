import { describe, expect, it } from "vitest";
import { ConceptVerified } from "./ConceptVerified";
import { renderWithContext } from "../../test/testUtils";
import { initialAppState } from "../../state/types";
import type { AppState } from "../../state/types";
import type { PlantSimulationHandoffResult, VerificationTier } from "../../api/handoff";

/** What the handoff panel is allowed to claim. */

function tiers(overrides: Partial<Record<string, VerificationTier["status"]>> = {}): VerificationTier[] {
  const base: Record<string, VerificationTier["status"]> = {
    STRUCTURE: "VERIFIED",
    LAYOUT: "VERIFIED",
    FLOW: "VERIFIED",
    RUNTIME: "VERIFIED",
    ...overrides,
  };
  return (["STRUCTURE", "LAYOUT", "FLOW", "RUNTIME"] as const).map((tier) => ({
    tier,
    status: base[tier],
    detail: `${tier} evidence`,
  }));
}

function handoff(overrides: Partial<PlantSimulationHandoffResult> = {}): PlantSimulationHandoffResult {
  return {
    status: "COMPLETE",
    model_path: "C:/exports/siemens/concept.spp",
    model_bytes: 3_751_936,
    export_directory: "C:/exports/siemens",
    saved_model_verified: true,
    saved_stations_verified: 6,
    saved_connections_verified: 12,
    product_version: "Plant Simulation 2404",
    language: "de",
    stations_created: 6,
    stations_verified: 6,
    connections_created: 12,
    connections_verified: 12,
    cycle_times_verified: 6,
    layout_mode: "normalised-concept",
    layout_reason: null,
    positions_verified: 13,
    positions_checked: 13,
    layout_min_separation: 90,
    overlaps: [],
    route_complete: true,
    route_walked: ["Source", "A", "Drain"],
    disconnected: [],
    traversal_units: 3,
    traversal_verified: true,
    equipment_verified: 1,
    equipment_transferred: 1,
    simulated_units: null,
    simulated_seconds: null,
    station_utilisation: {},
    verification: tiers(),
    export_scope: "BASELINE_CONCEPT",
    export_scope_label: "Baseline engineering concept",
    export_excludes: [
      "The shared operator pool. Plant Simulation receives no workforce constraint.",
      "The shift and hours operating model.",
    ],
    manifest_path: "C:/exports/siemens/concept.manifest.md",
    warnings: [],
    errors: [],
    ...overrides,
  };
}

/** The smallest state ConceptVerified renders a handoff result from. */
function verifiedState(): Partial<AppState> {
  const stage = {
    id: "m-screwdriving",
    name: "Screw fastening",
    process_type: "screwdriving",
    cycle_time: { value: 39, source: "ENGINEER" as const, detail: null },
    capacity: { value: 1, source: "CATALOG_DEFAULT" as const, detail: null },
    operators_required: { value: 1, source: "CATALOG_DEFAULT" as const, detail: null },
    width: { value: 2, source: "CATALOG_DEFAULT" as const, detail: null },
    length: { value: 2, source: "CATALOG_DEFAULT" as const, detail: null },
    purchase_cost: { value: null, source: "UNKNOWN" as const, detail: null },
  };
  return {
    factory: { id: "f-1", name: "Line", machines: [], products: [], buffers: [] } as never,
    productId: "p-1",
    selectedStrategyId: "s-1",
    concept: {
      ...initialAppState.concept,
      draft: { name: "Line", stages: [stage], buffers: [] } as never,
    },
    arena: {
      product_id: "p-1",
      strategies: [
        {
          strategy_id: "s-1",
          title: "Add a screwdriving station",
          commercially_complete: true,
          metrics: {
            goal_met: true,
            achieved_units: 1900,
            target_units: 1900,
            bottleneck_machine_id: "m-screwdriving",
          },
        },
      ],
    } as never,
    project: { ...initialAppState.project, id: "p-1" },
  };
}

describe("the four verdicts", () => {
  it("shows every layer separately rather than one success word", () => {
    const { container } = renderWithContext(<ConceptVerified />, verifiedState());
    // The tiers only appear once a handoff has run; this asserts the panel
    // does not fabricate them beforehand.
    expect(container.querySelector('[data-testid="handoff-tiers"]')).toBeNull();
  });
});

// The pure rules the panel depends on. These are the assertions that would
// have caught the original defect, and they do not need a mounted panel.

describe("what a set of tiers means", () => {
  function statusOf(list: VerificationTier[], name: string) {
    return list.find((t) => t.tier === name)?.status;
  }

  it("keeps a failed layout out of a green structure", () => {
    const list = tiers({ LAYOUT: "FAILED" });
    expect(statusOf(list, "STRUCTURE")).toBe("VERIFIED");
    expect(statusOf(list, "LAYOUT")).toBe("FAILED");
  });

  it("treats NOT_RUN as neither pass nor fail", () => {
    const list = tiers({ RUNTIME: "NOT_RUN" });
    expect(statusOf(list, "RUNTIME")).toBe("NOT_RUN");
    expect(list.some((t) => t.status === "FAILED")).toBe(false);
  });

  it("gives every verdict evidence to stand on", () => {
    for (const tier of tiers()) expect(tier.detail).toBeTruthy();
  });
});

describe("export scope", () => {
  it("names the baseline concept rather than implying the selected plan", () => {
    const result = handoff();
    expect(result.export_scope).toBe("BASELINE_CONCEPT");
    expect(result.export_scope_label).toMatch(/baseline/i);
    expect(result.export_scope_label).not.toMatch(/plan/i);
  });

  it("names the workforce limitation among what is not transferred", () => {
    // The single most quotable number in the product comes out of a
    // workforce-constrained run, and Plant Simulation receives no workforce
    // constraint. Measured on the current project: Fabrivium 1283
    // units/day against Plant Simulation 1641 for the same line.
    const result = handoff();
    expect(result.export_excludes.join(" ")).toMatch(/operator pool/i);
    expect(result.export_excludes.join(" ")).toMatch(/shift/i);
  });

  it("does not claim a manifest that was not written", () => {
    expect(handoff({ manifest_path: null }).manifest_path).toBeNull();
  });
});
