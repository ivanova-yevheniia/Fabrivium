import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  makeConversation,
  makeTurn,
  makeTwoBranchConversation,
  sampleBranchComparison,
  sampleFactory,
  sampleSessionAccepted,
} from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { ActiveConstraints } from "./ActiveConstraints";
import { BranchComparisonCard } from "./BranchComparisonCard";
import { BranchSelector } from "./BranchSelector";
import { ConversationPanel } from "./ConversationPanel";

/** Phase 7C frontend coverage (section 23, items 34-40). */

describe("ConversationPanel — turn rendering (34)", () => {
  it("shows the empty state before any message has been sent", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory });
    expect(screen.getByTestId("conversation-log")).toHaveTextContent(/describe what you need/i);
  });

  it("renders the user message and Fabrivium's reply as separate cards", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation: makeConversation() });
    expect(screen.getByTestId("turn-user-0")).toHaveTextContent("We need 700 units/day.");
    expect(screen.getByTestId("turn-reply-0")).toBeInTheDocument();
    expect(screen.getByTestId("turn-status-0")).toHaveTextContent(/plan updated/i);
  });

  it("renders the deterministic change list, not model prose", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation: makeConversation() });
    const changes = screen.getByTestId("turn-changes-0");
    expect(changes).toHaveTextContent("Objective: MEET_DEMAND");
    expect(changes).toHaveTextContent("Target: 700/day");
  });

  it("labels each turn's interpretation source", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation: makeConversation() });
    expect(screen.getByTestId("turn-provenance-0")).toHaveTextContent(/deterministic parsing/i);
  });

  it("names the model when a turn really was interpreted by one", () => {
    const conversation = makeConversation({
      turns: [
        makeTurn({
          provenance: {
            update_source: "LLM",
            planning_source: "LLM",
            explanation_source: "LLM",
            fallback_used: false,
            provider_name: "watsonx",
            model_name: "ibm/granite-4-h-small",
            prompt_tokens: 800,
            completion_tokens: 120,
            total_tokens: 920,
          },
        }),
      ],
    });
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation });
    const provenance = screen.getByTestId("turn-provenance-0");
    expect(provenance).toHaveTextContent("ibm/granite-4-h-small");
    expect(provenance).toHaveTextContent("920 tokens");
  });

  it("sends the typed message and clears the input", () => {
    const { contextValue } = renderWithContext(<ConversationPanel />, { factory: sampleFactory });
    const input = screen.getByLabelText(/what do you want to change/i);
    fireEvent.change(input, { target: { value: "Keep it below €150k." } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));
    expect(contextValue.sendMessage).toHaveBeenCalledWith("Keep it below €150k.");
    expect(input).toHaveValue("");
  });

  it("cannot send with no factory loaded or an empty message", () => {
    renderWithContext(<ConversationPanel />, { factory: null });
    expect(screen.getByRole("button", { name: /^send$/i })).toBeDisabled();
  });
});

describe("ConversationPanel — clarification card (38)", () => {
  const clarificationConversation = makeConversation({
    turns: [
      makeTurn(),
      makeTurn({
        turn_index: 1,
        raw_user_message: "Make it better.",
        status: "CLARIFICATION_REQUIRED",
        changes: [],
        branch_id: null,
        explanation: null,
        clarification: {
          question: "Should I optimise for lower CAPEX, higher throughput, lower WIP, or shorter flow time?",
          ambiguous_fields: ["objective"],
          safe_options: ["Lower CAPEX", "Higher throughput", "Lower WIP", "Shorter flow time"],
        },
      }),
    ],
  });

  it("renders the question and its concrete options", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation: clarificationConversation });
    const card = screen.getByTestId("turn-clarification-1");
    expect(card).toHaveTextContent(/should i optimise for/i);
    expect(card).toHaveTextContent("Higher throughput");
  });

  it("marks the turn as needing clarification and produces no branch link", () => {
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation: clarificationConversation });
    expect(screen.getByTestId("turn-status-1")).toHaveTextContent(/needs clarification/i);
    expect(screen.queryByTestId("turn-branch-link-1")).not.toBeInTheDocument();
  });

  it("surfaces an errored turn's reason instead of pretending it applied", () => {
    const conversation = makeConversation({
      turns: [
        makeTurn({
          turn_index: 0,
          status: "PROVIDER_UNAVAILABLE",
          changes: [],
          branch_id: null,
          errors: ["The request could not be interpreted right now, so nothing was changed."],
        }),
      ],
      branches: [],
    });
    renderWithContext(<ConversationPanel />, { factory: sampleFactory, conversation });
    expect(screen.getByTestId("turn-status-0")).toHaveTextContent(/could not interpret/i);
    expect(screen.getByTestId("turn-errors-0")).toHaveTextContent(/nothing was changed/i);
  });
});

