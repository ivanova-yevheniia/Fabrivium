import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ConceptValidation, FactoryConceptDraft } from "../../api/types";
import { renderWithContext } from "../../test/testUtils";
import { initialAppState } from "../../state/types";
import { ConceptBuilder } from "./ConceptBuilder";
import { StartScreen } from "./StartScreen";

/** Phase 13 — the concept builder's honesty rules, as UI behaviour. */

function sourced(value: number | null, source: FactoryConceptDraft["production_target"]["source"], detail: string | null = null) {
  return { value, source, detail };
}

function draft(overrides: Partial<FactoryConceptDraft> = {}): FactoryConceptDraft {
  return {
    name: "New factory concept",
    customer_brief: "We need 1,900 units per day through assembly and packaging.",
    production_target: sourced(1900, "CUSTOMER", "Stated in the customer brief"),
    product_name: "Product",
    stages: [
      {
        id: "m-assembly",
        name: "Assembly",
        process_type: "assembly",
        cycle_time: sourced(null, "UNKNOWN"),
        capacity: sourced(null, "UNKNOWN"),
        operators_required: sourced(null, "UNKNOWN"),
        width: sourced(null, "UNKNOWN"),
        length: sourced(null, "UNKNOWN"),
        purchase_cost: sourced(null, "UNKNOWN"),
      },
    ],
    buffers: [],
    shifts_per_day: sourced(null, "UNKNOWN"),
    hours_per_shift: sourced(null, "UNKNOWN"),
    operators_available: sourced(8, "CUSTOMER", "Stated in the customer brief"),
    floor_width: sourced(30, "CUSTOMER"),
    floor_length: sourced(18, "CUSTOMER"),
    budget: sourced(null, "UNKNOWN"),
    prefer_no_new_machines: true,
    ...overrides,
  };
}

const blockedValidation: ConceptValidation = {
  simulation_ready: false,
  blocking_gaps: [
    {
      key: "stage.m-assembly.cycle_time",
      label: "Assembly cycle time",
      severity: "REQUIRED",
      reason: "Processing time per unit is the core physical property of a stage.",
      stage_id: "m-assembly",
    },
  ],
  optional_gaps: [
    {
      key: "stage.m-assembly.purchase_cost",
      label: "Assembly equipment cost",
      severity: "OPTIONAL",
      reason: "Commercial only. The simulation reads no price.",
      stage_id: "m-assembly",
    },
  ],
  errors: [],
};

const readyValidation: ConceptValidation = {
  simulation_ready: true,
  blocking_gaps: [],
  optional_gaps: [],
  errors: [],
};

function conceptState(d: FactoryConceptDraft | null, validation: ConceptValidation | null) {
  return {
    startMode: "CONCEPT_BUILDER" as const,
    concept: {
      draft: d,
      validation,
      generatedLayout: null,
      building: false,
      extracting: false,
      error: null,
    },
  };
}

describe("StartScreen — how a project starts", () => {
  it("offers exactly the two starting paths that actually exist", () => {
    renderWithContext(<StartScreen />, {});
    expect(screen.getByTestId("start-from-product")).toBeInTheDocument();
    expect(screen.getByTestId("start-design-new")).toBeInTheDocument();
    // No import tile: no CSV/MES/CAD import exists, and offering one would
    // promise something the product cannot do.
    expect(screen.queryByText(/import/i)).toBeNull();
  });

  it("does not offer the bundled demo line as a peer of real work", () => {
    // P0 §A. The demo used to sit here as a third equal tile, which made a
    // bundled example read as a third way of doing production work. It is a
    // PROJECT now, offered on the landing page in the quieter row.
    renderWithContext(<StartScreen />, {});
    expect(screen.queryByTestId("start-open-demo")).toBeNull();
  });

  it("offers the bundled line inside an example project, where it belongs", () => {
    renderWithContext(<StartScreen />, {
      project: { ...initialAppState.project, id: "p1", name: "Example", isExample: true },
    });
    expect(screen.getByTestId("start-open-demo")).toBeInTheDocument();
  });

  it("loads the demo factory on request", async () => {
    const user = userEvent.setup();
    const openDemoFactory = vi.fn(async () => {});
    renderWithContext(
      <StartScreen />,
      { project: { ...initialAppState.project, id: "p1", name: "Example", isExample: true } },
      { openDemoFactory },
    );

    await user.click(screen.getByTestId("start-open-demo"));
    expect(openDemoFactory).toHaveBeenCalled();
  });

  it("offers the way back to the project list", async () => {
    const user = userEvent.setup();
    const closeProject = vi.fn();
    renderWithContext(<StartScreen />, {}, { closeProject });

    await user.click(screen.getByTestId("start-back-to-projects"));
    expect(closeProject).toHaveBeenCalled();
  });
});

