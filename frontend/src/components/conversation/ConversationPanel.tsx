import { useEffect, useRef, useState } from "react";
import type { ConversationTurn } from "../../api/types";
import { useAppContext } from "../../state/AppContext";
import { ActiveConstraints } from "./ActiveConstraints";
import { BranchComparisonCard } from "./BranchComparisonCard";
import { BranchSelector } from "./BranchSelector";
import { StrategyArenaPanel } from "../strategy/StrategyArenaPanel";

/** Phase 7C section 16 — the engineering conversation. */

const EXAMPLE_OPENERS = [
  "We need 600 units/day, budget €120k.",
  "That's too expensive. Keep it below €150k.",
  "Allow €180k, but don't modify Assembly.",
  "Packaging is allowed again.",
];

const STATUS_LABEL: Record<ConversationTurn["status"], string> = {
  APPLIED: "Plan updated",
  NO_CHANGE: "No change",
  CLARIFICATION_REQUIRED: "Needs clarification",
  REJECTED: "Not applied",
  PROVIDER_UNAVAILABLE: "Could not interpret",
};

const STATUS_TONE: Record<ConversationTurn["status"], "verified" | "unknown" | "bad"> = {
  APPLIED: "verified",
  NO_CHANGE: "unknown",
  CLARIFICATION_REQUIRED: "unknown",
  REJECTED: "bad",
  PROVIDER_UNAVAILABLE: "bad",
};

function TurnCard({ turn }: { turn: ConversationTurn }) {
  const { state, selectBranch } = useAppContext();
  const branch = state.conversation?.branches.find((b) => b.branch_id === turn.branch_id) ?? null;

  return (
    <div className="turn" data-testid={`turn-${turn.turn_index}`}>
      <div className="turn__user" data-testid={`turn-user-${turn.turn_index}`}>
        <span className="turn__who">You</span>
        <p className="turn__message">{turn.raw_user_message}</p>
      </div>

      <div className="turn__reply" data-testid={`turn-reply-${turn.turn_index}`}>
        <span className="turn__who">
          Fabrivium{" "}
          <span className={`fm-badge fm-badge--${STATUS_TONE[turn.status]}`} data-testid={`turn-status-${turn.turn_index}`}>
            {STATUS_LABEL[turn.status]}
          </span>
        </span>

        {/* The deterministic diff — rendered from typed values, so it can
            never describe a change that did not happen. */}
        {turn.changes.length > 0 && (
          <ul className="turn__changes" data-testid={`turn-changes-${turn.turn_index}`}>
            {turn.changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
        )}

        {turn.clarification && (
          <div className="turn__clarification" data-testid={`turn-clarification-${turn.turn_index}`}>
            <p className="turn__question">{turn.clarification.question}</p>
            {turn.clarification.safe_options.length > 0 && (
              <ul className="turn__options">
                {turn.clarification.safe_options.map((option) => (
                  <li key={option}>{option}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {branch && (
          <button
            type="button"
            className="turn__branch-link"
            onClick={() => selectBranch(branch.branch_id)}
            data-testid={`turn-branch-link-${turn.turn_index}`}
          >
            {branch.label}: {branch.summary}
          </button>
        )}

        {turn.errors.length > 0 && (
          <ul className="turn__errors" data-testid={`turn-errors-${turn.turn_index}`}>
            {turn.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        {turn.warnings.length > 0 && (
          <ul className="turn__warnings">
            {turn.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        )}

        <p className="turn__provenance" data-testid={`turn-provenance-${turn.turn_index}`}>
          Interpreted by{" "}
          {turn.provenance.update_source === "LLM"
            ? (turn.provenance.model_name ?? "the model")
            : "deterministic parsing"}
          {turn.provenance.total_tokens != null && ` · ${turn.provenance.total_tokens.toLocaleString()} tokens`}
        </p>
      </div>
    </div>
  );
}

export function ConversationPanel() {
  const { state, sendMessage, exploreOptions } = useAppContext();
  const [draft, setDraft] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  const turns = state.conversation?.turns ?? [];
  const busy = state.conversationSending || state.exploring;
  const canSend = Boolean(state.factory) && draft.trim().length > 0 && !busy;

  // Keep the newest turn in view without stealing focus from the input.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [turns.length]);

  const submit = () => {
    if (!canSend) return;
    const message = draft;
    setDraft("");
    void sendMessage(message);
  };

  /** Phase 8B: the same request, answered with SEVERAL verified strategies instead of one. */
  const explore = () => {
    if (!canSend) return;
    const message = draft;
    setDraft("");
    void exploreOptions(message);
  };

  return (
    <section className="left-panel fm-panel" data-testid="conversation-panel">
      <div className="fm-section">
        <p className="fm-section__title">Engineering conversation</p>

        <div className="conversation-log" ref={logRef} data-testid="conversation-log">
          {turns.length === 0 ? (
            <p className="fm-empty">
              Describe what you need. You can refine it afterwards — constraints you do not
              mention again are kept.
            </p>
          ) : (
            turns.map((turn) => <TurnCard key={turn.turn_index} turn={turn} />)
          )}
          {state.conversationSending && (
            <p className="conversation-log__pending" data-testid="conversation-pending">
              Planning and verifying…
            </p>
          )}
          {state.exploring && (
            <p className="conversation-log__pending" data-testid="exploring-pending">
              Exploring and verifying several strategies…
            </p>
          )}
        </div>

        <label htmlFor="conversation-input" className="fm-label">
          What do you want to change?
        </label>
        <textarea
          id="conversation-input"
          className="planning-request__textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="e.g. That's too expensive. Keep it below €150k."
        />

        {turns.length === 0 && (
          <div className="planning-request__examples">
            {EXAMPLE_OPENERS.map((example) => (
              <button
                key={example}
                type="button"
                className="planning-request__example"
                onClick={() => setDraft(example)}
              >
                “{example}”
              </button>
            ))}
          </div>
        )}

        <div className="conversation-actions">
          <button className="fm-btn" disabled={!canSend} onClick={submit}>
            {state.conversationSending ? "Running…" : "SEND"}
          </button>
          <button
            className="fm-btn-secondary"
            disabled={!canSend}
            onClick={explore}
            data-testid="explore-options"
            title="Verify several different engineering strategies for this goal"
          >
            {state.exploring ? "Exploring…" : "EXPLORE OPTIONS"}
          </button>
        </div>
      </div>

      <ActiveConstraints />
      <StrategyArenaPanel />
      <BranchSelector />
      <BranchComparisonCard />
    </section>
  );
}
