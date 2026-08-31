import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProductUnderstandingView } from "./ProductUnderstandingView";
import type { ProductUnderstanding } from "../../api/product";

/** The extraction-completeness panel — what it is allowed to say. */

const base: ProductUnderstanding = {
  product_name: "LT-8 gearbox housing",
  description: "",
  facts: [],
  source_documents: [],
  information_gaps: [],
  unresolved_statements: [],
    source_production_requirements: [],
  interpretation_method: "DOCUMENT_EXTRACTION",
  model_name: null,
};

function renderView(understanding: Partial<ProductUnderstanding>) {
  return render(
    <ProductUnderstandingView
      understanding={{ ...base, ...understanding }}
      modelUsed={false}
      onContinue={vi.fn()}
    />,
  );
}

const WASHING = {
  statement: "Both castings are washed and degreased before assembly.",
  evidence: {
    document_id: "doc-1",
    document_name: "LT-8 specification.txt",
    page: 2,
    quote: "Both castings are washed and degreased before assembly.",
  },
  reason: "This sentence states work performed on the product, and extraction produced no fact from it.",
};

describe("unresolved source statements", () => {
  it("says nothing at all when everything was mapped", () => {
    renderView({ unresolved_statements: [] });
    expect(screen.queryByTestId("product-unresolved")).toBeNull();
  });

  it("quotes the document's own sentence, unaltered", () => {
    renderView({ unresolved_statements: [WASHING] });
    // Not paraphrased, not truncated, not tidied — the engineer is being
    // asked to read what the document actually says.
    expect(screen.getByText(WASHING.statement)).toBeInTheDocument();
  });

  it("says where to go and look", () => {
    renderView({ unresolved_statements: [WASHING] });
    expect(screen.getByText(/LT-8 specification\.txt, page 2/)).toBeInTheDocument();
  });

  it("calls it a possibility, never a requirement", () => {
    renderView({ unresolved_statements: [WASHING] });
    expect(screen.getByText(/possible manufacturing requirement, not\s+mapped/)).toBeInTheDocument();
  });

  it("states plainly that no operation was created", () => {
    renderView({ unresolved_statements: [WASHING] });
    expect(screen.getByTestId("product-unresolved")).toHaveTextContent(
      /No operation has been created from them/,
    );
  });

  it("offers no control that would accept the sentence", () => {
    // The engineer's move is to add or link an operation in the process
    // review step, where the decision is recorded against their name. A
    // one-click accept here would record nothing and interpret nothing.
    const { container } = renderView({ unresolved_statements: [WASHING] });
    const panel = container.querySelector('[data-testid="product-unresolved"]')!;
    expect(panel.querySelectorAll("button")).toHaveLength(0);
    expect(panel.querySelectorAll("input")).toHaveLength(0);
  });

  it("counts more than one without saying 'sentence(s)'", () => {
    renderView({
      unresolved_statements: [WASHING, { ...WASHING, statement: "The drain plug is fitted with a copper washer." }],
    });
    expect(screen.getByTestId("product-unresolved")).toHaveTextContent(/2 sentences in the source state work/);
  });

  it("reads as one sentence, not '1 sentences'", () => {
    renderView({ unresolved_statements: [WASHING] });
    const panel = screen.getByTestId("product-unresolved");
    expect(panel).toHaveTextContent(/One sentence in the source states work/);
    expect(panel).not.toHaveTextContent(/sentence\(s\)|1 sentences/);
  });

  // Golden-run defect G2 — "Blocks equipment selection" was not true.
  // Equipment discovery runs on partial capability evidence and returns
  // candidates as "Under consideration"; nothing is blocked. What a missing
  // drive type and torque stop is validating a candidate against the job.
  it("does not claim a missing fastening parameter blocks equipment selection", () => {
    renderView({
      information_gaps: [
        {
          key: "fastener.screw.drive_torque",
          label: "Screw drive type and fastening torque",
          severity: "LIMITS_EQUIPMENT_VALIDATION",
          reason: "A screwdriving station is validated against drive type and fastening torque.",
        },
      ],
    });

    const gap = screen.getByTestId("gap-fastener.screw.drive_torque");
    expect(gap).toHaveTextContent("Required for equipment validation");
    expect(gap).not.toHaveTextContent(/blocks/i);
    // And it names drive and torque rather than the thread, which the
    // CEC-120 source states.
    expect(gap).not.toHaveTextContent(/thread/i);
  });

  it("is kept separate from the gaps list", () => {
    // A gap is something the document does not say; an unresolved statement
    // is something it does say and we did not map. Same panel would let one
    // stand in for the other.
    renderView({
      information_gaps: [
        {
          key: "fastener.screw.drive_torque",
          label: "Screw drive type and fastening torque",
          severity: "LIMITS_EQUIPMENT_VALIDATION",
          reason: "Not stated.",
        },
      ],
      unresolved_statements: [WASHING],
    });
    const gaps = screen.getByTestId("product-gaps");
    expect(gaps).not.toHaveTextContent(WASHING.statement);
    expect(screen.getByTestId("product-unresolved")).not.toHaveTextContent("Screw drive type");
  });
});
