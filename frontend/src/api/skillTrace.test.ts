import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getSkillExecutions,
  parseSkillTrace,
  recordSkillTrace,
  resetSkillTrace,
  subscribeToSkillTrace,
} from "./skillTrace";

describe("skill trace", () => {
  beforeEach(() => {
    resetSkillTrace();
  });

  it("parses one skill into id, version and status", () => {
    expect(parseSkillTrace("factory_simulation@1.0.0:SUCCESS", "/simulation/run")).toEqual([
      {
        skillId: "factory_simulation",
        version: "1.0.0",
        status: "SUCCESS",
        path: "/simulation/run",
      },
    ]);
  });

  it("keeps every stage of a workflow, in order", () => {
    const entries = parseSkillTrace(
      "factory_concept_builder@1.0.0:SUCCESS, layout_generation@1.0.0:SUCCESS",
      "/concept/build",
    );
    expect(entries.map((entry) => entry.skillId)).toEqual([
      "factory_concept_builder",
      "layout_generation",
    ]);
  });

  it("records a header the caller received", () => {
    recordSkillTrace("process_planning@1.0.0:PARTIAL", "/product/plan-process");
    expect(getSkillExecutions()).toHaveLength(1);
    expect(getSkillExecutions()[0].status).toBe("PARTIAL");
  });

  it("records nothing when an endpoint sent no header", () => {
    // An endpoint that does not go through the skill layer must not appear
    // here. The list is evidence, and evidence cannot be inferred.
    recordSkillTrace(null, "/health");
    expect(getSkillExecutions()).toHaveLength(0);
  });

  it("keeps a skill that could not be parsed rather than dropping it", () => {
    // Silently discarding an unrecognised entry would make the trace look
    // shorter than what actually ran.
    const entries = parseSkillTrace("something-unexpected", "/x");
    expect(entries).toHaveLength(1);
    expect(entries[0].skillId).toBe("something-unexpected");
  });

  it("notifies subscribers when a skill runs", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToSkillTrace(listener);
    recordSkillTrace("factory_simulation@1.0.0:SUCCESS", "/simulation/run");
    expect(listener).toHaveBeenCalled();
    unsubscribe();
  });

  it("stops notifying after unsubscribe", () => {
    const listener = vi.fn();
    subscribeToSkillTrace(listener)();
    recordSkillTrace("factory_simulation@1.0.0:SUCCESS", "/simulation/run");
    expect(listener).not.toHaveBeenCalled();
  });

  it("bounds the list so a long session cannot grow it without limit", () => {
    for (let i = 0; i < 60; i += 1) {
      recordSkillTrace("factory_simulation@1.0.0:SUCCESS", "/simulation/run");
    }
    expect(getSkillExecutions().length).toBeLessThanOrEqual(40);
  });

  it("records a BLOCKED skill behind a failed request", () => {
    // The execution an engineer most wants to see is the one that refused.
    recordSkillTrace("factory_concept_builder@1.0.0:BLOCKED", "/concept/build");
    expect(getSkillExecutions()[0].status).toBe("BLOCKED");
  });
});