describe("ConceptBuilder — the brief", () => {
  it("sends the brief for structuring", async () => {
    const user = userEvent.setup();
    const startConceptFromBrief = vi.fn(async () => {});
    renderWithContext(<ConceptBuilder />, conceptState(null, null), { startConceptFromBrief });

    await user.type(screen.getByTestId("concept-brief-input"), "Assembly then packaging. 900 units per day.");
    await user.click(screen.getByTestId("concept-build-from-brief"));

    expect(startConceptFromBrief).toHaveBeenCalledWith(
      "Assembly then packaging. 900 units per day.",
      "New factory concept",
    );
  });

  it("cannot submit an empty brief", () => {
    renderWithContext(<ConceptBuilder />, conceptState(null, null), {});
    expect(screen.getByTestId("concept-build-from-brief")).toBeDisabled();
  });
});

describe("ConceptBuilder — provenance", () => {
  it("marks what the customer stated as theirs", () => {
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});

    const workspace = screen.getByTestId("concept-workspace");
    expect(within(workspace).getAllByTestId("source-customer").length).toBeGreaterThan(0);
    expect(workspace).toHaveTextContent("1,900");
  });

  it("shows an unknown value as words, never as a zero", () => {
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});

    // The cycle-time field must be EMPTY rather than pre-filled with 0 — a
    // zero here would read as a measurement of zero seconds.
    const field = screen.getByTestId("field-cycle-m-assembly") as HTMLInputElement;
    expect(field.value).toBe("");
  });

  it("quotes the customer brief verbatim as evidence", () => {
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});
    expect(screen.getByTestId("concept-brief-quote")).toHaveTextContent(
      "We need 1,900 units per day through assembly and packaging.",
    );
  });

  it("shows a captured preference as a preference, not a constraint", () => {
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});
    expect(screen.getByTestId("concept-preference")).toHaveTextContent(/preference/i);
  });
});

