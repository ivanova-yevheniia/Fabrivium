import { describe, expect, it } from "vitest";
import { appReducer } from "./appReducer";
import { hydrateProject, projectFingerprint, serializeProject } from "./projectSerialization";
import { initialAppState } from "./types";
import type { AppState } from "./types";
import type { ProjectDocument, StaleReport } from "../api/projects";
import { emptyProjectState } from "../api/projects";
import { estimatorContext, staleEstimate } from "../api/operationContext";
import type { ConceptStage } from "../api/types";
import type { ManufacturingProcessDraft, ProposedOperation } from "../api/product";

/** P0 §I tests 1, 2, 13 and 20, at the level where they are actually decided. */

const NO_STALENESS: StaleReport = {
  stale: [],
  current: [],
  unverified: [],
  summary: "Nothing has been verified yet.",
};

function populated(): AppState {
  return {
    ...initialAppState,
    startMode: "FACTORY_LOADED",
    factory: { id: "f-1", name: "Controller line" } as never,
    layout: { placements: [{ machine_id: "m1", x: 1, y: 2, rotation_deg: 0 }] } as never,
    productId: "p-controller",
    verifiedFrom: { name: "Controller line" } as never,
    appliedLayouts: { baseline: { placements: [] } as never },
    arena: { product_id: "p-controller", strategies: [] } as never,
    selectedStrategyId: "s-2",
    exploreRequests: ["reach 1900 a day"],
    establishedCosts: [
      { gap_type: "SHIFT_COST", amount: 18000, category: "OPEX_PER_DAY", note: "" },
    ],
    concept: { ...initialAppState.concept, draft: { name: "Controller line" } as never },
    equipmentSelections: {
      "m-screwdriving": { manufacturer: "Atlas Copco", model: "MicroTorque 40", source_url: null },
    },
    product: {
      ...initialAppState.product,
      name: "Compact electronics controller",
      description: "Six screws secure the lid.",
      fromExample: true,
      understanding: { product_name: "Compact electronics controller", facts: [] } as never,
      modelUsed: false,
      process: { product_name: "CEC-120", operations: [] } as never,
      coverage: { items: [], summary: "", complete: true } as never,
      requirementsText: "1,900 units per day across 2 shifts of 8 hours.",
    },
    project: {
      ...initialAppState.project,
      id: "p-1",
      name: "Controller line — Plant 2",
      isExample: true,
    },
  };
}

function documentFrom(state: AppState): ProjectDocument {
  return {
    schema_version: 1,
    project_id: "p-1",
    name: state.project.name,
    created_at: "2026-08-01T09:00:00.000000+00:00",
    updated_at: "2026-08-20T09:00:00.000000+00:00",
    state: serializeProject(state, emptyProjectState()),
  };
}

describe("what a project remembers", () => {
  it("round-trips every engineering field", () => {
    const before = populated();
    const restored = { ...initialAppState, ...hydrateProject(documentFrom(before), NO_STALENESS) };

    expect(restored.product.name).toBe("Compact electronics controller");
    expect(restored.product.description).toBe("Six screws secure the lid.");
    expect(restored.product.fromExample).toBe(true);
    expect(restored.product.understanding).toEqual(before.product.understanding);
    expect(restored.product.process).toEqual(before.product.process);
    expect(restored.product.coverage).toEqual(before.product.coverage);
    expect(restored.product.requirementsText).toBe(before.product.requirementsText);

    expect(restored.concept.draft).toEqual(before.concept.draft);
    expect(restored.factory).toEqual(before.factory);
    expect(restored.productId).toBe("p-controller");
    expect(restored.layout).toEqual(before.layout);
    expect(restored.verifiedFrom).toEqual(before.verifiedFrom);
    expect(restored.appliedLayouts).toEqual(before.appliedLayouts);

    expect(restored.arena).toEqual(before.arena);
    expect(restored.selectedStrategyId).toBe("s-2");
    expect(restored.exploreRequests).toEqual(["reach 1900 a day"]);
    // G13 (C): a cost the engineer stated is an input, and reopening the
    // project must give it back — including the category, which is what
    // makes it an operating cost per day rather than a number.
    expect(restored.establishedCosts).toEqual(before.establishedCosts);
    expect(restored.equipmentSelections).toEqual(before.equipmentSelections);

    expect(restored.project.id).toBe("p-1");
    expect(restored.project.name).toBe("Controller line — Plant 2");
    expect(restored.project.isExample).toBe(true);
    expect(restored.project.schemaVersion).toBe(1);
  });

  it("lands a verified project back on the workspace, not at the first question", () => {
    const restored = hydrateProject(documentFrom(populated()), NO_STALENESS);
    expect(restored.startMode).toBe("FACTORY_LOADED");
  });

  it("falls back rather than showing a verified screen with nothing behind it", () => {
    // A project recorded as WORKSPACE whose factory did not survive is a
    // shape mismatch, not an invitation to render an empty results page.
    const document = documentFrom(populated());
    document.state.concept.factory = null;
    document.state.concept.product_id = null;

    const restored = hydrateProject(document, NO_STALENESS);
    expect(restored.startMode).not.toBe("FACTORY_LOADED");
  });

  it("does not persist transient interface state", () => {
    const noisy: AppState = {
      ...populated(),
      selectedMachineId: "m-1",
      draftLayout: { placements: [] } as never,
      isDirty: true,
      playback: { ...initialAppState.playback, active: true, simTime: 42 },
      viewMode: "3D",
    };

    const restored = { ...initialAppState, ...hydrateProject(documentFrom(noisy), NO_STALENESS) };
    expect(restored.selectedMachineId).toBeNull();
    expect(restored.draftLayout).toBeNull();
    expect(restored.isDirty).toBe(false);
    expect(restored.playback.active).toBe(false);
  });

  it("never authors the server's revision bookkeeping", () => {
    const stored = emptyProjectState();
    stored.revisions = { SIMULATION_INPUTS: 7 };
    stored.evidence = { SIMULATION_VERIFICATION: { revisions: { SIMULATION_INPUTS: 7 } } };
    stored.history = [{ seq: 1, channel: "SIMULATION_INPUTS", description: "cycle time: 48 → 44" }];

    const payload = serializeProject(populated(), stored);
    expect(payload.revisions).toEqual(stored.revisions);
    expect(payload.evidence).toEqual(stored.evidence);
    expect(payload.history).toEqual(stored.history);
  });

  it("sends the artifacts the client has produced, and nothing else", () => {
    const state = { ...populated(), project: { ...populated().project, produced: ["CONCEPT" as const] } };
    expect(serializeProject(state, emptyProjectState()).produced).toEqual(["CONCEPT"]);
  });
});

