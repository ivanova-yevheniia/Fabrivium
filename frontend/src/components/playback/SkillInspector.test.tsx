import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

import { SkillInspector } from "./SkillInspector";
import { recordSkillTrace, resetSkillTrace } from "../../api/skillTrace";

const REGISTRY = {
  skills: [
    {
      id: "factory_simulation",
      version: "1.0.0",
      qualified_id: "factory_simulation@1.0.0",
      name: "Factory simulation",
      description: "Runs the deterministic simulation.",
      category: "SIMULATION",
      capabilities: [],
      prerequisites: [],
      input_types: ["Factory"],
      output_types: ["SimulationResult"],
      supported_inputs: [],
      deterministic: true,
      uses_llm: false,
      uses_external_data: false,
      side_effects: ["NONE"],
      execution_mode: "DETERMINISTIC",
      namespace: "factorymind",
      owner: "Fabrivium",
      enabled: true,
    },
  ],
  workflows: [],
};

function stubRegistry() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => REGISTRY,
    } as Response),
  );
}

describe("SkillInspector — execution trace", () => {
  beforeEach(() => {
    resetSkillTrace();
    stubRegistry();
  });

  afterEach(() => {
    // Unmount first. `resetSkillTrace` notifies subscribers, and doing that
    // while the panel is still mounted is a React update outside act().
    cleanup();
    vi.unstubAllGlobals();
    resetSkillTrace();
  });

  it("says plainly that nothing has run yet", async () => {
    render(<SkillInspector />);
    expect(await screen.findByTestId("skill-trace-empty")).toBeInTheDocument();
    // The registry list is a catalogue; an empty trace must not read as if
    // those skills had produced something.
    expect(screen.queryByTestId("skill-trace")).not.toBeInTheDocument();
  });

  it("shows the skill, the version and the outcome once one has run", async () => {
    recordSkillTrace("factory_simulation@1.0.0:SUCCESS", "/simulation/run");
    render(<SkillInspector />);

    const entry = await screen.findByTestId("skill-trace-entry");
    expect(entry).toHaveTextContent("factory_simulation");
    expect(entry).toHaveTextContent("1.0.0");
    expect(entry).toHaveTextContent("SUCCESS");
    expect(entry).toHaveTextContent("/simulation/run");
  });

  it("lists every stage of a workflow", async () => {
    recordSkillTrace(
      "factory_concept_builder@1.0.0:SUCCESS, layout_generation@1.0.0:SUCCESS",
      "/concept/build",
    );
    render(<SkillInspector />);

    await waitFor(() => {
      expect(screen.getAllByTestId("skill-trace-entry")).toHaveLength(2);
    });
  });

  it("shows a BLOCKED skill rather than hiding the refusal", async () => {
    recordSkillTrace("factory_concept_builder@1.0.0:BLOCKED", "/concept/build");
    render(<SkillInspector />);

    expect(
      await screen.findByTestId("skill-trace-status-factory_concept_builder"),
    ).toHaveTextContent("BLOCKED");
  });

  it("updates when a skill runs after the panel is already rendered", async () => {
    render(<SkillInspector />);
    await screen.findByTestId("skill-trace-empty");

    act(() => {
      recordSkillTrace("process_planning@1.0.0:PARTIAL", "/product/plan-process");
    });

    expect(await screen.findByTestId("skill-trace-entry")).toHaveTextContent("PARTIAL");
  });
});
