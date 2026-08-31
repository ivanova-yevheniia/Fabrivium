import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ConstraintViolation, Factory, FactoryLayout } from "../../api/types";
import { sampleFactory } from "../../test/fixtures";
import { FactoryWorkspace } from "./FactoryWorkspace";

/**
 * jsdom implements no SVG geometry APIs (createSVGPoint/getScreenCTM) at
 * all — not even as inherited no-ops. Rather than guess which global
 * class jsdom exposes for which SVG tag (version-fragile), patch the
 * EXACT rendered <svg>/<g> instances directly with a trivial IDENTITY
 * transform (client coordinates pass through unchanged). This is enough
 * to test DRAG MECHANICS/wiring; the real geometry math (rotation,
 * asymmetric envelopes, coordinate mapping) is already exhaustively
 * covered by utils/geometry.test.ts's pure unit tests, which need no DOM.
 */
function installSvgGeometryMocks() {
  const svg = screen.getByTestId("factory-workspace-svg") as unknown as SVGSVGElement;
  const group = screen.getByTestId("factory-workspace-group") as unknown as SVGGElement;

  Object.defineProperty(svg, "createSVGPoint", {
    configurable: true,
    value: () => {
      let px = 0;
      let py = 0;
      return {
        get x() { return px; },
        set x(v: number) { px = v; },
        get y() { return py; },
        set y(v: number) { py = v; },
        matrixTransform() { return { x: px, y: py }; },
      };
    },
  });
  Object.defineProperty(group, "getScreenCTM", {
    configurable: true,
    value: () => ({ inverse: () => ({}) }),
  });
}

/** jsdom has no native `PointerEvent` constructor at all (verified: `new
 * window.PointerEvent(...)` throws "not a constructor"), so
 * `fireEvent.pointerDown`'s clientX/clientY never reach the handler.
 * Build a plain Event and attach the coordinate fields directly. */
function firePointerEvent(node: Element, type: string, init: { clientX: number; clientY: number; pointerId?: number }) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clientX", { value: init.clientX });
  Object.defineProperty(event, "clientY", { value: init.clientY });
  Object.defineProperty(event, "pointerId", { value: init.pointerId ?? 1 });
  fireEvent(node, event);
}

const layoutFactory: Factory = {
  ...sampleFactory,
  machines: sampleFactory.machines.map((m) =>
    m.id === "m-b" ? { ...m, asset: { asset_type: "PROXY", status: "AVAILABLE", asset_uri: null, source_uri: null, manufacturer: null, model_number: null, license_name: null, attribution: null, file_format: null, notes: null }, physical_envelope: { height: null, safety_clearance_front: 2, safety_clearance_back: 0, safety_clearance_left: 0.5, safety_clearance_right: 0.5 } } : m,
  ),
};

function sampleLayout(): FactoryLayout {
  return {
    factory_width: layoutFactory.width,
    factory_length: layoutFactory.length,
    placements: [
      { machine_id: "m-a", x: 5, y: 5, z: 0, rotation_deg: 0 },
      { machine_id: "m-b", x: 12, y: 5, z: 0, rotation_deg: 90 },
    ],
    reserved_zones: [{ id: "z-reserved", name: "Tooling", x: 0, y: 8, width: 4, length: 2, zone_type: "RESERVED" }],
    aisle_zones: [{ id: "z-aisle", name: "Main Aisle", x: 0, y: 6, width: 20, length: 1, zone_type: "AISLE" }],
  };
}

