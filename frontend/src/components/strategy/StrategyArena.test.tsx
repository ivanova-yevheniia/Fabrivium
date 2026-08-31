import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  conversationTurnResponse,
  makeConversation,
  makeStrategyAnswer,
  sampleArena,
  sampleFactory,
  sampleSessionAccepted,
  sampleSessionTwoIterations,
  sampleStrategyComparison,
  sampleStrategySessions,
  shiftCostGap,
  strategyA,
  strategyB,
} from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { appReducer } from "../../state/appReducer";
import { initialAppState } from "../../state/types";
import { StrategyArenaPanel } from "./StrategyArenaPanel";
import { StrategyAskBox } from "./StrategyAskBox";

/** Phase 8B frontend coverage (section 25, FRONTEND block). */

const arenaState = {
  factory: sampleFactory,
  arena: sampleArena,
  strategySessions: sampleStrategySessions,
  selectedStrategyId: strategyB.strategy_id,
  session: sampleSessionTwoIterations,
};

describe("StrategyArenaPanel — strategy cards", () => {
  it("renders nothing at all before an exploration has run", () => {
    const { container } = renderWithContext(<StrategyArenaPanel />, { factory: sampleFactory });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows one card per verified option", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`strategy-card-${strategyB.strategy_id}`)).toBeInTheDocument();
  });

  it("communicates goal status, family, known cost and change count", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const card = screen.getByTestId(`strategy-card-${strategyA.strategy_id}`);

    expect(card).toHaveTextContent("Plan A");
    expect(card).toHaveTextContent("Equipment");
    expect(card).toHaveTextContent("1,619/day");
    expect(card).toHaveTextContent("281 short");
    expect(card).toHaveTextContent("€85,000");
    expect(card).toHaveTextContent("1 change");
    expect(card).toHaveAttribute("data-goal-met", "false");
  });

  it("marks the recommended option without hiding the others", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId(`strategy-recommended-${strategyB.strategy_id}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`strategy-recommended-${strategyA.strategy_id}`)).toBeNull();
  });

  it("shows the deterministic trade-off line the backend produced", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId(`strategy-tradeoff-${strategyB.strategy_id}`)).toHaveTextContent(
      strategyB.tradeoffs[0],
    );
  });

  it("reports families that produced nothing rather than hiding them", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId("families-without-options")).toHaveTextContent(/buffer_flow/i);
  });
});

describe("StrategyArenaPanel — complete/incomplete badges (section 21)", () => {
  it("marks BOTH options verified — verification is about engineering, not cost", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId(`strategy-verified-${strategyA.strategy_id}`)).toHaveTextContent("Verified");
    expect(screen.getByTestId(`strategy-verified-${strategyB.strategy_id}`)).toHaveTextContent("Verified");
  });

  it("flags only the unpriced option as requiring cost data", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId(`strategy-needs-cost-${strategyB.strategy_id}`)).toHaveTextContent(
      /requires cost data/i,
    );
    expect(screen.queryByTestId(`strategy-needs-cost-${strategyA.strategy_id}`)).toBeNull();
    expect(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).toHaveTextContent("Cost complete");
  });

  it("never calls the option with lower known CAPEX cheaper", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    // Plan B has EUR 0 known CAPEX against Plan A's EUR 85,000 and would be
    // the "cheaper" one under naive arithmetic. Nothing on screen says so.
    expect(screen.getByTestId("strategy-arena").textContent).not.toMatch(/cheap/i);
  });

  it("lists exactly what information is missing, per plan", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const gaps = screen.getByTestId("information-gaps");
    const shift = within(gaps).getByTestId(`gap-${strategyB.strategy_id}-SHIFT_COST`);

    expect(shift).toHaveTextContent(/operating cost of the changed shift/i);
    expect(shift).toHaveTextContent("Plan B");
    expect(shift).toHaveTextContent(/opex per day/i);
    expect(within(gaps).getByTestId(`gap-${strategyB.strategy_id}-OPERATOR_COST`)).toHaveTextContent(
      /employment cost of the additional/i,
    );
  });

  it("keeps a shared gap type on BOTH plans that are blocked by it", () => {
    // Two plans needing the same kind of cost is the common case, and each
    // needs its own row — otherwise the list understates what is blocked.
    const secondBlocked = { ...strategyA, strategy_id: "plan-x", label: "Plan X", commercially_complete: false,
      cost: { ...strategyA.cost, information_gaps: [shiftCostGap] } };
    renderWithContext(<StrategyArenaPanel />, {
      ...arenaState,
      arena: { ...sampleArena, strategies: [secondBlocked, strategyB] },
    });

    const gaps = screen.getByTestId("information-gaps");
    expect(within(gaps).getByTestId("gap-plan-x-SHIFT_COST")).toHaveTextContent("Plan X");
    expect(within(gaps).getByTestId(`gap-${strategyB.strategy_id}-SHIFT_COST`)).toHaveTextContent("Plan B");
  });
});

describe("StrategyArenaPanel — selecting a strategy (section 22)", () => {
  it("asks the store for that strategy, without computing anything itself", () => {
    const selectStrategy = vi.fn();
    renderWithContext(<StrategyArenaPanel />, arenaState, { selectStrategy });

    fireEvent.click(within(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).getByRole("button", { name: /Plan A/ }));
    expect(selectStrategy).toHaveBeenCalledWith(strategyA.strategy_id);
  });

  it("loads the EXACT verified session the backend returned for it", () => {
    // The reducer is the thing under test here: no geometry reconstruction,
    // no re-planning — the snapshot object itself is adopted.
    const state = appReducer(
      { ...initialAppState, ...arenaState },
      { type: "SELECT_STRATEGY", strategyId: strategyA.strategy_id },
    );

    expect(state.session).toBe(sampleSessionAccepted);
    expect(state.selectedStrategyId).toBe(strategyA.strategy_id);
    expect(state.selectedIteration).toBe("final");
  });

  it("refuses to show a strategy whose verified session it does not hold", () => {
    const state = { ...initialAppState, ...arenaState, strategySessions: {} };
    // Falling back to the previous plan's numbers under a new name is the
    // silent mismatch this app exists to prevent.
    expect(appReducer(state, { type: "SELECT_STRATEGY", strategyId: strategyA.strategy_id })).toBe(state);
  });

  it("opens the exploration on the recommended option", () => {
    const state = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS",
      response: {
        parse_result: {
          raw_user_request: "",
          parsed_requirements: strategyA.requirements,
          warnings: [],
          parser_type: "DETERMINISTIC_FALLBACK",
          structured_output_valid: false,
        },
        arena: sampleArena,
        sessions: sampleStrategySessions,
        provenance: {
          requirements_source: "DETERMINISTIC",
          planning_source: "DETERMINISTIC",
          explanation_source: "NONE",
          fallback_used: false,
          provider_name: null,
          model_name: null,
        },
      },
    });

    expect(state.selectedStrategyId).toBe(sampleArena.recommended_strategy_id);
    expect(state.session).toBe(sampleStrategySessions[strategyB.strategy_id]);
  });
});

describe("StrategyArenaPanel — compare mode (section 23)", () => {
  it("compares an option against the one currently open", () => {
    const compareWithStrategy = vi.fn();
    renderWithContext(<StrategyArenaPanel />, arenaState, { compareWithStrategy });

    fireEvent.click(within(screen.getByTestId(`strategy-card-${strategyA.strategy_id}`)).getByRole("button", { name: /compare/i }));
    expect(compareWithStrategy).toHaveBeenCalledWith(strategyA.strategy_id);
  });

  it("offers no Compare button on the option already open", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const open = screen.getByTestId(`strategy-card-${strategyB.strategy_id}`);
    expect(within(open).queryByRole("button", { name: /compare/i })).toBeNull();
  });

  it("renders every deterministic row the backend sent", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, strategyComparison: sampleStrategyComparison });

    expect(screen.getByTestId("strategy-comparison-headline")).toHaveTextContent(sampleStrategyComparison.headline);
    expect(screen.getByTestId("strategy-row-completed_units")).toHaveTextContent("1,619");
    expect(screen.getByTestId("strategy-row-completed_units")).toHaveTextContent("1,900");
    expect(screen.getByTestId("strategy-row-goal_met")).toHaveTextContent("NO");
    expect(screen.getByTestId("strategy-row-goal_met")).toHaveTextContent("YES");
  });

  it("keeps cost categories in separate rows and never sums them", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, strategyComparison: sampleStrategyComparison });

    expect(screen.getByTestId("strategy-row-cost_CAPEX")).toHaveTextContent("€85,000");
    expect(screen.getByTestId("strategy-row-cost_OPEX_PER_DAY")).toBeInTheDocument();
    expect(screen.queryByText(/total cost/i)).toBeNull();
  });

  it("renders an unknown cost as an em dash, never as zero", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, strategyComparison: sampleStrategyComparison });
    const row = screen.getByTestId("strategy-row-cost_OPEX_PER_DAY");

    // value_b and delta are both null in the fixture. A "0" or "same" here
    // would assert that the two plans cost the same per day — which nobody
    // has established.
    const cells = row.querySelectorAll("td");
    expect(cells[2].textContent).toBe("—");
    expect(cells[3].textContent).toBe("—");
  });

  it("says plainly when two options are not comparable on cost", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, strategyComparison: sampleStrategyComparison });
    expect(screen.getByTestId("not-comparable-on-cost")).toHaveTextContent(
      /lower known capex does not mean cheaper/i,
    );
  });

  it("closes the comparison on request", () => {
    const closeStrategyComparison = vi.fn();
    renderWithContext(
      <StrategyArenaPanel />,
      { ...arenaState, strategyComparison: sampleStrategyComparison },
      { closeStrategyComparison },
    );
    fireEvent.click(screen.getByRole("button", { name: /close comparison/i }));
    expect(closeStrategyComparison).toHaveBeenCalled();
  });
});

describe("StrategyArenaPanel — before / after (section 24)", () => {
  it("puts the verified baseline beside the selected strategy", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const summary = screen.getByTestId("before-after");

    expect(summary).toHaveTextContent("1,105/day");
    expect(summary).toHaveTextContent("gap 795");
    expect(summary).toHaveTextContent("1,900/day");
    expect(summary).toHaveTextContent("gap 0");
  });

  it("lists the actual committed changes", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const changes = screen.getByTestId("before-after-changes");

    expect(changes).toHaveTextContent("+1 shift/day");
    expect(changes).toHaveTextContent("+2 operators");
    expect(changes).not.toHaveTextContent(/no changes committed/i);
  });

  it("names the added machines for an equipment plan", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, selectedStrategyId: strategyA.strategy_id });
    // §2 — the machine is named as the factory names it ("Machine A"), not
    // as its id happens to prettify ("A").
    expect(screen.getByTestId("before-after-changes")).toHaveTextContent("+ Machine A");
  });

  it("disappears when no strategy is open, rather than inventing a subject", () => {
    renderWithContext(<StrategyArenaPanel />, { ...arenaState, selectedStrategyId: null });
    expect(screen.queryByTestId("before-after")).toBeNull();
  });
});

describe("StrategyArenaPanel — no fake arithmetic", () => {
  it("renders only values present in the backend payload", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    const text = screen.getByTestId("strategy-arena").textContent ?? "";

    // 85,000 - 0 = 85,000 is the difference a naive UI would print, and
    // 1,900 - 1,619 = 281 only appears because the backend sent it.
    expect(text).toContain("€85,000");
    expect(text).toContain("281 short");
    expect(text).not.toMatch(/€85,000\s*more/);
  });

  it("shows the arena summary the backend composed", () => {
    renderWithContext(<StrategyArenaPanel />, arenaState);
    expect(screen.getByTestId("strategy-arena-summary")).toHaveTextContent(sampleArena.summary);
  });
});

describe("StrategyAskBox — follow-ups over verified data (section 15)", () => {
  it("asks the backend rather than deriving an answer locally", () => {
    const askAboutOptions = vi.fn();
    renderWithContext(<StrategyAskBox />, arenaState, { askAboutOptions });

    fireEvent.change(screen.getByLabelText(/ask about these options/i), {
      target: { value: "Which plan uses the fewest changes?" },
    });
    // Phase 12 — the control reads "Ask" in sentence case now (it was a
    // full-width button with SHOUTED text). Same button, same action.
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(askAboutOptions).toHaveBeenCalledWith("Which plan uses the fewest changes?");
  });

  it("renders the deterministic answer with its intent", () => {
    renderWithContext(<StrategyAskBox />, { ...arenaState, strategyAnswer: makeStrategyAnswer() });
    expect(screen.getByTestId("strategy-answer")).toHaveTextContent("Plan A uses the fewest changes");
    expect(screen.getByTestId("strategy-answer-intent")).toHaveTextContent(/fewest changes/i);
  });

  it("states that no simulation was needed to answer", () => {
    renderWithContext(<StrategyAskBox />, { ...arenaState, strategyAnswer: makeStrategyAnswer() });
    expect(screen.getByTestId("strategy-answer-provenance")).toHaveTextContent("0 simulations run");
  });

  it("says the engineering is unchanged when a cost was supplied", () => {
    renderWithContext(<StrategyAskBox />, {
      ...arenaState,
      strategyAnswer: makeStrategyAnswer({
        intent: "PROVIDE_COST",
        answer: "Recorded: shift cost = EUR 18,000 (opex per day).",
        requires_repricing: true,
      }),
    });
    expect(screen.getByTestId("strategy-answer-provenance")).toHaveTextContent(/engineering unchanged/i);
  });

  it("swaps in the repriced arena but leaves every verified session alone", () => {
    const before = { ...initialAppState, ...arenaState };
    const repricedArena = {
      ...sampleArena,
      strategies: [strategyA, { ...strategyB, commercially_complete: true }],
    };
    const after = appReducer(before, {
      type: "STRATEGY_ASK_SUCCESS",
      response: {
        answer: makeStrategyAnswer({ intent: "PROVIDE_COST", requires_repricing: true }),
        arena: repricedArena,
        repriced: true,
      },
    });

    expect(after.arena).toBe(repricedArena);
    // Money changed; engineering did not.
    expect(after.strategySessions).toBe(before.strategySessions);
    expect(after.session).toBe(before.session);
    expect(after.selectedStrategyId).toBe(before.selectedStrategyId);
  });

  it("keeps the current arena when the answer required no repricing", () => {
    const before = { ...initialAppState, ...arenaState };
    const after = appReducer(before, {
      type: "STRATEGY_ASK_SUCCESS",
      response: { answer: makeStrategyAnswer(), arena: sampleArena, repriced: false },
    });
    expect(after.arena).toBe(before.arena);
  });
});

describe("one workspace, one owner", () => {
  // A branch and a strategy both supply `session`. Whichever did it last
  // is the one the workspace is showing, so only that one may render as
  // selected — a highlighted card next to another plan's numbers is the
  // silent mismatch this app exists to prevent.
  it("clears the strategy selection when a conversation branch takes over", () => {
    const before = { ...initialAppState, ...arenaState, conversation: makeConversation() };
    const after = appReducer(before, {
      type: "CONVERSATION_SEND_SUCCESS",
      response: conversationTurnResponse(),
    });

    expect(after.selectedBranchId).not.toBeNull();
    expect(after.selectedStrategyId).toBeNull();
  });

  it("clears the branch selection when a strategy takes over", () => {
    const before = { ...initialAppState, ...arenaState, selectedBranchId: "branch-0-aaa" };
    const after = appReducer(before, { type: "SELECT_STRATEGY", strategyId: strategyA.strategy_id });

    expect(after.selectedStrategyId).toBe(strategyA.strategy_id);
    expect(after.selectedBranchId).toBeNull();
  });
});