describe("ActiveConstraints (35)", () => {
  it("renders nothing before any constraints exist", () => {
    renderWithContext(<ActiveConstraints />, { factory: sampleFactory });
    expect(screen.queryByTestId("active-constraints")).not.toBeInTheDocument();
  });

  it("shows every active constraint as a chip", () => {
    const conversation = makeConversation({
      active_requirements: {
        objective: "MEET_DEMAND",
        target_units_per_day: 1900,
        max_capex: 150_000,
        max_additional_machines: 2,
        max_additional_operators: null,
        max_floor_area: null,
        allowed_action_types: null,
        forbidden_machine_ids: ["m-packaging"],
        preserve_existing_layout: true,
        notes: [],
        confidence: 1,
        parse_warnings: [],
        prefer_no_new_machines: false,
        prefer_low_known_capex: false,
        prefer_few_changes: false,
        allowed_strategy_families: null,
      },
    });
    renderWithContext(<ActiveConstraints />, { factory: sampleFactory, conversation });
    const chips = screen.getByTestId("active-constraints");
    expect(chips).toHaveTextContent("MEET DEMAND");
    expect(chips).toHaveTextContent("Target 1,900/day");
    expect(chips).toHaveTextContent("CAPEX ≤ €150,000");
    expect(chips).toHaveTextContent("≤ 2 new machines");
    expect(chips).toHaveTextContent("Packaging locked");
    expect(chips).toHaveTextContent("Preserve layout");
  });

  it("omits a constraint that is not set rather than showing a placeholder", () => {
    renderWithContext(<ActiveConstraints />, { factory: sampleFactory, conversation: makeConversation() });
    const chips = screen.getByTestId("active-constraints");
    expect(chips).toHaveTextContent("Target 700/day");
    expect(chips).not.toHaveTextContent("CAPEX");
    expect(chips).not.toHaveTextContent("locked");
  });
});

describe("BranchSelector (36, 37)", () => {
  const conversation = makeTwoBranchConversation();

  it("lists every option with its verified outcome and cost", () => {
    renderWithContext(<BranchSelector />, { factory: sampleFactory, conversation });
    const selector = screen.getByTestId("branch-selector");
    expect(selector).toHaveTextContent("Plan A");
    expect(selector).toHaveTextContent("€205,000");
    expect(selector).toHaveTextContent("Plan B");
    expect(selector).toHaveTextContent("€85,000");
  });

  it("marks whether each option met the target", () => {
    renderWithContext(<BranchSelector />, { factory: sampleFactory, conversation });
    expect(within(screen.getByTestId("branch-card-branch-0-aaa")).getByText(/target met/i)).toBeInTheDocument();
    expect(within(screen.getByTestId("branch-card-branch-1-bbb")).getByText(/target unmet/i)).toBeInTheDocument();
  });

  it("highlights the branch currently shown in the workspace", () => {
    renderWithContext(<BranchSelector />, {
      factory: sampleFactory, conversation, selectedBranchId: "branch-0-aaa",
    });
    expect(screen.getByTestId("branch-card-branch-0-aaa")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("branch-card-branch-1-bbb")).toHaveAttribute("data-selected", "false");
  });

  it("selecting a branch asks the app to switch to it", () => {
    const { contextValue } = renderWithContext(<BranchSelector />, {
      factory: sampleFactory, conversation, selectedBranchId: "branch-0-aaa",
    });
    fireEvent.click(within(screen.getByTestId("branch-card-branch-1-bbb")).getByRole("button", { name: /plan b/i }));
    expect(contextValue.selectBranch).toHaveBeenCalledWith("branch-1-bbb");
  });

  it("offers Compare only against a branch other than the one shown", () => {
    const { contextValue } = renderWithContext(<BranchSelector />, {
      factory: sampleFactory, conversation, selectedBranchId: "branch-0-aaa",
    });
    expect(within(screen.getByTestId("branch-card-branch-0-aaa")).queryByRole("button", { name: /compare/i })).toBeNull();
    fireEvent.click(within(screen.getByTestId("branch-card-branch-1-bbb")).getByRole("button", { name: /compare/i }));
    expect(contextValue.compareWithBranch).toHaveBeenCalledWith("branch-1-bbb");
  });

  it("shows a branch's own verified summary rather than a derived one", () => {
    renderWithContext(<BranchSelector />, { factory: sampleFactory, conversation });
    expect(screen.getByTestId("branch-card-branch-1-bbb")).toHaveTextContent(
      "Target not reached: 420/500/day (80 short) for EUR 85,000.",
    );
  });
});

