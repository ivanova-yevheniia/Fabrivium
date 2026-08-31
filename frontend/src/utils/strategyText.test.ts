import { describe, expect, it } from "vitest";
import { humanizeStrategyText } from "./strategyText";

/** Phase 11 — no internal identifier may reach judge-facing text. */

const OPTIONS = [
  { strategy_id: "strategy-equipment_expansion", label: "Plan A" },
  { strategy_id: "strategy-shift_expansion", label: "Plan B" },
  { strategy_id: "strategy-process_improvement", label: "Plan C" },
  { strategy_id: "strategy-hybrid", label: "Plan D" },
  { strategy_id: "strategy-hybrid-no-equipment", label: "Plan E" },
];

describe("humanizeStrategyText", () => {
  it("replaces the exact leaked sentence found on Plan D's card", () => {
    expect(humanizeStrategyText("Operationally dominated by: strategy-hybrid-no-equipment.", OPTIONS)).toBe(
      // The id is replaced by the label — the contract this test exists
      // for — and the verdict wording is softened at the same time, which
      // is what a saved arena carrying the old sentence now renders as.
      "Requires more operational changes than Plan E.",
    );
  });

  it("does not corrupt a longer id that has a shorter id as its prefix", () => {
    // "strategy-hybrid" is a prefix of "strategy-hybrid-no-equipment";
    // replacing the short one first would yield "Plan D-no-equipment".
    expect(humanizeStrategyText("strategy-hybrid-no-equipment beats strategy-hybrid", OPTIONS)).toBe(
      "Plan E beats Plan D",
    );
  });

  it("replaces every id in a multi-strategy dominance sentence", () => {
    const text =
      "Operationally dominated by: strategy-equipment_expansion, strategy-hybrid, strategy-hybrid-no-equipment, strategy-shift_expansion.";
    expect(humanizeStrategyText(text, OPTIONS)).toBe(
      "Requires more operational changes than Plan A, Plan D, Plan E, Plan B.",
    );
  });

  it("leaves an unknown id visible rather than silently hiding it", () => {
    expect(humanizeStrategyText("dominated by strategy-unknown-thing", OPTIONS)).toBe(
      "dominated by strategy-unknown-thing",
    );
  });

  it("leaves prose containing no identifier untouched", () => {
    const text = "Falls 281 units/day short; other options reach the target.";
    expect(humanizeStrategyText(text, OPTIONS)).toBe(text);
  });

  it("is safe with an empty option list or empty text", () => {
    expect(humanizeStrategyText("strategy-hybrid", [])).toBe("strategy-hybrid");
    expect(humanizeStrategyText("", OPTIONS)).toBe("");
  });
});
