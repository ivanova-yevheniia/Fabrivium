import { useAppContext } from "../../state/AppContext";

const DISPLAY_SECTIONS = ["Executive Summary", "What Changed", "Tradeoffs", "Why Planning Stopped"];

/** Renders exactly the backend-verified PlanningExplanation — never
 * recomputes or rephrases an engineering conclusion in the frontend
 * (Phase 6A section 7). */
export function ExplanationPanel() {
  const { state } = useAppContext();
  const explanation = state.explanation;

  if (!explanation) {
    return (
      <div className="fm-section" data-testid="explanation-panel">
        <p className="fm-section__title">Explanation</p>
        <p className="fm-empty">Run a plan to see a verified explanation of the result.</p>
      </div>
    );
  }

  const sections = explanation.sections.filter((s) => DISPLAY_SECTIONS.includes(s.title));

  return (
    <div className="fm-section" data-testid="explanation-panel">
      <p className="fm-section__title">
        Explanation{" "}
        <span className={`fm-badge fm-badge--${explanation.source_type === "DETERMINISTIC" ? "verified" : "unknown"}`}>
          {explanation.source_type}
        </span>
      </p>
      {sections.map((section) => (
        <div className="explanation-section" key={section.title}>
          <p className="explanation-section__title">{section.title}</p>
          <p className="explanation-section__content">{section.content}</p>
        </div>
      ))}
    </div>
  );
}
