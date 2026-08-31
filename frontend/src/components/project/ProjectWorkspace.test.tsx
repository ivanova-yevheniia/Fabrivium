import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProjectLanding } from "./ProjectLanding";
import { EvidenceBadge, EvidenceNote } from "./EvidenceStatus";
import { ProductStart } from "../product/ProductStart";
import { ConceptVerified } from "../concept/ConceptVerified";
import { renderWithContext } from "../../test/testUtils";
import { initialAppState } from "../../state/types";
import type { AppState } from "../../state/types";
import type { StaleReport } from "../../api/projects";

/** P0 §I, frontend half — the workspace, and the badge that must never lie. */

const RECENT = [
  {
    project_id: "p-1",
    name: "Controller line — Plant 2",
    created_at: "2026-08-01T09:00:00.000000+00:00",
    updated_at: "2026-08-20T09:00:00.000000+00:00",
    product_name: "Compact electronics controller",
    is_example: false,
  },
  {
    project_id: "p-2",
    name: "Example — electronics controller",
    created_at: "2026-08-02T09:00:00.000000+00:00",
    updated_at: "2026-08-02T09:00:00.000000+00:00",
    product_name: "",
    is_example: true,
  },
];

function withProject(overrides: Partial<AppState["project"]> = {}): Partial<AppState> {
  return { project: { ...initialAppState.project, id: "p-1", name: "Controller line", ...overrides } };
}

// 14 / 20 — the landing page

describe("the landing page", () => {
  it("offers a new project, recent projects and the example project", () => {
    renderWithContext(<ProjectLanding />, { project: { ...initialAppState.project, recent: RECENT } });

    expect(screen.getByTestId("project-name-input")).toBeInTheDocument();
    expect(screen.getByTestId("project-create")).toBeInTheDocument();
    expect(screen.getByTestId("project-recent")).toBeInTheDocument();
    expect(screen.getByTestId("project-open-example")).toBeInTheDocument();
  });

  it("creates a project under the name the engineer chose", async () => {
    const user = userEvent.setup();
    const newProject = vi.fn(async () => {});
    renderWithContext(<ProjectLanding />, {}, { newProject });

    await user.type(screen.getByTestId("project-name-input"), "Controller line — Plant 2");
    await user.click(screen.getByTestId("project-create"));

    expect(newProject).toHaveBeenCalledWith("Controller line — Plant 2");
  });

  it("refuses to create a project with no name", async () => {
    const user = userEvent.setup();
    const newProject = vi.fn(async () => {});
    renderWithContext(<ProjectLanding />, {}, { newProject });

    expect(screen.getByTestId("project-create")).toBeDisabled();
    await user.type(screen.getByTestId("project-name-input"), "   ");
    expect(screen.getByTestId("project-create")).toBeDisabled();
    expect(newProject).not.toHaveBeenCalled();
  });

  it("reopens a listed project", async () => {
    const user = userEvent.setup();
    const openProject = vi.fn(async () => {});
    renderWithContext(
      <ProjectLanding />,
      { project: { ...initialAppState.project, recent: RECENT } },
      { openProject },
    );

    await user.click(screen.getByTestId("project-open-p-1"));
    expect(openProject).toHaveBeenCalledWith("p-1");
  });

  it("marks the example project as an example rather than as somebody's work", () => {
    renderWithContext(<ProjectLanding />, { project: { ...initialAppState.project, recent: RECENT } });

    const example = screen.getByTestId("project-open-p-2");
    expect(within(example).getByTestId("project-example-tag")).toHaveTextContent("example");
    // And the engineer's own project carries no such tag.
    expect(within(screen.getByTestId("project-open-p-1")).queryByTestId("project-example-tag")).toBeNull();
  });

  it("has a clean empty state that says what can be done from here", () => {
    renderWithContext(<ProjectLanding />, { project: { ...initialAppState.project, recent: [] } });

    const empty = screen.getByTestId("project-empty");
    expect(empty).toHaveTextContent(/no projects yet/i);
    expect(empty).toHaveTextContent(/example project/i);
  });

  it("asks before deleting a project", async () => {
    const user = userEvent.setup();
    const removeProject = vi.fn(async () => {});
    renderWithContext(
      <ProjectLanding />,
      { project: { ...initialAppState.project, recent: RECENT } },
      { removeProject },
    );

    await user.click(screen.getByTestId("project-delete-p-1"));
    expect(removeProject).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("project-delete-confirm-p-1"));
    expect(removeProject).toHaveBeenCalledWith("p-1");
  });
});

