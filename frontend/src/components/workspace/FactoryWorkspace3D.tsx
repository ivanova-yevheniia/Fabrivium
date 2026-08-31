import { Canvas } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ConstraintViolation, Factory, FactoryLayout } from "../../api/types";
import { OperatorHud } from "../playback/OperatorHud";
import { AssetProvenanceLegend } from "./AssetProvenanceLegend";
import { SceneLegend } from "./SceneLegend";
import type { TraceIndex } from "../../utils/traceIndex";
import { Scene3D } from "./Scene3D";
import type { Scene3DHandle } from "./Scene3D";

/** The canvas's live aspect ratio. */
function useCanvasAspect(ref: React.RefObject<HTMLElement>): number {
  // 16/9 until measured, which is also the fallback wherever no measurement
  // is possible (jsdom reports every element as 0 x 0).
  const [aspect, setAspect] = useState(16 / 9);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;

    const read = () => {
      const { width, height } = element.getBoundingClientRect();
      if (width > 0 && height > 0) setAspect(width / height);
    };
    read();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(read);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return aspect;
}

/**
 * 3D sibling of <FactoryWorkspace /> (Phase 6C) — SAME prop contract as
 * the 2D canvas (Phase 6A section 8's stability promise extended: either
 * view can be swapped for the other, or replaced internally later,
 * without the surrounding shell/state changing). View-only: there is no
 * onMoveMachine here — 3D never edits (section 1/10).
 */
export interface FactoryWorkspace3DProps {
  factory: Factory | null;
  layout: FactoryLayout | null;
  selectedMachineId: string | null;
  highlightedMachineIds: string[];
  isRejectedCandidate: boolean;
  /** Set only when demand was NOT met, so red alarm styling is honest. */
  bottleneckMachineId: string | null;
  /** The stage that limits throughput, whether or not the target was met. */
  limitingStageId: string | null;
  /** "Bottleneck" or "Limiting stage", decided by the same rule the KPI
   * panel uses so the two never disagree on screen. */
  limitingStageLabel: string;
  onSelectMachine: (machineId: string) => void;
  violations?: ConstraintViolation[];
  /** Phase 8C — see Scene3DProps. */
  traceIndex?: TraceIndex | null;
  simTime?: number;
  productId?: string | null;
  /** A pending imperative camera request from outside. */
  cameraFocusRequest?: "overview" | "bottleneck" | "selected" | null;
  onCameraFocusHandled?: () => void;
  /** Phase 10 — see Scene3DProps.presentation. Presentation only. */
  presentation?: "EXECUTIVE" | "ENGINEERING";
  /** Phase 12.1 — layout editing, same contract as <FactoryWorkspace />. */
  editable?: boolean;
  onMoveMachine?: (machineId: string, x: number, y: number) => void;
}

export function FactoryWorkspace3D({
  factory,
  layout,
  selectedMachineId,
  highlightedMachineIds,
  isRejectedCandidate,
  bottleneckMachineId,
  limitingStageId,
  limitingStageLabel,
  onSelectMachine,
  violations = [],
  traceIndex = null,
  simTime = 0,
  productId = null,
  cameraFocusRequest = null,
  onCameraFocusHandled,
  presentation = "ENGINEERING",
  editable = false,
  onMoveMachine,
}: FactoryWorkspace3DProps) {
  const sceneRef = useRef<Scene3DHandle>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const aspect = useCanvasAspect(canvasWrapRef);

  const focusMachine = (machineId: string | null) => {
    if (!machineId || !layout) return;
    const placement = layout.placements.find((p) => p.machine_id === machineId);
    const machine = factory?.machines.find((m) => m.id === machineId);
    if (!placement || !machine) return;
    const span = Math.max(machine.width, machine.length) * 3;
    sceneRef.current?.focusOn(placement.x, placement.y, span);
  };

  // External focus requests are applied once, imperatively, then cleared
  // — never a persistent camera "mode".
  useEffect(() => {
    if (!cameraFocusRequest) return;
    if (cameraFocusRequest === "overview") sceneRef.current?.resetView();
    else if (cameraFocusRequest === "bottleneck") focusMachine(limitingStageId);
    else if (cameraFocusRequest === "selected") focusMachine(selectedMachineId);
    onCameraFocusHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraFocusRequest]);

  if (!factory) {
    return (
      <div className="factory-workspace" data-testid="factory-workspace-3d">
        <p className="fm-empty">No factory loaded.</p>
      </div>
    );
  }

  if (!layout) {
    return (
      <div className="factory-workspace" data-testid="factory-workspace-3d">
        <p className="factory-workspace__notice" data-testid="workspace-no-layout-notice-3d">
          No floor layout is available for this state — 3D requires real placements. Enter Edit Layout
          (2D) to place machines on the floor.
        </p>
      </div>
    );
  }

  return (
    <div className="factory-workspace factory-workspace--3d" data-testid="factory-workspace-3d">
      {isRejectedCandidate && (
        <p className="factory-workspace__notice" data-testid="workspace-rejected-candidate-notice-3d">
          Rejected candidate — this geometry was evaluated but never accepted into the factory's history.
        </p>
      )}
      <div className="factory-workspace-3d__toolbar">
        <button type="button" className="fm-btn-secondary" onClick={() => sceneRef.current?.resetView()} data-testid="reset-view-button">
          Reset view
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={() => focusMachine(limitingStageId)}
          disabled={!limitingStageId}
          data-testid="focus-bottleneck-button"
        >
          Focus {limitingStageLabel.toLowerCase()}
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={() => focusMachine(selectedMachineId)}
          disabled={!selectedMachineId}
          data-testid="focus-selected-button"
        >
          Focus selected station
        </button>
      </div>
      <div className="factory-workspace-3d__canvas-wrap" ref={canvasWrapRef}>
        <Canvas shadows data-testid="factory-workspace-3d-canvas">
          <Scene3D
            ref={sceneRef}
            factory={factory}
            layout={layout}
            aspect={aspect}
            selectedMachineId={selectedMachineId}
            highlightedMachineIds={highlightedMachineIds}
            bottleneckMachineId={bottleneckMachineId}
            violations={violations}
            onSelectMachine={onSelectMachine}
            traceIndex={traceIndex}
            simTime={simTime}
            productId={productId}
            presentation={presentation}
            editable={editable}
            onMoveMachine={onMoveMachine}
          />
        </Canvas>
        {traceIndex && (
          <div className="operator-hud-3d-wrap">
            <OperatorHud traceIndex={traceIndex} simTime={simTime} />
          </div>
        )}
        {/* §16 — EVERY canvas overlay in ONE inset layer. */}
        <div className="scene-overlays">
          <SceneLegend
            factory={factory}
            traceIndex={traceIndex}
            limitingStageShown={Boolean(limitingStageId)}
          />
          <AssetProvenanceLegend factory={factory} />
        </div>
      </div>
    </div>
  );
}
