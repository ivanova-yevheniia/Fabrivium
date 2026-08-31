import type {
  BranchComparison,
  ConversationSession,
  Factory,
  FactoryLayout,
  LayoutValidationResult,
  PlanningExplanation,
  PlanningProvenance,
  PlanningSessionState,
  RequirementsParseResult,
  SimulationTrace,
  StrategyArenaResult,
  StrategyComparison,
  StrategyQueryAnswer,
  UserCostInput,
  ConceptValidation,
  FactoryConceptDraft,
} from "../api/types";
import type { CoverageReport, ManufacturingProcessDraft, ProductUnderstanding } from "../api/product";
import type { EquipmentSelectionMetadata } from "../api/handoff";
import type { Artifact, ProjectSummary, StaleReport } from "../api/projects";

/** Phase 7C — the full verified result of one branch, cached client-side. */
export interface BranchResult {
  session: PlanningSessionState;
  explanation: PlanningExplanation | null;
}

/** Which stage of the plan is currently selected for the workspace/KPI
 * panel — "baseline" and "final" are always available; a number selects
 * PlanningIteration.iteration_index (Phase 6A section 10). */
export type IterationSelection = "baseline" | "final" | number;

/** Phase 6B section 7 — explicit edit modes. */
export type EditMode = "VIEW" | "EDIT_LAYOUT";

/** Phase 6C section 10 — 2D/3D is a VIEW choice only; it never forks
 * selection/edit state (both views read the same AppState). */
/** Stable string key for an `IterationSelection`, so applied layouts can be
 * stored per stage in a plain record. */
export function stageLayoutKey(selection: IterationSelection): string {
  return String(selection);
}

export type ViewMode = "2D" | "3D";

/** Phase 9A — a PRESENTATION choice only, exactly like ViewMode: both
 * levels read the same AppState/AppContext, never a parallel data path.
 * EXECUTIVE is the default (competition/demo) layout; ENGINEERING is the
 * pre-Phase-9A AppShell, unchanged, for technical inspection. */
export type ViewLevel = "EXECUTIVE" | "ENGINEERING";

/** Phase 12 §8 — which engineering context is on screen. */
export type EngineeringTab = "FACTORY" | "SIMULATION" | "PLAN_ANALYSIS";

/** Phase 13 — how the session started, and therefore what the entry screen shows. */
export type StartMode =
  /** P0 — the landing page. */
  | "PROJECTS"
  //: A project is open and nothing has been chosen inside it yet.
  | "CHOOSING"
  /** Phase 19 — start from the product rather than from a factory. */
  | "PRODUCT_FIRST"
  //: Building a concept from a customer brief.
  | "CONCEPT_BUILDER"
  //: A factory is loaded (demo, or one the builder produced).
  | "FACTORY_LOADED";

/** Phase 13 — the concept-builder slice. */
export interface ConceptState {
  draft: FactoryConceptDraft | null;
  validation: ConceptValidation | null;
  /** The layout generated for the concept, kept so the builder can preview it before conversion. */
  generatedLayout: FactoryLayout | null;
  building: boolean;
  extracting: boolean;
  error: AppError | null;
}

export const initialConceptState: ConceptState = {
  draft: null,
  validation: null,
  generatedLayout: null,
  building: false,
  extracting: false,
  error: null,
};

export interface AppError {
  kind: "network" | "validation" | "api" | "unknown";
  message: string;
}

// P0 — the product half of a project, and the project itself

/** Everything the product route knows. */
export interface ProductWorkState {
  /** EMPTY for a new manual project. */
  name: string;
  /** The engineer's own description, or the text of the uploaded document. */
  description: string;
  /** True when the description came from the bundled example specification. */
  fromExample: boolean;
  understanding: ProductUnderstanding | null;
  /** True when the language model contributed facts. */
  modelUsed: boolean;
  process: ManufacturingProcessDraft | null;
  coverage: CoverageReport | null;
  /** How much, in what space, with which workforce. Separate from the product. */
  requirementsText: string;
  /** True when the engineer reopened product entry from a later step. */
  editing: boolean;
  busy: boolean;
  error: string | null;
}

export const initialProductWorkState: ProductWorkState = {
  name: "",
  description: "",
  fromExample: false,
  understanding: null,
  modelUsed: false,
  process: null,
  coverage: null,
  requirementsText: "",
  editing: false,
  busy: false,
  error: null,
};

/** Where the autosave loop stands. */
export type SaveStatus =
  //: No project open, or nothing has changed since it was loaded.
  | "IDLE"
  //: Changed, and a save is scheduled.
  | "DIRTY"
  | "SAVING"
  | "SAVED"
  //: The last save failed. Shown, never swallowed: an engineer who thinks
  //: their work is stored and is not has been actively misled.
  | "ERROR";

