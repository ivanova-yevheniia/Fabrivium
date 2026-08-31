import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sampleFactory } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { SelectedMachinePanel } from "./SelectedMachinePanel";

describe("SelectedMachinePanel", () => {
  it("renders nothing when no machine is selected", () => {
    renderWithContext(<SelectedMachinePanel />, { selectedMachineId: null });
    expect(screen.queryByTestId("selected-machine-panel")).not.toBeInTheDocument();
  });

  it("shows the section-3 field list for the selected machine, verbatim from Machine data", () => {
    renderWithContext(
      <SelectedMachinePanel />,
      { selectedMachineId: "m-a", factory: sampleFactory, layout: null },
      { currentStageFactory: () => sampleFactory },
    );
    const panel = screen.getByTestId("selected-machine-panel");
    expect(panel).toHaveTextContent("Machine A");
    expect(panel).toHaveTextContent("m-a");
    expect(panel).toHaveTextContent("assembly");
    expect(panel).toHaveTextContent("EXISTING");
  });

  it("shows 'unplaced' for position when the machine has no placement in the active layout", () => {
    renderWithContext(
      <SelectedMachinePanel />,
      { selectedMachineId: "m-a", factory: sampleFactory, layout: null },
      { currentStageFactory: () => sampleFactory },
    );
    expect(screen.getByTestId("selected-machine-panel")).toHaveTextContent(/unplaced/i);
  });

  it("shows position/rotation when the machine has a placement in draftLayout", () => {
    renderWithContext(
      <SelectedMachinePanel />,
      {
        selectedMachineId: "m-a", factory: sampleFactory,
        draftLayout: { factory_width: 20, factory_length: 10, placements: [{ machine_id: "m-a", x: 7, y: 3, z: 0, rotation_deg: 90 }], reserved_zones: [], aisle_zones: [] },
      },
      { currentStageFactory: () => sampleFactory },
    );
    const panel = screen.getByTestId("selected-machine-panel");
    // Phase 12 §9 regrouped the inspector and dropped the parentheses around
    // the coordinate pair; the assertion still pins that the placement's real
    // x/y and rotation are rendered, which is what this test exists for.
    expect(panel).toHaveTextContent(/7,\s*3/);
    expect(panel).toHaveTextContent("90°");
  });

  it("shows 'no simulation KPI available' when no session exists yet — never recomputes one", () => {
    renderWithContext(
      <SelectedMachinePanel />,
      { selectedMachineId: "m-a", factory: sampleFactory, session: null },
      { currentStageFactory: () => sampleFactory },
    );
    expect(screen.getByTestId("selected-machine-no-kpi")).toBeInTheDocument();
  });
});
