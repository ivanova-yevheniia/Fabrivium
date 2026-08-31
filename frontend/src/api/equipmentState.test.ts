import { describe, expect, it } from "vitest";
import {
  boundChanges,
  candidateState,
  checkTally,
  currentBounds,
  isStale,
  recordedBounds,
} from "./equipmentState";
import type { CandidateAssessment, CompatibilityCheck, EquipmentRequirement } from "./equipment";
import type { FactoryConceptDraft, SourcedNumber } from "./types";

/**
 * Equipment evidence expires when the requirement it answered moves — and
 * does NOT expire when something the requirement never read moves.
 *
 * The second half is the harder one and the one these tests spend most of
 * their length on. "Invalidate on any project change" would pass a careless
 * suite and ruin the feature: an engineer told their shortlist expired
 * because somebody edited the shift pattern learns to press "search again"
 * without reading, and then the warning is worthless on the day a footprint
 * actually narrowed.
 *
 * The exact dependency set comes from `requirement_from_concept`, which reads
 * nine things off the stage and one line preference — see
 * docs/EQUIPMENT_STATE_AUDIT.md §1.
 */

function sourced(value: number | null): SourcedNumber {
  return {
    value,
    source: (value === null ? "UNKNOWN" : "ENGINEER") as SourcedNumber["source"],
    detail: null,
  };
}

function requirement(overrides: Partial<EquipmentRequirement> = {}): EquipmentRequirement {
  return {
    station_id: "m-screwdriving",
    station_name: "Screw fastening",
    process_category: "screwdriving",
    required_capability: "SCREW_FASTENING",
    capability_statement: "drives threaded fasteners",
    max_cycle_time_seconds: sourced(39),
    operations_per_unit: sourced(6),
    max_payload_kg: sourced(null),
    part_dimensions_text: null,
    part_dimensions_provenance: null,
    required_capacity: sourced(1),
    operator_requirement: sourced(1),
    max_width_m: sourced(3),
    max_length_m: sourced(2),
    max_height_m: sourced(null),
    budget_limit: sourced(null),
    required_interfaces: [],
    optional_preferences: [],
    strategy_context: null,
    provenance: "from the concept",
    ...overrides,
  } as EquipmentRequirement;
}

function draft(stageOverrides: Record<string, unknown> = {}): FactoryConceptDraft {
  return {
    name: "Line",
    customer_brief: "",
    product_name: "Controller",
    production_target: sourced(1900),
    shifts_per_day: sourced(2),
    hours_per_shift: sourced(8),
    operators_available: sourced(8),
    floor_width: sourced(30),
    floor_length: sourced(18),
    budget: sourced(null),
    prefer_no_new_machines: false,
    buffers: [],
    stages: [
      {
        id: "m-screwdriving",
        name: "Screw fastening",
        process_type: "screwdriving",
        cycle_time: sourced(39),
        capacity: sourced(1),
        operators_required: sourced(1),
        width: sourced(3),
        length: sourced(2),
        purchase_cost: sourced(null),
        ...stageOverrides,
      },
    ],
  } as unknown as FactoryConceptDraft;
}

// What expires evidence

describe("a requirement bound that moves", () => {
  it("expires the finding when the cycle time changes", () => {
    expect(isStale(requirement(), draft({ cycle_time: sourced(12) }))).toBe(true);
  });

  it("expires the finding when the capacity changes", () => {
    expect(isStale(requirement(), draft({ capacity: sourced(2) }))).toBe(true);
  });

  it("expires the finding when the operator demand changes", () => {
    expect(isStale(requirement(), draft({ operators_required: sourced(2) }))).toBe(true);
  });

  it("expires the finding when the footprint narrows", () => {
    // The severe case: this flips a published-dimension check from PASS to
    // FAIL, so a stale panel presents as viable a machine that no longer fits.
    expect(isStale(requirement(), draft({ length: sourced(0.2) }))).toBe(true);
  });

  it("expires the finding when the station budget changes", () => {
    expect(isStale(requirement(), draft({ purchase_cost: sourced(900) }))).toBe(true);
  });

  it("expires the finding when the station's process changes", () => {
    expect(isStale(requirement(), draft({ process_type: "inspection" }))).toBe(true);
  });

  it("expires the finding when the station is gone from the concept", () => {
    const removed = draft();
    removed.stages = [];
    expect(isStale(requirement(), removed)).toBe(true);
    expect(boundChanges(recordedBounds(requirement()), currentBounds(removed, "m-screwdriving"))[0]
      .description).toMatch(/no longer part of the concept/i);
  });

  it("names the bound that moved, in the concept's own units", () => {
    const changes = boundChanges(
      recordedBounds(requirement()),
      currentBounds(draft({ cycle_time: sourced(12) }), "m-screwdriving"),
    );
    expect(changes).toHaveLength(1);
    expect(changes[0].description).toBe("Cycle time: 39 s → 12 s");
  });

  it("says 'not established' rather than inventing a previous number", () => {
    const changes = boundChanges(
      recordedBounds(requirement()),
      currentBounds(draft({ purchase_cost: sourced(900) }), "m-screwdriving"),
    );
    expect(changes[0].description).toBe("Station budget: not established → 900 €");
  });
});

