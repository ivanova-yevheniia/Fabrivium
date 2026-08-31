import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StaleResultsBanner } from "./StaleResultsBanner";
import { renderWithContext } from "../../test/testUtils";
import type { StaleResults } from "../../state/types";

/** A result computed before the last change must not sit on screen looking current. */

const STALE: StaleResults = {
  stale: ["BASELINE_RESULT", "BOTTLENECK", "RECOMMENDATION"],
  unaffected: ["LAYOUT"],
  summary: "1 input(s) changed.",
  changes: ["Screwdriving — cycle time: 52 → 61"],
};

describe("stale results banner", () => {
  it("renders nothing while the results still answer the current inputs", () => {
    renderWithContext(<StaleResultsBanner />, { staleResults: null });
    expect(screen.queryByTestId("stale-results-banner")).toBeNull();
  });

  it("names the results that are out of date", () => {
    renderWithContext(<StaleResultsBanner />, { staleResults: STALE });
    const list = screen.getByTestId("stale-results-list");
    expect(list).toHaveTextContent(/baseline throughput/i);
    expect(list).toHaveTextContent(/the limiting stage/i);
    expect(list).toHaveTextContent(/the recommendation/i);
  });

  it("says the results were not re-verified rather than that they are wrong", () => {
    // They are not wrong. They answer a question that has changed, and
    // alarming them as errors would train people to dismiss the banner.
    renderWithContext(<StaleResultsBanner />, { staleResults: STALE });
    expect(screen.getByTestId("stale-results-banner")).toHaveTextContent(
      /computed before the last change and have not been re-verified/i,
    );
  });

  it("offers re-verification instead of doing it silently", () => {
    renderWithContext(<StaleResultsBanner />, { staleResults: STALE });
    expect(screen.getByTestId("stale-results-reverify")).toHaveTextContent(/re-verify/i);
  });

  it("names the input that changed, on request", async () => {
    const user = userEvent.setup();
    renderWithContext(<StaleResultsBanner />, { staleResults: STALE });

    await user.click(screen.getByTestId("stale-results-toggle"));
    const detail = screen.getByTestId("stale-results-detail");
    expect(detail).toHaveTextContent("Screwdriving — cycle time: 52 → 61");
  });

  it("names what the change cannot have affected", async () => {
    // The usual worry after an edit is that everything was quietly rebuilt.
    const user = userEvent.setup();
    renderWithContext(<StaleResultsBanner />, { staleResults: STALE });

    await user.click(screen.getByTestId("stale-results-toggle"));
    expect(within(screen.getByTestId("stale-results-unaffected")).getByText(/the layout/i))
      .toBeInTheDocument();
  });

  it("does not hide the old results", () => {
    // The engineer may well want to see the previous figure while deciding
    // whether the change matters. The banner qualifies them; it does not
    renderWithContext(
      <div>
        <StaleResultsBanner />
        <p data-testid="previous-result">1,105 units/day</p>
      </div>,
      { staleResults: STALE },
    );
    expect(screen.getByTestId("previous-result")).toBeInTheDocument();
  });
});
