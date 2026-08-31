import { describe, expect, it } from "vitest";
import { limitingStageMove, planChanges } from "./planDelta";
import {
  makeStrategyActions,
  makeStrategyMetrics,
  sampleFactory,
  sampleSessionAccepted,
} from "../test/fixtures";
import type { Factory, PlanningSessionState } from "../api/types";

/** §3/§4 — what a plan changes, and where the constraint went. */

function factoryWith(overrides: Partial<Factory>): Factory {
  return { ...sampleFactory, ...overrides };
}

function sessionBetween(before: Factory, after: Factory): PlanningSessionState {
  return { ...sampleSessionAccepted, baseline_factory: before, current_factory: after };
}

describe("planChanges — from the verified session", () => {
  it("names a cycle-time change with both values, not a count", () => {
    const after = factoryWith({
      machines: sampleFactory.machines.map((m) =>
        m.id === "m-a" ? { ...m, cycle_time: 12.5 } : m,
      ),
    });
    const result = planChanges(sessionBetween(sampleFactory, after));

    expect(result.source).toBe("SESSION");
    expect(result.complete).toBe(true);
    expect(result.changes).toEqual([
      {
        key: "cycle-m-a",
        subject: "Machine A",
        property: "cycle time",
        before: "30 s",
        after: "12.5 s",
      },
    ]);
  });

  it("keeps sub-second precision — 78.5 s must not round to 79 s", () => {
    const before = factoryWith({
      machines: sampleFactory.machines.map((m) => (m.id === "m-a" ? { ...m, cycle_time: 78.5 } : m)),
    });
    const after = factoryWith({
      machines: sampleFactory.machines.map((m) => (m.id === "m-a" ? { ...m, cycle_time: 30 } : m)),
    });
    const [change] = planChanges(sessionBetween(before, after)).changes;
    expect(change.before).toBe("78.5 s");
    expect(change.after).toBe("30 s");
  });

  it("uses the station's own name, never the identifier", () => {
    const after = factoryWith({
      machines: sampleFactory.machines.map((m) => (m.id === "m-b" ? { ...m, capacity: 2 } : m)),
    });
    const [change] = planChanges(sessionBetween(sampleFactory, after)).changes;
    // "Machine B", not "M B" or "m-b".
    expect(change.subject).toBe("Machine B");
    expect(change.before).toBe("1");
    expect(change.after).toBe("2");
  });

  it("reports the operating model as absolutes, not as a delta", () => {
    const after = factoryWith({ shifts_per_day: 3, operators_available: 8 });
    const result = planChanges(sessionBetween(sampleFactory, after));

    expect(result.changes).toContainEqual({
      key: "shifts",
      subject: "Operating model",
      property: "shifts per day",
      before: "1 shift",
      after: "3 shifts",
    });
    expect(result.changes).toContainEqual({
      key: "operators",
      subject: "Workforce",
      property: "operators available",
      before: "5 operators",
      after: "8 operators",
    });
  });

  it("reports a station the plan removed — silence about it would mislead most", () => {
    const after = factoryWith({ machines: sampleFactory.machines.filter((m) => m.id !== "m-b") });
    const result = planChanges(sessionBetween(sampleFactory, after));
    expect(result.changes).toContainEqual({
      key: "remove-m-b",
      subject: "Machine B",
      property: "station",
      before: "in the concept",
      after: "removed",
    });
  });

  it("reports NOTHING for a field that did not move", () => {
    // Identical factories: a plan can never be shown committing to a change
    // the simulation did not run.
    expect(planChanges(sessionBetween(sampleFactory, sampleFactory)).changes).toEqual([]);
  });
});

describe("planChanges — the action-summary fallback", () => {
  // A reopened project does not restore the per-strategy sessions, and the
  // affordance must not silently disappear with them.
  it("derives absolutes from the baseline plus the verified deltas", () => {
    const result = planChanges(
      null,
      makeStrategyActions({ added_shift_count: 2, operator_delta: 3 }),
      sampleFactory,
    );

    expect(result.source).toBe("ACTION_SUMMARY");
    expect(result.complete).toBe(true);
    expect(result.changes).toContainEqual({
      key: "shifts",
      subject: "Operating model",
      property: "shifts per day",
      before: "1 shift",
      after: "3 shifts",
    });
    expect(result.changes).toContainEqual({
      key: "operators",
      subject: "Workforce",
      property: "operators available",
      before: "5 operators",
      after: "8 operators",
    });
  });

  it("NAMES the levers it cannot value rather than dropping them", () => {
    // A plan whose whole content is a cycle-time improvement would otherwise
    const result = planChanges(
      null,
      makeStrategyActions({ action_count: 3, action_types: ["CHANGE_MACHINE_CYCLE_TIME"] }),
      sampleFactory,
    );

    expect(result.complete).toBe(false);
    expect(result.unvalued).toEqual(["station cycle times"]);
  });

  it("splits the backend's own buffer before/after string", () => {
    const result = planChanges(
      null,
      makeStrategyActions({ buffer_changes: ["buf-1: 50 -> 100"] }),
      sampleFactory,
    );
    const buffer = result.changes.find((c) => c.key === "buffer-buf-1");
    expect(buffer?.before).toBe("50 units");
    expect(buffer?.after).toBe("100 units");
  });

  it("returns nothing at all when neither source is in hand", () => {
    const result = planChanges(null, null, null);
    expect(result.changes).toEqual([]);
    expect(result.source).toBe("NONE");
  });
});

describe("limitingStageMove", () => {
  it("reports the move, with both stations named", () => {
    const move = limitingStageMove(
      makeStrategyMetrics({ bottleneck_machine_id: "m-a" }),
      makeStrategyMetrics({ bottleneck_machine_id: "m-b" }),
      sampleFactory,
    );
    expect(move).toEqual({ fromId: "m-a", toId: "m-b", from: "Machine A", to: "Machine B" });
  });

  it("reports NOTHING when the constraint stayed where it was", () => {
    // "The limiting stage did not move" is the default, not an insight, and
    // rendering it would be noise on every plan that does not move it.
    expect(
      limitingStageMove(
        makeStrategyMetrics({ bottleneck_machine_id: "m-a" }),
        makeStrategyMetrics({ bottleneck_machine_id: "m-a" }),
        sampleFactory,
      ),
    ).toBeNull();
  });

  it("degrades to the identifier-derived name when no factory is loaded", () => {
    const move = limitingStageMove(
      makeStrategyMetrics({ bottleneck_machine_id: "m-screwdriving" }),
      makeStrategyMetrics({ bottleneck_machine_id: "m-inspection" }),
      null,
    );
    expect(move?.from).toBe("Screwdriving");
    expect(move?.to).toBe("Inspection");
  });
});
