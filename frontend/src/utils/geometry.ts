/** Pure 2D rectangle geometry for RENDERING the factory floor (Phase 6B). */

import type { LayoutZone, Machine, MachinePlacement } from "../api/types";

export interface Point {
  x: number;
  y: number;
}

function rotate(x: number, y: number, angleRad: number): Point {
  const cos = Math.cos(angleRad);
  const sin = Math.sin(angleRad);
  return { x: x * cos - y * sin, y: x * sin + y * cos };
}

/** 4 global-space corners of a rectangle defined in a local frame
 * (possibly asymmetric about the local origin), rotated CCW by
 * `rotationDeg` about the local origin, then translated to (centerX,
 * centerY). Mirrors backend `oriented_rectangle` exactly. */
export function orientedRectangle(
  centerX: number,
  centerY: number,
  rotationDeg: number,
  minLocalX: number,
  maxLocalX: number,
  minLocalY: number,
  maxLocalY: number,
): Point[] {
  const angleRad = (rotationDeg * Math.PI) / 180;
  const localCorners: [number, number][] = [
    [minLocalX, minLocalY],
    [maxLocalX, minLocalY],
    [maxLocalX, maxLocalY],
    [minLocalX, maxLocalY],
  ];
  return localCorners.map(([lx, ly]) => {
    const r = rotate(lx, ly, angleRad);
    return { x: centerX + r.x, y: centerY + r.y };
  });
}

/** Corners of an axis-aligned rectangle with (x, y) as its LOWER-LEFT
 * corner — the LayoutZone convention. Mirrors backend `axis_aligned_rectangle`. */
export function axisAlignedRectangle(x: number, y: number, width: number, length: number): Point[] {
  return [
    { x, y },
    { x: x + width, y },
    { x: x + width, y: y + length },
    { x, y: y + length },
  ];
}

/** The machine's physical footprint corners at `placement`. */
export function machineFootprint(machine: Machine, placement: MachinePlacement): Point[] {
  const halfW = machine.width / 2;
  const halfL = machine.length / 2;
  return orientedRectangle(placement.x, placement.y, placement.rotation_deg, -halfW, halfW, -halfL, halfL);
}

/** The machine's expanded safety envelope corners at `placement` — grown
 * by each of the four DIRECTIONAL clearances independently (never
 * symmetrized), rotated rigidly with the machine. Mirrors backend
 * `get_machine_safety_envelope` exactly. 0 on every side when
 * `physical_envelope` is null. */
export function machineSafetyEnvelope(machine: Machine, placement: MachinePlacement): Point[] {
  const halfW = machine.width / 2;
  const halfL = machine.length / 2;
  const extras = machine.physical_envelope;
  const front = extras?.safety_clearance_front ?? 0;
  const back = extras?.safety_clearance_back ?? 0;
  const left = extras?.safety_clearance_left ?? 0;
  const right = extras?.safety_clearance_right ?? 0;

  return orientedRectangle(
    placement.x, placement.y, placement.rotation_deg,
    -halfW - left, halfW + right,
    -halfL - back, halfL + front,
  );
}

export function zoneRectangle(zone: LayoutZone): Point[] {
  return axisAlignedRectangle(zone.x, zone.y, zone.width, zone.length);
}

export function pointsToSvgPolygon(points: Point[]): string {
  return points.map((p) => `${p.x},${p.y}`).join(" ");
}

function boundingBox(points: Point[]): { minX: number; maxX: number; minY: number; maxY: number } {
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

/** Cheap, APPROXIMATE (axis-aligned bounding box, ignores true rotation)
 * overlap check for LIVE drag feedback only — never authoritative, never
 * used to block Apply/commit (see module docstring). The real answer
 * always comes from POST /layout/validate. */
export function previewOverlap(a: Point[], b: Point[]): boolean {
  const boxA = boundingBox(a);
  const boxB = boundingBox(b);
  return boxA.minX < boxB.maxX && boxA.maxX > boxB.minX && boxA.minY < boxB.maxY && boxA.maxY > boxB.minY;
}
