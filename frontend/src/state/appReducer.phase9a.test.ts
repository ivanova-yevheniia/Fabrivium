import { describe, expect, it } from "vitest";
import { conversationTurnResponse, makeConversation, sampleArena, sampleSessionAccepted, sampleStrategySessions } from "../test/fixtures";
import { appReducer } from "./appReducer";
import { initialAppState } from "./types";

/**
 * Phase 9A — real defect found while building Executive View: switching to
 * a conversation branch (CONVERSATION_SEND_SUCCESS / SELECT_BRANCH) cleared
 * `selectedStrategyId` but left `arena`/`strategySessions` populated from a
 * PREVIOUS, now-unrelated exploration. Engineering View's StrategyArenaPanel
 * is always mounted and reads `arena` directly, so this stale panel already
 * rendered there too — not a Phase 9A regression, a pre-existing gap this
 * phase's audit surfaced. Fixed by clearing arena-derived state exactly
 * where selectedStrategyId already was.
 */
describe("appReducer — Phase 9A stale-arena-after-branch-switch fix", () => {
  it("CONVERSATION_SEND_SUCCESS (new branch) clears the arena and everything derived from it", () => {
    let state = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS",
      response: { parse_result: {} as never, arena: sampleArena, sessions: sampleStrategySessions, provenance: {} as never },
    });
    expect(state.arena).not.toBeNull();
    expect(Object.keys(state.strategySessions).length).toBeGreaterThan(0);

    state = appReducer(state, { type: "CONVERSATION_SEND_SUCCESS", response: conversationTurnResponse() });

    expect(state.arena).toBeNull();
    expect(state.strategySessions).toEqual({});
    expect(state.strategyComparison).toBeNull();
    expect(state.comparePickId).toBeNull();
    expect(state.strategyAnswer).toBeNull();
    expect(state.selectedStrategyId).toBeNull();
    // The new branch's own session is what's actually shown now.
    expect(state.session).toBe(sampleSessionAccepted);
  });

  it("SELECT_BRANCH clears the arena and everything derived from it", () => {
    let state = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS",
      response: { parse_result: {} as never, arena: sampleArena, sessions: sampleStrategySessions, provenance: {} as never },
    });
    state = {
      ...state,
      conversation: makeConversation(),
      branchResults: { "branch-0-aaa": { session: sampleSessionAccepted, explanation: null } },
    };
    expect(state.arena).not.toBeNull();

    state = appReducer(state, { type: "SELECT_BRANCH", branchId: "branch-0-aaa" });

    expect(state.arena).toBeNull();
    expect(state.strategySessions).toEqual({});
    expect(state.selectedStrategyId).toBeNull();
    expect(state.session).toBe(sampleSessionAccepted);
  });

  it("a CONVERSATION_SEND_SUCCESS turn with NO branch (clarification/no-op) leaves the arena untouched", () => {
    let state = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS",
      response: { parse_result: {} as never, arena: sampleArena, sessions: sampleStrategySessions, provenance: {} as never },
    });
    const noBranchResponse = conversationTurnResponse();
    const clarificationResponse = {
      ...noBranchResponse,
      turn: { ...noBranchResponse.turn, branch_id: null, status: "CLARIFICATION_REQUIRED" as const },
      planning_session: null,
    };
    state = appReducer(state, { type: "CONVERSATION_SEND_SUCCESS", response: clarificationResponse });
    // Nothing about the verified engineering state changed, so the arena
    // that was actually on screen must not be silently discarded either.
    expect(state.arena).not.toBeNull();
  });
});

/**
 * Pre-freeze — the exploration turn history that makes constraint
 * precedence possible across refinements. Sending only the most recent
 * prior turn would quietly drop the first turn's constraints on a third
 * refinement, and leaving the history behind on Reset would let a fresh
 * exploration inherit constraints the user just cleared.
 */
describe("exploration turn history", () => {
  const response = {
    arena: sampleArena,
    sessions: sampleStrategySessions,
    parse_result: {} as never,
    provenance: {} as never,
  };

  it("records the turn that produced the result, after its priors", () => {
    const after = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS",
      response,
      request: "Do not buy any new machines.",
      priorRequests: ["We need 1900 units/day."],
    });
    expect(after.exploreRequests).toEqual(["We need 1900 units/day.", "Do not buy any new machines."]);
  });

  it("accumulates across successive refinements", () => {
    const first = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS", response, request: "A", priorRequests: [],
    });
    const second = appReducer(first, {
      type: "EXPLORE_SUCCESS", response, request: "B", priorRequests: first.exploreRequests,
    });
    expect(second.exploreRequests).toEqual(["A", "B"]);
  });

  it("clears the history on Reset, so a new exploration starts clean", () => {
    const withHistory = appReducer(initialAppState, {
      type: "EXPLORE_SUCCESS", response, request: "A", priorRequests: ["B"],
    });
    expect(withHistory.exploreRequests).not.toHaveLength(0);
    expect(appReducer(withHistory, { type: "RESET_SESSION" }).exploreRequests).toEqual([]);
  });
});