describe("a change the requirement never read", () => {
  it("does not expire the finding when the production target changes", () => {
    const other = draft();
    other.production_target = sourced(2400);
    expect(isStale(requirement(), other)).toBe(false);
  });

  it("does not expire the finding when the shift pattern changes", () => {
    const other = draft();
    other.shifts_per_day = sourced(3);
    other.hours_per_shift = sourced(6);
    expect(isStale(requirement(), other)).toBe(false);
  });

  it("does not expire the finding when the workforce changes", () => {
    const other = draft();
    other.operators_available = sourced(12);
    expect(isStale(requirement(), other)).toBe(false);
  });

  it("does not expire the finding when the project budget changes", () => {
    // The STATION's planned cost is a bound; the project's capital budget is
    // not. Using the project figure would tell an engineer that half a
    // million euros may be spent on one screwdriver.
    const other = draft();
    other.budget = sourced(500000);
    expect(isStale(requirement(), other)).toBe(false);
  });

  it("does not expire the finding when the floor size changes", () => {
    const other = draft();
    other.floor_width = sourced(60);
    other.floor_length = sourced(40);
    expect(isStale(requirement(), other)).toBe(false);
  });

  it("does not expire the finding when nothing changed at all", () => {
    expect(isStale(requirement(), draft())).toBe(false);
  });
});

// What a finding amounts to

function check(field: string, status: CompatibilityCheck["status"]): CompatibilityCheck {
  return {
    field,
    label: field,
    status,
    requirement_text: "",
    candidate_text: "",
    reason: "",
  } as CompatibilityCheck;
}

function assessment(checks: CompatibilityCheck[]): CandidateAssessment {
  return {
    candidate: { candidate_id: "c-1" },
    compatibility: { candidate_id: "c-1", station_id: "m-screwdriving", checks },
    claim: "CANDIDATE",
    claim_text: "",
    pass_count: checks.filter((c) => c.status === "PASS").length,
    fail_count: checks.filter((c) => c.status === "FAIL").length,
    unknown_count: checks.filter((c) => c.status === "UNKNOWN").length,
  } as unknown as CandidateAssessment;
}

describe("what one candidate's assessment amounts to", () => {
  it("is CONTRADICTED when a published value fails a requirement", () => {
    const state = candidateState(
      assessment([check("capability", "PASS"), check("footprint_length", "FAIL")]),
    );
    expect(state).toBe("CONTRADICTED");
  });

  it("puts a contradiction above everything else, including staleness order", () => {
    // A stale finding is reported as STALE, because its verdicts are about
    // the old requirement — including its FAILs.
    const state = candidateState(assessment([check("footprint_length", "FAIL")]), { stale: true });
    expect(state).toBe("STALE");
  });

  it("is UNVERIFIED when an engineering requirement cannot be confirmed", () => {
    const state = candidateState(
      assessment([check("capability", "PASS"), check("cycle_time", "UNKNOWN")]),
    );
    expect(state).toBe("UNVERIFIED");
  });

  it("is COMMERCIAL_DATA_REQUIRED when only the price is missing", () => {
    const state = candidateState(
      assessment([check("capability", "PASS"), check("budget", "UNKNOWN")]),
    );
    expect(state).toBe("COMMERCIAL_DATA_REQUIRED");
  });

  it("keeps a missing price apart from a missing engineering value", () => {
    // One is a procurement task, the other an engineering unknown. Rolling
    // them together loses which one somebody has to go and do.
    const engineering = candidateState(assessment([check("cycle_time", "UNKNOWN")]));
    const commercial = candidateState(assessment([check("budget", "UNKNOWN")]));
    expect(engineering).not.toBe(commercial);
  });

  it("reaches REQUIREMENTS_MATCHED only when nothing is left unconfirmable", () => {
    const state = candidateState(
      assessment([check("capability", "PASS"), check("footprint_width", "PASS")]),
    );
    expect(state).toBe("REQUIREMENTS_MATCHED");
  });

  it("never reaches REQUIREMENTS_MATCHED on the real screwdriving shape", () => {
    // Three bounds matched, five unpublished: the honest shape of this
    // market. A screen that promoted this to "matched" would be claiming the
    // engineering was done.
    const state = candidateState(
      assessment([
        check("capability", "PASS"),
        check("footprint_width", "PASS"),
        check("footprint_length", "PASS"),
        check("cycle_time", "UNKNOWN"),
        check("capacity", "UNKNOWN"),
        check("operators", "UNKNOWN"),
        check("payload", "UNKNOWN"),
        check("budget", "UNKNOWN"),
      ]),
    );
    expect(state).toBe("UNVERIFIED");
  });

  it("says UNDER_CONSIDERATION for the candidate the engineer chose", () => {
    const state = candidateState(
      assessment([check("capability", "PASS"), check("cycle_time", "UNKNOWN")]),
      { underConsideration: true },
    );
    expect(state).toBe("UNDER_CONSIDERATION");
  });

  it("reports the tally so a state can never stand alone", () => {
    const tally = checkTally(
      assessment([check("capability", "PASS"), check("cycle_time", "UNKNOWN"), check("x", "FAIL")]),
    );
    expect(tally).toEqual({ passed: 1, contradicted: 1, unconfirmable: 1 });
  });
});

describe("the vocabulary", () => {
  it("never offers 'verified' as an equipment state", () => {
    // A machine whose cycle time nobody publishes has not been verified
    // against anything.
    const states = [
      "DISCOVERED",
      "UNDER_CONSIDERATION",
      "REQUIREMENTS_MATCHED",
      "UNVERIFIED",
      "CONTRADICTED",
      "COMMERCIAL_DATA_REQUIRED",
      "STALE",
    ];
    expect(states).not.toContain("VERIFIED");
    expect(states).not.toContain("COMPATIBLE");
  });
});
