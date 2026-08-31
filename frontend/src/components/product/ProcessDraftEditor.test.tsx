import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProcessDraftEditor } from "./ProcessDraftEditor";
import type {
  FactStatus,
  ManufacturingProcessDraft,
  OperationStatus,
  ProductUnderstanding,
  ProposedOperation,
} from "../../api/product";

/** What the operation badge is allowed to claim about who produced it. */

function operation(overrides: Partial<ProposedOperation> = {}): ProposedOperation {
  return {
    id: "op-1",
    process_type: "screwdriving",
    name: "Screw fastening ×6",
    description: "Screw fastening, 6 times per unit, implied by screws.",
    repeated_operations: 6,
    basis: "Six screws are stated in the source.",
    source_fact_keys: ["fastener.screw.count"],
    evidence: [],
    fact_status: "RULE_DERIVED" as FactStatus,
    confidence: "HIGH",
    status: "PROPOSED" as OperationStatus,
    ...overrides,
  };
}

function renderEditor(operations: ProposedOperation[]) {
  const draft: ManufacturingProcessDraft = {
    product_name: "CEC-120",
    operations,
    planner: "Fabrivium process rules",
    method: "RULE_TABLE",
    model_name: null,
    open_questions: [],
  };
  // The editor's audited edits post the understanding alongside the draft so
  // the backend can recompute coverage in the same response. These tests
  // exercise rendering only and never fire one, so a minimal stub is
  // sufficient and keeps them free of network stubbing.
  const understanding: ProductUnderstanding = {
    product_name: "CEC-120",
    description: "",
    facts: [],
    source_documents: [],
    information_gaps: [],
    unresolved_statements: [],
    source_production_requirements: [],
    interpretation_method: "LOCAL_RULES",
    model_name: null,
  };
  return render(
    <ProcessDraftEditor
      understanding={understanding}
      draft={draft}
      onChange={vi.fn()}
      onBuild={vi.fn()}
    />,
  );
}

const badge = (id = "op-1") => screen.getByTestId(`operation-status-${id}`);

describe("who produced this operation", () => {
  it("does not call a deterministic rule an AI inference", () => {
    renderEditor([operation({ fact_status: "RULE_DERIVED" as FactStatus })]);
    expect(badge()).not.toHaveTextContent(/AI/i);
  });

  it("names the rule table as the source", () => {
    renderEditor([operation({ fact_status: "RULE_DERIVED" as FactStatus })]);
    expect(badge()).toHaveTextContent("Fabrivium rule");
  });

  it("still says AI-inferred when a model really did infer it", () => {
    // The distinction only means something if it cuts both ways.
    renderEditor([operation({ fact_status: "AI_INFERRED" as FactStatus })]);
    expect(badge()).toHaveTextContent("AI-inferred");
  });

  it("credits the engineer for an operation they added themselves", () => {
    renderEditor([operation({ fact_status: "STATED" as FactStatus })]);
    expect(badge()).toHaveTextContent("Engineer");
  });

  // Golden-run defect G8 — an operation the engineer ADDED is ACCEPTED the
  // moment they add it (`process_editing.add_operation`), so the review badge
  // alone read "Verified" for it and for a rule output somebody had checked.
  // Same word, two different provenances, and the difference is exactly what
  // a reviewer asks about.
  it("says an engineer-added operation was engineer-added, not only verified", () => {
    renderEditor([
      operation({ fact_status: "STATED" as FactStatus, status: "ACCEPTED" as OperationStatus }),
    ]);
    expect(screen.getByTestId("operation-origin-op-1")).toHaveTextContent("Engineer added");
    expect(badge()).toHaveTextContent("Verified");
  });

  it("does not claim a rule-derived operation was engineer-added", () => {
    // The distinction only means something if it cuts both ways.
    renderEditor([
      operation({ fact_status: "ENGINEER_VERIFIED" as FactStatus, status: "ACCEPTED" as OperationStatus }),
    ]);
    expect(screen.queryByTestId("operation-origin-op-1")).toBeNull();
    expect(badge()).toHaveTextContent("Verified");
  });

  it("a reviewed operation reads as verified whatever produced it", () => {
    // Acceptance is a statement about review, not about derivation, and it
    // outranks the badge — the engineer has taken responsibility for it.
    renderEditor([
      operation({ fact_status: "RULE_DERIVED" as FactStatus, status: "ACCEPTED" as OperationStatus }),
    ]);
    expect(badge()).toHaveTextContent("Verified");
  });

  it("a rejected operation says so rather than showing its derivation", () => {
    renderEditor([
      operation({ fact_status: "RULE_DERIVED" as FactStatus, status: "REJECTED" as OperationStatus }),
    ]);
    expect(badge()).toHaveTextContent("Rejected");
  });

  it("styles a rule differently from an inference", () => {
    // The two carry different weight, so they must not be one visual state
    // wearing two words.
    const { unmount } = renderEditor([operation({ fact_status: "RULE_DERIVED" as FactStatus })]);
    expect(badge().className).toContain("product__status--rule_derived");
    unmount();

    renderEditor([operation({ fact_status: "AI_INFERRED" as FactStatus })]);
    expect(badge().className).toContain("product__status--ai_inferred");
  });
});
