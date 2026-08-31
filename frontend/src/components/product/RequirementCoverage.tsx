import { useState } from "react";
import { AlertTriangle, Check, Link2, Plus } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import { coverageSummaryText } from "../../utils/coverageSummary";
import {
  addOperation,
  linkRequirement,
  unlinkRequirement,
  type CoverageReport,
  type ManufacturingProcessDraft,
  type ProductUnderstanding,
  type ProposedOperation,
  type RequirementCoverageItem,
} from "../../api/product";
import {
  ProcessFamilySelect,
  defaultProcessType,
  useProcessFamilies,
} from "./ProcessFamilySelect";

/** Did the proposed process answer everything the document requires? */

/** Whether an engineer has reviewed the proposed process, read from the
 * status the operations already carry.
 *
 * Deliberately NOT a new field and NOT a new workflow: `ProposedOperation`
 * already records whether each operation was accepted, and an engineer who
 * has accepted every operation has looked at the route. What is added here
 * is only that the fact is now SAID — the distinction between "the extractor
 * found these" and "a person checked these against the document" was
 * previously visible only to someone reading the source.
 *
 * Neither state claims the process is complete. Reviewed means a person
 * looked; it does not mean the document held nothing else.
 */
function processScope(draft: ManufacturingProcessDraft): string {
  const operations = draft.operations ?? [];
  if (operations.length === 0) return "No operations proposed yet.";
  const reviewed = operations.filter((op) => op.status === "ACCEPTED").length;
  if (reviewed === operations.length) {
    return "Engineer reviewed every proposed operation. Completeness against the source document is not independently established.";
  }
  if (reviewed === 0) {
    return "Not yet reviewed — these operations are Fabrivium's proposal from the extracted facts.";
  }
  return `${reviewed} of ${operations.length} operations reviewed by an engineer. Completeness against the source document is not independently established.`;
}

