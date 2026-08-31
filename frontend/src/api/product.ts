import { API_BASE_URL, apiPost, BackendUnavailableError, ApiError, ApiValidationError } from "./client";
import { SKILL_TRACE_HEADER, recordSkillTrace } from "./skillTrace";
import type { ConceptValidation, FactoryConceptDraft } from "./types";

/** Phase 19 — product understanding and process planning. */

export type FactStatus =
  /** Derived by a deterministic rule, with no model involved. */
  | "RULE_DERIVED"
  /** A deterministic reader found it in the supplied text and cited it. */
  | "EXTRACTED"
  /** A language model read it out of, or inferred it from, the source. */
  | "AI_INFERRED"
  /** Stated by the customer or engineer directly. */
  | "STATED"
  /** An engineer has looked at it and accepted it. */
  | "ENGINEER_VERIFIED"
  /** Sources disagree; the alternatives travel with it. */
  | "CONFLICT"
  /** Not known. Never rendered as a value. */
  | "UNKNOWN";

export interface EvidenceRef {
  document_id: string;
  document_name: string;
  page: number | null;
  quote: string | null;
}

export interface ProductFact {
  key: string;
  category: string;
  label: string;
  value: string | null;
  quantity: number | null;
  unit: string | null;
  status: FactStatus;
  confidence: string | null;
  evidence: EvidenceRef[];
  /** Only for CONFLICT: the readings that disagree. */
  alternatives: ProductFact[];
}

export interface SourceDocument {
  document_id: string;
  name: string;
  media_type: string;
  pages: number | null;
  ingested_on: string;
  /** Pages with no text layer — visual content this version does not read. */
  pages_without_text: number[];
  notes: string[];
}

export interface InformationGap {
  key: string;
  label: string;
  /** Never BLOCKS_CONCEPT_SIMULATION: the simulator reads no product fact. */
  severity: string;
  reason: string;
}

/** A sentence that reads as manufacturing work and could not be mapped. */
export interface UnresolvedSourceStatement {
  /** The document's own words, verbatim. Never paraphrased. */
  statement: string;
  evidence: EvidenceRef;
  reason: string;
}

export interface ProductUnderstanding {
  product_name: string;
  description: string;
  facts: ProductFact[];
  source_documents: SourceDocument[];
  information_gaps: InformationGap[];
  /** Sentences stating work on the product that extraction could not map. */
  unresolved_statements: UnresolvedSourceStatement[];
  /** What the SOURCE says about production rather than about the product. */
  source_production_requirements: SourceProductionRequirement[];
  interpretation_method: string;
  model_name: string | null;
}

export interface SourceProductionRequirement {
  key: string;
  label: string;
  value: string;
  quantity: number;
  quantity_secondary: number | null;
  evidence: EvidenceRef;
}

export interface UnderstandingResult {
  understanding: ProductUnderstanding;
  /** True when the language model contributed facts. */
  model_used: boolean;
  /** Developer detail. Never shown as the headline. */
  provider_note: string | null;
}

export type OperationStatus = "PROPOSED" | "ACCEPTED" | "REJECTED" | "MODIFIED";

export interface ProposedOperation {
  id: string;
  process_type: string;
  name: string;
  description: string;
  repeated_operations: number | null;
  /** Why this operation was proposed — the "why does this station exist?". */
  basis: string;
  source_fact_keys: string[];
  evidence: EvidenceRef[];
  fact_status: FactStatus;
  confidence: string;
  status: OperationStatus;
}

export interface ManufacturingProcessDraft {
  product_name: string;
  operations: ProposedOperation[];
  planner: string;
  method: string;
  model_name: string | null;
  open_questions: string[];
}

export interface BuildConceptResult {
  draft: FactoryConceptDraft;
  validation: ConceptValidation;
  /** Per-stage product context for the Station Assumption Assistant. */
  station_context: Record<string, Record<string, unknown>>;
}

/** Read product facts out of a written description. */
export function describeProduct(
  description: string,
  productName: string,
): Promise<UnderstandingResult> {
  return apiPost<UnderstandingResult>("/product/describe", {
    description,
    product_name: productName,
  });
}

