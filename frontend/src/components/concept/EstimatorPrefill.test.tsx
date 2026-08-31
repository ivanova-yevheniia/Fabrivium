import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { EstimateAssistant } from "./EstimateAssistant";
import { ConceptBuilder } from "./ConceptBuilder";
import { estimatorContext } from "../../api/operationContext";
import { estimateCycleTime } from "../../api/uncertainty";
import { renderWithContext } from "../../test/testUtils";
import type { ManufacturingProcessDraft, ProposedOperation } from "../../api/product";
import type { ConceptStage, ConceptValidation, FactoryConceptDraft } from "../../api/types";

/** G10/G11 — the estimator opens on what the engineer already reviewed. */

vi.mock("../../api/uncertainty", async () => {
  const actual = await vi.importActual<typeof import("../../api/uncertainty")>("../../api/uncertainty");
  return { ...actual, estimateCycleTime: vi.fn(), applyEstimate: vi.fn(), acceptStationAssumptions: vi.fn() };
});

const estimateMock = vi.mocked(estimateCycleTime);

function sourced(value: number | null, source: string, detail: string | null = null) {
  return { value, source, detail } as ConceptStage["cycle_time"];
}

function operation(overrides: Partial<ProposedOperation> = {}): ProposedOperation {
  return {
    id: "op-screws",
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
    source_operation_id: "op-screws",
    ...overrides,
  };
}

function draft(stages: ConceptStage[]): FactoryConceptDraft {
  return {
    name: "Compact electronics controller",
    customer_brief: "1,900 units per day.",
    production_target: sourced(1900, "CUSTOMER"),
    product_name: "Compact electronics controller",
    stages,
    buffers: [],
    shifts_per_day: sourced(2, "ENGINEER"),
    hours_per_shift: sourced(8, "ENGINEER"),
    operators_available: sourced(8, "CUSTOMER"),
    floor_width: sourced(30, "CUSTOMER"),
    floor_length: sourced(18, "CUSTOMER"),
    budget: sourced(null, "UNKNOWN"),
    prefer_no_new_machines: true,
  } as FactoryConceptDraft;
}

const validation: ConceptValidation = {
  simulation_ready: false,
  blocking_gaps: [],
  optional_gaps: [],
  errors: [],
};

beforeEach(() => {
  estimateMock.mockReset();
  estimateMock.mockResolvedValue({
    estimate: null,
    proposal: null,
    needs_information: { reason: "n/a", questions: [] },
    contradiction: null,
    fell_back: false,
    provider_note: null,
    takt_seconds: {} as never,
  } as never);
});

async function openAssistant(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("estimate-mode-assist"));
}

function renderAssistant(station: ConceptStage, route: ManufacturingProcessDraft | null) {
  const concept = draft([station]);
  render(
    <EstimateAssistant
      draft={concept}
      stageId={station.id}
      stageName={station.name}
      context={estimatorContext(station, route)}
      onApplied={vi.fn()}
    />,
  );
  return userEvent.setup();
}

// G10/G11 — the panel

describe("the estimator opens on the reviewed operation", () => {
  it("shows the repeat count the process already states", async () => {
    const user = renderAssistant(stage(), process(operation()));
    await openAssistant(user);

    expect(screen.getByTestId("estimate-operations")).toHaveValue(6);
  });

  it("shows a different operation's own count, with no rule about names", async () => {
    const cable = operation({
      id: "op-cable",
      process_type: "connection",
      name: "Cable connection",
      description: "Cable connection, 2 times per unit.",
      repeated_operations: 2,
    });
    const user = renderAssistant(
      stage({ id: "m-connection", name: "Cable connection", source_operation_id: "op-cable" }),
      process(cable),
    );
    await openAssistant(user);

    expect(screen.getByTestId("estimate-operations")).toHaveValue(2);
  });

  it("leaves the count blank where nothing states one", async () => {
    const user = renderAssistant(stage(), process(operation({ repeated_operations: null })));
    await openAssistant(user);

    expect(screen.getByTestId("estimate-operations")).toHaveValue(null);
    // And it still explains what the field means, which is the only useful
    // thing to say when there is nothing to say about where a value is from.
    expect(screen.getByTestId("estimate-operations-source")).toHaveTextContent(
      /How many times this operation happens on one product/i,
    );
  });

  it("says where the count came from, rather than leaving it unexplained", async () => {
    const user = renderAssistant(stage(), process(operation()));
    await openAssistant(user);

    const note = screen.getByTestId("estimate-operations-source");
    expect(note).toHaveAttribute("data-source", "PROCESS");
    expect(note).toHaveTextContent(/reviewed process/i);
  });

  it("prefills the reviewed description", async () => {
    const user = renderAssistant(stage(), process(operation()));
    await openAssistant(user);

    expect(screen.getByTestId("estimate-description")).toHaveValue(
      "Screw fastening, 6 times per unit, implied by screws.",
    );
    expect(screen.getByTestId("estimate-description-source")).toHaveTextContent(
      /operation you reviewed/i,
    );
  });

  it("estimates with the propagated count, without it being typed", async () => {
    // The point of the whole fix: the request carries six because the route
    // said six, not because anybody re-entered it here.
    const user = renderAssistant(stage(), process(operation()));
    await openAssistant(user);
    await user.click(screen.getByTestId("estimate-ask"));

    expect(estimateMock).toHaveBeenCalledTimes(1);
    const [, , input] = estimateMock.mock.calls[0];
    expect(input.operations_per_unit).toBe(6);
    expect(input.description).toContain("6 times per unit");
  });

  it("opens blank for a station with no reviewed operation behind it", async () => {
    const user = renderAssistant(stage({ source_operation_id: null }), process(operation()));
    await openAssistant(user);

    expect(screen.getByTestId("estimate-description")).toHaveValue("");
    expect(screen.getByTestId("estimate-operations")).toHaveValue(null);
  });
});