// 15 / 16 — product entry and re-editing

describe("starting from a product", () => {
  it("starts with an empty product name", () => {
    // The observed defect: a manual project opened with "Compact electronics
    // controller" already typed in, which is right for the example and wrong
    // for every real project.
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, withProject());
    expect(screen.getByTestId("product-name")).toHaveValue("");
  });

  it("fills the name and the specification only when the example is asked for", async () => {
    const user = userEvent.setup();
    const loadExampleSpecification = vi.fn(async () => {});
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, withProject(), {
      loadExampleSpecification,
    });

    expect(loadExampleSpecification).not.toHaveBeenCalled();
    await user.click(screen.getByTestId("product-use-reference"));
    expect(loadExampleSpecification).toHaveBeenCalled();
  });

  it("says plainly that the example specification is an example", () => {
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, {
      ...withProject(),
      product: {
        ...initialAppState.product,
        description: "A controller in a plastic enclosure.",
        fromExample: true,
      },
    });

    expect(screen.getByTestId("product-example-notice")).toHaveTextContent(/example specification/i);
    expect(screen.getByTestId("product-example-notice")).toHaveTextContent(/not a customer file/i);
  });

  it("records what the engineer types rather than holding it locally", async () => {
    const user = userEvent.setup();
    const setProductField = vi.fn();
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, withProject(), { setProductField });

    await user.type(screen.getByTestId("product-name"), "A");
    expect(setProductField).toHaveBeenCalledWith({ name: "A" });
  });

  it("offers a way back to the product information after the facts exist", async () => {
    const user = userEvent.setup();
    const state: Partial<AppState> = {
      ...withProject(),
      product: {
        ...initialAppState.product,
        name: "Controller",
        description: "Six screws.",
        understanding: understanding(),
      },
    };
    const setProductField = vi.fn();
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, state, { setProductField });

    // The one-way wizard is the defect: once facts existed there was no
    // control anywhere that returned the engineer to the source.
    await user.click(screen.getByTestId("product-edit-information"));
    expect(setProductField).toHaveBeenCalledWith({ editing: true });
  });

  // Golden-run defect G1 — editing product information
  //
  // The entry form doubled as the edit form. Re-opening it after a PDF
  // upload showed a native file input reading "no file selected" underneath
  // a Product understanding panel built from a document that was still
  // perfectly present, and an empty "Describe the product" box beside it.
  // Nothing was broken; the screen simply said the opposite of the truth.

  const editingUploadedProduct = () => ({
    ...withProject(),
    product: {
      ...initialAppState.product,
      name: "Controller",
      // Empty, as it is after an upload: the source is the file, not text.
      description: "",
      understanding: {
        ...understanding(),
        source_documents: [
          {
            document_id: "d-1",
            name: "Controller_Specification.pdf",
            media_type: "application/pdf",
            pages: 2,
            ingested_on: "2026-08-28",
            pages_without_text: [],
            notes: [],
          },
        ],
      },
      editing: true,
    },
  });

  it("names the current document instead of showing an empty file input", () => {
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, editingUploadedProduct());

    const panel = screen.getByTestId("product-edit-panel");
    expect(panel).toHaveTextContent(/edit product information/i);

    const current = screen.getByTestId("product-current-document");
    expect(current).toHaveTextContent("Controller_Specification.pdf");
    expect(current).toHaveTextContent("2 pages");

    // The empty input is the thing that read as "your document is gone". It
    // appears only after an explicit Replace.
    expect(screen.queryByTestId("product-file")).toBeNull();
    expect(screen.getByTestId("product-replace-document")).toBeInTheDocument();
  });

  it("reveals the file input only when the engineer asks to replace the document", async () => {
    const user = userEvent.setup();
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, editingUploadedProduct());

    await user.click(screen.getByTestId("product-replace-document"));
    expect(screen.getByTestId("product-file")).toBeInTheDocument();
    // And it says what choosing a file will cost, before it is chosen.
    expect(screen.getByTestId("product-supported")).toHaveTextContent(/dropped, not kept/i);

    await user.click(screen.getByTestId("product-replace-cancel"));
    expect(screen.queryByTestId("product-file")).toBeNull();
  });

  it("saves a renamed product without touching its document or its facts", async () => {
    const user = userEvent.setup();
    const setProductField = vi.fn();
    renderWithContext(
      <ProductStart onConceptBuilt={vi.fn()} />,
      editingUploadedProduct(),
      { setProductField },
    );

    await user.clear(screen.getByTestId("product-name"));
    await user.type(screen.getByTestId("product-name"), "CEC-120");
    // Typing is not saving: nothing has reached the project yet, which is
    // what makes Cancel mean something.
    expect(setProductField).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("product-edit-save"));

    expect(setProductField).toHaveBeenCalledTimes(1);
    const patch = setProductField.mock.calls[0][0];
    expect(patch.name).toBe("CEC-120");
    expect(patch.editing).toBe(false);
    // The facts are untouched, and the name they are shown under follows the
    // rename rather than staying on the old one.
    expect(patch.understanding.facts).toEqual(understanding().facts);
    expect(patch.understanding.product_name).toBe("CEC-120");
    expect(patch.understanding.source_documents[0].name).toBe("Controller_Specification.pdf");
  });

  it("discards an unsaved edit on cancel", async () => {
    const user = userEvent.setup();
    const setProductField = vi.fn();
    renderWithContext(
      <ProductStart onConceptBuilt={vi.fn()} />,
      editingUploadedProduct(),
      { setProductField },
    );

    await user.clear(screen.getByTestId("product-name"));
    await user.type(screen.getByTestId("product-name"), "Something else");
    await user.click(screen.getByTestId("product-edit-cancel"));

    // Only the edit mode closes. The name never reached the project.
    expect(setProductField).toHaveBeenCalledTimes(1);
    expect(setProductField).toHaveBeenCalledWith({ editing: false });
  });

  it("offers a re-read only where there is source text to change", async () => {
    const user = userEvent.setup();
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, {
      ...withProject(),
      product: {
        ...initialAppState.product,
        name: "Controller",
        description: "Six screws.",
        understanding: understanding(),
        editing: true,
      },
    });

    expect(screen.getByTestId("product-description")).toHaveValue("Six screws.");
    // Unchanged text is not a re-reading job — the button appears once the
    // source actually differs from what was read.
    expect(screen.queryByTestId("product-read-description")).toBeNull();

    await user.type(screen.getByTestId("product-description"), " Eight cables.");
    expect(screen.getByTestId("product-read-description")).toHaveTextContent(/re-read/i);
  });

  it("shows the cause and the cure where the source was changed", () => {
    renderWithContext(<ProductStart onConceptBuilt={vi.fn()} />, {
      ...withProject({ staleness: report("PRODUCT_FACTS", ["Product specification changed."]) }),
      product: {
        ...initialAppState.product,
        description: "Eight screws.",
        understanding: understanding(),
        editing: true,
      },
    });

    const note = screen.getByTestId("evidence-note-PRODUCT_FACTS");
    expect(note).toHaveTextContent(/inputs changed since this result was verified/i);
    expect(within(note).getByTestId("evidence-reasons-PRODUCT_FACTS")).toHaveTextContent(
      "Product specification changed.",
    );
  });
});

