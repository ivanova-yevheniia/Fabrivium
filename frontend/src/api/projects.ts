import { apiDelete, apiGet, apiPost, apiPut } from "./client";
import type { Factory, FactoryLayout, FactoryConceptDraft, StrategyArenaResult, UserCostInput } from "./types";
import type { CoverageReport, ManufacturingProcessDraft, ProductUnderstanding } from "./product";
import type { EquipmentSelectionMetadata } from "./handoff";

/** P0 — the project workspace. */

/** An input family with its own revision. */
export type Channel =
  | "PRODUCT_SOURCE"
  | "PRODUCT_FACTS"
  | "PROCESS"
  | "COVERAGE_LINKS"
  | "SIMULATION_INPUTS"
  | "COMMERCIAL"
  | "LAYOUT"
  | "EQUIPMENT";

/** Something Fabrivium produced and may show as evidence. */
export type Artifact =
  | "PRODUCT_FACTS"
  | "PROCESS_PROPOSAL"
  | "REQUIREMENT_COVERAGE"
  | "CONCEPT"
  | "SIMULATION_VERIFICATION"
  | "STRATEGIES"
  | "SELECTED_PLAN"
  | "EQUIPMENT_REQUIREMENTS"
  | "COMMERCIAL_COMPARISON"
  | "LAYOUT_VALIDATION"
  | "SIEMENS_HANDOFF";

/** The only three things the UI may say about a piece of evidence. */
export type ArtifactStatus = "CURRENT" | "STALE" | "UNVERIFIED";

export interface StaleArtifact {
  artifact: Artifact;
  status: ArtifactStatus;
  changed_channels: Channel[];
  stale_parents: Artifact[];
  /** "Screw fastening — cycle time: 48 → 44". */
  reasons: string[];
  /** The precise action, not a generic "refresh". */
  action: string;
}

export interface StaleReport {
  stale: StaleArtifact[];
  current: Artifact[];
  unverified: Artifact[];
  summary: string;
}

export const EMPTY_STALE_REPORT: StaleReport = {
  stale: [],
  current: [],
  unverified: [],
  summary: "Nothing has been verified yet.",
};

export interface ProductSlice {
  name: string;
  description: string;
  from_example: boolean;
  understanding: ProductUnderstanding | null;
  understanding_model_used: boolean;
}

export interface ProcessSlice {
  draft: ManufacturingProcessDraft | null;
  coverage: CoverageReport | null;
}

export interface ConceptSlice {
  draft: FactoryConceptDraft | null;
  factory: Factory | null;
  product_id: string | null;
  layout: FactoryLayout | null;
  verified_from: FactoryConceptDraft | null;
}

export interface ResultsSlice {
  arena: StrategyArenaResult | null;
  selected_strategy_id: string | null;
  explore_requests: string[];
}

/** Commercial facts the engineer established — an input, not a result (G13). */
export interface CommercialSlice {
  established_costs: UserCostInput[];
}

export interface ChangeEntry {
  seq: number;
  channel: Channel;
  description: string;
}

export interface Stamp {
  revisions: Record<string, number>;
}

/** Where in the workspace the engineer was. A route, not a scroll position. */
export type ProjectStage = "PRODUCT" | "CONCEPT" | "WORKSPACE";

export interface ProjectState {
  product: ProductSlice;
  process: ProcessSlice;
  requirements: { text: string };
  concept: ConceptSlice;
  results: ResultsSlice;
  /** Optional: a project saved before G13 has no commercial slice, which
   * reads as "nothing established yet". */
  commercial?: CommercialSlice;
  layout: { applied: Record<string, FactoryLayout> };
  equipment: { selections: Record<string, EquipmentSelectionMetadata> };
  is_example: boolean;
  stage: ProjectStage;

  /** Server-owned. */
  revisions: Record<string, number>;
  evidence: Record<string, Stamp>;
  history: ChangeEntry[];
  /** Artifacts produced since the last save. */
  produced: Artifact[];
  /** Artifacts explicitly discarded. */
  withdrawn: Artifact[];
}

export interface ProjectDocument {
  schema_version: number;
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  state: ProjectState;
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  product_name: string;
  is_example: boolean;
}

export interface ProjectResponse {
  project: ProjectDocument;
  staleness: StaleReport;
}

/** A brand-new project's state. */
export function emptyProjectState(): ProjectState {
  return {
    product: {
      name: "",
      description: "",
      from_example: false,
      understanding: null,
      understanding_model_used: false,
    },
    process: { draft: null, coverage: null },
    requirements: { text: "" },
    concept: { draft: null, factory: null, product_id: null, layout: null, verified_from: null },
    results: { arena: null, selected_strategy_id: null, explore_requests: [] },
    commercial: { established_costs: [] },
    layout: { applied: {} },
    equipment: { selections: {} },
    is_example: false,
    stage: "PRODUCT",
    revisions: {},
    evidence: {},
    history: [],
    produced: [],
    withdrawn: [],
  };
}

export function createProject(name: string, state?: ProjectState): Promise<ProjectResponse> {
  return apiPost<ProjectResponse>("/projects", { name, state: state ?? null });
}

export function listProjects(): Promise<{ projects: ProjectSummary[] }> {
  return apiGet<{ projects: ProjectSummary[] }>("/projects");
}

export function openProject(projectId: string): Promise<ProjectResponse> {
  return apiGet<ProjectResponse>(`/projects/${projectId}`);
}

export function saveProject(
  projectId: string,
  state: ProjectState,
  name?: string,
): Promise<ProjectResponse> {
  return apiPut<ProjectResponse>(`/projects/${projectId}`, { state, name: name ?? null });
}

export function deleteProject(projectId: string): Promise<{ status: string }> {
  return apiDelete<{ status: string }>(`/projects/${projectId}`);
}

/** What a state WOULD report as stale, without saving it. */
export function evaluateStaleness(state: ProjectState): Promise<StaleReport> {
  return apiPost<StaleReport>("/projects/staleness", state);
}

/** Status of one artifact, read from a report rather than guessed at. */
export function statusOf(report: StaleReport | null, artifact: Artifact): ArtifactStatus {
  if (!report) return "UNVERIFIED";
  if (report.stale.some((item) => item.artifact === artifact)) return "STALE";
  if (report.current.includes(artifact)) return "CURRENT";
  return "UNVERIFIED";
}

export function staleEntry(report: StaleReport | null, artifact: Artifact): StaleArtifact | null {
  return report?.stale.find((item) => item.artifact === artifact) ?? null;
}
