import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RequirementsParseResult } from "../../api/types";
import { sampleArena, sampleFactory } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { RefineBar } from "./RefineBar";

/**
 * Phase 11 §8 — refining an EXPLORATION must stay an exploration, and
 * earlier constraints must survive the turn.
 *
 * Reproduced in the browser before the fix: `/strategies/explore` never
 * creates `state.conversation`, so `sendMessage` fell through to
 * `startConversation` and began a brand-new conversation carrying only the
 * refinement sentence. "We need 1900 units/day…" followed by "That's too
 * expensive. Keep it below EUR 150k." silently dropped the 1,900 target,
 * replaced the five-strategy arena with a single plan, and displayed
 * "1,200 / 1,200 units/day" — the factory's own default demand — which
 * reads as success against a goal the user never set.
 */

const ORIGINAL = "We need 1900 units/day. Avoid buying new machines if possible.";
const FOLLOW_UP = "That's too expensive. Keep it below €150k.";

const parseResult = {
  raw_user_request: ORIGINAL,
  parsed_requirements: { target_units_per_day: 1900 },
  warnings: [],
  parser_type: "DETERMINISTIC_FALLBACK",
  structured_output_valid: true,
} as unknown as RequirementsParseResult;

function refine(text: string, stateOverrides = {}, actionOverrides = {}) {
  const rendered = renderWithContext(<RefineBar />, { factory: sampleFactory, ...stateOverrides }, actionOverrides);
  fireEvent.change(screen.getByTestId("refine-bar-input"), { target: { value: text } });
  fireEvent.click(screen.getByTestId("refine-bar-submit"));
  return rendered;
}

describe("RefineBar — constraint continuity after an exploration", () => {
  it("re-runs the EXPLORATION rather than starting a conversation", () => {
    const exploreOptions = vi.fn(async () => {});
    const sendMessage = vi.fn(async () => {});
    refine(FOLLOW_UP, { arena: sampleArena, parseResult, exploreRequests: [ORIGINAL] }, { exploreOptions, sendMessage });

    expect(exploreOptions).toHaveBeenCalledTimes(1);
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("sends the earlier turn SEPARATELY, never joined into one string", () => {
    // Joining them is what let the first figure mentioned win and let a
    // softening word in one turn downgrade a hard constraint stated in
    // another; precedence is resolved structurally server-side instead.
    const exploreOptions = vi.fn(async (_request: string, _prior?: string[]) => {});
    refine(FOLLOW_UP, { arena: sampleArena, parseResult, exploreRequests: [ORIGINAL] }, { exploreOptions });

    const [current, prior] = exploreOptions.mock.calls[0];
    expect(current).toBe(FOLLOW_UP);
    expect(prior).toEqual([ORIGINAL]);
    expect(current).not.toContain("1900 units/day");
  });

  it("carries EVERY earlier turn, not just the most recent one", () => {
    const exploreOptions = vi.fn(async (_request: string, _prior?: string[]) => {});
    const turns = [ORIGINAL, "Do not buy any new machines."];
    refine(FOLLOW_UP, { arena: sampleArena, parseResult, exploreRequests: turns }, { exploreOptions });

    expect(exploreOptions.mock.calls[0][1]).toEqual(turns);
  });

  it("falls back to the conversational path when there is no arena to refine", () => {
    const exploreOptions = vi.fn(async () => {});
    const sendMessage = vi.fn(async () => {});
    refine("Do it without buying another machine.", {}, { exploreOptions, sendMessage });

    expect(sendMessage).toHaveBeenCalledWith("Do it without buying another machine.");
    expect(exploreOptions).not.toHaveBeenCalled();
  });

  it("uses the conversational path when an arena exists but no turn history is known", () => {
    // Nothing to accumulate onto — better to send the message as-is than
    // to invent a request the user never made.
    const exploreOptions = vi.fn(async () => {});
    const sendMessage = vi.fn(async () => {});
    refine("cheaper please", { arena: sampleArena, exploreRequests: [] }, { exploreOptions, sendMessage });

    expect(sendMessage).toHaveBeenCalledWith("cheaper please");
    expect(exploreOptions).not.toHaveBeenCalled();
  });

  it("does nothing on an empty refinement", () => {
    const exploreOptions = vi.fn(async () => {});
    const sendMessage = vi.fn(async () => {});
    renderWithContext(<RefineBar />, { factory: sampleFactory, arena: sampleArena, parseResult, exploreRequests: [ORIGINAL] }, { exploreOptions, sendMessage });
    fireEvent.click(screen.getByTestId("refine-bar-submit"));

    expect(exploreOptions).not.toHaveBeenCalled();
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
