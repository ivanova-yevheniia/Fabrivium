/** Pure 3D placement/geometry helpers (Phase 6C). */

import type { FactoryLayout, Machine, MachinePlacement } from "../api/types";

export const DEFAULT_MACHINE_HEIGHT_M = 1.8;

export interface Box3Dimensions {
  width: number;
  length: number;
  height: number;
  /** False when the height came from DEFAULT_MACHINE_HEIGHT_M, not a real
   * recorded Machine.physical_envelope.height — callers that want to be
   * honest about this (e.g. a tooltip) can check it. */
  heightIsMeasured: boolean;
}

export function machineBoxDimensions(machine: Machine): Box3Dimensions {
  const measuredHeight = machine.physical_envelope?.height;
  return {
    width: machine.width,
    length: machine.length,
    height: measuredHeight ?? DEFAULT_MACHINE_HEIGHT_M,
    heightIsMeasured: measuredHeight != null,
  };
}

export interface Position3 {
  x: number;
  y: number;
  z: number;
}

export function placementToThreePosition(placement: MachinePlacement, height: number): Position3 {
  return { x: placement.x, y: height / 2, z: placement.y };
}

/** Phase 12.1 — the inverse of `placementToThreePosition`, used by 3D layout dragging. */
export function threePositionToFactoryPoint(x: number, z: number): { x: number; y: number } {
  return { x, y: z };
}

export function rotationDegToThreeY(rotationDeg: number): number {
  return (rotationDeg * Math.PI) / 180;
}

export function factoryFloorSize(layout: FactoryLayout): { width: number; length: number } {
  return { width: layout.factory_width, length: layout.factory_length };
}

/** Bounding box of every placed machine, in factory (X, Y) coordinates —
 * used to frame the default camera (Phase 6C section 2). Falls back to
 * the factory's own floor size when there are no placements at all. */
export function factoryBoundingBox(layout: FactoryLayout): { minX: number; maxX: number; minY: number; maxY: number } {
  if (layout.placements.length === 0) {
    return { minX: 0, maxX: layout.factory_width, minY: 0, maxY: layout.factory_length };
  }
  const xs = layout.placements.map((p) => p.x);
  const ys = layout.placements.map((p) => p.y);
  return { minX: Math.min(...xs, 0), maxX: Math.max(...xs, layout.factory_width), minY: Math.min(...ys, 0), maxY: Math.max(...ys, layout.factory_length) };
}
