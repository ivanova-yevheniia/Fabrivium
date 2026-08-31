import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sampleSessionAccepted, sampleSessionRejected } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { PlanningTimeline } from "./PlanningTimeline";

describe("PlanningTimeline", () => {
  it("shows an empty state before any plan has been run", () => {
    renderWithContext(<PlanningTimeline />);
    expect(screen.getByTestId("planning-timeline")).toHaveTextContent(/run a plan/i);
  });

  it("renders baseline, every iteration, and final nodes", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("timeline-baseline")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-iteration-0")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-final")).toBeInTheDocument();
  });

  it("marks the final node ACCEPTED-path with GOAL REACHED when the session reached its goal", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("timeline-final")).toHaveTextContent(/goal reached/i);
  });

  it("renders an accepted iteration with the Accepted badge", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("timeline-iteration-0")).toHaveTextContent(/accepted/i);
  });

  it("renders a rejected iteration visibly but marked Rejected and visually secondary", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionRejected, selectedIteration: "baseline" });
    const node = screen.getByTestId("timeline-iteration-0");
    expect(node).toHaveTextContent(/rejected/i);
    expect(node.className).toMatch(/timeline__node--rejected/);
  });

  it("clicking a node calls selectIteration with the right key", () => {
    const { contextValue } = renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: "final" });
    fireEvent.click(screen.getByTestId("timeline-baseline"));
    expect(contextValue.selectIteration).toHaveBeenCalledWith("baseline");

    fireEvent.click(screen.getByTestId("timeline-iteration-0"));
    expect(contextValue.selectIteration).toHaveBeenCalledWith(0);
  });

  it("highlights the currently-selected node", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: 0 });
    expect(screen.getByTestId("timeline-iteration-0").className).toMatch(/timeline__node--selected/);
    expect(screen.getByTestId("timeline-baseline").className).not.toMatch(/timeline__node--selected/);
  });

  it("shows the demand gap transition for an accepted iteration", () => {
    renderWithContext(<PlanningTimeline />, { session: sampleSessionAccepted, selectedIteration: "final" });
    expect(screen.getByTestId("timeline-iteration-0")).toHaveTextContent(/200.*0/);
  });
});
