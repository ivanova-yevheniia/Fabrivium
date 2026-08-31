import { useMemo } from "react";
import type { Factory, FactoryLayout } from "../../api/types";
import { SCALE } from "../workspace/FactoryWorkspace";
import { buildPlaybackPositions, buildRouteSegments, unitPlaybackPosition } from "../../utils/playbackGeometry";
import { TraceIndex } from "../../utils/traceIndex";
import {
  buildInboundBufferByMachine,
  queueIsOwnedByInboundBuffer,
  unitIsOwnedByMachineProcessing,
} from "../../utils/machineFlowState";
import { stationName } from "../../utils/formatting";

const MAX_VISIBLE_QUEUE_MARKS = 8;

/**
 * Phase 8C — non-interactive playback layer drawn OVER the existing 2D
 * `<FactoryWorkspace>` (same SCALE/transform, so points line up exactly).
 * Deliberately a separate absolutely-positioned SVG rather than a change to
 * FactoryWorkspace itself — the Phase 6B editor (drag/rotate/violations)
 * stays completely untouched, so playback can never regress it.
 *
 * Every number rendered here is read straight from a TraceIndex sample —
 * this component computes screen pixels from factory-space (x, y) and
 * nothing else (Phase 8C's architectural rule).
 */
export function PlaybackOverlay2D({
  factory,
  layout,
  traceIndex,
  simTime,
  productId,
}: {
  factory: Factory;
  layout: FactoryLayout;
  traceIndex: TraceIndex;
  simTime: number;
  productId?: string | null;
}) {
  const positions = useMemo(() => buildPlaybackPositions(factory, layout), [factory, layout]);
  const state = useMemo(() => traceIndex.stateAt(simTime), [traceIndex, simTime]);
  const routeSegments = useMemo(
    () => (productId ? buildRouteSegments(factory, productId, positions) : []),
    [factory, productId, positions],
  );

  const machineById = new Map(factory.machines.map((m) => [m.id, m]));
  // Which machines already have their waiting units drawn by a buffer gauge
  // — see queueIsOwnedByInboundBuffer for why drawing both double-counts.
  const inboundBufferByMachine = useMemo(() => buildInboundBufferByMachine(factory), [factory]);

  return (
    <svg
      className="playback-overlay-2d"
      width={factory.width * SCALE + 4}
      height={factory.length * SCALE + 4}
      data-testid="playback-overlay-2d"
      aria-hidden="true"
    >
      <g transform={`scale(1,-1) translate(2, ${-(factory.length * SCALE) - 2})`}>
        {/* Route geometry (section 10) — subtle floor-level connectors,
            derived only from Product.route/Factory.buffers, never spatial
            proximity. Drawn first so everything else layers on top. */}
        {routeSegments.map((seg, i) => (
          <line
            // eslint-disable-next-line react/no-array-index-key
            key={`route-${i}`}
            x1={seg.from.x * SCALE}
            y1={seg.from.y * SCALE}
            x2={seg.to.x * SCALE}
            y2={seg.to.y * SCALE}
            stroke="#39434f"
            strokeWidth={1.5}
            strokeDasharray="3,3"
          />
        ))}

        {/* Machine state rings: BLOCKED > PROCESSING, never both at once. */}
        {Array.from(state.machines.entries()).map(([machineId, sample]) => {
          const pos = positions.machines.get(machineId);
          if (!pos || !machineById.has(machineId)) return null;
          if (!sample.blocked && sample.processing_count === 0) return null;
          const color = sample.blocked ? "#e0563f" : "#4fb3ff";
          return (
            <circle
              key={`state-${machineId}`}
              cx={pos.x * SCALE}
              cy={pos.y * SCALE}
              r={SCALE * 1.6}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeDasharray={sample.blocked ? undefined : "4,3"}
              opacity={0.85}
            />
          );
        })}

        {/* Bounded queue indicators, per machine — ONLY for machines whose
            waiting units are not already drawn by an inbound buffer gauge.
            A machine fed by a wired buffer has queue_length === that
            buffer's level (the same units, described twice), so drawing
            both showed ~50 units twice in the congested baseline. */}
        {Array.from(state.machines.entries()).map(([machineId, sample]) => {
          const pos = positions.machines.get(machineId);
          if (!pos || sample.queue_length <= 0) return null;
          if (queueIsOwnedByInboundBuffer(machineId, inboundBufferByMachine)) return null;
          const marks = Math.min(sample.queue_length, MAX_VISIBLE_QUEUE_MARKS);
          const overflow = sample.queue_length - marks;
          return (
            <g key={`queue-${machineId}`} transform={`translate(${pos.x * SCALE - SCALE}, ${pos.y * SCALE - SCALE * 2.4})`}>
              {Array.from({ length: marks }).map((_, i) => (
                <rect
                  // eslint-disable-next-line react/no-array-index-key
                  key={i}
                  x={i * 5}
                  y={0}
                  width={3.5}
                  height={10}
                  fill="#e0a83a"
                  transform="scale(1,-1)"
                />
              ))}
              <text x={marks * 5 + (overflow > 0 ? 4 : 0)} y={2} fontSize={9} fill="#e0a83a" transform="scale(1,-1)">
                {overflow > 0 ? `+${overflow}` : sample.queue_length}
              </text>
            </g>
          );
        })}

        {/* Processing tokens — "this station is currently working on real production". */}
        {Array.from(state.machines.entries()).map(([machineId, sample]) => {
          const pos = positions.machines.get(machineId);
          if (!pos || sample.processing_count <= 0) return null;
          return (
            <g
              key={`processing-${machineId}`}
              transform={`translate(${pos.x * SCALE}, ${pos.y * SCALE})`}
              data-testid={`playback-processing-${machineId}`}
            >
              <rect x={-4} y={-4} width={8} height={8} rx={2} fill="#4fb3ff" stroke="#0d1117" strokeWidth={0.75} />
              {sample.processing_count > 1 && (
                <text x={7} y={4} fontSize={9} fill="#4fb3ff" transform="scale(1,-1)">
                  ×{sample.processing_count}
                </text>
              )}
            </g>
          );
        })}

        {/* Buffer fill meters. */}
        {Array.from(state.buffers.entries()).map(([bufferId, sample]) => {
          const pos = positions.buffers.get(bufferId);
          if (!pos) return null;
          const fillFrac = sample.capacity > 0 ? sample.level / sample.capacity : 0;
          const barHeight = 26;
          return (
            <g key={`buffer-${bufferId}`} transform={`translate(${pos.x * SCALE}, ${pos.y * SCALE})`} data-testid={`playback-buffer-${bufferId}`}>
              <rect x={-4} y={-barHeight / 2} width={8} height={barHeight} fill="rgba(20,26,34,0.85)" stroke="#39434f" />
              <rect
                x={-4}
                y={-barHeight / 2}
                width={8}
                height={barHeight * fillFrac}
                fill={sample.blocked_upstream ? "#e0563f" : "#35c37a"}
              />
              <text x={8} y={-barHeight / 2 - 3} fontSize={9} fill="#c9d4e0" transform="scale(1,-1)">
                {sample.level}/{sample.capacity}
                {sample.blocked_upstream ? " · BLOCKING" : ""}
              </text>
            </g>
          );
        })}

        {/* Workpieces — bounded to tracked units, small dots along the route. */}
        {state.units.map((unit) => {
          // A unit being processed is already represented by its machine's
          // processing token — drawing it here too would place the same
          // physical unit twice at the same point.
          if (unitIsOwnedByMachineProcessing(unit)) return null;
          const pos = unitPlaybackPosition(unit, positions);
          if (!pos) return null;
          const jitter = ((unit.unitId * 37) % 7) - 3; // deterministic small offset so co-located units don't fully overlap
          return (
            <circle
              key={`unit-${unit.unitId}`}
              cx={pos.x * SCALE + jitter}
              cy={pos.y * SCALE + jitter}
              r={3}
              fill={unit.status === "buffered" ? "#4fb3ff" : "#e6ebf1"}
              stroke="#0d1117"
              strokeWidth={0.5}
              data-testid={`playback-unit-${unit.unitId}`}
            />
          );
        })}
      </g>

      {/* Legend — so a first-time viewer can tell the three kinds of WIP
          apart, and knows which of them covers the whole population. */}
      <g data-testid="playback-legend">
        <circle cx={10} cy={11} r={3} fill="#e6ebf1" stroke="#0d1117" strokeWidth={0.5} />
        <text x={18} y={14} fontSize={10} fill="#8896a6">moving</text>

        <rect x={69} y={7} width={8} height={8} rx={2} fill="#4fb3ff" stroke="#0d1117" strokeWidth={0.75} />
        <text x={81} y={14} fontSize={10} fill="#8896a6">processing</text>

        <rect x={148} y={6} width={5} height={10} fill="#35c37a" />
        <text x={158} y={14} fontSize={10} fill="#8896a6">buffered / waiting</text>

        <rect x={264} y={6} width={3.5} height={10} fill="#e0a83a" />
        <text x={272} y={14} fontSize={10} fill="#8896a6">queued</text>
      </g>
      <text x={6} y={27} fontSize={9.5} fill="#6f7d8c">
        Processing, queues and buffers reflect all {traceIndex.trace.total_unit_count} units. Moving markers follow{" "}
        {state.units.length}/{traceIndex.trace.tracked_unit_count} individually tracked units.
      </text>
    </svg>
  );
}

/** Small helper kept alongside the overlay so playback-only labels name a
 * station the way every other panel does.
 *
 * `known` is the factory's machines where the caller has them. Without it
 * this degrades to the identifier-derived guess, which is the correct
 * fallback and not a second naming convention. */
export function playbackMachineLabel(
  machineId: string,
  known?: readonly { id: string; name: string }[] | null,
): string {
  return stationName(machineId, known);
}
