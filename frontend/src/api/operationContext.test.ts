import { describe, expect, it } from "vitest";
import { estimatorContext, reviewedOperation, staleEstimate } from "./operationContext";
import type { ManufacturingProcessDraft, ProposedOperation } from "./product";
import type { ConceptStage } from "./types";

/** G10/G11 — what the estimator is allowed to open with. */

function operation(overrides: Partial<ProposedOperation> = {}): ProposedOperation {
  return {
    id: "op-1",
    process_type: "screwdriving",
    name: "Screw fastening",
    description: "Screw fastening, 6 times per unit, implied by screws.",
    repeated_operations: 6,
    basis: "The specification lists 6 × M3 screws.",
    source_fact_keys: [],
    evidence: [],
    fact_status: "STATED" as ProposedOperation["fact_status"],
    confidence: "HIGH",
    status: "ACCEPTED",
    ...overrides,
  };
}

function process(...operations: ProposedOperation[]): ManufacturingProcessDraft {
  return {
    product_name: "Compact electronics controller",
    operations,
    planner: "deterministic",
    method: "RULES",
    model_name: null,
    open_questions: [],
  };
}

function sourced(value: number | null, source: string, detail: string | null = null) {
  return { value, source, detail } as ConceptStage["cycle_time"];
}

function stage(overrides: Partial<ConceptStage> = {}): ConceptStage {
  return {
    id: "m-screwdriving",
    name: "Screw fastening",
    process_type: "screwdriving",
    cycle_time: sourced(null, "UNKNOWN"),
    capacity: sourced(null, "UNKNOWN"),
    operators_required: sourced(null, "UNKNOWN"),
    width: sourced(null, "UNKNOWN"),
    length: sourced(null, "UNKNOWN"),
    purchase_cost: sourced(null, "UNKNOWN"),
    source_operation_id: "op-1",
    ...overrides,
  };
}

/** A station whose cycle time came from an estimate composed for `repeats`. */
function estimated(repeats: number | null, overrides: Partial<ConceptStage> = {}): ConceptStage {
  return stage({
    cycle_time: sourced(48, "ENGINEERING_ESTIMATE", "35–55 s, medium confidence"),
    cycle_time_estimate: { operations_per_unit: repeats },
    ...overrides,
  });
}

describe("what the estimator opens with", () => {
  it("carries a reviewed repeat count through without it being retyped", () => {
    // The reported defect, at its smallest: the process says six, so the
    // estimator opens on six.
    const context = estimatorContext(stage(), process(operation()));

    expect(context.repeats).toBe(6);
    expect(context.repeatSource).toBe("PROCESS");
  });

  it("carries whatever count the operation actually states", () => {
    // Two per unit is not a special case of six per unit, and neither is a
    // rule about a named operation: the station reads its own.
    const cable = operation({
      id: "op-2",
      process_type: "connection",
      name: "Cable connection",
      description: "Cable connection, 2 times per unit.",
      repeated_operations: 2,
    });
    const context = estimatorContext(
      stage({ id: "m-connection", name: "Cable connection", source_operation_id: "op-2" }),
      process(cable),
    );

    expect(context.repeats).toBe(2);
    expect(context.repeatSource).toBe("PROCESS");
  });

  it("records one where the process explicitly records one", () => {
    const context = estimatorContext(
      stage({ source_operation_id: "op-3" }),
      process(operation({ id: "op-3", name: "Product labelling", repeated_operations: 1 })),
    );
    expect(context.repeats).toBe(1);
  });

  it("stays empty when nothing knows the count", () => {
    // An unstated repeat count is not a repeat count of one. The field is
    // blank and says so, which is the state the engineer can act on.
    const context = estimatorContext(
      stage(),
      process(operation({ repeated_operations: null })),
    );

    expect(context.repeats).toBeNull();
    expect(context.repeatSource).toBe("NONE");
  });

  it("prefills the description the engineer already reviewed", () => {
    const context = estimatorContext(stage(), process(operation()));

    expect(context.description).toBe("Screw fastening, 6 times per unit, implied by screws.");
    expect(context.descriptionFromProcess).toBe(true);
  });

  it("falls back to the operation name when it has no description", () => {
    const context = estimatorContext(stage(), process(operation({ description: "" })));
    expect(context.description).toBe("Screw fastening");
  });

  it("knows nothing about a station built by hand from a brief", () => {
    // No reviewed operation exists behind it. The panel opens exactly as
    // empty as it always did, rather than borrowing another station's facts.
    const context = estimatorContext(stage({ source_operation_id: null }), process(operation()));

    expect(context.operation).toBeNull();
    expect(context.repeats).toBeNull();
    expect(context.description).toBe("");
  });

  it("ignores an operation the engineer rejected", () => {
    const context = estimatorContext(stage(), process(operation({ status: "REJECTED" })));
    expect(context.operation).toBeNull();
  });

  it("keeps the context of an operation the engineer edited and kept", () => {
    // MODIFIED is an operation someone took responsibility for. Dropping its
    // context would punish the engineer for correcting it.
    const context = estimatorContext(
      stage(),
      process(operation({ status: "MODIFIED", repeated_operations: 4 })),
    );
    expect(context.repeats).toBe(4);
  });

  it("survives a rename of the operation", () => {
    // Matched by id. Renaming an operation renames one thing; it does not
    // detach the station from the route.
    const renamed = operation({ name: "Fastening (M3)" });
    expect(reviewedOperation(stage(), process(renamed))?.repeated_operations).toBe(6);
  });
});

