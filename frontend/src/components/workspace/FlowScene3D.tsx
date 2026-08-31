import { Html } from "@react-three/drei";
import type { Buffer, Machine } from "../../api/types";
import type { MachineCategory } from "../../utils/assetResolution";
import {
  bufferReadout,
  operatorMarkers,
  queueMarkers,
} from "../../utils/flowReadability";
import type { BufferReadout, CongestionLevel, FlowStage } from "../../utils/flowReadability";
import type { PlaybackPoint, RouteSegment } from "../../utils/playbackGeometry";
import { segmentDirection } from "../../utils/playbackGeometry";
import type { BufferTraceSample, MachineTraceSample } from "../../api/types";

/** Phase 10 — the readability layer of the 3D digital twin. */

// Palette

/** One accent per station category. */
export const STATION_ACCENTS: Record<MachineCategory, string> = {
  ASSEMBLY_STATION: "#4f9dff",
  SCREWDRIVING_STATION: "#b98cff",
  INSPECTION_STATION: "#35c37a",
  PACKAGING_STATION: "#f0a44a",
  GENERIC_PROCESSING_MACHINE: "#8b98a6",
};

/** Condition colours, shared by queues and buffers so the same severity looks
 * the same wherever it appears. */
export const CONGESTION_COLORS: Record<CongestionLevel, string> = {
  clear: "#35c37a",
  building: "#e0a83a",
  congested: "#e0563f",
};

const FLOW_COLOR = "#4a94b8";

// Stage pad

/** A flat disc under a station carrying its stage number and name. */
export function StagePad3D({
  at,
  stage,
  accent,
  radius,
}: {
  at: PlaybackPoint;
  stage: FlowStage;
  accent: string;
  radius: number;
}) {
  return (
    <group position={[at.x, 0, at.y]} name={`stagepad3d-${stage.machineId}`}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.012, 0]} receiveShadow>
        <ringGeometry args={[radius * 0.86, radius, 48]} />
        <meshBasicMaterial color={accent} transparent opacity={0.75} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.008, 0]}>
        <circleGeometry args={[radius, 48]} />
        <meshBasicMaterial color={accent} transparent opacity={0.09} />
      </mesh>

      {/* G15 — neighbouring stations sit about one label-width apart on a
          concept-stage canvas, so consecutive names touched each other.
          Alternate stages stand their label a little further forward, which
          separates them on screen without hiding a single word: the offset
          is in the floor plane, so the label still belongs unambiguously to
          the pad it is drawn on. */}
      <Html center distanceFactor={14} position={[0, 0.05, radius + 0.55 + (stage.index % 2 === 0 ? 1.7 : 0)]}>
        <div className="stage-pad-label" data-testid={`stage-label-${stage.machineId}`}>
          <span className="stage-pad-label__num" style={{ background: accent }}>
            {stage.index}
          </span>
          <span className="stage-pad-label__name">{stage.name}</span>
          {stage.isFirst && <span className="stage-pad-label__edge">IN</span>}
          {stage.isLast && <span className="stage-pad-label__edge">OUT</span>}
        </div>
      </Html>
    </group>
  );
}

// Flow direction

/** A single arrowhead at a route link's midpoint, pointing the way material travels. */
export function FlowArrow3D({ segment }: { segment: RouteSegment }) {
  const { midX, midY, angleRad, length } = segmentDirection(segment);
  if (length <= 0) return null;

  // Three's cone points +Y; rotate it down to the floor plane and then round
  // to the segment's heading. The extra -angleRad is the X/Y -> X/Z handedness
  // flip (factory +Y maps to three +Z).
  return (
    <group position={[midX, 0.16, midY]} name="flow-arrow3d">
      <mesh rotation={[Math.PI / 2, 0, -angleRad + Math.PI / 2]}>
        <coneGeometry args={[0.26, 0.72, 16]} />
        <meshBasicMaterial color={FLOW_COLOR} transparent opacity={0.95} />
      </mesh>
    </group>
  );
}

/** The link itself — a low, wide strip on the floor reading as a lane rather than a hairline. */
export function FlowLane3D({ segment }: { segment: RouteSegment }) {
  const { midX, midY, angleRad, length } = segmentDirection(segment);
  if (length <= 0) return null;

  return (
    <mesh
      position={[midX, 0.006, midY]}
      rotation={[-Math.PI / 2, 0, -angleRad]}
      name="flow-lane3d"
    >
      <planeGeometry args={[length, 0.5]} />
      <meshBasicMaterial color={FLOW_COLOR} transparent opacity={0.16} />
    </mesh>
  );
}