describe("what the engineer types here stays here", () => {
  it("lets the description be refined without touching the process", async () => {
    // The reviewed operation is the canonical one. Refining the sentence for
    // an estimate proposes nothing to the route, and the panel says so.
    const route = process(operation());
    const before = JSON.stringify(route);

    const user = renderAssistant(stage(), route);
    await openAssistant(user);
    await user.clear(screen.getByTestId("estimate-description"));
    await user.type(screen.getByTestId("estimate-description"), "Six M3 screws into ABS.");
    await user.click(screen.getByTestId("estimate-ask"));

    expect(JSON.stringify(route)).toBe(before);
    const [, , input] = estimateMock.mock.calls[0];
    expect(input.description).toBe("Six M3 screws into ABS.");
    // The count was not disturbed by editing the sentence beside it.
    expect(input.operations_per_unit).toBe(6);
    // And the panel stops claiming the wording is the reviewed one.
    expect(screen.queryByTestId("estimate-description-source")).toBeNull();
  });

  it("records an overridden count as the engineer's own", async () => {
    const user = renderAssistant(stage(), process(operation()));
    await openAssistant(user);
    await user.clear(screen.getByTestId("estimate-operations"));
    await user.type(screen.getByTestId("estimate-operations"), "8");

    const note = screen.getByTestId("estimate-operations-source");
    expect(note).toHaveAttribute("data-source", "ENGINEER");
    // Both numbers, because the engineer is now departing from the route and
    // should be able to see that they are.
    expect(note).toHaveTextContent(/Entered here/i);
    expect(note).toHaveTextContent(/6× per unit/);

    await user.click(screen.getByTestId("estimate-ask"));
    expect(estimateMock.mock.calls[0][2].operations_per_unit).toBe(8);
  });
});

// The row that opens it

function conceptState(stages: ConceptStage[], route: ManufacturingProcessDraft | null) {
  return {
    startMode: "CONCEPT_BUILDER" as const,
    concept: {
      draft: draft(stages),
      validation,
      generatedLayout: null,
      building: false,
      extracting: false,
      error: null,
    },
    product: {
      name: "Compact electronics controller",
      description: "",
      fromExample: false,
      understanding: null,
      modelUsed: false,
      process: route,
      coverage: null,
      requirementsText: "",
      editing: false,
      busy: false,
      error: null,
    },
  };
}

/** A station whose cycle time came from an estimate composed for `repeats`. */
function estimated(repeats: number, overrides: Partial<ConceptStage> = {}): ConceptStage {
  return stage({
    cycle_time: sourced(48, "ENGINEERING_ESTIMATE", "35–55 s, medium confidence"),
    cycle_time_estimate: { operations_per_unit: repeats },
    ...overrides,
  });
}

describe("a route change reaches the station that depended on it", () => {
  it("reopens on the new count, never the cached one", async () => {
    // Estimated at six, route since edited to four. The panel opens on four.
    const user = userEvent.setup();
    renderWithContext(
      <ConceptBuilder />,
      conceptState([estimated(6)], process(operation({ repeated_operations: 4 }))),
    );

    await user.click(screen.getByTestId("estimate-open-m-screwdriving"));
    await user.click(screen.getByTestId("estimate-mode-assist"));

    expect(screen.getByTestId("estimate-operations")).toHaveValue(4);
  });

  it("marks that station's estimate stale, with both numbers", () => {
    renderWithContext(
      <ConceptBuilder />,
      conceptState([estimated(6)], process(operation({ repeated_operations: 4 }))),
    );

    const note = screen.getByTestId("estimate-stale-m-screwdriving");
    expect(note).toHaveTextContent(/Estimated for 6 per unit/i);
    expect(note).toHaveTextContent(/now says 4/i);
  });

  it("leaves an unrelated station's estimate alone", () => {
    const labelling = estimated(1, {
      id: "m-labelling",
      name: "Product labelling",
      source_operation_id: "op-label",
    });
    renderWithContext(
      <ConceptBuilder />,
      conceptState(
        [estimated(6), labelling],
        process(
          operation({ repeated_operations: 4 }),
          operation({ id: "op-label", name: "Product labelling", repeated_operations: 1 }),
        ),
      ),
    );

    expect(screen.getByTestId("estimate-stale-m-screwdriving")).toBeInTheDocument();
    expect(screen.queryByTestId("estimate-stale-m-labelling")).toBeNull();
  });

  it("says nothing while the estimate still answers the route", () => {
    renderWithContext(<ConceptBuilder />, conceptState([estimated(6)], process(operation())));
    expect(screen.queryByTestId("estimate-stale-m-screwdriving")).toBeNull();
  });

  it("still works for a concept with no product route behind it", async () => {
    // The brief path has no reviewed operations. Nothing is claimed, nothing
    // crashes, and the panel behaves exactly as it did before G10/G11.
    const user = userEvent.setup();
    renderWithContext(<ConceptBuilder />, conceptState([stage({ source_operation_id: null })], null));

    await user.click(screen.getByTestId("estimate-open-m-screwdriving"));
    await user.click(screen.getByTestId("estimate-mode-assist"));

    const form = screen.getByTestId("estimate-assist-form");
    expect(within(form).getByTestId("estimate-operations")).toHaveValue(null);
  });
});