describe("ConceptBuilder — information gaps", () => {
  it("blocks the build while a required value is missing", async () => {
    const user = userEvent.setup();
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});

    // Phase 14 §4 summarises the gaps and discloses the items on request, so
    // the individual input is one click away rather than always listed. What
    // this test pins is unchanged: a missing required value blocks the build.
    expect(screen.getByTestId("concept-build-factory")).toBeDisabled();
    await user.click(screen.getByTestId("gap-required-toggle"));
    expect(screen.getByTestId("gap-required-list")).toHaveTextContent("Assembly cycle time");
  });

  it("does not block the build for a missing price", () => {
    renderWithContext(<ConceptBuilder />, conceptState(draft(), readyValidation), {});

    expect(screen.getByTestId("gap-ready")).toBeInTheDocument();
    expect(screen.getByTestId("concept-build-factory")).toBeEnabled();
  });

  it("separates optional gaps from blocking ones and says so", async () => {
    const user = userEvent.setup();
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});

    const optional = screen.getByTestId("gap-optional");
    expect(optional).toHaveTextContent(/does not block simulation/i);
    await user.click(screen.getByTestId("gap-optional-toggle"));
    expect(screen.getByTestId("gap-optional-list")).toHaveTextContent("Assembly equipment cost");
  });

  it("opens input resolution without adopting anything", async () => {
    const user = userEvent.setup();
    const useExampleEngineeringData = vi.fn(async () => {});
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {
      useExampleEngineeringData,
    });

    // Phase 14 §4 first made the demo dataset an explicit review step rather
    // than one blind click. Real Data First went further: the dataset is no
    // longer the step at all. The action opens per-value resolution, where
    // Fabrivium computes what it can compute, estimates what it can
    // estimate, and offers the dataset only as one named fallback per value.
    const gaps = screen.getByTestId("gap-required");
    expect(gaps).toHaveTextContent(/Fabrivium will not guess them/i);

    await user.click(screen.getByTestId("concept-review-assumptions"));
    expect(screen.getByTestId("resolve-inputs")).toBeInTheDocument();
    // Opening it adopts nothing — neither the dataset nor anything else.
    expect(useExampleEngineeringData).not.toHaveBeenCalled();
  });
});

describe("ConceptBuilder — editing", () => {
  it("a value the engineer types is recorded as the ENGINEER's decision", async () => {
    // P0 §D4. This field used to record a typed value as CUSTOMER, which
    // lost exactly what provenance exists to record: a customer STATES
    // REQUIREMENTS and an engineer STATES ENGINEERING DECISIONS, and
    // conflating the two loses who is accountable for the number. It is also
    // the source that beats every automatic one, so it must be the source
    // that a human typing into the model actually gets.
    const user = userEvent.setup();
    const updateConceptDraft = vi.fn(async (_next: FactoryConceptDraft) => {});
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), { updateConceptDraft });

    const field = screen.getByTestId("field-cycle-m-assembly");
    await user.type(field, "35");
    await user.tab();

    expect(updateConceptDraft).toHaveBeenCalled();
    const committed = updateConceptDraft.mock.calls[0][0];
    expect(committed.stages[0].cycle_time.value).toBe(35);
    expect(committed.stages[0].cycle_time.source).toBe("ENGINEER");
    expect(committed.stages[0].cycle_time.source).not.toBe("CUSTOMER");
  });

  it("clearing a value returns it to unknown rather than to zero", async () => {
    const user = userEvent.setup();
    const updateConceptDraft = vi.fn(async (_next: FactoryConceptDraft) => {});
    const withCycle = draft({
      stages: [{ ...draft().stages[0], cycle_time: sourced(35, "CUSTOMER") }],
    });
    renderWithContext(<ConceptBuilder />, conceptState(withCycle, readyValidation), { updateConceptDraft });

    const field = screen.getByTestId("field-cycle-m-assembly");
    await user.clear(field);
    await user.tab();

    const committed = updateConceptDraft.mock.calls[0][0];
    expect(committed.stages[0].cycle_time.value).toBeNull();
    expect(committed.stages[0].cycle_time.source).toBe("UNKNOWN");
  });

  it("states that placement does not affect throughput", () => {
    // The simulator takes no layout. The screen must never imply that moving
    // a station makes the line faster.
    renderWithContext(<ConceptBuilder />, conceptState(draft(), blockedValidation), {});
    expect(screen.getByTestId("concept-workspace")).toHaveTextContent(
      /placement is checked for validity, never for speed/i,
    );
  });
});

describe("ConceptBuilder — building", () => {
  it("converts the concept into a factory on request", async () => {
    const user = userEvent.setup();
    const buildConceptFactory = vi.fn(async () => {});
    renderWithContext(<ConceptBuilder />, conceptState(draft(), readyValidation), { buildConceptFactory });

    await user.click(screen.getByTestId("concept-build-factory"));
    expect(buildConceptFactory).toHaveBeenCalled();
  });
});
