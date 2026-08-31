import type {
  CandidateAssessment,
  CompatibilityCheck,
  EquipmentRequirement,
  SourcedNumber,
} from "./equipment";
import type { ConceptStage, FactoryConceptDraft } from "./types";

/**
 * What an equipment finding IS, and whether it still answers the station in
 * front of the engineer.
 *
 * WHY THIS IS A SEPARATE MODULE
 * -----------------------------
 * Two different questions were being answered by one word on screen —
 * "selected" — and both answers were wrong in the same direction. Selecting a
 * candidate read as though the machine had been adopted into the concept, and
 * a discovery result kept rendering after the requirement it was judged
 * against had changed underneath it.
 *
 * The second is the dangerous one. Tightening a station's footprint flips a
 * published-dimension check from PASS to FAIL, so a panel that keeps showing
 * the old assessment presents equipment as a viable CANDIDATE that the
 * current requirement rejects. Nothing is fabricated — the assessment was
 * true when it was computed — which is exactly what makes it convincing.
 *
 * THE DEPENDENCY SET IS EXACT, NOT GENEROUS
 * -----------------------------------------
 * `requirement_from_concept` reads nine things off the stage plus one line
 * preference, and nothing else — not the production target, not the shift
 * pattern, not the project budget. Fingerprinting more than it reads would
 * expire equipment evidence when somebody changed the shift pattern, which
 * teaches engineers to ignore the badge. Fingerprinting less would leave the
 * silent reuse in place. See docs/EQUIPMENT_STATE_AUDIT.md §1.
 *
 * NOTHING HERE RE-DERIVES A REQUIREMENT. The backend owns that rule. This
 * module compares the bounds the backend SAID it used against the values the
 * concept holds now — a value comparison, not a second copy of the
 * derivation.
 */

/** The states an equipment finding can be in. */
export type EquipmentState =
  /** A source published this record and it declares the capability. */
  | "DISCOVERED"
  /** The engineer put it on the table for this station. Not adopted, not bought, not proven. */
  | "UNDER_CONSIDERATION"
  /** Every requirement that COULD be checked against published data passed,
   * and at least one was actually checked. */
  | "REQUIREMENTS_MATCHED"
  /** Something the station requires cannot be confirmed from published data.
   * Not a failure — an absence. */
  | "UNVERIFIED"
  /** A published value contradicts a requirement. */
  | "CONTRADICTED"
  /** No published price; a quote is needed before this can be compared on cost. */
  | "COMMERCIAL_DATA_REQUIRED"
  /** The engineering requirements moved after this finding was produced. */
  | "STALE";

/** The badge, as short as it can be without becoming a claim. */
export const EQUIPMENT_STATE_LABEL: Record<EquipmentState, string> = {
  DISCOVERED: "Candidate",
  UNDER_CONSIDERATION: "Under consideration",
  REQUIREMENTS_MATCHED: "Requirement matched",
  UNVERIFIED: "Not verified",
  CONTRADICTED: "Constraint mismatch",
  COMMERCIAL_DATA_REQUIRED: "Commercial data required",
  STALE: "Stale",
};

/** What the badge means, in one sentence, next to the badge. */
export const EQUIPMENT_STATE_NOTE: Record<EquipmentState, string> = {
  DISCOVERED:
    "A source publishes this record and it declares the required capability. Nothing has been checked against this station yet.",
  UNDER_CONSIDERATION:
    "Recorded by an engineer as a machine to consider for this station. Not adopted, not purchased, and its cycle time is not proven.",
  REQUIREMENTS_MATCHED:
    "Matches the required capability. Application-specific parameters still need supplier or engineering confirmation.",
  UNVERIFIED:
    "Something this station requires is not published, so it could not be checked either way. An absence, not a failure.",
  CONTRADICTED:
    "A published value contradicts a requirement this station states. Read the mismatch before considering it further.",
  COMMERCIAL_DATA_REQUIRED:
    "Every engineering bound that could be checked passed. No price is published, so this cannot yet be compared on cost.",
  STALE:
    "This station's requirements changed after this candidate was judged. The assessment answers the previous requirement.",
};

// The dependency fingerprint

/** One bound, named the same way on both sides of the comparison. */
export interface BoundValue {
  field: string;
  label: string;
  unit: string | null;
  value: number | string | null;
}

