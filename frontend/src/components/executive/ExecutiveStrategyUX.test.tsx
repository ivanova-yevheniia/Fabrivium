import { screen, within } from "@testing-library/react";
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
import type { PlanningProvenance } from "../../api/types";
import { StrategyRail } from "./StrategyRail";
import { FinalSuccessBanner } from "./FinalSuccessBanner";
import { BeforeAfterHero } from "./BeforeAfterHero";
import { ProvenanceBadge } from "./ProvenanceBadge";

/**
 * Phase 9B section 19 — coverage for the FOUR presentation defects real
 * manual QA found in Executive View (section 11) plus the selected-strategy
 * hero rule (section 12).
 *
 * The fixture arena is deliberately the honest hard case, unchanged from
 * Phase 8B: Plan A is fully priced and MISSES the target, Plan B is the
 * RECOMMENDED option, reaches the target, has €0 known CAPEX and is NOT
 * commercially complete. Every assertion below would have passed silently
 * on a UI that treats "unknown" as "zero" or lets a manually selected plan
 * masquerade as the recommendation — which is exactly why they exist.
 */

const arenaState = {
  factory: sampleFactory,
  arena: sampleArena,
  strategySessions: sampleStrategySessions,
  session: sampleSessionTwoIterations,
};

/** Plan B is the recommended option in the fixture. */
const recommendedId = sampleArena.recommended_strategy_id;

const fallbackProvenance: PlanningProvenance = {
  requirements_source: "DETERMINISTIC",
  planning_source: "DETERMINISTIC",
  explanation_source: "NONE",
  fallback_used: true,
  provider_name: "watsonx",
  model_name: "ibm/granite-4-h-small",
};

const graniteProvenance: PlanningProvenance = {
  requirements_source: "LLM",
  planning_source: "DETERMINISTIC",
  explanation_source: "NONE",
  fallback_used: false,
  provider_name: "watsonx",
  model_name: "ibm/granite-4-h-small",
};

