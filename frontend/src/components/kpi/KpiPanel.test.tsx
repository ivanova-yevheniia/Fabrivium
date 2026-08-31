import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { IterationSelection } from "../../state/types";
import { sampleSessionAccepted, sampleSessionBudgeted, sampleSessionRejected } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { KpiPanel } from "./KpiPanel";

describe("KpiPanel", () => {
  it("shows an empty state before any plan has been run", () => {
    renderWithContext(<KpiPanel />);
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent(/run a plan/i);
  });

  it("renders KPI values for the final stage, each badged by what produced it", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-panel");
    expect(panel).toHaveTextContent("500"); // completed units
    expect(panel).toHaveTextContent("0"); // demand gap
    expect(panel).toHaveTextContent("YES"); // demand met
    // Physics sections are simulation outputs and say so. The Budget section
    // is arithmetic over catalogue list prices — giving it the same badge as a
    // throughput figure would invite a price to be read as a verified
    // engineering result.
    expect(screen.getAllByText("Simulated").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Known costs").length).toBe(1);
  });

  it("renders demand_met = NO when the stage's simulation has demand_met false", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionRejected, selectedIteration: "baseline" });
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent("NO");
  });

  it("renders demand_met = YES when the stage's simulation has demand_met true", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent("YES");
  });

  it("Phase 9A section 8 — labels the row 'Limiting stage' (not 'Bottleneck') and notes target achieved when demand_met is true", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-panel");
    expect(panel).toHaveTextContent("Limiting stage");
    expect(panel).not.toHaveTextContent("Bottleneck");
    expect(panel).toHaveTextContent(/target achieved/i);
  });

  it("Phase 9A section 8 — keeps the alarming 'Bottleneck' label when demand was NOT met", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionRejected, selectedIteration: "baseline" });
    const panel = screen.getByTestId("kpi-panel");
    expect(panel).toHaveTextContent("Bottleneck");
    expect(panel).not.toHaveTextContent(/target achieved/i);
  });

  it("marks remaining CAPEX as Unknown/no-constraint when max_capex is not set", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent(/no budget constraint set/i);
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("shows an exact numeric remaining CAPEX when a budget constraint is set", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionBudgeted, selectedIteration: "final" });
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent("€15,000");
  });

  it("labels a rejected candidate's KPIs explicitly as a rejected candidate, never as accepted state", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionRejected, selectedIteration: 0 });
    const panel = screen.getByTestId("kpi-panel");
    expect(panel).toHaveTextContent(/rejected candidate/i);
    expect(panel).toHaveTextContent(/hypothetical cumulative capex/i);
  });

  it("does not label an accepted iteration's KPIs as a rejected candidate", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: 0 });
    expect(screen.getByTestId("kpi-panel")).not.toHaveTextContent(/rejected candidate/i);
  });

  it("never displays a raw candidate KPI as the accepted state for a rejected proposal", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionRejected, selectedIteration: 0 });
    // The rejected iteration's own evaluated numbers ARE shown (gap 200,
    // demand not met) — but they must never be presented under a "Final"/
    // accepted heading.
    expect(screen.getByTestId("kpi-panel")).toHaveTextContent(/Iteration 1/);
  });

  // Budget snapshot consistency
  //
  // Regression for a defect found in the Phase 7B audit: "Remaining known
  // CAPEX" was read from the SESSION (always the final remaining) while
  // "Cumulative known CAPEX" came from the selected stage, so Iteration 1
  // of a €220,000 session rendered €85,000 cumulative beside €15,000
  // remaining — two numbers from different points in time, both badged
  // Verified.

  describe("budget figures always describe the selected stage", () => {
    /** Read one KpiRow's value by its label, so an assertion can never be
     * satisfied by the same number appearing in an unrelated row. */
    function rowValue(label: string | RegExp): string {
      const panel = screen.getByTestId("kpi-panel");
      const labelNode = within(panel).getByText(label);
      const value = labelNode.parentElement?.querySelector(".kpi-item__value");
      return value?.textContent?.replace(/Simulated|Known costs|Verified|Unknown/g, "").trim() ?? "";
    }

    const cases: Array<{ stage: IterationSelection; label: string; cumulative: string; remaining: string }> = [
      { stage: "baseline", label: "Baseline", cumulative: "€0", remaining: "€220,000" },
      { stage: 0, label: "Iteration 1", cumulative: "€85,000", remaining: "€135,000" },
      { stage: 1, label: "Iteration 2", cumulative: "€205,000", remaining: "€15,000" },
      { stage: "final", label: "Final", cumulative: "€205,000", remaining: "€15,000" },
    ];

    it.each(cases)(
      "$label shows cumulative $cumulative and remaining $remaining",
      ({ stage, cumulative, remaining }) => {
        renderWithContext(<KpiPanel />, { session: sampleSessionBudgeted, selectedIteration: stage });
        expect(rowValue("Cumulative known CAPEX")).toBe(cumulative);
        expect(rowValue("Remaining known CAPEX")).toBe(remaining);
      },
    );

    it.each(cases)("$label's cumulative and remaining always sum to the €220,000 budget", ({ stage }) => {
      renderWithContext(<KpiPanel />, { session: sampleSessionBudgeted, selectedIteration: stage });
      const euros = (text: string) => Number(text.replace(/[^0-9.-]/g, ""));
      expect(euros(rowValue("Cumulative known CAPEX")) + euros(rowValue("Remaining known CAPEX"))).toBe(220_000);
    });

    it("does not show the session-final remaining while an earlier iteration is selected", () => {
      renderWithContext(<KpiPanel />, { session: sampleSessionBudgeted, selectedIteration: 0 });
      // €15,000 is the FINAL remaining — the exact wrong value this
      // regression is about. It must not appear on Iteration 1 at all.
      expect(screen.getByTestId("kpi-panel")).not.toHaveTextContent("€15,000");
    });

    it("switching through every stage keeps the other verified KPIs in step too", () => {
      const expected = [
        { stage: "baseline" as IterationSelection, completed: "1,105", gap: "795", met: "NO" },
        { stage: 0 as IterationSelection, completed: "1,642", gap: "258", met: "NO" },
        { stage: 1 as IterationSelection, completed: "1,900", gap: "0", met: "YES" },
        { stage: "final" as IterationSelection, completed: "1,900", gap: "0", met: "YES" },
      ];
      for (const { stage, completed, gap, met } of expected) {
        const { unmount } = renderWithContext(<KpiPanel />, {
          session: sampleSessionBudgeted,
          selectedIteration: stage,
        });
        expect(rowValue("Completed units")).toBe(completed);
        expect(rowValue("Demand gap")).toBe(gap);
        expect(rowValue("Demand met")).toBe(met);
        unmount();
      }
    });

    it("labels a rejected candidate's remaining CAPEX as hypothetical, like its cumulative", () => {
      const hypothetical = {
        ...sampleSessionBudgeted,
        iterations: [
          {
            ...sampleSessionBudgeted.iterations[0],
            accepted: false,
            state_after: null,
            rejected_candidate_snapshot: {
              ...sampleSessionBudgeted.iterations[0].state_after!,
              cumulative_known_capex: 300_000,
              remaining_known_capex: -80_000,
            },
          },
          sampleSessionBudgeted.iterations[1],
        ],
      };
      renderWithContext(<KpiPanel />, { session: hypothetical, selectedIteration: 0 });
      const panel = screen.getByTestId("kpi-panel");
      expect(panel).toHaveTextContent(/hypothetical cumulative capex/i);
      // An over-budget hypothetical reports the overrun honestly rather
      // than clamping to a misleading €0.
      expect(panel).toHaveTextContent(/hypothetical remaining capex/i);
      expect(rowValue("Hypothetical remaining CAPEX")).toContain("80,000");
    });
  });
});