/** The bounds the backend reported it judged candidates against. */
export function recordedBounds(requirement: EquipmentRequirement): BoundValue[] {
  const n = (field: string, label: string, unit: string | null, v: SourcedNumber): BoundValue => ({
    field,
    label,
    unit,
    value: v?.value ?? null,
  });
  return [
    { field: "station_id", label: "Station", unit: null, value: requirement.station_id },
    {
      field: "process_type",
      label: "Process",
      unit: null,
      value: requirement.process_category,
    },
    n("cycle_time", "Cycle time", "s", requirement.max_cycle_time_seconds),
    n("capacity", "Capacity", null, requirement.required_capacity),
    n("operators_required", "Operators", null, requirement.operator_requirement),
    n("width", "Footprint width", "m", requirement.max_width_m),
    n("length", "Footprint length", "m", requirement.max_length_m),
    n("purchase_cost", "Station budget", "€", requirement.budget_limit),
  ];
}

/** The same bounds as the concept holds them NOW. */
export function currentBounds(
  draft: FactoryConceptDraft,
  stationId: string,
): BoundValue[] | null {
  const stage: ConceptStage | undefined = draft.stages.find((s) => s.id === stationId);
  if (!stage) return null;

  const n = (field: string, label: string, unit: string | null, v: SourcedNumber): BoundValue => ({
    field,
    label,
    unit,
    value: v?.value ?? null,
  });
  return [
    { field: "station_id", label: "Station", unit: null, value: stage.id },
    { field: "process_type", label: "Process", unit: null, value: stage.process_type },
    n("cycle_time", "Cycle time", "s", stage.cycle_time),
    n("capacity", "Capacity", null, stage.capacity),
    n("operators_required", "Operators", null, stage.operators_required),
    n("width", "Footprint width", "m", stage.width),
    n("length", "Footprint length", "m", stage.length),
    n("purchase_cost", "Station budget", "€", stage.purchase_cost),
  ];
}

/** One bound that moved, in the words the engineer will read. */
export interface BoundChange {
  field: string;
  description: string;
}

function show(bound: BoundValue): string {
  if (bound.value === null) return "not established";
  if (typeof bound.value === "string") return bound.value;
  return bound.unit ? `${bound.value} ${bound.unit}` : String(bound.value);
}

/** Which requirement bounds have moved since this finding was produced. */
export function boundChanges(
  recorded: BoundValue[],
  current: BoundValue[] | null,
): BoundChange[] {
  if (current === null) {
    return [
      {
        field: "station_id",
        description: "This station is no longer part of the concept.",
      },
    ];
  }

  const byField = new Map(current.map((b) => [b.field, b]));
  const changes: BoundChange[] = [];
  for (const before of recorded) {
    const after = byField.get(before.field);
    if (!after) continue;
    if (before.value === after.value) continue;
    changes.push({
      field: before.field,
      description: `${before.label}: ${show(before)} → ${show(after)}`,
    });
  }
  return changes;
}

/** Is this finding still evidence about the station as it now stands? */
export function isStale(requirement: EquipmentRequirement, draft: FactoryConceptDraft): boolean {
  return boundChanges(recordedBounds(requirement), currentBounds(draft, requirement.station_id))
    .length > 0;
}

// Per-candidate state

/** Checks that are about money rather than about physics. */
const COMMERCIAL_FIELDS = new Set(["budget"]);

function isCommercial(check: CompatibilityCheck): boolean {
  return COMMERCIAL_FIELDS.has(check.field);
}

/** What one candidate's assessment amounts to. */
export function candidateState(
  assessment: CandidateAssessment,
  options: { stale?: boolean; underConsideration?: boolean } = {},
): EquipmentState {
  if (options.stale) return "STALE";

  const checks = assessment.compatibility.checks;
  if (checks.some((c) => c.status === "FAIL")) return "CONTRADICTED";

  const engineeringUnknown = checks.some((c) => c.status === "UNKNOWN" && !isCommercial(c));
  if (engineeringUnknown) {
    return options.underConsideration ? "UNDER_CONSIDERATION" : "UNVERIFIED";
  }

  const commercialUnknown = checks.some((c) => c.status === "UNKNOWN" && isCommercial(c));
  if (commercialUnknown) return "COMMERCIAL_DATA_REQUIRED";

  const checkedSomething = checks.some((c) => c.status === "PASS");
  if (!checkedSomething) return options.underConsideration ? "UNDER_CONSIDERATION" : "DISCOVERED";

  return "REQUIREMENTS_MATCHED";
}

/** How many requirements were genuinely checked, and how many could not be. */
export function checkTally(assessment: CandidateAssessment): {
  passed: number;
  contradicted: number;
  unconfirmable: number;
} {
  const checks = assessment.compatibility.checks;
  return {
    passed: checks.filter((c) => c.status === "PASS").length,
    contradicted: checks.filter((c) => c.status === "FAIL").length,
    unconfirmable: checks.filter((c) => c.status === "UNKNOWN").length,
  };
}
