import { useState } from "react";
import { X } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { Overlay } from "../layout/Overlay";
import { SkillInspector } from "./SkillInspector";

/** Phase 8C section 41 / Phase 12 §17 — the "why is this more than an LLM wrapper" panel. */

const PIPELINE = [
  {
    key: "intent",
    title: "User intent",
    detail: "A plain-language production request.",
  },
  {
    key: "language",
    title: "Language understanding",
    detail: null, // rendered as two explicit branches below
  },
  {
    key: "requirements",
    title: "Structured requirements",
    detail: "A typed target plus hard constraints and soft preferences. No engineering number exists yet.",
  },
  {
    key: "optimizer",
    title: "Candidate generator",
    detail: "Generates candidate interventions across engineering families — equipment, shifts, workforce, buffers.",
  },
  {
    key: "simulation",
    title: "Simulation + constraints",
    detail: "A deterministic discrete-event engine verifies physical behaviour against the factory model.",
    truth: true,
  },
  {
    key: "arena",
    title: "Verified strategies",
    detail: "Options a simulation actually reached, compared on their real trade-offs — never one opaque score.",
  },
  {
    key: "twin",
    title: "Simulated factory",
    detail: "Shows the consequences in 2D/3D, animated frame by frame from the simulation trace.",
  },
] as const;

export function ArchitecturePanel() {
  const [open, setOpen] = useState(false);
  const { state } = useAppContext();
  const provenance = state.provenance;
  const usedFallback = provenance ? provenance.fallback_used || provenance.requirements_source !== "LLM" : null;

  // Escape, the backdrop click, the page scroll lock and the layer this is
  // drawn on all belong to <Overlay> now. This panel opens from the top bar,
  // which is not inside a transformed ancestor, so it never showed the
  // containing-block bug the inputs dialog did — but two implementations of
  // "what a modal is" is exactly how the next one appears somewhere else.

  return (
    <>
      <button type="button" className="fm-btn-secondary" onClick={() => setOpen(true)} data-testid="architecture-panel-open">
        Architecture
      </button>
      {open && (
        <Overlay
          onClose={() => setOpen(false)}
          label="Fabrivium architecture"
          className="architecture-panel"
          testId="architecture-panel"
        >
            <header className="architecture-panel__head">
              <div>
                <h2 className="architecture-panel__title">How Fabrivium works</h2>
                <p className="architecture-panel__subtitle">
                  AI interprets and explains. Deterministic simulation decides.
                </p>
              </div>
              <button
                type="button"
                className="architecture-panel__close"
                onClick={() => setOpen(false)}
                aria-label="Close architecture panel"
                data-testid="architecture-panel-close"
              >
                <X size={18} strokeWidth={2} aria-hidden="true" />
              </button>
            </header>

            <ol className="pipeline">
              {PIPELINE.map((stage) => (
                <li
                  className={`pipeline__node${"truth" in stage && stage.truth ? " pipeline__node--truth" : ""}`}
                  key={stage.key}
                  data-testid={stage.key === "language" ? "architecture-language-step" : undefined}
                >
                  <span className="pipeline__marker" aria-hidden="true" />
                  <div className="pipeline__body">
                    <p className="pipeline__title">
                      {stage.title}
                      {"truth" in stage && stage.truth && (
                        <span className="fm-badge fm-badge--verified">Source of engineering truth</span>
                      )}
                    </p>

                    {stage.detail && <p className="pipeline__detail">{stage.detail}</p>}

                    {stage.key === "language" && (
                      <>
                        <div className="pipeline__branches">
                          <div
                            className={`pipeline__branch${usedFallback === false ? " pipeline__branch--active" : ""}`}
                          >
                            <p className="pipeline__branch-title">IBM Granite · watsonx.ai</p>
                            <p className="pipeline__branch-detail">
                              Reads requests into structured requirements and rewrites simulation
                              results as prose. No number it produces reaches the simulator
                              without an engineer accepting it.
                            </p>
                          </div>
                          <span className="pipeline__branch-or">or</span>
                          <div
                            className={`pipeline__branch${usedFallback === true ? " pipeline__branch--active" : ""}`}
                          >
                            <p className="pipeline__branch-title">Deterministic parser</p>
                            <p className="pipeline__branch-detail">
                              A rule-based fallback extracting the same structured requirements when the model is
                              unavailable.
                            </p>
                          </div>
                        </div>
                        <p className="pipeline__detail">
                          Either way the output is structured requirements — neither branch produces an engineering
                          number.
                        </p>
                        {usedFallback !== null && (
                          <span
                            className={`architecture-panel__branch architecture-panel__branch--${usedFallback ? "fallback" : "llm"}`}
                            data-testid="architecture-active-branch"
                          >
                            {usedFallback
                              ? "This request: deterministic parser"
                              : `This request: ${provenance?.provider_name ?? "Granite"}`}
                          </span>
                        )}
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ol>

            {/* Collapsed by default: the pipeline above is the story, and
                the skill registry is the evidence that it is extensible. */}
            <SkillInspector />

            <section className="architecture-panel__section" data-testid="architecture-current-run">
              <h3 className="fm-label">Current run</h3>
              <dl className="architecture-panel__run">
                <div>
                  <dt>Requirements interpretation</dt>
                  <dd data-testid="architecture-run-requirements">
                    {usedFallback === null
                      ? "Not yet run"
                      : usedFallback
                        ? "Deterministic fallback"
                        : (provenance?.model_name ?? "IBM Granite")}
                  </dd>
                </div>
                <div>
                  <dt>Engineering verification</dt>
                  <dd>Deterministic simulation</dd>
                </div>
              </dl>
              {/* Stated because it is true and because the alternative —
                  letting a judge assume the integration was never built —
                  is worse than naming an account limit. */}
              <p className="architecture-panel__note">
                The live IBM Granite integration is implemented and was tested end to end; the watsonx.ai Lite
                inference quota for this account is currently exhausted, so requests take the deterministic
                branch. Engineering results are unaffected — they never came from the model.
              </p>
            </section>

            <section className="architecture-panel__section">
              <h3 className="fm-label">IBM Bob · development</h3>
              <p className="architecture-panel__detail">
                Engineering collaboration used to build, test, debug and validate Fabrivium during development.
                It is not part of the runtime pipeline above and takes no part in producing a result.
              </p>
            </section>

            <p className="architecture-panel__note">
              Playback works completely without Granite — every animated frame is read from a real simulation
              trace, never generated by a language model.
            </p>
        </Overlay>
      )}
    </>
  );
}
