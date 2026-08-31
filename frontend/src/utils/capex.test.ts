import { describe, expect, it } from "vitest";
import { describeKnownCapex } from "./capex";

describe("known CAPEX presentation (audit §4)", () => {
  // The rule being pinned: an unknown cost must never render as zero.
  // "UNKNOWN must never silently become zero" is a standing constraint, and
  // money is where it does the most damage.

  it("shows a real figure when everything in the plan is priced", () => {
    const shown = describeKnownCapex(85_000, { commerciallyComplete: true });
    expect(shown.amount).toBe("€85,000");
    expect(shown.qualifier).toBeNull();
    expect(shown.nothingPriced).toBe(false);
  });

  it("marks a figure as partial when some of the plan is unpriced", () => {
    const shown = describeKnownCapex(85_000, { commerciallyComplete: false });
    expect(shown.amount).toBe("€85,000");
    expect(shown.qualifier).toBe("+ unpriced");
  });

  it("never renders an unpriced plan as €0", () => {
    // The extra-shift plan: buys nothing, so the KNOWN sum is 0 — while its
    // real cost is unknown, not zero.
    const shown = describeKnownCapex(0, { commerciallyComplete: false });
    expect(shown.amount).not.toContain("0");
    expect(shown.amount).toBe("Nothing priced yet");
    expect(shown.nothingPriced).toBe(true);
  });

  it("still allows a genuine zero when the plan is fully priced", () => {
    // The one case where zero is an answer rather than an absence.
    const shown = describeKnownCapex(0, { commerciallyComplete: true });
    expect(shown.amount).toBe("€0");
    expect(shown.nothingPriced).toBe(false);
  });
});
