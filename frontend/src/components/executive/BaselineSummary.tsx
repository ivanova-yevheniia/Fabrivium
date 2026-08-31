import { formatNumber } from "../../utils/formatting";
import type { StageStats } from "../../utils/executiveSummary";
import { limitingStageLabel } from "../../utils/limitingStage";
import { useStationName } from "../../utils/useStationName";

/** Phase 9A section 4 — the baseline problem, at a glance. */
export function BaselineSummary({ stats }: { stats: StageStats }) {
  const stationLabel = useStationName();
  return (
    <div className="baseline-summary" data-testid="baseline-summary">
      <div className="baseline-summary__row">
        <span className="baseline-summary__label">Current production</span>
        <span className="baseline-summary__value fm-mono">
          {formatNumber(stats.completedUnits)} / {formatNumber(stats.targetUnits)} units/day
        </span>
      </div>
      {!stats.met && (
        <div className="baseline-summary__row">
          <span className="baseline-summary__label">Shortfall</span>
          <span className="baseline-summary__value fm-mono baseline-summary__value--bad">
            {formatNumber(stats.gapUnits)} units/day
          </span>
        </div>
      )}
      <div className="baseline-summary__row">
        <span className="baseline-summary__label">{limitingStageLabel({ demand_met: stats.met })}</span>
        <span className="baseline-summary__value">{stationLabel(stats.bottleneckMachineId)}</span>
      </div>
    </div>
  );
}
