import { useState } from "react";
import { ArrowDown, ArrowUp, Check, HelpCircle, Loader2, Pencil, Plus, RotateCcw, X } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import {
  addOperation,
  editOperation,
  reorderOperations,
  restoreOperation,
  type CoverageReport,
  type ManufacturingProcessDraft,
  type ProductUnderstanding,
  type ProposedOperation,
} from "../../api/product";
import {
  ProcessFamilySelect,
  defaultProcessType,
  useProcessFamilies,
} from "./ProcessFamilySelect";

/** Phase 19 — the engineer reviews the proposed route. */
export function ProcessDraftEditor({
  understanding,
  draft,
  onChange,
  onDraftAndCoverage,
  onBuild,
  busy,
  error,
  approvalBlocked = false,
  buildBlocked = false,
}: {
  /** Required for every audited edit: the backend recomputes coverage
   * against the source in the same response, so the consequence of an edit
   * arrives with the edit rather than having to be looked up. */
  understanding: ProductUnderstanding;
  draft: ManufacturingProcessDraft;
  onChange: (draft: ManufacturingProcessDraft) => void;
  /** Used by the audited edits, which return the recomputed coverage too. */
  onDraftAndCoverage?: (draft: ManufacturingProcessDraft, coverage: CoverageReport) => void;
  onBuild: () => void;
  /** A request is in flight. */
  busy?: boolean;
  error?: string | null;
  /** True while the source states a requirement no operation answers. */
  approvalBlocked?: boolean;
  /** True while something OTHER than the process blocks the build — today,
   * an empty production-requirements box.
   *
   * Kept apart from `busy` deliberately. It used to be folded into it by the
   * caller, which was harmless while the only control `busy` disabled was
   * the build button; once review gained restore, edit and reorder it meant
   * an engineer could not touch their own process until they had typed the
   * production target, which is a different question entirely. */
  buildBlocked?: boolean;
}) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [working, setWorking] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const pending = draft.operations.filter((op) => op.status === "PROPOSED");
  // MODIFIED counts as accepted: an operation the engineer edited is one
  // they have taken responsibility for, and the backend builds it.
  const accepted = draft.operations.filter(
    (op) => op.status === "ACCEPTED" || op.status === "MODIFIED",
  );

  function replace(operations: ProposedOperation[]) {
    onChange({ ...draft, operations });
  }

  /** Run one audited edit, and adopt both halves of the answer. */
  async function audited(
    work: () => Promise<{ draft: ManufacturingProcessDraft; coverage: CoverageReport }>,
  ) {
    setWorking(true);
    setEditError(null);
    try {
      const result = await work();
      if (onDraftAndCoverage) onDraftAndCoverage(result.draft, result.coverage);
      else onChange(result.draft);
    } catch (err) {
      setEditError(describeRequestFailure(err));
    } finally {
      setWorking(false);
    }
  }

  function setStatus(id: string, status: ProposedOperation["status"]) {
    replace(
      draft.operations.map((op) =>
        op.id === id
          ? {
              ...op,
              status,
              // Acceptance is what turns an inference into something the
              // engineer stands behind; the two move together.
              fact_status: status === "ACCEPTED" ? "ENGINEER_VERIFIED" : op.fact_status,
            }
          : op,
      ),
    );
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= draft.operations.length) return;
    const order = draft.operations.map((op) => op.id);
    [order[index], order[target]] = [order[target], order[index]];
    void audited(() => reorderOperations(understanding, draft, order));
  }

  const disabled = busy || working;

  return (
    <section className="process" data-testid="process-draft">
      <header className="process__head">
        <div>
          <p className="process__title">Proposed manufacturing process</p>
          <p className="product__detail">
            Derived from the product facts. Review each operation before Fabrivium builds a
            concept from it — and come back and change it whenever the process changes.
          </p>
        </div>
        <span className="process__method" data-testid="process-method">
          {draft.method === "LANGUAGE_MODEL"
            ? `Proposed with ${draft.model_name ?? "a language model"}`
            : "Proposed by Fabrivium process rules"}
        </span>
      </header>

      <ol className="process__list">
        {draft.operations.map((operation, index) => (
          <OperationRow
            key={operation.id}
            operation={operation}
            index={index}
            total={draft.operations.length}
            busy={disabled}
            editing={editingId === operation.id}
            onEditToggle={() => setEditingId(editingId === operation.id ? null : operation.id)}
            onEditSubmit={(changes) => {
              setEditingId(null);
              void audited(() => editOperation(understanding, draft, operation.id, changes));
            }}
            onAccept={() => setStatus(operation.id, "ACCEPTED")}
            onReject={() => setStatus(operation.id, "REJECTED")}
            onRestore={() => void audited(() => restoreOperation(understanding, draft, operation.id))}
            onMove={(delta) => move(index, delta)}
          />
        ))}
      </ol>

      {adding ? (
        <AddOperationForm
          busy={disabled}
          onCancel={() => setAdding(false)}
          onSubmit={(fields) => {
            setAdding(false);
            void audited(() => addOperation(understanding, draft, fields));
          }}
        />
      ) : (
        <button
          type="button"
          className="fm-btn-tertiary fm-btn--auto"
          onClick={() => setAdding(true)}
          disabled={disabled}
          data-testid="process-add-operation"
        >
          <Plus size={13} strokeWidth={2.2} aria-hidden="true" />
          Add an operation
        </button>
      )}

      {draft.open_questions.length > 0 && (
        <div className="process__questions" data-testid="process-questions">
          <p className="fm-label">Open questions</p>
          <ul>
            {draft.open_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="process__actions">
        <button
          type="button"
          className="fm-btn-secondary fm-btn--auto"
          onClick={() => replace(draft.operations.map((op) => (op.status === "PROPOSED" ? { ...op, status: "ACCEPTED", fact_status: "ENGINEER_VERIFIED" } : op)))}
          disabled={disabled || pending.length === 0}
          data-testid="process-accept-all"
        >
          Accept all {pending.length > 0 ? `(${pending.length})` : ""}
        </button>
        <button
          type="button"
          className="fm-btn-primary fm-btn--auto"
          onClick={onBuild}
          disabled={
            disabled || buildBlocked || pending.length > 0 || accepted.length === 0 || approvalBlocked
          }
          data-testid="process-build-concept"
        >
          {working && <Loader2 size={13} className="equipment__spin" aria-hidden="true" />}
          {pending.length > 0
            ? `${pending.length} still to review`
            : approvalBlocked
              ? "Unresolved source requirements"
              : "Build factory concept"}
        </button>
      </div>

      {(error || editError) && (
        <p className="estimate__error" data-testid="process-error">
          {error ?? editError}
        </p>
      )}
    </section>
  );
}

/** What produced this operation, in the words the backend actually used. */
const DERIVATION_LABELS: Record<string, string> = {
  //: Produced by Fabrivium's process rules from a named product fact. No
  //: model involved — the "Why" button shows the fact and the rule.
  RULE_DERIVED: "Fabrivium rule",
  //: A language model read it out of, or inferred it from, the source.
  AI_INFERRED: "AI-inferred",
  //: Read out of the document by deterministic extraction.
  EXTRACTED: "Document",
  //: The engineer added or edited this operation themselves.
  STATED: "Engineer",
  ENGINEER_VERIFIED: "Verified",
  CONFLICT: "Conflict",
  UNKNOWN: "Unknown",
};

function OperationRow({
  operation,
  index,
  total,
  busy,
  editing,
  onEditToggle,
  onEditSubmit,
  onAccept,
  onReject,
  onRestore,
  onMove,
}: {
  operation: ProposedOperation;
  index: number;
  total: number;
  busy: boolean;
  editing: boolean;
  onEditToggle: () => void;
  onEditSubmit: (changes: { name?: string; description?: string; repeated_operations?: number }) => void;
  onAccept: () => void;
  onReject: () => void;
  onRestore: () => void;
  onMove: (delta: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const evidence = operation.evidence[0];
  const rejected = operation.status === "REJECTED";

  return (
    <li
      className={`process__op process__op--${operation.status.toLowerCase()}`}
      data-testid={`operation-${operation.id}`}
    >
      <span className="process__op-index fm-mono">{index + 1}</span>

      <div className="process__op-body">
        <p className="process__op-name">{operation.name}</p>
        <p className="product__detail">{operation.description}</p>
        {operation.repeated_operations != null && (
          <p className="product__detail" data-testid={`operation-repeats-${operation.id}`}>
            {operation.repeated_operations}× per unit
          </p>
        )}
      </div>

      <span className="process__op-provenance">
        {/* WHO PUT THIS OPERATION HERE, AND WHO CHECKED IT — two questions,
            two answers, and they used to collapse into one word.
            An operation the engineer added themselves reached ACCEPTED the
            moment they added it (see `process_editing.add_operation`), so
            the card read "Verified" and was indistinguishable at a glance
            from one Fabrivium derived from the source and a person then
            reviewed. Those are different provenance, and the difference is
            exactly what a reviewer asks about. `fact_status === "STATED"` is
            the same predicate the coverage panel uses for "Linked manually
            by engineer". */}
        {operation.fact_status === "STATED" && (
          <span
            className="process__op-origin"
            data-testid={`operation-origin-${operation.id}`}
          >
            Engineer added
          </span>
        )}
        <span
          className={`product__status product__status--${operation.fact_status.toLowerCase()}`}
          data-testid={`operation-status-${operation.id}`}
        >
          {operation.status === "ACCEPTED"
            ? "Verified"
            : rejected
              ? "Rejected"
              : (DERIVATION_LABELS[operation.fact_status] ?? operation.fact_status)}
        </span>
      </span>

      <button
        type="button"
        className="product__evidence-toggle"
        aria-expanded={open}
        aria-label={`Why ${operation.name} was proposed`}
        onClick={() => setOpen((o) => !o)}
        data-testid={`operation-why-${operation.id}`}
      >
        <HelpCircle size={13} aria-hidden="true" />
        Why
      </button>

      <div className="process__op-actions">
        <button
          type="button"
          className="process__icon"
          onClick={() => onMove(-1)}
          disabled={busy || index === 0}
          aria-label="Move earlier"
          data-testid={`operation-up-${operation.id}`}
        >
          <ArrowUp size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="process__icon"
          onClick={() => onMove(1)}
          disabled={busy || index === total - 1}
          aria-label="Move later"
          data-testid={`operation-down-${operation.id}`}
        >
          <ArrowDown size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="process__icon"
          onClick={onEditToggle}
          disabled={busy}
          aria-label={`Edit ${operation.name}`}
          aria-expanded={editing}
          data-testid={`operation-edit-${operation.id}`}
        >
          <Pencil size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="process__icon process__icon--accept"
          onClick={onAccept}
          disabled={busy || operation.status === "ACCEPTED"}
          aria-label="Accept"
          data-testid={`operation-accept-${operation.id}`}
        >
          <Check size={13} aria-hidden="true" />
        </button>
        {rejected ? (
          /* Rejection was always meant to be reversible. */
          <button
            type="button"
            className="process__icon"
            onClick={onRestore}
            disabled={busy}
            aria-label="Restore"
            data-testid={`operation-restore-${operation.id}`}
          >
            <RotateCcw size={13} aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className="process__icon process__icon--reject"
            onClick={onReject}
            disabled={busy}
            aria-label="Reject"
            data-testid={`operation-reject-${operation.id}`}
          >
            <X size={13} aria-hidden="true" />
          </button>
        )}
      </div>

      {editing && (
        <EditOperationForm operation={operation} busy={busy} onSubmit={onEditSubmit} onCancel={onEditToggle} />
      )}

      {open && (
        <p className="process__op-why" data-testid={`operation-basis-${operation.id}`}>
          {operation.basis}
          {operation.source_fact_keys.length > 0 && (
            <span className="product__detail" data-testid={`operation-links-${operation.id}`}>
              {" "}
              Answers: {operation.source_fact_keys.join(", ")}.
            </span>
          )}
          {evidence && (
            <>
              {" "}
              <span className="product__detail">
                {evidence.document_name}
                {evidence.page ? `, page ${evidence.page}` : ""}
                {evidence.quote ? ` — “${evidence.quote}”` : ""}
              </span>
            </>
          )}
        </p>
      )}
    </li>
  );
}

/** Correcting an operation. */
function EditOperationForm({
  operation,
  busy,
  onSubmit,
  onCancel,
}: {
  operation: ProposedOperation;
  busy: boolean;
  onSubmit: (changes: { name?: string; description?: string; repeated_operations?: number }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(operation.name);
  const [description, setDescription] = useState(operation.description);
  const [repeats, setRepeats] = useState(
    operation.repeated_operations == null ? "" : String(operation.repeated_operations),
  );

  const repeatsValue = repeats.trim() === "" ? undefined : Number(repeats);
  const repeatsInvalid = repeatsValue !== undefined && (!Number.isFinite(repeatsValue) || repeatsValue < 1);

  return (
    <div className="process__op-edit" data-testid={`operation-edit-form-${operation.id}`}>
      <label className="estimate__basis">
        <span className="fm-label">Operation name</span>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          data-testid={`operation-edit-name-${operation.id}`}
        />
      </label>
      <label className="estimate__basis">
        <span className="fm-label">What this operation does</span>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          data-testid={`operation-edit-description-${operation.id}`}
        />
      </label>
      <label className="estimate__basis">
        <span className="fm-label">Repeated operations per unit</span>
        <input
          type="number"
          min="1"
          value={repeats}
          onChange={(e) => setRepeats(e.target.value)}
          data-testid={`operation-edit-repeats-${operation.id}`}
        />
      </label>
      <div className="process__actions">
        <button
          type="button"
          className="fm-btn-primary fm-btn--auto"
          disabled={busy || !name.trim() || repeatsInvalid}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              description: description.trim(),
              ...(repeatsValue === undefined ? {} : { repeated_operations: repeatsValue }),
            })
          }
          data-testid={`operation-edit-save-${operation.id}`}
        >
          Save changes
        </button>
        <button type="button" className="fm-btn-tertiary fm-btn--auto" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/** An operation the engineer decided the process needs. */
function AddOperationForm({
  busy,
  onSubmit,
  onCancel,
}: {
  busy: boolean;
  onSubmit: (fields: {
    name: string;
    process_type: string;
    basis: string;
    repeated_operations?: number | null;
  }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const families = useProcessFamilies();
  // Empty until the catalog arrives; `ready` gates on it, so this form can
  // never submit a family the frontend made up.
  const [chosenType, setChosenType] = useState("");
  const processType = chosenType || defaultProcessType(families);
  const [basis, setBasis] = useState("");
  const [repeats, setRepeats] = useState("");

  const ready = name.trim() && basis.trim() && processType;

  return (
    <div className="process__op-edit" data-testid="process-add-form">
      <label className="estimate__basis">
        <span className="fm-label">Operation name</span>
        <input
          type="text"
          value={name}
          placeholder="e.g. Label application"
          onChange={(e) => setName(e.target.value)}
          data-testid="process-add-name"
        />
      </label>
      <label className="estimate__basis">
        <span className="fm-label">Process family</span>
        {/* The families the concept builder and the reference bands
            recognise, served by the backend rather than repeated here. The
            list that used to live at this line offered six entries, of
            which `labeling` and `testing` were not families at all: neither
            matched any reference band, equipment map or station asset, so
            an operation created with either one quietly found no data — the
            exact degradation the list claimed to prevent. */}
        <ProcessFamilySelect
          value={processType}
          onChange={setChosenType}
          state={families}
          testId="process-add-type"
        />
      </label>
      <label className="estimate__basis">
        <span className="fm-label">Why does this operation exist?</span>
        <input
          type="text"
          value={basis}
          placeholder="e.g. the specification requires a unique identification label"
          onChange={(e) => setBasis(e.target.value)}
          data-testid="process-add-basis"
        />
      </label>
      <label className="estimate__basis">
        <span className="fm-label">Repeated operations per unit (optional)</span>
        <input
          type="number"
          min="1"
          value={repeats}
          onChange={(e) => setRepeats(e.target.value)}
          data-testid="process-add-repeats"
        />
      </label>
      <div className="process__actions">
        <button
          type="button"
          className="fm-btn-primary fm-btn--auto"
          disabled={busy || !ready}
          onClick={() =>
            onSubmit({
              name: name.trim(),
              process_type: processType,
              basis: basis.trim(),
              repeated_operations: repeats.trim() === "" ? null : Number(repeats),
            })
          }
          data-testid="process-add-submit"
        >
          Add operation
        </button>
        <button type="button" className="fm-btn-tertiary fm-btn--auto" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
