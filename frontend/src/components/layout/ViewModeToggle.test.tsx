import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithContext } from "../../test/testUtils";
import { ViewModeToggle } from "./ViewModeToggle";

describe("ViewModeToggle", () => {
  it("marks 2D active by default", () => {
    renderWithContext(<ViewModeToggle />, { viewMode: "2D" });
    expect(screen.getByTestId("view-mode-2d-button").className).toMatch(/active/);
    expect(screen.getByTestId("view-mode-3d-button").className).not.toMatch(/active/);
  });

  it("marks 3D active when viewMode is 3D", () => {
    renderWithContext(<ViewModeToggle />, { viewMode: "3D" });
    expect(screen.getByTestId("view-mode-3d-button").className).toMatch(/active/);
  });

  it("clicking 2D/3D calls setViewMode with the right mode", () => {
    const { contextValue } = renderWithContext(<ViewModeToggle />, { viewMode: "2D" });
    fireEvent.click(screen.getByTestId("view-mode-3d-button"));
    expect(contextValue.setViewMode).toHaveBeenCalledWith("3D");
    fireEvent.click(screen.getByTestId("view-mode-2d-button"));
    expect(contextValue.setViewMode).toHaveBeenCalledWith("2D");
  });
});
