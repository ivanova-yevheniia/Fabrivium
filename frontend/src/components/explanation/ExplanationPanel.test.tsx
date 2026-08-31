import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sampleExplanationAccepted, sampleExplanationRejected } from "../../test/fixtures";
import { renderWithContext } from "../../test/testUtils";
import { ExplanationPanel } from "./ExplanationPanel";

describe("ExplanationPanel", () => {
  it("shows an empty state before any plan has been run", () => {
    renderWithContext(<ExplanationPanel />);
    expect(screen.getByTestId("explanation-panel")).toHaveTextContent(/run a plan/i);
  });

  it("renders the executive summary verbatim", () => {
    renderWithContext(<ExplanationPanel />, { explanation: sampleExplanationAccepted });
    expect(screen.getByTestId("explanation-panel")).toHaveTextContent(sampleExplanationAccepted.executive_summary);
  });

  it("renders What Changed, Tradeoffs, and Why Planning Stopped sections", () => {
    renderWithContext(<ExplanationPanel />, { explanation: sampleExplanationAccepted });
    const panel = screen.getByTestId("explanation-panel");
    expect(panel).toHaveTextContent("What Changed");
    expect(panel).toHaveTextContent("Tradeoffs");
    expect(panel).toHaveTextContent("Why Planning Stopped");
  });

  it("displays the backend-verified explanation exactly — never rewrites it", () => {
    renderWithContext(<ExplanationPanel />, { explanation: sampleExplanationRejected });
    expect(screen.getByTestId("explanation-panel")).toHaveTextContent(sampleExplanationRejected.stop_explanation);
  });

  it("shows the DETERMINISTIC source badge", () => {
    renderWithContext(<ExplanationPanel />, { explanation: sampleExplanationAccepted });
    expect(screen.getByText("DETERMINISTIC")).toBeInTheDocument();
  });
});
