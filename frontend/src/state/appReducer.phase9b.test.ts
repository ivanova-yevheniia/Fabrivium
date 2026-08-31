import { describe, expect, it } from "vitest";
import { appReducer } from "./appReducer";
import { initialAppState, initialPlaybackState } from "./types";
import { sampleArena, sampleFactory, sampleStrategySessions, strategyA, strategyB } from "../test/fixtures";

/**
 * Phase 9B section 13 — digital-twin synchronization across a strategy
 * switch (the historically defect-prone area).
 *
 * Everything the twin renders — KPI panel, timeline, 2D layout, 3D
 * geometry, playback trace — is derived from ONE field: `state.session`.
 * That is the design that makes synchronization possible at all, so these
 * tests pin exactly that: after SELECT_STRATEGY there is no field left
 * pointing at the previous plan. A test asserting on rendered 3D output
 * could not catch this — vitest mocks react-three-fiber — so the invariant
 * is enforced where it actually lives, in the reducer.
 *
 * The fixture's Plan A / Plan B stand in for the demo's Plan D / Plan E:
 * one adds equipment, the other reaches the target with no new machines.
 */

const arenaState = {
  ...initialAppState,
  factory: sampleFactory,
  arena: sampleArena,
  strategySessions: sampleStrategySessions,
  selectedStrategyId: strategyB.strategy_id,
  session: sampleStrategySessions[strategyB.strategy_id],
};

const select = (state: typeof arenaState, strategyId: string) =>
  appReducer(state, { type: "SELECT_STRATEGY", strategyId });

describe("Phase 9B 13 — switching strategy moves the WHOLE twin together", () => {
  it("adopts the exact verified session of the newly selected strategy", () => {
    const after = select(arenaState, strategyA.strategy_id);

    expect(after.selectedStrategyId).toBe(strategyA.strategy_id);
    // Identity, not equality: the twin shows the backend's own snapshot,
    // never a locally reconstructed one.
    expect(after.session).toBe(sampleStrategySessions[strategyA.strategy_id]);
    expect(after.session).not.toBe(arenaState.session);
  });

  it("B → A → B returns to B's own session, with nothing carried over from A", () => {
    const toA = select(arenaState, strategyA.strategy_id);
    const backToB = select(toA as typeof arenaState, strategyB.strategy_id);

    expect(backToB.selectedStrategyId).toBe(strategyB.strategy_id);
    expect(backToB.session).toBe(sampleStrategySessions[strategyB.strategy_id]);
    expect(backToB.session).not.toBe(toA.session);
  });

  it("resets playback on every switch — a trace belongs to ONE plan", () => {
    const playing = {
      ...arenaState,
      playback: { ...initialPlaybackState, active: true, playing: true, simTime: 4200, stageKey: "final" as const },
    };
    const after = select(playing, strategyA.strategy_id);

    expect(after.playback).toEqual(initialPlaybackState);
    expect(after.playback.trace).toBeNull();
    expect(after.playback.simTime).toBe(0);
  });

  it("opens on the FINAL stage, so KPI/timeline/2D/3D all read the same snapshot", () => {
    const midTimeline = { ...arenaState, selectedIteration: 0 as const };
    const after = select(midTimeline, strategyA.strategy_id);

    expect(after.selectedIteration).toBe("final");
    expect(after.pendingIterationSelection).toBeNull();
  });

  it("drops the previous plan's explanation rather than re-labelling it", () => {
    const withExplanation = {
      ...arenaState,
      explanation: { summary: "belongs to Plan B" } as unknown as typeof arenaState.explanation,
    };
    const after = select(withExplanation, strategyA.strategy_id);

    expect(after.explanation).toBeNull();
  });

  it("leaves no half-finished layout edit attached to the new plan", () => {
    const editing = {
      ...arenaState,
      editMode: "EDIT_LAYOUT" as const,
      isDirty: true,
      selectedMachineId: "m-a",
    };
    const after = select(editing, strategyA.strategy_id);

    expect(after.editMode).toBe("VIEW");
    expect(after.isDirty).toBe(false);
    expect(after.draftLayout).toBeNull();
    expect(after.layoutValidation).toBeNull();
    expect(after.selectedMachineId).toBeNull();
  });

  it("clears a branch selection, so branch and strategy can never both claim the twin", () => {
    const after = select({ ...arenaState, selectedBranchId: "branch-0-aaa" }, strategyA.strategy_id);
    expect(after.selectedBranchId).toBeNull();
  });

  it("refuses a strategy whose verified session is missing, instead of showing stale numbers", () => {
    const noSessions = { ...arenaState, strategySessions: {} };
    // Returning the SAME object proves nothing moved: the previous plan's
    // twin stays intact rather than being re-badged under a new name.
    expect(select(noSessions, strategyA.strategy_id)).toBe(noSessions);
  });
});

describe("Phase 9B 13 — the arena itself survives a switch", () => {
  it("keeps every option and the backend's recommendation after switching away from it", () => {
    const after = select(arenaState, strategyA.strategy_id);

    expect(after.arena).toBe(sampleArena);
    expect(after.arena?.strategies).toHaveLength(sampleArena.strategies.length);
    // The recommendation is the BACKEND's, and selecting another plan is a
    // human override — it must not rewrite what was recommended.
    expect(after.arena?.recommended_strategy_id).toBe(sampleArena.recommended_strategy_id);
    expect(after.selectedStrategyId).not.toBe(after.arena?.recommended_strategy_id);
  });
});
