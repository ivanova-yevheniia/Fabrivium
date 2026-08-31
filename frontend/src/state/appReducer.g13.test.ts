import { describe, expect, it } from "vitest";
import { makeStrategyAnswer, sampleArena, sampleStrategySessions } from "../test/fixtures";
import { appReducer, mergeEstablishedCosts } from "./appReducer";
import { initialAppState } from "./types";
import type { AppState } from "./types";
import type { StrategyAskResponse, UserCostInput } from "../api/types";

/** G13 — established engineering and commercial inputs survive refinement. */

const SHIFT_18K: UserCostInput = {
  gap_type: "SHIFT_COST",
  amount: 18000,
  category: "OPEX_PER_DAY",
  note: "An extra shift costs EUR 18k/day.",
};

const OPERATORS_90K: UserCostInput = {
  gap_type: "OPERATOR_COST",
  amount: 90000,
  category: "OPEX_PER_YEAR",
  note: "",
};

function askResponse(overrides: Partial<StrategyAskResponse> = {}): StrategyAskResponse {
  return {
    answer: makeStrategyAnswer({
      intent: "PROVIDE_COST",
      answer: "Recorded: the cost of an additional shift = EUR 18,000 (operating cost per day).",
      cost_inputs: [SHIFT_18K],
      requires_repricing: true,
    }),
    arena: sampleArena,
    repriced: true,
    ...overrides,
  };
}

/** The state the engineer was in: options on screen, sessions loaded. */
function explored(): AppState {
  return appReducer(initialAppState, {
    type: "EXPLORE_SUCCESS",
    response: {
      parse_result: {} as never,
      arena: sampleArena,
      sessions: sampleStrategySessions,
      provenance: {} as never,
    },
    request: "We need 1,900 units per day.",
    priorRequests: [],
  });
}

describe("mergeEstablishedCosts", () => {
  it("records a cost that has not been stated before", () => {
    expect(mergeEstablishedCosts([], [SHIFT_18K])).toEqual([SHIFT_18K]);
  });

  it("keeps one entry per gap type, with the newer figure winning", () => {
    const revised: UserCostInput = { ...SHIFT_18K, amount: 21000 };
    const merged = mergeEstablishedCosts([SHIFT_18K], [revised]);

    // Two sentences about one cost are one fact. Accumulating them would
    // leave the project holding both 18k and 21k with nothing to say which
    // is current.
    expect(merged).toEqual([revised]);
  });

  it("keeps the order costs were first established in", () => {
    const merged = mergeEstablishedCosts(
      [SHIFT_18K, OPERATORS_90K],
      [{ ...SHIFT_18K, amount: 21000 }],
    );
    expect(merged.map((c) => c.gap_type)).toEqual(["SHIFT_COST", "OPERATOR_COST"]);
  });

  it("costs about different things sit beside each other", () => {
    const merged = mergeEstablishedCosts([SHIFT_18K], [OPERATORS_90K]);
    expect(merged).toEqual([SHIFT_18K, OPERATORS_90K]);
  });

  it("an answer that supplied nothing changes nothing", () => {
    const existing = [SHIFT_18K];
    expect(mergeEstablishedCosts(existing, [])).toBe(existing);
    expect(mergeEstablishedCosts(existing, undefined)).toBe(existing);
  });
});

describe("G13 — a stated cost becomes a project fact", () => {
  it("STRATEGY_ASK_SUCCESS records what the engineer supplied", () => {
    const state = appReducer(explored(), { type: "STRATEGY_ASK_SUCCESS", response: askResponse() });

    expect(state.establishedCosts).toEqual([SHIFT_18K]);
    // Recording the input does not disturb the answer or the repriced
    // arena — money was re-derived, engineering was not.
    expect(state.strategyAnswer?.intent).toBe("PROVIDE_COST");
    expect(state.arena).toBe(sampleArena);
  });

  it("records the cost even when the arena could not be repriced", () => {
    // Repricing rebuilds each profile from its verified session, and a
    // reopened project deliberately restores none of them — so the backend
    // honestly leaves the arena alone. The statement was still made, and
    // must apply to the next exploration.
    const state = appReducer(explored(), {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse({ repriced: false }),
    });

    expect(state.establishedCosts).toEqual([SHIFT_18K]);
  });

  it("a question that states no cost establishes nothing", () => {
    const state = appReducer(explored(), {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse({
        answer: makeStrategyAnswer({ intent: "FEWEST_CHANGES" }),
        repriced: false,
      }),
    });

    expect(state.establishedCosts).toEqual([]);
  });

  it("stores the parser's own object, never a figure read back off the screen", () => {
    const state = appReducer(explored(), { type: "STRATEGY_ASK_SUCCESS", response: askResponse() });

    // Provenance travels in these fields. `category` is what makes 18,000 an
    // operating cost per day rather than a capital purchase, and `gap_type`
    // is what makes it the cost of a SHIFT rather than of anything else that
    // happens to cost 18,000. Reconstructing either from the rendered
    // sentence would be inventing an attribution.
    expect(state.establishedCosts[0]).toBe(SHIFT_18K);
    expect(state.establishedCosts[0].category).toBe("OPEX_PER_DAY");
    expect(state.establishedCosts[0].gap_type).toBe("SHIFT_COST");
  });
});

