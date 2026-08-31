import { fireEvent, render, screen } from "@testing-library/react";
import { forwardRef } from "react";
import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { FactoryLayout } from "../../api/types";
import { sampleFactory } from "../../test/fixtures";
import { FactoryWorkspace3D } from "./FactoryWorkspace3D";

vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children, "data-testid": testId }: { children: React.ReactNode; "data-testid"?: string }) => (
    <div data-testid={testId}>{children}</div>
  ),
}));
vi.mock("@react-three/drei", () => ({
  Html: ({ children, "data-testid": testId }: { children: React.ReactNode; "data-testid"?: string }) => (
    <div data-testid={testId}>{children}</div>
  ),
  useGLTF: () => {
    const group = new THREE.Group();
    group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1)));
    return { scene: group };
  },
  // forwardRef so Scene3D's cameraRef/controlsRef attach without React's
  // "function components cannot be given refs" warning (Scene3D.resetView
  // reads .current off both — see the real-browser fix in Scene3D.tsx).
  OrbitControls: forwardRef(() => null),
  PerspectiveCamera: forwardRef(() => null),
  Grid: () => null,
}));

function sampleLayout(): FactoryLayout {
  return {
    factory_width: sampleFactory.width, factory_length: sampleFactory.length,
    placements: [
      { machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 },
      { machine_id: "m-b", x: 12, y: 5, z: 0, rotation_deg: 0 },
    ],
    reserved_zones: [], aisle_zones: [],
  };
}

describe("FactoryWorkspace3D", () => {
  it("shows an empty state with no factory", () => {
    render(
      <FactoryWorkspace3D factory={null} layout={null} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    expect(screen.getByTestId("factory-workspace-3d")).toHaveTextContent(/no factory loaded/i);
  });

  it("shows an honest 'no layout' message rather than fabricating one, when the stage legitimately has none", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={null} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    expect(screen.getByTestId("workspace-no-layout-notice-3d")).toBeInTheDocument();
    expect(screen.queryByTestId("factory-workspace-3d-canvas")).not.toBeInTheDocument();
  });

  it("renders the canvas and every placed machine when a layout is supplied", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    expect(screen.getByTestId("factory-workspace-3d-canvas")).toBeInTheDocument();
    // Machine3D identifies itself via the `name` prop, not data-testid — see
    // the comment in Machine3D.test.tsx (data-testid crashes the real R3F
    // renderer; name is the safe, dash-free equivalent).
    expect(document.querySelector('[name="machine3d-m-a"]')).toBeInTheDocument();
    expect(document.querySelector('[name="machine3d-m-b"]')).toBeInTheDocument();
  });

  it("shows the rejected-candidate notice only when isRejectedCandidate is true", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    expect(screen.getByTestId("workspace-rejected-candidate-notice-3d")).toBeInTheDocument();
  });

  it("clicking a machine calls onSelectMachine, syncing with the same selection state 2D uses", () => {
    const onSelectMachine = vi.fn();
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={onSelectMachine} />,
    );
    fireEvent.click(document.querySelector('[name="machine3d-m-b"]') as HTMLElement);
    expect(onSelectMachine).toHaveBeenCalledWith("m-b");
  });

  it("has a Reset View control", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    expect(screen.getByTestId("reset-view-button")).toBeInTheDocument();
  });

  /** G16 — the concept-visualization disclosure must survive a short canvas. */
  it("keeps the concept-visualization disclosure inside the canvas overlay layer", () => {
    const { container } = render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );

    const wrap = container.querySelector(".factory-workspace-3d__canvas-wrap");
    const overlays = container.querySelector(".scene-overlays");
    const plaque = screen.getByText(/Exact supplier equipment has not been selected/i);

    expect(wrap).not.toBeNull();
    expect(overlays?.parentElement).toBe(wrap);
    expect(overlays?.contains(plaque)).toBe(true);
  });

  it("states the disclosure in full, at full size", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );

    // The sentence is the disclosure. Truncating it, or shrinking it out of
    // legibility to make it fit, would be a worse failure than clipping it.
    const plaque = screen.getByText(/Exact supplier equipment has not been selected/i);
    expect(plaque.textContent).not.toMatch(/…|\.\.\./);
  });

  it("Reset View moves the existing camera/controls instead of remounting the Canvas (regression: a key-based remount tears down and recreates the whole WebGL context, logging a spurious 'Context Lost' from the discarded canvas — found via real-browser inspection, Phase 6C.1)", () => {
    render(
      <FactoryWorkspace3D factory={sampleFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]} isRejectedCandidate={false} bottleneckMachineId={null} limitingStageId={null} limitingStageLabel="Limiting stage" onSelectMachine={() => {}} />,
    );
    const canvasBefore = screen.getByTestId("factory-workspace-3d-canvas");
    fireEvent.click(screen.getByTestId("reset-view-button"));
    const canvasAfter = screen.getByTestId("factory-workspace-3d-canvas");
    expect(canvasAfter).toBe(canvasBefore);
  });
});
