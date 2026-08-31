import { describe, expect, it } from "vitest";
import {
  MAX_QUEUE_MARKERS,
  bufferReadout,
  congestionFromRatio,
  flowStages,
  machineReadout,
  operatorMarkers,
  queueCongestion,
  queueMarkers,
} from "./flowReadability";
import type { BufferTraceSample, MachineTraceSample, Product } from "../api/types";

/** Phase 10 — everything a first-time observer has to be able to SEE. */

const product: Product = {
  id: "p-electronics-widget",
  name: "Widget",
  demand_per_day: 1900,
  route: [
    { name: "Assembly", machine_id: "m-assembly", cycle_time: 35 },
    { name: "Screwdriving", machine_id: "m-screwdriving", cycle_time: 52 },
    { name: "Inspection", machine_id: "m-inspection", cycle_time: 30 },
    { name: "Packaging", machine_id: "m-packaging", cycle_time: 25 },
  ],
};

function machineSample(overrides: Partial<MachineTraceSample> = {}): MachineTraceSample {
  return {
    timestamp: 0, machine_id: "m-a", queue_length: 0,
    processing_count: 0, blocked: false, utilization_so_far: 0,
    ...overrides,
  };
}

function bufferSample(overrides: Partial<BufferTraceSample> = {}): BufferTraceSample {
  return {
    timestamp: 0, buffer_id: "buf-1", level: 0, capacity: 50, blocked_upstream: false,
    ...overrides,
  };
}

describe("flowStages — the sequence reads as a numbered sequence", () => {
  it("numbers the flagship route 1..4 in route order", () => {
    const stages = flowStages(product);
    expect(stages.map((s) => `${s.index} ${s.name}`)).toEqual([
      "1 Assembly", "2 Screwdriving", "3 Inspection", "4 Packaging",
    ]);
  });

  it("marks the first and last stage so entry and exit are identifiable", () => {
    const stages = flowStages(product);
    expect(stages[0].isFirst).toBe(true);
    expect(stages[0].isLast).toBe(false);
    expect(stages[3].isLast).toBe(true);
  });

  it("takes order from the route, never from position", () => {
    const reversed: Product = { ...product, route: [...product.route].reverse() };
    expect(flowStages(reversed).map((s) => s.machineId)).toEqual([
      "m-packaging", "m-inspection", "m-screwdriving", "m-assembly",
    ]);
  });

  it("is empty, not thrown, for a missing product", () => {
    expect(flowStages(null)).toEqual([]);
    expect(flowStages(undefined)).toEqual([]);
  });
});

describe("congestion bands", () => {
  it("bands a ratio into clear / building / congested", () => {
    expect(congestionFromRatio(0)).toBe("clear");
    expect(congestionFromRatio(0.2)).toBe("clear");
    expect(congestionFromRatio(0.5)).toBe("building");
    expect(congestionFromRatio(0.9)).toBe("congested");
    expect(congestionFromRatio(1)).toBe("congested");
  });

  it("turns red well before a buffer is literally full", () => {
    // The story is "work is piling up". A gauge that only reddens at 100%
    // tells it far too late to be useful in a 3-minute demo.
    expect(congestionFromRatio(0.85)).toBe("congested");
  });
});

describe("bufferReadout — read straight off the recorded sample", () => {
  it("copies level and capacity without recomputing them", () => {
    const readout = bufferReadout(bufferSample({ level: 37, capacity: 50 }));
    expect(readout.level).toBe(37);
    expect(readout.capacity).toBe(50);
    expect(readout.ratio).toBeCloseTo(0.74, 5);
    expect(readout.congestion).toBe("building");
  });

  it("reports a full buffer as congested", () => {
    expect(bufferReadout(bufferSample({ level: 50, capacity: 50 })).congestion).toBe("congested");
  });

  it("treats work sitting on a zero-capacity link as blocked, not as 0% full", () => {
    const readout = bufferReadout(bufferSample({ level: 3, capacity: 0 }));
    expect(readout.ratio).toBe(1);
    expect(readout.congestion).toBe("congested");
  });

  it("clamps a level that exceeds capacity instead of overflowing the gauge", () => {
    expect(bufferReadout(bufferSample({ level: 80, capacity: 50 })).ratio).toBe(1);
  });

  it("passes blocked_upstream through untouched", () => {
    expect(bufferReadout(bufferSample({ blocked_upstream: true })).blockedUpstream).toBe(true);
  });
});