describe("a reviewed change is never overridden by an older estimate", () => {
  it("opens on the new count after the route is edited from 6 to 4", () => {
    // The exact sequence from the defect report: estimate accepted at six,
    // process later edited to four. Reopening must show four.
    const station = estimated(6);
    const context = estimatorContext(station, process(operation({ repeated_operations: 4 })));

    expect(context.repeats).toBe(4);
    expect(context.repeatSource).toBe("PROCESS");
  });

  it("marks that station's estimate stale, and says both numbers", () => {
    const stale = staleEstimate(estimated(6), process(operation({ repeated_operations: 4 })));

    expect(stale).toEqual({ estimatedFor: 6, reviewedAs: 4 });
  });

  it("leaves unrelated stations alone", () => {
    // Changing how many screws go into an enclosure says nothing about the
    // labelling station, and invalidating it too would teach engineers that
    // the warning means nothing.
    const labelling = estimated(1, {
      id: "m-labelling",
      name: "Product labelling",
      source_operation_id: "op-9",
    });
    const route = process(
      operation({ repeated_operations: 4 }),
      operation({ id: "op-9", name: "Product labelling", repeated_operations: 1 }),
    );

    expect(staleEstimate(labelling, route)).toBeNull();
  });

  it("says nothing while the estimate still matches the route", () => {
    expect(staleEstimate(estimated(6), process(operation()))).toBeNull();
  });

  it("says nothing about a value a person typed over the estimate", () => {
    // Once somebody enters their own number, the estimate drives nothing and
    // its assumptions are history rather than state.
    const typed = estimated(6, { cycle_time: sourced(52, "ENGINEER", "Typed by the engineer") });
    expect(staleEstimate(typed, process(operation({ repeated_operations: 4 })))).toBeNull();
  });

  it("says nothing about an estimate that never used a repeat count", () => {
    const typedRange = estimated(null);
    expect(staleEstimate(typedRange, process(operation({ repeated_operations: 4 })))).toBeNull();
  });
});

describe("an accepted estimate is only consulted where the route is silent", () => {
  it("reuses the accepted count when the operation states none", () => {
    // Precedence: an engineer-specific estimator input that was accepted
    // beats a blank field. They should not have to type 3 again.
    const context = estimatorContext(
      estimated(3),
      process(operation({ repeated_operations: null })),
    );

    expect(context.repeats).toBe(3);
    expect(context.repeatSource).toBe("ESTIMATE");
  });

  it("does not resurrect it once a person has typed their own cycle time", () => {
    const typed = estimated(3, { cycle_time: sourced(52, "ENGINEER", "Typed by the engineer") });
    const context = estimatorContext(typed, process(operation({ repeated_operations: null })));

    expect(context.repeats).toBeNull();
    expect(context.repeatSource).toBe("NONE");
  });
});

describe("no process at all", () => {
  it("is not an error — the brief path never had one", () => {
    const context = estimatorContext(stage(), null);
    expect(context.repeats).toBeNull();
    expect(context.operation).toBeNull();
    expect(staleEstimate(estimated(6), null)).toBeNull();
  });
});
