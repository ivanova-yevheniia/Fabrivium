import { MoveRight } from "lucide-react";
import { useAppContext } from "../../state/AppContext";
import { formatNumber } from "../../utils/formatting";
import { statsFromStrategyMetrics } from "../../utils/executiveSummary";
import { interventionPhrases } from "../../utils/interventionSummary";
import { limitingStageLabel } from "../../utils/limitingStage";
import { limitingStageMove } from "../../utils/planDelta";
import { scenarioWords, transitionLabel } from "../../utils/scenario";
import { useStationName } from "../../utils/useStationName";

/** Phase 9A section 7 / Phase 12 §11 — the baseline/plan comparison. */
export function BeforeAfterHero() {
  const stationLabel = useStationName();
  const { state } = useAppContext();
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  if (!arena || !selected) return null;

  const before = statsFromStrategyMetrics(arena.baseline_metrics);
  const after = statsFromStrategyMetrics(selected.metrics);
  const changes = interventionPhrases(selected.actions, state.factory?.machines);
  const words = scenarioWords(state);
  const moved = limitingStageMove(arena.baseline_metrics, selected.metrics, state.factory);

  return (
    <section className="before-after-hero" data-testid="before-after-hero">
      <h2 className="fm-section__title" data-testid="before-after-heading">
        Verified comparison — {transitionLabel(words, selected.label)}
      </h2>

      <div className="before-after-hero__row">
        <div className="ba-state ba-state--before">
          <span className="fm-label" data-testid="ba-baseline-label">
            {words.baselineShort}
          </span>
          <span className="ba-state__value fm-mono">{formatNumber(before.completedUnits)}</span>
          <span className="ba-state__unit">units/day</span>
          <span className="ba-state__note ba-state__note--bad">
            {formatNumber(before.gapUnits)} short of target
          </span>
          <span className="ba-state__note">
            {limitingStageLabel({ demand_met: before.met })}: {stationLabel(before.bottleneckMachineId)}
          </span>
        </div>

        {/* The intervention IS the causal link, so it is rendered as the
            connector between the two states rather than as a third list
            beside them. */}
        <div className="ba-link" data-testid="before-after-intervention">
          <span className="ba-link__rail" aria-hidden="true" />
          <ul className="ba-link__changes">
            {changes.map((change) => (
              <li key={change}>{change}</li>
            ))}
          </ul>
          <span className="ba-link__rail" aria-hidden="true" />
        </div>

        <div className="ba-state ba-state--after">
          <span className="fm-label" data-testid="ba-selected-label">
            {selected.label}
          </span>
          <span className="ba-state__value ba-state__value--good fm-mono">
            {formatNumber(after.completedUnits)}
          </span>
          <span className="ba-state__unit">units/day</span>
          <span className={`ba-state__note${after.met ? " ba-state__note--good" : " ba-state__note--bad"}`}>
            {after.met ? "Target achieved" : `${formatNumber(after.gapUnits)} short of target`}
          </span>
          <span className="ba-state__note">
            {limitingStageLabel({ demand_met: after.met })}: {stationLabel(after.bottleneckMachineId)}
          </span>
        </div>
      </div>

      {moved && (
        <p className="limiting-move" data-testid="limiting-stage-moved">
          <span className="limiting-move__tag">Limiting stage moved</span>
          <span className="limiting-move__from">{moved.from}</span>
          <MoveRight size={14} strokeWidth={2.2} aria-hidden="true" />
          <span className="limiting-move__to">{moved.to}</span>
          <span className="limiting-move__note">
            The constraint did not disappear — it is now {moved.to}, which is where further
            capacity would have to go.
          </span>
        </p>
      )}
    </section>
  );
}