describe("FactoryWorkspace", () => {
  it("shows an empty state with no factory", () => {
    render(
      <FactoryWorkspace
        factory={null}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate={false}
        bottleneckMachineId={null}
        onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("factory-workspace")).toHaveTextContent(/no factory loaded/i);
  });

  it("renders every machine in route order as a flow diagram when no layout is supplied", () => {
    render(
      <FactoryWorkspace
        factory={sampleFactory}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate={false}
        bottleneckMachineId="m-a"
        onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-node-m-a")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-b")).toBeInTheDocument();
  });

  it("marks the bottleneck machine distinctly", () => {
    render(
      <FactoryWorkspace
        factory={sampleFactory}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate={false}
        bottleneckMachineId="m-a"
        onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-node-m-a").className).toMatch(/node--bottleneck/);
    expect(screen.getByTestId("workspace-node-m-b").className).not.toMatch(/node--bottleneck/);
  });

  it("calls onSelectMachine when a node is clicked", () => {
    const onSelectMachine = vi.fn();
    render(
      <FactoryWorkspace
        factory={sampleFactory}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate={false}
        bottleneckMachineId={null}
        onSelectMachine={onSelectMachine}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-node-m-b"));
    expect(onSelectMachine).toHaveBeenCalledWith("m-b");
  });

  it("shows the rejected-candidate notice only when isRejectedCandidate is true", () => {
    const { rerender } = render(
      <FactoryWorkspace
        factory={sampleFactory}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate={false}
        bottleneckMachineId={null}
        onSelectMachine={() => {}}
      />,
    );
    expect(screen.queryByTestId("workspace-rejected-candidate-notice")).not.toBeInTheDocument();

    rerender(
      <FactoryWorkspace
        factory={sampleFactory}
        layout={null}
        selectedMachineId={null}
        highlightedMachineIds={[]}
        isRejectedCandidate
        bottleneckMachineId={null}
        onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-rejected-candidate-notice")).toBeInTheDocument();
  });
});

describe("FactoryWorkspace — 2D canvas (Phase 6B)", () => {
  it("renders the SVG canvas (not the flow diagram) when a layout is supplied", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("factory-workspace-svg")).toBeInTheDocument();
    expect(screen.queryByTestId("factory-workspace-flow")).not.toBeInTheDocument();
  });

  it("renders the factory boundary", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("factory-boundary")).toBeInTheDocument();
  });

  it("renders every placed machine and its safety envelope", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-node-m-a")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-node-m-b")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-envelope-m-a")).toBeInTheDocument();
    expect(screen.getByTestId("workspace-envelope-m-b")).toBeInTheDocument();
  });

  it("renders AISLE and RESERVED zones distinctly", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-zone-z-aisle")).toHaveTextContent("AISLE");
    expect(screen.getByTestId("workspace-zone-z-reserved")).toHaveTextContent("RESERVED");
  });

  it("marks the selected machine", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId="m-b" highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-node-m-b").getAttribute("data-selected")).toBe("true");
    expect(screen.getByTestId("workspace-node-m-a").getAttribute("data-selected")).toBeNull();
  });

  it("clicking a machine in canvas mode calls onSelectMachine", () => {
    const onSelectMachine = vi.fn();
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={onSelectMachine}
      />,
    );
    fireEvent.click(screen.getByTestId("workspace-node-m-a"));
    expect(onSelectMachine).toHaveBeenCalledWith("m-a");
  });

  it("shows a PROXY visual marker for a PROXY-asset machine", () => {
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
      />,
    );
    expect(screen.getByTestId("workspace-node-m-b")).toHaveTextContent("PROXY");
    expect(screen.getByTestId("workspace-node-m-a")).not.toHaveTextContent("PROXY");
  });

  it("highlights machines named in ERROR-severity violations", () => {
    const violations: ConstraintViolation[] = [
      { violation_type: "MACHINE_OVERLAP", severity: "ERROR", message: "overlap", machine_ids: ["m-a", "m-b"], zone_ids: [], details: null },
    ];
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}} violations={violations}
      />,
    );
    const polygonStroke = screen.getByTestId("workspace-node-m-a").querySelectorAll("polygon")[1]?.getAttribute("stroke");
    expect(polygonStroke).toBe("var(--fm-bad)");
  });

  it("highlights the aisle zone named in an AISLE_BLOCKED violation", () => {
    const violations: ConstraintViolation[] = [
      { violation_type: "AISLE_BLOCKED", severity: "ERROR", message: "blocks aisle", machine_ids: ["m-a"], zone_ids: ["z-aisle"], details: null },
    ];
    render(
      <FactoryWorkspace
        factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
        isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}} violations={violations}
      />,
    );
    const stroke = screen.getByTestId("workspace-zone-z-aisle").querySelector("polygon")?.getAttribute("stroke");
    expect(stroke).toBe("var(--fm-bad)");
  });

  describe("drag behavior (jsdom SVG geometry mocked — see installSvgGeometryMocks)", () => {
    it("does not allow drag when editable=false, even with onMoveMachine supplied", () => {
      const onMoveMachine = vi.fn();
      render(
        <FactoryWorkspace
          factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
          isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
          editable={false} onMoveMachine={onMoveMachine}
        />,
      );
      installSvgGeometryMocks();
      const node = screen.getByTestId("workspace-node-m-a");
      firePointerEvent(node, "pointerdown", { clientX: 100, clientY: 50 });
      firePointerEvent(node, "pointermove", { clientX: 130, clientY: 70 });
      firePointerEvent(node, "pointerup", { clientX: 130, clientY: 70 });
      expect(onMoveMachine).not.toHaveBeenCalled();
    });

    it("commits a move via onMoveMachine on drop when editable", () => {
      const onMoveMachine = vi.fn();
      const onSelectMachine = vi.fn();
      render(
        <FactoryWorkspace
          factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
          isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={onSelectMachine}
          editable onMoveMachine={onMoveMachine}
        />,
      );
      installSvgGeometryMocks();
      const node = screen.getByTestId("workspace-node-m-a");
      // Placement m-a is at factory (5,5). With the identity-mocked CTM,
      // matrixTransform returns clientX/clientY unchanged as SCALE'd px
      // (matching what a real (non-mocked) CTM inverse would return —
      // see toFactoryPoint's SCALE divide), so clientX/Y must be
      // pre-multiplied by SCALE(16) here for the resulting factory point
      // to land on a clean, checkable metre value.
      const SCALE = 16;
      firePointerEvent(node, "pointerdown", { clientX: 5 * SCALE, clientY: 5 * SCALE, pointerId: 1 });
      firePointerEvent(node, "pointermove", { clientX: 15 * SCALE, clientY: 15 * SCALE, pointerId: 1 });
      firePointerEvent(node, "pointerup", { clientX: 15 * SCALE, clientY: 15 * SCALE, pointerId: 1 });
      expect(onSelectMachine).toHaveBeenCalledWith("m-a");
      expect(onMoveMachine).toHaveBeenCalledTimes(1);
      const [machineId, x, y] = onMoveMachine.mock.calls[0];
      expect(machineId).toBe("m-a");
      expect(x).toBeCloseTo(15);
      expect(y).toBeCloseTo(15);
    });

    it("regression: a small on-screen drag produces a small in-metres move, not a SCALE(16)x-inflated one (found via real-browser drag testing, Phase 6C.1 — toFactoryPoint previously returned SCALE'd px straight through, so a 150px drag moved a machine ~150 METRES instead of ~9)", () => {
      const onMoveMachine = vi.fn();
      render(
        <FactoryWorkspace
          factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
          isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
          editable onMoveMachine={onMoveMachine}
        />,
      );
      installSvgGeometryMocks();
      const node = screen.getByTestId("workspace-node-m-a");
      const SCALE = 16;
      // Placement m-a starts at factory (5,5) -> SCALE'd screen (80,80).
      // A 150px on-screen drag must move it by 150/SCALE ~= 9.4m, landing
      // well within the factory (never hundreds of metres out of bounds).
      firePointerEvent(node, "pointerdown", { clientX: 5 * SCALE, clientY: 5 * SCALE, pointerId: 1 });
      firePointerEvent(node, "pointermove", { clientX: 5 * SCALE, clientY: 5 * SCALE + 150, pointerId: 1 });
      firePointerEvent(node, "pointerup", { clientX: 5 * SCALE, clientY: 5 * SCALE + 150, pointerId: 1 });
      const [, , y] = onMoveMachine.mock.calls[0];
      expect(y).toBeCloseTo(5 + 150 / SCALE);
      expect(y).toBeLessThan(20); // sanity: still inside the 20m-long sample factory
    });

    it("shows a preview position while dragging without calling onMoveMachine until drop", () => {
      const onMoveMachine = vi.fn();
      render(
        <FactoryWorkspace
          factory={layoutFactory} layout={sampleLayout()} selectedMachineId={null} highlightedMachineIds={[]}
          isRejectedCandidate={false} bottleneckMachineId={null} onSelectMachine={() => {}}
          editable onMoveMachine={onMoveMachine}
        />,
      );
      installSvgGeometryMocks();
      const node = screen.getByTestId("workspace-node-m-a");
      firePointerEvent(node, "pointerdown", { clientX: 5, clientY: 5, pointerId: 1 });
      firePointerEvent(node, "pointermove", { clientX: 8, clientY: 8, pointerId: 1 });
      expect(node.getAttribute("data-dragging")).toBe("true");
      expect(onMoveMachine).not.toHaveBeenCalled();
    });
  });
});
