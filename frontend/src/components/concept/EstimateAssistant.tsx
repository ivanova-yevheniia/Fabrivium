import { useState } from "react";
import { CircleAlert, HelpCircle, Loader2, Ruler, Sparkles } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import {
  acceptStationAssumptions,
  applyEstimate,
  estimateCycleTime,
  protectedValueConflict,
  type EstimateContradiction,
  type EstimatedRange,
  type NeedsInformation,
  type ProtectedValueConflict,
  type StationAssumptionProposal,
} from "../../api/uncertainty";
import { AssumptionCard } from "./AssumptionCard";
import { NO_CONTEXT, type EstimatorContext, type RepeatCountSource } from "../../api/operationContext";
import type { ConceptResponse, FactoryConceptDraft } from "../../api/types";

/**
 * Phase 18 / 18B — "what do you already know about this operation?"
 *
 * ONE MODE AT A TIME (18B §18)
 * ----------------------------
 * Two full forms side by side made the panel read like a tax return. The
 * engineer picks a route first; only that route's fields appear. Neither is
 * privileged — the direct-entry tab is the default, because someone who
 * knows the number should not have to walk past an assistant to type it.
 *
 * A PROVIDER OUTAGE IS NO LONGER A DEAD END (18B)
 * -----------------------------------------------
 * When the language model cannot be reached, the backend composes a range
 * from documented reference bands instead. The screen shows the estimate
 * normally and adds one line saying which route produced it. It does NOT
 * show HTTP codes or quota internals: those are a fact about our account,
 * not about the engineering, and they belong in logs.
 *
 * WHAT IS STILL REFUSED
 * ---------------------
 * A number when neither route has a basis. That returns the specific
 * questions that would unblock it, which is more use than a fabricated
 * figure and considerably more honest.
 *
 * P0 — RE-ESTIMATION, AND WHAT IT MAY NOT QUIETLY DO
 * --------------------------------------------------
 * Two defects were observed walking the product. A station could be
 * estimated once and then never revisited, because the way in disappeared
 * the moment it had a value; and there was no protection at all against an
 * estimate landing on top of a number the engineer had typed.
 *
 * The first is fixed upstream, in the row that opens this panel. The second
 * is fixed here and in the backend together: applying still POSTs the same
 * request, but a value that came from a person, a document, a measurement
 * or a manufacturer answers 409 with what would be lost — and the engineer
 * is shown BOTH numbers and asked. The proposal is never withheld; only the
 * write is, and only until they say so.
 *
 * G10/G11 — THIS FORM DOES NOT START BLANK ANY MORE
 * -------------------------------------------------
 * It used to. A station reviewed as "Screw fastening, 6 times per unit"
 * opened an empty description and an empty repeat count, and the engineer
 * retyped what Fabrivium had already read and asked them to approve.
 *
 * The repeat count is the serious half: it is an INPUT to the composition,
 * so a blank field invites a band composed for one fastening onto a station
 * that performs six, and that number then reaches cycle time, throughput
 * and the bottleneck looking exactly like a reviewed one.
 *
 * So the panel opens on what is already known (see `api/operationContext`),
 * and says beside each field where the value came from — reviewed process,
 * earlier estimate, or the engineer just now. Editing either field changes
 * only this form: refining a description here proposes nothing to the
 * process, and the canonical operation is only ever changed where operations
 * are edited.
 */