function Unresolved({
  item,
  understanding,
  draft,
  busy,
  onResolved,
  onError,
}: {
  item: RequirementCoverageItem;
  understanding: ProductUnderstanding;
  draft: ManufacturingProcessDraft;
  busy: boolean;
  onResolved: (result: { draft: ManufacturingProcessDraft; coverage: CoverageReport }) => void;
  onError: (message: string) => void;
}) {
  const [mode, setMode] = useState<null | "add" | "link">(null);
  const [name, setName] = useState("");
  const families = useProcessFamilies();
  // Empty until the catalog arrives, and `submitAdd` refuses to post an
  // empty family — so an operation can never be created carrying a process
  // type this session invented rather than one the backend published.
  const [chosenType, setChosenType] = useState("");
  const processType = chosenType || defaultProcessType(families);
  const [basis, setBasis] = useState("");
  const [linkTo, setLinkTo] = useState(draft.operations[0]?.id ?? "");

  async function submitAdd() {
    if (!name.trim() || !basis.trim() || !processType) return;
    try {
      onResolved(
        await addOperation(understanding, draft, {
          name,
          process_type: processType,
          basis,
          source_fact_keys: [item.fact_key],
        }),
      );
      setMode(null);
    } catch (err) {
      onError(describeRequestFailure(err));
    }
  }

  async function submitLink() {
    if (!linkTo) return;
    try {
      onResolved(await linkRequirement(understanding, draft, linkTo, [item.fact_key]));
      setMode(null);
    } catch (err) {
      onError(describeRequestFailure(err));
    }
  }

  return (
    <li className="coverage-row coverage-row--unresolved" data-testid={`coverage-${item.fact_key}`}>
      <div className="coverage-row__head">
        <AlertTriangle size={13} strokeWidth={2.2} aria-hidden="true" className="status-fail" />
        <span className="coverage-row__label">{item.label}</span>
        <span className="coverage-row__status" data-testid={`coverage-status-${item.fact_key}`}>
          Unresolved
        </span>
        {item.severity === "CRITICAL" && (
          <span className="fm-badge fm-badge--bad" data-testid={`coverage-critical-${item.fact_key}`}>
            Stated by the source
          </span>
        )}
      </div>

      {item.quotes.length > 0 && (
        <p className="coverage-row__quote" data-testid={`coverage-quote-${item.fact_key}`}>
          “{item.quotes[0]}”
        </p>
      )}

      {mode === null && (
        <div className="coverage-row__actions">
          <button
            type="button"
            className="fm-btn-tertiary"
            disabled={busy}
            onClick={() => setMode("add")}
            data-testid={`coverage-add-${item.fact_key}`}
          >
            <Plus size={13} strokeWidth={2} aria-hidden="true" />
            Add an operation
          </button>
          <button
            type="button"
            className="fm-btn-tertiary"
            disabled={busy || draft.operations.length === 0}
            onClick={() => setMode("link")}
            data-testid={`coverage-link-${item.fact_key}`}
          >
            <Link2 size={13} strokeWidth={2} aria-hidden="true" />
            An existing operation covers this
          </button>
        </div>
      )}

      {mode === "add" && (
        <div className="coverage-row__editor" data-testid={`coverage-add-form-${item.fact_key}`}>
          <input
            className="fm-input"
            value={name}
            autoFocus
            placeholder="Operation name"
            aria-label="Operation name"
            onChange={(event) => setName(event.target.value)}
            data-testid={`coverage-add-name-${item.fact_key}`}
          />
          <ProcessFamilySelect
            className="fm-input"
            value={processType}
            onChange={setChosenType}
            state={families}
            ariaLabel="Process type"
            testId={`coverage-add-type-${item.fact_key}`}
          />
          <input
            className="fm-input"
            value={basis}
            placeholder="Why does this operation exist?"
            aria-label="Reason this operation exists"
            onChange={(event) => setBasis(event.target.value)}
            data-testid={`coverage-add-basis-${item.fact_key}`}
          />
          <button
            type="button"
            className="fm-btn-primary"
            disabled={busy || !name.trim() || !basis.trim()}
            onClick={submitAdd}
            data-testid={`coverage-add-save-${item.fact_key}`}
          >
            <Check size={13} strokeWidth={2.2} aria-hidden="true" />
            Add
          </button>
          <button type="button" className="fm-btn-tertiary" onClick={() => setMode(null)}>
            Cancel
          </button>
        </div>
      )}

      {mode === "link" && (
        <div className="coverage-row__editor" data-testid={`coverage-link-form-${item.fact_key}`}>
          <select
            className="fm-input"
            value={linkTo}
            aria-label="Operation that covers this requirement"
            onChange={(event) => setLinkTo(event.target.value)}
            data-testid={`coverage-link-select-${item.fact_key}`}
          >
            {draft.operations
              .filter((operation) => operation.status !== "REJECTED")
              .map((operation) => (
                <option key={operation.id} value={operation.id}>
                  {operation.name}
                </option>
              ))}
          </select>
          <button
            type="button"
            className="fm-btn-primary"
            disabled={busy || !linkTo}
            onClick={submitLink}
            data-testid={`coverage-link-save-${item.fact_key}`}
          >
            <Check size={13} strokeWidth={2.2} aria-hidden="true" />
            Link
          </button>
          <button type="button" className="fm-btn-tertiary" onClick={() => setMode(null)}>
            Cancel
          </button>
        </div>
      )}
    </li>
  );
}