/** The open project, and the workspace around it. */
export interface ProjectSessionState {
  /** Null on the landing page. */
  id: string | null;
  name: string;
  createdAt: string | null;
  updatedAt: string | null;
  schemaVersion: number | null;
  isExample: boolean;

  saveStatus: SaveStatus;
  saveError: string | null;

  /** What may still be shown as current. */
  staleness: StaleReport | null;

  /** The recent-projects list on the landing page. */
  recent: ProjectSummary[];
  listing: boolean;
  opening: boolean;
  error: string | null;

  /** Artifacts computed since the last save. */
  produced: Artifact[];
}

export const initialProjectSessionState: ProjectSessionState = {
  id: null,
  name: "",
  createdAt: null,
  updatedAt: null,
  schemaVersion: null,
  isExample: false,
  saveStatus: "IDLE",
  saveError: null,
  staleness: null,
  recent: [],
  listing: false,
  opening: false,
  error: null,
  produced: [],
};

/** Phase 8C — playback speed multipliers, layered on top of the default
 * demo compression (section 17): "1x" already compresses a full shift into
 * ~30 real seconds, never real-time wall-clock. */
export type PlaybackSpeed = 1 | 5 | 20;

/** Phase 8C section 15/16/28 — one playback trace, always for an EXACT
 * timeline stage (`stageKey` mirrors IterationSelection). Deliberately NOT
 * auto-refetched on every stage change: a mismatch between `stageKey` and
 * the currently selected timeline stage is surfaced explicitly in the UI
 * rather than silently resolved, so playback/KPI/2D/3D can never disagree
 * without it being visible (the exact bug class section 28 calls out). */
export interface PlaybackState {
  active: boolean;
  stageKey: IterationSelection | null;
  trace: SimulationTrace | null;
  loading: boolean;
  error: AppError | null;
  playing: boolean;
  speed: PlaybackSpeed;
  /** Simulated seconds since horizon start, 0..trace.horizon_seconds. */
  simTime: number;
}

export const initialPlaybackState: PlaybackState = {
  active: false,
  stageKey: null,
  trace: null,
  loading: false,
  error: null,
  playing: false,
  speed: 1,
  simTime: 0,
};

/** WHY THE RECOMMENDATION CHANGED, after a refinement. */
export interface RefinementTrace {
  /** The sentence the engineer typed for this turn. */
  request: string;
  /** The plan recommended BEFORE this turn, null if there was none. */
  previousPlan: string | null;
  /** The plan recommended after it. */
  currentPlan: string | null;
  /** True when the two differ — the only case worth calling a change. */
  changed: boolean;
}

export interface AppState {
  factory: Factory | null;
  layout: FactoryLayout | null;
  productId: string | null;

  planningRequestText: string;
  parseResult: RequirementsParseResult | null;
  /** Every exploration turn so far, oldest first. */
  exploreRequests: string[];
  session: PlanningSessionState | null;
  explanation: PlanningExplanation | null;
  /** Phase 7A — where the last plan run's requirements/planning/explanation
   * stages actually came from. null before any plan has run. Never affects
   * how KPIs are labeled (those stay VERIFIED regardless — see
   * PlanningProvenance's own doc comment). */
  provenance: PlanningProvenance | null;

  selectedIteration: IterationSelection;
  selectedMachineId: string | null;

  factoryLoading: boolean;
  planLoading: boolean;
  error: AppError | null;

  // Phase 6B: layout editor state (section 8)
  editMode: EditMode;
  /** Working copy of the currently-edited stage's layout. */
  draftLayout: FactoryLayout | null;
  /** Last POST /layout/validate result for draftLayout; null until Validate
   * has been run at least once since the draft last changed. */
  layoutValidation: LayoutValidationResult | null;
  layoutValidating: boolean;
  /** True iff draftLayout differs from the verified snapshot it was seeded
   * from — drives the "uncommitted draft" warning on stage switch. */
  isDirty: boolean;
  /** Set when the user tries to switch timeline stage while isDirty — the
   * switch is held pending an explicit confirm/cancel (section 11). */
  pendingIterationSelection: IterationSelection | null;

  /** Phase 12.1 — layouts the user edited and APPLIED, keyed by the stage
   * they were applied to (see `stageLayoutKey`).
   *
   * Defect this fixes: `APPLY_DRAFT` wrote the committed geometry to
   * `state.layout` only. Once a planning session exists, every layout
   * consumer reads `stage.snapshot.layout` instead — the verified snapshot
   * the simulator produced — so pressing Apply appeared to succeed and the
   * machines immediately snapped back to their old positions. The edit was
   * never lost, it was simply never read.
   *
   * Why an overlay rather than writing into the snapshot: a
   * `PlanningStateSnapshot` is the exact state a simulation ran on, and
   * overwriting part of it would break that guarantee. Keeping the applied
   * geometry beside the snapshot preserves it while still showing the user
   * what they committed.
   *
   * This is sound because placement does not feed the simulator:
   * `run_simulation(factory, product_id)` takes no layout, so moving a
   * machine cannot invalidate a verified KPI. Placement is checked by its
   * own backend validator (`POST /layout/validate`), and APPLY_DRAFT
   * already refuses to commit a draft with ERROR violations.
   *
   * Cleared whenever a new session arrives: fresh snapshots carry their own
   * geometry and may contain machines this layout has never heard of. */
  appliedLayouts: Record<string, FactoryLayout>;

