import { RotateCcw } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { ArchitecturePanel } from "../playback/ArchitecturePanel";
import { ProjectBar } from "../project/ProjectBar";

/**
 * Phase 12 §3 — the top bar carries identity on the left and the level
 * switch on the right, and nothing else competes with them.
 *
 * The Executive/Engineering control is a segmented switch rather than two
 * loose buttons: these are two views of ONE state, not two destinations,
 * and a segmented control is the standard way to say so. Both halves keep
 * their `aria-pressed` and their test ids.
 *
 * There is no Demo Mode. A guided eight-step presentation strip existed
 * here and was audited twice: four of its steps had no consumer, two only
 * moved the 3D camera while the demo ran in 2D, and one was a no-op
 * because Executive already selects the recommended strategy. Its single
 * useful action — opening playback — is a primary button in the results.
 *
 * It was left unmounted for a while, which was the wrong resting place: the
 * component was gone from the screen while its eight-stage script stayed in
 * AppState, in the reducer and on the app context, serving nothing. A
 * presentation script in the core state shape is how a product starts
 * behaving like a slideshow, so the whole thing is removed rather than
 * parked.
 */
export function TopBar() {
  const { state, resetSession, setViewLevel } = useAppContext();

  return (
    <header className="top-bar">
      <div className="top-bar__identity">
        {/* The project, not the brand, is the identity once one is open:
            the engineer needs to know WHICH piece of work is on screen. */}
        {/* One implementation of the project identity and its save state,
            shared with the product and concept routes — two copies would be
            two chances for the save indicator to disagree with itself. */}
        {state.project.id ? <ProjectBar /> : <span className="top-bar__brand">Fabrivium</span>}
        <span className="top-bar__divider" aria-hidden="true" />
        <span className="top-bar__factory-name">
          {state.factory ? state.factory.name : state.factoryLoading ? "Loading factory…" : "No factory loaded"}
        </span>
      </div>

      <div className="top-bar__spacer" />

      <div className="level-switch" role="group" aria-label="Presentation level" data-testid="view-level-toggle">
        <button
          type="button"
          className={`level-switch__option ${state.viewLevel === "EXECUTIVE" ? "level-switch__option--active" : ""}`}
          onClick={() => setViewLevel("EXECUTIVE")}
          aria-pressed={state.viewLevel === "EXECUTIVE"}
          data-testid="view-level-executive"
          title="What should I do? — the decision"
        >
          Executive
        </button>
        <button
          type="button"
          className={`level-switch__option ${state.viewLevel === "ENGINEERING" ? "level-switch__option--active" : ""}`}
          onClick={() => setViewLevel("ENGINEERING")}
          aria-pressed={state.viewLevel === "ENGINEERING"}
          data-testid="view-level-engineering"
          title="Why should I trust this? — the evidence"
        >
          Engineering
        </button>
      </div>

      <ArchitecturePanel />

      {/* Phase 7C: the one-shot "Run Planning" button was removed here. */}
      <button
        className="fm-btn-secondary top-bar__reset"
        onClick={resetSession}
        disabled={!state.conversation && !state.session}
        title="Clear the conversation and every planning option, and return to baseline"
      >
        <RotateCcw size={14} strokeWidth={2} aria-hidden="true" />
        Reset
      </button>
    </header>
  );
}
