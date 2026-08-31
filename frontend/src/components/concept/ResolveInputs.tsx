import { useCallback, useEffect, useMemo, useState } from "react";
import { Calculator, Check, ChevronRight, Info, Loader2, X } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import {
  bufferSensitivity,
  resolutionPlan,
  resolveInput,
  type BufferSensitivity,
  type Necessity,
  type ResolutionAction,
  type ResolutionPlan,
  type ResolvableInput,
} from "../../api/concept";
import { applyExampleData, useExampleDataForUnresolved } from "../../api/concept";
import type { EstimateMethod, EstimatedRange } from "../../api/uncertainty";
import type { FactoryConceptDraft } from "../../api/types";
import { SourceBadge } from "./SourceBadge";
import { Overlay } from "../layout/Overlay";

/** Resolve engineering inputs — real data first. */

const NECESSITY_LABEL: Record<Necessity, string> = {
  BLOCKS_SIMULATION: "Required to simulate",
  AFFECTS_LAYOUT: "Layout only",
  COMMERCIAL_ONLY: "Commercial only",
  HAS_DEFAULT: "Has a default",
};

const ACTION_LABEL: Record<ResolutionAction, string> = {
  ENGINEER_INPUT: "Enter value",
  ESTIMATE: "Estimate",
  EXTERNAL_DATA: "Use published data",
  ENTER_QUOTE: "Enter quote",
  USE_EXAMPLE_DATA: "Use demo value",
  LEAVE_UNKNOWN: "Leave unknown",
};

function formatValue(input: ResolvableInput): string {
  if (input.value === null) return input.quote_required ? "Quote required" : "Not established";
  const n = input.value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (input.unit === "€") return `€${n}`;
  return input.unit ? `${n} ${input.unit}` : n;
}

/** How the number was actually arrived at, named for the MECHANISM. */
const METHOD_LABEL: Record<EstimateMethod, string> = {
  DERIVED: "Arithmetic on values the concept already holds",
  REFERENCE_DATA: "Fabrivium reference dataset",
  LANGUAGE_MODEL: "Language model, from the engineer's description",
  LOCAL_HEURISTIC: "Fabrivium reference bands (deterministic)",
  ENGINEER: "Entered by the engineer",
};

/** The estimate contract, made inspectable — §2 of the transparency phase. */
function EstimateContract({ estimate, inputKey }: { estimate: EstimatedRange; inputKey: string }) {
  const hasRange = estimate.low !== estimate.high;
  return (
    <dl className="resolve-row__estimate" data-testid={`resolve-estimate-${inputKey}`}>
      <div>
        <dt>Method</dt>
        <dd data-testid={`resolve-estimate-method-${inputKey}`}>
          {estimate.method === "LANGUAGE_MODEL" && estimate.model_name
            ? `${METHOD_LABEL.LANGUAGE_MODEL} (${estimate.model_name})`
            : METHOD_LABEL[estimate.method]}
        </dd>
      </div>
      <div>
        <dt>Basis</dt>
        <dd>{estimate.basis}</dd>
      </div>
      {hasRange && (
        <div>
          <dt>Plausible range</dt>
          <dd className="fm-mono">
            {estimate.low}–{estimate.high} {estimate.unit}
          </dd>
        </div>
      )}
      <div>
        <dt>Working value</dt>
        <dd className="fm-mono">
          {estimate.working_value} {estimate.unit}
        </dd>
      </div>
      <div>
        <dt>Confidence</dt>
        <dd>{estimate.confidence}</dd>
      </div>
      <div>
        <dt>Status</dt>
        {/* Says plainly that this is not a specification and that the
            engineer may replace it — §8's "can I change it?". */}
        <dd>Preliminary assumption for concept simulation. Enter a value to override it.</dd>
      </div>
    </dl>
  );
}