export function EstimateAssistant({
  draft,
  stageId,
  stageName,
  taktSeconds,
  context = NO_CONTEXT,
  onApplied,
  onCancel,
}: {
  draft: FactoryConceptDraft;
  stageId: string;
  stageName: string;
  /** Shown for context so a proposed range can be judged against the line. */
  taktSeconds?: number | null;
  /** What the reviewed process already says about this station. */
  context?: EstimatorContext;
  onApplied: (response: ConceptResponse) => void;
  onCancel?: () => void;
}) {
  const [mode, setMode] = useState<"known" | "assist">("known");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seeded from the reviewed process, not from nothing. The panel is keyed
  // by station upstream, so moving to another station remounts it and these
  // are re-seeded from that station's own context rather than carrying the
  // previous one's along.
  const [description, setDescription] = useState(context.description);
  const [automation, setAutomation] = useState("UNKNOWN");
  const [repeats, setRepeats] = useState(context.repeats === null ? "" : String(context.repeats));
  // Where what is IN the fields came from, which stops being the context's
  // answer the moment the engineer types. Tracked rather than inferred by
  // comparing values: an engineer who deliberately retypes 6 has still
  // entered it themselves, and the estimate should record that honestly.
  const [descriptionEdited, setDescriptionEdited] = useState(false);
  const [repeatsEdited, setRepeatsEdited] = useState(false);
  const repeatOrigin: RepeatCountSource = repeatsEdited ? "ENGINEER" : context.repeatSource;

  const [proposal, setProposal] = useState<StationAssumptionProposal | null>(null);
  const [needs, setNeeds] = useState<NeedsInformation | null>(null);
  const [clash, setClash] = useState<EstimateContradiction | null>(null);
  //: A write the backend declined because it would replace something
  //: stronger than an estimate, together with the write that was declined —
  //: so confirming re-runs the SAME request rather than reconstructing it.
  const [conflict, setConflict] = useState<
    { detail: ProtectedValueConflict; retry: (replace: boolean) => Promise<void> } | null
  >(null);

  // Seeded from whatever the station currently holds, so "I know the value"
  // opens on the number in force rather than on a blank field. An engineer
  // correcting 48 to 47 should not have to remember what 48 was, and a blank
  // form beside a station that already has a value reads as though the value
  // is about to be lost.
  const current = draft.stages.find((stage) => stage.id === stageId)?.cycle_time.value ?? null;
  const seed = current === null ? "" : String(current);
  const [manualLow, setManualLow] = useState(seed);
  const [manualWorking, setManualWorking] = useState(seed);
  const [manualHigh, setManualHigh] = useState(seed);
  const [manualBasis, setManualBasis] = useState("");

  function clearOutcome() {
    setProposal(null);
    setNeeds(null);
    setClash(null);
    setConflict(null);
    setError(null);
  }

  /** Run one write, and turn a protected-value refusal into a question. */
  async function write(attempt: (replace: boolean) => Promise<void>) {
    setBusy(true);
    setError(null);
    setConflict(null);
    try {
      await attempt(false);
    } catch (err) {
      const detail = protectedValueConflict(err);
      if (detail) setConflict({ detail, retry: attempt });
      else setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmReplacement() {
    if (!conflict) return;
    const { retry } = conflict;
    setBusy(true);
    setError(null);
    try {
      await retry(true);
      setConflict(null);
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }

  async function ask(automationOverride?: string) {
    setBusy(true);
    clearOutcome();
    const level = automationOverride ?? automation;
    if (automationOverride) setAutomation(automationOverride);
    try {
      const result = await estimateCycleTime(draft, stageId, {
        description,
        automation_level: level,
        operations_per_unit: repeats ? Number(repeats) : null,
      });
      if (result.proposal) {
        // `fell_back` travels on the proposal itself, so the card can say
        // which route produced each row without the parent tracking it.
        setProposal(result.proposal);
      } else if (result.contradiction) {
        setClash(result.contradiction);
      } else {
        setNeeds(result.needs_information);
      }
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(false);
    }
  }

  /** The manual route still writes one value: the engineer typed a cycle time, not a station. */
  const acceptManual = (range: EstimatedRange) =>
    write(async (replace) => {
      onApplied(await applyEstimate(draft, stageId, range, replace));
    });

  /** The assisted route writes every parameter the engineer accepted, so
   * nothing has to be copied across by hand. */
  const acceptProposal = (fields: string[]) => {
    if (!proposal) return Promise.resolve();
    return write(async (replace) => {
      const result = await acceptStationAssumptions(draft, proposal, fields, replace);
      onApplied({ draft: result.draft, validation: result.validation } as never);
    });
  };

  function manualRange(): EstimatedRange | null {
    const low = Number(manualLow);
    const working = Number(manualWorking);
    const high = Number(manualHigh);
    if (!low || !working || !high || !manualBasis.trim()) return null;
    return {
      low,
      working_value: working,
      high,
      unit: "s",
      confidence: "MEDIUM",
      method: "ENGINEER",
      basis: manualBasis.trim(),
      model_name: null,
    };
  }

  const manual = manualRange();

  return (
    <section className="estimate" data-testid="estimate-assistant">
      <header className="estimate__head">
        <p className="estimate__title">{stageName} — what do you already know?</p>
        {taktSeconds != null && (
          <p className="estimate__detail">
            This line's takt is <strong>{taktSeconds.toFixed(1)} s/unit</strong> — the average a
            station must beat, not a value any one station can sit at.
          </p>
        )}
      </header>

      {/* One route at a time. */}
      <div className="estimate__modes" role="tablist" aria-label="How to supply the cycle time">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "known"}
          className={`estimate__mode${mode === "known" ? " estimate__mode--on" : ""}`}
          onClick={() => setMode("known")}
          data-testid="estimate-mode-known"
        >
          <Ruler size={13} strokeWidth={2} aria-hidden="true" />I know the value
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "assist"}
          className={`estimate__mode${mode === "assist" ? " estimate__mode--on" : ""}`}
          onClick={() => setMode("assist")}
          data-testid="estimate-mode-assist"
        >
          <Sparkles size={13} strokeWidth={2} aria-hidden="true" />
          Help me estimate
        </button>
      </div>

      {mode === "known" ? (
        <div className="estimate__known" data-testid="estimate-manual">
          <div className="estimate__fields">
            <label>
              <span className="fm-label">Fastest</span>
              <input type="number" min="0" value={manualLow} onChange={(e) => setManualLow(e.target.value)} data-testid="estimate-manual-low" />
            </label>
            <label>
              <span className="fm-label">Working value</span>
              <input type="number" min="0" value={manualWorking} onChange={(e) => setManualWorking(e.target.value)} data-testid="estimate-manual-working" />
            </label>
            <label>
              <span className="fm-label">Slowest</span>
              <input type="number" min="0" value={manualHigh} onChange={(e) => setManualHigh(e.target.value)} data-testid="estimate-manual-high" />
            </label>
          </div>
          <label className="estimate__basis">
            <span className="fm-label">What is this based on?</span>
            <input
              type="text"
              value={manualBasis}
              onChange={(e) => setManualBasis(e.target.value)}
              placeholder="e.g. measured on a comparable line"
              data-testid="estimate-manual-basis"
            />
          </label>
          <button
            type="button"
            className="fm-btn-primary fm-btn--auto"
            disabled={!manual || busy}
            onClick={() => manual && acceptManual(manual)}
            data-testid="estimate-manual-apply"
          >
            Use these values
          </button>
        </div>
      ) : (
        <div className="estimate__assist" data-testid="estimate-assist-form">
          <label className="estimate__basis">
            <span className="fm-label">Describe the operation</span>
            <input
              type="text"
              value={description}
              onChange={(e) => {
                setDescription(e.target.value);
                setDescriptionEdited(true);
              }}
              placeholder="e.g. six screws into a plastic electronics enclosure"
              data-testid="estimate-description"
            />
            {context.descriptionFromProcess && !descriptionEdited && (
              <span
                className="estimate__hint"
                data-testid="estimate-description-source"
                data-source="PROCESS"
              >
                From the operation you reviewed. Refine it for this estimate if you want to — the
                process keeps its own wording.
              </span>
            )}
          </label>
          <div className="estimate__fields">
            <label>
              <span className="fm-label">Automation level</span>
              <select value={automation} onChange={(e) => setAutomation(e.target.value)} data-testid="estimate-automation">
                <option value="MANUAL">Manual</option>
                <option value="ASSISTED">Assisted</option>
                <option value="AUTOMATIC">Automatic</option>
                <option value="UNKNOWN">Unknown</option>
              </select>
            </label>
            <label>
              {/* Renamed from "Operations per unit", which read as "how many
                  units per operation" to more than one reader. */}
              <span className="fm-label">Repeated operations per unit</span>
              <input
                type="number"
                min="1"
                value={repeats}
                onChange={(e) => {
                  setRepeats(e.target.value);
                  setRepeatsEdited(true);
                }}
                data-testid="estimate-operations"
              />
              {/* One line, and it says where this number came from rather
                  than what the field means — because once the field is
                  filled in for them, "where did that 6 come from?" is the
                  question the engineer actually has. */}
              <span
                className="estimate__hint"
                data-testid="estimate-operations-source"
                data-source={repeatOrigin}
              >
                {repeatOrigin === "PROCESS" &&
                  `From the reviewed process: this operation happens ${context.repeats}× per unit.`}
                {repeatOrigin === "ESTIMATE" &&
                  `From the estimate already accepted for this station. The reviewed process does not state a count.`}
                {repeatOrigin === "ENGINEER" &&
                  (context.repeats === null
                    ? "Entered here."
                    : `Entered here. The reviewed process states ${context.repeats}× per unit.`)}
                {repeatOrigin === "NONE" &&
                  "How many times this operation happens on one product — e.g. 6 screws, 2 checks. Leave blank to read it from the description."}
              </span>
            </label>
          </div>
          <button
            type="button"
            className="fm-btn-secondary fm-btn--auto"
            onClick={() => ask()}
            disabled={busy || !description.trim()}
            aria-busy={busy}
            data-testid="estimate-ask"
          >
            {busy && <Loader2 size={13} strokeWidth={2} aria-hidden="true" className="equipment__spin" />}
            {busy ? "Estimating…" : "Propose a range"}
          </button>
        </div>
      )}

      {clash && <ContradictionPrompt clash={clash} busy={busy} onResolve={(level) => void ask(level)} />}

      {needs && (
        <div className="estimate__needs" data-testid="estimate-needs-information">
          <p className="estimate__unavailable-title">
            <HelpCircle size={13} strokeWidth={2.2} aria-hidden="true" />
            Not enough information to estimate this operation
          </p>
          <p className="estimate__detail">{needs.reason}</p>
          <ul className="estimate__questions">
            {needs.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
          <button
            type="button"
            className="fm-btn-secondary fm-btn--auto"
            onClick={() => setMode("known")}
            data-testid="estimate-switch-to-known"
          >
            Enter known data instead
          </button>
        </div>
      )}

      {proposal && <AssumptionCard proposal={proposal} onAccept={acceptProposal} busy={busy} />}

      {conflict && (
        <ReplaceConfirmation
          conflict={conflict.detail}
          busy={busy}
          onConfirm={() => void confirmReplacement()}
          onKeep={() => setConflict(null)}
        />
      )}

      {error && (
        <p className="estimate__error" data-testid="estimate-error">
          {error}
        </p>
      )}

      {onCancel && (
        <div className="estimate__footer">
          <button type="button" className="fm-btn-tertiary" onClick={onCancel} data-testid="estimate-cancel">
            Cancel
          </button>
        </div>
      )}
    </section>
  );
}

/** The description and the selector disagree. */
function ContradictionPrompt({
  clash,
  busy,
  onResolve,
}: {
  clash: EstimateContradiction;
  busy: boolean;
  onResolve: (level: string) => void;
}) {
  return (
    <div className="estimate__clash" data-testid="estimate-contradiction">
      <p className="estimate__unavailable-title">
        <CircleAlert size={13} strokeWidth={2.2} aria-hidden="true" />
        These inputs disagree
      </p>
      <p className="estimate__detail">{clash.message}</p>
      <div className="estimate__clash-actions">
        <button
          type="button"
          className="fm-btn-secondary"
          disabled={busy}
          onClick={() => onResolve(clash.described_as)}
          data-testid="estimate-use-described"
        >
          Use {clash.described_as.toLowerCase()}
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          disabled={busy}
          onClick={() => onResolve(clash.selected_as)}
          data-testid="estimate-keep-selected"
        >
          Keep {clash.selected_as.toLowerCase()}
        </button>
      </div>
    </div>
  );
}


/** An estimate would replace something a person is accountable for. */
function ReplaceConfirmation({
  conflict,
  busy,
  onConfirm,
  onKeep,
}: {
  conflict: ProtectedValueConflict;
  busy: boolean;
  onConfirm: () => void;
  onKeep: () => void;
}) {
  return (
    <div className="estimate__clash" role="alertdialog" data-testid="estimate-replace-confirm">
      <p className="estimate__unavailable-title">
        <CircleAlert size={13} strokeWidth={2.2} aria-hidden="true" />
        This would replace a value that did not come from an estimate
      </p>
      <ul className="estimate__questions" data-testid="estimate-protected-values">
        {conflict.protected.map((value) => (
          <li key={value.field}>
            <strong>{value.label}</strong> is currently{" "}
            <span className="fm-mono">{value.value ?? "unknown"}</span>, entered as{" "}
            {value.source.replace(/_/g, " ").toLowerCase()}
            {value.detail ? ` — ${value.detail}` : ""}.
          </li>
        ))}
      </ul>
      <p className="estimate__detail">
        Replacing it makes the estimate the value the simulation reads. The one it replaces stays in
        the station's revision history.
      </p>
      <div className="estimate__clash-actions">
        <button
          type="button"
          className="fm-btn-secondary"
          disabled={busy}
          onClick={onKeep}
          data-testid="estimate-keep-existing"
        >
          Keep the existing value
        </button>
        <button
          type="button"
          className="fm-btn-tertiary"
          disabled={busy}
          onClick={onConfirm}
          data-testid="estimate-replace-existing"
        >
          Replace it with the estimate
        </button>
      </div>
    </div>
  );
}