describe("G13 — refinement discards results, not inputs", () => {
  it("EXPLORE_SUCCESS keeps the established cost while replacing the arena", () => {
    const priced = appReducer(explored(), {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse(),
    });
    expect(priced.establishedCosts).toEqual([SHIFT_18K]);

    const rebuiltArena = { ...sampleArena, summary: "1 verified option after the constraint." };
    const refined = appReducer(priced, {
      type: "EXPLORE_SUCCESS",
      response: {
        parse_result: {} as never,
        arena: rebuiltArena as never,
        sessions: sampleStrategySessions,
        provenance: {} as never,
      },
      request: "Do it without buying another machine.",
      priorRequests: ["We need 1,900 units per day."],
    });

    // The whole defect, in one assertion.
    expect(refined.establishedCosts).toEqual([SHIFT_18K]);

    // And the derived half genuinely was rebuilt — this is not a test that
    // passes because the refinement did nothing.
    expect(refined.arena).toBe(rebuiltArena);
    expect(refined.refinementTrace?.request).toBe("Do it without buying another machine.");
    expect(refined.exploreRequests).toEqual([
      "We need 1,900 units per day.",
      "Do it without buying another machine.",
    ]);
  });

  it("the stale answer is invalidated even though the fact behind it is not", () => {
    // F. The sentence "Plan B is the only fully priced option that reaches
    // the target" was about a set of plans that no longer exists, so it
    // goes. The EUR 18,000 it was computed from was never about that set.
    const priced = appReducer(explored(), {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse(),
    });
    expect(priced.strategyAnswer).not.toBeNull();

    const refined = appReducer(priced, {
      type: "EXPLORE_SUCCESS",
      response: {
        parse_result: {} as never,
        arena: sampleArena,
        sessions: sampleStrategySessions,
        provenance: {} as never,
      },
      request: "Do it without buying another machine.",
      priorRequests: ["We need 1,900 units per day."],
    });

    expect(refined.strategyAnswer).toBeNull();
    expect(refined.strategyComparison).toBeNull();
    expect(refined.establishedCosts).toEqual([SHIFT_18K]);
  });

  it("the engineering inputs a refinement never asked about are left alone", () => {
    // G. The concept draft holds the cycle times, capacity and operator
    // demand the engineer accepted station by station. A refinement asks a
    // new question of those values; it does not restate them, and a rebuild
    // that quietly reset one would be the same defect wearing different
    // clothes.
    const withConcept: AppState = {
      ...explored(),
      concept: {
        ...initialAppState.concept,
        draft: { name: "CEC-120 line", stations: [{ name: "Cable connection", cycle_time_s: 38.5 }] } as never,
      },
      product: { ...initialAppState.product, requirementsText: "1,900 units per day across 2 shifts of 8 hours." },
    };
    const priced = appReducer(withConcept, { type: "STRATEGY_ASK_SUCCESS", response: askResponse() });

    const refined = appReducer(priced, {
      type: "EXPLORE_SUCCESS",
      response: {
        parse_result: {} as never,
        arena: sampleArena,
        sessions: sampleStrategySessions,
        provenance: {} as never,
      },
      request: "Do it without buying another machine.",
      priorRequests: ["We need 1,900 units per day."],
    });

    expect(refined.concept.draft).toEqual(withConcept.concept.draft);
    expect(refined.product.requirementsText).toBe(withConcept.product.requirementsText);
    expect(refined.establishedCosts).toEqual([SHIFT_18K]);
  });

  it("several established costs all survive a refinement", () => {
    // G, generalised: the fix must not be a special case for shift cost.
    let state = appReducer(explored(), { type: "STRATEGY_ASK_SUCCESS", response: askResponse() });
    state = appReducer(state, {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse({
        answer: makeStrategyAnswer({
          intent: "PROVIDE_COST",
          cost_inputs: [OPERATORS_90K],
          requires_repricing: true,
        }),
      }),
    });
    expect(state.establishedCosts).toEqual([SHIFT_18K, OPERATORS_90K]);

    const refined = appReducer(state, {
      type: "EXPLORE_SUCCESS",
      response: {
        parse_result: {} as never,
        arena: sampleArena,
        sessions: sampleStrategySessions,
        provenance: {} as never,
      },
      request: "Do it without buying another machine.",
      priorRequests: ["We need 1,900 units per day."],
    });

    expect(refined.establishedCosts).toEqual([SHIFT_18K, OPERATORS_90K]);
  });
});

describe("G13 — established facts belong to one project", () => {
  it("closing the project leaves nothing established behind it", () => {
    const priced = appReducer(explored(), {
      type: "STRATEGY_ASK_SUCCESS",
      response: askResponse(),
    });

    const closed = appReducer(priced, { type: "PROJECT_CLOSED" });
    expect(closed.establishedCosts).toEqual([]);
  });
});
