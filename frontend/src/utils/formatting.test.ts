import { describe, expect, it } from "vitest";
import { formatCurrency, formatNumber, formatPercent, friendlyMachineName } from "./formatting";

describe("formatting helpers", () => {
  // "No fake KPI calculations in frontend" (Phase 6A section 13): every
  // formatter must be the identity transform on its numeric input — it
  // may only change presentation (rounding for display, adding a symbol),
  // never derive a NEW value (no arithmetic between two different inputs).

  it("formatNumber never changes the underlying magnitude beyond display rounding", () => {
    expect(formatNumber(1900)).toContain("1,900");
    expect(formatNumber(0)).toBe("0");
  });

  it("formatCurrency only adds a currency symbol/grouping, never recomputes the amount", () => {
    expect(formatCurrency(85_000)).toBe("€85,000");
    expect(formatCurrency(0)).toBe("€0");
  });

  it("formatPercent is a straight *100 display transform of the given fraction, not an independent computation", () => {
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(1)).toBe("100.0%");
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("friendlyMachineName is a pure string transform of an existing machine_id, never invents a new id", () => {
    expect(friendlyMachineName("m-screwdriving")).toBe("Screwdriving");
    expect(friendlyMachineName("m-parallel-assembly")).toBe("Parallel Assembly");
    expect(friendlyMachineName(null)).toBe("—");
    expect(friendlyMachineName(undefined)).toBe("—");
  });
});
