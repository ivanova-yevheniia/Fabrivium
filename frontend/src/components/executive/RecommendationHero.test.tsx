import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  sampleArena,
  sampleFactory,
  sampleSessionTwoIterations,
  sampleStrategySessions,
  strategyA,
  strategyB,
} from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { RecommendationHero } from "./RecommendationHero";

/**
 * Phase 12 §5 — the recommendation hero became the page's focal point, and
 * with it the component that states the verdict. Every truthfulness rule
 * the Executive page had before now has to hold HERE, so each of them is
 * pinned below.
 *
 * The fixture arena is the honest hard case, unchanged since Phase 8B:
 *   Plan A — fully priced (EUR 85,000), buys a machine, MISSES the target.
 *   Plan B — RECOMMENDED, reaches the target, EUR 0 known CAPEX, and is
 *            NOT commercially complete (its real cost is unknown).
 * A hero that treats "unknown" as "zero", or lets a manually selected plan
 * wear the word "Recommended", passes none of these.
 */

const arenaState = {
  factory: sampleFactory,
  arena: sampleArena,
  strategySessions: sampleStrategySessions,
  session: sampleSessionTwoIterations,
};

const recommendedId = sampleArena.recommended_strategy_id;

describe("RecommendationHero — the verdict", () => {
  it("names the selected plan and reports its verified before/after figures", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });

    const hero = screen.getByTestId("recommendation-hero");
    expect(hero).toHaveTextContent(strategyB.label);
    expect(screen.getByTestId("rec-hero-before")).toHaveTextContent(
      sampleArena.baseline_metrics.completed_units.toLocaleString("en-US"),
    );
    expect(screen.getByTestId("rec-hero-after")).toHaveTextContent(
      strategyB.metrics.completed_units.toLocaleString("en-US"),
    );
  });

  it("states TARGET ACHIEVED only when the verified metrics actually met demand", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });
    expect(screen.getByTestId("rec-hero-verdict")).toHaveTextContent(/target achieved/i);
    expect(screen.getByTestId("recommendation-hero")).toHaveAttribute("data-goal-met", "true");
  });

  it("refuses to say TARGET ACHIEVED for a plan that cannot sustain the target", () => {
    // The defect this guards: the simulator releases exactly the target and
    // stops, so a line that merely keeps up reports the target as met. Plan D
    // on the demo line does exactly that — paced 1,900, real capacity 1,880.
    // Measured at continuous demand it cannot hold the figure it claims.
    const fragile = {
      ...strategyB,
      metrics: {
        ...strategyB.metrics,
        goal_met: true,
        capacity_units_per_day: 1880,
        capacity_headroom_percent: -1,
        sustains_target_at_capacity: false,
      },
    };
    renderWithContext(<RecommendationHero />, {
      ...arenaState,
      arena: { ...sampleArena, strategies: [fragile, strategyA] },
      selectedStrategyId: fragile.strategy_id,
    });

    expect(screen.getByTestId("rec-hero-verdict")).not.toHaveTextContent(/target achieved/i);
    expect(screen.getByTestId("rec-hero-verdict")).toHaveTextContent(/only at full speed/i);
    expect(screen.getByTestId("rec-hero-capacity")).toHaveTextContent("1,880");
  });

  it("states the headroom when the plan genuinely sustains the target", () => {
    const solid = {
      ...strategyB,
      metrics: {
        ...strategyB.metrics,
        goal_met: true,
        capacity_units_per_day: 2430,
        capacity_headroom_percent: 28,
        sustains_target_at_capacity: true,
      },
    };
    renderWithContext(<RecommendationHero />, {
      ...arenaState,
      arena: { ...sampleArena, strategies: [solid, strategyA] },
      selectedStrategyId: solid.strategy_id,
    });

    expect(screen.getByTestId("rec-hero-verdict")).toHaveTextContent(/target achieved/i);
    expect(screen.getByTestId("rec-hero-capacity")).toHaveTextContent("28% headroom");
  });

  it("says so plainly — with the real remaining gap — when the plan misses the target", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });

    expect(screen.getByTestId("rec-hero-verdict")).toHaveTextContent(/target not reached/i);
    expect(screen.getByTestId("recommendation-hero")).toHaveAttribute("data-goal-met", "false");
    expect(screen.getByTestId("recommendation-hero")).toHaveTextContent(
      strategyA.metrics.demand_gap_units.toLocaleString("en-US"),
    );
  });
});

describe("RecommendationHero — recommended vs merely selected", () => {
  it("marks the recommended plan as Recommended", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });

    expect(screen.getByTestId("rec-hero-recommended")).toHaveTextContent(/recommended/i);
    expect(screen.queryByTestId("rec-hero-not-recommended")).toBeNull();
  });

  it("never lets a manually chosen plan read as the system's recommendation", () => {
    // Phase 9B §11B, carried into the hero: a user looking at Plan A must be
    // told, on the same element, that Plan B is what Fabrivium recommends.
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });

    expect(screen.queryByTestId("rec-hero-recommended")).toBeNull();
    const notice = screen.getByTestId("rec-hero-not-recommended");
    expect(notice).toHaveTextContent(/your selection/i);
    expect(notice).toHaveTextContent(strategyB.label);
  });
});

describe("RecommendationHero — cost honesty", () => {
  it("marks a EUR 0 known CAPEX as PARTIAL when the plan is not commercially complete", () => {
    // The single most dangerous misreading this UI can produce: Plan B buys
    // nothing, so known_capex is 0, but its shift/operator cost is simply
    // not known yet. "EUR 0" alone would read as "this plan is free".
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });

    // Audit §4 tightened this: not even "€0 + partial" is allowed, because
    // the zero is the part that gets remembered. Nothing is priced, so no
    // figure is shown.
    expect(screen.getByTestId("rec-hero-capex")).not.toHaveTextContent("€0");
    expect(screen.getByTestId("rec-hero-capex")).toHaveTextContent(/nothing priced yet/i);
  });

  it("does not mark a fully priced plan as partial", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });

    expect(screen.getByTestId("rec-hero-capex")).toHaveTextContent("85,000");
    expect(screen.queryByTestId("rec-hero-capex-partial")).toBeNull();
  });

  it("lists the backend's own information gaps rather than hiding them", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });

    const gaps = screen.getByTestId("rec-hero-gaps");
    for (const gap of strategyB.cost.information_gaps) {
      expect(gaps).toHaveTextContent(gap.description);
    }
  });
});

describe("RecommendationHero — intervention and machine count", () => {
  it("leads with the plan's primary intervention, read from its verified actions", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });
    expect(screen.getByTestId("rec-hero-intervention")).toHaveTextContent("+1 shift/day");
  });

  it("reports the machine count from the verified action summary", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: recommendedId });
    expect(screen.getByTestId("rec-hero-machines")).toHaveTextContent(
      String(strategyB.actions.added_machine_count),
    );

    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });
    expect(screen.getAllByTestId("rec-hero-machines")[1]).toHaveTextContent(
      String(strategyA.actions.added_machine_count),
    );
  });

  it("renders nothing at all when no strategy is selected — never a placeholder verdict", () => {
    renderWithContext(<RecommendationHero />, { ...arenaState, selectedStrategyId: null });
    expect(screen.queryByTestId("recommendation-hero")).toBeNull();
  });
});
