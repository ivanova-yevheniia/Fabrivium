import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import type { EquipmentAsset, MachinePlacement } from "../../api/types";
import { sampleFactory } from "../../test/fixtures";
import { Machine3D } from "./Machine3D";

/**
 * These tests render Machine3D OUTSIDE a real <Canvas> (no WebGL in
 * jsdom) — React DOM treats the lowercase three.js JSX tags (<mesh>,
 * <group>, ...) as generic unknown elements, which is enough to assert on
 * our own data-testid/text-content wiring (click handling, label text,
 * conditional rendering). It does NOT exercise real WebGL rendering —
 * that's a manual/visual concern (see the Phase 6C final report).
 */
let failGltfLoad = false;

vi.mock("@react-three/drei", () => ({
  Html: ({ children, "data-testid": testId }: { children: React.ReactNode; "data-testid"?: string }) => (
    <div data-testid={testId}>{children}</div>
  ),
  useGLTF: () => {
    if (failGltfLoad) throw new Error("simulated GLB load failure");
    const group = new THREE.Group();
    group.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1)));
    return { scene: group };
  },
}));

function placement(overrides: Partial<MachinePlacement> = {}): MachinePlacement {
  return { machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0, ...overrides };
}

function assetOf(overrides: Partial<EquipmentAsset>): EquipmentAsset {
  return {
    asset_type: "EXACT_CAD", status: "AVAILABLE", asset_uri: "https://example.com/m.glb",
    source_uri: null, manufacturer: null, model_number: null, license_name: null, attribution: null, file_format: "GLB", notes: null,
    ...overrides,
  };
}

const [machineA] = sampleFactory.machines;

/** Machine3D's <group>/<mesh> identify themselves via the `name` prop, NOT `data-testid`. */
function machineGroup(id: string): HTMLElement {
  const el = document.querySelector(`[name="machine3d-${id}"]`);
  if (!el) throw new Error(`no element with name="machine3d-${id}"`);
  return el as HTMLElement;
}

function machineOutline(id: string): Element | null {
  return document.querySelector(`[name="machine3d-outline-${id}"]`);
}

describe("Machine3D", () => {
  it("renders a machine with no machine-level asset but a matching generic asset-pack category as GENERIC, not silently exact", () => {
    render(
      <Machine3D machine={machineA} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(machineGroup("m-a")).toBeInTheDocument();
    expect(machineGroup("m-a")).toHaveTextContent("GENERIC");
  });

  it("renders a proxy box for a machine with no asset and no generic asset-pack match either (MISSING)", () => {
    render(
      <Machine3D machine={{ ...machineA, process_type: "laser welding" }} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(machineGroup("m-a")).toBeInTheDocument();
    expect(machineGroup("m-a")).toHaveTextContent("NO ASSET");
  });

  it("shows the friendly machine name as the label", () => {
    render(
      <Machine3D machine={machineA} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(screen.getByTestId("machine3d-label-m-a")).toHaveTextContent("A");
  });

  it("marks a PROXY asset distinctly, never as a normal machine", () => {
    render(
      <Machine3D machine={{ ...machineA, asset: assetOf({ asset_type: "PROXY", asset_uri: null, file_format: null }) }} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(machineGroup("m-a")).toHaveTextContent("PROXY");
  });

  it("does not tag an EXACT_CAD machine with any placeholder label", () => {
    render(
      <Machine3D machine={{ ...machineA, asset: assetOf({}) }} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    const node = machineGroup("m-a");
    expect(node).not.toHaveTextContent("PROXY");
    expect(node).not.toHaveTextContent("NO ASSET");
  });

  it("calls onSelect with the machine id when clicked", () => {
    const onSelect = vi.fn();
    render(
      <Machine3D machine={machineA} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={onSelect} />,
    );
    fireEvent.click(machineGroup("m-a"));
    expect(onSelect).toHaveBeenCalledWith("m-a");
  });

  it("falls back to the procedural proxy silhouette (never crashes the scene) when a GLB fails to load", () => {
    failGltfLoad = true;
    try {
      render(
        <Machine3D machine={{ ...machineA, asset: assetOf({}) }} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
      );
      // Reaching this assertion at all proves GltfErrorBoundary caught the
      // simulated load failure — an uncaught error here would abort the
      // whole test (and, in production, the whole 3D scene).
      expect(machineGroup("m-a")).toBeInTheDocument();
    } finally {
      failGltfLoad = false;
    }
  });

  it("shows a selection/violation outline element only when one applies", () => {
    const { rerender } = render(
      <Machine3D machine={machineA} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation={false} isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(machineOutline("m-a")).not.toBeInTheDocument();

    rerender(
      <Machine3D machine={machineA} placement={placement()} selected={false} highlighted={false} isBottleneck={false} isErrorViolation isWarningViolation={false} onSelect={() => {}} />,
    );
    expect(machineOutline("m-a")).toBeInTheDocument();
  });
});