describe("the change fingerprint", () => {
  it("moves when an engineering value moves", () => {
    const before = populated();
    const after: AppState = {
      ...before,
      product: { ...before.product, requirementsText: "2,400 units per day." },
    };

    expect(projectFingerprint(serializeProject(after, emptyProjectState()))).not.toBe(
      projectFingerprint(serializeProject(before, emptyProjectState())),
    );
  });

  it("does not move when only the interface moves", () => {
    // Otherwise opening a panel or scrubbing playback would schedule a
    const before = populated();
    const after: AppState = { ...before, viewMode: "3D", selectedMachineId: "m-9" };

    expect(projectFingerprint(serializeProject(after, emptyProjectState()))).toBe(
      projectFingerprint(serializeProject(before, emptyProjectState())),
    );
  });

  it("ignores the produced list, which is an instruction and not content", () => {
    const before = populated();
    const after: AppState = {
      ...before,
      project: { ...before.project, produced: ["SIMULATION_VERIFICATION"] },
    };

    expect(projectFingerprint(serializeProject(after, emptyProjectState()))).toBe(
      projectFingerprint(serializeProject(before, emptyProjectState())),
    );
  });
});

describe("two projects", () => {
  it("do not bleed into one another when one is opened over the other", () => {
    const first = populated();
    const second = documentFrom({
      ...initialAppState,
      product: { ...initialAppState.product, name: "Sensor module" },
      project: { ...initialAppState.project, id: "p-2", name: "Sensor line" },
    });
    second.project_id = "p-2";
    second.name = "Sensor line";

    const opened = appReducer(first, {
      type: "PROJECT_OPENED",
      document: second,
      staleness: NO_STALENESS,
    });

    expect(opened.project.id).toBe("p-2");
    expect(opened.product.name).toBe("Sensor module");
    // Nothing of the first project survives: not its factory, not its
    // results, not the equipment it was considering.
    expect(opened.factory).toBeNull();
    expect(opened.arena).toBeNull();
    expect(opened.selectedStrategyId).toBeNull();
    expect(opened.equipmentSelections).toEqual({});
    expect(opened.concept.draft).toBeNull();
    expect(opened.product.requirementsText).toBe("");
  });

  it("keeps the recent list, which belongs to the workspace rather than to one project", () => {
    const withList: AppState = {
      ...initialAppState,
      project: {
        ...initialAppState.project,
        recent: [
          {
            project_id: "p-1",
            name: "Controller line",
            created_at: "",
            updated_at: "",
            product_name: "",
            is_example: false,
          },
        ],
      },
    };

    const opened = appReducer(withList, {
      type: "PROJECT_OPENED",
      document: documentFrom(populated()),
      staleness: NO_STALENESS,
    });
    expect(opened.project.recent).toHaveLength(1);
  });

  it("returns to a clean workspace when a project is closed", () => {
    const closed = appReducer(populated(), { type: "PROJECT_CLOSED" });
    expect(closed.startMode).toBe("PROJECTS");
    expect(closed.project.id).toBeNull();
    expect(closed.factory).toBeNull();
    expect(closed.product.name).toBe("");
  });
});

