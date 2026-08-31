import { apiPost } from "./client";
import type { FactoryConceptDraft, ConceptResponse, SourcedNumber } from "./types";

/** Phase 18 — uncertainty-aware concept assistance. */

export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type EstimateMethod =
  | "DERIVED"
  | "REFERENCE_DATA"
  /** A language model structured the description into a range. */
  | "LANGUAGE_MODEL"
  /** Composed from Fabrivium's documented reference bands (Phase 18B). */
  | "LOCAL_HEURISTIC"
  | "ENGINEER";

export interface EstimatedRange {
  low: number;
  working_value: number;
  high: number;
  unit: string;
  confidence: Confidence;
  method: EstimateMethod;
  /** What the number rests on. An estimate without one is a guess. */
  basis: string;
  model_name: string | null;
  /** How many times the operation was assumed to happen per unit when this
   * range was composed — propagated from the reviewed process, typed by the
   * engineer, or read out of the description. Travels back with the
   * acceptance so the station keeps the assumption it was estimated under
   * (G11). Absent where the count played no part. */
  operations_per_unit?: number | null;
}

export interface EstimateUnavailable {
  reason: string;
  retryable: boolean;
}

/** How many of the concept's values came from where. */
export interface ProvenanceCounts {
  customer_facts: number;
  manufacturer_facts: number;
  engineering_estimates: number;
  example_data: number;
  derived: number;
  planning_defaults: number;
  unknown: number;
  engineer_decisions: number;
  documents: number;
  measured: number;
  external_data: number;
  simulated: number;
}

export interface ConceptReadiness {
  counts: ProvenanceCounts;
  simulation_ready: boolean;
  verdict: string;
  unknown_critical: number;
  unknown_commercial: number;
  missing: string[];
  /** Definitional arithmetic — an upper bound on the average cycle, never
   * an achievable per-station time. */
  takt_seconds: SourcedNumber;
}

/** What Fabrivium still needs before it can estimate. */
export interface NeedsInformation {
  reason: string;
  questions: string[];
}

/** The description and the selected automation level disagree. */
export interface EstimateContradiction {
  message: string;
  described_as: string;
  selected_as: string;
}

export interface EstimateResult {
  /** Exactly one of these three is set. */
  estimate: EstimatedRange | null;
  /** The whole station, when one could be proposed. */
  proposal: StationAssumptionProposal | null;
  needs_information: NeedsInformation | null;
  contradiction: EstimateContradiction | null;
  /** True when the language model could not be reached and the local
   * heuristic produced the range instead. */
  fell_back: boolean;
  /** Provider-side detail for developers. Never the headline: the demo
   * does not show quota internals. */
  provider_note: string | null;
  takt_seconds: SourcedNumber;
}

export interface SweepPoint {
  value: number;
  unit: string;
  completed_units: number;
  target_units: number;
  meets_target: boolean;
  bottleneck_machine_id: string;
}

export interface SensitivityResult {
  stage_id: string;
  stage_name: string;
  parameter: string;
  unit: string;
  points: SweepPoint[];
  /** Real runs of the deterministic simulator — not samples. */
  simulations_run: number;
  monotonic: boolean;
  summary: string;
}

export interface ThresholdResult {
  stage_id: string;
  stage_name: string;
  parameter: string;
  unit: string;
  /** Null whenever no honest single number exists; `statement` says why. */
  threshold: number | null;
  target_units: number;
  simulations_run: number;
  monotonic: boolean;
  statement: string;
  requirement_value: SourcedNumber;
}

/** What the concept is made of, by provenance. No completeness score. */
export function conceptReadiness(draft: FactoryConceptDraft): Promise<ConceptReadiness> {
  return apiPost<ConceptReadiness>("/concept/readiness", { draft });
}

/** Ask the assistant for a preliminary cycle-time range. */
export function estimateCycleTime(
  draft: FactoryConceptDraft,
  stageId: string,
  input: {
    description: string;
    automation_level?: string;
    operations_per_unit?: number | null;
    part_information?: string | null;
    other_constraints?: string | null;
    /** AUTO (default) | LLM_ONLY | LOCAL_ONLY. */
    mode?: string | null;
  },
): Promise<EstimateResult> {
  return apiPost<EstimateResult>("/concept/estimate", {
    draft,
    stage_id: stageId,
    description: input.description,
    automation_level: input.automation_level ?? "UNKNOWN",
    operations_per_unit: input.operations_per_unit ?? null,
    part_information: input.part_information ?? null,
    other_constraints: input.other_constraints ?? null,
    mode: input.mode ?? null,
  });
}

