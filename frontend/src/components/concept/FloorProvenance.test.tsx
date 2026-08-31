import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConceptBuilder } from "./ConceptBuilder";
import { ResolveInputs } from "./ResolveInputs";
import { renderWithContext } from "../../test/testUtils";
import type { ResolutionPlan, ResolvableInput } from "../../api/concept";
import type { ConceptValidation, FactoryConceptDraft, SourcedNumber } from "../../api/types";

/** G12 — the floor is one requirement, and both screens must say so. */

vi.mock("../../api/concept", async () => {
  const actual = await vi.importActual<typeof import("../../api/concept")>("../../api/concept");
  return {
    ...actual,
    resolutionPlan: vi.fn(),
    resolveInput: vi.fn(),
    applyExampleData: vi.fn(),
    useExampleDataForUnresolved: vi.fn(),
    bufferSensitivity: vi.fn(),
  };
});

const api = await import("../../api/concept");

function sourced(value: number | null, source: string, detail: string | null = null): SourcedNumber {
  return { value, source, detail } as SourcedNumber;
}

function draft(floor: { width: SourcedNumber; length: SourcedNumber }): FactoryConceptDraft {
  return {
    name: "Compact electronics controller",
    customer_brief: "1,900 units per day on a 30 by 18 metre floor.",
    production_target: sourced(1900, "CUSTOMER", "Stated in the customer brief"),
    product_name: "Compact electronics controller",
    stages: [],
    buffers: [],
    shifts_per_day: sourced(2, "ENGINEER"),
    hours_per_shift: sourced(8, "ENGINEER"),
    operators_available: sourced(8, "CUSTOMER", "Stated in the customer brief"),
    floor_width: floor.width,
    floor_length: floor.length,
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

function conceptState(d: FactoryConceptDraft) {
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

function floorRow(): HTMLElement {
  const label = screen.getByText("Floor area");
  return label.parentElement as HTMLElement;
}

// The Concept screen

describe("the concept screen states who required the floor", () => {
  it("shows a customer-stated floor as the customer's, once", () => {
    const stated = sourced(30, "CUSTOMER", "Stated by the customer in spec.pdf, page 2");
    renderWithContext(
      <ConceptBuilder />,
      conceptState(draft({ width: stated, length: sourced(18, "CUSTOMER", stated.detail) })),
    );

    const row = floorRow();
    expect(row).toHaveTextContent("30 × 18");
    expect(within(row).getByTestId("source-customer")).toBeInTheDocument();
    // One requirement, one badge — the halves agree, so there is nothing to
    // separate out.
    expect(within(row).queryByTestId("concept-floor-mixed")).toBeNull();
  });

  it("shows an engineer-entered floor as the engineer's", () => {
    const entered = sourced(28, "ENGINEER", "Measured on site");
    renderWithContext(
      <ConceptBuilder />,
      conceptState(draft({ width: entered, length: sourced(16, "ENGINEER", "Measured on site") })),
    );

    expect(within(floorRow()).getByTestId("source-engineer")).toBeInTheDocument();
  });

  it("will not let one half speak for the pair when they genuinely differ", () => {
    // The residual case: something filled one side from elsewhere. A single
    // CUSTOMER badge over a length that came from the demonstration dataset
    // would be the exact claim this screen exists to prevent.
    renderWithContext(
      <ConceptBuilder />,
      conceptState(
        draft({
          width: sourced(30, "CUSTOMER", "Stated by the customer in spec.pdf"),
          length: sourced(18, "EXAMPLE_DATA", "Demonstration dataset"),
        }),
      ),
    );

    const mixed = within(floorRow()).getByTestId("concept-floor-mixed");
    expect(mixed).toHaveTextContent(/width/i);
    expect(mixed).toHaveTextContent(/length/i);
    expect(within(mixed).getByTestId("source-customer")).toBeInTheDocument();
    expect(within(mixed).getByTestId("source-example_data")).toBeInTheDocument();
  });
});

// The Resolve panel, on the same values

function input(over: Partial<ResolvableInput> & Pick<ResolvableInput, "key" | "label">): ResolvableInput {
  return {
    unit: "m",
    value: null,
    source: "UNKNOWN",
    detail: null,
    necessity: "AFFECTS_LAYOUT",
    consequence: "Bounds where stations may be placed.",
    actions: ["ENGINEER_INPUT", "LEAVE_UNKNOWN"],
    stage_id: null,
    quote_required: false,
    resolved: true,
    estimate: null,
    superseded: null,
    ...over,
  };
}

function floorPlan(source: ResolvableInput["source"]): ResolutionPlan {
  const detail = "Stated by the customer in spec.pdf, page 2";
  return {
    inputs: [
      input({ key: "floor_width", label: "Floor width", value: 30, source, detail }),
      input({ key: "floor_length", label: "Floor length", value: 18, source, detail }),
    ],
    computed: [],
    blocking_unresolved: 0,
    ready_to_simulate: false,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.resolveInput).mockResolvedValue({ draft: {} as never, validation: {} as never });
});

describe("the resolve panel agrees with the concept screen", () => {
  it("renders a customer floor as the customer's on both dimensions", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(floorPlan("CUSTOMER"));
    render(
      <ResolveInputs
        draft={{ buffers: [] } as unknown as FactoryConceptDraft}
        onDraftChange={() => {}}
        onEstimateStage={() => {}}
        onClose={() => {}}
      />,
    );

    const width = await screen.findByTestId("resolve-row-floor_width");
    const length = screen.getByTestId("resolve-row-floor_length");
    expect(within(width).getByTestId("source-customer")).toBeInTheDocument();
    expect(within(length).getByTestId("source-customer")).toBeInTheDocument();
  });

  it("renders an engineer-entered floor as the engineer's on both dimensions", async () => {
    vi.mocked(api.resolutionPlan).mockResolvedValue(floorPlan("ENGINEER"));
    render(
      <ResolveInputs
        draft={{ buffers: [] } as unknown as FactoryConceptDraft}
        onDraftChange={() => {}}
        onEstimateStage={() => {}}
        onClose={() => {}}
      />,
    );

    const width = await screen.findByTestId("resolve-row-floor_width");
    const length = screen.getByTestId("resolve-row-floor_length");
    expect(within(width).getByTestId("source-engineer")).toBeInTheDocument();
    expect(within(length).getByTestId("source-engineer")).toBeInTheDocument();
  });

  it("keeps the floor out of the simulation blockers on both screens", async () => {
    // Preserved classification: the simulator reads no layout. The station
    // summary's "needed to simulate" count depends on this staying true.
    vi.mocked(api.resolutionPlan).mockResolvedValue(floorPlan("CUSTOMER"));
    render(
      <ResolveInputs
        draft={{ buffers: [] } as unknown as FactoryConceptDraft}
        onDraftChange={() => {}}
        onEstimateStage={() => {}}
        onClose={() => {}}
      />,
    );

    expect(await screen.findByTestId("resolve-necessity-floor_width")).toHaveTextContent("Layout only");
    expect(screen.getByTestId("resolve-necessity-floor_length")).toHaveTextContent("Layout only");
  });
});
