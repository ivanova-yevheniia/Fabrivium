import { describe, expect, it } from "vitest";
import { replaySupport } from "./replaySupport";
import type { StrategyActionSummary } from "../api/types";

/** Which saved plans may be offered a play action. */

function actions(overrides: Partial<StrategyActionSummary> = {}): StrategyActionSummary {
  return {
    action_count: 1,
    added_machine_ids: [],
    added_machine_count: 0,
    added_shift_count: 0,
    hours_per_shift_delta: 0,
    operator_delta: 0,
    buffer_changes: [],
    action_types: [],
    ...overrides,
  };
}

describe("replaySupport", () => {
  it("the baseline always replays — it needs no reconstruction", () => {
    expect(replaySupport(null).replayable).toBe(true);
    expect(replaySupport(undefined).replayable).toBe(true);
  });

  it.each([
    "CHANGE_SHIFT_CONFIGURATION",
    "CHANGE_OPERATOR_CAPACITY",
    "ADD_PARALLEL_MACHINE",
  ])("offers playback for %s, whose effect the summary determines exactly", (type) => {
    expect(replaySupport(actions({ action_types: [type] })).replayable).toBe(true);
  });

  it.each([
    "CHANGE_MACHINE_CAPACITY",
    "CHANGE_MACHINE_CYCLE_TIME",
    "CHANGE_BUFFER_CAPACITY",
    "CHANGE_DEMAND",
    "REMOVE_MACHINE",
  ])("fails closed for %s, whose figure the summary does not record", (type) => {
    const support = replaySupport(actions({ action_types: [type] }));
    expect(support.replayable).toBe(false);
    expect(support.reason).toContain("cannot be replayed");
  });

  it("refuses a plan with machines the summary cannot name", () => {
    // Rebuilding would produce a smaller factory than the one verified.
    const support = replaySupport(
      actions({
        action_types: ["ADD_PARALLEL_MACHINE"],
        added_machine_ids: ["m-1"],
        added_machine_count: 2,
      }),
    );
    expect(support.replayable).toBe(false);
  });

  it("does not read a buffer size out of the sentence describing it", () => {
    // `buffer_changes` is prose for a reader: "buf-1: 50 -> 100".
    const support = replaySupport(
      actions({ action_types: ["CHANGE_SHIFT_CONFIGURATION"], buffer_changes: ["buf-1: 50 -> 100"] }),
    );
    expect(support.replayable).toBe(false);
  });

  it("refuses as soon as any one lever is unreplayable", () => {
    const support = replaySupport(
      actions({ action_types: ["CHANGE_SHIFT_CONFIGURATION", "CHANGE_MACHINE_CYCLE_TIME"] }),
    );
    expect(support.replayable).toBe(false);
  });

  it("replays a plan that pulls several replayable levers at once", () => {
    const support = replaySupport(
      actions({
        action_types: ["CHANGE_SHIFT_CONFIGURATION", "ADD_PARALLEL_MACHINE"],
        added_shift_count: 1,
        added_machine_ids: ["m-1"],
        added_machine_count: 1,
      }),
    );
    expect(support.replayable).toBe(true);
  });
});