// Queues

/**
 * The pile of work waiting at a station, drawn as boxes trailing back along
 * the direction material arrives from.
 *
 * The count is capped (`MAX_QUEUE_MARKERS`) — the colour band carries "how
 * bad", the markers carry "there is a queue here". Drawing 300 boxes would be
 * both slow and less readable than 8.
 */
export function QueueMarkers3D({
  at,
  machineId,
  queueLength,
  incomingAngleRad,
  congestion,
}: {
  at: PlaybackPoint;
  machineId: string;
  queueLength: number;
  incomingAngleRad: number;
  congestion: CongestionLevel;
}) {
  const markers = queueMarkers(at, queueLength, incomingAngleRad);
  if (markers.length === 0) return null;
  const color = CONGESTION_COLORS[congestion];

  return (
    <group name={`queue3d-${machineId}`}>
      {markers.map((marker) => (
        <mesh
          key={`${machineId}-q-${marker.rank}`}
          position={[marker.x, 0.16, marker.y]}
          castShadow
        >
          <boxGeometry args={[0.34, 0.26, 0.34]} />
          <meshStandardMaterial
            color={color}
            roughness={0.55}
            metalness={0.05}
            transparent
            // The tail fades so a long queue reads as "continuing beyond
            // what is drawn" rather than as an exact count of 8.
            opacity={Math.max(0.35, 1 - marker.rank * 0.09)}
          />
        </mesh>
      ))}
    </group>
  );
}

// Processing indicator

/** Colour of "a unit is being worked on right now" — the same processing
 * blue the machine outline and the 2D token use, so the language is one. */
const PROCESSING_COLOR = "#4fb3ff";

/** A single token riding on the station, shown whenever `machine_series.processing_count > 0`. */
export function ProcessingToken3D({
  at,
  machineId,
  processingCount,
  height,
}: {
  at: PlaybackPoint;
  machineId: string;
  processingCount: number;
  /** Machine box height, so the token sits ON the station rather than
   * inside its geometry where it would be hidden. */
  height: number;
}) {
  if (processingCount <= 0) return null;
  const y = height + 0.22;

  return (
    <group name={`processing3d-${machineId}`}>
      <mesh position={[at.x, y, at.y]} castShadow>
        <boxGeometry args={[0.3, 0.22, 0.3]} />
        <meshStandardMaterial
          color={PROCESSING_COLOR}
          roughness={0.4}
          metalness={0.1}
          emissive={PROCESSING_COLOR}
          emissiveIntensity={0.35}
        />
      </mesh>

      {processingCount > 1 && (
        <Html center distanceFactor={14} position={[at.x, y + 0.4, at.y]}>
          <div className="processing-token-label" data-testid={`processing-count-${machineId}`}>
            ×{processingCount}
          </div>
        </Html>
      )}
    </group>
  );
}

// Buffers

const BUFFER_GAUGE_HEIGHT = 1.6;

/** A vertical fill gauge at a buffer's real recorded position. */
export function BufferGauge3D({
  at,
  buffer,
  readout,
}: {
  at: PlaybackPoint;
  buffer: Buffer;
  readout: BufferReadout;
}) {
  const filled = Math.max(0.02, BUFFER_GAUGE_HEIGHT * readout.ratio);
  const color = CONGESTION_COLORS[readout.congestion];

  return (
    <group position={[at.x, 0, at.y]} name={`buffer3d-${buffer.id}`}>
      {/* Capacity outline */}
      <mesh position={[0, BUFFER_GAUGE_HEIGHT / 2, 0]}>
        <boxGeometry args={[0.46, BUFFER_GAUGE_HEIGHT, 0.46]} />
        <meshBasicMaterial color="#38434f" wireframe transparent opacity={0.55} />
      </mesh>

      {/* Recorded level */}
      <mesh position={[0, filled / 2, 0]} castShadow>
        <boxGeometry args={[0.4, filled, 0.4]} />
        <meshStandardMaterial color={color} roughness={0.5} metalness={0.1} emissive={color} emissiveIntensity={0.18} />
      </mesh>

      <Html center distanceFactor={14} position={[0, BUFFER_GAUGE_HEIGHT + 0.45, 0]}>
        <div
          className={`buffer-gauge-label buffer-gauge-label--${readout.congestion}`}
          data-testid={`buffer-label-${buffer.id}`}
        >
          <span className="buffer-gauge-label__level">
            {readout.level}/{readout.capacity}
          </span>
          {readout.blockedUpstream && (
            <span className="buffer-gauge-label__flag" data-testid={`buffer-blocked-${buffer.id}`}>
              BLOCKING
            </span>
          )}
        </div>
      </Html>
    </group>
  );
}

