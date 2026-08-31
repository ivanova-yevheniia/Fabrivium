import { describe, expect, it } from "vitest";
import { appReducer } from "./appReducer";
import { hydrateProject, serializeProject } from "./projectSerialization";
import { initialAppState } from "./types";
import type { AppState } from "./types";
import type { EquipmentSelectionMetadata } from "../api/handoff";
import type { ProjectDocument, StaleReport } from "../api/projects";
import { emptyProjectState } from "../api/projects";

/**
 * One current selection per station, a trail of the ones it replaced, and a
 * selection that survives a reload carrying the evidence to check it by.
 *
 * The audit trail is not bookkeeping for its own sake. An engineer who tried
 * three candidates and settled on the second made an engineering decision,
 * and the two they rejected are part of why — a choice with no record of what
 * it was chosen over is a choice nobody can review.
 */

const NO_STALENESS: StaleReport = {
  stale: [],
  current: [],
  unverified: [],
  summary: "",
};

function selection(
  candidateId: string,
  model: string,
  at: string,
): EquipmentSelectionMetadata {
  return {
    candidate_id: candidateId,
    manufacturer: "Kolver S.r.l.",
    model,
    source_url: "https://kolver.com/catalog.pdf",
    station_id: "m-screwdriving",
    selected_at: at,
    bounds: [
      { field: "station_id", label: "Station", unit: null, value: "m-screwdriving" },
      { field: "cycle_time", label: "Cycle time", unit: "s", value: 39 },
    ],
  };
}

function choose(state: AppState, chosen: EquipmentSelectionMetadata): AppState {
  return appReducer(state, {
    type: "EQUIPMENT_SELECTION_SET",
    stationId: "m-screwdriving",
    selection: chosen,
  });
}

describe("one current selection per station", () => {
  it("records the chosen candidate", () => {
    const state = choose(initialAppState, selection("c-a", "KDS-NT120CA", "2026-08-26T10:00:00Z"));
    expect(state.equipmentSelections["m-screwdriving"].candidate_id).toBe("c-a");
  });

  it("leaves exactly one current selection after a replacement", () => {
    let state = choose(initialAppState, selection("c-a", "KDS-NT120CA", "2026-08-26T10:00:00Z"));
    state = choose(state, selection("c-b", "KBL30FR/CA", "2026-08-26T11:00:00Z"));

    const current = state.equipmentSelections["m-screwdriving"];
    expect(current.candidate_id).toBe("c-b");
    expect(current.model).toBe("KBL30FR/CA");
    expect(Object.keys(state.equipmentSelections)).toHaveLength(1);
  });

  it("keeps the replaced candidate in the audit trail", () => {
    let state = choose(initialAppState, selection("c-a", "KDS-NT120CA", "2026-08-26T10:00:00Z"));
    state = choose(state, selection("c-b", "KBL30FR/CA", "2026-08-26T11:00:00Z"));

    const trail = state.equipmentSelections["m-screwdriving"].superseded ?? [];
    expect(trail).toHaveLength(1);
    expect(trail[0].candidate_id).toBe("c-a");
    expect(trail[0].model).toBe("KDS-NT120CA");
    expect(trail[0].superseded_at).toBe("2026-08-26T11:00:00Z");
  });

  it("accumulates the trail across several replacements, oldest first", () => {
    let state = choose(initialAppState, selection("c-a", "A", "2026-08-26T10:00:00Z"));
    state = choose(state, selection("c-b", "B", "2026-08-26T11:00:00Z"));
    state = choose(state, selection("c-c", "C", "2026-08-26T12:00:00Z"));

    const current = state.equipmentSelections["m-screwdriving"];
    expect(current.model).toBe("C");
    expect((current.superseded ?? []).map((s) => s.model)).toEqual(["A", "B"]);
  });

  it("does not record a supersession when the same candidate is re-selected", () => {
    // Pressing the button twice is not an engineering decision to review.
    let state = choose(initialAppState, selection("c-a", "A", "2026-08-26T10:00:00Z"));
    state = choose(state, selection("c-a", "A", "2026-08-26T10:05:00Z"));
    expect(state.equipmentSelections["m-screwdriving"].superseded).toEqual([]);
  });

  it("clears the station when the selection is withdrawn", () => {
    let state = choose(initialAppState, selection("c-a", "A", "2026-08-26T10:00:00Z"));
    state = appReducer(state, {
      type: "EQUIPMENT_SELECTION_SET",
      stationId: "m-screwdriving",
      selection: null,
    });
    expect(state.equipmentSelections["m-screwdriving"]).toBeUndefined();
  });

  it("keeps stations independent of one another", () => {
    let state = choose(initialAppState, selection("c-a", "A", "2026-08-26T10:00:00Z"));
    state = appReducer(state, {
      type: "EQUIPMENT_SELECTION_SET",
      stationId: "m-inspection",
      selection: { ...selection("c-z", "Z", "2026-08-26T10:00:00Z"), station_id: "m-inspection" },
    });

    expect(state.equipmentSelections["m-screwdriving"].candidate_id).toBe("c-a");
    expect(state.equipmentSelections["m-inspection"].candidate_id).toBe("c-z");
    expect(state.equipmentSelections["m-inspection"].superseded).toEqual([]);
  });
});