export function RequirementCoverage({
  coverage,
  understanding,
  draft,
  busy = false,
  onResolved,
}: {
  coverage: CoverageReport;
  understanding: ProductUnderstanding;
  draft: ManufacturingProcessDraft;
  busy?: boolean;
  onResolved: (result: { draft: ManufacturingProcessDraft; coverage: CoverageReport }) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const unresolved = coverage.items.filter((item) => item.status === "UNRESOLVED");
  const addressed = coverage.items.filter((item) => item.status === "ADDRESSED");

  return (
    <section className="coverage" data-testid="requirement-coverage">
      <div className="coverage__head">
        {/* The panel is named for the metric it actually computes. */}
        <p className="fm-section__title">Extracted-requirement coverage</p>
        {/* §11 — stated at exactly the strength the evidence supports. */}
        <p className="coverage__summary" data-testid="coverage-summary">
          {coverageSummaryText(coverage)}
        </p>

        {/* The scope, on screen rather than only in a docstring. */}
        <details className="coverage__scope" data-testid="coverage-scope">
          <summary data-testid="coverage-scope-toggle">What does this mean?</summary>
          <p>
            Coverage checks whether the manufacturing facts Fabrivium extracted from the
            source are represented in the current process. It does not prove that every
            manufacturing step in the source was extracted.
          </p>
          <p>
            A step the extractor did not read cannot appear here as missing. Reviewing the
            process against the document is the engineer&rsquo;s judgement, and it is what
            the operation review below records.
          </p>
        </details>

        {/* PROCESS SCOPE — reusing the review state the operations already
            carry, rather than inventing a second notion of "reviewed". */}
        <p className="coverage__process-scope" data-testid="coverage-process-scope">
          <span className="fm-label">Process scope</span>{" "}
          {processScope(draft)}
        </p>
      </div>

      {error && (
        <p className="concept-error" data-testid="coverage-error">
          {error}
        </p>
      )}

      {unresolved.length > 0 && (
        <ul className="coverage__list" data-testid="coverage-unresolved">
          {unresolved.map((item) => (
            <Unresolved
              key={item.fact_key}
              item={item}
              understanding={understanding}
              draft={draft}
              busy={busy}
              onResolved={onResolved}
              onError={setError}
            />
          ))}
        </ul>
      )}

      {coverage.approval_blocked && (
        <p className="coverage__blocked" data-testid="coverage-blocked">
          The source states {coverage.critical_unresolved_count}{" "}
          {coverage.critical_unresolved_count === 1 ? "requirement" : "requirements"} that no
          operation answers. Resolve {coverage.critical_unresolved_count === 1 ? "it" : "them"}, or
          record that {coverage.critical_unresolved_count === 1 ? "it is" : "they are"} out of scope
          for this line, before building the concept.
        </p>
      )}

      {addressed.length > 0 && (
        <details className="coverage__addressed">
          <summary data-testid="coverage-addressed-toggle">
            {addressed.length} requirement{addressed.length === 1 ? "" : "s"} addressed
          </summary>
          <ul className="coverage__list">
            {addressed.map((item) => (
              <li key={item.fact_key} className="coverage-row" data-testid={`coverage-${item.fact_key}`}>
                <div className="coverage-row__head">
                  <Check size={13} strokeWidth={2.2} aria-hidden="true" className="status-pass" />
                  <span className="coverage-row__label">{item.label}</span>

                  {/* §12 — WHO decided this requirement is covered. */}
                  <span className="coverage-row__covered">
                    <span className="coverage-row__by" data-testid={`coverage-by-${item.fact_key}`}>
                      Covered by: {item.addressed_by.join(", ")}
                    </span>
                    {citing(draft, item.fact_key).map((operation) => (
                      <span
                        key={`how-${operation.id}`}
                        className="coverage-row__how"
                        data-testid={`coverage-how-${item.fact_key}`}
                      >
                        {linkedManually(operation, item.fact_key)
                          ? "Linked manually by engineer"
                          : "Derived by Fabrivium from the source"}
                      </span>
                    ))}
                  </span>

                  {/* P0 §C1 — a link made in error is worse than a missing
                      one: coverage then reports a requirement as answered
                      when nothing answers it, which is the exact failure
                      this panel exists to catch. Taking it back is recorded
                      on the operation, like every other engineer edit. */}
                  {citing(draft, item.fact_key).map((operation) => (
                    <button
                      key={operation.id}
                      type="button"
                      className="fm-btn-tertiary coverage-row__unlink"
                      disabled={busy}
                      onClick={async () => {
                        setError(null);
                        try {
                          onResolved(
                            await unlinkRequirement(understanding, draft, operation.id, [
                              item.fact_key,
                            ]),
                          );
                        } catch (err) {
                          setError(describeRequestFailure(err));
                        }
                      }}
                      data-testid={`coverage-unlink-${item.fact_key}`}
                    >
                      Unlink from {operation.name}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** The operations that record themselves as answering this requirement. */
/** Did a person decide this requirement is covered, or did the planner derive it? */
export function linkedManually(
  operation: Pick<ProposedOperation, "basis" | "fact_status">,
  factKey: string,
): boolean {
  // An operation a person added is a person's decision about every
  // requirement it cites — there is no planner derivation behind it at all.
  if (operation.fact_status === "STATED") return true;

  const matches = (operation.basis ?? "").matchAll(
    /Engineer linked this operation to: (.+?)\.(?=\s|$)/g,
  );
  for (const match of matches) {
    if (match[1].split(",").some((key) => key.trim() === factKey)) return true;
  }
  return false;
}

function citing(draft: ManufacturingProcessDraft, factKey: string) {
  // Tolerant of a missing list: a draft stored by an earlier build, or a
  // fixture that does not set it, must not take the panel down.
  return draft.operations.filter((operation) => (operation.source_fact_keys ?? []).includes(factKey));
}
