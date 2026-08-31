import { describe, expect, it } from "vitest";
import { CAMERA_FOV_DEG, cameraFramingFor, contentBoundingBox } from "./sceneComposition";
import { sampleFactory } from "../test/fixtures";
import type { FactoryLayout } from "../api/types";

/** §15 — the default camera fits the factory, at any shape of canvas. */

const layout: FactoryLayout = {
  factory_width: 20,
  factory_length: 10,
  placements: [
    { machine_id: "m-a", x: 3, y: 5, z: 0, rotation_deg: 0 },
    { machine_id: "m-b", x: 17, y: 5, z: 0, rotation_deg: 0 },
  ],
  zones: [],
} as unknown as FactoryLayout;

const bounds = contentBoundingBox(sampleFactory, layout);

/** Half-width of the frustum, in metres, at `distance`, for `aspect`. */
function visibleHalfWidth(distance: number, aspect: number): number {
  const halfV = (CAMERA_FOV_DEG * Math.PI) / 360;
  return distance * Math.tan(Math.atan(Math.tan(halfV) * aspect));
}

function distanceFrom(framing: ReturnType<typeof cameraFramingFor>): number {
  const [px, py, pz] = framing.position;
  const [tx, ty, tz] = framing.target;
  return Math.hypot(px - tx, py - ty, pz - tz);
}

describe("cameraFramingFor", () => {
  it("stands further back for a narrow frame than for a wide one", () => {
    // The same factory, two canvases. A tall, narrow frame has less
    // horizontal room, so the camera must retreat; a distance that ignores
    // the aspect ratio cannot express this at all.
    const wide = distanceFrom(cameraFramingFor(bounds, 3.4));
    const narrow = distanceFrom(cameraFramingFor(bounds, 1.2));
    expect(narrow).toBeGreaterThan(wide);
  });

  it("actually fits the content across, at the extreme wide canvas that broke it", () => {
    const aspect = 1098 / 321; // measured, 1920x1080 Executive twin
    const framing = cameraFramingFor(bounds, aspect);
    const visible = visibleHalfWidth(distanceFrom(framing), aspect) * 2;

    expect(visible).toBeGreaterThanOrEqual(bounds.width);
  });

  it("does not leave the factory swimming in empty frame", () => {
    // The failure mode was over-retreat, so an upper bound matters as much
    // as the lower one. The content must occupy a real share of the width.
    const aspect = 1098 / 321;
    const framing = cameraFramingFor(bounds, aspect);
    const visible = visibleHalfWidth(distanceFrom(framing), aspect) * 2;

    expect(bounds.width / visible).toBeGreaterThan(0.6);
  });

  it("fits at every viewport the demo is run on", () => {
    // 1920x1080, 1440x900 and 1366x768 give the twin canvas these ratios.
    for (const aspect of [1098 / 321, 820 / 300, 1099 / 321]) {
      const framing = cameraFramingFor(bounds, aspect);
      const visible = visibleHalfWidth(distanceFrom(framing), aspect) * 2;
      expect(visible).toBeGreaterThanOrEqual(bounds.width);
    }
  });

  it("looks at the line from its long side, so the route runs across the frame", () => {
    // A production line seen end-on disappears into perspective.
    const framing = cameraFramingFor(bounds, 16 / 9);
    expect(framing.position[0]).toBeCloseTo(bounds.centerX, 5);
    expect(framing.position[2]).toBeGreaterThan(bounds.maxY);
  });

  it("survives a viewport reported as zero mid-layout", () => {
    const framing = cameraFramingFor(bounds, 0);
    expect(Number.isFinite(distanceFrom(framing))).toBe(true);
    expect(distanceFrom(framing)).toBeGreaterThan(0);
  });

  it("lets the user get closer than the default frame and pull back past it", () => {
    const framing = cameraFramingFor(bounds, 16 / 9);
    const distance = distanceFrom(framing);
    expect(framing.minDistance).toBeLessThan(distance);
    expect(framing.maxDistance).toBeGreaterThan(distance);
  });
});
