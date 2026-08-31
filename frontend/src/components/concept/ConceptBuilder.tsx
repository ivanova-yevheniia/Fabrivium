import { useState } from "react";
import { ArrowRight, CheckCircle2, CircleAlert, Database, Mic, MicOff, Play } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { EstimateAssistant } from "./EstimateAssistant";
import { estimatorContext, staleEstimate } from "../../api/operationContext";
import type { ConceptStage, FactoryConceptDraft, SourcedNumber } from "../../api/types";
import { SourceBadge, SourcedValue } from "./SourceBadge";
import { ResolveInputs } from "./ResolveInputs";
import { JourneyStrip } from "./JourneyStrip";
import { useSpeechInput } from "./useSpeechInput";
import { StaleResultsBanner } from "../executive/StaleResultsBanner";

/** Phase 13 — the factory concept builder. */

// An example of the SHAPE of a brief, not of an industry. It used to
// describe "a new electronics assembly line" going through the demo
// product's own route, which told every user — including one planning a
// packaging line — what kind of factory this tool expects. The parts that
// matter are the route, the target, the floor, the workforce and the
// preference; none of them needs a domain.
const EXAMPLE_BRIEF =
  "We need a new production line. The product goes through assembly, " +
  "inspection and packaging. We need about 600 units per day. " +
  "The available production area is 24 by 15 meters. We have six operators. " +
  "We would prefer not to buy unnecessary equipment.";

export function ConceptBuilder() {
  const { state, startConceptFromBrief, setStartMode } = useAppContext();
  const [brief, setBrief] = useState("");
  const concept = state.concept;

  // Dictation appends to whatever is in the field; it never replaces text
  // the user has edited, and it never submits. See useSpeechInput for the
  // rules this enforces.
  const speech = useSpeechInput((text) => {
    setBrief((current) => (current ? `${current.trimEnd()} ${text}` : text));
  });

  if (!concept.draft) {
    return (
      <div className="concept-brief" data-testid="concept-brief">
        <JourneyStrip />
        <header className="concept-brief__head">
          <h1 className="concept-brief__title">From customer requirements to a verified factory concept</h1>
          <p className="concept-brief__detail">
            Describe the production system you need. Fabrivium structures the concept, identifies the
            engineering information that is still missing, and prepares it for simulation.
          </p>
        </header>

        <div className="concept-brief__label-row">
          <label htmlFor="concept-brief-input" className="fm-label">
            Customer brief
          </label>
          {speech.supported ? (
            <button
              type="button"
              className={`brief-mic${speech.status === "listening" ? " brief-mic--listening" : ""}`}
              onClick={() => (speech.status === "listening" ? speech.stop() : speech.start())}
              aria-pressed={speech.status === "listening"}
              data-testid="concept-brief-mic"
            >
              {speech.status === "listening" ? (
                <>
                  <span className="brief-mic__level" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  Listening — tap to stop
                </>
              ) : (
                <>
                  <Mic size={14} strokeWidth={2} aria-hidden="true" />
                  Dictate
                </>
              )}
            </button>
          ) : (
            <span className="brief-mic brief-mic--unsupported" data-testid="concept-brief-mic-unsupported">
              <MicOff size={14} strokeWidth={2} aria-hidden="true" />
              Dictation unavailable in this browser
            </span>
          )}
        </div>
        <textarea
          id="concept-brief-input"
          className="concept-brief__input"
          value={brief}
          onChange={(event) => setBrief(event.target.value)}
          placeholder="e.g. We need a line producing 600 units per day through assembly, inspection and packaging…"
          data-testid="concept-brief-input"
          rows={5}
        />

        {speech.interim && (
          <p className="brief-mic__interim" data-testid="concept-brief-interim">
            {speech.interim}
          </p>
        )}
        {speech.message && (
          <p className="brief-mic__message" data-testid="concept-brief-speech-message">
            {speech.message}
          </p>
        )}

        <div className="concept-brief__examples">
          <button
            type="button"
            className="planning-request__example"
            onClick={() => setBrief(EXAMPLE_BRIEF)}
            data-testid="concept-brief-example"
          >
            Use the example customer brief
          </button>
        </div>

        {concept.error && (
          <p className="concept-error" data-testid="concept-error">
            {concept.error.message}
          </p>
        )}

        <div className="concept-brief__actions">
          <button
            type="button"
            className="fm-btn"
            disabled={!brief.trim() || concept.extracting}
            onClick={() => void startConceptFromBrief(brief, "New factory concept")}
            data-testid="concept-build-from-brief"
          >
            {concept.extracting ? "Reading the brief…" : "Build factory concept"}
          </button>
          <button
            type="button"
            className="fm-btn-secondary"
            onClick={() => setStartMode("CHOOSING")}
            data-testid="concept-back"
          >
            Back
          </button>
        </div>
      </div>
    );
  }

  return <ConceptWorkspace draft={concept.draft} />;
}


