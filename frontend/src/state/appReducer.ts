import type {
  BranchComparison,
  ConceptValidation,
  ConversationTurnResponse,
  Factory,
  FactoryConceptDraft,
  FactoryLayout,
  LayoutValidationResult,
  PlanningRunResponse,
  SimulationTrace,
  StrategyAskResponse,
  StrategyComparison,
  StrategyExploreResponse,
  UserCostInput,
} from "../api/types";
import type { AppError, AppState, EditMode, EngineeringTab, IterationSelection, PlaybackSpeed, ProductWorkState, StartMode, ViewLevel, ViewMode, StaleResults } from "./types";
import { initialAppState, initialPlaybackState, initialProjectSessionState, stageLayoutKey } from "./types";
import type { Artifact, ProjectDocument, ProjectSummary, StaleReport } from "../api/projects";
import type { CoverageReport, ManufacturingProcessDraft, ProductUnderstanding } from "../api/product";
import type { EquipmentSelectionMetadata } from "../api/handoff";
import { hydrateProject } from "./projectSerialization";

export type AppAction =
  | { type: "FACTORY_LOAD_START" }
  | { type: "FACTORY_LOAD_SUCCESS"; factory: Factory }
  | { type: "FACTORY_LOAD_ERROR"; error: AppError }
  | { type: "LAYOUT_LOAD_SUCCESS"; layout: FactoryLayout }
  | { type: "SET_REQUEST_TEXT"; text: string }
  | { type: "PLAN_RUN_START" }
  | { type: "PLAN_RUN_SUCCESS"; response: PlanningRunResponse }
  | { type: "PLAN_RUN_ERROR"; error: AppError }
  | { type: "SELECT_ITERATION"; selection: IterationSelection }
  | { type: "REQUEST_ITERATION_SWITCH"; selection: IterationSelection }
  | { type: "CONFIRM_ITERATION_SWITCH" }
  | { type: "CANCEL_ITERATION_SWITCH" }
  | { type: "SELECT_MACHINE"; machineId: string | null }
  | { type: "RESET_SESSION" }
  | { type: "CLEAR_ERROR" }
  | { type: "SET_EDIT_MODE"; mode: EditMode }
  | { type: "START_DRAFT"; draftLayout: FactoryLayout }
  | { type: "UPDATE_DRAFT"; draftLayout: FactoryLayout }
  | { type: "RESET_DRAFT" }
  | { type: "VALIDATE_DRAFT_START" }
  | { type: "VALIDATE_DRAFT_SUCCESS"; result: LayoutValidationResult }
  | { type: "VALIDATE_DRAFT_ERROR"; error: AppError }
  | { type: "APPLY_DRAFT" }
  | { type: "SET_VIEW_MODE"; mode: ViewMode }
  | { type: "SET_VIEW_LEVEL"; level: ViewLevel }
  | { type: "SET_ENGINEERING_TAB"; tab: EngineeringTab }
  // Phase 13: factory concept builder
  | { type: "SET_START_MODE"; mode: StartMode }
  | { type: "CONCEPT_EXTRACT_START" }
  | { type: "CONCEPT_UPDATED"; draft: FactoryConceptDraft; validation: ConceptValidation }
  /** Validation recomputed for a REOPENED concept. */
  | { type: "CONCEPT_RESTORED"; draft: FactoryConceptDraft; validation: ConceptValidation }
  | { type: "CONCEPT_ERROR"; error: AppError }
  | { type: "CONCEPT_BUILD_START" }
  | { type: "CONCEPT_BUILD_SUCCESS"; factory: Factory; productId: string; layout: FactoryLayout; validation: ConceptValidation }
  | { type: "RESULTS_STALE"; stale: StaleResults | null }
  // Phase 7C: conversational copilot
  | { type: "CONVERSATION_SEND_START" }
  | { type: "CONVERSATION_SEND_SUCCESS"; response: ConversationTurnResponse }
  | { type: "CONVERSATION_SEND_ERROR"; error: AppError }
  | { type: "SELECT_BRANCH"; branchId: string }
  | { type: "COMPARE_START" }
  | { type: "COMPARE_SUCCESS"; comparison: BranchComparison }
  | { type: "COMPARE_ERROR"; error: AppError }
  | { type: "CLOSE_COMPARISON" }
  // Phase 8B: optimization arena
  | { type: "EXPLORE_START" }
  | { type: "EXPLORE_SUCCESS"; response: StrategyExploreResponse; request?: string; priorRequests?: string[] }
  | { type: "EXPLORE_ERROR"; error: AppError }
  | { type: "SELECT_STRATEGY"; strategyId: string }
  | { type: "PICK_STRATEGY_FOR_COMPARE"; strategyId: string | null }
  | { type: "STRATEGY_COMPARE_SUCCESS"; comparison: StrategyComparison }
  | { type: "CLOSE_STRATEGY_COMPARISON" }
  | { type: "STRATEGY_ASK_START" }
  | { type: "STRATEGY_ASK_SUCCESS"; response: StrategyAskResponse }
  | { type: "STRATEGY_ASK_ERROR"; error: AppError }
  // Phase 8C: playback / demo storytelling
  | { type: "PLAYBACK_OPEN_START"; stageKey: IterationSelection }
  | { type: "PLAYBACK_OPEN_SUCCESS"; stageKey: IterationSelection; trace: SimulationTrace }
  | { type: "PLAYBACK_OPEN_ERROR"; error: AppError }
  | { type: "PLAYBACK_CLOSE" }
  | { type: "PLAYBACK_PLAY" }
  | { type: "PLAYBACK_PAUSE" }
  | { type: "PLAYBACK_RESET" }
  | { type: "PLAYBACK_SET_SPEED"; speed: PlaybackSpeed }
  | { type: "PLAYBACK_SEEK"; simTime: number }
  | { type: "REQUEST_CAMERA_FOCUS"; target: "overview" | "bottleneck" | "selected" }
  | { type: "CLEAR_CAMERA_FOCUS_REQUEST" }
  // P0: the project workspace
  | { type: "PROJECT_LIST_START" }
  | { type: "PROJECT_LIST_SUCCESS"; projects: ProjectSummary[] }
  | { type: "PROJECT_LIST_ERROR"; message: string }
  | { type: "PROJECT_OPEN_START" }
  | { type: "PROJECT_OPENED"; document: ProjectDocument; staleness: StaleReport }
  | { type: "PROJECT_OPEN_ERROR"; message: string }
  | { type: "PROJECT_CLOSED" }
  | { type: "PROJECT_SAVE_START" }
  | { type: "PROJECT_SAVED"; document: ProjectDocument; staleness: StaleReport }
  | { type: "PROJECT_SAVE_ERROR"; message: string }
  | { type: "PROJECT_DIRTY" }
  | { type: "PROJECT_RENAMED"; name: string }
  /** Names an artifact Fabrivium has just computed. */
  | { type: "ARTIFACT_PRODUCED"; artifact: Artifact }
  | { type: "STALENESS_UPDATED"; staleness: StaleReport }
  // P0: the product half, lifted out of ProductStart
  | { type: "PRODUCT_PATCH"; patch: Partial<ProductWorkState> }
  | { type: "PRODUCT_UNDERSTOOD"; understanding: ProductUnderstanding; modelUsed: boolean }
  | { type: "PRODUCT_PROCESS_UPDATED"; process: ManufacturingProcessDraft; coverage?: CoverageReport | null }
  | { type: "PRODUCT_COVERAGE_UPDATED"; coverage: CoverageReport | null }
  | { type: "PRODUCT_EDIT_REOPENED" }
  | { type: "EQUIPMENT_SELECTION_SET"; stationId: string; selection: EquipmentSelectionMetadata | null };