describe("machineReadout — starved and blocked must never be confused", () => {
  it("calls an idle machine with an EMPTY queue starved (upstream is the problem)", () => {
    const readout = machineReadout(machineSample({ processing_count: 0, queue_length: 0, blocked: false }));
    expect(readout.activity).toBe("starved");
  });

  it("calls a machine that cannot hand work on blocked (downstream is the problem)", () => {
    const readout = machineReadout(machineSample({ blocked: true, queue_length: 40 }));
    expect(readout.activity).toBe("blocked");
  });

  it("ranks blocked above processing — a blocked machine can look busy", () => {
    expect(machineReadout(machineSample({ blocked: true, processing_count: 1 })).activity).toBe("blocked");
  });

  it("calls a working machine processing", () => {
    expect(machineReadout(machineSample({ processing_count: 1 })).activity).toBe("processing");
  });

  it("bands the queue and passes utilization through", () => {
    const readout = machineReadout(machineSample({ queue_length: 11, utilization_so_far: 0.97 }));
    expect(readout.queueLength).toBe(11);
    expect(readout.queueCongestion).toBe("congested");
    expect(readout.utilization).toBe(0.97);
  });

  it("is safe on a missing sample", () => {
    expect(machineReadout(null).activity).toBe("idle");
    expect(machineReadout(undefined).queueLength).toBe(0);
  });

  it("bands queue depth consistently", () => {
    expect(queueCongestion(0)).toBe("clear");
    expect(queueCongestion(6)).toBe("building");
    expect(queueCongestion(20)).toBe("congested");
  });
});

describe("queueMarkers — a queue trails BACK from the station", () => {
  const at = { x: 12, y: 5 };

  it("places markers upstream of the machine, opposite the flow direction", () => {
    // Flow runs +X, so the queue must extend in -X.
    const markers = queueMarkers(at, 3, 0);
    expect(markers).toHaveLength(3);
    for (const marker of markers) expect(marker.x).toBeLessThan(at.x);
    expect(markers[0].x).toBeGreaterThan(markers[2].x);
  });

  it("follows the flow direction rather than a fixed axis", () => {
    // Flow running +Y must put the queue at -Y, not at -X.
    const markers = queueMarkers(at, 2, Math.PI / 2);
    for (const marker of markers) {
      expect(marker.y).toBeLessThan(at.y);
      expect(marker.x).toBeCloseTo(at.x, 5);
    }
  });

  it("draws nothing for an empty queue", () => {
    expect(queueMarkers(at, 0, 0)).toEqual([]);
    expect(queueMarkers(at, -5, 0)).toEqual([]);
  });

  it("caps a huge queue instead of emitting hundreds of markers", () => {
    expect(queueMarkers(at, 300, 0)).toHaveLength(MAX_QUEUE_MARKERS);
  });

  it("ranks markers so the renderer can fade the tail", () => {
    expect(queueMarkers(at, 4, 0).map((m) => m.rank)).toEqual([0, 1, 2, 3]);
  });

  it("spaces markers evenly", () => {
    const [a, b, c] = queueMarkers(at, 3, 0);
    expect(Math.abs(a.x - b.x)).toBeCloseTo(Math.abs(b.x - c.x), 5);
  });
});

describe("operatorMarkers — beside the station, never on the line", () => {
  const at = { x: 12, y: 5 };

  it("draws one marker per required operator", () => {
    expect(operatorMarkers(at, 2, 0)).toHaveLength(2);
    expect(operatorMarkers(at, 0, 0)).toEqual([]);
  });

  it("places them off the flow axis", () => {
    // Flow along +X: operators must be displaced in Y.
    for (const marker of operatorMarkers(at, 2, 0)) {
      expect(Math.abs(marker.y - at.y)).toBeGreaterThan(0.5);
    }
  });

  it("keeps them within a sane radius of the station", () => {
    for (const marker of operatorMarkers(at, 3, 0, 1.25)) {
      const d = Math.hypot(marker.x - at.x, marker.y - at.y);
      expect(d).toBeCloseTo(1.25, 5);
    }
  });

  it("indexes them for stable keys", () => {
    expect(operatorMarkers(at, 3, 0).map((m) => m.index)).toEqual([0, 1, 2]);
  });
});
