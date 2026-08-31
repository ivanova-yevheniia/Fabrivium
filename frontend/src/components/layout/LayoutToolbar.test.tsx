import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithContext } from "../../test/testUtils";
import { LayoutToolbar } from "./LayoutToolbar";

const draft = { factory_width: 20, factory_length: 10, placements: [{ machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 }], reserved_zones: [], aisle_zones: [] };

describe("LayoutToolbar", () => {
  it("VIEW is the default mode; EDIT LAYOUT calls enterEditMode", () => {
    const { contextValue } = renderWithContext(<LayoutToolbar />, { factory: { name: "F" } as never });
    expect(screen.getByTestId("mode-view-button").className).toMatch(/active/);
    fireEvent.click(screen.getByTestId("mode-edit-button"));
    expect(contextValue.enterEditMode).toHaveBeenCalled();
  });

  it("Validate/Apply/Reset Draft only render in EDIT_LAYOUT mode", () => {
    renderWithContext(<LayoutToolbar />, { editMode: "VIEW" });
    expect(screen.queryByTestId("apply-button")).not.toBeInTheDocument();
  });

  it("Apply is disabled until validation has zero errors", () => {
    renderWithContext(<LayoutToolbar />, {
      editMode: "EDIT_LAYOUT", draftLayout: draft, layoutValidation: { valid: false, error_count: 1, warning_count: 0, violations: [] },
    });
    expect(screen.getByTestId("apply-button")).toBeDisabled();
  });

  it("Apply is enabled once validation reports zero errors", () => {
    renderWithContext(<LayoutToolbar />, {
      editMode: "EDIT_LAYOUT", draftLayout: draft, layoutValidation: { valid: true, error_count: 0, warning_count: 0, violations: [] },
    });
    expect(screen.getByTestId("apply-button")).toBeEnabled();
  });

  it("clicking Reset Draft calls resetDraft", () => {
    const { contextValue } = renderWithContext(<LayoutToolbar />, { editMode: "EDIT_LAYOUT", draftLayout: draft });
    fireEvent.click(screen.getByTestId("reset-draft-button"));
    expect(contextValue.resetDraft).toHaveBeenCalled();
  });

  it("rotation buttons appear only when a placed machine is selected, and call rotateMachine", () => {
    const { contextValue } = renderWithContext(<LayoutToolbar />, {
      editMode: "EDIT_LAYOUT", draftLayout: draft, selectedMachineId: "m-a",
    });
    fireEvent.click(screen.getByTestId("rotate-plus-90"));
    expect(contextValue.rotateMachine).toHaveBeenCalledWith("m-a", 90);
    fireEvent.click(screen.getByTestId("rotate-minus-90"));
    expect(contextValue.rotateMachine).toHaveBeenCalledWith("m-a", -90);
  });

  it("shows the dirty indicator only when isDirty is true", () => {
    renderWithContext(<LayoutToolbar />, { isDirty: false });
    expect(screen.queryByTestId("dirty-indicator")).not.toBeInTheDocument();
  });

  it("shows the dirty indicator when isDirty is true", () => {
    renderWithContext(<LayoutToolbar />, { isDirty: true, editMode: "EDIT_LAYOUT", draftLayout: draft });
    expect(screen.getByTestId("dirty-indicator")).toBeInTheDocument();
  });
});
