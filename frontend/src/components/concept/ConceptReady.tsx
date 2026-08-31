import { ArrowRight, CircleAlert, PencilRuler, Play } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { CenterWorkspace } from "../layout/CenterWorkspace";
import { JourneyStrip } from "./JourneyStrip";

/** Phase 14 §6/§7 — what a freshly built concept looks like. */
export function ConceptReady() {
  const { state, exploreOptions, setStartMode } = useAppContext();
  const draft = state.concept.draft;
  const factory = state.factory;
  if (!factory) return null;

  const target = draft?.production_target.value ?? factory.products[0]?.demand_per_day ?? null;
  const stageNames = factory.machines.map((machine) => machine.name);

  // The verification request is built from what the concept already
  // captured, so the target and the stated preference cannot drift from the
  // brief the user gave. Same `exploreOptions` action the Executive entry
  // uses — there is no concept-specific analysis path.
  const verificationRequest = [
    target !== null ? `We need ${Math.round(target)} units/day.` : "",
    draft?.prefer_no_new_machines ? "Avoid buying new machines if possible." : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="concept-ready" data-testid="concept-ready">
      <JourneyStrip />
      <header className="concept-ready__head">
        <p className="fm-label">Factory concept created</p>
        <h1 className="concept-ready__title">{factory.name}</h1>
        <p className="concept-ready__detail">
          Built from your product specification and production requirements. Nothing has been
          simulated yet — the next step verifies whether this concept can actually meet the target.
        </p>
      </header>

      <section className="concept-ready__facts">
        <div className="concept-ready__fact">
          <span className="fm-label">Production target</span>
          <span className="concept-ready__fact-value fm-mono" data-testid="concept-ready-target">
            {target !== null ? target.toLocaleString("en-US") : "—"}
          </span>
          <span className="concept-ready__fact-unit">units/day</span>
        </div>
        <div className="concept-ready__fact">
          <span className="fm-label">Process</span>
          <span className="concept-ready__fact-flow" data-testid="concept-ready-flow">
            {stageNames.map((name, index) => (
              <span key={name} className="concept-ready__flow-stage">
                <span className="concept-ready__flow-index fm-mono">{index + 1}</span>
                {name}
                {index < stageNames.length - 1 && (
                  <ArrowRight size={13} strokeWidth={2} aria-hidden="true" className="concept-ready__flow-arrow" />
                )}
              </span>
            ))}
          </span>
        </div>
        <div className="concept-ready__fact">
          <span className="fm-label">Floor</span>
          <span className="concept-ready__fact-value fm-mono">
            {factory.width} × {factory.length}
          </span>
          <span className="concept-ready__fact-unit">m</span>
        </div>
      </section>

      <section className="concept-ready__layout" data-testid="concept-layout-reveal">
        <header className="concept-ready__layout-head">
          <h2 className="fm-section__title">Concept layout</h2>
          <p className="concept-ready__layout-note">
            An early-stage arrangement for process and simulation — stations in route order inside the
            available floor. It is not an optimised layout and not CAD, and because the simulator reads no
            placement, moving a station changes validity, never output. Detailed engineering follows concept
            approval.
          </p>
        </header>
        <div className="concept-ready__twin">
          <CenterWorkspace />
        </div>
      </section>

      {/* Equipment is genuinely unresolved at concept stage, and saying so is
          part of the product's argument: you do not need to have chosen a
          machine to find out whether the concept works. */}
      <section className="concept-ready__open" data-testid="concept-ready-open-items">
        <p className="concept-ready__open-title">
          <CircleAlert size={14} strokeWidth={2} aria-hidden="true" />
          Still open at concept stage
        </p>
        <ul>
          <li>Specific equipment is not selected — each station carries a requirement, not a machine.</li>
          <li>Commercial data is incomplete wherever a price is unknown.</li>
        </ul>
      </section>

      <footer className="concept-ready__foot">
        <button
          type="button"
          className="fm-btn concept-ready__cta"
          onClick={() => void exploreOptions(verificationRequest)}
          disabled={state.exploring || !verificationRequest}
          data-testid="concept-verify"
        >
          <Play size={15} strokeWidth={2.4} fill="currentColor" aria-hidden="true" />
          Verify production concept
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          onClick={() => setStartMode("CONCEPT_BUILDER")}
          data-testid="concept-ready-back"
        >
          <PencilRuler size={14} strokeWidth={2} aria-hidden="true" />
          Edit concept
        </button>
        <span className="concept-ready__foot-note">
          Runs the deterministic simulator against this concept.
        </span>
      </footer>
    </div>
  );
}
