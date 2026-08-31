import { useAppContext } from "../../state/AppContext";
import { activeScenario } from "../../utils/scenario";
import { resolveStage } from "../../utils/stage";
import { statsFromSimulationResult, statsFromStrategyMetrics } from "../../utils/executiveSummary";
import { BeforeAfterHero } from "./BeforeAfterHero";
import { GoalDiagnosis } from "./GoalDiagnosis";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { RecommendationHero } from "./RecommendationHero";
import { RefineBar } from "./RefineBar";
import { RefinementTrace } from "./RefinementTrace";
import { StrategyRail } from "./StrategyRail";
import { CenterWorkspace } from "../layout/CenterWorkspace";
import { StrategyAskBox } from "../strategy/StrategyAskBox";
import { ConceptVerified } from "../concept/ConceptVerified";
import { JourneyStrip } from "../concept/JourneyStrip";
import { BaselineSummary } from "./BaselineSummary";
import { StaleResultsBanner } from "./StaleResultsBanner";

/** Phase 9A — the results body once a plan/exploration has actually returned. */
export function ExecutiveResults() {
  const { state } = useAppContext();
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  // Which run the picture below is actually showing. Follows playback while
  // it is open, the selection otherwise.
  const scenario = activeScenario(state);

  if (arena) {
    const baseline = statsFromStrategyMetrics(arena.baseline_metrics);
    return (
      <div className="executive-results" data-testid="executive-results">
        <StaleResultsBanner />
        {/* Phase 14 — position in the concept journey, when there is one. */}
        <JourneyStrip />
        <GoalDiagnosis baseline={baseline} />

        {/* Why this recommendation and not the last one. */}
        <RefinementTrace />

        {selected && <RecommendationHero />}

        {selected && <BeforeAfterHero />}

        {/* The twin is the EVIDENCE for the plan, so it sits after the
            decision content rather than above it — at baseline it is mostly
            empty floor, and rendered first its fixed height pushed the
            whole comparison below the fold at 1366x768. */}
        <section className="executive-section" data-testid="executive-twin-wrap">
          {/* Follows the run being PLAYED, not the plan selected. */}
          <h2 className="fm-section__title" data-testid="executive-twin-title">
            Simulated factory — {scenario.name}
          </h2>
          <div className="executive-twin-wrap">
            <CenterWorkspace />
          </div>
        </section>

        <StrategyRail />

        {/* Phase 14 §10 — the concept's conclusion. */}
        {state.concept.draft && <ConceptVerified />}

        <div className="executive-followup">
          <RefineBar />
          <StrategyAskBox />
        </div>

        {/* Provenance closes the page instead of opening it: it qualifies
            HOW the request was interpreted, which is context for the
            result, not the headline. It is still stated in full, still
            never claims Granite did work a parser did. */}
        <footer className="executive-footer">
          <ProvenanceBadge provenance={state.provenance} />
        </footer>
      </div>
    );
  }

  // Fallback: SEND path — a single verified plan, no strategy comparison.
  if (state.session) {
    const stage = resolveStage(state.session, state.selectedIteration);
    if (!stage) return null;
    const stats = statsFromSimulationResult(stage.snapshot.simulation);
    return (
      <div className="executive-results" data-testid="executive-results">
        <StaleResultsBanner />
        <section className="executive-section">
          <h2 className="fm-section__title">{stage.label}</h2>
          <BaselineSummary stats={stats} />
        </section>
        <section className="executive-section" data-testid="executive-twin-wrap">
          <h2 className="fm-section__title">Simulated factory</h2>
          <div className="executive-twin-wrap">
            <CenterWorkspace />
          </div>
        </section>
        <div className="executive-followup">
          <RefineBar />
        </div>
        <footer className="executive-footer">
          <ProvenanceBadge provenance={state.provenance} />
        </footer>
      </div>
    );
  }

  return null;
}
