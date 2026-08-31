/**
 * Phase 8C — maps trace machine_id/buffer_id to the SAME factory-space
 * (x, y) coordinates the 2D/3D renderers already use. No new coordinate
 * system: machine positions come from `FactoryLayout.placements` (falling
 * back to `Machine.position_x/position_y` when no layout is loaded, same
 * as the rest of the app treats a layout-less factory), buffer positions
 * from `Buffer.position_x/position_y` directly — buffers have no
 * layout-placement type, so there is nothing else to read (see Phase 8C
 * audit point 6).
 */

import type { Factory, FactoryLayout } from "../api/types";

export interface PlaybackPoint {
  x: number;
  y: number;
}

export interface PlaybackPositions {
  machines: Map<string, PlaybackPoint>;
  buffers: Map<string, PlaybackPoint>;
}

export function buildPlaybackPositions(factory: Factory, layout: FactoryLayout | null): PlaybackPositions {
  const machines = new Map<string, PlaybackPoint>();
  const placementByMachine = new Map((layout?.placements ?? []).map((p) => [p.machine_id, p]));
  for (const machine of factory.machines) {
    const placement = placementByMachine.get(machine.id);
    machines.set(machine.id, {
      x: placement?.x ?? machine.position_x,
      y: placement?.y ?? machine.position_y,
    });
  }

  const buffers = new Map<string, PlaybackPoint>();
  for (const buffer of factory.buffers) {
    buffers.set(buffer.id, { x: buffer.position_x, y: buffer.position_y });
  }

  return { machines, buffers };
}

function lerp(a: PlaybackPoint, b: PlaybackPoint, t: number): PlaybackPoint {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

export interface UnitPositionInput {
  status: "released" | "queued" | "processing" | "finished" | "buffered" | "completed";
  atMachineId: string | null;
  atBufferId: string | null;
  progress: number;
}

/** One target (x, y) per unit — a real interpolation between two known
 * recorded points, never a fabricated one. Returns null only when neither
 * endpoint can be resolved (e.g. a machine/buffer id absent from this
 * layout, which should not happen for a consistent snapshot). */
export function unitPlaybackPosition(unit: UnitPositionInput, positions: PlaybackPositions): PlaybackPoint | null {
  if (unit.status === "buffered" && unit.atBufferId) {
    return positions.buffers.get(unit.atBufferId) ?? null;
  }
  if ((unit.status === "processing" || unit.status === "finished") && unit.atMachineId) {
    return positions.machines.get(unit.atMachineId) ?? null;
  }
  if (unit.status === "queued") {
    const target = unit.atMachineId ? positions.machines.get(unit.atMachineId) : null;
    const from = unit.atBufferId ? positions.buffers.get(unit.atBufferId) : null;
    if (target && from) return lerp(from, target, unit.progress);
    return target ?? from ?? null;
  }
  if (unit.status === "released") {
    return unit.atMachineId ? (positions.machines.get(unit.atMachineId) ?? null) : null;
  }
  return null;
}

// Route geometry (Phase 8C section 10)

export interface RouteSegment {
  from: PlaybackPoint;
  to: PlaybackPoint;
  fromId: string;
  toId: string;
}

/** Phase 9B — pure vector math over an existing segment's two real
 * endpoints: where its midpoint is and which way it points. Used to place
 * a direction arrowhead; never changes what the segment connects. */
export interface SegmentDirection {
  midX: number;
  midY: number;
  angleRad: number;
  length: number;
}

export function segmentDirection(seg: RouteSegment): SegmentDirection {
  const dx = seg.to.x - seg.from.x;
  const dy = seg.to.y - seg.from.y;
  return {
    midX: (seg.from.x + seg.to.x) / 2,
    midY: (seg.from.y + seg.to.y) / 2,
    angleRad: Math.atan2(dy, dx),
    length: Math.sqrt(dx * dx + dy * dy),
  };
}

/** One segment per route transition, derived ONLY from
 * `Product.route`/`Factory.buffers` — never from spatial proximity (section
 * 10's explicit rule). For each consecutive pair of stages: machine ->
 * buffer -> downstream machine when a WIRED buffer names that exact pair,
 * otherwise a single machine -> machine segment. */
export function buildRouteSegments(factory: Factory, productId: string, positions: PlaybackPositions): RouteSegment[] {
  const product = factory.products.find((p) => p.id === productId);
  if (!product) return [];

  const bufferByPair = new Map<string, { id: string }>();
  for (const buffer of factory.buffers) {
    if (buffer.upstream_machine_id && buffer.downstream_machine_id) {
      bufferByPair.set(`${buffer.upstream_machine_id}->${buffer.downstream_machine_id}`, buffer);
    }
  }

  const segments: RouteSegment[] = [];
  for (let i = 0; i < product.route.length - 1; i++) {
    const upstreamId = product.route[i].machine_id;
    const downstreamId = product.route[i + 1].machine_id;
    const upstreamPos = positions.machines.get(upstreamId);
    const downstreamPos = positions.machines.get(downstreamId);
    if (!upstreamPos || !downstreamPos) continue;

    const buffer = bufferByPair.get(`${upstreamId}->${downstreamId}`);
    const bufferPos = buffer ? positions.buffers.get(buffer.id) : undefined;

    if (buffer && bufferPos) {
      segments.push({ from: upstreamPos, to: bufferPos, fromId: upstreamId, toId: buffer.id });
      segments.push({ from: bufferPos, to: downstreamPos, fromId: buffer.id, toId: downstreamId });
    } else {
      segments.push({ from: upstreamPos, to: downstreamPos, fromId: upstreamId, toId: downstreamId });
    }
  }
  return segments;
}
