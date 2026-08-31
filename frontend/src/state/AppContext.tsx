import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import type { ReactNode } from "react";
import { describeRequestFailure } from "../api/client";
import { getExampleFactory } from "../api/factory";
import { getExampleLayout, validateLayout } from "../api/layout";
import { compareBranches, sendConversationTurn, startConversation } from "../api/conversation";
import { runPlanning } from "../api/planning";
import { getSimulationPlayback, getVerifiedPlayback } from "../api/simulation";
import { askAboutStrategies, compareStrategyOptions, exploreStrategies } from "../api/strategy";
import { applyExampleData, buildConcept, changeImpact, conceptFromBrief, validateConcept } from "../api/concept";
import { createEmptyDraft, moveMachineDraft, placeMachineDraft, rotateMachineDraft } from "../utils/layoutDraft";
import { effectiveStageLayout, resolveStage } from "../utils/stage";
import {
  createProject as createProjectRequest,
  deleteProject as deleteProjectRequest,
  emptyProjectState,
  listProjects,
  openProject as openProjectRequest,
  saveProject as saveProjectRequest,
} from "../api/projects";
import type { Artifact, ProjectState as StoredProjectState } from "../api/projects";
import { referenceProduct } from "../api/product";
import { appReducer } from "./appReducer";
import { projectFingerprint, serializeProject } from "./projectSerialization";
import { initialAppState } from "./types";
import type { AppError, AppState, EditMode, EngineeringTab, IterationSelection, PlaybackSpeed, StartMode, ViewLevel, ViewMode } from "./types";
import type { FactoryConceptDraft, SimulationTrace } from "../api/types";

function classifyError(error: unknown): AppError {
  const message = describeRequestFailure(error);
  if (error instanceof Error && error.name === "BackendUnavailableError") {
    return { kind: "network", message };
  }
  if (error instanceof Error && error.name === "ApiValidationError") {
    return { kind: "validation", message };
  }
  if (error instanceof Error && error.name === "ApiError") {
    return { kind: "api", message };
  }
  return { kind: "unknown", message };
}

export interface AppContextValue {
  state: AppState;
  loadExampleFactory: () => Promise<void>;
  loadExampleLayout: () => Promise<void>;
  setRequestText: (text: string) => void;
  runPlan: (userRequest?: string) => Promise<void>;
  selectIteration: (selection: IterationSelection) => void;
  selectMachine: (machineId: string | null) => void;
  resetSession: () => void;
  clearError: () => void;

  // Phase 6B: layout editor
  currentStageFactory: () => import("../api/types").Factory | null;
  currentStageLayout: () => import("../api/types").FactoryLayout | null;
  setEditMode: (mode: EditMode) => void;
  enterEditMode: () => void;
  moveMachine: (machineId: string, x: number, y: number) => void;
  rotateMachine: (machineId: string, rotationDeg: number) => void;
  placeMachine: (machineId: string, x: number, y: number) => void;
  validateDraft: () => Promise<void>;
  applyDraft: () => void;
  resetDraft: () => void;
  setViewMode: (mode: ViewMode) => void;
  setViewLevel: (level: ViewLevel) => void;
  setEngineeringTab: (tab: EngineeringTab) => void;

  // Phase 13: factory concept builder
  setStartMode: (mode: StartMode) => void;
  startConceptFromBrief: (brief: string, name?: string) => Promise<void>;
  useExampleEngineeringData: () => Promise<void>;
  updateConceptDraft: (draft: FactoryConceptDraft) => Promise<void>;
  buildConceptFactory: () => Promise<void>;
  openDemoFactory: () => Promise<void>;
  confirmIterationSwitch: () => void;
  cancelIterationSwitch: () => void;

  // Phase 7C: conversational copilot
  sendMessage: (message: string) => Promise<void>;
  selectBranch: (branchId: string) => void;
  compareWithBranch: (branchId: string) => Promise<void>;
  closeComparison: () => void;

  // Phase 8B: optimization arena
  exploreOptions: (userRequest: string, priorRequests?: string[]) => Promise<void>;
  selectStrategy: (strategyId: string) => void;
  compareWithStrategy: (strategyId: string) => Promise<void>;
  closeStrategyComparison: () => void;
  askAboutOptions: (question: string) => Promise<void>;

  // Phase 8C: playback / demo storytelling
  openPlayback: () => Promise<void>;
  viewStagePlayback: (selection: IterationSelection) => Promise<void>;
  closePlayback: () => void;
  playPlayback: () => void;
  pausePlayback: () => void;
  resetPlayback: () => void;
  setPlaybackSpeed: (speed: PlaybackSpeed) => void;
  seekPlayback: (simTime: number) => void;
  requestCameraFocus: (target: "overview" | "bottleneck" | "selected") => void;
  clearCameraFocusRequest: () => void;

  // P0: the project workspace
  refreshProjects: () => Promise<void>;
  newProject: (name: string) => Promise<void>;
  openExampleProject: () => Promise<void>;
  openProject: (projectId: string) => Promise<void>;
  closeProject: () => void;
  renameProject: (name: string) => void;
  removeProject: (projectId: string) => Promise<void>;
  /** Force the pending autosave to land now. */
  flushSave: () => Promise<void>;
  /** Name an artifact Fabrivium has just computed. */
  recordArtifact: (artifact: Artifact) => void;

