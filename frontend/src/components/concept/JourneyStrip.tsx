import { useAppContext } from "../../state/AppContext";

/** Phase 14 §14 — where the user is, without turning the product into a wizard. */

const STEPS = ["Brief", "Concept", "Verify", "Improve", "Handoff"] as const;
type Step = (typeof STEPS)[number];

/** Which step the CURRENT state corresponds to. */
function currentStep(state: ReturnType<typeof useAppContext>["state"]): Step | null {
  if (state.startMode === "CHOOSING") return null;
  // Only the concept journey has these steps.
  if (state.startMode === "CONCEPT_BUILDER") {
    return state.concept.draft ? "Concept" : "Brief";
  }
  if (state.concept.draft === null) return null;

  if (state.arena) {
    // A recommendation exists; the user is comparing and can move on.
    return "Improve";
  }
  if (state.exploring || state.session) return "Verify";
  return "Concept";
}

export function JourneyStrip() {
  const { state } = useAppContext();
  const active = currentStep(state);
  if (active === null) return null;

  const activeIndex = STEPS.indexOf(active);

  return (
    <nav className="journey" aria-label="Project progress" data-testid="journey">
      <ol className="journey__steps">
        {STEPS.map((step, index) => {
          const done = index < activeIndex;
          const isActive = index === activeIndex;
          return (
            <li
              key={step}
              className={`journey__step${isActive ? " journey__step--active" : ""}${done ? " journey__step--done" : ""}`}
              data-testid={`journey-step-${step.toLowerCase()}`}
              aria-current={isActive ? "step" : undefined}
            >
              {step}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
