import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppContext } from "../../state/AppContext";
import { makeContextValue } from "../../test/testUtils";
import { sampleArena, sampleStrategySessions } from "../../test/fixtures";
import { RecommendationHero } from "./RecommendationHero";
import { hydrateProject } from "../../state/projectSerialization";
import { emptyProjectState } from "../../api/projects";
import { initialAppState } from "../../state/types";
import type { AppState } from "../../state/types";
import type { ProjectDocument, StaleReport } from "../../api/projects";

/** A saved verified project stays watchable after it is reopened. */

const NO_STALENESS: StaleReport = { stale: [], current: [], unverified: [], summary: "" };
const planB = sampleArena.strategies[0];

function reopened(overrides: Partial<AppState> = {}): AppState {
  return {
    ...initialAppState,
    arena: sampleArena,
    selectedStrategyId: planB.strategy_id,
    factory: { name: "Line", machines: [], products: [], buffers: [] } as never,
    productId: "p-1",
    concept: { ...initialAppState.concept, draft: { name: "Concept" } as never },
    // The defining condition of a reopened project.
    session: null,
    strategySessions: {},
    ...overrides,
  };
}

function renderHero(state: AppState, actions = {}) {
  return render(
    <AppContext.Provider value={makeContextValue(state, actions)}>
      <RecommendationHero />
    </AppContext.Provider>,
  );
}

describe("playback after reopening a saved project", () => {
  it("offers the play action with no exploration session at all", () => {
    renderHero(reopened());

    // The reported defect: this button was absent, leaving only Compare.
    expect(screen.getByTestId("rec-hero-play")).toBeInTheDocument();
  });

  it("still offers it while a session IS live, unchanged", () => {
    renderHero(reopened({ strategySessions: sampleStrategySessions }));
    expect(screen.getByTestId("rec-hero-play")).toBeInTheDocument();
  });

  it("opens playback without re-running any exploration", async () => {
    const openPlayback = vi.fn(async () => {});
    const exploreOptions = vi.fn(async () => {});
    const user = userEvent.setup();

    renderHero(reopened(), { openPlayback, exploreOptions });
    await user.click(screen.getByTestId("rec-hero-play"));

    expect(openPlayback).toHaveBeenCalledTimes(1);
    // Nothing re-verifies, re-plans or rebuilds the concept to get a trace.
    expect(exploreOptions).not.toHaveBeenCalled();
  });

  it("hides the action for a plan that cannot be rebuilt from what was saved", () => {
    // Fails closed rather than offering a click that would be refused. The
    // summary records that a cycle-time change happened, not its new value.
    const unreplayable = {
      ...sampleArena,
      strategies: [
        { ...planB, actions: { ...planB.actions, action_types: ["CHANGE_MACHINE_CYCLE_TIME"] } },
        ...sampleArena.strategies.slice(1),
      ],
    };
    renderHero(reopened({ arena: unreplayable as never }));

    expect(screen.queryByTestId("rec-hero-play")).not.toBeInTheDocument();
  });

  it("hides it while playback is already open", () => {
    renderHero(
      reopened({
        playback: { ...initialAppState.playback, active: true, stageKey: "final" },
      }),
    );
    expect(screen.queryByTestId("rec-hero-play")).not.toBeInTheDocument();
  });
});

describe("what a hydrated project carries into playback", () => {
  function documentFrom(state: AppState): ProjectDocument {
    return {
      schema_version: 1,
      project_id: "p-1",
      name: "Saved",
      created_at: "2026-08-01T09:00:00.000000+00:00",
      updated_at: "2026-08-20T09:00:00.000000+00:00",
      state: {
        ...emptyProjectState(),
        concept: {
          draft: { name: "Concept" } as never,
          factory: state.factory,
          product_id: state.productId,
          layout: null,
          verified_from: null,
        },
        results: {
          arena: state.arena,
          selected_strategy_id: state.selectedStrategyId,
          explore_requests: [],
        },
      },
    };
  }

  it("restores everything a replay needs, and still no session", () => {
    const restored = hydrateProject(documentFrom(reopened()), NO_STALENESS);

    // The three things the reconstruction reads, all persisted.
    expect(restored.factory).not.toBeNull();
    expect(restored.productId).toBe("p-1");
    expect(restored.arena?.strategies[0].actions).toBeDefined();
    expect(restored.arena?.baseline_metrics).toBeDefined();

    // And the thing it deliberately does not need. Sessions stay unpersisted
    // — the fix was to stop requiring one, not to start storing one.
    expect(restored.session).toBeNull();
    expect(restored.strategySessions).toEqual({});
  });

  it("carries the metrics the replay is checked against", () => {
    // The verification gate compares a fresh run to these. Without them a
    // stale concept could be animated under its old figures.
    const restored = hydrateProject(documentFrom(reopened()), NO_STALENESS);
    expect(restored.arena?.strategies[0].metrics.completed_units).toBe(
      planB.metrics.completed_units,
    );
  });
});
