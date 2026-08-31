import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlanningProvenance } from "../../api/types";
import { ProvenanceBadge } from "./ProvenanceBadge";

describe("ProvenanceBadge", () => {
  it("renders nothing when provenance is null (never fabricated)", () => {
    const { container } = render(<ProvenanceBadge provenance={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the verified Granite badge when the LLM actually interpreted the request", () => {
    const provenance: PlanningProvenance = {
      requirements_source: "LLM",
      planning_source: "DETERMINISTIC",
      explanation_source: "NONE",
      fallback_used: false,
      provider_name: "watsonx",
      model_name: "ibm/granite-4-h-small",
    };
    render(<ProvenanceBadge provenance={provenance} />);
    const badge = screen.getByTestId("provenance-badge");
    expect(badge).toHaveAttribute("data-tone", "verified");
    expect(badge).toHaveTextContent("IBM Granite");
  });

  it("shows an honest fallback badge — never claims Granite — when fallback_used is true", () => {
    const provenance: PlanningProvenance = {
      requirements_source: "DETERMINISTIC",
      planning_source: "DETERMINISTIC",
      explanation_source: "NONE",
      fallback_used: true,
      provider_name: "watsonx",
      model_name: "ibm/granite-4-h-small",
    };
    render(<ProvenanceBadge provenance={provenance} />);
    const badge = screen.getByTestId("provenance-badge");
    // The two properties that must never regress: the badge is toned as
    // unverified, and it does not claim Granite did work a parser did.
    expect(badge).toHaveAttribute("data-tone", "unknown");
    expect(badge).not.toHaveTextContent("IBM Granite interpreted");
    expect(badge).not.toHaveTextContent(/granite/i);
    // The provider outage is still carried — as a title rather than as the
    // headline of a screen about throughput.
    expect(badge).toHaveAttribute("title", expect.stringContaining("watsonx"));
    expect(badge.getAttribute("title")).toMatch(/unavailable/i);
  });
});
