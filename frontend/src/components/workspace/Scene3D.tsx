import { Grid, OrbitControls, PerspectiveCamera } from "@react-three/drei";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import type {
  ConstraintViolation,
  Factory,
  FactoryLayout,
} from "../../api/types";
import { buildPlaybackPositions, buildRouteSegments, segmentDirection, unitPlaybackPosition } from "../../utils/playbackGeometry";
import { threePositionToFactoryPoint } from "../../utils/geometry3d";
import type { TraceIndex } from "../../utils/traceIndex";
import { categoryForProcessType } from "../../utils/assetResolution";
import { CAMERA_FOV_DEG, cameraFramingFor, contentBoundingBox } from "../../utils/sceneComposition";
import { flowStages, machineReadout } from "../../utils/flowReadability";
import {
  buildInboundBufferByMachine,
  queueIsOwnedByInboundBuffer,
  unitIsOwnedByMachineProcessing,
} from "../../utils/machineFlowState";
import { machineBoxDimensions } from "../../utils/geometry3d";
import { Machine3D } from "./Machine3D";
import {
  BufferGauges3D,
  FlowArrow3D,
  FlowLane3D,
  STATION_ACCENTS,
  StationOverlay3D,
} from "./FlowScene3D";

/** Phase 8C section 10 — a subtle floor-level route connector between two points. */
function RouteLine3D({ from, to }: { from: [number, number, number]; to: [number, number, number] }) {
  const positionsArray = useMemo(() => new Float32Array([...from, ...to]), [from, to]);
  return (
    <line>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positionsArray, 3]} />
      </bufferGeometry>
      <lineBasicMaterial color="#39434f" transparent opacity={0.6} />
    </line>
  );
}

function violationSets(violations: ConstraintViolation[]) {
  const errorMachines = new Set<string>();
  const warningMachines = new Set<string>();

  for (const violation of violations) {
    const targetSet =
      violation.severity === "ERROR"
        ? errorMachines
        : warningMachines;

    violation.machine_ids.forEach((id) => targetSet.add(id));
  }

  return {
    errorMachines,
    warningMachines,
  };
}

/** Phase 10 — the default camera frames the PRODUCTION LINE, not the building. */
function defaultCameraPosition(factory: Factory, layout: FactoryLayout, aspect: number) {
  return cameraFramingFor(contentBoundingBox(factory, layout), aspect);
}

export interface Scene3DProps {
  factory: Factory;
  layout: FactoryLayout;

  /** The canvas's width/height ratio, measured by the wrapper. */
  aspect?: number;

  selectedMachineId: string | null;
  highlightedMachineIds: string[];
  bottleneckMachineId: string | null;

  violations: ConstraintViolation[];

  onSelectMachine: (machineId: string) => void;

  /** Phase 8C — non-null only while a playback trace is loaded. */
  traceIndex?: TraceIndex | null;
  simTime?: number;
  /** Phase 8C section 10 — which product's route to draw connectors for. */
  productId?: string | null;

  /** Phase 10 — which audience this scene is being drawn for. */
  presentation?: "EXECUTIVE" | "ENGINEERING";

  /** Phase 12.1 — 3D layout editing. */
  editable?: boolean;
  /** Called with FACTORY-space coordinates when a drag ends. */
  onMoveMachine?: (machineId: string, x: number, y: number) => void;
}

/** Imperative handle exposed to FactoryWorkspace3D's camera buttons. */
export interface Scene3DHandle {
  resetView: () => void;
  /** Phase 8C section 30 — frame the camera on one machine's placement
   * (used by the "Focus limiting stage" / "Focus selected station" controls). */
  focusOn: (targetX: number, targetZ: number, span?: number) => void;
}

