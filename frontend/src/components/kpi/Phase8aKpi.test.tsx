import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SimulationResult } from "../../api/types";
import { sampleSessionAccepted } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { KpiPanel } from "./KpiPanel";
import { PlanningTimeline } from "../timeline/PlanningTimeline";

/** Phase 8A frontend coverage — shift, workforce and buffer visibility. */

function sessionWith(simOverrides: Partial<SimulationResult>) {
  const base = sampleSessionAccepted;
  const sim = { ...base.final_snapshot.simulation, ...simOverrides };
  return {
    ...base,
    final_snapshot: { ...base.final_snapshot, simulation: sim },
  };
}

describe("KpiPanel — production time", () => {
  it("shows the stage's shift configuration and total production hours", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-shift");
    // sampleFactory is 1 shift x 8h.
    expect(panel).toHaveTextContent("1 × 8 h");
    expect(panel).toHaveTextContent("8 h");
  });

  it("shows throughput per hour alongside it, so extra time is not read as extra speed", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("kpi-shift")).toHaveTextContent(/throughput\/hour/i);
  });

  it("reflects the SELECTED stage, not the session's final state", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "baseline" });
    expect(screen.getByTestId("kpi-shift")).toBeInTheDocument();
  });
});

describe("KpiPanel — workforce", () => {
  it("renders the operator KPI the backend measured", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-operators");
    expect(panel).toHaveTextContent("Operators available");
    expect(panel).toHaveTextContent("4");
    expect(panel).toHaveTextContent("30.0%"); // utilization 0.3
  });

  it("shows no Constrained badge when staff never waited", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.queryByTestId("operator-constrained-badge")).not.toBeInTheDocument();
  });

  it("flags a workforce constraint only when the backend reports one", () => {
    const session = sessionWith({
      operator_kpi: {
        operators_available: 4,
        operators_required_peak: 8,
        peak_operators_in_use: 4,
        average_operators_in_use: 3.9,
        utilization: 0.975,
        total_operator_wait_seconds: 5400,
        average_operator_wait_seconds: 27.3,
        max_operator_wait_seconds: 120,
        operations_delayed_by_operators: 198,
        operator_constrained: true,
      },
    });
    renderWithContext(<KpiPanel />, { session, selectedIteration: "final" });
    expect(screen.getByTestId("operator-constrained-badge")).toHaveTextContent(/constrained/i);
    const panel = screen.getByTestId("kpi-operators");
    expect(panel).toHaveTextContent("97.5%");
    expect(panel).toHaveTextContent("27.3");
    expect(panel).toHaveTextContent("198");
  });

  it("renders nothing at all when the backend reported no workforce data", () => {
    const session = sessionWith({ operator_kpi: null });
    renderWithContext(<KpiPanel />, { session, selectedIteration: "final" });
    // A row of zeros would look like a measurement; absence is honest.
    expect(screen.queryByTestId("kpi-operators")).not.toBeInTheDocument();
  });
});

describe("KpiPanel — buffers", () => {
  it("reports a quiet buffer as not blocking rather than inventing congestion", () => {
    renderWithContext(<KpiPanel />, { session: sampleSessionAccepted, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-buffers");
    expect(panel).toHaveTextContent("Pre-B Buffer");
    expect(panel).toHaveTextContent(/no blocking/i);
  });

  it("reports measured blocking when the backend saw it", () => {
    const session = sessionWith({
      buffer_kpis: [
        {
          buffer_id: "buf-1",
          buffer_name: "Pre-B Buffer",
          capacity: 2,
          upstream_machine_id: "m-a",
          downstream_machine_id: "m-b",
          average_level: 2,
          max_level: 2,
          utilization: 1,
          time_full_seconds: 18393,
          time_empty_seconds: 100,
          full_fraction: 0.983,
          empty_fraction: 0.006,
          upstream_blocked_seconds: 18393,
          upstream_blocked_events: 1084,
          blocking_observed: true,
        },
      ],
    });
    renderWithContext(<KpiPanel />, { session, selectedIteration: "final" });
    const panel = screen.getByTestId("kpi-buffers");
    expect(panel).toHaveTextContent("98.3%");
    expect(panel).toHaveTextContent("18,393");
    expect(panel).toHaveTextContent("(2/2)");
  });

  it("renders nothing when no buffer participates in the route", () => {
    const session = sessionWith({ buffer_kpis: [] });
    renderWithContext(<KpiPanel />, { session, selectedIteration: "final" });
    expect(screen.queryByTestId("kpi-buffers")).not.toBeInTheDocument();
  });
});

describe("PlanningTimeline — Phase 8A action text", () => {
  function sessionWithAction(action: Record<string, unknown>) {
    const base = sampleSessionAccepted;
    const iteration = {
      ...base.iterations[0],
      selected_proposal: {
        ...base.iterations[0].selected_proposal!,
        scenario: { id: "s", name: "n", description: "", actions: [action as never] },
      },
    };
    return { ...base, iterations: [iteration] };
  }

  it("describes a shift change in engineering terms, not as a raw enum", () => {
    renderWithContext(<PlanningTimeline />, {
      session: sessionWithAction({ action_type: "CHANGE_SHIFT_CONFIGURATION", shifts_per_day: 3, hours_per_shift: null }),
    });
    const node = screen.getByTestId("timeline-iteration-0");
    expect(node).toHaveTextContent("Change shifts to 3 shifts/day");
    expect(node).not.toHaveTextContent("CHANGE_SHIFT_CONFIGURATION");
  });

  it("renders only the shift fields the action actually carries", () => {
    renderWithContext(<PlanningTimeline />, {
      session: sessionWithAction({ action_type: "CHANGE_SHIFT_CONFIGURATION", shifts_per_day: null, hours_per_shift: 12 }),
    });
    const node = screen.getByTestId("timeline-iteration-0");
    expect(node).toHaveTextContent("12 h/shift");
    expect(node).not.toHaveTextContent("shifts/day");
  });

  it("describes an operator change", () => {
    renderWithContext(<PlanningTimeline />, {
      session: sessionWithAction({ action_type: "CHANGE_OPERATOR_CAPACITY", operators_available: 10 }),
    });
    expect(screen.getByTestId("timeline-iteration-0")).toHaveTextContent("Set operators to 10");
  });

  it("describes a buffer change", () => {
    renderWithContext(<PlanningTimeline />, {
      session: sessionWithAction({ action_type: "CHANGE_BUFFER_CAPACITY", buffer_id: "buf-1", new_capacity: 100 }),
    });
    expect(screen.getByTestId("timeline-iteration-0")).toHaveTextContent("Set buf-1 capacity to 100");
  });
});