/** One value, with everything needed to decide what to do about it. */
function InputRow({
  input,
  busy,
  onResolve,
  onEstimate,
  onUseExample,
  isExampleProject = false,
}: {
  input: ResolvableInput;
  busy: boolean;
  onResolve: (key: string, value: number | null, detail: string | null) => void;
  onEstimate: (input: ResolvableInput) => void;
  onUseExample: (input: ResolvableInput) => void;
  /** True only inside the bundled example project. */
  isExampleProject?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draftValue, setDraftValue] = useState("");
  const [note, setNote] = useState("");
  const [showWhy, setShowWhy] = useState(false);

  function commit() {
    const parsed = Number(draftValue);
    if (draftValue.trim() === "" || Number.isNaN(parsed)) return;
    onResolve(input.key, parsed, note.trim() || null);
    setEditing(false);
    setNote("");
  }

  return (
    <li className="resolve-row" data-testid={`resolve-row-${input.key}`}>
      <div className="resolve-row__head">
        <span className="resolve-row__label">{input.label}</span>
        <span
          className={`resolve-row__value fm-mono${input.resolved ? "" : " resolve-row__value--absent"}`}
          data-testid={`resolve-value-${input.key}`}
        >
          {formatValue(input)}
        </span>
        <SourceBadge source={input.source} detail={input.detail} />
        <span
          className={`resolve-row__necessity resolve-row__necessity--${input.necessity.toLowerCase()}`}
          data-testid={`resolve-necessity-${input.key}`}
        >
          {NECESSITY_LABEL[input.necessity]}
        </span>
        {/* The panel behind this now carries the estimate contract as well as
            the consequence, so for an estimated value the label says what it
            opens rather than only "why it matters". */}
        <button
          type="button"
          className="provenance__toggle"
          aria-expanded={showWhy}
          aria-label={
            input.estimate
              ? `Why ${input.label} is this value, and what depends on it`
              : `Why ${input.label} matters`
          }
          onClick={() => setShowWhy((open) => !open)}
          data-testid={`resolve-why-${input.key}`}
        >
          <Info size={13} strokeWidth={2} aria-hidden="true" />
        </button>
      </div>

      {showWhy && (
        <div className="resolve-row__consequence" role="note" data-testid={`resolve-consequence-${input.key}`}>
          <p>
            {input.consequence}
            {input.detail && !input.estimate && (
              <>
                {" "}
                <span className="resolve-row__origin">Current value from: {input.detail}.</span>
              </>
            )}
          </p>
          {/* The estimate contract, only where the value actually is one. */}
          {input.estimate && <EstimateContract estimate={input.estimate} inputKey={input.key} />}
          {input.superseded && (
            <p className="resolve-row__superseded" data-testid={`resolve-superseded-${input.key}`}>
              {input.superseded}.
            </p>
          )}
        </div>
      )}

      {editing ? (
        <div className="resolve-row__editor">
          <input
            className="fm-input"
            type="number"
            value={draftValue}
            autoFocus
            onChange={(event) => setDraftValue(event.target.value)}
            aria-label={`${input.label} value`}
            data-testid={`resolve-input-${input.key}`}
          />
          <input
            className="fm-input"
            type="text"
            value={note}
            placeholder="Where does this come from?"
            onChange={(event) => setNote(event.target.value)}
            aria-label={`${input.label} basis`}
            data-testid={`resolve-basis-${input.key}`}
          />
          <button
            type="button"
            className="fm-btn-primary"
            onClick={commit}
            data-testid={`resolve-save-${input.key}`}
          >
            <Check size={13} strokeWidth={2.2} aria-hidden="true" />
            Save
          </button>
          <button type="button" className="fm-btn-tertiary" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="resolve-row__actions">
          {input.actions.map((action) => {
            const label = ACTION_LABEL[action];
            if (action === "ENGINEER_INPUT" || action === "ENTER_QUOTE") {
              return (
                <button
                  key={action}
                  type="button"
                  className="fm-btn-tertiary"
                  disabled={busy}
                  onClick={() => {
                    setDraftValue(input.value === null ? "" : String(input.value));
                    setEditing(true);
                  }}
                  data-testid={`resolve-action-${action}-${input.key}`}
                >
                  {label}
                </button>
              );
            }
            if (action === "ESTIMATE") {
              return (
                <button
                  key={action}
                  type="button"
                  className="fm-btn-tertiary"
                  disabled={busy}
                  onClick={() => onEstimate(input)}
                  data-testid={`resolve-action-ESTIMATE-${input.key}`}
                >
                  {label}
                </button>
              );
            }
            if (action === "USE_EXAMPLE_DATA") {
              // Offered ONLY inside the bundled example project.
              //
              // This action fills a station from the Electronics Assembly
              // Demo Dataset, matched by process family. Inside the example
              // project that is exactly what it says it is. Outside it, on a
              // mechanical actuator or a filling line, it offers to write an
              // electronics demo's measured cycle time into a different
              // product — and the value is honestly badged EXAMPLE_DATA, so
              // nothing is falsified, but a reader scanning KPIs rather than
              // provenance badges would not notice. Found by walking the
              // mechanical scenario through the real UI: the button was
              // sitting on an aluminium housing.
              //
              // The estimator, "Enter value" and "Leave unknown" remain, so
              // nothing an engineer legitimately needs is removed.
              if (!isExampleProject) return null;
              return (
                <button
                  key={action}
                  type="button"
                  className="fm-btn-tertiary"
                  disabled={busy}
                  onClick={() => onUseExample(input)}
                  data-testid={`resolve-action-USE_EXAMPLE_DATA-${input.key}`}
                >
                  {label}
                </button>
              );
            }
            if (action === "LEAVE_UNKNOWN") {
              return (
                <button
                  key={action}
                  type="button"
                  className="fm-btn-tertiary"
                  disabled={busy || !input.resolved}
                  onClick={() => onResolve(input.key, null, null)}
                  data-testid={`resolve-action-LEAVE_UNKNOWN-${input.key}`}
                >
                  {label}
                </button>
              );
            }
            // EXTERNAL_DATA — equipment discovery owns published prices, and
            // it is reached from the verified concept rather than from here.
            return (
              <span key={action} className="resolve-row__hint" data-testid={`resolve-hint-${action}-${input.key}`}>
                {label}: via equipment discovery
              </span>
            );
          })}
        </div>
      )}
    </li>
  );
}

