import { describe, expect, it } from "vitest";
import { activeScenario } from "./scenario";
import { sampleArena } from "../test/fixtures";
import { initialAppState, initialPlaybackState } from "../state/types";
import type { AppState } from "../state/types";

/** Which run the screen is describing — reproduced in the golden run. */

const planB = sampleArena.strategies[0];

function stateWith(overrides: Partial<AppState>): AppState {
  return {
    ...initialAppState,
    arena: sampleArena,
    selectedStrategyId: planB.strategy_id,
    concept: { ...initialAppState.concept, draft: { name: "CEC-120" } as never },
    ...overrides,
  };
}

describe("activeScenario", () => {
  it("follows the selected plan when nothing is playing", () => {
    const scenario = activeScenario(stateWith({}));

    expect(scenario.name).toBe(planB.label);
    expect(scenario.isBaseline).toBe(false);
    expect(scenario.fromPlayback).toBe(false);
    expect(scenario.metrics).toEqual(planB.metrics);
  });

  it("follows the BASELINE while baseline playback is running", () => {
    // The defect, at the level it was decided.
    const scenario = activeScenario(
      stateWith({ playback: { ...initialPlaybackState, active: true, stageKey: "baseline" } }),
    );

    expect(scenario.name).toBe("Baseline concept");
    expect(scenario.isBaseline).toBe(true);
    expect(scenario.fromPlayback).toBe(true);
    // Scenario-dependent figures follow the same run as the name, so a
    // limiting-stage or output label cannot describe the other scenario.
    expect(scenario.metrics).toEqual(sampleArena.baseline_metrics);
  });

  it("follows the selected plan while that plan's playback is running", () => {
    const scenario = activeScenario(
      stateWith({ playback: { ...initialPlaybackState, active: true, stageKey: "final" } }),
    );

    expect(scenario.name).toBe(planB.label);
    expect(scenario.isBaseline).toBe(false);
    expect(scenario.metrics).toEqual(planB.metrics);
  });

  it("returns to the selected plan once playback closes", () => {
    // Toggling back must rebind, not leave the heading stuck on baseline.
    const playing = activeScenario(
      stateWith({ playback: { ...initialPlaybackState, active: true, stageKey: "baseline" } }),
    );
    const closed = activeScenario(stateWith({ playback: initialPlaybackState }));

    expect(playing.name).toBe("Baseline concept");
    expect(closed.name).toBe(planB.label);
  });

  it("ignores a playback that is not active", () => {
    // A stage key left behind by a closed playback must not steer the
    // heading — `active` is the gate.
    const scenario = activeScenario(
      stateWith({ playback: { ...initialPlaybackState, active: false, stageKey: "baseline" } }),
    );
    expect(scenario.name).toBe(planB.label);
  });

  it("names the baseline when no plan is selected at all", () => {
    const scenario = activeScenario(stateWith({ selectedStrategyId: null }));
    expect(scenario.isBaseline).toBe(true);
    expect(scenario.metrics).toEqual(sampleArena.baseline_metrics);
  });

  it("uses the brownfield vocabulary on an existing line", () => {
    // The example line is modelled as existing, where "baseline concept"
    // would be the wrong word in the other direction.
    const scenario = activeScenario(
      stateWith({
        concept: { ...initialAppState.concept, draft: null },
        playback: { ...initialPlaybackState, active: true, stageKey: "baseline" },
      }),
    );
    expect(scenario.name).toBe("Today, without changes");
  });
});