function ConceptWorkspace({ draft }: { draft: FactoryConceptDraft }) {
  // The demo dataset is no longer a step in this flow. Resolving inputs goes
  // through ResolveInputs, which computes what is computable, estimates what
  // is estimatable, and offers the dataset only as one explicitly-chosen
  // fallback per value. `useExampleEngineeringData` remains on the context
  // for callers that genuinely want the whole dataset at once.
  const { state, updateConceptDraft, buildConceptFactory } = useAppContext();
  const concept = state.concept;
  // The reviewed route, read live. Every station's estimator context and
  // every "this estimate assumed something else" notice below is derived
  // from it at render time rather than captured when the concept was built
  // — which is what makes an operation edited afterwards visible here.
  const process = state.product.process;
  const validation = concept.validation;
  const blocking = validation?.blocking_gaps ?? [];
  const optional = validation?.optional_gaps ?? [];
  const ready = validation?.simulation_ready ?? false;
  const [reviewing, setReviewing] = useState(false);
  // Which stage, if any, has the estimation assistant open. One at a time:
  // estimating is a focused act on one operation, not a form to fill in.
  const [estimating, setEstimating] = useState<string | null>(null);
  const [showRequired, setShowRequired] = useState(false);
  const [showOptional, setShowOptional] = useState(false);

  const setStage = (stageId: string, patch: Partial<ConceptStage>) => {
    void updateConceptDraft({
      ...draft,
      stages: draft.stages.map((stage) => (stage.id === stageId ? { ...stage, ...patch } : stage)),
    });
  };

  const setDraftField = (patch: Partial<FactoryConceptDraft>) => {
    void updateConceptDraft({ ...draft, ...patch });
  };

  return (
    <div className="concept-workspace" data-testid="concept-workspace">
      {/* Editing an input brings the engineer back here. */}
      <StaleResultsBanner />
      <JourneyStrip />
      {/* What the customer asked for */}
      <section className="concept-section">
        <h2 className="fm-section__title">What the customer asked for</h2>
        <div className="concept-requirements">
          <div className="concept-requirement">
            <span className="fm-label">Production target</span>
            <SourcedValue value={draft.production_target} unit="units/day" />
          </div>
          <div className="concept-requirement">
            <span className="fm-label">Workforce</span>
            <SourcedValue value={draft.operators_available} unit="operators" />
          </div>
          <div className="concept-requirement">
            <span className="fm-label">Floor area</span>
            {draft.floor_width.value !== null && draft.floor_length.value !== null ? (
              <span className="sourced-value">
                <span className="fm-mono sourced-value__number">
                  {draft.floor_width.value} × {draft.floor_length.value}
                </span>
                <span className="sourced-value__unit">m</span>
                {/* The floor is the only requirement on this row built from
                    TWO values, and it was the only one rendered without its
                    source. Everything beside it answered "who said this?"
                    and it did not — which matters most here, because a floor
                    the customer stated and a floor the engineer assumed are
                    different commitments.

                    ONE STATEMENT, ONE BADGE — while the two halves really do
                    agree. They are projections of one requirement and the
                    services that write them keep them together (G12), so
                    this is the normal case by construction. Where something
                    has nonetheless filled one side from elsewhere, the pair
                    is labelled side by side rather than having one half
                    speak for a number it did not come from. */}
                {draft.floor_width.source === draft.floor_length.source ? (
                  <SourceBadge source={draft.floor_width.source} detail={draft.floor_width.detail} />
                ) : (
                  <span className="concept-floor-sources" data-testid="concept-floor-mixed">
                    <span className="concept-floor-source">
                      <span className="fm-label">width</span>
                      <SourceBadge source={draft.floor_width.source} detail={draft.floor_width.detail} />
                    </span>
                    <span className="concept-floor-source">
                      <span className="fm-label">length</span>
                      <SourceBadge source={draft.floor_length.source} detail={draft.floor_length.detail} />
                    </span>
                  </span>
                )}
              </span>
            ) : (
              <span className="sourced-value sourced-value--unknown">Not known yet</span>
            )}
          </div>
        </div>
        {draft.prefer_no_new_machines && (
          <p className="concept-preference" data-testid="concept-preference">
            <span className="interpreted-req__chip interpreted-req__chip--soft">
              avoid new machines
              <span className="interpreted-req__soft-tag">preference</span>
            </span>
          </p>
        )}
        <p className="concept-brief-quote" data-testid="concept-brief-quote">
          “{draft.customer_brief}”
        </p>
      </section>

      {/* The route */}
      <section className="concept-section">
        <header className="concept-section__head">
          <h2 className="fm-section__title">Process flow</h2>
          <p className="concept-section__note">
            Cycle time, capacity and operators drive the simulation. Station footprint and floor position do
            not — placement is checked for validity, never for speed.
          </p>
        </header>

        {draft.stages.length === 0 ? (
          <p className="fm-empty">No process stages were recognised in the brief.</p>
        ) : (
          <ol className="stage-list" data-testid="stage-list">
            {draft.stages.map((stage, index) => {
              const context = estimatorContext(stage, process);
              const stale = staleEstimate(stage, process);
              return (
              <li className="stage-row" key={stage.id} data-testid={`stage-${stage.id}`}>
                <span className="stage-row__index fm-mono">{index + 1}</span>
                <div className="stage-row__identity">
                  <span className="stage-row__name">{stage.name}</span>
                  <span className="stage-row__type">{stage.process_type}</span>
                </div>

                <label className="stage-field">
                  <span className="fm-label">Cycle time</span>
                  <NumberField
                    value={stage.cycle_time}
                    unit="s"
                    testId={`cycle-${stage.id}`}
                    onCommit={(next) => setStage(stage.id, { cycle_time: next })}
                  />
                </label>

                <label className="stage-field">
                  <span className="fm-label">Capacity</span>
                  <NumberField
                    value={stage.capacity}
                    testId={`capacity-${stage.id}`}
                    onCommit={(next) => setStage(stage.id, { capacity: next })}
                  />
                </label>

                <label className="stage-field">
                  <span className="fm-label">Operators</span>
                  <NumberField
                    value={stage.operators_required}
                    testId={`operators-${stage.id}`}
                    onCommit={(next) => setStage(stage.id, { operators_required: next })}
                  />
                </label>

                {/* Phase 18 offered this ONLY where the cycle time was
                    still missing, which made estimation a one-shot: once a
                    station had a value the assistant disappeared from the
                    row, and an engineer who wanted to reconsider it after
                    learning more about the operation had nowhere to go.
                    Estimating is a refinement loop, so the way back in stays
                    open. The field above is still the direct route for
                    someone who simply knows the number. */}
                <button
                  type="button"
                  className="fm-btn-secondary fm-btn--auto stage-row__estimate"
                  onClick={() => {
                    setReviewing(false);
                    setEstimating(estimating === stage.id ? null : stage.id);
                  }}
                  aria-expanded={estimating === stage.id}
                  data-testid={`estimate-open-${stage.id}`}
                >
                  {estimating === stage.id
                    ? "Close"
                    : stage.cycle_time.value == null
                      ? "Help me estimate"
                      : "Re-estimate"}
                </button>

                {/* G11 — this station's estimate was composed under an
                    assumption the route no longer makes. The number is not
                    wrong, it answers a question nobody is asking any more,
                    and only THIS station is told so: changing how many
                    screws go into an enclosure says nothing about the
                    labelling station. */}
                {stale && (
                  <p className="stage-row__stale" data-testid={`estimate-stale-${stage.id}`}>
                    <CircleAlert size={12} strokeWidth={2.2} aria-hidden="true" />
                    Estimated for {stale.estimatedFor} per unit. The reviewed process now says{" "}
                    {stale.reviewedAs}. Re-estimate this station.
                  </p>
                )}

                {estimating === stage.id && (
                  <div className="stage-row__assistant">
                    {/* Keyed by station. */}
                    <EstimateAssistant
                      key={stage.id}
                      draft={draft}
                      stageId={stage.id}
                      stageName={stage.name}
                      context={context}
                      onApplied={(response) => {
                        void updateConceptDraft(response.draft);
                        setEstimating(null);
                      }}
                      onCancel={() => setEstimating(null)}
                    />
                  </div>
                )}
              </li>
              );
            })}
          </ol>
        )}
      </section>

      {/* Resources */}
      <section className="concept-section">
        <h2 className="fm-section__title">Operating schedule and workforce</h2>
        <div className="concept-requirements">
          <label className="concept-requirement">
            <span className="fm-label">Shifts per day</span>
            <NumberField
              value={draft.shifts_per_day}
              testId="shifts-per-day"
              onCommit={(next) => setDraftField({ shifts_per_day: next })}
            />
          </label>
          <label className="concept-requirement">
            <span className="fm-label">Hours per shift</span>
            <NumberField
              value={draft.hours_per_shift}
              unit="h"
              testId="hours-per-shift"
              onCommit={(next) => setDraftField({ hours_per_shift: next })}
            />
          </label>
          <label className="concept-requirement">
            <span className="fm-label">Operators available</span>
            <NumberField
              value={draft.operators_available}
              testId="operators-available"
              onCommit={(next) => setDraftField({ operators_available: next })}
            />
          </label>
        </div>
      </section>

      {/* Gaps
          Audit finding A3: this was two flat lists — 6 required and 9
          optional bullet points with a reason line each, ~30 lines of prose
          standing between the concept and its primary action. The counts and
          the decision now lead; the item lists are disclosed on demand. */}
      <section className="concept-section" data-testid="concept-gaps">
        <header className="concept-section__head">
          <h2 className="fm-section__title">Engineering information</h2>
        </header>

        {blocking.length > 0 ? (
          <div className="gap-block gap-block--required" data-testid="gap-required">
            <p className="gap-block__title">
              <CircleAlert size={15} strokeWidth={2} aria-hidden="true" />
              We can build the first concept, but {blocking.length} engineering input
              {blocking.length === 1 ? "" : "s"} still need{blocking.length === 1 ? "s" : ""} confirmation
            </p>
            <p className="gap-block__summary">
              These are values the simulation actually reads, so Fabrivium will not guess them.
            </p>

            <div className="gap-block__actions">
              <button
                type="button"
                className="fm-btn-secondary gap-block__action"
                onClick={() => {
                  // One at a time. With both open, the per-station
                  // assistant sits behind the review's backdrop and its
                  // own controls (including the provenance ⓘ) cannot be
                  // clicked — verified in a real browser at 1366x768.
                  setEstimating(null);
                  setReviewing(true);
                }}
                disabled={concept.extracting}
                data-testid="concept-review-assumptions"
              >
                <Database size={14} strokeWidth={2} aria-hidden="true" />
                Resolve inputs
              </button>
              <button
                type="button"
                className="gap-block__disclose"
                onClick={() => setShowRequired((open) => !open)}
                aria-expanded={showRequired}
                data-testid="gap-required-toggle"
              >
                {showRequired ? "Hide" : "Show"} the {blocking.length} inputs
              </button>
            </div>

            {showRequired && (
              <ul data-testid="gap-required-list">
                {blocking.map((gap) => (
                  <li key={gap.key}>
                    <strong>{gap.label}</strong>
                    <span className="gap-block__reason">{gap.reason}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="gap-block gap-block--ready" data-testid="gap-ready">
            <p className="gap-block__title">
              <CheckCircle2 size={15} strokeWidth={2} aria-hidden="true" />
              Every value the simulation needs is present
            </p>
          </div>
        )}

        {optional.length > 0 && (
          <div className="gap-block gap-block--optional" data-testid="gap-optional">
            <p className="gap-block__title">
              {optional.length} value{optional.length === 1 ? "" : "s"} still unknown — does not block
              simulation
            </p>
            <button
              type="button"
              className="gap-block__disclose"
              onClick={() => setShowOptional((open) => !open)}
              aria-expanded={showOptional}
              data-testid="gap-optional-toggle"
            >
              {showOptional ? "Hide" : "Show"} them
            </button>
            {showOptional && (
              <ul data-testid="gap-optional-list">
                {optional.map((gap) => (
                  <li key={gap.key}>
                    <strong>{gap.label}</strong>
                    <span className="gap-block__reason">{gap.reason}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {validation?.errors.length ? (
          <div className="gap-block gap-block--error" data-testid="gap-errors">
            <p className="gap-block__title">Problems to repair</p>
            <ul>
              {validation.errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {reviewing && (
        <ResolveInputs
          isExampleProject={Boolean(state.project?.isExample)}
          draft={draft}
          onClose={() => setReviewing(false)}
          onDraftChange={(next) => void updateConceptDraft(next)}
          onEstimateStage={(stageId) => {
            // One panel at a time — the estimation assistant lives behind
            // this one, and two stacked dialogs leave the lower one's
            // controls unreachable.
            setReviewing(false);
            setEstimating(stageId);
          }}
        />
      )}

      {concept.error && (
        <p className="concept-error" data-testid="concept-error">
          {concept.error.message}
        </p>
      )}

      {/* Build
          Audit finding A2: this action sat at y=1608 on a 1366-high screen —
          more than two screens down — so the presenter had to scroll to find
          the button that advances the demo. It is sticky now, and it states
          the concept's current status beside it so the reason it is disabled
          is visible at the same moment the button is. */}
      <footer className="concept-footer" data-testid="concept-footer">
        <div className="concept-footer__status">
          {ready ? (
            <span className="concept-footer__status-ready">Ready to build</span>
          ) : (
            <span className="concept-footer__status-blocked">
              {blocking.length} input{blocking.length === 1 ? "" : "s"} still needed
            </span>
          )}
        </div>
        <button
          type="button"
          className="fm-btn concept-footer__cta"
          disabled={!ready || concept.building}
          onClick={() => void buildConceptFactory()}
          data-testid="concept-build-factory"
        >
          {concept.building ? (
            "Building…"
          ) : (
            <>
              <Play size={15} strokeWidth={2.4} fill="currentColor" aria-hidden="true" />
              Build concept
            </>
          )}
        </button>
        <span className="concept-footer__note">
          <ArrowRight size={14} strokeWidth={2} aria-hidden="true" />
          Generates stations, buffers and a concept layout.
        </span>
      </footer>
    </div>
  );
}


/** An editable number that preserves provenance. */
function NumberField({
  value,
  unit,
  testId,
  onCommit,
}: {
  value: SourcedNumber;
  unit?: string;
  testId: string;
  onCommit: (next: SourcedNumber) => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? (value.value === null ? "" : String(value.value));

  const commit = () => {
    if (text === null) return;
    const trimmed = text.trim();
    if (trimmed === "") {
      onCommit({ value: null, source: "UNKNOWN", detail: null });
    } else {
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed)) {
        setText(null);
        return;
      }
      onCommit({ value: parsed, source: "ENGINEER", detail: "Entered by the engineer" });
    }
    setText(null);
  };

  return (
    <span className="number-field">
      <input
        type="text"
        inputMode="decimal"
        className="number-field__input fm-mono"
        value={shown}
        placeholder="—"
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        data-testid={`field-${testId}`}
      />
      {unit && <span className="number-field__unit">{unit}</span>}
      {/* One provenance label table, not two. */}
      {value.value !== null && <SourceBadge source={value.source} detail={value.detail} />}
    </span>
  );
}
