import { useAppContext } from "../../state/AppContext";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { formatNumber } from "../../utils/formatting";
import { statsFromStrategyMetrics } from "../../utils/executiveSummary";

/** Phase 9A section 9 — the screenshot-quality final state. */
export function FinalSuccessBanner() {
  const { state } = useAppContext();
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  if (!arena || !selected) return null;

  const before = statsFromStrategyMetrics(arena.baseline_metrics);
  const after = statsFromStrategyMetrics(selected.metrics);
  const gaps = selected.cost.information_gaps;
  const recommended = arena.strategies.find((s) => s.strategy_id === arena.recommended_strategy_id);
  const isRecommended = recommended !== undefined && recommended.strategy_id === selected.strategy_id;

  return (
    <div className={`final-success-banner${after.met ? " final-success-banner--achieved" : ""}`} data-testid="final-success-banner">
      <p className="final-success-banner__headline">{after.met ? "TARGET ACHIEVED" : "TARGET NOT YET REACHED"}</p>
      <p className="final-success-banner__subject" data-testid="final-success-banner-subject">
        <strong>{selected.label}</strong>
        {recommended &&
          (isRecommended ? (
            <span className="final-success-banner__rec"> · recommended strategy</span>
          ) : (
            <span className="final-success-banner__rec" data-testid="final-success-banner-not-recommended">
              {" "}
              · your selection — recommended is {recommended.label}
            </span>
          ))}
      </p>
      <div className="final-success-banner__stats">
        <span className="fm-mono">
          {formatNumber(before.completedUnits)} → {formatNumber(after.completedUnits)} units/day
        </span>
        <span className="fm-mono">
          {formatNumber(before.gapUnits)} → {formatNumber(after.gapUnits)} production gap
        </span>
        <span className="fm-mono">
          {selected.actions.added_machine_count} new machine{selected.actions.added_machine_count === 1 ? "" : "s"}
        </span>
      </div>
      {/* SCOPE OF "VERIFIED". */}
      <p className="final-success-banner__note">
        <span className="fm-badge fm-badge--verified">Verified</span> by deterministic
        simulation of the current engineering model
      </p>
      {/* Phase 9B section 11D — compact: the full provenance sentence is
          already stated once at the top of the results. Source, tone and
          the fallback/Granite distinction are still shown here. */}
      <ProvenanceBadge provenance={state.provenance} compact />
      {gaps.length > 0 && (
        <div className="final-success-banner__gaps" data-testid="final-success-banner-gaps">
          <p className="final-success-banner__gaps-title">Cost information still required for this plan</p>
          <ul>
            {gaps.map((gap) => (
              <li key={gap.gap_type}>{gap.description}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
