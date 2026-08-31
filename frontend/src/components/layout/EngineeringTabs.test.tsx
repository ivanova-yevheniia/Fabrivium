import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { sampleFactory, sampleSessionTwoIterations } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { appReducer } from "../../state/appReducer";
import { initialAppState } from "../../state/types";
import { EngineeringTabs } from "./EngineeringTabs";

/** Phase 12 §8/§19 — the Engineering View's three contexts. */

describe("EngineeringTabs", () => {
  it("exposes the three contexts as a tablist and marks the active one", () => {
    renderWithContext(<EngineeringTabs />, { factory: sampleFactory, engineeringTab: "FACTORY" });

    expect(screen.getByRole("tablist", { name: /engineering context/i })).toBeInTheDocument();
    expect(screen.getByTestId("engineering-tab-factory")).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("engineering-tab-simulation")).toHaveAttribute("aria-selected", "false");
    expect(screen.getByTestId("engineering-tab-plan_analysis")).toHaveAttribute("aria-selected", "false");
  });

  it("requests the chosen context", async () => {
    const user = userEvent.setup();
    const setEngineeringTab = vi.fn();
    renderWithContext(
      <EngineeringTabs />,
      { factory: sampleFactory, engineeringTab: "FACTORY" },
      { setEngineeringTab },
    );

    await user.click(screen.getByTestId("engineering-tab-simulation"));
    expect(setEngineeringTab).toHaveBeenCalledWith("SIMULATION");
  });

  it("switching context changes NOTHING about which scenario is on screen", () => {
    // Driven through the real reducer rather than a spy: this is a claim
    // about state, not about a click handler.
    const seeded = {
      ...initialAppState,
      session: sampleSessionTwoIterations,
      selectedIteration: 1 as const,
      selectedStrategyId: "strategy-hybrid-no-equipment",
      selectedMachineId: "m-a",
      viewMode: "3D" as const,
      engineeringTab: "FACTORY" as const,
    };

    const next = appReducer(seeded, { type: "SET_ENGINEERING_TAB", tab: "PLAN_ANALYSIS" });

    expect(next.engineeringTab).toBe("PLAN_ANALYSIS");
    expect(next.selectedIteration).toBe(seeded.selectedIteration);
    expect(next.selectedStrategyId).toBe(seeded.selectedStrategyId);
    expect(next.selectedMachineId).toBe(seeded.selectedMachineId);
    expect(next.viewMode).toBe(seeded.viewMode);
    expect(next.session).toBe(seeded.session);
    expect(next.draftLayout).toBe(seeded.draftLayout);
    expect(next.playback).toBe(seeded.playback);
  });
});