describe("branch switching drives the digital twin (37)", () => {
  it("SELECT_BRANCH swaps the session the workspace, KPI panel and timeline read", async () => {
    const { appReducer } = await import("../../state/appReducer");
    const { initialAppState } = await import("../../state/types");

    const other = { ...sampleSessionAccepted, session_id: "other", cumulative_known_capex: 85_000 };
    const state = {
      ...initialAppState,
      conversation: makeTwoBranchConversation(),
      selectedBranchId: "branch-0-aaa",
      session: sampleSessionAccepted,
      selectedIteration: 0 as const,
      branchResults: {
        "branch-0-aaa": { session: sampleSessionAccepted, explanation: null },
        "branch-1-bbb": { session: other, explanation: null },
      },
    };

    const next = appReducer(state, { type: "SELECT_BRANCH", branchId: "branch-1-bbb" });
    expect(next.session).toBe(other);
    expect(next.selectedBranchId).toBe("branch-1-bbb");
    // Always lands on the branch's verified end state.
    expect(next.selectedIteration).toBe("final");
  });

  it("never shows a branch whose verified result the client does not hold", async () => {
    const { appReducer } = await import("../../state/appReducer");
    const { initialAppState } = await import("../../state/types");

    const state = { ...initialAppState, session: sampleSessionAccepted, selectedBranchId: "branch-0-aaa" };
    const next = appReducer(state, { type: "SELECT_BRANCH", branchId: "branch-unknown" });
    expect(next).toBe(state);
  });
});

