import { apiPost } from "./client";
import type { EstimatedRange } from "./uncertainty";
import type {
  ConceptBuildResponse,
  ConceptResponse,
  ConceptValidation,
  FactoryConceptDraft,
  ValueSource,
} from "./types";

/** Phase 13 factory-concept endpoints. */

/** Structure a customer brief into a concept draft. */
export function conceptFromBrief(brief: string, name?: string): Promise<ConceptResponse> {
  return apiPost<ConceptResponse>("/concept/from-brief", { brief, name: name ?? null });
}

/** Fill missing ENGINEERING values from the bundled demo dataset. */
export function applyExampleData(draft: FactoryConceptDraft): Promise<ConceptResponse> {
  return apiPost<ConceptResponse>("/concept/example-data", { draft });
}

/** What still blocks simulation, and what is merely missing. */
export function validateConcept(draft: FactoryConceptDraft): Promise<ConceptValidation> {
  return apiPost<ConceptValidation>("/concept/validate", { draft });
}

/** Convert a validated concept into a Factory plus an initial layout. */
export function buildConcept(draft: FactoryConceptDraft): Promise<ConceptBuildResponse> {
  return apiPost<ConceptBuildResponse>("/concept/build", { draft });
}

// Engineering input resolution — real data first

/** What actually depends on one input. Not a priority — a consequence. */
export type Necessity =
  | "BLOCKS_SIMULATION"
  | "AFFECTS_LAYOUT"
  | "COMMERCIAL_ONLY"
  | "HAS_DEFAULT";

/** A legitimate way to obtain ONE particular quantity. */
export type ResolutionAction =
  | "ENGINEER_INPUT"
  | "ESTIMATE"
  | "EXTERNAL_DATA"
  | "ENTER_QUOTE"
  | "USE_EXAMPLE_DATA"
  | "LEAVE_UNKNOWN";

export interface ResolvableInput {
  key: string;
  label: string;
  unit: string | null;
  value: number | null;
  source: ValueSource;
  detail: string | null;
  necessity: Necessity;
  consequence: string;
  actions: ResolutionAction[];
  stage_id: string | null;
  /** Absent and only obtainable commercially. Render as "quote required", never as €0. */
  quote_required: boolean;
  resolved: boolean;
  /** The estimate contract behind this value, when the value currently IS
   * an estimate: method, basis, range and confidence. Null for every other
   * provenance — including after an override, because the server retires
   * the range at that point rather than leaving it to describe a number it
   * no longer produced. */
  estimate: EstimatedRange | null;
  /** One line naming the estimate an override replaced, when one did. */
  superseded: string | null;
}

export interface ComputedValue {
  key: string;
  label: string;
  unit: string | null;
  value: number | null;
  /** The arithmetic, written out. Shown so nobody has to trust the number. */
  formula: string;
  blocked_by: string | null;
  source: ValueSource;
}

export interface ResolutionPlan {
  inputs: ResolvableInput[];
  computed: ComputedValue[];
  blocking_unresolved: number;
  ready_to_simulate: boolean;
}

/** Every input this concept needs, and everything it works out itself. */
export function resolutionPlan(draft: FactoryConceptDraft): Promise<ResolutionPlan> {
  return apiPost<ResolutionPlan>("/concept/resolution-plan", { draft });
}

/** Resolve ONE value, leaving every other value exactly as it was. */
export function resolveInput(
  draft: FactoryConceptDraft,
  key: string,
  value: number | null,
  source: ValueSource,
  detail?: string | null,
): Promise<ConceptResponse> {
  return apiPost<ConceptResponse>("/concept/resolve-input", {
    draft,
    key,
    value,
    source,
    detail: detail ?? null,
  });
}

export interface BufferPoint {
  size: number;
  completed_units: number;
  target_units: number;
  meets_target: boolean;
  limiting_stage_id: string | null;
  average_level: number | null;
  /** Seconds an upstream station finished a unit and could not hand it on. */
  upstream_blocked_seconds: number;
  blocking_observed: boolean;
}

export interface BufferSensitivity {
  points: BufferPoint[];
  simulations_run: number;
  /** True when every size produced the same output — the finding that lets
   * an engineer stop thinking about buffers for this target. */
  indifferent: boolean;
  smallest_size_meeting_target: number | null;
  summary: string;
}

/** Ask the simulator whether buffer size matters on this line. */
export function bufferSensitivity(draft: FactoryConceptDraft): Promise<BufferSensitivity> {
  return apiPost<BufferSensitivity>("/concept/buffer-sensitivity", { draft });
}

export interface BulkResolveResult {
  draft: FactoryConceptDraft;
  validation: ConceptValidation;
  filled: string[];
  /** Keys the dataset CREATED (it wires buffers between stages) rather than filled. */
  added: string[];
  /** Keys left alone because a person had already decided them. */
  protected: string[];
  unavailable: string[];
}

/** Fill everything still unresolved from the bundled demo dataset. */
export function useExampleDataForUnresolved(
  draft: FactoryConceptDraft,
): Promise<BulkResolveResult> {
  return apiPost<BulkResolveResult>("/concept/use-example-data-for-unresolved", { draft });
}

// Change impact

export interface InputChangeDescription {
  key: string;
  label: string;
  kind: "RESOLVED" | "CLEARED" | "VALUE_CHANGED" | "SOURCE_CHANGED" | "ADDED" | "REMOVED";
  before: number | null;
  after: number | null;
  before_source: string | null;
  after_source: string | null;
  description: string;
}

export interface ChangeImpactResult {
  changes: InputChangeDescription[];
  /** Results that may no longer be shown as current. */
  stale: string[];
  /** Results the change provably cannot have affected. */
  unaffected: string[];
  summary: string;
  explanation: string;
}

/** What a changed input invalidates. */
export function changeImpact(
  before: FactoryConceptDraft,
  after: FactoryConceptDraft,
): Promise<ChangeImpactResult> {
  return apiPost<ChangeImpactResult>("/concept/change-impact", { before, after });
}