  // P0: the product half, lifted out of ProductStart
  setProductField: (patch: Partial<AppState["product"]>) => void;
  productUnderstood: (understanding: import("../api/product").ProductUnderstanding, modelUsed: boolean) => void;
  setProcessDraft: (
    process: import("../api/product").ManufacturingProcessDraft,
    coverage?: import("../api/product").CoverageReport | null,
  ) => void;
  setCoverage: (coverage: import("../api/product").CoverageReport | null) => void;
  loadExampleSpecification: () => Promise<void>;
  editProductInformation: () => void;
  setEquipmentSelection: (
    stationId: string,
    selection: import("../api/handoff").EquipmentSelectionMetadata | null,
  ) => void;
}

// Exported (rather than kept module-private) so tests can seed an exact
// AppState via `<AppContext.Provider value={...}>` without driving the
// real reducer/fetch machinery — see src/test/testUtils.tsx.
export const AppContext = createContext<AppContextValue | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialAppState);

  const loadExampleFactory = useCallback(async () => {
    dispatch({ type: "FACTORY_LOAD_START" });
    try {
      const factory = await getExampleFactory();
      dispatch({ type: "FACTORY_LOAD_SUCCESS", factory });
    } catch (error) {
      dispatch({ type: "FACTORY_LOAD_ERROR", error: classifyError(error) });
    }
  }, []);

  const loadExampleLayout = useCallback(async () => {
    try {
      const layout = await getExampleLayout();
      dispatch({ type: "LAYOUT_LOAD_SUCCESS", layout });
    } catch (error) {
      dispatch({ type: "FACTORY_LOAD_ERROR", error: classifyError(error) });
    }
  }, []);

  const setRequestText = useCallback((text: string) => {
    dispatch({ type: "SET_REQUEST_TEXT", text });
  }, []);

  const runPlan = useCallback(
    async (userRequestOverride?: string) => {
      const userRequest = userRequestOverride ?? state.planningRequestText;
      if (!state.factory || !state.productId || !userRequest.trim()) return;

      dispatch({ type: "PLAN_RUN_START" });
      try {
        const response = await runPlanning({
          factory: state.factory,
          product_id: state.productId,
          user_request: userRequest,
          layout: state.layout ?? undefined,
        });
        dispatch({ type: "PLAN_RUN_SUCCESS", response });
      } catch (error) {
        dispatch({ type: "PLAN_RUN_ERROR", error: classifyError(error) });
      }
    },
    [state.factory, state.productId, state.planningRequestText, state.layout],
  );

  // Phase 7C: conversational copilot

  /** Send one conversational message. */
  const sendMessage = useCallback(
    async (message: string) => {
      if (!state.factory || !state.productId || !message.trim()) return;

      dispatch({ type: "CONVERSATION_SEND_START" });
      try {
        const response = state.conversation
          ? await sendConversationTurn({ session: state.conversation, user_message: message })
          : await startConversation({
              factory: state.factory,
              product_id: state.productId,
              user_message: message,
              layout: state.layout ?? undefined,
            });
        dispatch({ type: "CONVERSATION_SEND_SUCCESS", response });
      } catch (error) {
        dispatch({ type: "CONVERSATION_SEND_ERROR", error: classifyError(error) });
      }
    },
    [state.factory, state.productId, state.layout, state.conversation],
  );

  /** Switch which verified branch the workspace shows. */
  const selectBranch = useCallback((branchId: string) => {
    dispatch({ type: "SELECT_BRANCH", branchId });
  }, []);

  /** Compare the selected branch against *branchId*. */
  const compareWithBranch = useCallback(
    async (branchId: string) => {
      if (!state.conversation || !state.selectedBranchId) return;
      dispatch({ type: "COMPARE_START" });
      try {
        const comparison = await compareBranches({
          session: state.conversation,
          branch_a_id: branchId,
          branch_b_id: state.selectedBranchId,
        });
        dispatch({ type: "COMPARE_SUCCESS", comparison });
      } catch (error) {
        dispatch({ type: "COMPARE_ERROR", error: classifyError(error) });
      }
    },
    [state.conversation, state.selectedBranchId],
  );

  const closeComparison = useCallback(() => dispatch({ type: "CLOSE_COMPARISON" }), []);

  // Phase 8B: optimization arena

  /** Explore several verified strategies for one goal. */
  const exploreOptions = useCallback(
    async (userRequest: string, priorRequests: string[] = []) => {
      if (!state.factory || !state.productId || !userRequest.trim()) return;

      dispatch({ type: "EXPLORE_START" });
      try {
        const response = await exploreStrategies({
          factory: state.factory,
          product_id: state.productId,
          user_request: userRequest,
          // Earlier turns are sent SEPARATELY, never joined into one
          // string: each is parsed alone and precedence between them is
          // resolved structurally server-side. Joining them let the first
          // figure mentioned win and let a softening word in one turn
          // downgrade an absolute restriction stated in another.
          prior_requests: priorRequests.length > 0 ? priorRequests : undefined,
          layout: state.layout ?? undefined,
          // G13: costs the engineer has already established travel WITH the
          // exploration. Without this the arena is rebuilt from defaults
          // that have never heard of them, and a refinement silently
          // un-prices a plan the engineer had already priced — the number
          // was only ever held inside the arena being replaced.
          //
          // Sending them is not the same as charging them: the backend
          // consults a cost only where the rebuilt strategy actually has
          // that gap, so a plan that adds no shift is not billed for one.
          user_costs: state.establishedCosts.length > 0 ? state.establishedCosts : undefined,
        });
        dispatch({ type: "EXPLORE_SUCCESS", response, request: userRequest, priorRequests });
        // Exploring RUNS the deterministic simulator, on the baseline and on
        // every candidate. Those runs are the verification, so this is the
        // moment the project has evidence about throughput — and the moment
        // a later cycle-time edit has something to invalidate.
        dispatch({ type: "ARTIFACT_PRODUCED", artifact: "SIMULATION_VERIFICATION" });
        dispatch({ type: "ARTIFACT_PRODUCED", artifact: "STRATEGIES" });
        dispatch({ type: "ARTIFACT_PRODUCED", artifact: "SELECTED_PLAN" });
      } catch (error) {
        dispatch({ type: "EXPLORE_ERROR", error: classifyError(error) });
      }
    },
    [state.factory, state.productId, state.layout, state.establishedCosts],
  );

  /** Show a strategy's own verified session in the workspace. */
  const selectStrategy = useCallback((strategyId: string) => {
    dispatch({ type: "SELECT_STRATEGY", strategyId });
  }, []);

  /** Compare *strategyId* against the option currently open. */
  const compareWithStrategy = useCallback(
    async (strategyId: string) => {
      const arena = state.arena;
      if (!arena || !state.selectedStrategyId) return;
      const a = arena.strategies.find((o) => o.strategy_id === strategyId);
      const b = arena.strategies.find((o) => o.strategy_id === state.selectedStrategyId);
      if (!a || !b || a === b) return;

      dispatch({ type: "COMPARE_START" });
      try {
        const comparison = await compareStrategyOptions({ strategy_a: a, strategy_b: b });
        dispatch({ type: "STRATEGY_COMPARE_SUCCESS", comparison });
      } catch (error) {
        dispatch({ type: "COMPARE_ERROR", error: classifyError(error) });
      }
    },
    [state.arena, state.selectedStrategyId],
  );

  const closeStrategyComparison = useCallback(() => dispatch({ type: "CLOSE_STRATEGY_COMPARISON" }), []);

  /** Ask a follow-up about the options already on screen (section 15). */
  const askAboutOptions = useCallback(
    async (question: string) => {
      if (!state.arena || !question.trim()) return;
      dispatch({ type: "STRATEGY_ASK_START" });
      try {
        const response = await askAboutStrategies({
          arena: state.arena,
          question,
          sessions: state.strategySessions,
          // Repricing rebuilds every cost profile from its session, so it
          // must be handed everything established so far — otherwise
          // stating a second cost closes its own gap and re-opens the one
          // the previous statement had already closed (G13).
          established_costs: state.establishedCosts.length > 0 ? state.establishedCosts : undefined,
        });
        dispatch({ type: "STRATEGY_ASK_SUCCESS", response });
      } catch (error) {
        dispatch({ type: "STRATEGY_ASK_ERROR", error: classifyError(error) });
      }
    },
    [state.arena, state.strategySessions, state.establishedCosts],
  );

  // Phase 8C: playback / demo storytelling

  /** Open playback for the CURRENTLY SELECTED timeline stage — the same
   * snapshot already driving KPI/2D/3D (`resolveStage`), never a
   * separately-selected one. This is what makes playback/KPI/explanation
   * impossible to desync by construction (section 28). */
  /** The trace for *selection*, however this project can produce one. */
  const fetchTraceFor = useCallback(
    async (selection: IterationSelection): Promise<SimulationTrace | null> => {
      if (!state.productId) return null;
      const layout = effectiveStageLayout(state, selection) ?? undefined;

      const stage = resolveStage(state.session, selection);
      if (stage) {
        return getSimulationPlayback({
          factory: stage.snapshot.factory,
          product_id: state.productId,
          // The geometry currently on screen, so playback animates along the
          // route the user actually laid out. The FACTORY is still the
          // snapshot's — placement is not a simulation input, so this
          // changes where units are drawn, never what is computed.
          layout,
        });
      }

      // Reopened project: rebuild from what was saved.
      const arena = state.arena;
      const factory = state.factory;
      if (!arena || !factory) return null;

      const onBaseline = selection === "baseline";
      const selected = arena.strategies.find((o) => o.strategy_id === state.selectedStrategyId) ?? null;
      // Only the two scenarios a saved project can name. An intermediate
      // planning iteration belongs to a session; without one there is
      // nothing to rebuild it from, and guessing is not on offer.
      if (!onBaseline && !selected) return null;

      return getVerifiedPlayback({
        factory,
        product_id: state.productId,
        actions: onBaseline ? null : selected!.actions,
        expected: onBaseline ? arena.baseline_metrics : selected!.metrics,
        layout,
      });
    },
    [state, state.session, state.arena, state.factory, state.productId, state.selectedStrategyId],
  );

  const openPlayback = useCallback(async () => {
    // With a session, the stage on screen is the subject — unchanged.
    //
    // Without one (a reopened project) `selectedIteration` is still its
    // default of "baseline", while the panel this action sits in is showing
    // the SELECTED PLAN. Opening the baseline from a button under Plan B's
    // figures would answer a question nobody asked; the Before/After toggle
    // inside the panel is how the baseline is reached.
    const hasSession = resolveStage(state.session, state.selectedIteration) !== null;
    const stageKey: IterationSelection =
      hasSession ? state.selectedIteration : state.selectedStrategyId ? "final" : "baseline";

    // Keep the timeline selection with the scenario being played: the twin
    // only renders playback while the two agree (CenterWorkspace).
    if (!hasSession && stageKey !== state.selectedIteration) {
      dispatch({ type: "SELECT_ITERATION", selection: stageKey });
    }
    dispatch({ type: "PLAYBACK_OPEN_START", stageKey });
    try {
      const trace = await fetchTraceFor(stageKey);
      if (!trace) {
        dispatch({
          type: "PLAYBACK_OPEN_ERROR",
          error: { kind: "unknown", message: "There is nothing verified to play for this stage." },
        });
        return;
      }
      dispatch({ type: "PLAYBACK_OPEN_SUCCESS", stageKey, trace });
    } catch (error) {
      dispatch({ type: "PLAYBACK_OPEN_ERROR", error: classifyError(error) });
    }
  }, [fetchTraceFor, state.session, state.selectedIteration, state.selectedStrategyId]);

  /** Switch the workspace to *selection* AND (re)open playback for it in
   * one action — the Before/After toggle inside an open playback panel
   * uses this instead of two separate clicks. Respects the same
   * uncommitted-draft guard as `selectIteration` (section 34: playback
   * must never let a stage switch silently discard an edit). */
  const viewStagePlayback = useCallback(
    async (selection: IterationSelection) => {
      if (state.isDirty) {
        dispatch({ type: "REQUEST_ITERATION_SWITCH", selection });
        return;
      }
      if (!state.productId) return;
      dispatch({ type: "SELECT_ITERATION", selection });
      dispatch({ type: "PLAYBACK_OPEN_START", stageKey: selection });
      try {
        const trace = await fetchTraceFor(selection);
        if (!trace) {
          dispatch({
            type: "PLAYBACK_OPEN_ERROR",
            error: { kind: "unknown", message: "There is nothing verified to play for this stage." },
          });
          return;
        }
        dispatch({ type: "PLAYBACK_OPEN_SUCCESS", stageKey: selection, trace });
      } catch (error) {
        dispatch({ type: "PLAYBACK_OPEN_ERROR", error: classifyError(error) });
      }
    },
    [fetchTraceFor, state.productId, state.isDirty],
  );

  const closePlayback = useCallback(() => dispatch({ type: "PLAYBACK_CLOSE" }), []);
  const playPlayback = useCallback(() => dispatch({ type: "PLAYBACK_PLAY" }), []);
  const pausePlayback = useCallback(() => dispatch({ type: "PLAYBACK_PAUSE" }), []);
  const resetPlayback = useCallback(() => dispatch({ type: "PLAYBACK_RESET" }), []);
  const setPlaybackSpeed = useCallback((speed: PlaybackSpeed) => dispatch({ type: "PLAYBACK_SET_SPEED", speed }), []);
  const seekPlayback = useCallback((simTime: number) => dispatch({ type: "PLAYBACK_SEEK", simTime }), []);
  const requestCameraFocus = useCallback(
    (target: "overview" | "bottleneck" | "selected") => dispatch({ type: "REQUEST_CAMERA_FOCUS", target }),
    [],
  );
  const clearCameraFocusRequest = useCallback(() => dispatch({ type: "CLEAR_CAMERA_FOCUS_REQUEST" }), []);

  // P0: the project workspace
  //
  // THE EDITING LOOP
  // There is no Save button. Saving is not a decision an engineer makes —
  // changing a cycle time already was one — and a button would imply that
  // not pressing it is a way to undo, which it is not.
  //
  // Instead: the serialised project is compared against what was last
  // stored, and a difference schedules a debounced write. Change detection
  // is a comparison rather than a dirty flag set by each action, because
  // forty actions each responsible for remembering the same bookkeeping is
  // forty chances to forget one — and the one that gets forgotten is the one
  // that loses somebody's work.

  //: How long editing has to pause before a save goes out. Long enough that
  //: typing a description is one write rather than sixty; short enough that
  //: the engineer never gets ahead of it.
  const AUTOSAVE_DELAY_MS = 700;

  //: The stored document's server-owned bookkeeping (revisions, evidence
  //: stamps, history), round-tripped verbatim on every save. Held in a ref
  //: rather than in state because nothing renders from it and it must never
  //: participate in change detection.
  const storedRef = useRef<StoredProjectState | null>(null);
  //: Fingerprint of the last payload known to be on disk.
  const savedFingerprintRef = useRef<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  //: The save currently in flight, so `flushSave` can wait for it.
  const inFlightRef = useRef<Promise<void> | null>(null);
  //: The live state, for the save routine to read without re-creating
  //: itself (and therefore re-arming the timer) on every keystroke. Written
  //: by the autosave effect below, which runs after every render.
  const stateRef = useRef(state);
  //: The fingerprint a save is currently armed for. Guards against re-arming
  //: the debounce on renders that changed nothing — see the effect.
  const armedRef = useRef<string | null>(null);
  //: The engineering slices, by reference. React's reducer keeps unchanged
  //: slices reference-identical, so comparing eight pointers is a sound and
  //: very cheap way to skip serialising a multi-hundred-kilobyte arena on a
  //: render that could not possibly have touched it — playback dispatches
  //: on an animation loop, and stringifying the arena per frame would be a
  //: real cost for no possible gain.
  const slicesRef = useRef<readonly unknown[]>([]);

  const refreshProjects = useCallback(async () => {
    dispatch({ type: "PROJECT_LIST_START" });
    try {
      const { projects } = await listProjects();
      dispatch({ type: "PROJECT_LIST_SUCCESS", projects });
    } catch (error) {
      dispatch({ type: "PROJECT_LIST_ERROR", message: describeRequestFailure(error) });
    }
  }, []);

  /** Write the project now. Returns once the write has landed or failed. */
  const performSave = useCallback(async () => {
    const current = stateRef.current;
    const projectId = current.project.id;
    if (!projectId) return;

    const payload = serializeProject(current, storedRef.current);
    const fingerprint = projectFingerprint(payload);
    // `produced` is an instruction rather than content, so a save is still
    // warranted when only it has changed — that is how a re-verification
    // clears a stale badge without any other edit.
    if (fingerprint === savedFingerprintRef.current && payload.produced.length === 0) return;

    dispatch({ type: "PROJECT_SAVE_START" });
    try {
      const response = await saveProjectRequest(projectId, payload, current.project.name);
      storedRef.current = response.project.state;
      savedFingerprintRef.current = projectFingerprint(response.project.state);
      dispatch({ type: "PROJECT_SAVED", document: response.project, staleness: response.staleness });
    } catch (error) {
      // Reported, never swallowed. An engineer who believes their work is
      // stored and finds it is not has been actively misled, which is worse
      // than a visible failure they can act on.
      dispatch({ type: "PROJECT_SAVE_ERROR", message: describeRequestFailure(error) });
    }
  }, []);

  const flushSave = useCallback(async () => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    armedRef.current = null;
    if (inFlightRef.current) await inFlightRef.current;
    const run = performSave();
    inFlightRef.current = run;
    await run;
    inFlightRef.current = null;
  }, [performSave]);

  const adoptProject = useCallback(
    async (response: {
      project: import("../api/projects").ProjectDocument;
      staleness: import("../api/projects").StaleReport;
    }) => {
      storedRef.current = response.project.state;
      savedFingerprintRef.current = projectFingerprint(response.project.state);
      armedRef.current = null;
      slicesRef.current = [];
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      dispatch({ type: "PROJECT_OPENED", document: response.project, staleness: response.staleness });

      // Re-validate the restored concept.
      //
      // `ConceptValidation` is DERIVED — which gaps block simulation is a
      // property of what the simulator reads — so it is deliberately not
      // persisted. But nothing recomputed it on reopen either, which left a
      // reopened concept with `validation === null`: the footer read
      // "0 inputs still needed" (there are no blocking gaps in a null
      // validation) while Build stayed disabled (`simulation_ready` is
      // likewise absent). A screen that says ready and refuses to act is
      // worse than one that says what is missing.
      const restored = response.project.state.concept.draft;
      if (restored) {
        try {
          const validation = await validateConcept(restored as FactoryConceptDraft);
          dispatch({ type: "CONCEPT_RESTORED", draft: restored as FactoryConceptDraft, validation });
        } catch {
          // A validation that cannot be fetched leaves the concept exactly as
          // it was restored. The engineer can still edit it, and the next
          // edit re-validates through the ordinary path.
        }
      }
    },
    [],
  );

  const newProject = useCallback(
    async (name: string) => {
      if (!name.trim()) return;
      dispatch({ type: "PROJECT_OPEN_START" });
      try {
        await adoptProject(await createProjectRequest(name.trim()));
        void refreshProjects();
      } catch (error) {
        dispatch({ type: "PROJECT_OPEN_ERROR", message: describeRequestFailure(error) });
      }
    },
    [adoptProject, refreshProjects],
  );

  /** The bundled example, as a real project rather than a third workflow. */
  const openExampleProject = useCallback(async () => {
    dispatch({ type: "PROJECT_OPEN_START" });
    try {
      const reference = await referenceProduct();
      const seeded = emptyProjectState();
      seeded.is_example = true;
      seeded.product = {
        ...seeded.product,
        name: "Compact electronics controller",
        description: reference.text,
        from_example: true,
      };
      await adoptProject(await createProjectRequest("Example — electronics controller", seeded));
      void refreshProjects();
    } catch (error) {
      dispatch({ type: "PROJECT_OPEN_ERROR", message: describeRequestFailure(error) });
    }
  }, [adoptProject, refreshProjects]);

  const openProject = useCallback(
    async (projectId: string) => {
      dispatch({ type: "PROJECT_OPEN_START" });
      try {
        await adoptProject(await openProjectRequest(projectId));
      } catch (error) {
        dispatch({ type: "PROJECT_OPEN_ERROR", message: describeRequestFailure(error) });
      }
    },
    [adoptProject],
  );

  const closeProject = useCallback(() => {
    // The pending write goes out first. Leaving a project is exactly when a
    // debounce would otherwise eat the last edit.
    void flushSave().finally(() => {
      storedRef.current = null;
      savedFingerprintRef.current = null;
      dispatch({ type: "PROJECT_CLOSED" });
      void refreshProjects();
    });
  }, [flushSave, refreshProjects]);

  const renameProject = useCallback((name: string) => {
    dispatch({ type: "PROJECT_RENAMED", name });
  }, []);

  const removeProject = useCallback(
    async (projectId: string) => {
      try {
        await deleteProjectRequest(projectId);
      } catch (error) {
        dispatch({ type: "PROJECT_LIST_ERROR", message: describeRequestFailure(error) });
        return;
      }
      await refreshProjects();
    },
    [refreshProjects],
  );

  const recordArtifact = useCallback((artifact: Artifact) => {
    dispatch({ type: "ARTIFACT_PRODUCED", artifact });
  }, []);

  // P0: the product half

  const setProductField = useCallback((patch: Partial<AppState["product"]>) => {
    dispatch({ type: "PRODUCT_PATCH", patch });
  }, []);

  const productUnderstood = useCallback(
    (understanding: import("../api/product").ProductUnderstanding, modelUsed: boolean) => {
      dispatch({ type: "PRODUCT_UNDERSTOOD", understanding, modelUsed });
      dispatch({ type: "ARTIFACT_PRODUCED", artifact: "PRODUCT_FACTS" });
    },
    [],
  );

  /** Adopt an edited process, and the coverage recomputed against it. */
  const setProcessDraft = useCallback(
    (
      process: import("../api/product").ManufacturingProcessDraft,
      coverage?: import("../api/product").CoverageReport | null,
    ) => {
      dispatch({ type: "PRODUCT_PROCESS_UPDATED", process, coverage });
      if (coverage) dispatch({ type: "ARTIFACT_PRODUCED", artifact: "REQUIREMENT_COVERAGE" });
    },
    [],
  );

  const setCoverage = useCallback((coverage: import("../api/product").CoverageReport | null) => {
    dispatch({ type: "PRODUCT_COVERAGE_UPDATED", coverage });
    if (coverage) dispatch({ type: "ARTIFACT_PRODUCED", artifact: "REQUIREMENT_COVERAGE" });
  }, []);

  /** Load the bundled example specification, on an explicit click. */
  const loadExampleSpecification = useCallback(async () => {
    dispatch({ type: "PRODUCT_PATCH", patch: { busy: true, error: null } });
    try {
      const reference = await referenceProduct();
      dispatch({
        type: "PRODUCT_PATCH",
        patch: {
          name: "Compact electronics controller",
          description: reference.text,
          fromExample: true,
          busy: false,
        },
      });
    } catch (error) {
      dispatch({
        type: "PRODUCT_PATCH",
        patch: { busy: false, error: describeRequestFailure(error) },
      });
    }
  }, []);

  const editProductInformation = useCallback(() => {
    dispatch({ type: "PRODUCT_EDIT_REOPENED" });
  }, []);

  const setEquipmentSelection = useCallback(
    (stationId: string, selection: import("../api/handoff").EquipmentSelectionMetadata | null) => {
      dispatch({ type: "EQUIPMENT_SELECTION_SET", stationId, selection });
    },
    [],
  );


  const selectIteration = useCallback(
    (selection: IterationSelection) => {
      if (selection === state.selectedIteration) return;
      if (state.isDirty) {
        dispatch({ type: "REQUEST_ITERATION_SWITCH", selection });
      } else {
        dispatch({ type: "SELECT_ITERATION", selection });
      }
    },
    [state.selectedIteration, state.isDirty],
  );

  const confirmIterationSwitch = useCallback(() => {
    dispatch({ type: "CONFIRM_ITERATION_SWITCH" });
  }, []);

  const cancelIterationSwitch = useCallback(() => {
    dispatch({ type: "CANCEL_ITERATION_SWITCH" });
  }, []);

  const selectMachine = useCallback((machineId: string | null) => {
    dispatch({ type: "SELECT_MACHINE", machineId });
  }, []);

  const resetSession = useCallback(() => {
    dispatch({ type: "RESET_SESSION" });
  }, []);

  const clearError = useCallback(() => {
    dispatch({ type: "CLEAR_ERROR" });
  }, []);

  // The Factory/FactoryLayout backing the CURRENTLY SELECTED timeline
  // stage — falls back to the top-level pre-plan factory/layout when no
  // session exists yet. Never fabricated: either a real snapshot or the
  // real top-level state, nothing in between.
  const currentStageFactory = useCallback(() => {
    if (state.session) {
      return resolveStage(state.session, state.selectedIteration)?.snapshot.factory ?? state.factory;
    }
    return state.factory;
  }, [state.session, state.selectedIteration, state.factory]);

  // Phase 12.1 — goes through the shared resolver so entering EDIT mode
  // seeds the draft from the geometry actually on screen (including a
  // previously applied edit), rather than from the snapshot the user has
  // already moved away from.
  const currentStageLayout = useCallback(
    () => effectiveStageLayout(state, state.selectedIteration),
    [state],
  );

  const setEditMode = useCallback(
    (mode: EditMode) => {
      dispatch({ type: "SET_EDIT_MODE", mode });
    },
    [],
  );

  const enterEditMode = useCallback(() => {
    if (state.draftLayout) {
      dispatch({ type: "SET_EDIT_MODE", mode: "EDIT_LAYOUT" });
      return;
    }
    const factory = currentStageFactory();
    const layout = currentStageLayout();
    if (!factory) return;
    dispatch({ type: "START_DRAFT", draftLayout: layout ?? createEmptyDraft(factory) });
  }, [state.draftLayout, currentStageFactory, currentStageLayout]);

  const moveMachine = useCallback(
    (machineId: string, x: number, y: number) => {
      if (!state.draftLayout) return;
      dispatch({ type: "UPDATE_DRAFT", draftLayout: moveMachineDraft(state.draftLayout, machineId, x, y) });
    },
    [state.draftLayout],
  );

  const rotateMachine = useCallback(
    (machineId: string, rotationDeg: number) => {
      if (!state.draftLayout) return;
      dispatch({ type: "UPDATE_DRAFT", draftLayout: rotateMachineDraft(state.draftLayout, machineId, rotationDeg) });
    },
    [state.draftLayout],
  );

  const placeMachine = useCallback(
    (machineId: string, x: number, y: number) => {
      if (!state.draftLayout) return;
      dispatch({ type: "UPDATE_DRAFT", draftLayout: placeMachineDraft(state.draftLayout, machineId, x, y) });
    },
    [state.draftLayout],
  );

  const validateDraft = useCallback(async () => {
    const factory = currentStageFactory();
    if (!factory || !state.draftLayout) return;
    dispatch({ type: "VALIDATE_DRAFT_START" });
    try {
      const result = await validateLayout({
        factory,
        layout: state.draftLayout,
        product_id: state.productId ?? undefined,
      });
      dispatch({ type: "VALIDATE_DRAFT_SUCCESS", result });
      // Placement has its own evidence, entirely separate from throughput:
      // the simulator takes no layout, so a validated layout says the
      // stations fit and nothing whatsoever about how fast the line runs.
      dispatch({ type: "ARTIFACT_PRODUCED", artifact: "LAYOUT_VALIDATION" });
    } catch (error) {
      dispatch({ type: "VALIDATE_DRAFT_ERROR", error: classifyError(error) });
    }
  }, [currentStageFactory, state.draftLayout, state.productId]);

  const applyDraft = useCallback(() => {
    dispatch({ type: "APPLY_DRAFT" });
  }, []);

  const resetDraft = useCallback(() => {
    dispatch({ type: "RESET_DRAFT" });
  }, []);

  const setViewMode = useCallback((mode: ViewMode) => {
    dispatch({ type: "SET_VIEW_MODE", mode });
  }, []);

  const setViewLevel = useCallback((level: ViewLevel) => {
    dispatch({ type: "SET_VIEW_LEVEL", level });
  }, []);

  const setEngineeringTab = useCallback((tab: EngineeringTab) => {
    dispatch({ type: "SET_ENGINEERING_TAB", tab });
  }, []);

  // Phase 13: factory concept builder

  const setStartMode = useCallback((mode: StartMode) => {
    dispatch({ type: "SET_START_MODE", mode });
  }, []);

  /** Structure a customer brief into a concept draft. */
  const startConceptFromBrief = useCallback(async (brief: string, name?: string) => {
    if (!brief.trim()) return;
    dispatch({ type: "CONCEPT_EXTRACT_START" });
    try {
      const response = await conceptFromBrief(brief, name);
      dispatch({ type: "CONCEPT_UPDATED", draft: response.draft, validation: response.validation });
    } catch (error) {
      dispatch({ type: "CONCEPT_ERROR", error: classifyError(error) });
    }
  }, []);

  /** Fill the concept's missing ENGINEERING values from the bundled demo dataset. */
  const useExampleEngineeringData = useCallback(async () => {
    const draft = state.concept.draft;
    if (!draft) return;
    dispatch({ type: "CONCEPT_EXTRACT_START" });
    try {
      const response = await applyExampleData(draft);
      dispatch({ type: "CONCEPT_UPDATED", draft: response.draft, validation: response.validation });
    } catch (error) {
      dispatch({ type: "CONCEPT_ERROR", error: classifyError(error) });
    }
  }, [state.concept.draft]);

  /** Commit an edited draft and re-validate it. */
  const updateConceptDraft = useCallback(
    async (draft: FactoryConceptDraft) => {
      try {
        const validation = await validateConcept(draft);
        dispatch({ type: "CONCEPT_UPDATED", draft, validation });

        // If verified results exist, work out whether this edit invalidated
        // any of them. Done here rather than in the reducer because it is a
        // server call: the dependency graph lives with the engineering code
        // that owns it, not in the browser.
        const verifiedFrom = state.verifiedFrom;
        const hasResults = Boolean(state.session || state.arena);
        if (!verifiedFrom || !hasResults) return;

        const impact = await changeImpact(verifiedFrom, draft);
        dispatch({
          type: "RESULTS_STALE",
          stale: impact.stale.length
            ? {
                stale: impact.stale,
                unaffected: impact.unaffected,
                summary: impact.summary,
                changes: impact.changes.map((change) => change.description),
              }
            : null,
        });
      } catch (error) {
        dispatch({ type: "CONCEPT_ERROR", error: classifyError(error) });
      }
    },
    [state.verifiedFrom, state.session, state.arena],
  );

  /** Convert the concept into an ordinary Factory + initial layout. */
  const buildConceptFactory = useCallback(async () => {
    const draft = state.concept.draft;
    if (!draft) return;
    dispatch({ type: "CONCEPT_BUILD_START" });
    try {
      const response = await buildConcept(draft);
      dispatch({
        type: "CONCEPT_BUILD_SUCCESS",
        factory: response.factory,
        productId: response.product_id,
        layout: response.layout,
        validation: response.validation,
      });
      dispatch({ type: "ARTIFACT_PRODUCED", artifact: "CONCEPT" });
      // A rebuilt concept invalidates what the OLD one was evidence for, and
      // saying so is the store's job. Withdrawing the runs here rather than
      // waiting for an input diff covers the case where the concept was
      // rebuilt from an unchanged draft — the factory is new either way, and
      // a verification of the previous one is not evidence about it.
      dispatch({ type: "ARTIFACT_PRODUCED", artifact: "SIMULATION_VERIFICATION" });
    } catch (error) {
      dispatch({ type: "CONCEPT_ERROR", error: classifyError(error) });
    }
  }, [state.concept.draft]);

  /** Load the bundled demo line — the deterministic recovery path, and the
   * factory the frozen golden values belong to. */
  const openDemoFactory = useCallback(async () => {
    await loadExampleFactory();
    await loadExampleLayout();
    dispatch({ type: "SET_START_MODE", mode: "FACTORY_LOADED" });
  }, [loadExampleFactory, loadExampleLayout]);

  // Auto-validate on every draft change (move/rotate/place) — Phase 6B
  // section 4 ("on drop: ... call POST /layout/validate") and section 5
  // ("every committed rotation must be validated"). Driven by React's own
  // FRESH draftLayout, never a stale pre-update closure.
  useEffect(() => {
    if (state.draftLayout) {
      void validateDraft();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.draftLayout]);

  // P0 — autosave.
  //
  // Runs on every render, which is cheap: it serialises the engineering half
  // of the state and compares one string. Only a real difference arms the
  // timer, so idle renders (a panel opening, playback scrubbing) cost a
  // comparison and nothing else.
  //
  // It is deliberately NOT keyed on individual fields. The set of things
  // worth persisting is defined once, in `serializeProject`; making this
  // effect list them again would be a second definition, and the day the two
  // disagree is the day an edit stops being saved without anyone noticing.
  useEffect(() => {
    stateRef.current = state;
    if (!state.project.id) return;

    // Reference guard first. Every render reaches this effect, and most of
    // them changed nothing a project stores.
    const slices = [
      state.product,
      state.concept.draft,
      state.factory,
      state.layout,
      state.productId,
      state.verifiedFrom,
      state.appliedLayouts,
      state.arena,
      state.selectedStrategyId,
      state.exploreRequests,
      state.equipmentSelections,
      state.startMode,
      state.project.produced,
      state.project.name,
    ] as const;
    const unchanged =
      slices.length === slicesRef.current.length &&
      slices.every((slice, index) => slice === slicesRef.current[index]);
    slicesRef.current = slices;
    if (unchanged) return;

    const payload = serializeProject(state, storedRef.current);
    const fingerprint = projectFingerprint(payload);
    const changed = fingerprint !== savedFingerprintRef.current;
    const hasNewEvidence = payload.produced.length > 0;
    if (!changed && !hasNewEvidence) return;

    // Already armed for exactly this payload: leave the running timer alone.
    // Re-arming it on every render is how a debounce starves — a render loop
    // elsewhere in the app would push the save out indefinitely, and the
    // engineer would watch "Unsaved changes" never resolve.
    if (fingerprint === armedRef.current && saveTimerRef.current) return;
    armedRef.current = fingerprint;

    if (state.project.saveStatus !== "DIRTY" && state.project.saveStatus !== "SAVING") {
      dispatch({ type: "PROJECT_DIRTY" });
    }

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null;
      armedRef.current = null;
      const run = performSave();
      inFlightRef.current = run;
      void run.finally(() => {
        inFlightRef.current = null;
      });
    }, AUTOSAVE_DELAY_MS);
  });

  // The pending write is cancelled only when the provider goes away. It is
  // deliberately NOT cleaned up per render: the effect above has no
  // dependency array, so a per-render cleanup would clear the timer on every
  // unrelated update and the save would never land.
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // The recent-projects list, fetched once when the landing page first
  // appears. Not on every render of it: reopening the landing page after
  // closing a project refreshes explicitly (see `closeProject`), and polling
  // a list nobody is looking at is write churn with extra steps.
  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  // Phase 13 — the demo factory is no longer loaded on mount.
  //
  // Before this phase the app fetched the Electronics Assembly Line the
  // moment it started, which quietly asserted that a modelled factory always
  // exists. That is exactly the assumption this phase removes: an engineer
  // sitting with a customer has requirements, not a simulation model. The
  // demo line is now ONE of two explicit starting choices (see StartScreen),
  // and `openDemoFactory` loads it on that click — same endpoints, same
  // resulting state, just no longer implicit.

  const value = useMemo<AppContextValue>(
    () => ({
      state,
      loadExampleFactory,
      loadExampleLayout,
      setRequestText,
      runPlan,
      selectIteration,
      selectMachine,
      resetSession,
      clearError,
      currentStageFactory,
      currentStageLayout,
      setEditMode,
      enterEditMode,
      moveMachine,
      rotateMachine,
      placeMachine,
      validateDraft,
      applyDraft,
      resetDraft,
      confirmIterationSwitch,
      cancelIterationSwitch,
      setViewMode,
      setViewLevel,
      setEngineeringTab,
      setStartMode,
      startConceptFromBrief,
      useExampleEngineeringData,
      updateConceptDraft,
      buildConceptFactory,
      openDemoFactory,
      sendMessage,
      selectBranch,
      compareWithBranch,
      closeComparison,
      exploreOptions,
      selectStrategy,
      compareWithStrategy,
      closeStrategyComparison,
      askAboutOptions,
      openPlayback,
      viewStagePlayback,
      closePlayback,
      playPlayback,
      pausePlayback,
      resetPlayback,
      setPlaybackSpeed,
      seekPlayback,
      requestCameraFocus,
      clearCameraFocusRequest,
      refreshProjects,
      newProject,
      openExampleProject,
      openProject,
      closeProject,
      renameProject,
      removeProject,
      flushSave,
      recordArtifact,
      setProductField,
      productUnderstood,
      setProcessDraft,
      setCoverage,
      loadExampleSpecification,
      editProductInformation,
      setEquipmentSelection,
    }),
    [
      state,
      loadExampleFactory,
      loadExampleLayout,
      setRequestText,
      runPlan,
      selectIteration,
      selectMachine,
      resetSession,
      clearError,
      currentStageFactory,
      currentStageLayout,
      setEditMode,
      enterEditMode,
      moveMachine,
      rotateMachine,
      placeMachine,
      validateDraft,
      applyDraft,
      resetDraft,
      confirmIterationSwitch,
      cancelIterationSwitch,
      setViewMode,
      setViewLevel,
      setEngineeringTab,
      setStartMode,
      startConceptFromBrief,
      useExampleEngineeringData,
      updateConceptDraft,
      buildConceptFactory,
      openDemoFactory,
      sendMessage,
      selectBranch,
      compareWithBranch,
      closeComparison,
      exploreOptions,
      selectStrategy,
      compareWithStrategy,
      closeStrategyComparison,
      askAboutOptions,
      openPlayback,
      viewStagePlayback,
      closePlayback,
      playPlayback,
      pausePlayback,
      resetPlayback,
      setPlaybackSpeed,
      seekPlayback,
      requestCameraFocus,
      clearCameraFocusRequest,
      refreshProjects,
      newProject,
      openExampleProject,
      openProject,
      closeProject,
      renameProject,
      removeProject,
      flushSave,
      recordArtifact,
      setProductField,
      productUnderstood,
      setProcessDraft,
      setCoverage,
      loadExampleSpecification,
      editProductInformation,
      setEquipmentSelection,
    ],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useAppContext must be used within an AppProvider.");
  }
  return ctx;
}