// Operators

/** `Machine.operators_required` markers, beside the station and off the flow lane. */
export function OperatorMarkers3D({
  at,
  machineId,
  operatorsRequired,
  flowAngleRad,
}: {
  at: PlaybackPoint;
  machineId: string;
  operatorsRequired: number;
  flowAngleRad: number;
}) {
  const markers = operatorMarkers(at, operatorsRequired, flowAngleRad);
  if (markers.length === 0) return null;

  return (
    <group name={`operators3d-${machineId}`}>
      {markers.map((marker) => (
        <group key={`${machineId}-op-${marker.index}`} position={[marker.x, 0, marker.y]}>
          <mesh position={[0, 0.34, 0]} castShadow>
            <cylinderGeometry args={[0.12, 0.16, 0.68, 12]} />
            <meshStandardMaterial color="#cbd6e2" roughness={0.7} />
          </mesh>
          <mesh position={[0, 0.79, 0]} castShadow>
            <sphereGeometry args={[0.14, 14, 12]} />
            <meshStandardMaterial color="#e6ebf1" roughness={0.6} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// Composed per-station overlay

export interface StationOverlayProps {
  machine: Machine;
  at: PlaybackPoint;
  stage: FlowStage | null;
  accent: string;
  /** Direction material ARRIVES from, for queue/operator placement. */
  incomingAngleRad: number;
  sample: MachineTraceSample | null;
  queueCongestionLevel: CongestionLevel;
  /** False when this machine's waiting units are already drawn by its
   * inbound buffer gauge — queue_length and that buffer's level are the
   * SAME physical units (see utils/machineFlowState.queueIsOwnedByInboundBuffer),
   * so drawing both would count them twice. Machines with no wired inbound
   * buffer keep their markers: nothing else represents those units. */
  showQueue: boolean;
  showOperators: boolean;
  padRadius: number;
  /** Machine height, so the processing token sits on top of the station. */
  machineHeight: number;
}

/** Everything drawn around one station. */
export function StationOverlay3D({
  machine,
  at,
  stage,
  accent,
  incomingAngleRad,
  sample,
  queueCongestionLevel,
  showQueue,
  showOperators,
  padRadius,
  machineHeight,
}: StationOverlayProps) {
  return (
    <group name={`station-overlay-${machine.id}`}>
      {stage && <StagePad3D at={at} stage={stage} accent={accent} radius={padRadius} />}

      {sample && (
        <ProcessingToken3D
          at={at}
          machineId={machine.id}
          processingCount={sample.processing_count}
          height={machineHeight}
        />
      )}

      {showQueue && sample && sample.queue_length > 0 && (
        <QueueMarkers3D
          at={at}
          machineId={machine.id}
          queueLength={sample.queue_length}
          incomingAngleRad={incomingAngleRad}
          congestion={queueCongestionLevel}
        />
      )}

      {showOperators && (
        <OperatorMarkers3D
          at={at}
          machineId={machine.id}
          operatorsRequired={machine.operators_required}
          flowAngleRad={incomingAngleRad}
        />
      )}
    </group>
  );
}

/** Buffer gauges for every buffer that has a recorded sample at this instant. */
export function BufferGauges3D({
  buffers,
  positions,
  samples,
}: {
  buffers: Buffer[];
  positions: Map<string, PlaybackPoint>;
  samples: Map<string, BufferTraceSample>;
}) {
  return (
    <>
      {buffers.map((buffer) => {
        const at = positions.get(buffer.id);
        const sample = samples.get(buffer.id);
        if (!at || !sample) return null;
        return (
          <BufferGauge3D key={buffer.id} at={at} buffer={buffer} readout={bufferReadout(sample)} />
        );
      })}
    </>
  );
}