/** Read product facts out of an uploaded specification. */
export async function uploadProductDocument(
  file: File,
  productName: string,
): Promise<UnderstandingResult> {
  const body = new FormData();
  body.append("file", file);
  body.append("product_name", productName);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/product/upload`, { method: "POST", body });
  } catch (cause) {
    throw new BackendUnavailableError(cause);
  }
  // The multipart path bypasses the shared client, so it records the trace
  // itself. Without this, the one upload in the product would be the one
  // request whose skills went unreported.
  recordSkillTrace(response.headers.get(SKILL_TRACE_HEADER), "/product/upload");

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json())?.detail;
    } catch {
      // Non-JSON error body — leave the detail undefined.
    }
    if (response.status === 422) throw new ApiValidationError(detail);
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as UnderstandingResult;
}

/** Propose the manufacturing operations the product facts imply. */
export function planProcess(
  understanding: ProductUnderstanding,
): Promise<{ draft: ManufacturingProcessDraft }> {
  return apiPost<{ draft: ManufacturingProcessDraft }>("/product/plan-process", { understanding });
}

/** Turn an accepted process into the existing FactoryConceptDraft. */
export function buildConceptFromProduct(
  understanding: ProductUnderstanding,
  process: ManufacturingProcessDraft,
  requirementsBrief: string,
  name?: string,
): Promise<BuildConceptResult> {
  return apiPost<BuildConceptResult>("/product/build-concept", {
    understanding,
    process,
    requirements_brief: requirementsBrief,
    name: name ?? null,
  });
}

/** The bundled competition reference specification. */
export function referenceProduct(): Promise<{
  name: string;
  text: string;
  classification: string;
}> {
  return fetch(`${API_BASE_URL}/product/reference`).then((r) => r.json());
}

// Requirement coverage and engineer process edits

export type CoverageStatus = "ADDRESSED" | "UNRESOLVED" | "NOT_A_REQUIREMENT";
export type CoverageSeverity = "CRITICAL" | "EXPECTED" | "INFORMATIONAL";

export interface RequirementCoverageItem {
  fact_key: string;
  label: string;
  value: string | null;
  status: CoverageStatus;
  severity: CoverageSeverity;
  /** Operations citing this requirement. Empty when unresolved. */
  addressed_by: string[];
  /** The source sentences, so the requirement can be checked without reopening the document. */
  quotes: string[];
}

export interface CoverageReport {
  items: RequirementCoverageItem[];
  summary: string;
  complete: boolean;
  /** A requirement the source states explicitly, with nothing answering it, blocks approval. */
  approval_blocked: boolean;
  unresolved_count: number;
  critical_unresolved_count: number;
}

export interface ProcessDraftResult {
  draft: ManufacturingProcessDraft;
  /** Recomputed on every edit, so the consequence of the edit arrives with
   * the edit rather than having to be looked up. */
  coverage: CoverageReport;
}

export function requirementCoverage(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
): Promise<CoverageReport> {
  return apiPost<CoverageReport>("/product/requirement-coverage", { understanding, draft });
}

/** Add an operation the engineer decided the process needs. */
export function addOperation(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation: {
    name: string;
    process_type: string;
    basis: string;
    source_fact_keys?: string[];
    repeated_operations?: number | null;
    position?: number | null;
  },
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/add-operation", {
    understanding,
    draft,
    ...operation,
  });
}

export function editOperation(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation_id: string,
  changes: {
    name?: string;
    process_type?: string;
    repeated_operations?: number;
    /** What the operation DOES. */
    description?: string;
    basis?: string;
  },
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/edit-operation", {
    understanding,
    draft,
    operation_id,
    ...changes,
  });
}

export function removeOperation(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation_id: string,
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/remove-operation", {
    understanding,
    draft,
    operation_id,
  });
}

/** Record that an existing operation satisfies these source requirements. */
export function linkRequirement(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation_id: string,
  fact_keys: string[],
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/link-requirement", {
    understanding,
    draft,
    operation_id,
    fact_keys,
  });
}


/** Bring a rejected operation back into the route. */
export function restoreOperation(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation_id: string,
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/restore-operation", {
    understanding,
    draft,
    operation_id,
  });
}

/** Record that an operation does NOT satisfy these source requirements. */
export function unlinkRequirement(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  operation_id: string,
  fact_keys: string[],
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/unlink-requirement", {
    understanding,
    draft,
    operation_id,
    fact_keys,
  });
}

/** Put the route in the order the engineer chose. */
export function reorderOperations(
  understanding: ProductUnderstanding,
  draft: ManufacturingProcessDraft,
  ordered_ids: string[],
): Promise<ProcessDraftResult> {
  return apiPost<ProcessDraftResult>("/product/process/reorder", {
    understanding,
    draft,
    ordered_ids,
  });
}
