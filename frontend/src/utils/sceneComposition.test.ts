import { describe, expect, it } from "vitest";
import {
  CAMERA_TARGET_HEIGHT_M,
  MAX_FIT_ASPECT,
  cameraFramingFor,
  contentBoundingBox,
} from "./sceneComposition";
import { factoryBoundingBox } from "./geometry3d";
import type { Factory, FactoryLayout, Machine } from "../api/types";

/** Phase 10 — the camera must frame the LINE, not the building. */

function machine(id: string, x: number, width = 3, length = 2): Machine {
  return {
    id, name: id, process_type: id, cycle_time: 10, setup_time: 0, capacity: 1,
    operators_required: 2, purchase_cost: 0, position_x: x, position_y: 5,
    width, length, parallel_of_machine_id: null, asset: null,
    lifecycle_status: "EXISTING", physical_envelope: null,
  } as Machine;
}

const FLAGSHIP_MACHINES = [
  machine("m-assembly", 5, 3, 2),
  machine("m-screwdriving", 12, 2.5, 2),
  machine("m-inspection", 19, 2, 2),
  machine("m-packaging", 26, 2.5, 2),
];

const flagshipFactory = {
  name: "Electronics Assembly Line",
  width: 50, length: 20,
  machines: FLAGSHIP_MACHINES,
  buffers: [
    { id: "buf-1", name: "b1", capacity: 50, upstream_machine_id: "m-assembly", downstream_machine_id: "m-screwdriving", position_x: 8.5, position_y: 5 },
    { id: "buf-2", name: "b2", capacity: 50, upstream_machine_id: "m-screwdriving", downstream_machine_id: "m-inspection", position_x: 15.5, position_y: 5 },
  ],
  products: [],
} as unknown as Factory;

const flagshipLayout = {
  factory_width: 50,
  factory_length: 20,
  placements: FLAGSHIP_MACHINES.map((m) => ({ machine_id: m.id, x: m.position_x, y: 5, rotation_deg: 0 })),
  zones: [],
} as unknown as FactoryLayout;

describe("contentBoundingBox — frames the content, not the floor", () => {
  it("is dramatically tighter than the floor bounding box", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    const floor = factoryBoundingBox(flagshipLayout);

    expect(floor.maxX - floor.minX).toBe(50);
    // The line spans ~23.75 m of a 50 m floor. Framed content must be well
    // under the floor width or the camera change achieved nothing.
    expect(content.width).toBeLessThan(35);
    expect(content.depth).toBeLessThan(floor.maxY - floor.minY);
  });

  it("includes the outer machines' full footprints, not just their centres", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    // Assembly is 3 m wide centred at x=5 -> its left edge is 3.5.
    expect(content.minX).toBeLessThanOrEqual(3.5);
    // Packaging is 2.5 m wide centred at x=26 -> its right edge is 27.25.
    expect(content.maxX).toBeGreaterThanOrEqual(27.25);
  });

  it("includes buffer positions", () => {
    const shifted = {
      ...flagshipFactory,
      buffers: [{ ...flagshipFactory.buffers[0], position_x: 40, position_y: 15 }],
    } as Factory;
    const content = contentBoundingBox(shifted, flagshipLayout);
    expect(content.maxX).toBeGreaterThanOrEqual(40);
    expect(content.maxY).toBeGreaterThanOrEqual(15);
  });

  it("centres on the content, not on the middle of the building", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    // Floor centre is x=25; the line's centre is near x=15.4.
    expect(content.centerX).toBeLessThan(20);
    expect(content.centerY).toBeCloseTo(5, 0);
  });

  it("reports hasContent and falls back to the floor when nothing is placed", () => {
    expect(contentBoundingBox(flagshipFactory, flagshipLayout).hasContent).toBe(true);

    const empty = contentBoundingBox(
      { ...flagshipFactory, buffers: [] } as Factory,
      { ...flagshipLayout, placements: [] } as FactoryLayout,
    );
    expect(empty.hasContent).toBe(false);
    expect(empty.width).toBe(50);
    expect(empty.depth).toBe(20);
  });

  it("never returns a zero or negative span for a single tiny machine", () => {
    const tiny = contentBoundingBox(
      { ...flagshipFactory, machines: [machine("m-1", 10, 0.5, 0.5)], buffers: [] } as Factory,
      { ...flagshipLayout, placements: [{ machine_id: "m-1", x: 10, y: 5, rotation_deg: 0 }] } as unknown as FactoryLayout,
    );
    expect(tiny.width).toBeGreaterThan(0);
    expect(tiny.depth).toBeGreaterThan(0);
  });
});

