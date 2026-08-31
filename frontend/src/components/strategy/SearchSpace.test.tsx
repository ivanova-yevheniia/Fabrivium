import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SearchSpace } from "./SearchSpace";
import type { StrategyArenaResult } from "../../api/types";

/**
 * "Is this really optimisation?" is the most predictable technical
 * objection to a tool that recommends a plan, and the honest answer is no —
 * it is bounded candidate comparison. That answer is perfectly defensible,
 * but only when the search behind it is stated rather than implied.
 */

function arena(over: Partial<StrategyArenaResult["stats"]> = {}, extra: Partial<StrategyArenaResult> = {}) {
  return {
    strategies: [{ strategy_id: "a" }, { strategy_id: "b" }, { strategy_id: "c" }],
    families_without_options: [],
    stats: {
      families_attempted: 5,
      strategies_retained: 3,
      strategies_discarded: 2,
      simulations_run: 42,
      budget_exhausted: false,
      cache_hits: 0,
      elapsed_seconds: 3.2,
      ...over,
    },
    ...extra,
  } as unknown as StrategyArenaResult;
}

describe("search space", () => {
  it("states the claim as comparison, not optimisation", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.getByTestId("search-space-summary")).toHaveTextContent(
      // "Best" is an optimality claim over a bounded enumeration, and the
      // project's own jury notes promise the word appears nowhere.
      /highest-ranked option among 3 explored candidates/i,
    );
    expect(screen.getByTestId("search-space-claim")).toHaveTextContent(
      /does not prove optimality/i,
    );
  });

  it("never uses the word optimal", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.getByTestId("search-space").textContent).not.toMatch(/\boptimal\b/i);
  });

  it("shows the numbers behind the claim", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.getByTestId("search-space-families")).toHaveTextContent("5");
    expect(screen.getByTestId("search-space-retained")).toHaveTextContent("3");
    expect(screen.getByTestId("search-space-discarded")).toHaveTextContent("2");
    expect(screen.getByTestId("search-space-simulations")).toHaveTextContent("42");
  });

  it("states the selection rule rather than implying a score", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.getByTestId("search-space-claim")).toHaveTextContent(/ranked by a fixed rule/i);
  });

  it("says outright when the search was truncated", () => {
    // A search that stopped at its budget and does not say so reads as an
    // exhaustive one.
    render(<SearchSpace arena={arena({ budget_exhausted: true })} />);
    expect(screen.getByTestId("search-space-truncated")).toHaveTextContent(
      /not explored to exhaustion/i,
    );
  });

  it("does not claim truncation when the search completed", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.queryByTestId("search-space-truncated")).toBeNull();
  });

  it("reports families that produced nothing", () => {
    render(
      <SearchSpace
        arena={arena({}, { families_without_options: ["process_improvement"] } as never)}
      />,
    );
    expect(screen.getByTestId("search-space-empty-families")).toHaveTextContent(
      /process_improvement/,
    );
  });

  it("stays collapsed so the executive view is not cluttered", () => {
    render(<SearchSpace arena={arena()} />);
    expect(screen.getByTestId("search-space").tagName).toBe("DETAILS");
    expect(screen.getByTestId("search-space")).not.toHaveAttribute("open");
  });
});