// 18 / 19 — the badge

describe("evidence status", () => {
  it("says VERIFIED only for a result that answers the current inputs", () => {
    renderWithContext(<EvidenceBadge artifact="SIMULATION_VERIFICATION" />, {
      project: {
        ...initialAppState.project,
        staleness: {
          stale: [],
          current: ["SIMULATION_VERIFICATION"],
          unverified: [],
          summary: "Every result on screen answers the current inputs.",
        },
      },
    });

    const badge = screen.getByTestId("evidence-SIMULATION_VERIFICATION");
    expect(badge).toHaveAttribute("data-status", "CURRENT");
    expect(badge).toHaveTextContent("Verified");
  });

  it("loses the verified state the moment an input it depends on moves", () => {
    renderWithContext(<EvidenceBadge artifact="SIMULATION_VERIFICATION" />, {
      project: {
        ...initialAppState.project,
        staleness: report("SIMULATION_VERIFICATION", ["Screw fastening — cycle time: 48 → 44"]),
      },
    });

    const badge = screen.getByTestId("evidence-SIMULATION_VERIFICATION");
    expect(badge).toHaveAttribute("data-status", "STALE");
    expect(badge).not.toHaveTextContent("Verified");
    expect(badge.className).not.toMatch(/evidence-badge--current/);
  });

  it("keeps 'nobody has looked' apart from 'we looked and it changed'", () => {
    renderWithContext(<EvidenceBadge artifact="SIEMENS_HANDOFF" />, {});
    const badge = screen.getByTestId("evidence-SIEMENS_HANDOFF");
    expect(badge).toHaveAttribute("data-status", "UNVERIFIED");
    expect(badge).toHaveTextContent(/not verified/i);
  });

  it("names the change in the engineer's own units", () => {
    renderWithContext(<EvidenceNote artifact="SIMULATION_VERIFICATION" />, {
      project: {
        ...initialAppState.project,
        staleness: report("SIMULATION_VERIFICATION", ["Screw fastening — cycle time: 48 → 44"]),
      },
    });

    expect(screen.getByTestId("evidence-reasons-SIMULATION_VERIFICATION")).toHaveTextContent(
      "Screw fastening — cycle time: 48 → 44",
    );
  });

  it("names the exact action rather than a generic refresh", async () => {
    const user = userEvent.setup();
    const act = vi.fn();
    renderWithContext(<EvidenceNote artifact="SIMULATION_VERIFICATION" onAct={act} />, {
      project: {
        ...initialAppState.project,
        staleness: report("SIMULATION_VERIFICATION", ["Screw fastening — cycle time: 48 → 44"]),
      },
    });

    const action = screen.getByTestId("evidence-action-SIMULATION_VERIFICATION");
    expect(action).toHaveTextContent("Re-run verification");
    await user.click(action);
    expect(act).toHaveBeenCalled();
  });

  it("says nothing at all when nothing has gone stale", () => {
    renderWithContext(<EvidenceNote artifact="SIMULATION_VERIFICATION" />, {
      project: {
        ...initialAppState.project,
        staleness: { stale: [], current: ["SIMULATION_VERIFICATION"], unverified: [], summary: "" },
      },
    });
    expect(screen.queryByTestId("evidence-note-SIMULATION_VERIFICATION")).toBeNull();
  });
});