describe("Phase 9B 11A — the recommended strategy is visible without scrolling", () => {
  it("renders the recommended option FIRST in the Executive rail", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    const cards = within(screen.getByTestId("strategy-rail")).getAllByTestId(/^strategy-card-/);
    expect(cards[0]).toHaveAttribute("data-testid", `strategy-card-${recommendedId}`);
  });

  it("still renders EVERY option — recommended-first is a reordering, never a filter", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    const cards = within(screen.getByTestId("strategy-rail")).getAllByTestId(/^strategy-card-/);
    expect(cards).toHaveLength(sampleArena.strategies.length);
    expect(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`strategy-card-${strategyB.strategy_id}`)).toBeInTheDocument();
  });

  it("preserves the backend's relative order of the non-recommended options", () => {
    // Pin the invariant rather than the fixture's current 2 options: after
    // the recommended card, the rest must appear in `arena.strategies`
    // order, so display order can never be mistaken for a re-ranking.
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    const rendered = within(screen.getByTestId("strategy-rail"))
      .getAllByTestId(/^strategy-card-/)
      .map((el) => el.getAttribute("data-testid")?.replace("strategy-card-", ""));
    const expected = [
      recommendedId,
      ...sampleArena.strategies.map((s) => s.strategy_id).filter((id) => id !== recommendedId),
    ];
    expect(rendered).toEqual(expected);
  });

  it("marks exactly the backend's recommended option, wherever it is drawn", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    expect(screen.getByTestId(`strategy-recommended-${recommendedId}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`strategy-recommended-${strategyA.strategy_id}`)).toBeNull();
  });
});

describe("Phase 9B 11B — selected is never presented as recommended", () => {
  it("names BOTH plans when the user is viewing something other than the recommendation", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });

    const notice = screen.getByTestId("strategy-selection-notice");
    expect(within(notice).getByTestId("strategy-selection-notice-recommended")).toHaveTextContent(strategyB.label);
    expect(within(notice).getByTestId("strategy-selection-notice-viewing")).toHaveTextContent(strategyA.label);
    expect(notice).toHaveTextContent(/recommended/i);
    expect(notice).toHaveTextContent(/currently viewing/i);
  });

  it("stays silent when the user IS viewing the recommendation — no redundant noise", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });
    expect(screen.queryByTestId("strategy-selection-notice")).toBeNull();
  });

  it("says on the final banner that a manually selected plan is NOT the recommendation", () => {
    renderWithContext(<FinalSuccessBanner />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });

    const note = screen.getByTestId("final-success-banner-not-recommended");
    expect(note).toHaveTextContent(strategyB.label);
    expect(screen.getByTestId("final-success-banner-subject")).toHaveTextContent(strategyA.label);
  });

  it("calls the recommended plan recommended when it IS the one selected", () => {
    renderWithContext(<FinalSuccessBanner />, { ...arenaState, selectedStrategyId: recommendedId });

    expect(screen.queryByTestId("final-success-banner-not-recommended")).toBeNull();
    expect(screen.getByTestId("final-success-banner-subject")).toHaveTextContent(/recommended strategy/i);
  });
});

describe("Phase 9B 11C — an unknown cost is never rendered as a zero cost", () => {
  it("shows no figure at all when nothing in the plan is priced yet", () => {
    // Audit §4 tightened this. "€0 + unpriced" still LEADS with a zero, and
    // a zero is what a reader remembers. When the known sum is 0 and the
    // plan is incomplete, nothing about the cost is known, so no number is
    // shown — the absence is stated in words instead.
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    const card = screen.getByTestId(`strategy-card-${strategyB.strategy_id}`);
    expect(strategyB.cost.known_capex).toBe(0);
    expect(strategyB.commercially_complete).toBe(false);
    expect(card).toHaveTextContent(/nothing priced yet/i);
    expect(card).not.toHaveTextContent("€0");
  });

  it("keeps the independent REQUIRES COST DATA badge exactly as it was", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    expect(screen.getByTestId(`strategy-needs-cost-${strategyB.strategy_id}`)).toHaveTextContent(
      /requires cost data/i,
    );
  });

  it("does NOT mark a fully priced plan as partial", () => {
    renderWithContext(<StrategyRail />, { ...arenaState, selectedStrategyId: recommendedId });

    expect(strategyA.commercially_complete).toBe(true);
    expect(screen.queryByTestId(`strategy-capex-partial-${strategyA.strategy_id}`)).toBeNull();
    expect(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).toHaveTextContent("€85,000");
  });

  it("still lists the unresolved cost questions on the final banner", () => {
    renderWithContext(<FinalSuccessBanner />, { ...arenaState, selectedStrategyId: recommendedId });

    const gaps = screen.getByTestId("final-success-banner-gaps");
    expect(strategyB.cost.information_gaps.length).toBeGreaterThan(0);
    expect(within(gaps).getAllByRole("listitem")).toHaveLength(strategyB.cost.information_gaps.length);
  });
});

describe("Phase 9B 11D — compact provenance reduces repetition without hiding a fallback", () => {
  it("still tones the fallback as unverified, and still carries it, in compact mode", () => {
    render_compact(fallbackProvenance);

    const badge = screen.getByTestId("provenance-badge");
    // The tone is the machine-checkable half of the distinction, and it is
    // unchanged. The badge no longer LEADS with the provider outage, but the
    // outage is still reachable — see the title assertion below.
    expect(badge).toHaveAttribute("data-tone", "unknown");
    expect(badge).toHaveAttribute("data-compact", "true");
    expect(badge).not.toHaveTextContent(/granite/i);
    expect(badge.getAttribute("title")).toMatch(/deterministic parser handled it instead/i);
  });

  it("drops only the duplicated explanatory sentence, keeping it reachable as a title", () => {
    render_compact(fallbackProvenance);

    const badge = screen.getByTestId("provenance-badge");
    expect(badge).not.toHaveTextContent(/deterministic parser handled it instead/i);
    expect(badge).toHaveAttribute("title", expect.stringMatching(/deterministic parser handled it instead/i));
  });

  it("compact mode NEVER upgrades a fallback into an IBM Granite claim", () => {
    render_compact(fallbackProvenance);
    expect(screen.getByTestId("provenance-badge")).not.toHaveTextContent(/IBM Granite/i);
  });

  it("keeps the provider sentence reachable in the default (non-compact) placement", () => {
    renderWithContext(<ProvenanceBadge provenance={fallbackProvenance} />, {});
    const badge = screen.getByTestId("provenance-badge");
    // It used to be rendered as visible body text on the results screen. It is
    // now a title, and rendered in full in the Architecture panel. The fact
    // survives; it is no longer the headline of the screen carrying the
    // throughput figure.
    expect(badge.getAttribute("title")).toMatch(/deterministic parser handled it instead/i);
    expect(badge).toHaveTextContent(/requirements read by fabrivium/i);
  });

  it("compact mode reports live Granite as verified when Granite really ran", () => {
    render_compact(graniteProvenance);

    const badge = screen.getByTestId("provenance-badge");
    expect(badge).toHaveAttribute("data-tone", "verified");
    expect(badge).toHaveTextContent(/IBM Granite/i);
  });

  function render_compact(provenance: PlanningProvenance) {
    renderWithContext(<ProvenanceBadge provenance={provenance} compact />, {});
  }
});

describe("Phase 9B 12 — the hero always describes the CURRENTLY SELECTED strategy", () => {
  it("Plan A selected → hero and banner both report Plan A's verified numbers", () => {
    renderWithContext(
      <>
        <BeforeAfterHero />
        <FinalSuccessBanner />
      </>,
      { ...arenaState, selectedStrategyId: strategyA.strategy_id },
    );

    expect(screen.getByTestId("before-after-hero")).toHaveTextContent(strategyA.label);
    // Phase 12 §11 splits the figure from its unit ("1,619" + "units/day") so
    // the number can be set at display size with tabular figures. The point of
    // the assertion is unchanged: the AFTER side must carry the verified
    // output of the SELECTED plan, not the recommended one.
    expect(screen.getByTestId("before-after-hero")).toHaveTextContent(
      strategyA.metrics.completed_units.toLocaleString("en-US"),
    );
    expect(screen.getByTestId("before-after-hero")).toHaveTextContent("units/day");
    // Plan A misses the target — the banner must say so, not claim success.
    expect(screen.getByTestId("final-success-banner")).toHaveTextContent("TARGET NOT YET REACHED");
    expect(screen.getByTestId("final-success-banner-subject")).toHaveTextContent(strategyA.label);
  });

  it("Plan B selected → hero and banner both report Plan B's verified numbers", () => {
    renderWithContext(
      <>
        <BeforeAfterHero />
        <FinalSuccessBanner />
      </>,
      { ...arenaState, selectedStrategyId: strategyB.strategy_id },
    );

    expect(screen.getByTestId("before-after-hero")).toHaveTextContent(strategyB.label);
    expect(screen.getByTestId("final-success-banner")).toHaveTextContent("TARGET ACHIEVED");
    expect(screen.getByTestId("final-success-banner-subject")).toHaveTextContent(strategyB.label);
  });

  it("the machine count in the banner is the SELECTED plan's, not the recommendation's", () => {
    // Plan A adds 1 machine, Plan B adds 0. A banner that ignored the
    // selection would show the same figure for both.
    expect(strategyA.actions.added_machine_count).not.toBe(strategyB.actions.added_machine_count);

    const a = renderWithContext(<FinalSuccessBanner />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });
    expect(screen.getByTestId("final-success-banner")).toHaveTextContent(
      `${strategyA.actions.added_machine_count} new machine`,
    );
    a.unmount();

    renderWithContext(<FinalSuccessBanner />, { ...arenaState, selectedStrategyId: strategyB.strategy_id });
    expect(screen.getByTestId("final-success-banner")).toHaveTextContent(
      `${strategyB.actions.added_machine_count} new machine`,
    );
  });

  it("renders nothing at all when no strategy is selected — never a stale hero", () => {
    const { container } = renderWithContext(
      <>
        <BeforeAfterHero />
        <FinalSuccessBanner />
      </>,
      { ...arenaState, selectedStrategyId: null },
    );
    expect(container).toBeEmptyDOMElement();
  });
});

/**
 * Phase 11 — "which options actually meet the target?" must be answerable
 * without horizontal scrolling.
 *
 * The rail is `overflow-x: auto` and only ~3 of 5 cards fit at 1366px. On
 * the real flagship arena the recommended-first-then-backend-order rule put
 * the SECOND target-achieving plan (Plan D: 1,900/day, but 2 new machines
 * and EUR 205,000) last and off-screen, so a judge saw exactly one ✓.
 * Plans that reach the target are now kept together at the front.
 */
describe("Phase 11 — target-achieving options are grouped at the front of the rail", () => {
  const missA = { ...strategyA, strategy_id: "s-miss-a", label: "Miss A", metrics: { ...strategyA.metrics, goal_met: false } };
  const missB = { ...strategyA, strategy_id: "s-miss-b", label: "Miss B", metrics: { ...strategyA.metrics, goal_met: false } };
  const hit = { ...strategyB, strategy_id: "s-hit", label: "Other Hit", metrics: { ...strategyB.metrics, goal_met: true } };
  const rec = { ...strategyB, strategy_id: "s-rec", label: "Recommended", metrics: { ...strategyB.metrics, goal_met: true } };

  // Backend order deliberately buries the other goal-met option LAST.
  const arena = { ...sampleArena, recommended_strategy_id: "s-rec", strategies: [missA, rec, missB, hit] };
  const state = { ...arenaState, arena, selectedStrategyId: "s-rec" };

  const order = () =>
    within(screen.getByTestId("strategy-rail"))
      .getAllByTestId(/^strategy-card-/)
      .map((el) => el.getAttribute("data-testid")?.replace("strategy-card-", ""));

  it("puts the recommended plan first and the other target-achieving plan second", () => {
    renderWithContext(<StrategyRail />, state);
    expect(order().slice(0, 2)).toEqual(["s-rec", "s-hit"]);
  });

  it("still renders every option — grouping is a reordering, never a filter", () => {
    renderWithContext(<StrategyRail />, state);
    expect(order()).toHaveLength(4);
    expect(order().slice(2).sort()).toEqual(["s-miss-a", "s-miss-b"]);
  });

  it("keeps the backend's relative order WITHIN each group", () => {
    renderWithContext(<StrategyRail />, state);
    // missA precedes missB in arena.strategies and must still do so.
    expect(order()).toEqual(["s-rec", "s-hit", "s-miss-a", "s-miss-b"]);
  });

  it("does not re-mark the recommendation — only the backend's choice is recommended", () => {
    renderWithContext(<StrategyRail />, state);
    expect(screen.getByTestId("strategy-recommended-s-rec")).toBeInTheDocument();
    expect(screen.queryByTestId("strategy-recommended-s-hit")).toBeNull();
  });
});

describe("Phase 11 — no internal strategy id is shown to a judge", () => {
  it("renders another plan's LABEL, not its id, in a dominance tradeoff", () => {
    const dominated = {
      ...strategyA,
      tradeoffs: [`Operationally dominated by: ${strategyB.strategy_id}.`],
    };
    const arena = { ...sampleArena, strategies: [strategyB, dominated] };
    renderWithContext(<StrategyRail />, { ...arenaState, arena, selectedStrategyId: strategyB.strategy_id });

    const tradeoff = screen.getByTestId(`strategy-tradeoff-${dominated.strategy_id}`);
    // The label, not the id — and in the softened wording a saved arena now
    expect(tradeoff).toHaveTextContent(
      `Requires more operational changes than ${strategyB.label}.`,
    );
    expect(tradeoff).not.toHaveTextContent(strategyB.strategy_id);
    expect(tradeoff.textContent).not.toContain(strategyB.strategy_id);
  });
});
