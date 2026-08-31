import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { AppContext } from "../state/AppContext";
import type { AppContextValue } from "../state/AppContext";
import { initialAppState } from "../state/types";
import type { AppState } from "../state/types";

/** Builds a full AppContextValue for tests, seeding `state` exactly and
 * stubbing every action creator as a no-op spy unless overridden — lets a
 * component test assert on rendering without driving the real
 * reducer/fetch machinery (see src/state/AppContext.tsx's exported
 * AppContext). */
export function makeContextValue(stateOverrides: Partial<AppState>, actionOverrides: Partial<AppContextValue> = {}): AppContextValue {
  return {
    state: { ...initialAppState, ...stateOverrides },
    loadExampleFactory: vi.fn(async () => {}),
    loadExampleLayout: vi.fn(async () => {}),
    setRequestText: vi.fn(),
    runPlan: vi.fn(async () => {}),
    selectIteration: vi.fn(),
    selectMachine: vi.fn(),
    resetSession: vi.fn(),
    clearError: vi.fn(),
    currentStageFactory: vi.fn(() => stateOverrides.factory ?? null),
    currentStageLayout: vi.fn(() => stateOverrides.layout ?? null),
    setEditMode: vi.fn(),
    enterEditMode: vi.fn(),
    moveMachine: vi.fn(),
    rotateMachine: vi.fn(),
    placeMachine: vi.fn(),
    validateDraft: vi.fn(async () => {}),
    applyDraft: vi.fn(),
    resetDraft: vi.fn(),
    confirmIterationSwitch: vi.fn(),
    cancelIterationSwitch: vi.fn(),
    setViewMode: vi.fn(),
    setViewLevel: vi.fn(),
    setEngineeringTab: vi.fn(),
    setStartMode: vi.fn(),
    startConceptFromBrief: vi.fn(async () => {}),
    useExampleEngineeringData: vi.fn(async () => {}),
    updateConceptDraft: vi.fn(async () => {}),
    buildConceptFactory: vi.fn(async () => {}),
    openDemoFactory: vi.fn(async () => {}),
    sendMessage: vi.fn(async () => {}),
    selectBranch: vi.fn(),
    compareWithBranch: vi.fn(async () => {}),
    closeComparison: vi.fn(),
    exploreOptions: vi.fn(async () => {}),
    selectStrategy: vi.fn(),
    compareWithStrategy: vi.fn(async () => {}),
    closeStrategyComparison: vi.fn(),
    askAboutOptions: vi.fn(async () => {}),
    openPlayback: vi.fn(async () => {}),
    viewStagePlayback: vi.fn(async () => {}),
    closePlayback: vi.fn(),
    playPlayback: vi.fn(),
    pausePlayback: vi.fn(),
    resetPlayback: vi.fn(),
    setPlaybackSpeed: vi.fn(),
    seekPlayback: vi.fn(),
    requestCameraFocus: vi.fn(),
    clearCameraFocusRequest: vi.fn(),
    refreshProjects: vi.fn(async () => {}),
    newProject: vi.fn(async () => {}),
    openExampleProject: vi.fn(async () => {}),
    openProject: vi.fn(async () => {}),
    closeProject: vi.fn(),
    renameProject: vi.fn(),
    removeProject: vi.fn(async () => {}),
    flushSave: vi.fn(async () => {}),
    recordArtifact: vi.fn(),
    setProductField: vi.fn(),
    productUnderstood: vi.fn(),
    setProcessDraft: vi.fn(),
    setCoverage: vi.fn(),
    loadExampleSpecification: vi.fn(async () => {}),
    editProductInformation: vi.fn(),
    setEquipmentSelection: vi.fn(),
    ...actionOverrides,
  };
}

export function renderWithContext(
  ui: ReactElement,
  stateOverrides: Partial<AppState> = {},
  actionOverrides: Partial<AppContextValue> = {},
) {
  const value = makeContextValue(stateOverrides, actionOverrides);
  return { ...render(<AppContext.Provider value={value}>{ui}</AppContext.Provider>), contextValue: value };
}
