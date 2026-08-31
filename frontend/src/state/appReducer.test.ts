import { describe, expect, it } from "vitest";
import type { FactoryLayout, LayoutValidationResult } from "../api/types";
import { appReducer } from "./appReducer";
import { initialAppState } from "./types";

const draft: FactoryLayout = {
  factory_width: 20, factory_length: 10,
  placements: [{ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 }],
  reserved_zones: [], aisle_zones: [],
};

const invalidResult: LayoutValidationResult = {
  valid: false, error_count: 1, warning_count: 0,
  violations: [{ violation_type: "MACHINE_OVERLAP", severity: "ERROR", message: "overlap", machine_ids: ["m-a", "m-b"], zone_ids: [], details: null }],
};

const validResult: LayoutValidationResult = { valid: true, error_count: 0, warning_count: 0, violations: [] };

describe("appReducer — Phase 6B layout editor actions", () => {
  it("START_DRAFT seeds draftLayout, enters EDIT_LAYOUT, and starts clean (not dirty)", () => {
    const state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    expect(state.draftLayout).toBe(draft);
    expect(state.editMode).toBe("EDIT_LAYOUT");
    expect(state.isDirty).toBe(false);
    expect(state.layoutValidation).toBeNull();
  });

  it("UPDATE_DRAFT marks isDirty and clears any stale validation result", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    const moved: FactoryLayout = { ...draft, placements: [{ ...draft.placements[0], x: 8 }] };
    state = appReducer(state, { type: "UPDATE_DRAFT", draftLayout: moved });
    expect(state.draftLayout).toBe(moved);
    expect(state.isDirty).toBe(true);
    expect(state.layoutValidation).toBeNull(); // stale result cleared, not left misleadingly "valid"
  });

  it("VALIDATE_DRAFT_SUCCESS stores the backend-verified result verbatim", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: invalidResult });
    expect(state.layoutValidation).toBe(invalidResult);
  });

  it("APPLY_DRAFT is rejected (no-op) when the last validation has ERROR violations — invalid move never applied", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "UPDATE_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: invalidResult });
    const before = state;
    state = appReducer(state, { type: "APPLY_DRAFT" });
    expect(state).toBe(before); // unchanged
    expect(state.layout).toBeNull();
    expect(state.draftLayout).toBe(draft);
  });

  it("APPLY_DRAFT is rejected when validation has not run at all yet", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    const before = state;
    state = appReducer(state, { type: "APPLY_DRAFT" });
    expect(state).toBe(before);
  });

  it("APPLY_DRAFT commits the draft to state.layout when validation has zero errors — valid move applied", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });
    expect(state.layout).toBe(draft);
    expect(state.draftLayout).toBeNull();
    expect(state.isDirty).toBe(false);
    expect(state.editMode).toBe("VIEW");
  });

  it("RESET_DRAFT discards the draft and validation, returning to VIEW", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "UPDATE_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: invalidResult });
    state = appReducer(state, { type: "RESET_DRAFT" });
    expect(state.draftLayout).toBeNull();
    expect(state.layoutValidation).toBeNull();
    expect(state.isDirty).toBe(false);
    expect(state.editMode).toBe("VIEW");
  });

  it("REQUEST/CONFIRM_ITERATION_SWITCH discards the draft only on explicit confirm", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "UPDATE_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "REQUEST_ITERATION_SWITCH", selection: "final" });
    expect(state.pendingIterationSelection).toBe("final");
    expect(state.draftLayout).toBe(draft); // not discarded yet — pending confirm

    state = appReducer(state, { type: "CONFIRM_ITERATION_SWITCH" });
    expect(state.selectedIteration).toBe("final");
    expect(state.draftLayout).toBeNull();
    expect(state.pendingIterationSelection).toBeNull();
  });

  it("CANCEL_ITERATION_SWITCH keeps the draft and the current selection", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "REQUEST_ITERATION_SWITCH", selection: "final" });
    state = appReducer(state, { type: "CANCEL_ITERATION_SWITCH" });
    expect(state.pendingIterationSelection).toBeNull();
    expect(state.draftLayout).toBe(draft);
    expect(state.selectedIteration).toBe("baseline");
  });

  it("SET_VIEW_MODE (Phase 6C) only changes viewMode — never selection/editMode/draftLayout", () => {
    let state = appReducer(initialAppState, { type: "START_DRAFT", draftLayout: draft });
    state = appReducer(state, { type: "SELECT_MACHINE", machineId: "m-a" });
    const before = { ...state };
    state = appReducer(state, { type: "SET_VIEW_MODE", mode: "3D" });
    expect(state.viewMode).toBe("3D");
    expect(state.draftLayout).toBe(before.draftLayout);
    expect(state.editMode).toBe(before.editMode);
    expect(state.selectedMachineId).toBe(before.selectedMachineId);
  });
});
