import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BeforeAfterHero } from "./BeforeAfterHero";
import { GoalDiagnosis } from "./GoalDiagnosis";
import { RecommendationHero } from "./RecommendationHero";
import { RefinementTrace } from "./RefinementTrace";
import { PlaybackControls } from "../playback/PlaybackControls";
import { renderWithContext } from "../../test/testUtils";
import {
  makeStrategyMetrics,
  sampleArena,
  sampleFactory,
  sampleStrategySessions,
  strategyB,
} from "../../test/fixtures";
import { statsFromStrategyMetrics } from "../../utils/executiveSummary";
import { initialConceptState, initialPlaybackState } from "../../state/types";
import type { FactoryConceptDraft, SimulationTrace } from "../../api/types";

/** The final demo pass, at the component level. */

const draft = { name: "concept" } as unknown as FactoryConceptDraft;

/** A greenfield session: a concept was built, so there is no "today". */
const greenfield = {
  arena: sampleArena,
  selectedStrategyId: strategyB.strategy_id,
  factory: sampleFactory,
  concept: { ...initialConceptState, draft },
};

/** The brownfield entry: the bundled example line, which really does exist. */
const brownfield = { ...greenfield, concept: initialConceptState };

describe("§1 — baseline / selected plan, per route", () => {
  it("calls the unchanged state a baseline concept on the product-first route", () => {
    const baseline = statsFromStrategyMetrics(sampleArena.baseline_metrics);
    renderWithContext(<GoalDiagnosis baseline={baseline} />, greenfield);
    expect(screen.getByTestId("baseline-label")).toHaveTextContent("Baseline concept");
  });

  it("keeps 'Today' for a factory that already exists", () => {
    const baseline = statsFromStrategyMetrics(sampleArena.baseline_metrics);
    renderWithContext(<GoalDiagnosis baseline={baseline} />, brownfield);
    expect(screen.getByTestId("baseline-label")).toHaveTextContent("Today, without changes");
  });

  it("names both sides of the comparison by what they are", () => {
    renderWithContext(<BeforeAfterHero />, greenfield);
    expect(screen.getByTestId("before-after-heading")).toHaveTextContent(
      "Verified comparison — Baseline → Plan B",
    );
    expect(screen.getByTestId("ba-baseline-label")).toHaveTextContent("Baseline");
    // The plan side is the PLAN, not the word "After".
    expect(screen.getByTestId("ba-selected-label")).toHaveTextContent("Plan B");
  });
});

describe("§3 — the limiting stage moved", () => {
  it("says so, and says where it went, when the two runs disagree", () => {
    const moved = {
      ...greenfield,
      arena: {
        ...sampleArena,
        baseline_metrics: makeStrategyMetrics({ bottleneck_machine_id: "m-a", goal_met: false }),
        strategies: [
          { ...strategyB, metrics: makeStrategyMetrics({ bottleneck_machine_id: "m-b" }) },
        ],
      },
      selectedStrategyId: strategyB.strategy_id,
    };
    renderWithContext(<BeforeAfterHero />, moved);

    const insight = screen.getByTestId("limiting-stage-moved");
    expect(insight).toHaveTextContent("Machine A");
    expect(insight).toHaveTextContent("Machine B");
    // The engineering point, not just the fact.
    expect(insight).toHaveTextContent(/constraint did not disappear/i);
  });

  it("renders nothing when the constraint stayed put — no fabricated insight", () => {
    const same = {
      ...greenfield,
      arena: {
        ...sampleArena,
        baseline_metrics: makeStrategyMetrics({ bottleneck_machine_id: "m-b", goal_met: false }),
        strategies: [{ ...strategyB, metrics: makeStrategyMetrics({ bottleneck_machine_id: "m-b" }) }],
      },
    };
    renderWithContext(<BeforeAfterHero />, same);
    expect(screen.queryByTestId("limiting-stage-moved")).toBeNull();
  });
});

describe("§4 — what the plan actually changes", () => {
  it("offers the detail behind '2 changes' and states its before/after pairs", async () => {
    const user = userEvent.setup();
    renderWithContext(<RecommendationHero />, {
      ...greenfield,
      strategySessions: sampleStrategySessions,
    });

    await user.click(screen.getByTestId("rec-hero-changes-toggle"));
    const list = screen.getByTestId("rec-hero-change-list");
    expect(list).toHaveTextContent(/Read from the factory model/i);
    expect(list.querySelectorAll(".plan-delta__row").length).toBeGreaterThan(0);
  });

  it("still explains the plan when the session was not restored, and says which source it used", async () => {
    const user = userEvent.setup();
    renderWithContext(<RecommendationHero />, { ...greenfield, strategySessions: {} });

    await user.click(screen.getByTestId("rec-hero-changes-toggle"));
    const list = screen.getByTestId("rec-hero-change-list");
    // Plan B adds a shift and two operators; both are exact deltas.
    expect(list).toHaveTextContent("1 shift");
    expect(list).toHaveTextContent("2 shifts");
    expect(list).toHaveTextContent(/Read from the verified change summary/i);
  });
});

