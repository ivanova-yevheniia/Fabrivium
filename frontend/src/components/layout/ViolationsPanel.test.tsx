import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithContext } from "../../test/testUtils";
import { ViolationsPanel } from "./ViolationsPanel";

const draft = { factory_width: 20, factory_length: 10, placements: [], reserved_zones: [], aisle_zones: [] };

describe("ViolationsPanel", () => {
  it("renders nothing outside EDIT_LAYOUT mode", () => {
    renderWithContext(<ViolationsPanel />, { editMode: "VIEW" });
    expect(screen.queryByTestId("violations-panel")).not.toBeInTheDocument();
  });

  it("shows a not-yet-validated message before any Validate call", () => {
    renderWithContext(<ViolationsPanel />, { editMode: "EDIT_LAYOUT", draftLayout: draft, layoutValidation: null });
    expect(screen.getByTestId("violations-panel")).toHaveTextContent(/not yet validated/i);
  });

  it("renders backend-verified violations directly, never a frontend-invented verdict", () => {
    renderWithContext(<ViolationsPanel />, {
      editMode: "EDIT_LAYOUT",
      draftLayout: draft,
      layoutValidation: {
        valid: false, error_count: 1, warning_count: 0,
        violations: [{ violation_type: "AISLE_BLOCKED", severity: "ERROR", message: "Machine 'm-packaging' footprint blocks aisle 'z-aisle'.", machine_ids: ["m-packaging"], zone_ids: ["z-aisle"], details: null }],
      },
    });
    expect(screen.getByTestId("validation-verdict")).toHaveTextContent("1 error(s)");
    expect(screen.getByTestId("violation-AISLE_BLOCKED")).toHaveTextContent(/blocks aisle/i);
  });

  it("shows VALID when there are zero violations", () => {
    renderWithContext(<ViolationsPanel />, {
      editMode: "EDIT_LAYOUT", draftLayout: draft,
      layoutValidation: { valid: true, error_count: 0, warning_count: 0, violations: [] },
    });
    expect(screen.getByTestId("validation-verdict")).toHaveTextContent("VALID");
  });
});
