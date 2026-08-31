/**
 * Phase 10 — the small amount of pure maths behind "a first-time observer can
 * see where material flows and where it piles up".
 *
 * ARCHITECTURAL RULE, same as `traceIndex.ts`: nothing here computes a KPI.
 * Every number that describes what the factory is DOING is read straight off
 * a `SimulationTrace` sample that the deterministic simulator recorded
 * (`MachineTraceSample.queue_length`, `BufferTraceSample.level/capacity`,
 * `OperatorTraceSample.operators_in_use`). What this module adds is purely
 * geometric: given a count the simulator recorded, WHERE do the little boxes
 * representing it go, and which of three readability bands is it in.
 *
 * The bands exist because a raw number is not a visual. "37" means nothing at
 * a glance; a queue that is visibly amber-and-growing versus red-and-full is
 * readable in one second, which is the entire requirement.
 */

import type { BufferTraceSample, MachineTraceSample, Product } from "../api/types";
import type { PlaybackPoint } from "./playbackGeometry";

// Stage order — makes Assembly -> Screwdriving -> Inspection -> Packaging
// legible as a numbered sequence rather than four unrelated props.

export interface FlowStage {
  /** 1-based position in the product's route, as the observer counts them. */
  index: number;
  machineId: string;
  /** The route stage's own name (`RouteStage.name`), which is what the
   * process is called — never re-derived from the machine's id. */
  name: string;
  isFirst: boolean;
  isLast: boolean;
}

/** The product's route, numbered. */
export function flowStages(product: Product | null | undefined): FlowStage[] {
  const route = product?.route ?? [];
  return route.map((stage, i) => ({
    index: i + 1,
    machineId: stage.machine_id,
    name: stage.name,
    isFirst: i === 0,
    isLast: i === route.length - 1,
  }));
}

// Congestion bands

export type CongestionLevel = "clear" | "building" | "congested";

/** Fractions of capacity at which a buffer stops reading as "fine". */
const BUILDING_AT = 0.35;
const CONGESTED_AT = 0.8;

export function congestionFromRatio(ratio: number): CongestionLevel {
  if (ratio >= CONGESTED_AT) return "congested";
  if (ratio >= BUILDING_AT) return "building";
  return "clear";
}

export interface BufferReadout {
  level: number;
  capacity: number;
  /** 0..1, clamped. */
  ratio: number;
  congestion: CongestionLevel;
  blockedUpstream: boolean;
}

export function bufferReadout(sample: BufferTraceSample): BufferReadout {
  const capacity = sample.capacity;
  const level = sample.level;
  const ratio = capacity > 0 ? Math.min(1, Math.max(0, level / capacity)) : level > 0 ? 1 : 0;
  return {
    level,
    capacity,
    ratio,
    congestion: congestionFromRatio(ratio),
    blockedUpstream: sample.blocked_upstream,
  };
}

/** A machine's queue banded the same way, so a queue and a buffer that are
 * equally bad look equally bad. There is no recorded queue *capacity*, so the
 * band is taken against a readability reference rather than a physical limit
 * — hence a separate function with its own documented reference, never a
 * pretend "queue capacity". */
const QUEUE_REFERENCE_DEPTH = 12;

export function queueCongestion(queueLength: number): CongestionLevel {
  return congestionFromRatio(queueLength / QUEUE_REFERENCE_DEPTH);
}

// Queue geometry

export interface QueueMarker {
  x: number;
  y: number;
  /** 0-based position back from the machine — lets the renderer fade or
   * shrink the tail without recomputing anything. */
  rank: number;
}

/** How many markers we will ever draw for one queue. */
export const MAX_QUEUE_MARKERS = 8;

/**
 * Lays a queue out as a line of markers running BACK from the machine, along
 * the direction material arrives from.
 *
 * *angleRad* is the incoming flow direction (as produced by
 * `playbackGeometry.segmentDirection`), so the queue always trails behind the
 * station in the direction the work came from — never at an arbitrary fixed
 * offset that would sit inside the neighbouring machine on a differently
 * laid-out factory.
 */
export function queueMarkers(
  at: PlaybackPoint,
  queueLength: number,
  angleRad: number,
  spacing = 0.55,
  startOffset = 1.1,
): QueueMarker[] {
  const count = Math.min(Math.max(0, Math.floor(queueLength)), MAX_QUEUE_MARKERS);
  if (count === 0) return [];

  // Back along the incoming direction = opposite the direction of travel.
  const dx = -Math.cos(angleRad);
  const dy = -Math.sin(angleRad);

  return Array.from({ length: count }, (_, rank) => {
    const distance = startOffset + rank * spacing;
    return { x: at.x + dx * distance, y: at.y + dy * distance, rank };
  });
}

// Machine readout — one place that answers "what is this station doing?"

export type MachineActivity = "blocked" | "processing" | "starved" | "idle";

export interface MachineReadout {
  activity: MachineActivity;
  queueLength: number;
  queueCongestion: CongestionLevel;
  utilization: number;
}

/** Collapses a machine's recorded sample into the one word that explains it. */
export function machineReadout(sample: MachineTraceSample | null | undefined): MachineReadout {
  if (!sample) {
    return { activity: "idle", queueLength: 0, queueCongestion: "clear", utilization: 0 };
  }
  const queueLength = sample.queue_length;
  const activity: MachineActivity = sample.blocked
    ? "blocked"
    : sample.processing_count > 0
      ? "processing"
      : queueLength === 0
        ? "starved"
        : "idle";

  return {
    activity,
    queueLength,
    queueCongestion: queueCongestion(queueLength),
    utilization: sample.utilization_so_far,
  };
}

// Operators

export interface OperatorMarkerLayout {
  x: number;
  y: number;
  index: number;
}

/**
 * Positions for a machine's operators, arranged in a short arc on the side of
 * the station facing the viewer-ish direction (perpendicular to flow).
 *
 * `Machine.operators_required` is a real, deterministic engineering field —
 * this only decides where to draw that many markers. The simulator's
 * system-wide `OperatorTraceSample` says how many are BUSY overall; it does
 * not attribute operators to machines, and this module does not invent that
 * attribution. Callers should present these as "this station needs N", never
 * as "these N are currently working here".
 */
export function operatorMarkers(
  at: PlaybackPoint,
  operatorsRequired: number,
  angleRad: number,
  radius = 1.25,
): OperatorMarkerLayout[] {
  const count = Math.max(0, Math.floor(operatorsRequired));
  if (count === 0) return [];

  // Perpendicular to flow, so operators never sit on the conveyor line.
  const side = angleRad + Math.PI / 2;
  const spread = 0.45;
  const first = -((count - 1) / 2) * spread;

  return Array.from({ length: count }, (_, index) => {
    const a = side + first + index * spread;
    return { x: at.x + Math.cos(a) * radius, y: at.y + Math.sin(a) * radius, index };
  });
}
