import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RequirementCoverage } from "./RequirementCoverage";
import { resetProcessFamilyCache } from "./ProcessFamilySelect";
import { PROCESS_FAMILY_CATALOG } from "../../test/fixtures";
import type {
  CoverageReport,
  ManufacturingProcessDraft,
  ProductUnderstanding,
} from "../../api/product";

/** Coverage has to be actionable, not diagnostic. */

vi.mock("../../api/product", async () => {
  const actual = await vi.importActual<typeof import("../../api/product")>("../../api/product");
  return { ...actual, addOperation: vi.fn(), linkRequirement: vi.fn() };
});

// The process-family vocabulary is fetched, not hard-coded — see
// ProcessFamilySelect. Adding an operation is deliberately blocked until it
// arrives, so a test that adds one has to let it arrive.
vi.mock("../../api/processFamilies", () => ({
  fetchProcessFamilies: vi.fn(async () => PROCESS_FAMILY_CATALOG),
}));

const api = await import("../../api/product");

const understanding = { product_name: "CEC-120", facts: [] } as unknown as ProductUnderstanding;
const draft = {
  operations: [
    { id: "op-1", name: "PCB placement", status: "ACCEPTED" },
    { id: "op-2", name: "Packaging", status: "ACCEPTED" },
  ],
} as unknown as ManufacturingProcessDraft;

const COVERAGE: CoverageReport = {
  // Verbatim from the backend, which now says "extracted" in both the
  // complete and the incomplete sentence.
  summary: "6 of 8 extracted manufacturing requirements are addressed; 2 unresolved.",
  complete: false,
  approval_blocked: true,
  unresolved_count: 2,
  critical_unresolved_count: 2,
  items: [
    {
      fact_key: "component.label",
      label: "Label",
      value: "present",
      status: "UNRESOLVED",
      severity: "CRITICAL",
      addressed_by: [],
      quotes: ["Product identification label shall be applied to the exterior of the enclosure."],
    },
    {
      fact_key: "fastener.screw.count",
      label: "Screws",
      value: "6",
      status: "ADDRESSED",
      severity: "EXPECTED",
      addressed_by: ["Screw fastening ×6"],
      quotes: [],
    },
  ],
};

function renderPanel(onResolved = vi.fn()) {
  render(
    <RequirementCoverage
      coverage={COVERAGE}
      understanding={understanding}
      draft={draft}
      onResolved={onResolved}
    />,
  );
  return onResolved;
}

beforeEach(() => {
  vi.clearAllMocks();
  // The catalog is cached for the life of the module, so without this the
  resetProcessFamilyCache();
});

describe("requirement coverage", () => {
  it("shows the source sentence behind an unresolved requirement", () => {
    renderPanel();
    // The engineer has to be able to check the claim without reopening the
    // document.
    expect(screen.getByTestId("coverage-quote-component.label")).toHaveTextContent(
      /identification label shall be applied/i,
    );
  });

  it("marks a requirement the source stated explicitly", () => {
    renderPanel();
    expect(screen.getByTestId("coverage-critical-component.label")).toHaveTextContent(
      /stated by the source/i,
    );
  });

  it("says outright that approval is blocked, and why", () => {
    renderPanel();
    const blocked = screen.getByTestId("coverage-blocked");
    expect(blocked).toHaveTextContent(/no operation answers/i);
    expect(blocked).toHaveTextContent(/before building the concept/i);
  });

  it("offers both real ways to resolve, and no fake third one", () => {
    renderPanel();
    const row = screen.getByTestId("coverage-component.label");
    expect(within(row).getByTestId("coverage-add-component.label")).toBeInTheDocument();
    expect(within(row).getByTestId("coverage-link-component.label")).toBeInTheDocument();
    // No "resolve all" — which station applies a label is an engineering
    // decision, and a bulk button turns a real question into a formality.
    expect(screen.queryByText(/resolve all/i)).toBeNull();
  });

  it("requires a stated reason before an added operation can be saved", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByTestId("coverage-add-component.label"));
    await user.type(screen.getByTestId("coverage-add-name-component.label"), "Label application");

    // Name alone is not enough: an operation with no reason is the thing
    // traceability exists to prevent.
    expect(screen.getByTestId("coverage-add-save-component.label")).toBeDisabled();

    await user.type(
      screen.getByTestId("coverage-add-basis-component.label"),
      "The specification requires a label.",
    );
    expect(screen.getByTestId("coverage-add-save-component.label")).toBeEnabled();
  });

  it("adds the operation against the requirement it answers", async () => {
    const user = userEvent.setup();
    vi.mocked(api.addOperation).mockResolvedValue({ draft, coverage: COVERAGE });
    const onResolved = renderPanel();

    await user.click(screen.getByTestId("coverage-add-component.label"));
    await user.type(screen.getByTestId("coverage-add-name-component.label"), "Label application");
    await user.type(screen.getByTestId("coverage-add-basis-component.label"), "Spec requires it.");
    await user.click(screen.getByTestId("coverage-add-save-component.label"));

    await waitFor(() => expect(api.addOperation).toHaveBeenCalled());
    const [, , operation] = vi.mocked(api.addOperation).mock.calls[0];
    // The link back to the requirement is what recomputes coverage.
    expect(operation.source_fact_keys).toEqual(["component.label"]);
    expect(onResolved).toHaveBeenCalled();
  });

  it("links an existing operation when the process was already right", async () => {
    const user = userEvent.setup();
    vi.mocked(api.linkRequirement).mockResolvedValue({ draft, coverage: COVERAGE });
    renderPanel();

    await user.click(screen.getByTestId("coverage-link-component.label"));
    await user.click(screen.getByTestId("coverage-link-save-component.label"));

    await waitFor(() => expect(api.linkRequirement).toHaveBeenCalled());
    const [, , operationId, keys] = vi.mocked(api.linkRequirement).mock.calls[0];
    expect(operationId).toBe("op-1");
    expect(keys).toEqual(["component.label"]);
  });

  it("keeps addressed requirements collapsed", () => {
    renderPanel();
    // Reassurance, not work. It should not compete with the thing that
    // needs doing.
    expect(screen.getByTestId("coverage-addressed-toggle")).toHaveTextContent(/1 requirement/i);
  });
});

/** COVERAGE MUST NOT IMPLY DOCUMENT COMPLETENESS. */
describe("coverage states its own scope", () => {
  it("names the metric for what it measures, not for the document", async () => {
    renderPanel();
    expect(screen.getByText("Extracted-requirement coverage")).toBeInTheDocument();
  });

  it("offers the boundary without shouting it", async () => {
    renderPanel();
    const scope = screen.getByTestId("coverage-scope");
    // Progressive disclosure: present, collapsed, not an alert.
    expect(scope.tagName.toLowerCase()).toBe("details");
    expect((scope as HTMLDetailsElement).open).toBe(false);
    expect(scope.textContent).toContain("does not prove that every");
  });

  it("says the process was not independently established as complete", async () => {
    renderPanel();
    expect(screen.getByTestId("coverage-process-scope").textContent).toMatch(
      /not independently established|Not yet reviewed/,
    );
  });
});