  // Phase 6C: 3D view mode
  viewMode: ViewMode;

  // Phase 9A: presentation level
  viewLevel: ViewLevel;

  // Phase 12: engineering sub-context
  engineeringTab: EngineeringTab;

  // Phase 13: factory concept builder
  startMode: StartMode;
  concept: ConceptState;

  // P0: the project workspace
  /** The open project and its save/staleness bookkeeping. */
  project: ProjectSessionState;
  /** The product half of the project, lifted out of ProductStart so it can
   * be reopened, edited and persisted. */
  product: ProductWorkState;
  /** Equipment recorded as UNDER CONSIDERATION, per station. */
  equipmentSelections: Record<string, EquipmentSelectionMetadata>;

  // Phase 7C: conversational copilot
  /** Null until the first message is sent. */
  conversation: ConversationSession | null;
  /** branch_id -> that branch's full verified result (see BranchResult). */
  branchResults: Record<string, BranchResult>;
  /** Which branch the workspace/KPI/timeline are currently showing. */
  selectedBranchId: string | null;
  conversationSending: boolean;
  /** Result of the last "compare" action; null when the card is closed. */
  branchComparison: BranchComparison | null;
  comparing: boolean;

  /** The concept draft the CURRENT verified results were computed from. */
  verifiedFrom: FactoryConceptDraft | null;

  /** Results that no longer answer the current inputs. */
  staleResults: StaleResults | null;

  // Phase 8B: optimization arena
  /** The verified options currently on screen. null before exploring. */
  arena: StrategyArenaResult | null;
  /** strategy_id -> the EXACT verified session the backend returned for it. */
  strategySessions: Record<string, PlanningSessionState>;
  selectedStrategyId: string | null;
  exploring: boolean;
  /** Last deterministic strategy comparison; null when the card is closed. */
  strategyComparison: StrategyComparison | null;
  /** The strategy the NEXT compare will use as its left-hand side. */
  comparePickId: string | null;
  /** Answer to the last follow-up question about the options (section 15). */
  strategyAnswer: StrategyQueryAnswer | null;
  /** Why the recommendation on screen differs from the one before it. */
  refinementTrace: RefinementTrace | null;
  askingStrategy: boolean;

  /** COMMERCIAL FACTS THE ENGINEER ESTABLISHED, kept apart from the arena. */
  establishedCosts: UserCostInput[];

  // Phase 8C: playback
  playback: PlaybackState;
  /** Imperative camera focus request for the active 3D scene, consumed and
   * cleared by Scene3D once applied (section 30). null = no pending request. */
  cameraFocusRequest: "overview" | "bottleneck" | "selected" | null;
}

export const initialAppState: AppState = {
  factory: null,
  layout: null,
  productId: null,
  planningRequestText: "",
  parseResult: null,
  exploreRequests: [],
  session: null,
  explanation: null,
  provenance: null,
  selectedIteration: "baseline",
  selectedMachineId: null,
  factoryLoading: false,
  planLoading: false,
  error: null,
  editMode: "VIEW",
  draftLayout: null,
  layoutValidation: null,
  layoutValidating: false,
  isDirty: false,
  pendingIterationSelection: null,
  viewMode: "2D",
  viewLevel: "EXECUTIVE",
  engineeringTab: "FACTORY",
  // The application now opens on the project workspace. Before P0 it opened
  // straight into a production flow, which is what made it a one-shot demo:
  // there was nowhere to come back to.
  startMode: "PROJECTS",
  concept: initialConceptState,
  project: initialProjectSessionState,
  product: initialProductWorkState,
  equipmentSelections: {},
  appliedLayouts: {},
  conversation: null,
  branchResults: {},
  selectedBranchId: null,
  conversationSending: false,
  branchComparison: null,
  comparing: false,
  verifiedFrom: null,
  staleResults: null,
  arena: null,
  strategySessions: {},
  selectedStrategyId: null,
  exploring: false,
  strategyComparison: null,
  comparePickId: null,
  strategyAnswer: null,
  refinementTrace: null,
  askingStrategy: false,
  establishedCosts: [],
  playback: initialPlaybackState,
  cameraFocusRequest: null,
};

/** What changed, and what it invalidated. */
export interface StaleResults {
  /** Result names, as the backend's dependency graph reports them. */
  stale: string[];
  /** Results the change provably cannot have affected. */
  unaffected: string[];
  /** One-line human summary from the backend. */
  summary: string;
  /** Human descriptions of each changed input. */
  changes: string[];
}