describe("cameraFramingFor — a readable presentation angle", () => {
  it("looks at the centre of the framed content", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    const framing = cameraFramingFor(content);

    expect(framing.target[0]).toBeCloseTo(content.centerX, 5);
    expect(framing.target[2]).toBeCloseTo(content.centerY, 5);
    // Aimed at machine mid-height, not the floor — a floor-aimed camera
    // wastes the bottom of the frame on empty near-floor.
    expect(framing.target[1]).toBeCloseTo(CAMERA_TARGET_HEIGHT_M, 5);
    expect(framing.target[1]).toBeGreaterThan(0);
  });

  it("stands off the LONG axis so a long thin line runs across the frame", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    const framing = cameraFramingFor(content);
    const [camX, , camZ] = framing.position;

    // The line runs along X, so the camera must be displaced in Z (to the
    // side) rather than parked off the end of the line in X.
    expect(Math.abs(camZ - content.centerY)).toBeGreaterThan(Math.abs(camX - content.centerX));
    expect(camZ).toBeGreaterThan(content.maxY);
  });

  it("stands SQUARE-ON to the line, so no station is favoured by distance", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    const [camX, camY, camZ] = cameraFramingFor(content).position;

    // Square-on in the along-line axis...
    expect(camX).toBeCloseTo(content.centerX, 5);

    // ...so the first and last station are the same distance away. An
    // oblique camera made the far end shrink into perspective and cost the
    // frame nearly half its usable width.
    const distTo = (x: number) => Math.hypot(camX - x, camY, camZ - content.centerY);
    expect(distTo(content.minX)).toBeCloseTo(distTo(content.maxX), 5);
  });

  it("flips the stand-off axis for a line that runs the other way", () => {
    const deep = {
      ...contentBoundingBox(flagshipFactory, flagshipLayout),
      width: 6, depth: 30, minX: 0, maxX: 6, minY: 0, maxY: 30, centerX: 3, centerY: 15,
    };
    const [camX, , camZ] = cameraFramingFor(deep).position;
    expect(Math.abs(camX - deep.centerX)).toBeGreaterThan(Math.abs(camZ - deep.centerY));
  });

  it("is elevated but not top-down — silhouettes must stay readable", () => {
    const content = contentBoundingBox(flagshipFactory, flagshipLayout);
    const framing = cameraFramingFor(content);
    const height = framing.position[1];
    const span = Math.max(content.width, content.depth);

    expect(height).toBeGreaterThan(0);
    // A camera at or above the span reads as a floor plan, not a scene.
    expect(height).toBeLessThan(span);
  });

  it("scales its distance with the content, so any factory size fills the frame", () => {
    const small = cameraFramingFor({ ...contentBoundingBox(flagshipFactory, flagshipLayout), width: 10, depth: 6 });
    const large = cameraFramingFor({ ...contentBoundingBox(flagshipFactory, flagshipLayout), width: 200, depth: 60 });

    expect(large.position[1]).toBeGreaterThan(small.position[1]);
    expect(large.maxDistance).toBeGreaterThan(small.maxDistance);
    expect(small.minDistance).toBeGreaterThanOrEqual(2);
  });

  it("keeps zoom limits ordered", () => {
    const framing = cameraFramingFor(contentBoundingBox(flagshipFactory, flagshipLayout));
    expect(framing.minDistance).toBeLessThan(framing.maxDistance);
  });
});

/** G15 — ONE home view, and a letterbox must not wreck it. */
describe("the home view is one view", () => {
  const content = () => contentBoundingBox(flagshipFactory, flagshipLayout);

  it("gives identical numbers for identical inputs, however it is reached", () => {
    // with the same bounds and the same aspect. If it were not a pure
    // function of them, "converge to the home view" would be unenforceable.
    const a = cameraFramingFor(content(), 2.1);
    const b = cameraFramingFor(content(), 2.1);
    expect(a).toEqual(b);
  });

  it("stops fitting to the frame once it is a letterbox", () => {
    // Past the clamp the camera stands where a 2.4:1 frame would put it and
    // lets the extra width become margin. Fitting a 4.4:1 frame instead
    // means standing about a third closer to a line three times longer than
    // the distance — which is what compressed the stations together.
    const wide = cameraFramingFor(content(), 4.4);
    const clamped = cameraFramingFor(content(), MAX_FIT_ASPECT);

    expect(wide.position).toEqual(clamped.position);
    expect(wide.target).toEqual(clamped.target);
  });

  it("still fits narrower frames to their own shape", () => {
    // The clamp is a ceiling, not a fixed frame: a tall canvas must still
    // move the camera back far enough to get the line in.
    const tall = cameraFramingFor(content(), 1.2);
    const wide = cameraFramingFor(content(), 2.0);

    expect(tall.position[2]).toBeGreaterThan(wide.position[2]);
  });

  it("frames the content large enough to read, not merely to fit", () => {
    // The occupancy the composition is judged on: the line across a normal
    // frame. Solved from the same frustum arithmetic the camera uses, so
    // this fails if the margin is ever widened back to where the stations
    // became small and their names crowded.
    const bounds = content();
    const framing = cameraFramingFor(bounds, 2.4);
    const distance = Math.hypot(
      framing.position[2] - framing.target[2],
      framing.position[1] - framing.target[1],
    );
    const halfFovH = Math.atan(Math.tan((42 * Math.PI) / 360) * 2.4);
    const visibleWidth = 2 * distance * Math.tan(halfFovH);
    const stationSpan = bounds.width / (1 + 2 * 0.1); // the bounds without their margin

    const occupancy = stationSpan / visibleWidth;
    expect(occupancy).toBeGreaterThan(0.55);
    expect(occupancy).toBeLessThan(0.75);
  });

  it("keeps the outermost station clear of the frame edge", () => {
    // Occupancy is bought from the margin, and the margin is what stops a
    // station touching the edge. Both halves of that trade are asserted.
    const bounds = content();
    const rawSpan = bounds.width / (1 + 2 * 0.1);
    expect(bounds.width - rawSpan).toBeGreaterThan(1.5);
  });
});
