import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { sampleSessionRejected, sampleSessionTwoIterations } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { CenterWorkspace } from "./CenterWorkspace";

vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children, "data-testid": testId }: { children: React.ReactNode; "data-testid"?: string }) => (
    <div data-testid={testId}>{children}</div>
  ),
}));
vi.mock("@react-three/drei", () => ({
  Html: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useGLTF: () => ({ scene: { clone: () => ({ traverse: () => {} }) } }),
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  Grid: () => null,
}));

describe("CenterWorkspace", () => {
  it("baseline stage renders the baseline factory's machines only", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline" });
    expect(screen.getByTestId("workspace-node-m-a")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-b")).toBeInTheDocument();
    expect(screen.queryByTestId("workspace-node-m-a-parallel-1")).not.toBeInTheDocument();
  });

  it("iteration 1 stage renders iteration 1's exact machine set", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: 0 });
    expect(screen.getByTestId("workspace-node-m-a-parallel-1")).toBeInTheDocument();
    expect(screen.queryByTestId("workspace-node-m-b-parallel-1")).not.toBeInTheDocument();
  });

  it("iteration 2 stage renders both accepted clones", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: 1 });
    expect(screen.getByTestId("workspace-node-m-a-parallel-1")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-b-parallel-1")).toBeInTheDocument();
  });

  it("final stage matches iteration 2's geometry exactly", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "final" });
    expect(screen.getByTestId("workspace-node-m-a-parallel-1")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-b-parallel-1")).toBeInTheDocument();
  });

  it("a rejected candidate stage shows the rejected-candidate notice, never presented as accepted", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionRejected, selectedIteration: 0 });
    expect(screen.getByTestId("workspace-rejected-candidate-notice")).toBeInTheDocument();
  });

  it("does not fabricate a layout when the session legitimately has none — renders the flow diagram instead", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "final" });
    expect(screen.getByTestId("factory-workspace-flow")).toBeInTheDocument();
    expect(screen.queryByTestId("factory-workspace-svg")).not.toBeInTheDocument();
  });

  it("Phase 9A section 8 — suppresses the alarm BOTTLENECK flag once the final stage's demand is met", () => {
    // sampleSessionTwoIterations' final stage has demand_met=true and a real
    // bottleneck_machine_id ("m-a") — the stage must still be nameable, just
    // never flagged with the same styling as a genuine constraint violation.
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "final" });
    expect(screen.queryByText(/BOTTLENECK/)).not.toBeInTheDocument();
  });

  it("Phase 9A section 8 — KEEPS the alarm BOTTLENECK flag when the baseline stage's demand is not met", () => {
    renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline" });
    expect(screen.getByText(/BOTTLENECK/)).toBeInTheDocument();
  });

  describe("Phase 6C — 2D/3D toggle", () => {
    it("defaults to the 2D view", () => {
      renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline" });
      expect(screen.getByTestId("factory-workspace")).toBeInTheDocument();
      expect(screen.queryByTestId("factory-workspace-3d")).not.toBeInTheDocument();
    });

    it("renders the 3D workspace instead of 2D when viewMode is 3D", () => {
      renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline", viewMode: "3D" });
      expect(screen.getByTestId("factory-workspace-3d")).toBeInTheDocument();
      expect(screen.queryByTestId("factory-workspace")).not.toBeInTheDocument();
    });

    it("3D also refuses to fabricate a layout when the session legitimately has none", () => {
      renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "final", viewMode: "3D" });
      expect(screen.getByTestId("workspace-no-layout-notice-3d")).toBeInTheDocument();
    });

    it("clicking the 3D toggle button calls setViewMode without touching selection", () => {
      const { contextValue } = renderWithContext(<CenterWorkspace />, { session: sampleSessionTwoIterations, selectedIteration: "baseline", selectedMachineId: "m-a" });
      fireEvent.click(screen.getByTestId("view-mode-3d-button"));
      expect(contextValue.setViewMode).toHaveBeenCalledWith("3D");
      expect(contextValue.selectMachine).not.toHaveBeenCalled();
      expect(contextValue.selectIteration).not.toHaveBeenCalled();
    });
  });
});
