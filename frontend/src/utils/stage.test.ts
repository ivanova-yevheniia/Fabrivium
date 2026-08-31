import { describe, expect, it } from "vitest";
import {
  sampleFactory,
  sampleFactoryAfterIteration1,
  sampleSessionAccepted,
  sampleSessionRejected,
  sampleSessionTwoIterations,
} from "../test/fixtures";
import { resolveStage } from "./stage";

describe("resolveStage", () => {
  it("returns null when there is no session", () => {
    expect(resolveStage(null, "baseline")).toBeNull();
  });

  it("baseline resolves to the session's own baseline_snapshot, verbatim", () => {
    const stage = resolveStage(sampleSessionAccepted, "baseline");
    expect(stage?.snapshot).toBe(sampleSessionAccepted.baseline_snapshot);
    expect(stage?.snapshot.factory).toEqual(sampleFactory);
    expect(stage?.isRejectedCandidate).toBe(false);
  });

  it("final resolves to the session's own final_snapshot, verbatim", () => {
    const stage = resolveStage(sampleSessionAccepted, "final");
    expect(stage?.snapshot).toBe(sampleSessionAccepted.final_snapshot);
  });

  it("an accepted iteration resolves to its exact state_after snapshot", () => {
    const stage = resolveStage(sampleSessionAccepted, 0);
    expect(stage?.accepted).toBe(true);
    expect(stage?.snapshot).toBe(sampleSessionAccepted.iterations[0].state_after);
    expect(stage?.snapshot.factory).toEqual(sampleFactoryAfterIteration1);
    expect(stage?.isRejectedCandidate).toBe(false);
  });

  it("a rejected iteration resolves to its rejected_candidate_snapshot, explicitly labeled", () => {
    const stage = resolveStage(sampleSessionRejected, 0);
    expect(stage?.accepted).toBe(false);
    expect(stage?.snapshot).toBe(sampleSessionRejected.iterations[0].rejected_candidate_snapshot);
    expect(stage?.isRejectedCandidate).toBe(true);
  });

  it("still reports the exact verified simulation numbers for a rejected candidate", () => {
    const stage = resolveStage(sampleSessionRejected, 0);
    expect(stage?.snapshot.simulation).toBe(sampleSessionRejected.iterations[0].rejected_candidate_snapshot!.simulation);
  });

  it("returns null for an iteration index that does not exist on the session", () => {
    expect(resolveStage(sampleSessionAccepted, 99)).toBeNull();
  });

  it("collects the machine ids touched by the selected iteration's proposal", () => {
    const stage = resolveStage(sampleSessionAccepted, 0);
    expect(stage?.actionMachineIds).toEqual(["m-a"]);
  });

  it("never fabricates a layout — null stays null through every stage", () => {
    expect(resolveStage(sampleSessionAccepted, "baseline")?.snapshot.layout).toBeNull();
    expect(resolveStage(sampleSessionAccepted, 0)?.snapshot.layout).toBeNull();
    expect(resolveStage(sampleSessionAccepted, "final")?.snapshot.layout).toBeNull();
  });

  describe("two-iteration session (1900/day-style demonstration)", () => {
    it("baseline selects the baseline factory (2 machines, no clones)", () => {
      const stage = resolveStage(sampleSessionTwoIterations, "baseline");
      expect(stage?.snapshot.factory.machines).toHaveLength(2);
      expect(stage?.snapshot.factory.machines.map((m) => m.id).sort()).toEqual(["m-a", "m-b"]);
    });

    it("iteration 1 selects iteration-1's own exact factory (3 machines)", () => {
      const stage = resolveStage(sampleSessionTwoIterations, 0);
      expect(stage?.snapshot.factory.machines.map((m) => m.id).sort()).toEqual(["m-a", "m-a-parallel-1", "m-b"]);
    });

    it("iteration 2 selects iteration-2's own exact factory (4 machines) — distinct from iteration 1", () => {
      const stage1 = resolveStage(sampleSessionTwoIterations, 0);
      const stage2 = resolveStage(sampleSessionTwoIterations, 1);
      expect(stage2?.snapshot.factory.machines.map((m) => m.id).sort()).toEqual([
        "m-a", "m-a-parallel-1", "m-b", "m-b-parallel-1",
      ]);
      expect(stage2?.snapshot.factory.machines.length).toBeGreaterThan(stage1!.snapshot.factory.machines.length);
    });

    it("final selects the final snapshot, identical to iteration 2's after-state", () => {
      const stage = resolveStage(sampleSessionTwoIterations, "final");
      expect(stage?.snapshot).toBe(sampleSessionTwoIterations.final_snapshot);
      expect(stage?.snapshot.factory.machines.map((m) => m.id).sort()).toEqual(
        resolveStage(sampleSessionTwoIterations, 1)?.snapshot.factory.machines.map((m) => m.id).sort(),
      );
    });

    it("KPI (demand gap) and geometry (machine count) always correspond for the same stage", () => {
      const baseline = resolveStage(sampleSessionTwoIterations, "baseline")!;
      const it1 = resolveStage(sampleSessionTwoIterations, 0)!;
      const it2 = resolveStage(sampleSessionTwoIterations, 1)!;
      expect(baseline.snapshot.simulation.demand_gap_units).toBe(450);
      expect(baseline.snapshot.factory.machines).toHaveLength(2);
      expect(it1.snapshot.simulation.demand_gap_units).toBe(200);
      expect(it1.snapshot.factory.machines).toHaveLength(3);
      expect(it2.snapshot.simulation.demand_gap_units).toBe(0);
      expect(it2.snapshot.factory.machines).toHaveLength(4);
    });

    it("earlier snapshots remain unchanged after resolving a later stage", () => {
      const before = resolveStage(sampleSessionTwoIterations, 0)!.snapshot.factory.machines.length;
      resolveStage(sampleSessionTwoIterations, 1); // resolve iteration 2
      const after = resolveStage(sampleSessionTwoIterations, 0)!.snapshot.factory.machines.length;
      expect(after).toBe(before);
    });
  });
});