describe("save bookkeeping", () => {
  it("clears the produced list once the server has stamped it", () => {
    const dirty: AppState = {
      ...populated(),
      project: { ...populated().project, produced: ["CONCEPT"], saveStatus: "SAVING" },
    };

    const saved = appReducer(dirty, {
      type: "PROJECT_SAVED",
      document: documentFrom(populated()),
      staleness: NO_STALENESS,
    });

    expect(saved.project.produced).toEqual([]);
    expect(saved.project.saveStatus).toBe("SAVED");
  });

  it("reports a failed save rather than swallowing it", () => {
    const failed = appReducer(populated(), {
      type: "PROJECT_SAVE_ERROR",
      message: "Backend unavailable",
    });

    expect(failed.project.saveStatus).toBe("ERROR");
    expect(failed.project.saveError).toBe("Backend unavailable");
  });

  it("records a produced artifact once, however many times it is reported", () => {
    let state = appReducer(populated(), { type: "ARTIFACT_PRODUCED", artifact: "CONCEPT" });
    state = appReducer(state, { type: "ARTIFACT_PRODUCED", artifact: "CONCEPT" });
    expect(state.project.produced).toEqual(["CONCEPT"]);
  });
});

describe("re-reading a product", () => {
  it("drops the route derived from the facts that were replaced", () => {
    // The old operations answer the OLD facts. Leaving them on screen under
    // a fresh reading is the exact "stale masquerading as current" failure
    // this phase exists to close.
    const state = appReducer(populated(), {
      type: "PRODUCT_UNDERSTOOD",
      understanding: { product_name: "Controller", facts: [] } as never,
      modelUsed: false,
    });

    expect(state.product.process).toBeNull();
    expect(state.product.coverage).toBeNull();
    expect(state.product.editing).toBe(false);
  });

  it("keeps the facts and the route when the form is merely reopened", () => {
    const state = appReducer(populated(), { type: "PRODUCT_EDIT_REOPENED" });

    expect(state.product.editing).toBe(true);
    expect(state.product.understanding).not.toBeNull();
    expect(state.product.process).not.toBeNull();
    expect(state.startMode).toBe("PRODUCT_FIRST");
  });
});


describe("what the estimator knows after a project is reopened", () => {
  /** G10/G11 — provenance is only worth something if it comes back. */
  const operation = {
    id: "op-screws",
    process_type: "screwdriving",
    name: "Screw fastening",
    description: "Screw fastening, 6 times per unit, implied by screws.",
    repeated_operations: 6,
    basis: "The specification lists 6 × M3 screws.",
    source_fact_keys: [],
    evidence: [],
    fact_status: "STATED",
    confidence: "HIGH",
    status: "ACCEPTED",
  } as ProposedOperation;

  const station = {
    id: "m-screwdriving",
    name: "Screw fastening",
    process_type: "screwdriving",
    cycle_time: { value: 48, source: "ENGINEERING_ESTIMATE", detail: "35–55 s" },
    capacity: { value: null, source: "UNKNOWN", detail: null },
    operators_required: { value: null, source: "UNKNOWN", detail: null },
    width: { value: null, source: "UNKNOWN", detail: null },
    length: { value: null, source: "UNKNOWN", detail: null },
    purchase_cost: { value: null, source: "UNKNOWN", detail: null },
    source_operation_id: "op-screws",
    cycle_time_estimate: { operations_per_unit: 6 },
  } as unknown as ConceptStage;

  function saved(route: ManufacturingProcessDraft) {
    const before: AppState = {
      ...populated(),
      concept: {
        ...initialAppState.concept,
        draft: { name: "Controller line", stages: [station] } as never,
      },
      product: { ...populated().product, process: route },
    };
    return { ...initialAppState, ...hydrateProject(documentFrom(before), NO_STALENESS) };
  }

  const route = (...operations: ProposedOperation[]) =>
    ({
      product_name: "CEC-120",
      operations,
      planner: "deterministic",
      method: "RULES",
      model_name: null,
      open_questions: [],
    }) as ManufacturingProcessDraft;

  it("still opens on the reviewed count, and still says where it came from", () => {
    const restored = saved(route(operation));
    const context = estimatorContext(restored.concept.draft!.stages[0], restored.product.process);

    expect(context.repeats).toBe(6);
    expect(context.repeatSource).toBe("PROCESS");
    expect(context.description).toBe("Screw fastening, 6 times per unit, implied by screws.");
  });

  it("still knows the estimate was composed under a count the route has since changed", () => {
    const restored = saved(route({ ...operation, repeated_operations: 4 }));
    const stage = restored.concept.draft!.stages[0];

    expect(staleEstimate(stage, restored.product.process)).toEqual({ estimatedFor: 6, reviewedAs: 4 });
    expect(estimatorContext(stage, restored.product.process).repeats).toBe(4);
  });
});
