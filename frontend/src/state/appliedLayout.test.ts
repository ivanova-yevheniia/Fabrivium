import { describe, expect, it } from "vitest";
import type { FactoryLayout, LayoutValidationResult } from "../api/types";
import { sampleSessionTwoIterations } from "../test/fixtures";
import { appReducer } from "./appReducer";
import { initialAppState } from "./types";
import type { AppState } from "./types";
import { effectiveStageLayout } from "../utils/stage";

/** Phase 12.1 — "Apply reverted my layout edit". */

const validResult: LayoutValidationResult = {
  valid: true,
  violations: [],
  error_count: 0,
  warning_count: 0,
};

/** The fixture session carries no layout, so this test builds the geometry
 * it needs and pins it onto the snapshots — the defect is about WHICH
 * layout is read for a stage, so each stage needs a distinguishable one. */
function layoutAt(x: number): FactoryLayout {
  return {
    factory_width: 20,
    factory_length: 10,
    placements: [{ machine_id: "m-a", x, y: 3, z: 0, rotation_deg: 0 }],
    reserved_zones: [],
    aisle_zones: [],
  };
}

const snapshotLayout = layoutAt(5);
const baselineLayout = layoutAt(1);

/** The same stage geometry with the machine moved — what a user drags to. */
const editedLayout = layoutAt(8);

const session = {
  ...sampleSessionTwoIterations,
  baseline_snapshot: { ...sampleSessionTwoIterations.baseline_snapshot, layout: baselineLayout },
  final_snapshot: { ...sampleSessionTwoIterations.final_snapshot, layout: snapshotLayout },
};

function sessionState(): AppState {
  return {
    ...initialAppState,
    session,
    selectedIteration: "final" as const,
  };
}

describe("applying a layout edit while a planning session is on screen", () => {
  it("records the applied geometry against the stage it was applied to", () => {
    let state: AppState = sessionState();
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(state.appliedLayouts["final"]).toBe(editedLayout);
    expect(state.draftLayout).toBeNull();
    expect(state.editMode).toBe("VIEW");
    expect(state.isDirty).toBe(false);
  });

  it("is what the workspace then resolves for that stage — the edit does not revert", () => {
    let state: AppState = sessionState();
    // Before applying, the stage resolves to the snapshot's own geometry.
    expect(effectiveStageLayout(state, "final")).toBe(snapshotLayout);

    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(effectiveStageLayout(state, "final")).toBe(editedLayout);
  });

  it("never mutates the verified snapshot the simulation ran on", () => {
    let state: AppState = sessionState();
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(state.session?.final_snapshot.layout).toBe(snapshotLayout);
    expect(state.session).toBe(session);
  });

  it("applies to the SELECTED stage only — other stages keep their own geometry", () => {
    let state: AppState = sessionState();
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(effectiveStageLayout(state, "final")).toBe(editedLayout);
    expect(effectiveStageLayout(state, "baseline")).toBe(baselineLayout);
  });

  it("still refuses to apply a draft whose validation reported errors", () => {
    let state: AppState = sessionState();
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, {
      type: "VALIDATE_DRAFT_SUCCESS",
      result: { valid: false, violations: [], error_count: 1, warning_count: 0 },
    });
    const before = state;
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(state).toBe(before);
    expect(state.appliedLayouts["final"]).toBeUndefined();
    expect(effectiveStageLayout(state, "final")).toBe(snapshotLayout);
  });

  it("retires applied placements when a new verified session replaces the old one", () => {
    // A new session's snapshots carry their own geometry and may contain
    // machines this layout has never heard of, so the overlay must not
    // survive into it.
    let state: AppState = sessionState();
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });
    expect(state.appliedLayouts["final"]).toBe(editedLayout);

    state = appReducer(state, { type: "RESET_SESSION" });
    expect(state.appliedLayouts).toEqual({});
  });
});

describe("applying a layout edit with no planning session", () => {
  it("commits to the factory's base layout, exactly as before", () => {
    let state: AppState = { ...initialAppState };
    state = appReducer(state, { type: "START_DRAFT", draftLayout: editedLayout });
    state = appReducer(state, { type: "VALIDATE_DRAFT_SUCCESS", result: validResult });
    state = appReducer(state, { type: "APPLY_DRAFT" });

    expect(state.layout).toBe(editedLayout);
    // No session means no stage to key an overlay against.
    expect(state.appliedLayouts).toEqual({});
    expect(effectiveStageLayout(state, "baseline")).toBe(editedLayout);
  });
});
