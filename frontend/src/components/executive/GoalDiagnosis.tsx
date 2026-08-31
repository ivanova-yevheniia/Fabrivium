import { useAppContext } from "../../state/AppContext";
import { formatNumber } from "../../utils/formatting";
import { limitingStageLabel } from "../../utils/limitingStage";
import { InterpretedRequirement } from "./InterpretedRequirement";
import type { StageStats } from "../../utils/executiveSummary";
import { useStationName } from "../../utils/useStationName";
import { scenarioWords } from "../../utils/scenario";

/**
 * Phase 12 §4 — the two questions that must be answered before the
 * recommendation means anything: what was asked for, and what is stopping
 * it today.
 *
 * Finding this replaces: the goal was never stated on the results screen at
 * all. The target only appeared as the denominator of "1,105 / 1,900
 * units/day" inside a bordered BASELINE card, three quiet blocks down the
 * page, so the first question a judge asks ("what does this factory need?")
 * had no answer with any visual weight behind it.
 *
 * Every value is read from state that already existed:
 *   goal + constraints  ← state.parseResult.parsed_requirements
 *   baseline production ← arena.baseline_metrics (verified simulation)
 *   limiting stage      ← arena.baseline_metrics.bottleneck_machine_id
 *
 * The constraint chips are the Phase 11 §4 component unchanged, so a hard
 * constraint the engine enforces and a soft preference that only orders
 * options stay visibly different, and a constraint the parser could not
 * read still produces NO chip — a silent drop remains a visible absence.
 *
 * `limitingStageLabel` decides between "Bottleneck" and "Limiting stage":
 * a stage is only called a bottleneck when demand was actually missed
 * (Phase 9A §8). That rule is consumed here, never re-implemented.
 */
export function GoalDiagnosis({ baseline }: { baseline: StageStats }) {
  const stationLabel = useStationName();
  const { state } = useAppContext();
  const arena = state.arena;
  // "Today, without changes" is a true sentence about the bundled example
  // line and a false one about a concept for a factory nobody has built.
  // See utils/scenario.ts for why this asks rather than assumes.
  const words = scenarioWords(state);

  return (
    <section className="goal-diagnosis" data-testid="goal-diagnosis">
      <div className="goal-diagnosis__goal">
        <p className="fm-label">Your production goal</p>
        <p className="goal-diagnosis__target">
          <span className="fm-mono" data-testid="goal-diagnosis-target">
            {formatNumber(baseline.targetUnits)}
          </span>
          <span className="goal-diagnosis__unit">units/day</span>
        </p>
        {/* The target is the headline above, so it is not repeated as a
            chip; every other understood constraint still is. */}
        <InterpretedRequirement omitTarget />
      </div>

      <div className="goal-diagnosis__problem" data-testid="baseline-summary">
        <p className="fm-label" data-testid="baseline-label">
          {words.baseline}
        </p>
        <div className="goal-diagnosis__stats">
          <div className="goal-diagnosis__stat">
            <span className="goal-diagnosis__stat-value fm-mono">{formatNumber(baseline.completedUnits)}</span>
            <span className="goal-diagnosis__stat-label">units/day produced</span>
          </div>
          {!baseline.met && (
            <div className="goal-diagnosis__stat goal-diagnosis__stat--bad">
              <span className="goal-diagnosis__stat-value fm-mono">−{formatNumber(baseline.gapUnits)}</span>
              <span className="goal-diagnosis__stat-label">units/day short</span>
            </div>
          )}
          <div className="goal-diagnosis__stat goal-diagnosis__stat--wide">
            <span className="goal-diagnosis__stat-value goal-diagnosis__stat-value--name">
              {stationLabel(baseline.bottleneckMachineId)}
            </span>
            <span className="goal-diagnosis__stat-label">{limitingStageLabel({ demand_met: baseline.met })}</span>
          </div>
        </div>
        {arena && (
          <p className="goal-diagnosis__search" data-testid="analysis-reveal">
            {formatNumber(arena.stats.simulations_run)} simulations evaluated ·{" "}
            {formatNumber(arena.strategies.length)} strategies compared
          </p>
        )}
      </div>
    </section>
  );
}
