import { useState } from "react";
import { useAppContext } from "../../state/AppContext";

/**
 * Phase 9A section 6/16 — keeps a follow-up entry point visible even after
 * a result exists (Phase 9A audit finding: the pre-fix Executive layout
 * had no way to refine once `GoalInput` disappeared behind results).
 * Wired to the EXACT SAME `sendMessage` conversational action Engineering
 * View's `ConversationPanel` uses — Phase 7C's constraint-accumulation
 * ("constraints you do not mention again are kept") is untouched, this is
 * only a second, compact entry point into it.
 */
export function RefineBar() {
  const { state, sendMessage, exploreOptions } = useAppContext();
  const [draft, setDraft] = useState("");
  const busy = state.conversationSending || state.exploring;
  const canSend = Boolean(state.factory) && draft.trim().length > 0 && !busy;

  /** Phase 11 §8 — refining an EXPLORATION must stay an exploration. */
  const submit = () => {
    if (!canSend) return;
    const message = draft.trim();
    setDraft("");

    // EVERY earlier turn, not just the most recent one — otherwise a third
    // refinement would quietly drop the first turn's constraints.
    const priorTurns = state.exploreRequests.filter((t) => t.trim().length > 0);
    if (state.arena && priorTurns.length > 0) {
      void exploreOptions(message, priorTurns);
      return;
    }
    void sendMessage(message);
  };

  return (
    <div className="refine-bar" data-testid="refine-bar">
      <input
        type="text"
        className="refine-bar__input"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="Refine further — e.g. Do it without buying another machine."
        data-testid="refine-bar-input"
      />
      <button type="button" className="fm-btn-secondary" disabled={!canSend} onClick={submit} data-testid="refine-bar-submit">
        {state.conversationSending ? "Running…" : "Refine"}
      </button>
    </div>
  );
}
