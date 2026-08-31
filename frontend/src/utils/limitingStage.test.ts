import { describe, expect, it } from "vitest";
import { isAlarmBottleneck, limitingStageLabel } from "./limitingStage";

describe("limitingStage — Phase 9A section 8 terminology decision", () => {
  it("is an alarm bottleneck when demand was not met", () => {
    expect(isAlarmBottleneck({ demand_met: false })).toBe(true);
    expect(limitingStageLabel({ demand_met: false })).toBe("Bottleneck");
  });

  it("is NOT an alarm bottleneck when the target was reached — same stage, different meaning", () => {
    expect(isAlarmBottleneck({ demand_met: true })).toBe(false);
    expect(limitingStageLabel({ demand_met: true })).toBe("Limiting stage");
  });
});
