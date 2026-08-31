import { useEffect, useState } from "react";
import { Check, Loader2, Target, X } from "lucide-react";
import { describeRequestFailure } from "../../api/client";
import {
  deriveThreshold,
  runSensitivity,
  type SensitivityResult,
  type ThresholdResult,
} from "../../api/uncertainty";
import type { FactoryConceptDraft } from "../../api/types";
import { stationName } from "../../utils/formatting";

/** Phase 18 — what the uncertainty actually costs, and what it demands. */
export function SensitivityPanel({
  draft,
  stageId,
  stageName,
}: {
  draft: FactoryConceptDraft;
  stageId: string;
  stageName: string;
}) {
  const [busy, setBusy] = useState<null | "sweep" | "threshold">(null);
  const [sweep, setSweep] = useState<SensitivityResult | null>(null);
  const [threshold, setThreshold] = useState<ThresholdResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Changing station discards this station's answers rather than leaving
  // them on screen under the next one's name. Deliberately NOT a cache: a
  // result restored on switching back would be arithmetic over a draft that
  // may have moved since, presented as current. Cleared is the state the
  // buttons already describe, and it is the same every time.
  //
  // Nothing is re-run here. Selecting a station asks a question; it does not
  // answer it, and spending real simulations on a selector change would be
  // the product deciding for the engineer what they wanted to know.
  useEffect(() => {
    setSweep(null);
    setThreshold(null);
    setError(null);
  }, [stageId]);

  // A result belongs to the station it was computed for. `stage_id` comes
  // back from the backend on both results, so this is the model's own key
  // rather than a second copy of it kept in sync by hand.
  const sweepForStation = sweep && sweep.stage_id === stageId ? sweep : null;
  const thresholdForStation = threshold && threshold.stage_id === stageId ? threshold : null;

  async function run(kind: "sweep" | "threshold") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "sweep") setSweep(await runSensitivity(draft, stageId));
      else setThreshold(await deriveThreshold(draft, stageId));
    } catch (err) {
      setError(describeRequestFailure(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="sensitivity" data-testid="sensitivity-panel">
      <header className="sensitivity__head">
        <p className="sensitivity__title">{stageName} — how much does this assumption matter?</p>
        <p className="sensitivity__detail">
          Fabrivium runs the same deterministic simulation once per value. These are real runs, not
          samples.
        </p>
      </header>

      <div className="sensitivity__actions">
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={() => run("sweep")}
          disabled={busy !== null}
          aria-busy={busy === "sweep"}
          data-testid="sensitivity-run"
        >
          {busy === "sweep" && <Loader2 size={13} strokeWidth={2} aria-hidden="true" className="equipment__spin" />}
          {busy === "sweep" ? "Simulating…" : "Test the range"}
        </button>
        <button
          type="button"
          className="fm-btn-primary"
          onClick={() => run("threshold")}
          disabled={busy !== null}
          aria-busy={busy === "threshold"}
          data-testid="threshold-run"
        >
          {busy === "threshold" && (
            <Loader2 size={13} strokeWidth={2} aria-hidden="true" className="equipment__spin" />
          )}
          {busy === "threshold" ? "Searching…" : "Can improving this station reach the target?"}
        </button>
      </div>

      {sweepForStation && (
        <div className="sensitivity__result" data-testid="sensitivity-result">
          <table className="sensitivity__table">
            <thead>
              <tr>
                <th scope="col">Cycle time</th>
                <th scope="col">Output</th>
                <th scope="col">Target</th>
                <th scope="col">Verdict</th>
                <th scope="col">Limiting station</th>
              </tr>
            </thead>
            <tbody>
              {sweepForStation.points.map((point) => (
                <tr key={point.value} data-testid={`sweep-point-${point.value}`}>
                  <td>
                    {point.value} {point.unit}
                  </td>
                  <td>{point.completed_units.toLocaleString("en-US")}</td>
                  <td>{point.target_units.toLocaleString("en-US")}</td>
                  <td data-status={point.meets_target ? "PASS" : "FAIL"}>
                    {point.meets_target ? (
                      <>
                        <Check size={12} strokeWidth={2.6} aria-hidden="true" className="status-pass" /> PASS
                      </>
                    ) : (
                      <>
                        <X size={12} strokeWidth={2.6} aria-hidden="true" className="status-fail" /> FAIL
                      </>
                    )}
                  </td>
                  <td>{stationName(point.bottleneck_machine_id, draft.stages)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="sensitivity__summary" data-testid="sensitivity-summary">
            {sweepForStation.summary}{" "}
            {/* Named, because the panel can show two counts at once and they
                belong to different analyses. "3 simulations run" beside
                "derived from 2 simulations" read as a contradiction; they
                are a sweep across the range and a separate feasibility
                probe, and each says which it is. */}
            <span>
              <strong>Range sweep</strong> · {sweepForStation.simulations_run} simulation
              {sweepForStation.simulations_run === 1 ? "" : "s"}
            </span>
          </p>
          {!sweepForStation.monotonic && (
            <p className="sensitivity__warn" data-testid="sensitivity-non-monotonic">
              Output does not fall consistently as this value rises, so no single threshold would
              describe it.
            </p>
          )}
        </div>
      )}

      {thresholdForStation && (
        <div
          className={
            thresholdForStation.threshold != null ? "sensitivity__requirement" : "sensitivity__finding"
          }
          data-testid="threshold-result"
        >
          <p className="sensitivity__requirement-title">
            <Target size={14} strokeWidth={2.2} aria-hidden="true" />
            {thresholdForStation.threshold != null ? "Engineering requirement" : "Finding"}
          </p>
          <p className="sensitivity__statement" data-testid="threshold-statement">
            {thresholdForStation.statement}
          </p>
          <p className="sensitivity__summary">
            <span>
              <strong>Target-feasibility probe</strong> · {thresholdForStation.simulations_run}{" "}
              simulation{thresholdForStation.simulations_run === 1 ? "" : "s"}
              {thresholdForStation.threshold != null ? ", by bisection" : ""}
            </span>
          </p>
        </div>
      )}

      {error && (
        <p className="estimate__error" data-testid="sensitivity-error">
          {error}
        </p>
      )}
    </section>
  );
}
