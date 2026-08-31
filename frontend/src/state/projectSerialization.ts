import type { AppState } from "./types";
import { initialConceptState, initialProductWorkState, initialProjectSessionState } from "./types";
import type { ProjectDocument, ProjectState, StaleReport } from "../api/projects";
import { emptyProjectState } from "../api/projects";

/** The one place `AppState` and a stored project meet. */

/** The engineering state of `state`, in the shape the project store holds. */
export function serializeProject(state: AppState, previous?: ProjectState | null): ProjectState {
  const base = previous ?? emptyProjectState();
  return {
    product: {
      name: state.product.name,
      description: state.product.description,
      from_example: state.product.fromExample,
      understanding: state.product.understanding,
      understanding_model_used: state.product.modelUsed,
    },
    process: {
      draft: state.product.process,
      coverage: state.product.coverage,
    },
    requirements: { text: state.product.requirementsText },
    concept: {
      draft: state.concept.draft,
      factory: state.factory,
      product_id: state.productId,
      layout: state.layout,
      verified_from: state.verifiedFrom,
    },
    results: {
      // The arena is stored whole rather than as a pointer. Reopening a
      // project must show the exact numbers the simulator produced, not a
      // re-run that may differ from the one the engineer was looking at.
      arena: state.arena,
      selected_strategy_id: state.selectedStrategyId,
      explore_requests: state.exploreRequests,
    },
    // G13: established commercial facts are stored OUTSIDE `results`,
    // beside the engineer's other inputs, because that is what they are.
    // Everything in `results` is output the simulator produced and a
    // refinement is free to discard; a cost the engineer stated is not, and
    // filing it here is what stops the next rebuild from dropping it.
    commercial: { established_costs: state.establishedCosts },
    layout: { applied: state.appliedLayouts },
    equipment: { selections: state.equipmentSelections },
    is_example: state.project.isExample,
    stage: stageOf(state),

    // Server-owned. Round-tripped, never authored here.
    revisions: base.revisions,
    evidence: base.evidence,
    history: base.history,
    produced: state.project.produced,
    withdrawn: [],
  };
}

/** Where in the workspace the engineer was — a route, not a scroll position. */
function stageOf(state: AppState): ProjectState["stage"] {
  if (state.startMode === "FACTORY_LOADED") return "WORKSPACE";
  if (state.startMode === "CONCEPT_BUILDER") return "CONCEPT";
  return "PRODUCT";
}

/** A stored project, as the slice of `AppState` it restores. */
export function hydrateProject(document: ProjectDocument, staleness: StaleReport): Partial<AppState> {
  const stored = document.state;
  const hasFactory = Boolean(stored.concept.factory && stored.concept.product_id);

  return {
    startMode: startModeFor(stored, hasFactory),

    factory: stored.concept.factory,
    layout: stored.concept.layout,
    productId: stored.concept.product_id,
    verifiedFrom: stored.concept.verified_from,
    appliedLayouts: stored.layout.applied ?? {},

    arena: stored.results.arena,
    selectedStrategyId: stored.results.selected_strategy_id,
    exploreRequests: stored.results.explore_requests ?? [],
    // Reopening a project restores what the engineer established, not just
    // what the simulator produced. Absent in a project saved before G13,
    // which reads as "nothing established yet" — the honest default.
    establishedCosts: stored.commercial?.established_costs ?? [],
    // The per-strategy sessions are NOT restored: they are large, and every
    // one of them is reachable from the arena the engineer can re-open.
    // Restoring a session pointer with no session behind it would show an
    // empty workspace under a verified heading, so the selection stands and
    // the workspace reads the arena.
    strategySessions: {},
    session: null,
    explanation: null,

    concept: {
      ...initialConceptState,
      draft: stored.concept.draft,
    },

    product: {
      ...initialProductWorkState,
      name: stored.product.name,
      description: stored.product.description,
      fromExample: stored.product.from_example,
      understanding: stored.product.understanding,
      modelUsed: stored.product.understanding_model_used,
      process: stored.process.draft,
      coverage: stored.process.coverage,
      requirementsText: stored.requirements.text,
    },

    equipmentSelections: stored.equipment.selections ?? {},

    project: {
      ...initialProjectSessionState,
      id: document.project_id,
      name: document.name,
      createdAt: document.created_at,
      updatedAt: document.updated_at,
      schemaVersion: document.schema_version,
      isExample: stored.is_example,
      saveStatus: "IDLE",
      staleness,
    },
  };
}

/** Which screen a reopened project lands on. */
function startModeFor(stored: ProjectState, hasFactory: boolean): AppState["startMode"] {
  if (stored.stage === "WORKSPACE" && hasFactory) return "FACTORY_LOADED";
  if (stored.stage === "CONCEPT" && stored.concept.draft) return "CONCEPT_BUILDER";
  if (stored.product.understanding || stored.product.description || stored.product.name) {
    return "PRODUCT_FIRST";
  }
  return "CHOOSING";
}

/** A stable string for change detection. */
export function projectFingerprint(state: ProjectState): string {
  const { revisions, evidence, history, produced, withdrawn, ...content } = state;
  void revisions;
  void evidence;
  void history;
  void produced;
  void withdrawn;
  return JSON.stringify(content);
}