describe("BranchComparisonCard (39, 40)", () => {
  it("renders nothing until a comparison has been requested", () => {
    renderWithContext(<BranchComparisonCard />, { factory: sampleFactory });
    expect(screen.queryByTestId("branch-comparison")).not.toBeInTheDocument();
  });

  it("shows the backend's deterministic headline verbatim", () => {
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory, branchComparison: sampleBranchComparison,
    });
    expect(screen.getByTestId("comparison-headline")).toHaveTextContent(
      "Plan A reaches the target and costs EUR 120,000 more; Plan B does not.",
    );
  });

  it("renders both values and the delta exactly as the backend computed them", () => {
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory, branchComparison: sampleBranchComparison,
    });
    const row = screen.getByTestId("comparison-row-cumulative_known_capex");
    expect(row).toHaveTextContent("€205,000");
    expect(row).toHaveTextContent("€85,000");
    expect(row).toHaveTextContent("−€120,000");
  });

  it("renders an unknown delta as a dash, never as zero", () => {
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory, branchComparison: sampleBranchComparison,
    });
    const row = screen.getByTestId("comparison-row-goal_reached");
    expect(row).toHaveTextContent("YES");
    expect(row).toHaveTextContent("NO");
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent("0");
  });

  it("reports constraint differences separately from outcomes", () => {
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory, branchComparison: sampleBranchComparison,
    });
    expect(screen.getByTestId("branch-comparison")).toHaveTextContent(
      "Budget: Plan A EUR 220,000, Plan B EUR 150,000",
    );
  });

  it("states what could not be compared instead of omitting it", () => {
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory,
      branchComparison: {
        ...sampleBranchComparison,
        unknown_information: ["Remaining CAPEX is not comparable: at least one option had no budget ceiling."],
      },
    });
    expect(screen.getByTestId("branch-comparison")).toHaveTextContent(/not comparable/i);
  });

  it("renders the backend's delta rather than recomputing one from the two values", () => {
    // A deliberately inconsistent payload: if the component did its own
    // arithmetic it would show −80, and this test would catch it. The
    // backend is the only source of engineering numbers, so 999 must win.
    renderWithContext(<BranchComparisonCard />, {
      factory: sampleFactory,
      branchComparison: {
        ...sampleBranchComparison,
        metrics: [
          {
            metric: "completed_units", label: "Completed units",
            value_a: 500, value_b: 420, delta: 999, unit: "units/day",
          },
        ],
      },
    });
    const row = screen.getByTestId("comparison-row-completed_units");
    expect(row).toHaveTextContent("+999");
    expect(row).not.toHaveTextContent("80");
  });
});

describe("ActiveConstraints — Phase 8A levers", () => {
  function withRequirements(overrides: Record<string, unknown>) {
    return makeConversation({
      active_requirements: {
        objective: "MEET_DEMAND",
        target_units_per_day: 1900,
        max_capex: null,
        max_additional_machines: null,
        max_additional_operators: null,
        max_floor_area: null,
        allowed_action_types: null,
        forbidden_machine_ids: [],
        preserve_existing_layout: false,
        notes: [],
        confidence: 1,
        parse_warnings: [],
        prefer_no_new_machines: false,
        prefer_low_known_capex: false,
        prefer_few_changes: false,
        allowed_strategy_families: null,
        ...overrides,
      },
    });
  }

  it("shows a lever restriction, so 'shifts only' is never hidden in the transcript", () => {
    renderWithContext(<ActiveConstraints />, {
      factory: sampleFactory,
      conversation: withRequirements({ allowed_action_types: ["CHANGE_SHIFT_CONFIGURATION"] }),
    });
    expect(screen.getByTestId("active-constraints")).toHaveTextContent("Only: shifts");
  });

  it("names several levers readably rather than as raw enums", () => {
    renderWithContext(<ActiveConstraints />, {
      factory: sampleFactory,
      conversation: withRequirements({
        allowed_action_types: ["CHANGE_OPERATOR_CAPACITY", "CHANGE_BUFFER_CAPACITY"],
      }),
    });
    const chips = screen.getByTestId("active-constraints");
    expect(chips).toHaveTextContent("Only: operators, buffers");
    expect(chips).not.toHaveTextContent("CHANGE_OPERATOR_CAPACITY");
  });

  it("falls back to the raw action type rather than dropping an unknown lever", () => {
    renderWithContext(<ActiveConstraints />, {
      factory: sampleFactory,
      conversation: withRequirements({ allowed_action_types: ["SOME_FUTURE_ACTION"] }),
    });
    expect(screen.getByTestId("active-constraints")).toHaveTextContent("SOME_FUTURE_ACTION");
  });

  it("shows a hiring cap when one is set", () => {
    renderWithContext(<ActiveConstraints />, {
      factory: sampleFactory,
      conversation: withRequirements({ max_additional_operators: 2 }),
    });
    expect(screen.getByTestId("active-constraints")).toHaveTextContent("≤ 2 new operators");
  });

  it("shows no lever chip when planning is unrestricted", () => {
    renderWithContext(<ActiveConstraints />, { factory: sampleFactory, conversation: withRequirements({}) });
    expect(screen.getByTestId("active-constraints")).not.toHaveTextContent("Only:");
  });
});
