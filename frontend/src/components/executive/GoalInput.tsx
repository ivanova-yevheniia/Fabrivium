import { useState } from "react";
import { useAppContext } from "../../state/AppContext";

/** Phase 9A section 2 — the Executive View's primary entry point. */

// Shapes of request, deliberately not this product's own figures: a
// placeholder pre-filled with the demo's target reads as a preset.
const EXAMPLE_OPENERS = [
  "We need 600 units/day. Avoid buying new machines if possible.",
  "We need 600 units/day, budget €120k.",
  "That's too expensive. Keep it below €80k.",
];

export function GoalInput() {
  const { state, exploreOptions, sendMessage } = useAppContext();
  const [draft, setDraft] = useState("");

  const busy = state.exploring || state.conversationSending || state.planLoading;
  const canSubmit = Boolean(state.factory) && draft.trim().length > 0 && !busy;

  const explore = () => {
    if (!canSubmit) return;
    const message = draft;
    setDraft("");
    void exploreOptions(message);
  };

  const refine = () => {
    if (!canSubmit) return;
    const message = draft;
    setDraft("");
    void sendMessage(message);
  };

  return (
    <div className="goal-input" data-testid="goal-input">
      <h1 className="goal-input__title">Fabrivium</h1>
      <p className="goal-input__tagline">Compare production strategies — each one checked by deterministic simulation</p>

      <label htmlFor="goal-input-textarea" className="goal-input__label">
        What does your factory need?
      </label>
      <textarea
        id="goal-input-textarea"
        className="goal-input__textarea"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            explore();
          }
        }}
        placeholder="e.g. We need 600 units/day. Avoid buying new machines if possible."
        data-testid="goal-input-textarea"
      />

      <div className="goal-input__examples">
        {EXAMPLE_OPENERS.map((example) => (
          <button key={example} type="button" className="planning-request__example" onClick={() => setDraft(example)}>
            “{example}”
          </button>
        ))}
      </div>

      <div className="goal-input__actions">
        <button
          type="button"
          className="fm-btn"
          disabled={!canSubmit}
          onClick={explore}
          data-testid="goal-input-explore"
          title="Verify several different engineering strategies for this goal"
        >
          {state.exploring ? "Analyzing…" : "SIMULATE STRATEGIES"}
        </button>
        <button
          type="button"
          className="fm-btn-secondary"
          disabled={!canSubmit}
          onClick={refine}
          data-testid="goal-input-refine"
          title="Run one engineering plan for this goal (no comparison across strategies)"
        >
          {state.conversationSending ? "Running…" : "Run a single plan"}
        </button>
      </div>
    </div>
  );
}