// The verified screen must not contradict its own badge

describe("the verified concept screen", () => {
  it("stops calling the concept verified once the inputs move", async () => {
    const state = verifiedState();
    renderWithContext(<ConceptVerified />, {
      ...state,
      project: {
        ...initialAppState.project,
        id: "p-1",
        staleness: report("SIMULATION_VERIFICATION", ["Screw fastening — cycle time: 48 → 44"]),
      },
    });

    await waitFor(() => expect(screen.getByTestId("concept-verified")).toBeInTheDocument());
    expect(screen.getByTestId("concept-verified")).toHaveTextContent(/needs revalidation/i);
    expect(screen.getByTestId("concept-verified-process")).toHaveTextContent(
      /inputs that have since changed/i,
    );
  });

  it("still says verified while the inputs are unchanged", () => {
    renderWithContext(<ConceptVerified />, {
      ...verifiedState(),
      project: {
        ...initialAppState.project,
        id: "p-1",
        staleness: {
          stale: [],
          current: ["SIMULATION_VERIFICATION"],
          unverified: [],
          summary: "",
        },
      },
    });

    expect(screen.getByTestId("concept-verified")).toHaveTextContent("Concept verified");
  });

  it("calls selected equipment 'under consideration', never proven", () => {
    renderWithContext(<ConceptVerified />, {
      ...verifiedState(),
      equipmentSelections: {
        "m-screwdriving": { manufacturer: "Atlas Copco", model: "MicroTorque 40", source_url: null },
      },
      project: { ...initialAppState.project, id: "p-1" },
    });

    const line = screen.getByTestId("concept-verified-equipment");
    expect(line).toHaveTextContent(/under consideration/i);
    expect(line).not.toHaveTextContent(/proven|verified equipment/i);
  });
});

