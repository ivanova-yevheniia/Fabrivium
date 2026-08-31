import { Check, X } from "lucide-react";
import type { VerifiedStrategyOption } from "../../api/types";
import { formatNumber } from "../../utils/formatting";
import { primaryInterventionPhrase } from "../../utils/interventionSummary";
import { humanizeStrategyText } from "../../utils/strategyText";
import type { StrategyLabelSource } from "../../utils/strategyText";
import { describeKnownCost } from "../../utils/capex";

/** Phase 8B section 21 — one verified strategy, readable at a glance. */

const FAMILY_LABELS: Record<string, string> = {
  EQUIPMENT_EXPANSION: "Equipment",
  SHIFT_EXPANSION: "Shift-heavy",
  WORKFORCE_EXPANSION: "Workforce",
  BUFFER_FLOW: "Buffer flow",
  PROCESS_IMPROVEMENT: "Process",
  HYBRID: "Hybrid",
};

export function StrategyCard({
  option,
  selected,
  recommended,
  onSelect,
  onCompare,
  comparing,
  allOptions = [],
}: {
  option: VerifiedStrategyOption;
  selected: boolean;
  recommended: boolean;
  onSelect: () => void;
  onCompare?: () => void;
  comparing?: boolean;
  /** Every option in the arena, so backend prose that names another
   * strategy by its internal id can be shown with that plan's real label
   * (see utils/strategyText). Presentation only — never re-ranks. */
  allOptions?: readonly StrategyLabelSource[];
}) {
  const goalMet = option.metrics.goal_met;
  const intervention = primaryInterventionPhrase(option.actions);
  // §4 — a plan that buys nothing has known_capex 0 and an unknown real
  // cost. The shared rule decides what that may look like on screen.
  const capex = describeKnownCost(option.cost, {
    commerciallyComplete: option.commercially_complete,
  });

  return (
    <div
      className={`strategy-card${selected ? " strategy-card--selected" : ""}${recommended ? " strategy-card--recommended" : ""}`}
      data-testid={`strategy-card-${option.strategy_id}`}
      data-selected={selected}
      data-goal-met={goalMet}
    >
      <button type="button" className="strategy-card__main" onClick={onSelect} aria-pressed={selected}>
        <span className="strategy-card__head">
          <span className="strategy-card__label">{option.label}</span>
          <span className="strategy-card__family">{FAMILY_LABELS[option.family] ?? option.family}</span>
          {recommended && (
            <span className="fm-badge fm-badge--verified" data-testid={`strategy-recommended-${option.strategy_id}`}>
              Start here
            </span>
          )}
        </span>

        {/* The outcome, as the card's own headline figure. */}
        <span className={`strategy-card__goal strategy-card__goal--${goalMet ? "met" : "unmet"}`}>
          <span className="strategy-card__goal-icon" aria-hidden="true">
            {goalMet ? <Check size={14} strokeWidth={3} /> : <X size={14} strokeWidth={3} />}
          </span>
          <span className="strategy-card__goal-value fm-mono">{formatNumber(option.metrics.completed_units)}</span>
          <span className="strategy-card__goal-unit">/day</span>
          {!goalMet && (
            <span className="strategy-card__gap">{formatNumber(option.metrics.demand_gap_units)} short</span>
          )}
        </span>

        {intervention && <span className="strategy-card__intervention">{intervention}</span>}

        <span className="strategy-card__capex fm-mono">
          {capex.amount}
          <span className="strategy-card__capex-note">known CAPEX</span>
          {/* Phase 9B section 11C. */}
          {capex.qualifier && (
            <span className="strategy-card__capex-partial" data-testid={`strategy-capex-partial-${option.strategy_id}`}>
              {capex.qualifier}
            </span>
          )}
        </span>

        {/* G14 — recurring money the CAPEX figure does not cover. */}
        {capex.otherDimensions.map((dimension) => (
          <span
            className="strategy-card__capex fm-mono"
            key={dimension.category}
            data-testid={`strategy-cost-${dimension.category.toLowerCase()}-${option.strategy_id}`}
          >
            {dimension.amount}
            <span className="strategy-card__capex-note">{dimension.label.toLowerCase()}</span>
          </span>
        ))}

        <span className="strategy-card__badges">
          <span className="fm-badge fm-badge--verified" data-testid={`strategy-verified-${option.strategy_id}`}>
            Verified
          </span>
          {option.commercially_complete ? (
            <span className="fm-badge fm-badge--verified">Cost complete</span>
          ) : (
            <span className="fm-badge fm-badge--unknown" data-testid={`strategy-needs-cost-${option.strategy_id}`}>
              Requires cost data
            </span>
          )}
        </span>

        <span className="strategy-card__actions">
          {option.actions.action_count} change{option.actions.action_count === 1 ? "" : "s"}
          {option.actions.added_machine_count > 0 && ` · +${option.actions.added_machine_count} machine${option.actions.added_machine_count === 1 ? "" : "s"}`}
          {option.actions.added_shift_count !== 0 && ` · ${option.actions.added_shift_count > 0 ? "+" : ""}${option.actions.added_shift_count} shift`}
          {option.actions.operator_delta !== 0 && ` · ${option.actions.operator_delta > 0 ? "+" : ""}${option.actions.operator_delta} operator${Math.abs(option.actions.operator_delta) === 1 ? "" : "s"}`}
        </span>

        {option.tradeoffs.length > 0 && (
          <span className="strategy-card__tradeoff" data-testid={`strategy-tradeoff-${option.strategy_id}`}>
            {humanizeStrategyText(option.tradeoffs[0], allOptions)}
          </span>
        )}
      </button>

      {onCompare && !selected && (
        <button
          type="button"
          className="strategy-card__compare"
          onClick={onCompare}
          disabled={comparing}
          title={`Compare ${option.label} with the option currently shown`}
        >
          Compare
        </button>
      )}
    </div>
  );
}
