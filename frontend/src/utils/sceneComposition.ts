/** Phase 10 — scene composition for the 3D digital twin. */

import type { Factory, FactoryLayout } from "../api/types";

export interface ContentBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  centerX: number;
  centerY: number;
  width: number;
  depth: number;
  /** True when real content was found. */
  hasContent: boolean;
}

/** Padding around the content, as a fraction of the content's longer side. */
const CONTENT_MARGIN_FRACTION = 0.1;

/** Never frame something smaller than this (metres). */
const MIN_FRAMED_SPAN_M = 6;

/**
 * Bounds of everything an observer is meant to look at: every placed
 * machine's actual FOOTPRINT (not just its centre point) plus every buffer
 * position, padded.
 *
 * Machine footprints matter here — a 3 m wide station centred at x=5 reaches
 * x=3.5, and framing on centres alone clips the outer stations' geometry.
 * Rotation is deliberately NOT applied: a rotated footprint's true extent is
 * at most its diagonal, and using the unrotated half-extents keeps this a
 * simple, stable, always-slightly-generous bound rather than a second
 * (differently-rounded) copy of the 2D geometry maths.
 */
export function contentBoundingBox(factory: Factory, layout: FactoryLayout | null): ContentBounds {
  const machineById = new Map(factory.machines.map((m) => [m.id, m]));
  const xs: number[] = [];
  const ys: number[] = [];

  for (const placement of layout?.placements ?? []) {
    const machine = machineById.get(placement.machine_id);
    const halfW = (machine?.width ?? 1) / 2;
    const halfL = (machine?.length ?? 1) / 2;
    xs.push(placement.x - halfW, placement.x + halfW);
    ys.push(placement.y - halfL, placement.y + halfL);
  }

  for (const buffer of factory.buffers) {
    xs.push(buffer.position_x);
    ys.push(buffer.position_y);
  }

  if (xs.length === 0 || ys.length === 0) {
    const width = layout?.factory_width ?? factory.width;
    const depth = layout?.factory_length ?? factory.length;
    return {
      minX: 0, maxX: width, minY: 0, maxY: depth,
      centerX: width / 2, centerY: depth / 2,
      width, depth, hasContent: false,
    };
  }

  const rawMinX = Math.min(...xs);
  const rawMaxX = Math.max(...xs);
  const rawMinY = Math.min(...ys);
  const rawMaxY = Math.max(...ys);

  const margin = Math.max(rawMaxX - rawMinX, rawMaxY - rawMinY, MIN_FRAMED_SPAN_M) * CONTENT_MARGIN_FRACTION;

  const minX = rawMinX - margin;
  const maxX = rawMaxX + margin;
  const minY = rawMinY - margin;
  const maxY = rawMaxY + margin;

  return {
    minX, maxX, minY, maxY,
    centerX: (minX + maxX) / 2,
    centerY: (minY + maxY) / 2,
    width: maxX - minX,
    depth: maxY - minY,
    hasContent: true,
  };
}

export interface CameraFraming {
  position: [number, number, number];
  target: [number, number, number];
  minDistance: number;
  maxDistance: number;
}

/** Roughly a machine's mid-height. */
export const CAMERA_TARGET_HEIGHT_M = 0.9;

/** The camera's vertical field of view. */
export const CAMERA_FOV_DEG = 42;

/** How high the camera sits, as an angle above the floor. */
const CAMERA_PITCH_DEG = 26;

/** Typical station height, used only to decide how much VERTICAL frame the
 * stations themselves need. Visualization-only: no geometry is drawn from
 * it, and `Machine` carries no height. */
const ASSUMED_STATION_HEIGHT_M = 2;

/** The widest frame shape the fit will solve for. */
export const MAX_FIT_ASPECT = 2.9;


//: ONE pitch, at every viewport. Raising it on wide frames was tried and
//: reverted: a deeper layout projects its depth onto the vertical axis, so a
//: steeper camera has to stand FURTHER back to fit — the opposite of what a
//: short frame needs. The pitch is what the composition is recognised by, and
//: it stays the number the Reset view has always used.

/** A presentation camera framed on *bounds*, for a viewport of *aspect*. */
export function cameraFramingFor(bounds: ContentBounds, aspect = 16 / 9): CameraFraming {
  const alongX = bounds.width >= bounds.depth;
  const longSide = Math.max(bounds.width, bounds.depth, MIN_FRAMED_SPAN_M);
  const shortSide = Math.max(Math.min(bounds.width, bounds.depth), MIN_FRAMED_SPAN_M / 2);

  const halfFovV = (CAMERA_FOV_DEG * Math.PI) / 360;
  // A viewport can be reported as zero mid-layout; a zero or negative aspect
  // would divide the camera into the floor.
  const safeAspect = Number.isFinite(aspect) && aspect > 0 ? aspect : 16 / 9;
  const fitAspect = Math.min(safeAspect, MAX_FIT_ASPECT);
  const pitch = (CAMERA_PITCH_DEG * Math.PI) / 180;
  const halfFovH = Math.atan(Math.tan(halfFovV) * fitAspect);

  // What the frame has to contain, in metres, on each screen axis.
  const neededAcross = longSide;
  const neededUp = shortSide * Math.sin(pitch) + ASSUMED_STATION_HEIGHT_M * Math.cos(pitch);

  const distance = Math.max(
    neededAcross / 2 / Math.tan(halfFovH),
    neededUp / 2 / Math.tan(halfFovV),
    // Never inside the content, however small the factory.
    MIN_FRAMED_SPAN_M,
  );

  const height = CAMERA_TARGET_HEIGHT_M + distance * Math.sin(pitch);
  const standOff = distance * Math.cos(pitch);

  const position: [number, number, number] = alongX
    ? [bounds.centerX, height, bounds.maxY + standOff]
    : [bounds.maxX + standOff, height, bounds.centerY];

  return {
    position,
    target: [bounds.centerX, CAMERA_TARGET_HEIGHT_M, bounds.centerY],
    // Zoom limits follow the fit rather than the content span, so a user can
    // always get closer than the default frame and can pull back to see the
    // building, at every viewport.
    minDistance: Math.max(distance * 0.15, 2),
    maxDistance: distance * 4,
  };
}