/** One station, with every value that belongs to it in one place. */
function StationGroup({
  stageId,
  label,
  inputs,
  busy,
  onResolve,
  onEstimate,
  onUseExample,
  isExampleProject = false,
}: {
  stageId: string;
  label: string;
  inputs: ResolvableInput[];
  busy: boolean;
  onResolve: (key: string, value: number | null, detail: string | null) => void;
  onEstimate: (input: ResolvableInput) => void;
  onUseExample: (input: ResolvableInput) => void;
  isExampleProject?: boolean;
}) {
  const unresolved = inputs.filter((input) => !input.resolved);
  // WHAT ACTUALLY BLOCKS A RUN, AND WHAT MERELY IS NOT FILLED IN (G12).
  //
  // The header used to say "6 not established" over a station where two
  // values stop the simulator and four do not: a price nobody has quoted, a
  // footprint the layout reads and the simulator never does, a buffer with a
  // stated default. Counting them together makes an engineer chase four
  // things that block nothing — or, far worse, teaches them that the number
  // in this chip can be ignored, on a screen whose whole job is to say what
  // is still missing.
  //
  // The split is read from `necessity`, which the backend already sets and
  // every row already shows. Nothing is re-derived here, so the chip cannot
  // disagree with the rows under it.
  const blocking = unresolved.filter((input) => input.necessity === "BLOCKS_SIMULATION");
  const otherUnresolved = unresolved.length - blocking.length;
  // An estimate is a resolved value and an OPEN QUESTION. It has a number,
  // so it does not count as unresolved, and it is a range Fabrivium
  // proposed rather than something anybody established — which makes it
  // precisely what an engineer opening this panel needs to look at. A
  // station holding one is therefore expanded like a station holding a gap.
  const estimated = inputs.filter((input) => input.estimate !== null);
  const needsAttention = unresolved.length + estimated.length;
  const [open, setOpen] = useState(needsAttention > 0);

  // A station that BECOMES incomplete must open itself. Resolving the last
  // gap does not close it — an engineer working through a station should not
  // have it fold up underneath them.
  useEffect(() => {
    if (needsAttention > 0) setOpen(true);
  }, [needsAttention]);

  const cycle = inputs.find((input) => input.key.endsWith(".cycle_time"));
  const capacity = inputs.find((input) => input.key.endsWith(".capacity"));
  // How many of this station's values nobody has actually established.
  // Stated on the COLLAPSED row, so a station can be closed for length
  // without its provenance being closed with it: a line whose cycle times
  // all came from the demo dataset must not read as settled just because
  // every field has a number in it.
  const assumed = inputs.filter(
    (input) => input.resolved && (input.source === "EXAMPLE_DATA" || input.source === "CATALOG_DEFAULT"),
  ).length;

  return (
    <div className="resolve-station" data-testid={`resolve-station-${stageId}`} data-open={open}>
      <button
        type="button"
        className="resolve-station__head"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        data-testid={`resolve-station-toggle-${stageId}`}
      >
        <ChevronRight
          size={13}
          strokeWidth={2.4}
          aria-hidden="true"
          className="resolve-station__chevron"
        />
        <span className="resolve-station__name">{label}</span>
        <span className="resolve-station__summary fm-mono">
          {cycle && cycle.value !== null ? `${cycle.value} s` : "cycle time not established"}
          {capacity && capacity.value !== null ? ` · capacity ${capacity.value}` : ""}
        </span>
        {unresolved.length > 0 ? (
          <span className="resolve-station__gaps" data-testid={`resolve-station-gaps-${stageId}`}>
            {blocking.length > 0 && (
              <span
                className="resolve-station__gaps-blocking"
                data-testid={`resolve-station-blocking-${stageId}`}
              >
                {blocking.length} needed to simulate
              </span>
            )}
            {blocking.length > 0 && otherUnresolved > 0 && (
              <span aria-hidden="true"> · </span>
            )}
            {otherUnresolved > 0 && (
              <span
                className="resolve-station__gaps-other"
                data-testid={`resolve-station-other-${stageId}`}
              >
                {blocking.length > 0
                  ? `${otherUnresolved} other unresolved`
                  : `${otherUnresolved} unresolved, none needed to simulate`}
              </span>
            )}
          </span>
        ) : assumed > 0 ? (
          <span className="resolve-station__gaps" data-testid={`resolve-station-assumed-${stageId}`}>
            {assumed} assumed
          </span>
        ) : (
          <span className="resolve-station__complete">All values supplied</span>
        )}
      </button>

      {open && (
        <ul className="resolve-list">
          {inputs.map((input) => (
            <InputRow
              key={input.key}
              input={input}
              busy={busy}
              onResolve={onResolve}
              onEstimate={onEstimate}
              onUseExample={onUseExample}
              isExampleProject={isExampleProject}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

/** The demonstration-data fallback, made to look like what it is. */
function DemoDataFallback({
  busy,
  onConfirm,
}: {
  busy: boolean;
  onConfirm: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="demo-fallback demo-fallback--confirming" data-testid="resolve-demo-confirm">
        <p className="demo-fallback__warning">
          These values are fictional demonstration assumptions. They will be written into this
          project tagged as demo data, and every result computed from them carries that tag.
        </p>
        <div className="demo-fallback__actions">
          <button
            type="button"
            className="fm-btn-tertiary"
            disabled={busy}
            onClick={() => {
              setConfirming(false);
              onConfirm();
            }}
            data-testid="resolve-demo-confirm-yes"
          >
            Use demonstration values
          </button>
          <button
            type="button"
            className="fm-btn-tertiary"
            onClick={() => setConfirming(false)}
            data-testid="resolve-demo-confirm-cancel"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="demo-fallback" data-testid="resolve-demo-fallback">
      <span className="demo-fallback__tag">Demo only</span>
      <button
        type="button"
        className="fm-btn-tertiary demo-fallback__trigger"
        disabled={busy}
        onClick={() => setConfirming(true)}
        data-testid="resolve-bulk-example"
      >
        Use demonstration values for what is unresolved
      </button>
    </div>
  );
}

export function ResolveInputs({
  draft,
  onDraftChange,
  onEstimateStage,
  onClose,
  isExampleProject = false,
}: {
  draft: FactoryConceptDraft;
  onDraftChange: (next: FactoryConceptDraft) => void;
  /** Hands a stage over to the Phase 18 estimation assistant. */
  onEstimateStage: (stageId: string) => void;
  onClose: () => void;
  /** True only inside the bundled example project. */
  isExampleProject?: boolean;
}) {
  const [plan, setPlan] = useState<ResolutionPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buffers, setBuffers] = useState<BufferSensitivity | null>(null);
  const [bufferBusy, setBufferBusy] = useState(false);
  const [bulkNote, setBulkNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    resolutionPlan(draft)
      .then((result) => {
        if (!cancelled) setPlan(result);
      })
      .catch((err) => {
        if (!cancelled) setError(describeRequestFailure(err));
      });
    return () => {
      cancelled = true;
    };
  }, [draft]);

  const resolve = useCallback(
    async (key: string, value: number | null, detail: string | null) => {
      setBusy(true);
      setError(null);
      try {
        // ENGINEER, always. A number typed here is an engineering decision;
        // the server rejects any attempt to call it CUSTOMER or MEASURED.
        const response = await resolveInput(draft, key, value, "ENGINEER", detail);
        onDraftChange(response.draft);
      } catch (err) {
        setError(describeRequestFailure(err));
      } finally {
        setBusy(false);
      }
    },
    [draft, onDraftChange],
  );

  const useExampleFor = useCallback(
    async (input: ResolvableInput) => {
      setBusy(true);
      setError(null);
      try {
        // Ask the backend what the dataset says, then adopt ONLY this field.
        // Reusing the existing endpoint means the value shown is the value
        // the dataset actually holds, not a second copy of it.
        const filled = await applyExampleData(draft);
        const source = await resolutionPlan(filled.draft);
        const match = source.inputs.find((i) => i.key === input.key);
        if (!match || match.value === null) {
          setError(`The demo dataset has no value for ${input.label}.`);
          return;
        }
        const response = await resolveInput(
          draft,
          input.key,
          match.value,
          "EXAMPLE_DATA",
          match.detail,
        );
        onDraftChange(response.draft);
      } catch (err) {
        setError(describeRequestFailure(err));
      } finally {
        setBusy(false);
      }
    },
    [draft, onDraftChange],
  );

  const applyDemoData = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const outcome = await useExampleDataForUnresolved(draft);
      onDraftChange(outcome.draft);
      setBulkNote(
        `Filled ${outcome.filled.length} unresolved value${
          outcome.filled.length === 1 ? "" : "s"
        } from the demonstration dataset` +
          (outcome.added.length
            ? `, and wired ${outcome.added.length} buffer${
                outcome.added.length === 1 ? "" : "s"
              } between stages`
            : "") +
          (outcome.protected.length
            ? `. ${outcome.protected.length} value${
                outcome.protected.length === 1 ? "" : "s"
              } you or the customer had already decided were left untouched.`
            : "."),
      );
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }, [draft, onDraftChange]);

  /** The panel's information architecture — §9. */
  const grouped = useMemo(() => {
    if (!plan) return null;

    const stageInputs = plan.inputs.filter((input) => input.stage_id !== null);
    const lineInputs = plan.inputs.filter((input) => input.stage_id === null);

    const required = lineInputs.filter((input) => input.necessity === "BLOCKS_SIMULATION");
    const layout = lineInputs.filter((input) => input.necessity === "AFFECTS_LAYOUT");
    const optional = lineInputs.filter(
      (input) => input.necessity !== "BLOCKS_SIMULATION" && input.necessity !== "AFFECTS_LAYOUT",
    );

    // Station order follows the ROUTE, not the order the plan happened to
    // list values in: the panel reads down the line the way the line runs.
    const byStage = new Map<string, ResolvableInput[]>();
    for (const input of stageInputs) {
      const id = input.stage_id as string;
      if (!byStage.has(id)) byStage.set(id, []);
      (byStage.get(id) as ResolvableInput[]).push(input);
    }
    // Tolerant of a draft with no stage list at all — a concept stored by an
    // earlier build, or one whose stages have not been read yet. The panel
    // names, every value still present. Taking the whole dialog down because
    // one optional array is missing would lose the values too.
    const stages = draft.stages ?? [];
    const stations = stages
      .filter((stage) => byStage.has(stage.id))
      .map((stage) => ({
        id: stage.id,
        // The engineer's own name for the station, never the identifier.
        label: stage.name,
        inputs: byStage.get(stage.id) as ResolvableInput[],
      }));
    // A stage_id the concept no longer holds must not silently vanish.
    for (const [id, inputs] of byStage) {
      if (!stages.some((stage) => stage.id === id)) {
        stations.push({ id, label: id, inputs });
      }
    }

    const stationGaps = stationInputsUnresolved(stations);
    return { required, layout, optional, stations, stationGaps };
  }, [plan, draft.stages]);

  const rows = (inputs: ResolvableInput[]) => (
    <ul className="resolve-list">
      {inputs.map((input) => (
        <InputRow
          key={input.key}
          input={input}
          busy={busy}
          onResolve={resolve}
          onEstimate={(i) => i.stage_id && onEstimateStage(i.stage_id)}
          onUseExample={useExampleFor}
          isExampleProject={isExampleProject}
        />
      ))}
    </ul>
  );

  return (
    <Overlay
      onClose={onClose}
      label="Resolve engineering inputs"
      className="resolve-panel"
      testId="resolve-inputs"
    >
      <header className="assumption-review__head">
        <div>
          <h2 className="assumption-review__title">Resolve engineering inputs</h2>
          <p className="assumption-review__subtitle">
            Fabrivium computes what it can compute and estimates what it can estimate. Anything
            that can only be known, measured or quoted is asked for — never invented.
          </p>
        </div>
        <button
          type="button"
          className="architecture-panel__close"
          onClick={onClose}
          aria-label="Close"
          data-testid="resolve-close"
        >
          <X size={18} strokeWidth={2} aria-hidden="true" />
        </button>
      </header>

      {error && (
        <p className="concept-error" data-testid="resolve-error">
          {error}
        </p>
      )}
      {bulkNote && (
        <p className="resolve-section__finding" data-testid="resolve-bulk-note">
          {bulkNote}
        </p>
      )}
      {!plan && !error && <p className="fm-empty">Working out what this concept needs…</p>}

      {plan && grouped && (
        <div className="resolve-body">
          {/* Computed first: it changes what the engineer thinks they have
              to supply, and several of these answers make other rows
              unnecessary. */}
          <section className="resolve-section" data-testid="resolve-computed">
            <h3 className="resolve-section__title">
              <Calculator size={13} strokeWidth={2} aria-hidden="true" />
              Fabrivium works these out
            </h3>
            <ul className="resolve-computed">
              {plan.computed.map((value) => (
                <li key={value.key} data-testid={`computed-${value.key}`}>
                  <span className="resolve-row__label">{value.label}</span>
                  <span className="resolve-row__value fm-mono">
                    {value.value === null
                      ? `Needs ${value.blocked_by}`
                      : `${value.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}${
                          value.unit ? ` ${value.unit}` : ""
                        }`}
                  </span>
                  <SourceBadge source={value.source} detail={value.formula} />
                  <span className="resolve-computed__formula fm-mono">{value.formula}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="resolve-section" data-testid="resolve-required">
            <h3 className="resolve-section__title">
              Required to simulate
              <span className="resolve-section__count">
                {plan.blocking_unresolved > 0
                  ? `${plan.blocking_unresolved} still needed`
                  : "all supplied"}
              </span>
            </h3>
            <p className="resolve-section__hint">
              Values the simulation reads directly. Without them the concept cannot be run at all.
            </p>
            {rows(grouped.required)}
          </section>

          <section className="resolve-section" data-testid="resolve-stations">
            <h3 className="resolve-section__title">
              Station parameters
              <span className="resolve-section__count" data-testid="resolve-stations-count">
                {grouped.stationGaps.total > 0
                  ? grouped.stationGaps.blocking > 0
                    ? `${grouped.stationGaps.blocking} needed to simulate` +
                      (grouped.stationGaps.total > grouped.stationGaps.blocking
                        ? ` · ${grouped.stationGaps.total - grouped.stationGaps.blocking} other unresolved`
                        : "")
                    : `${grouped.stationGaps.total} unresolved, none needed to simulate`
                  : `${grouped.stations.length} stations, all supplied`}
              </span>
            </h3>
            <p className="resolve-section__hint">
              Per station, in route order. A station with anything unresolved is opened.
            </p>
            <div className="resolve-stations">
              {grouped.stations.map((station) => (
                <StationGroup
                  key={station.id}
                  stageId={station.id}
                  label={station.label}
                  inputs={station.inputs}
                  busy={busy}
                  onResolve={resolve}
                  onEstimate={(i) => i.stage_id && onEstimateStage(i.stage_id)}
                  onUseExample={useExampleFor}
                  isExampleProject={isExampleProject}
                />
              ))}
            </div>
          </section>

          {grouped.layout.length > 0 && (
            <section className="resolve-section" data-testid="resolve-layout">
              <h3 className="resolve-section__title">Layout</h3>
              <p className="resolve-section__hint">
                Read by placement and by the floor checks. The simulator reads no layout, so none
                of these can change what the concept produces.
              </p>
              {rows(grouped.layout)}
            </section>
          )}

          {grouped.optional.length > 0 && (
            <section className="resolve-section" data-testid="resolve-optional">
              <h3 className="resolve-section__title">Commercial and optional</h3>
              <p className="resolve-section__hint">
                Money, and values that already have a stated default. The simulation runs without
                these; a plan cannot be compared on cost until the commercial ones are known.
              </p>
              {rows(grouped.optional)}
            </section>
          )}

          {/* Buffer sizing is a question, not a value to fill in. */}
          <section className="resolve-section" data-testid="resolve-buffers">
            <h3 className="resolve-section__title">Does buffer size matter here?</h3>
            {buffers ? (
              <>
                <p className="resolve-section__finding" data-testid="buffer-summary">
                  {buffers.summary}
                </p>
                <ul className="resolve-computed" data-testid="buffer-points">
                  {buffers.points.map((point) => (
                    <li key={point.size}>
                      <span className="resolve-row__label">
                        {point.size === 0 ? "No buffers" : `${point.size} units`}
                      </span>
                      <span className="resolve-row__value fm-mono">
                        {point.completed_units.toLocaleString("en-US")} /{" "}
                        {point.target_units.toLocaleString("en-US")} units/day
                      </span>
                      <span className="resolve-computed__formula fm-mono">
                        upstream blocked {Math.round(point.upstream_blocked_seconds).toLocaleString("en-US")} s
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <>
                <p className="resolve-section__hint">
                  Rather than adopting a buffer size, Fabrivium can run the concept once per
                  candidate size and report whether the choice changes anything.
                </p>
                <button
                  type="button"
                  className="fm-btn-secondary"
                  disabled={bufferBusy || draft.buffers.length === 0}
                  onClick={async () => {
                    setBufferBusy(true);
                    setError(null);
                    try {
                      setBuffers(await bufferSensitivity(draft));
                    } catch (err) {
                      setError(describeRequestFailure(err));
                    } finally {
                      setBufferBusy(false);
                    }
                  }}
                  data-testid="buffer-sweep-run"
                >
                  {bufferBusy ? (
                    <Loader2 size={13} strokeWidth={2} aria-hidden="true" className="concept-verified__spin" />
                  ) : null}
                  {draft.buffers.length === 0
                    ? "This concept has no buffers"
                    : "Run the buffer sweep"}
                </button>
              </>
            )}
          </section>
        </div>
      )}

      {plan && (
        <footer className="assumption-review__foot">
          {/* Demoted and confirmed — see DemoDataFallback. */}
          <DemoDataFallback busy={busy} onConfirm={() => void applyDemoData()} />
          <button
            type="button"
            className="fm-btn"
            onClick={onClose}
            data-testid="resolve-done"
            disabled={busy}
          >
            {plan.ready_to_simulate
              ? "Done — the concept can be simulated"
              : `Done — ${plan.blocking_unresolved} still needed to simulate`}
          </button>
        </footer>
      )}
    </Overlay>
  );
}

/** How many station values are still not established, and how many of those
 * actually stop the simulator running.
 *
 * Counted, never estimated — the section heading must not disagree with the
 * per-station counts under it, and neither may claim that a missing price
 * blocks a simulation that never reads one. */
function stationInputsUnresolved(
  stations: Array<{ inputs: ResolvableInput[] }>,
): { total: number; blocking: number } {
  let total = 0;
  let blocking = 0;
  for (const station of stations) {
    for (const input of station.inputs) {
      if (input.resolved) continue;
      total += 1;
      if (input.necessity === "BLOCKS_SIMULATION") blocking += 1;
    }
  }
  return { total, blocking };
}