describe("a selection that survives a reload", () => {
  function documentFrom(state: AppState): ProjectDocument {
    return {
      schema_version: 1,
      project_id: "p-1",
      name: "Line",
      created_at: "2026-08-26T09:00:00Z",
      updated_at: "2026-08-26T12:00:00Z",
      state: serializeProject(state, emptyProjectState()),
    };
  }

  it("comes back with the candidate, the bounds and the trail intact", () => {
    let state: AppState = { ...initialAppState, project: { ...initialAppState.project, id: "p-1" } };
    state = choose(state, selection("c-a", "A", "2026-08-26T10:00:00Z"));
    state = choose(state, selection("c-b", "B", "2026-08-26T11:00:00Z"));

    const restored = {
      ...initialAppState,
      ...hydrateProject(documentFrom(state), NO_STALENESS),
    };
    const current = restored.equipmentSelections["m-screwdriving"];

    expect(current.candidate_id).toBe("c-b");
    // The evidence to CHECK the selection by, not just the selection.
    expect(current.bounds).toEqual([
      { field: "station_id", label: "Station", unit: null, value: "m-screwdriving" },
      { field: "cycle_time", label: "Cycle time", unit: "s", value: 39 },
    ]);
    expect((current.superseded ?? []).map((s) => s.model)).toEqual(["A"]);
  });

  it("carries the manufacturer and model the Siemens exchange reads", () => {
    // from_factory.py reads exactly these three keys off each selection and
    // ignores the rest, so they must survive the round trip unchanged.
    let state: AppState = { ...initialAppState, project: { ...initialAppState.project, id: "p-1" } };
    state = choose(state, selection("c-a", "KDS-NT120CA", "2026-08-26T10:00:00Z"));

    const restored = {
      ...initialAppState,
      ...hydrateProject(documentFrom(state), NO_STALENESS),
    };
    const current = restored.equipmentSelections["m-screwdriving"];
    expect(current.manufacturer).toBe("Kolver S.r.l.");
    expect(current.model).toBe("KDS-NT120CA");
    expect(current.source_url).toBe("https://kolver.com/catalog.pdf");
  });
});

describe("what selecting equipment must not do", () => {
  it("changes no verified engineering value on the concept", () => {
    // E5 of the P0 pass, restated here because this is the phase that could
    // break it: a candidate is equipment under consideration, and adopting a
    // manufacturer's figure is a separate, explicit act.
    const before: AppState = {
      ...initialAppState,
      concept: {
        ...initialAppState.concept,
        draft: {
          stages: [{ id: "m-screwdriving", cycle_time: { value: 39, source: "ENGINEER" } }],
        } as never,
      },
    };
    const after = choose(before, selection("c-a", "A", "2026-08-26T10:00:00Z"));

    expect(after.concept.draft).toBe(before.concept.draft);
    expect(after.factory).toBe(before.factory);
    expect(after.arena).toBe(before.arena);
  });
});
