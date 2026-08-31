import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PlanningRequirements, RequirementsParseResult } from "../../api/types";
import { renderWithContext } from "../../test/testUtils";
import { InterpretedRequirement } from "./InterpretedRequirement";

/** Phase 11 §4 — show what Fabrivium actually understood. */

function requirements(overrides: Partial<PlanningRequirements> = {}): PlanningRequirements {
  return {
    objective: "MEET_DEMAND",
    target_units_per_day: null,
    max_capex: null,
    max_additional_machines: null,
    max_additional_operators: null,
    max_floor_area: null,
    allowed_action_types: null,
    forbidden_machine_ids: [],
    preserve_existing_layout: false,
    notes: [],
    confidence: 1,
    parse_warnings: [],
    prefer_no_new_machines: false,
    prefer_low_known_capex: false,
    prefer_few_changes: false,
    allowed_strategy_families: null,
    ...overrides,
  } as PlanningRequirements;
}

function parseResult(req: PlanningRequirements): RequirementsParseResult {
  return {
    raw_user_request: "test",
    parsed_requirements: req,
    warnings: [],
    parser_type: "DETERMINISTIC_FALLBACK",
    structured_output_valid: true,
  } as RequirementsParseResult;
}

const render = (req: PlanningRequirements) =>
  renderWithContext(<InterpretedRequirement />, { parseResult: parseResult(req) });

describe("InterpretedRequirement", () => {
  it("shows a parsed demand target", () => {
    render(requirements({ target_units_per_day: 1900 }));
    expect(screen.getByTestId("interpreted-requirement")).toHaveTextContent("reach 1,900 units/day");
  });

  it("shows a parsed budget ceiling", () => {
    render(requirements({ target_units_per_day: 1900, max_capex: 150000 }));
    expect(screen.getByTestId("interpreted-requirement")).toHaveTextContent("spend at most");
    expect(screen.getByTestId("interpreted-requirement")).toHaveTextContent("150,000");
  });

  it("shows NO budget chip when the budget was not parsed — the honest case", () => {
    // This is the regression that matters: a dropped ceiling must never be
    // rendered as though it had been applied.
    render(requirements({ target_units_per_day: 1900, max_capex: null }));
    expect(screen.getByTestId("interpreted-requirement")).not.toHaveTextContent("spend at most");
  });

  it("labels a soft preference as a preference, never as a constraint", () => {
    render(requirements({ target_units_per_day: 1900, prefer_no_new_machines: true }));
    const el = screen.getByTestId("interpreted-requirement");
    expect(el).toHaveTextContent("avoid new machines");
    expect(el).toHaveTextContent("preference");
  });

  it("renders a HARD no-new-machines ban distinctly from the soft preference", () => {
    render(
      requirements({
        target_units_per_day: 1900,
        allowed_action_types: ["CHANGE_SHIFT_CONFIGURATION", "CHANGE_MACHINE_CAPACITY"],
      }),
    );
    const el = screen.getByTestId("interpreted-requirement");
    expect(el).toHaveTextContent("no new machines");
    // The hard chip carries no "preference" tag.
    expect(el.querySelector(".interpreted-req__chip--hard")).not.toBeNull();
  });

  it("does not claim a ban when adding machines is still allowed", () => {
    render(
      requirements({
        target_units_per_day: 1900,
        allowed_action_types: ["ADD_PARALLEL_MACHINE", "CHANGE_SHIFT_CONFIGURATION"],
      }),
    );
    expect(screen.getByTestId("interpreted-requirement")).not.toHaveTextContent("no new machines");
  });

  it("renders nothing at all when no requirement was understood", () => {
    render(requirements());
    expect(screen.queryByTestId("interpreted-requirement")).toBeNull();
  });

  it("renders nothing when there is no parse result yet", () => {
    renderWithContext(<InterpretedRequirement />, {});
    expect(screen.queryByTestId("interpreted-requirement")).toBeNull();
  });
});
