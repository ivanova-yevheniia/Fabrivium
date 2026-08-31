import { describe, expect, it } from "vitest";
import { describeKnownCost } from "./capex";

/** G14 — a plan with no capital cost is not a plan with no cost. */

const SHIFT_ONLY = {
  known_capex: 0,
  components: [
    { category: "OPEX_PER_DAY", amount: 18000 },
  ],
  known_by_category: { OPEX_PER_DAY: 18000 },
};

describe("describeKnownCost — every kind of money a plan is known to cost", () => {
  it("shows the operating cost beside a zero CAPEX", () => {
    const shown = describeKnownCost(SHIFT_ONLY, { commerciallyComplete: true });

    expect(shown.amount).toBe("€0");
    expect(shown.otherDimensions).toHaveLength(1);
    expect(shown.otherDimensions[0].label).toBe("Additional OPEX");
    expect(shown.otherDimensions[0].amount).toBe("€18,000/day");
  });

  it("keeps the period attached to a recurring figure", () => {
    // "€18,000" and "€18,000/day" are different claims, and only one of
    // them is true here.
    const shown = describeKnownCost(SHIFT_ONLY, { commerciallyComplete: true });
    expect(shown.otherDimensions[0].amount).toContain("/day");
  });

  it("never lets €0 stand alone when other money is known", () => {
    const shown = describeKnownCost(SHIFT_ONLY, { commerciallyComplete: true });
    // The defect: "€0" as the only figure on a card for an €18,000/day plan.
    expect(shown.otherDimensions.length).toBeGreaterThan(0);
  });

  it("adds nothing across categories", () => {
    const mixed = {
      known_capex: 205000,
      components: [
        { category: "CAPEX", amount: 205000 },
        { category: "OPEX_PER_DAY", amount: 18000 },
      ],
      known_by_category: { CAPEX: 205000, OPEX_PER_DAY: 18000 },
    };
    const shown = describeKnownCost(mixed, { commerciallyComplete: true });

    expect(shown.amount).toBe("€205,000");
    expect(shown.otherDimensions[0].amount).toBe("€18,000/day");
    // 223,000 would be a number with no meaning — a one-off and a per-day
    // figure are not summable, which is why the category exists at all.
    const rendered = [shown.amount, ...shown.otherDimensions.map((d) => d.amount)].join(" ");
    expect(rendered).not.toContain("223,000");
  });

  it("still refuses to price a plan where nothing is known", () => {
    // The original rule, unchanged: an unknown cost is not a zero cost.
    const shown = describeKnownCost(
      { known_capex: 0, components: [{ category: "ONE_TIME_OTHER", amount: null }], known_by_category: {} },
      { commerciallyComplete: false },
    );

    expect(shown.amount).toBe("Nothing priced yet");
    expect(shown.nothingPriced).toBe(true);
    expect(shown.otherDimensions).toHaveLength(0);
  });

  it("marks a partial figure as partial", () => {
    const shown = describeKnownCost(
      { known_capex: 85000, components: [], known_by_category: { CAPEX: 85000 } },
      { commerciallyComplete: false },
    );
    expect(shown.amount).toBe("€85,000");
    expect(shown.qualifier).toBe("+ unpriced");
  });

  it("recovers the dimension from components when the arena predates G14", () => {
    // A project SAVED BEFORE this fix stores an arena with no
    // `known_by_category`. Reopening it must not silently drop a cost the
    // engineer had already established.
    const stored = {
      known_capex: 0,
      components: [{ category: "OPEX_PER_DAY", amount: 18000 }],
    };
    const shown = describeKnownCost(stored, { commerciallyComplete: true });

    expect(shown.otherDimensions).toHaveLength(1);
    expect(shown.otherDimensions[0].amount).toBe("€18,000/day");
  });

  it("an unknown component in a stored arena contributes nothing", () => {
    const stored = {
      known_capex: 0,
      components: [{ category: "ONE_TIME_OTHER", amount: null }],
    };
    const shown = describeKnownCost(stored, { commerciallyComplete: false });

    expect(shown.otherDimensions).toHaveLength(0);
    expect(shown.amount).toBe("Nothing priced yet");
  });
});
