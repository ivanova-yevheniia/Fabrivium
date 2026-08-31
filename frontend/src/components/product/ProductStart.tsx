import { useEffect, useState } from "react";
import { ArrowLeft, FileText, FileUp, Loader2, PencilLine } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import {
  buildConceptFromProduct,
  describeProduct,
  planProcess,
  uploadProductDocument,
  type BuildConceptResult,
  requirementCoverage,
} from "../../api/product";
import { useAppContext } from "../../state/AppContext";
import { ProcessDraftEditor } from "./ProcessDraftEditor";
import { RequirementCoverage } from "./RequirementCoverage";
import { ProductUnderstandingView } from "./ProductUnderstandingView";
import { EvidenceNote } from "../project/EvidenceStatus";

/** Phase 19 — the product-first entry point. */
export function ProductStart({
  onConceptBuilt,
  onBack,
}: {
  onConceptBuilt: (result: BuildConceptResult) => void;
  onBack?: () => void;
}) {
  const {
    state,
    setProductField,
    productUnderstood,
    setProcessDraft,
    setCoverage,
    loadExampleSpecification,
    recordArtifact,
    flushSave,
  } = useAppContext();
  const product = state.product;

  const [mode, setMode] = useState<"describe" | "upload">("describe");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // What the engineer has typed in the edit panel but not yet saved. Held
  // here rather than written straight into the project, because Cancel has
  // to mean something: with the fields bound directly to project state,
  // every keystroke was already committed and "Cancel" could only close a
  // form whose changes had happened.
  const [edit, setEdit] = useState<{ name: string; description: string } | null>(null);
  // The file input appears only on an explicit "Replace document". Showing
  // an empty one beside a document that is still perfectly present is what
  // made the panel read as "your PDF is gone".
  const [replacing, setReplacing] = useState(false);

  // Two different screens, and conflating them was the defect.
  //
  // Before facts exist, this is the ENTRY form: name the product, describe
  // it or upload a specification. Once facts exist, reopening it is an EDIT
  // of information that already has a source — and the entry form rendered
  // in that state was actively misleading. It showed a native file input
  // reading "no file selected" beneath a Product understanding panel built
  // from a PDF that was still perfectly present, so the only reasonable
  // reading was that the document had been lost.
  //
  // A native file input cannot be pre-filled with the current file (no
  // browser permits it, and faking one would be worse than the confusion it
  // replaced). So the edit panel does not try: it STATES what the current
  // document is, and offers to replace it.
  const showEntryForm = !product.understanding;
  const showEditPanel = Boolean(product.understanding) && product.editing;

  useEffect(() => {
    if (showEditPanel) {
      setEdit((current) => current ?? { name: product.name, description: product.description });
    } else {
      setEdit(null);
      setReplacing(false);
    }
    // `product.name`/`product.description` are read, not depended on: the
    // buffer is seeded once when the panel opens and must not be reset
    // underneath the engineer while they are typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showEditPanel]);

  async function run<T>(work: () => Promise<T>, then: (value: T) => void) {
    setBusy(true);
    setError(null);
    try {
      then(await work());
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }

  // The values are passed in rather than read off `product`, because the
  // edit panel holds its own buffer until Save: a re-read triggered from
  // there must use what the engineer just typed, not what the project still
  // holds one dispatch behind.
  const readDescription = (name: string, description: string) =>
    run(
      () => describeProduct(description, name || "Product"),
      (result) => {
        productUnderstood(result.understanding, result.model_used);
        // The name the extractor settled on wins where the engineer left the
        // field blank — an uploaded specification often states it, and
        // storing "Product" over the real name loses information the source
        if (!name.trim() && result.understanding.product_name) {
          setProductField({ name: result.understanding.product_name });
        }
        void flushSave();
      },
    );

  const readFile = (file: File, name = product.name) =>
    run(
      () => uploadProductDocument(file, name || "Product"),
      (result) => {
        productUnderstood(result.understanding, result.model_used);
        setProductField({
          // An uploaded document IS the source, so it becomes the recorded
          // description. Leaving the old text there would make the next
          // change-detection pass compare against a source nobody supplied.
          description: result.understanding.description || "",
          fromExample: false,
          editing: false,
          ...(name.trim() ? { name } : { name: result.understanding.product_name }),
        });
        void flushSave();
      },
    );

  const propose = () =>
    product.understanding &&
    run(() => planProcess(product.understanding!), (result) => {
      setProcessDraft(result.draft, null);
      recordArtifact("PROCESS_PROPOSAL");
      // Coverage is fetched with the plan rather than on demand: an
      // unanswered source requirement is something the engineer must see
      // immediately, not something they have to know to go looking for.
      void requirementCoverage(product.understanding!, result.draft)
        .then((coverage) => {
          setCoverage(coverage);
          recordArtifact("REQUIREMENT_COVERAGE");
        })
        .catch(() => setCoverage(null));
      void flushSave();
    });

  const build = () =>
    product.understanding &&
    product.process &&
    run(
      () =>
        buildConceptFromProduct(
          product.understanding!,
          product.process!,
          product.requirementsText,
          product.name || undefined,
        ),
      (result) => {
        recordArtifact("CONCEPT");
        onConceptBuilt(result);
      },
    );

  return (
    <div className="product-start" data-testid="product-start">
      <header className="product-start__head">
        <h1 className="product-start__title">What do you want to build?</h1>
        <p className="product-start__tagline">
          Start with the product. Fabrivium works out what manufacturing system it needs.
        </p>
      </header>

      {/* Once, at the top, whichever half of this screen is showing. */}
      <EvidenceNote
        artifact="PRODUCT_FACTS"
        // The cure for stale facts is the edit panel, whichever kind of
        // source they came from: it holds the source text, the current
        // document and the way to replace it. Offering "Re-read product
        // facts" here re-read `product.description`, which is EMPTY after a
        // PDF upload — the cure for a stale reading was a request the
        // backend would refuse.
        onAct={() => setProductField({ editing: true })}
        actionLabel="Edit product information"
      />

      {showEntryForm && (
        <section className="product-start__input">
          <div className="estimate__modes" role="tablist" aria-label="How to supply the product">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "describe"}
              className={`estimate__mode${mode === "describe" ? " estimate__mode--on" : ""}`}
              onClick={() => setMode("describe")}
              data-testid="product-mode-describe"
            >
              <PencilLine size={13} strokeWidth={2} aria-hidden="true" />
              Describe a product
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "upload"}
              className={`estimate__mode${mode === "upload" ? " estimate__mode--on" : ""}`}
              onClick={() => setMode("upload")}
              data-testid="product-mode-upload"
            >
              <FileUp size={13} strokeWidth={2} aria-hidden="true" />
              Upload documentation
            </button>
          </div>

          <label className="estimate__basis">
            <span className="fm-label">Product name</span>
            <input
              type="text"
              value={product.name}
              placeholder="e.g. Compact electronics controller"
              onChange={(e) => setProductField({ name: e.target.value })}
              data-testid="product-name"
            />
          </label>

          {mode === "describe" ? (
            <>
              <label className="estimate__basis">
                <span className="fm-label">Describe the product</span>
                <textarea
                  className="product-start__textarea"
                  value={product.description}
                  onChange={(e) => setProductField({ description: e.target.value, fromExample: false })}
                  placeholder="e.g. A controller in a plastic enclosure. The lid is secured with six screws. Two cables connect the PCB…"
                  data-testid="product-description"
                />
              </label>
              {product.fromExample && (
                <p className="product-start__supported" data-testid="product-example-notice">
                  <strong>Example specification.</strong> This is Fabrivium's own bundled document,
                  not a customer file. It is read by exactly the same extractor as a real one.
                </p>
              )}
              <div className="product-start__actions">
                <button
                  type="button"
                  className="fm-btn-primary fm-btn--auto"
                  onClick={() => readDescription(product.name, product.description)}
                  disabled={busy || !product.description.trim()}
                  aria-busy={busy}
                  data-testid="product-read-description"
                >
                  {busy && <Loader2 size={13} className="equipment__spin" aria-hidden="true" />}
                  Read product facts
                </button>
                <button
                  type="button"
                  className="fm-btn-secondary fm-btn--auto"
                  onClick={() => void loadExampleSpecification()}
                  disabled={busy}
                  data-testid="product-use-reference"
                >
                  Use the example specification
                </button>
              </div>

            </>
          ) : (
            <>
              <label className="estimate__basis">
                <span className="fm-label">Product documentation</span>
                <input
                  type="file"
                  accept=".pdf,.txt,application/pdf,text/plain"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void readFile(file);
                  }}
                  data-testid="product-file"
                />
              </label>
              {/* Named in words rather than shown as buttons that nearly work. */}
              <p className="product-start__supported" data-testid="product-supported">
                <strong>Read now:</strong> PDF with a text layer, plain text.{" "}
                <strong>Not read in this version:</strong> scanned pages, drawings and images,
                BOM spreadsheets, CAD. A page with no text is reported as visual content rather
                than guessed at.
              </p>
            </>
          )}
        </section>
      )}

      {showEditPanel && edit && (
        <section className="product-start__input" data-testid="product-edit-panel">
          <header className="product-start__edit-head">
            <p className="process__title">Edit product information</p>
            <p className="product__detail">
              The facts below were read from the document named here. Changing the name changes what
              this product is called; replacing the document changes what was read.
            </p>
          </header>

          <label className="estimate__basis">
            <span className="fm-label">Product name</span>
            <input
              type="text"
              value={edit.name}
              placeholder="e.g. Compact electronics controller"
              onChange={(e) => setEdit({ ...edit, name: e.target.value })}
              data-testid="product-name"
            />
          </label>

          {/* WHAT THE SOURCE IS, STATED. */}
          <div className="product-start__current-source" data-testid="product-current-document">
            <span className="fm-label">Current document</span>
            {product.understanding!.source_documents.map((document) => (
              <p key={document.document_id} className="product__source">
                <FileText size={13} strokeWidth={2} aria-hidden="true" />
                {document.name}
                {document.pages ? ` · ${document.pages} pages` : ""}
              </p>
            ))}
            {product.understanding!.source_documents.length === 0 && (
              <p className="product__detail">No document was supplied; the facts were read from text.</p>
            )}

            {replacing ? (
              <label className="estimate__basis">
                <span className="fm-label">Replacement document</span>
                <input
                  type="file"
                  accept=".pdf,.txt,application/pdf,text/plain"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    // Replacing the source IS the change. It re-reads
                    // immediately, which drops the process and coverage
                    // derived from the old facts rather than leaving them
                    // standing under a new document.
                    if (file) void readFile(file, edit.name);
                  }}
                  data-testid="product-file"
                />
                <p className="product-start__supported" data-testid="product-supported">
                  <strong>Read now:</strong> PDF with a text layer, plain text.{" "}
                  <strong>Not read in this version:</strong> scanned pages, drawings and images, BOM
                  spreadsheets, CAD. Choosing a file re-reads the product immediately: the proposed
                  process and its coverage are derived from the old facts and are dropped, not kept.
                </p>
                <button
                  type="button"
                  className="fm-btn-tertiary fm-btn--auto"
                  onClick={() => setReplacing(false)}
                  disabled={busy}
                  data-testid="product-replace-cancel"
                >
                  Keep the current document
                </button>
              </label>
            ) : (
              <button
                type="button"
                className="fm-btn-secondary fm-btn--auto"
                onClick={() => setReplacing(true)}
                disabled={busy}
                data-testid="product-replace-document"
              >
                <FileUp size={13} strokeWidth={2} aria-hidden="true" />
                Replace document
              </button>
            )}
          </div>

          {/* Only where there is source TEXT to edit. */}
          {product.description.trim() !== "" && (
            <label className="estimate__basis">
              <span className="fm-label">Source text</span>
              <textarea
                className="product-start__textarea"
                value={edit.description}
                onChange={(e) => setEdit({ ...edit, description: e.target.value })}
                data-testid="product-description"
              />
            </label>
          )}

          <div className="product-start__actions">
            <button
              type="button"
              className="fm-btn-primary fm-btn--auto"
              onClick={() => {
                // A NAME IS NOT A SOURCE. Renaming the product changes what
                // it is called and nothing about what was read from the
                // specification, so the facts stay current and no re-read is
                // asked for. `Channel.PRODUCT_SOURCE` no longer carries the
                // name, which is what makes that true of the badge as well
                // as of this screen.
                setProductField({
                  name: edit.name,
                  description: edit.description,
                  editing: false,
                  understanding: {
                    ...product.understanding!,
                    product_name: edit.name.trim() || product.understanding!.product_name,
                  },
                });
                setEdit(null);
                void flushSave();
              }}
              disabled={busy}
              data-testid="product-edit-save"
            >
              Save changes
            </button>
            {/* The source text really is a source. */}
            {product.description.trim() !== "" && edit.description !== product.description && (
              <button
                type="button"
                className="fm-btn-secondary fm-btn--auto"
                onClick={() => {
                  setProductField({ name: edit.name, description: edit.description, editing: false });
                  setEdit(null);
                  void readDescription(edit.name, edit.description);
                }}
                disabled={busy || !edit.description.trim()}
                aria-busy={busy}
                data-testid="product-read-description"
              >
                {busy && <Loader2 size={13} className="equipment__spin" aria-hidden="true" />}
                Save and re-read product facts
              </button>
            )}
            <button
              type="button"
              className="fm-btn-tertiary fm-btn--auto"
              onClick={() => {
                setEdit(null);
                setReplacing(false);
                setProductField({ editing: false });
              }}
              disabled={busy}
              data-testid="product-edit-cancel"
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {product.understanding && !product.process && (
        <ProductUnderstandingView
          understanding={product.understanding}
          modelUsed={product.modelUsed}
          onContinue={propose}
          onEditProduct={() => setProductField({ editing: !product.editing })}
          busy={busy}
        />
      )}

      {product.understanding && product.process && (
        <>
          {/* Order matters here, and it is presentational only. */}
          <ProcessDraftEditor
            understanding={product.understanding}
            draft={product.process}
            onChange={(next) => {
              setProcessDraft(next);
              // Accepting, rejecting or reordering can change what is
              // covered — a rejected operation may have been the only thing
              // answering a requirement.
              void requirementCoverage(product.understanding!, next)
                .then(setCoverage)
                .catch(() => undefined);
            }}
            onDraftAndCoverage={(next, coverage) => setProcessDraft(next, coverage)}
            onBuild={build}
            busy={busy}
            buildBlocked={!product.requirementsText.trim()}
            error={error}
            approvalBlocked={product.coverage?.approval_blocked ?? false}
          />

          {product.coverage && (
            <RequirementCoverage
              coverage={product.coverage}
              understanding={product.understanding}
              draft={product.process}
              busy={busy}
              onResolved={(result) => setProcessDraft(result.draft, result.coverage)}
            />
          )}

          <section className="product-start__requirements" data-testid="production-requirements">
            <p className="process__title">Production requirements</p>
            <p className="product__detail">
              Separate from the product: how much, in what space, with which workforce.
            </p>
            <textarea
              className="product-start__textarea"
              value={product.requirementsText}
              onChange={(e) => setProductField({ requirementsText: e.target.value })}
              placeholder="e.g. 600 units per day across 2 shifts of 8 hours. 24 by 15 meters. 6 operators."
              data-testid="production-requirements-input"
            />
          </section>

          <div className="product-start__actions">
            <button
              type="button"
              className="fm-btn-tertiary fm-btn--auto"
              onClick={() => setProductField({ editing: true })}
              data-testid="product-edit-information-late"
            >
              Edit product information
            </button>
          </div>
        </>
      )}

      {error && !product.process && (
        <p className="estimate__error" data-testid="product-error">
          {error}
        </p>
      )}
      {product.error && (
        <p className="estimate__error" data-testid="product-state-error">
          {product.error}
        </p>
      )}

      {onBack && (
        <div className="estimate__footer">
          <button type="button" className="fm-btn-tertiary" onClick={onBack} data-testid="product-back">
            <ArrowLeft size={13} strokeWidth={2} aria-hidden="true" />
            Back
          </button>
        </div>
      )}
    </div>
  );
}
