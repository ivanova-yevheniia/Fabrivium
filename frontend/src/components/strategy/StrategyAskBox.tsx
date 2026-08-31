import { useState } from "react";
import { useAppContext } from "../../state/AppContext";
import { groupGaps, humanizeInternalTokens } from "../../utils/informationGaps";

/** Phase 8B section 15 — follow-ups about the options already on screen. */

const EXAMPLES = [
  "Show me a cheaper option.",
  "Can we do it without another machine?",
  "Which plan uses the fewest changes?",
  "What information do we still need?",
  "An extra shift costs €9k/day.",
];

const INTENT_LABEL: Record<string, string> = {
  CHEAPER_OPTION: "Cost ranking",
  NO_NEW_MACHINE: "Machine-free options",
  FEWEST_CHANGES: "Fewest changes",
  COMPARE: "Comparison",
  INFORMATION_NEEDED: "Missing information",
  PROVIDE_COST: "Cost recorded",
  UNRECOGNIZED: "Not understood",
};

export function StrategyAskBox() {
  const { state, askAboutOptions } = useAppContext();
  const [draft, setDraft] = useState("");

  if (!state.arena) return null;

  const answer = state.strategyAnswer;
  const canAsk = draft.trim().length > 0 && !state.askingStrategy;
  // The stations, so any machine or buffer key inside backend prose is
  // rendered as the name the rest of the screen uses. Prefer the concept
  // draft's stages (the semantic route) and fall back to the factory's
  // machines, which carry the same names for a factory-first project.
  const stations = state.concept.draft?.stages ?? state.factory?.machines ?? null;
  const groups = answer ? groupGaps(answer.information_gaps ?? [], stations) : [];

  const submit = () => {
    if (!canAsk) return;
    const question = draft;
    setDraft("");
    void askAboutOptions(question);
  };

  return (
    <div className="fm-section" data-testid="strategy-ask">
      <p className="fm-section__title">Ask about these options</p>

      {answer && (
        <div className="strategy-answer" data-testid="strategy-answer">
          <span
            className={`fm-badge fm-badge--${answer.intent === "UNRECOGNIZED" ? "unknown" : "verified"}`}
            data-testid="strategy-answer-intent"
          >
            {INTENT_LABEL[answer.intent] ?? answer.intent}
          </span>
          <p className="strategy-answer__text" data-testid="strategy-answer-text">
            {humanizeInternalTokens(answer.answer, stations)}
          </p>

          {groups.length > 0 && (
            <div className="missing-info" data-testid="strategy-answer-gaps">
              <p className="missing-info__title">
                {answer.intent === "INFORMATION_NEEDED"
                  ? "Missing to complete the cost comparison"
                  : "Still required before these options can be compared on cost"}
              </p>
              {groups.map((group) => (
                <div key={group.group} className="missing-info__group">
                  <p className="fm-label">{group.group}</p>
                  <ul>
                    {group.items.map((item) => (
                      <li key={item.type} data-testid={`missing-info-${item.type}`}>
                        <strong>{item.title}</strong>
                        <span className="missing-info__why">{item.description}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}

          {/* Proof, not a promise: the backend reports how many simulations
              it ran to answer, and it is always zero. */}
          <p className="strategy-answer__provenance" data-testid="strategy-answer-provenance">
            Answered from verified data · {answer.simulations_run} simulations run
            {answer.requires_repricing && " · cost re-derived, engineering unchanged"}
          </p>
        </div>
      )}

      <textarea
        id="strategy-ask-input"
        className="planning-request__textarea"
        aria-label="Ask about these options"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="e.g. Which plan uses the fewest changes?"
      />

      <div className="planning-request__examples">
        {EXAMPLES.map((example) => (
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

      <button className="fm-btn-secondary strategy-ask__submit" disabled={!canAsk} onClick={submit}>
        {state.askingStrategy ? "Looking it up…" : "Ask"}
      </button>
    </div>
  );
}