describe("§5 — why the recommendation changed", () => {
  it("names the constraint and the plan it displaced", () => {
    renderWithContext(<RefinementTrace />, {
      ...greenfield,
      refinementTrace: {
        request: "Reach 1,900 units/day without purchasing another machine.",
        previousPlan: "Plan A",
        currentPlan: "Plan B",
        changed: true,
      },
    });
    expect(screen.getByTestId("refinement-trace-request")).toHaveTextContent(
      "without purchasing another machine",
    );
    const change = screen.getByTestId("refinement-trace-change");
    expect(change).toHaveTextContent("Plan A");
    expect(change).toHaveTextContent("Plan B");
  });

  it("says plainly when the refinement did NOT move the recommendation", () => {
    renderWithContext(<RefinementTrace />, {
      ...greenfield,
      refinementTrace: {
        request: "Keep it below EUR 150k.",
        previousPlan: "Plan B",
        currentPlan: "Plan B",
        changed: false,
      },
    });
    expect(screen.getByTestId("refinement-trace-unchanged")).toHaveTextContent(
      /still recommended under this constraint/i,
    );
  });

  it("renders nothing before any refinement has been applied", () => {
    const { container } = renderWithContext(<RefinementTrace />, greenfield);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("§7 — the commercial gaps, grouped and de-duplicated", () => {
  it("names each missing input once, under what an engineer would go and do", () => {
    renderWithContext(<RecommendationHero />, greenfield);
    const gaps = screen.getByTestId("rec-hero-gaps");
    // Plan B is blocked by a shift cost and an operator cost.
    expect(screen.getByTestId("rec-hero-gap-SHIFT_COST")).toHaveTextContent(
      "Cost of an additional shift",
    );
    expect(screen.getByTestId("rec-hero-gap-OPERATOR_COST")).toBeInTheDocument();
    // And never as the enum member.
    expect(gaps.textContent).not.toMatch(/SHIFT_COST|OPERATOR_COST/);
  });
});

describe("§2 — which run am I watching", () => {
  const trace: SimulationTrace = {
    trace_version: 1,
    horizon_seconds: 57_600,
    sampled_interval_seconds: 600,
    config: { max_tracked_units: 10, sample_count_target: 96 },
    events: [],
    machine_series: [],
    buffer_series: [],
    unit_tracks: [],
    story_markers: [],
    total_unit_count: 1900,
    tracked_unit_count: 10,
  } as unknown as SimulationTrace;

  it("states the plan, the state, the horizon and the outcome", () => {
    renderWithContext(<PlaybackControls />, {
      ...greenfield,
      playback: { ...initialPlaybackState, active: true, stageKey: "final", trace },
    });

    expect(screen.getByTestId("playback-scenario")).toHaveTextContent("Plan B");
    expect(screen.getByTestId("playback-state-name")).toHaveTextContent("Selected plan");
    expect(screen.getByTestId("playback-horizon")).toHaveTextContent("16 h operating horizon");
    expect(screen.getByTestId("playback-output")).toHaveTextContent("1,900");
    expect(screen.getByTestId("playback-target")).toHaveTextContent("1,900");
    expect(screen.getByTestId("playback-verdict")).toHaveTextContent("Target met");
  });

  it("describes the baseline run as the baseline, with its own gap", () => {
    renderWithContext(<PlaybackControls />, {
      ...greenfield,
      playback: { ...initialPlaybackState, active: true, stageKey: "baseline", trace },
    });

    expect(screen.getByTestId("playback-scenario")).toHaveTextContent("Baseline concept");
    expect(screen.getByTestId("playback-output")).toHaveTextContent("1,105");
    expect(screen.getByTestId("playback-verdict")).toHaveTextContent("Gap 795/day");
  });

  it("labels the two playback tabs by what they are, not Before/After", () => {
    renderWithContext(<PlaybackControls />, {
      ...greenfield,
      playback: { ...initialPlaybackState, active: true, stageKey: "final", trace },
    });
    expect(screen.getByTestId("playback-view-before")).toHaveTextContent("Baseline");
    expect(screen.getByTestId("playback-view-after")).toHaveTextContent("Plan B");
  });
});