/** Fold newly-stated costs into the established set (G13). */
export function mergeEstablishedCosts(
  existing: UserCostInput[],
  incoming: UserCostInput[] | undefined,
): UserCostInput[] {
  if (!incoming || incoming.length === 0) return existing;

  const merged = [...existing];
  for (const cost of incoming) {
    const at = merged.findIndex((c) => c.gap_type === cost.gap_type);
    if (at >= 0) merged[at] = cost;
    else merged.push(cost);
  }
  return merged;
}

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "FACTORY_LOAD_START":
      return { ...state, factoryLoading: true, error: null };

    case "FACTORY_LOAD_SUCCESS":
      return {
        ...state,
        factoryLoading: false,
        factory: action.factory,
        productId: action.factory.products[0]?.id ?? null,
        error: null,
      };

    case "FACTORY_LOAD_ERROR":
      return { ...state, factoryLoading: false, error: action.error };

    case "LAYOUT_LOAD_SUCCESS":
      return { ...state, layout: action.layout };

    case "SET_REQUEST_TEXT":
      return { ...state, planningRequestText: action.text };

    case "PLAN_RUN_START":
      return { ...state, planLoading: true, error: null };

    case "PLAN_RUN_SUCCESS":
      return {
        ...state,
        planLoading: false,
        parseResult: action.response.parse_result,
        session: action.response.session,
        explanation: action.response.explanation,
        provenance: action.response.provenance,
        selectedIteration: "final",
        error: null,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        // A new verified session brings its own snapshot geometry, and may
        // contain machines an earlier layout never had. Applied placements
        // from the previous session retire with it rather than being
        // silently overlaid onto a factory they do not describe.
        appliedLayouts: {},
        // A new plan is a new verified session — any open playback trace
        // belonged to the previous one. See PlaybackState's doc comment.
        playback: initialPlaybackState,
      };

    case "PLAN_RUN_ERROR":
      return { ...state, planLoading: false, error: action.error };

    case "SELECT_ITERATION":
      return { ...state, selectedIteration: action.selection, pendingIterationSelection: null };

    case "REQUEST_ITERATION_SWITCH":
      return { ...state, pendingIterationSelection: action.selection };

    case "CONFIRM_ITERATION_SWITCH":
      if (state.pendingIterationSelection === null) return state;
      return {
        ...state,
        selectedIteration: state.pendingIterationSelection,
        pendingIterationSelection: null,
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        editMode: "VIEW",
      };

    case "CANCEL_ITERATION_SWITCH":
      return { ...state, pendingIterationSelection: null };

    case "SELECT_MACHINE":
      return { ...state, selectedMachineId: action.machineId };

    case "RESET_SESSION":
      return {
        ...state,
        conversation: null,
        branchResults: {},
        selectedBranchId: null,
        branchComparison: null,
        conversationSending: false,
        comparing: false,
        arena: null,
        strategySessions: {},
        selectedStrategyId: null,
        exploring: false,
        strategyComparison: null,
        comparePickId: null,
        strategyAnswer: null,
        refinementTrace: null,
        askingStrategy: false,
        parseResult: null,
        // Turn history must go too, or the next exploration would silently
        // inherit constraints from the conversation the user just cleared.
        exploreRequests: [],
        session: null,
        explanation: null,
        provenance: null,
        selectedIteration: "baseline",
        selectedMachineId: null,
        error: null,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        pendingIterationSelection: null,
        appliedLayouts: {},
        playback: initialPlaybackState,
        cameraFocusRequest: null,
      };

    case "CLEAR_ERROR":
      return { ...state, error: null };

    case "SET_EDIT_MODE":
      return { ...state, editMode: action.mode };

    case "START_DRAFT":
      return { ...state, draftLayout: action.draftLayout, layoutValidation: null, isDirty: false, editMode: "EDIT_LAYOUT" };

    case "UPDATE_DRAFT":
      return { ...state, draftLayout: action.draftLayout, layoutValidation: null, isDirty: true };

    case "RESET_DRAFT":
      return { ...state, draftLayout: null, layoutValidation: null, isDirty: false, editMode: "VIEW" };

    case "VALIDATE_DRAFT_START":
      return { ...state, layoutValidating: true, error: null };

    case "VALIDATE_DRAFT_SUCCESS":
      return { ...state, layoutValidating: false, layoutValidation: action.result };

    case "VALIDATE_DRAFT_ERROR":
      return { ...state, layoutValidating: false, error: action.error };

    case "APPLY_DRAFT": {
      if (!state.draftLayout || !state.layoutValidation || state.layoutValidation.error_count > 0) return state;
      // Phase 12.1 — commit to BOTH places, because two different readers
      // exist. Without a session the workspace reads `state.layout`; with
      // one it reads the selected stage's snapshot, and the committed
      // geometry has to be recorded against that stage or Apply looks like
      // it silently reverted. See AppState.appliedLayouts for why this is
      // an overlay rather than a write into the snapshot.
      const applied = state.session
        ? { ...state.appliedLayouts, [stageLayoutKey(state.selectedIteration)]: state.draftLayout }
        : state.appliedLayouts;
      return {
        ...state,
        layout: state.draftLayout,
        appliedLayouts: applied,
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        editMode: "VIEW",
      };
    }

    case "SET_VIEW_MODE":
      // A view choice only — never touches selection/editMode/draftLayout
      // (Phase 6C section 10: toggling view is never destructive).
      return { ...state, viewMode: action.mode };

    case "SET_VIEW_LEVEL":
      // Same discipline as SET_VIEW_MODE (Phase 9A): a presentation choice
      // only, never destructive, never forks state — both levels read this
      // exact AppState.
      return { ...state, viewLevel: action.level };

    case "SET_ENGINEERING_TAB":
      // Phase 12 §8/§19 — a presentation choice, held to the exact same
      // discipline as SET_VIEW_MODE/SET_VIEW_LEVEL: it never touches
      // selectedIteration, selectedStrategyId, selectedMachineId,
      // draftLayout or playback, so moving between Factory / Simulation /
      // Plan Analysis can never silently change WHICH scenario is on
      // screen. State continuity across the tabs is a property of the
      // reducer, not something each tab has to remember to preserve.
      return { ...state, engineeringTab: action.tab };

    // Phase 13: factory concept builder

    case "SET_START_MODE":
      return { ...state, startMode: action.mode };

    case "CONCEPT_EXTRACT_START":
      return { ...state, concept: { ...state.concept, extracting: true, error: null } };

    case "CONCEPT_RESTORED":
      // Validation only. The route, the factory and the results are whatever
      // the reopened project restored them to.
      return {
        ...state,
        concept: { ...state.concept, draft: action.draft, validation: action.validation },
      };

    case "CONCEPT_UPDATED":
      return {
        ...state,
        startMode: "CONCEPT_BUILDER",
        concept: {
          ...state.concept,
          draft: action.draft,
          validation: action.validation,
          extracting: false,
          error: null,
        },
      };

    case "CONCEPT_ERROR":
      return {
        ...state,
        concept: { ...state.concept, extracting: false, building: false, error: action.error },
      };

    case "CONCEPT_BUILD_START":
      return { ...state, concept: { ...state.concept, building: true, error: null } };

    case "RESULTS_STALE":
      // Recording staleness only. Nothing is hidden and nothing is
      // recomputed: both are decisions for the engineer, who may well want
      // to see the old result while deciding whether the change matters.
      return { ...state, staleResults: action.stale };

    case "CONCEPT_BUILD_SUCCESS":
      // The concept has become an ordinary Factory. From here the EXISTING
      // pipeline owns it: same `factory`/`layout`/`productId` fields the demo
      // factory populates, so simulation, planning and the strategy arena
      // need no concept-specific path at all.
      //
      // The draft is deliberately kept (the provenance view still answers
      // "where did 52 seconds come from?" after the build) but the generated
      // layout is stored so the builder can show what it produced.
      return {
        ...state,
        startMode: "FACTORY_LOADED",
        factory: action.factory,
        layout: action.layout,
        productId: action.productId,
        // A newly built factory is a new world: any earlier session, arena or
        // applied placement belonged to a different line.
        session: null,
        // Everything computed from here on answers the question THIS draft
        // poses. Remembering it is what lets a later edit be recognised as
        // invalidating rather than incidental.
        verifiedFrom: state.concept.draft,
        staleResults: null,
        explanation: null,
        arena: null,
        strategySessions: {},
        selectedStrategyId: null,
        refinementTrace: null,
        parseResult: null,
        exploreRequests: [],
        appliedLayouts: {},
        selectedIteration: "baseline",
        selectedMachineId: null,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        playback: initialPlaybackState,
        concept: {
          ...state.concept,
          validation: action.validation,
          generatedLayout: action.layout,
          building: false,
          error: null,
        },
      };

    // Phase 7C: conversational copilot

    case "CONVERSATION_SEND_START":
      return { ...state, conversationSending: true, error: null };

    case "CONVERSATION_SEND_ERROR":
      return { ...state, conversationSending: false, error: action.error };

    case "CONVERSATION_SEND_SUCCESS": {
      const { session, turn, planning_session } = action.response;

      // A turn that produced no branch (clarification / no-op / provider
      // outage) updates the transcript ONLY. The workspace keeps showing
      // whatever verified branch it was showing, because nothing about the
      // engineering state changed.
      if (!turn.branch_id || !planning_session) {
        return { ...state, conversationSending: false, conversation: session, error: null };
      }

      return {
        ...state,
        conversationSending: false,
        conversation: session,
        branchResults: {
          ...state.branchResults,
          [turn.branch_id]: { session: planning_session, explanation: turn.explanation ?? null },
        },
        selectedBranchId: turn.branch_id,
        // The workspace now shows a BRANCH. Leaving a strategy card
        // highlighted would have it claim to be what is on screen.
        selectedStrategyId: null,
        // Phase 9A real-defect fix: `selectedStrategyId` being cleared here
        // was already correct, but `arena` itself was NOT — a whole panel of
        // could keep rendering alongside this new, unrelated branch. Found
        // while building Executive View (whose results view branches on
        // `arena` truthiness), but the exact same stale-arena panel already
        // rendered in Engineering View's always-mounted StrategyArenaPanel —
        // a pre-existing defect, not a Phase 9A regression. A conversation
        // branch is a genuinely different verified history from any prior
        // arena exploration, so the arena and everything derived from it
        // retire here, exactly like RESET_SESSION already does.
        arena: null,
        strategySessions: {},
        strategyComparison: null,
        comparePickId: null,
        strategyAnswer: null,
        refinementTrace: null,
        session: planning_session,
        explanation: turn.explanation ?? null,
        selectedIteration: "final",
        // A new branch is a new verified history; an in-progress layout
        // draft belonged to the old one (mirrors PLAN_RUN_SUCCESS).
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        error: null,
        // A new verified session brings its own snapshot geometry, and may
        // contain machines an earlier layout never had. Applied placements
        // from the previous session retire with it rather than being
        // silently overlaid onto a factory they do not describe.
        appliedLayouts: {},
        playback: initialPlaybackState,
      };
    }

    case "SELECT_BRANCH": {
      const result = state.branchResults[action.branchId];
      // Never fabricate a view for a branch whose verified result we do not
      // hold — showing the previous branch's numbers under a new label
      // would be exactly the kind of silent mismatch this app exists to
      // prevent.
      if (!result) return state;
      return {
        ...state,
        selectedBranchId: action.branchId,
        selectedStrategyId: null,
        // Phase 9A real-defect fix — see the identical note on
        // CONVERSATION_SEND_SUCCESS: a selected branch is a different
        // verified history from any prior arena exploration.
        arena: null,
        strategySessions: {},
        strategyComparison: null,
        comparePickId: null,
        strategyAnswer: null,
        refinementTrace: null,
        session: result.session,
        explanation: result.explanation,
        selectedIteration: "final",
        selectedMachineId: null,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        pendingIterationSelection: null,
        // A new verified session brings its own snapshot geometry, and may
        // contain machines an earlier layout never had. Applied placements
        // from the previous session retire with it rather than being
        // silently overlaid onto a factory they do not describe.
        appliedLayouts: {},
        playback: initialPlaybackState,
      };
    }

    case "COMPARE_START":
      return { ...state, comparing: true, error: null };

    case "COMPARE_SUCCESS":
      return { ...state, comparing: false, branchComparison: action.comparison };

    case "COMPARE_ERROR":
      return { ...state, comparing: false, error: action.error };

    case "CLOSE_COMPARISON":
      return { ...state, branchComparison: null };

    // Phase 8B: optimization arena

    case "EXPLORE_START":
      return { ...state, exploring: true, error: null };

    case "EXPLORE_ERROR":
      return { ...state, exploring: false, error: action.error };

    case "EXPLORE_SUCCESS": {
      const { arena, sessions, parse_result, provenance } = action.response;
      // is never left showing a plan that belongs to a previous question.
      const opening = arena.recommended_strategy_id ?? arena.strategies[0]?.strategy_id ?? null;
      const session = opening ? (sessions[opening] ?? null) : null;

      // WHY THE RECOMMENDATION MOVED.
      //
      // A turn that carries PRIOR requests is a refinement of a question
      // already answered, not a new question — the same test `RefineBar`
      // uses to decide to re-explore rather than start a conversation. Only
      //
      // Both labels are read here, at the one moment both arenas exist: the
      // outgoing recommendation from the arena being replaced, the incoming
      // one from the arena replacing it. A component reading this later
      // cannot reconstruct the first — the state it lived in is gone.
      const isRefinement = Boolean(action.request) && (action.priorRequests?.length ?? 0) > 0;
      const previousPlan = state.arena
        ? (state.arena.strategies.find((s) => s.strategy_id === state.arena?.recommended_strategy_id)
            ?.label ?? null)
        : null;
      const currentPlan =
        arena.strategies.find((s) => s.strategy_id === arena.recommended_strategy_id)?.label ?? null;
      const refinementTrace = isRefinement
        ? {
            request: action.request as string,
            previousPlan,
            currentPlan,
            changed: previousPlan !== null && previousPlan !== currentPlan,
          }
        : null;

      return {
        ...state,
        exploring: false,
        arena,
        strategySessions: sessions,
        selectedStrategyId: session ? opening : null,
        selectedBranchId: session ? null : state.selectedBranchId,
        strategyComparison: null,
        comparePickId: null,
        strategyAnswer: null,
        refinementTrace,
        parseResult: parse_result,
        // The full turn history this result was produced from, so the next
        // refinement can carry EVERY earlier constraint, not just the last.
        exploreRequests: action.request
          ? [...(action.priorRequests ?? []), action.request]
          : state.exploreRequests,
        provenance,
        // Only adopt a session we actually hold. Showing the PREVIOUS
        // plan's numbers under a new strategy's name is exactly the silent
        // mismatch this app exists to prevent.
        session: session ?? state.session,
        explanation: session ? null : state.explanation,
        selectedIteration: session ? "final" : state.selectedIteration,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        error: null,
        appliedLayouts: session ? {} : state.appliedLayouts,
        playback: session ? initialPlaybackState : state.playback,
      };
    }

    case "SELECT_STRATEGY": {
      const session = state.strategySessions[action.strategyId];
      // Same rule as SELECT_BRANCH: never fabricate a view for a strategy
      // whose verified session we do not hold.
      if (!session) return state;
      return {
        ...state,
        selectedStrategyId: action.strategyId,
        selectedBranchId: null,
        session,
        explanation: null,
        selectedIteration: "final",
        selectedMachineId: null,
        editMode: "VIEW",
        draftLayout: null,
        layoutValidation: null,
        isDirty: false,
        pendingIterationSelection: null,
        // A new verified session brings its own snapshot geometry, and may
        // contain machines an earlier layout never had. Applied placements
        // from the previous session retire with it rather than being
        // silently overlaid onto a factory they do not describe.
        appliedLayouts: {},
        playback: initialPlaybackState,
      };
    }

    case "PICK_STRATEGY_FOR_COMPARE":
      return { ...state, comparePickId: action.strategyId };

    case "STRATEGY_COMPARE_SUCCESS":
      return { ...state, comparing: false, strategyComparison: action.comparison, comparePickId: null };

    case "CLOSE_STRATEGY_COMPARISON":
      return { ...state, strategyComparison: null, comparePickId: null };

    case "STRATEGY_ASK_START":
      return { ...state, askingStrategy: true, error: null };

    case "STRATEGY_ASK_ERROR":
      return { ...state, askingStrategy: false, error: action.error };

    case "STRATEGY_ASK_SUCCESS": {
      const { answer, arena, repriced } = action.response;
      return {
        ...state,
        askingStrategy: false,
        strategyAnswer: answer,
        // Repricing re-derives MONEY only, from the same verified sessions
        // — so the arena is swapped while `strategySessions`, `session` and
        // `selectedStrategyId` deliberately stay exactly as they were.
        arena: repriced ? arena : state.arena,
        // G13: the cost the engineer just stated is recorded as a PROJECT
        // FACT here, not only as arithmetic inside the arena above. The
        // arena is derived and a refinement rebuilds it from nothing; this
        // list is an input and survives. Recorded whether or not `repriced`
        // is true: a statement made when the sessions needed to re-derive
        // the profiles are not loaded is still a statement the engineer
        // made, and it must apply to the next exploration.
        establishedCosts: mergeEstablishedCosts(state.establishedCosts, answer.cost_inputs),
        strategyComparison: answer.comparison ?? state.strategyComparison,
        error: null,
      };
    }

    // Phase 8C: playback / demo storytelling

    case "PLAYBACK_OPEN_START":
      return {
        ...state,
        playback: {
          ...state.playback,
          active: true,
          stageKey: action.stageKey,
          loading: true,
          error: null,
          playing: false,
        },
      };

    case "PLAYBACK_OPEN_SUCCESS":
      // Ignore a stale response — the user may have closed/reopened for a
      // different stage while the request was in flight (section 28: never
      // let a late response silently overwrite a newer selection).
      if (state.playback.stageKey !== action.stageKey) return state;
      return {
        ...state,
        playback: {
          ...state.playback,
          loading: false,
          trace: action.trace,
          simTime: 0,
          playing: false,
          error: null,
        },
      };

    case "PLAYBACK_OPEN_ERROR":
      return { ...state, playback: { ...state.playback, loading: false, error: action.error } };

    case "PLAYBACK_CLOSE":
      return { ...state, playback: initialPlaybackState };

    case "PLAYBACK_PLAY":
      if (!state.playback.trace) return state;
      // Restart from the top when replaying after reaching the end.
      return {
        ...state,
        playback: {
          ...state.playback,
          playing: true,
          simTime: state.playback.simTime >= state.playback.trace.horizon_seconds ? 0 : state.playback.simTime,
        },
      };

    case "PLAYBACK_PAUSE":
      return { ...state, playback: { ...state.playback, playing: false } };

    case "PLAYBACK_RESET":
      return { ...state, playback: { ...state.playback, playing: false, simTime: 0 } };

    case "PLAYBACK_SET_SPEED":
      return { ...state, playback: { ...state.playback, speed: action.speed } };

    case "PLAYBACK_SEEK": {
      const horizon = state.playback.trace?.horizon_seconds ?? 0;
      const clamped = Math.min(horizon, Math.max(0, action.simTime));
      // Reaching the end pauses automatically rather than holding on a
      // "playing" state that visually never advances again.
      const playing = state.playback.playing && clamped < horizon;
      return { ...state, playback: { ...state.playback, simTime: clamped, playing } };
    }

    case "REQUEST_CAMERA_FOCUS":
      return { ...state, cameraFocusRequest: action.target };

    case "CLEAR_CAMERA_FOCUS_REQUEST":
      return { ...state, cameraFocusRequest: null };

    // P0: the project workspace

    case "PROJECT_LIST_START":
      return { ...state, project: { ...state.project, listing: true, error: null } };

    case "PROJECT_LIST_SUCCESS":
      return { ...state, project: { ...state.project, listing: false, recent: action.projects } };

    case "PROJECT_LIST_ERROR":
      return { ...state, project: { ...state.project, listing: false, error: action.message } };

    case "PROJECT_OPEN_START":
      return { ...state, project: { ...state.project, opening: true, error: null } };

    case "PROJECT_OPENED": {
      // A whole new world. Starting from `initialAppState` rather than from
      // `state` is what makes "two projects never bleed into one another"
      // true by construction instead of by remembering to clear thirty
      // fields — the exact bug class the audit found in the old flow.
      const hydrated = hydrateProject(action.document, action.staleness);
      return {
        ...initialAppState,
        ...hydrated,
        // The recent list belongs to the workspace, not to any one project.
        project: { ...(hydrated.project ?? initialProjectSessionState), recent: state.project.recent },
      };
    }

    case "PROJECT_OPEN_ERROR":
      return { ...state, project: { ...state.project, opening: false, error: action.message } };

    case "PROJECT_CLOSED":
      // Back to the landing page, with nothing of the closed project left
      // behind it.
      return {
        ...initialAppState,
        startMode: "PROJECTS",
        project: { ...initialProjectSessionState, recent: state.project.recent },
      };

    case "PROJECT_SAVE_START":
      return { ...state, project: { ...state.project, saveStatus: "SAVING", saveError: null } };

    case "PROJECT_SAVED":
      return {
        ...state,
        project: {
          ...state.project,
          saveStatus: "SAVED",
          saveError: null,
          updatedAt: action.document.updated_at,
          name: action.document.name,
          staleness: action.staleness,
          // Consumed by the server, which has now stamped them.
          produced: [],
        },
      };

    case "PROJECT_SAVE_ERROR":
      // Never swallowed. An engineer who believes their work is stored and
      // finds it is not has been actively misled, which is worse than a
      // visible failure they can act on.
      return { ...state, project: { ...state.project, saveStatus: "ERROR", saveError: action.message } };

    case "PROJECT_DIRTY":
      return state.project.saveStatus === "DIRTY"
        ? state
        : { ...state, project: { ...state.project, saveStatus: "DIRTY" } };

    case "PROJECT_RENAMED":
      return { ...state, project: { ...state.project, name: action.name } };

    case "ARTIFACT_PRODUCED":
      return state.project.produced.includes(action.artifact)
        ? state
        : {
            ...state,
            project: { ...state.project, produced: [...state.project.produced, action.artifact] },
          };

    case "STALENESS_UPDATED":
      return { ...state, project: { ...state.project, staleness: action.staleness } };

    // P0: the product half

    case "PRODUCT_PATCH":
      return { ...state, product: { ...state.product, ...action.patch } };

    case "PRODUCT_UNDERSTOOD":
      return {
        ...state,
        product: {
          ...state.product,
          understanding: action.understanding,
          modelUsed: action.modelUsed,
          // Re-reading the product is a new reading of it. The route derived
          // from the OLD facts is not evidence about the new ones, and
          // keeping it on screen under a fresh set of facts is precisely the
          // "stale masquerading as current" failure this phase exists to
          // close. It is dropped rather than marked, because a proposal is
          // cheap to regenerate and there is a button for it.
          process: null,
          coverage: null,
          editing: false,
          busy: false,
          error: null,
        },
      };

    case "PRODUCT_PROCESS_UPDATED":
      return {
        ...state,
        product: {
          ...state.product,
          process: action.process,
          coverage: action.coverage === undefined ? state.product.coverage : action.coverage,
        },
      };

    case "PRODUCT_COVERAGE_UPDATED":
      return { ...state, product: { ...state.product, coverage: action.coverage } };

    case "PRODUCT_EDIT_REOPENED":
      // The facts and the route are KEPT. Reopening the form is not the act
      // of discarding what was read from the old one — that happens only if
      // the engineer actually changes the source and re-reads it.
      return {
        ...state,
        startMode: "PRODUCT_FIRST",
        product: { ...state.product, editing: true, error: null },
      };

    case "EQUIPMENT_SELECTION_SET": {
      // ONE current selection per station, always. A station showing two
      // machines as chosen is not a richer answer, it is an unanswered
      // question wearing the badge of a decision.
      //
      // The one it replaces is not discarded, though: an engineer who tried
      // three candidates and settled on the second made an engineering
      // decision, and the two they rejected are part of why. The trail moves
      // onto the new record so it travels with the station rather than with
      // whichever machine happens to be current.
      const selections = { ...state.equipmentSelections };
      const previous = selections[action.stationId];

      if (action.selection === null) {
        delete selections[action.stationId];
        return { ...state, equipmentSelections: selections };
      }

      const trail = [...(previous?.superseded ?? [])];
      const replacesADifferentMachine =
        previous && previous.candidate_id && previous.candidate_id !== action.selection.candidate_id;
      if (replacesADifferentMachine) {
        trail.push({
          candidate_id: previous.candidate_id as string,
          manufacturer: previous.manufacturer,
          model: previous.model,
          selected_at: previous.selected_at ?? "",
          superseded_at: action.selection.selected_at ?? "",
        });
      }

      selections[action.stationId] = { ...action.selection, superseded: trail };
      return { ...state, equipmentSelections: selections };
    }

    default:
      return state;
  }
}