// fixtures

function report(artifact: string, reasons: string[]): StaleReport {
  return {
    stale: [
      {
        artifact: artifact as StaleReport["stale"][number]["artifact"],
        status: "STALE",
        changed_channels: ["SIMULATION_INPUTS"],
        stale_parents: [],
        reasons,
        action:
          artifact === "PRODUCT_FACTS" ? "Re-read the product specification" : "Re-run verification",
      },
    ],
    current: [],
    unverified: [],
    summary: "Inputs changed since this was verified.",
  };
}

function understanding() {
  return {
    product_name: "Controller",
    description: "A controller in a plastic enclosure.",
    facts: [
      {
        key: "fastener.screw.count",
        category: "fastening",
        label: "Screws",
        value: "6",
        quantity: 6,
        unit: null,
        status: "EXTRACTED" as const,
        confidence: "HIGH",
        evidence: [],
        alternatives: [],
      },
    ],
    source_documents: [],
    information_gaps: [],
    unresolved_statements: [],
    source_production_requirements: [],
    interpretation_method: "LOCAL_RULES",
    model_name: null,
  };
}

/** The smallest state ConceptVerified will render from: an arena with one
 * selected strategy, the factory it was built into, and the draft behind it. */
function verifiedState(): Partial<AppState> {
  const stage = {
    id: "m-screwdriving",
    name: "Screw fastening",
    process_type: "screwdriving",
    cycle_time: { value: 48, source: "ENGINEER" as const, detail: null },
    capacity: { value: 1, source: "CATALOG_DEFAULT" as const, detail: null },
    operators_required: { value: 1, source: "CATALOG_DEFAULT" as const, detail: null },
    width: { value: 2, source: "CATALOG_DEFAULT" as const, detail: null },
    length: { value: 2, source: "CATALOG_DEFAULT" as const, detail: null },
    purchase_cost: { value: null, source: "UNKNOWN" as const, detail: null },
  };

  return {
    factory: { id: "f-1", name: "Controller line", width: 30, length: 18, machines: [], products: [], buffers: [], shifts_per_day: 2, hours_per_shift: 8, operators_available: 8, budget: null } as never,
    productId: "p-controller",
    selectedStrategyId: "s-1",
    concept: {
      ...initialAppState.concept,
      draft: {
        name: "Controller line",
        customer_brief: "",
        product_name: "Controller",
        stages: [stage],
        buffers: [],
        production_target: { value: 1900, source: "CUSTOMER" as const, detail: null },
        shifts_per_day: { value: 2, source: "CUSTOMER" as const, detail: null },
        hours_per_shift: { value: 8, source: "CUSTOMER" as const, detail: null },
        operators_available: { value: 8, source: "CUSTOMER" as const, detail: null },
        floor_width: { value: 30, source: "CUSTOMER" as const, detail: null },
        floor_length: { value: 18, source: "CUSTOMER" as const, detail: null },
        budget: { value: null, source: "UNKNOWN" as const, detail: null },
        prefer_no_new_machines: false,
      } as never,
    },
    arena: {
      product_id: "p-controller",
      strategies: [
        {
          strategy_id: "s-1",
          title: "Add a screwdriving station",
          commercially_complete: true,
          metrics: {
            goal_met: true,
            achieved_units: 1900,
            target_units: 1900,
            bottleneck_machine_id: "m-screwdriving",
          },
        },
      ],
    } as never,
  };
}
