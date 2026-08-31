import { useState } from "react";
import { ChevronDown, ChevronUp, CircleAlert, FileText } from "lucide-react";
import type {
  InformationGap,
  ProductFact,
  ProductUnderstanding,
  UnresolvedSourceStatement,
} from "../../api/product";
import { EvidenceBadge } from "../project/EvidenceStatus";

/** Phase 19 — what Fabrivium believes about the product, and why. */
export function ProductUnderstandingView({
  understanding,
  modelUsed,
  onContinue,
  onEditProduct,
  busy,
}: {
  understanding: ProductUnderstanding;
  modelUsed: boolean;
  onContinue: () => void;
  /** P0 §B4 — the way back. */
  onEditProduct?: () => void;
  busy?: boolean;
}) {
  const known = understanding.facts.filter((f) => f.status !== "CONFLICT");
  const conflicts = understanding.facts.filter((f) => f.status === "CONFLICT");

  return (
    <section className="product" data-testid="product-understanding">
      <header className="product__head">
        <div>
          <p className="product__title">Product understanding</p>
          <p className="product__detail">{understanding.product_name}</p>
        </div>
        <span className="product__method" data-testid="product-method">
          {modelUsed
            ? `Interpreted with ${understanding.model_name ?? "a language model"}`
            : "Read by document extraction"}
        </span>
        {/* The badge lives here, beside the facts it describes. */}
        <EvidenceBadge artifact="PRODUCT_FACTS" />
      </header>

      {understanding.source_documents.map((document) => (
        <p key={document.document_id} className="product__source" data-testid="product-source">
          <FileText size={13} strokeWidth={2} aria-hidden="true" />
          {document.name}
          {document.pages ? ` · ${document.pages} pages` : ""}
          {document.notes.map((note) => (
            <span key={note} className="product__source-note">
              {note}
            </span>
          ))}
        </p>
      ))}

      <div className="product__facts" data-testid="product-facts">
        <p className="fm-label">Detected facts</p>
        <ul>
          {known.map((fact) => (
            <FactRow key={fact.key} fact={fact} />
          ))}
        </ul>
      </div>

      {conflicts.length > 0 && (
        <div className="product__conflicts" data-testid="product-conflicts">
          <p className="product__conflict-title">
            <CircleAlert size={13} strokeWidth={2.2} aria-hidden="true" />
            Sources disagree
          </p>
          {conflicts.map((fact) => (
            <div key={fact.key} className="product__conflict" data-testid={`conflict-${fact.key}`}>
              <p className="product__conflict-label">{fact.label}</p>
              <ul>
                {fact.alternatives.map((alternative, index) => (
                  <li key={`${alternative.value}-${index}`}>
                    <strong>{alternative.value}</strong>
                    {alternative.evidence[0] && (
                      <span> — {alternative.evidence[0].document_name}</span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="product__detail">
                Fabrivium has not chosen between these. Resolve it before selecting equipment.
              </p>
            </div>
          ))}
        </div>
      )}

      {understanding.information_gaps.length > 0 && (
        <div className="product__gaps" data-testid="product-gaps">
          <p className="fm-label">Still needed</p>
          <ul>
            {understanding.information_gaps.map((gap) => (
              <GapRow key={gap.key} gap={gap} />
            ))}
          </ul>
        </div>
      )}

      {understanding.unresolved_statements.length > 0 && (
        <div className="product__unresolved" data-testid="product-unresolved">
          <p className="fm-label">Not understood by Fabrivium</p>
          <p className="product__detail">
            {understanding.unresolved_statements.length === 1
              ? "One sentence in the source states work on the product that Fabrivium could not map to a requirement."
              : `${understanding.unresolved_statements.length} sentences in the source state work on the product that Fabrivium could not map to a requirement.`}{" "}
            No operation has been created from them — add one in the next step if the work belongs on this
            line.
          </p>
          <ul>
            {understanding.unresolved_statements.map((statement, index) => (
              <UnresolvedRow key={`${statement.evidence.document_id}-${index}`} statement={statement} />
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        className="fm-btn-primary fm-btn--auto"
        onClick={onContinue}
        disabled={busy || understanding.facts.length === 0}
        data-testid="product-continue"
      >
        Propose manufacturing process
      </button>

      {onEditProduct && (
        <button
          type="button"
          className="fm-btn-tertiary fm-btn--auto"
          onClick={onEditProduct}
          data-testid="product-edit-information"
        >
          Edit product information
        </button>
      )}
    </section>
  );
}

/** One fact, with its evidence one click away. */
function FactRow({ fact }: { fact: ProductFact }) {
  const [open, setOpen] = useState(false);
  const evidence = fact.evidence[0];

  return (
    <li className="product__fact" data-testid={`fact-${fact.key}`}>
      <span className="product__fact-label">{fact.label}</span>
      <span className="product__fact-value">
        {fact.value ?? <em>Not established</em>}
        {fact.unit && fact.quantity != null ? ` ${fact.unit}` : ""}
      </span>
      <span
        className={`product__status product__status--${fact.status.toLowerCase()}`}
        data-testid={`fact-status-${fact.key}`}
      >
        {STATUS_LABELS[fact.status]}
      </span>
      {evidence && (
        <>
          <button
            type="button"
            className="product__evidence-toggle"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            data-testid={`fact-evidence-toggle-${fact.key}`}
          >
            {open ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
            Evidence
          </button>
          {open && (
            <p className="product__evidence" data-testid={`fact-evidence-${fact.key}`}>
              {evidence.document_name}
              {evidence.page ? `, page ${evidence.page}` : ""}
              {evidence.quote ? (
                <>
                  {" — "}
                  <q>{evidence.quote}</q>
                </>
              ) : (
                // A model-added fact cites the document but no sentence.
                // Inventing a quote would be the most convincing kind of
                // wrong this feature could produce.
                <> — no sentence cited; this fact was inferred, not quoted.</>
              )}
            </p>
          )}
        </>
      )}
    </li>
  );
}

/** One sentence the extractor could not map, quoted and left alone. */
function UnresolvedRow({ statement }: { statement: UnresolvedSourceStatement }) {
  const { evidence } = statement;
  return (
    <li className="product__unresolved-row" data-testid="unresolved-statement">
      <q className="product__unresolved-quote">{statement.statement}</q>
      <span className="product__detail">
        {evidence.document_name}
        {evidence.page ? `, page ${evidence.page}` : ""} — possible manufacturing requirement, not
        mapped.
      </span>
    </li>
  );
}

function GapRow({ gap }: { gap: InformationGap }) {
  return (
    <li className="product__gap" data-testid={`gap-${gap.key}`}>
      <span>{gap.label}</span>
      <span className="product__gap-severity">{GAP_LABELS[gap.severity] ?? gap.severity}</span>
      <span className="product__detail">{gap.reason}</span>
    </li>
  );
}

/** The three that matter read differently on purpose. */
const STATUS_LABELS: Record<string, string> = {
  EXTRACTED: "Document",
  AI_INFERRED: "AI-inferred",
  STATED: "Customer",
  ENGINEER_VERIFIED: "Verified",
  CONFLICT: "Conflict",
  UNKNOWN: "Unknown",
};

/** What a gap actually stops, in the words the rest of the product uses. */
const GAP_LABELS: Record<string, string> = {
  BLOCKS_EQUIPMENT_SELECTION: "Blocks equipment selection",
  LIMITS_EQUIPMENT_VALIDATION: "Required for equipment validation",
  BLOCKS_DETAILED_ENGINEERING: "Blocks detailed engineering",
  OPTIONAL: "Optional",
};
