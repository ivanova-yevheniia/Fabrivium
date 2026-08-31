import { describe, expect, it } from "vitest";
import { linkedManually } from "./RequirementCoverage";
import type { ProposedOperation } from "../../api/product";

/** §12 — WHO decided this requirement is covered. */

function operation(overrides: Partial<ProposedOperation>): ProposedOperation {
  return {
    id: "op-6-packaging",
    process_type: "packaging",
    name: "Packaging",
    description: "Packaging, implied by packaging required.",
    repeated_operations: null,
    basis: "The product information states packaging required.",
    source_fact_keys: ["requirement.packaging"],
    evidence: [],
    fact_status: "RULE_DERIVED",
    confidence: "HIGH",
    status: "ACCEPTED",
    ...overrides,
  } as ProposedOperation;
}

describe("linkedManually", () => {
  it("recognises a link the engineer made, THROUGH the dot in the fact key", () => {
    // The bug this locks out: the first version matched `([^.]+)\.`, so the
    // character class stopped at the dot INSIDE "component.label" and the
    // link never registered. Verified in a real browser — a link the
    // engineer had just made rendered as a Fabrivium derivation.
    const op = operation({
      basis:
        "The product information states packaging required. " +
        "Engineer linked this operation to: component.label.",
      source_fact_keys: ["requirement.packaging", "component.label"],
    });
    expect(linkedManually(op, "component.label")).toBe(true);
  });

  it("handles several keys linked in one act", () => {
    const op = operation({
      basis: "Base. Engineer linked this operation to: component.label, component.lid.",
    });
    expect(linkedManually(op, "component.lid")).toBe(true);
    expect(linkedManually(op, "component.label")).toBe(true);
  });

  it("treats an operation the engineer ADDED as their decision", () => {
    // `add_operation` files it as STATED — "a person said so" — precisely so
    // a human decision is never stored under the planner's name.
    const op = operation({
      id: "op-engineer-7-assembly",
      name: "Prepare plastic enclosure",
      fact_status: "STATED",
      basis: "The enclosure base must be deburred and staged before the PCB goes in.",
      source_fact_keys: ["component.enclosure"],
    });
    expect(linkedManually(op, "component.enclosure")).toBe(true);
  });

  it("does NOT claim a person decided a rule-derived link", () => {
    expect(linkedManually(operation({}), "requirement.packaging")).toBe(false);
  });

  it("does not attribute one linked key's decision to another requirement", () => {
    const op = operation({
      basis: "Base. Engineer linked this operation to: component.label.",
    });
    expect(linkedManually(op, "requirement.packaging")).toBe(false);
  });

  it("survives a draft stored by an earlier build with no basis at all", () => {
    expect(linkedManually({ basis: undefined, fact_status: "RULE_DERIVED" } as never, "x")).toBe(
      false,
    );
  });
});