/** Write an estimate's working value onto a stage, tagged as an estimate. */
export function applyEstimate(
  draft: FactoryConceptDraft,
  stageId: string,
  range: Omit<EstimatedRange, "unit"> & { unit?: string },
  /** Required before an estimate may replace a value that came from a
   * person, a document, a measurement or a manufacturer. Without it the
   * backend answers 409 and names what would have been lost — see
   * `ProtectedValueConflict`. */
  replaceExisting = false,
): Promise<ConceptResponse> {
  return apiPost<ConceptResponse>("/concept/apply-estimate", {
    draft,
    stage_id: stageId,
    low: range.low,
    working_value: range.working_value,
    high: range.high,
    basis: range.basis,
    confidence: range.confidence,
    method: range.method,
    model_name: range.model_name,
    replace_existing: replaceExisting,
  });
}

/** One value an estimate would have overwritten. */
export interface ProtectedValue {
  field: string;
  label: string;
  value: number | null;
  source: string;
  detail: string | null;
}

/** The backend's refusal to overwrite something stronger than an estimate. */
export interface ProtectedValueConflict {
  conflict: "PROTECTED_VALUE";
  /** Readable on its own, so the generic error path degrades gracefully if
   * a caller does not handle the conflict. */
  message: string;
  protected: ProtectedValue[];
}

/** Reads a 409 from either apply path, or null for any other failure. */
export function protectedValueConflict(error: unknown): ProtectedValueConflict | null {
  const candidate = error as { status?: number; detail?: unknown };
  if (candidate?.status !== 409) return null;
  const detail = candidate.detail as ProtectedValueConflict | undefined;
  if (detail?.conflict !== "PROTECTED_VALUE") return null;
  return detail;
}

/** Run the deterministic simulator once per value. A bounded sweep — not
 * sampling, and not Monte Carlo. */
export function runSensitivity(
  draft: FactoryConceptDraft,
  stageId: string,
  values?: number[],
): Promise<SensitivityResult> {
  return apiPost<SensitivityResult>("/concept/sensitivity", {
    draft,
    stage_id: stageId,
    values: values ?? null,
  });
}

/** What this parameter must achieve for the concept to meet its target. */
export function deriveThreshold(
  draft: FactoryConceptDraft,
  stageId: string,
  bounds?: { fastest?: number; slowest?: number },
): Promise<ThresholdResult> {
  return apiPost<ThresholdResult>("/concept/threshold", {
    draft,
    stage_id: stageId,
    fastest: bounds?.fastest ?? 5,
    slowest: bounds?.slowest ?? 120,
  });
}

/** Phase 18B — one station, every simulation parameter. */
export interface StationAssumptionProposal {
  stage_id: string;
  stage_name: string;
  cycle_time: EstimatedRange | null;
  /** Units in process AT THE SAME TIME — the simulator's server capacity,
   * not batch size and not buffer space. */
  capacity: EstimatedRange | null;
  /** People this station occupies while it runs. Never the size of the factory's workforce pool. */
  operators: EstimatedRange | null;
  fell_back: boolean;
  provider_note: string | null;
}

export interface AcceptAssumptionsResult {
  draft: FactoryConceptDraft;
  validation: unknown;
  /** What was actually written, so the UI reports the truth rather than what it asked for. */
  applied: string[];
}

/** Write the accepted parameters into the concept. */
export function acceptStationAssumptions(
  draft: FactoryConceptDraft,
  proposal: StationAssumptionProposal,
  acceptedFields: string[],
  /** As `applyEstimate`: accepting an assumption over a value a person is
   * accountable for takes a second, explicit act. */
  replaceExisting = false,
): Promise<AcceptAssumptionsResult> {
  return apiPost<AcceptAssumptionsResult>("/concept/accept-assumptions", {
    draft,
    proposal,
    accepted_fields: acceptedFields,
    replace_existing: replaceExisting,
  });
}