export const Scene3D = forwardRef<Scene3DHandle, Scene3DProps>(function Scene3D({
  factory,
  layout,
  aspect = 16 / 9,
  selectedMachineId,
  highlightedMachineIds,
  bottleneckMachineId,
  violations,
  onSelectMachine,
  traceIndex = null,
  simTime = 0,
  productId = null,
  presentation = "ENGINEERING",
  editable = false,
  onMoveMachine,
}: Scene3DProps, ref) {
  const {
    errorMachines,
    warningMachines,
  } = violationSets(violations);

  /** G15 — THE ONE CANONICAL HOME VIEW. */
  const home = useMemo(
    () => defaultCameraPosition(factory, layout, aspect),
    [factory, layout, aspect],
  );
  const { position, target, minDistance, maxDistance } = home;

  const cameraRef = useRef<THREE.PerspectiveCamera>(null);
  const controlsRef = useRef<OrbitControlsImpl>(null);

  /** True once the engineer has deliberately focused somewhere — "Focus
   * limiting stage", "Focus selected station". A resize must not throw that
   * away; Reset view clears it, because that is what Reset means. */
  const focused = useRef(false);

  /** Put the camera on the home view. */
  const applyHome = useCallback(() => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;

    // THE INERTIA HAS TO GO FIRST.
    //
    // The controls damp: a drag leaves momentum that keeps easing the camera
    // for about a second afterwards. Setting the home position underneath
    // that momentum lands the camera on home and then lets the leftover
    // motion carry it away again — measured at 18% of the canvas after a
    // flick, which is exactly the "Reset gives a different view" symptom.
    //
    // Turning damping off makes the next `update()` spend the residual
    // motion at once and zero it; home is then applied to a camera that is
    // no longer moving, and damping is restored for the engineer's own next
    // drag. Both steps happen inside one frame, so nothing is drawn between
    // them and there is no visible jump.
    const damped = controls.enableDamping;
    controls.enableDamping = false;
    controls.update();

    camera.position.set(...home.position);
    camera.updateProjectionMatrix();
    controls.target.set(...home.target);
    controls.update();

    controls.enableDamping = damped;
  }, [home]);

  // a layout edit, a project reopened into 3D. Skipped while the engineer is
  // deliberately focused on one station — a window resize is not a request
  // to abandon what they were looking at.
  useEffect(() => {
    if (focused.current) return;
    applyHome();
  }, [applyHome]);

  /* Phase 12.1: dragging a machine across the floor in 3D
   *
   * The gesture is owned here rather than by Machine3D, because it needs
   * two things a single machine cannot see: the shared floor plane the
   * pointer is projected onto, and the OrbitControls instance, which has
   * to be suspended for the duration or the camera orbits while the user
   * is trying to place equipment.
   *
   * `grabOffset` is the difference between where the pointer landed and
   * the machine's own centre, so the machine follows the cursor instead of
   * snapping its centre under it — the same correction the 2D canvas makes.
   *
   * Nothing is committed until pointer-up, and the commit goes out through
   * `onMoveMachine` to the draft the parent owns. No verified snapshot is
   * touched at any point. */
  const [drag, setDrag] = useState<{ machineId: string; offsetX: number; offsetZ: number } | null>(null);

  const beginDrag = (machineId: string) => {
    if (!editable || !onMoveMachine) return;
    const placement = layout.placements.find((p) => p.machine_id === machineId);
    if (!placement) return;
    // Offset deliberately starts at zero and is calibrated on the FIRST
    // pointer-move over the floor plane, not from the pointer-down point.
    //
    // Defect this fixes, found in real-browser QA: pointer-down lands on the
    // machine's own surface, which is a metre or two ABOVE the floor. Under
    // a perspective camera that hit point projects to a very different floor
    // coordinate than the cursor is over, so seeding the offset from it made
    // the station jump to the edge of the hall the instant a drag began —
    // repeatedly out of bounds, which the layout validator then (correctly)
    // rejected. Calibrating on the floor plane means both the grab point and
    // every subsequent position are measured in the same plane.
    setDrag({ machineId, offsetX: 0, offsetZ: 0 });
    if (controlsRef.current) controlsRef.current.enabled = false;
  };

  /** True until the first floor-plane sample has calibrated the grab offset. */
  const dragCalibrated = useRef(false);

  const moveDrag = (pointerX: number, pointerZ: number) => {
    if (!drag || !onMoveMachine) return;
    const placement = layout.placements.find((p) => p.machine_id === drag.machineId);
    if (!placement) return;

    if (!dragCalibrated.current) {
      // it, and move nothing this frame — so the station does not shift the
      // moment it is picked up.
      dragCalibrated.current = true;
      setDrag({ ...drag, offsetX: pointerX - placement.x, offsetZ: pointerZ - placement.y });
      return;
    }

    const point = threePositionToFactoryPoint(pointerX - drag.offsetX, pointerZ - drag.offsetZ);
    onMoveMachine(drag.machineId, point.x, point.y);
  };

  const endDrag = () => {
    if (!drag) return;
    setDrag(null);
    dragCalibrated.current = false;
    if (controlsRef.current) controlsRef.current.enabled = true;
  };

  // same function that placed the camera when the scene first appeared.
  useImperativeHandle(ref, () => ({
    resetView: () => {
      focused.current = false;
      applyHome();
    },
    // Phase 8C section 30. Same "move the existing camera/controls, never
    // remount" discipline as the home view, framed on one point instead of
    // the whole factory bounding box.
    focusOn: (targetX: number, targetZ: number, span = 8) => {
      const camera = cameraRef.current;
      const controls = controlsRef.current;
      if (!camera || !controls) return;
      focused.current = true;
      const height = span * 1.1;
      const offset = span * 0.9;
      camera.position.set(targetX + offset, height, targetZ + offset);
      camera.updateProjectionMatrix();
      controls.target.set(targetX, 0, targetZ);
      controls.update();
    },
  }), [applyHome]);

  const machineById = new Map(
    factory.machines.map((machine) => [
      machine.id,
      machine,
    ]),
  );

  const maxFloorSpan = Math.max(
    layout.factory_width,
    layout.factory_length,
  );

  // Phase 8C — everything below is read straight off the trace sample at
  // `simTime`; nothing here computes a KPI. `null` whenever no trace is
  // loaded, so every playback-only render branch is skipped identically to
  // before Phase 8C existed.
  const playbackState = useMemo(() => (traceIndex ? traceIndex.stateAt(simTime) : null), [traceIndex, simTime]);
  const playbackPositions = useMemo(() => buildPlaybackPositions(factory, layout), [factory, layout]);
  const routeSegments = useMemo(
    () => (productId ? buildRouteSegments(factory, productId, playbackPositions) : []),
    [factory, productId, playbackPositions],
  );

  // Phase 10 — flow readability. All static (route//layout-derived) except the
  // per-instant samples, which come straight off the trace exactly as before.
  const product = useMemo(
    () => (productId ? (factory.products.find((p) => p.id === productId) ?? null) : null),
    [factory.products, productId],
  );

  const stages = useMemo(() => flowStages(product), [product]);
  // Machines whose waiting units are already shown by a buffer gauge — their
  // queue markers are suppressed so the same units are not drawn twice.
  const inboundBufferByMachine = useMemo(() => buildInboundBufferByMachine(factory), [factory]);
  const stageByMachineId = useMemo(
    () => new Map(stages.map((stage) => [stage.machineId, stage])),
    [stages],
  );

  /** The heading material ARRIVES on, per machine — the direction of the last
   * route segment that ends there. Used to trail queues and place operators.
   * The first stage has no inbound segment, so it borrows the outbound one:
   * work still enters it from "behind" in the same sense. */
  const incomingAngleByMachineId = useMemo(() => {
    const angles = new Map<string, number>();
    for (const segment of routeSegments) {
      angles.set(segment.toId, segmentDirection(segment).angleRad);
    }
    for (const segment of routeSegments) {
      if (!angles.has(segment.fromId)) {
        angles.set(segment.fromId, segmentDirection(segment).angleRad);
      }
    }
    return angles;
  }, [routeSegments]);

  return (
    <>
      <PerspectiveCamera
        ref={cameraRef}
        makeDefault
        position={position}
        fov={CAMERA_FOV_DEG}
        near={0.1}
        far={Math.max(maxFloorSpan * 20, 500)}
      />

      <OrbitControls
        ref={controlsRef}
        makeDefault
        target={target}
        enableDamping
        dampingFactor={0.08}
        minDistance={minDistance}
        maxDistance={maxDistance}
        minPolarAngle={Math.PI * 0.12}
        maxPolarAngle={Math.PI * 0.47}
        screenSpacePanning
      />

      {/* Lighting */}
      <ambientLight intensity={0.75} />

      <hemisphereLight
        intensity={0.55}
        groundColor="#121820"
      />

      <directionalLight
        position={[
          layout.factory_width * 0.35,
          maxFloorSpan * 0.8,
          layout.factory_length * 0.25,
        ]}
        intensity={1.15}
        castShadow
      />

      {/* Phase 10 — ground beyond the building. */}
      <mesh
        position={[
          layout.factory_width / 2,
          -0.06,
          layout.factory_length / 2,
        ]}
        rotation={[-Math.PI / 2, 0, 0]}
      >
        <planeGeometry
          args={[
            Math.max(layout.factory_width, layout.factory_length) * 6,
            Math.max(layout.factory_width, layout.factory_length) * 6,
          ]}
        />
        <meshBasicMaterial color="#080b0f" />
      </mesh>

      {/* Phase 12.1 — the drag surface. */}
      {drag && (
        <mesh
          position={[layout.factory_width / 2, 0.01, layout.factory_length / 2]}
          rotation={[-Math.PI / 2, 0, 0]}
          onPointerMove={(event) => {
            event.stopPropagation();
            moveDrag(event.point.x, event.point.z);
          }}
          onPointerUp={(event) => {
            event.stopPropagation();
            endDrag();
          }}
          onPointerLeave={() => endDrag()}
        >
          <planeGeometry
            args={[
              Math.max(layout.factory_width, layout.factory_length) * 4,
              Math.max(layout.factory_width, layout.factory_length) * 4,
            ]}
          />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      )}

      {/* Floor */}
      <mesh
        position={[
          layout.factory_width / 2,
          -0.03,
          layout.factory_length / 2,
        ]}
        rotation={[-Math.PI / 2, 0, 0]}
        receiveShadow
      >
        <planeGeometry
          args={[
            layout.factory_width,
            layout.factory_length,
          ]}
        />

        <meshStandardMaterial
          color="#111820"
          roughness={0.95}
          metalness={0.05}
        />
      </mesh>

      {/* Engineering grid */}
      <Grid
        args={[
          layout.factory_width,
          layout.factory_length,
        ]}
        position={[
          layout.factory_width / 2,
          0.002,
          layout.factory_length / 2,
        ]}
        cellSize={1}
        cellThickness={0.45}
        cellColor="#27333e"
        sectionSize={5}
        sectionThickness={0.9}
        sectionColor="#315f78"
        fadeDistance={maxFloorSpan * 1.6}
        fadeStrength={1}
        infiniteGrid={false}
      />

      {/* Route geometry (Phase 8C section 10) — subtle floor-level
          connectors derived only from Product.route/Factory.buffers.
          Phase 10 adds the LANE and the direction ARROW on top of the same
          segments: the hairline alone showed that two stations are related
          but not which way material moves between them. */}
      {routeSegments.map((seg, i) => (
        <group key={`route3d-${i}`}>
          <RouteLine3D
            from={[seg.from.x, 0.01, seg.from.y]}
            to={[seg.to.x, 0.01, seg.to.y]}
          />
          <FlowLane3D segment={seg} />
          <FlowArrow3D segment={seg} />
        </group>
      ))}

      {/* Phase 10 — per-station readability: numbered stage pad, the queue
          waiting at the station, and the operators the station requires. */}
      {layout.placements.map((placement) => {
        const machine = machineById.get(placement.machine_id);
        if (!machine) return null;
        const at = playbackPositions.machines.get(machine.id);
        if (!at) return null;

        const sample = playbackState?.machines.get(machine.id) ?? null;
        const readout = machineReadout(sample);

        return (
          <StationOverlay3D
            key={`overlay-${machine.id}`}
            machine={machine}
            at={at}
            stage={stageByMachineId.get(machine.id) ?? null}
            accent={STATION_ACCENTS[categoryForProcessType(machine.process_type)]}
            incomingAngleRad={incomingAngleByMachineId.get(machine.id) ?? 0}
            sample={sample}
            queueCongestionLevel={readout.queueCongestion}
            showQueue={!queueIsOwnedByInboundBuffer(machine.id, inboundBufferByMachine)}
            machineHeight={machineBoxDimensions(machine).height}
            showOperators={machine.operators_required > 0}
            padRadius={Math.max(machine.width, machine.length) * 0.78}
          />
        );
      })}

      {/* Phase 10 — buffer fill gauges. */}
      {playbackState && (
        <BufferGauges3D
          buffers={factory.buffers}
          positions={playbackPositions.buffers}
          samples={playbackState.buffers}
        />
      )}

      {/* Machines */}
      {layout.placements.map((placement) => {
        const machine = machineById.get(
          placement.machine_id,
        );

        if (!machine) {
          return null;
        }

        return (
          <Machine3D
            key={placement.machine_id}
            machine={machine}
            placement={placement}
            selected={
              placement.machine_id ===
              selectedMachineId
            }
            highlighted={
              highlightedMachineIds.includes(
                placement.machine_id,
              )
            }
            isBottleneck={
              placement.machine_id ===
              bottleneckMachineId
            }
            isErrorViolation={
              errorMachines.has(
                placement.machine_id,
              )
            }
            isWarningViolation={
              warningMachines.has(
                placement.machine_id,
              )
            }
            playbackBlocked={playbackState?.machines.get(placement.machine_id)?.blocked ?? false}
            playbackProcessing={(playbackState?.machines.get(placement.machine_id)?.processing_count ?? 0) > 0}
            playbackQueueLength={playbackState?.machines.get(placement.machine_id)?.queue_length ?? 0}
            showAssetBadge={presentation === "ENGINEERING"}
            onSelect={onSelectMachine}
            onDragStart={editable && onMoveMachine ? beginDrag : undefined}
          />
        );
      })}

      {/* Phase 8C — bounded set of workpiece markers, small rounded boxes
          drifting through Assembly -> buffer -> ... -> output. Simple
          geometry on purpose (section 9): the point is to make the FLOW
          understandable, not to render every physical unit. */}
      {playbackState?.units.map((unit) => {
        // Units inside a machine are represented by that station's
        // processing token — see ProcessingToken3D / the ownership table in
        // utils/machineFlowState. Drawing both would place the same
        // physical unit twice at the same coordinates.
        if (unitIsOwnedByMachineProcessing(unit)) return null;
        const point = unitPlaybackPosition(unit, playbackPositions);
        if (!point) return null;
        const y = 0.35;
        return (
          <mesh key={`workpiece-${unit.unitId}`} position={[point.x, y, point.y]} name={`workpiece3d-${unit.unitId}`}>
            <boxGeometry args={[0.28, 0.2, 0.28]} />
            <meshStandardMaterial
              color={unit.status === "buffered" ? "#4fb3ff" : "#e6ebf1"}
              roughness={0.5}
              metalness={0.1}
            />
          </mesh>
        );
      })}
    </>
  );
});