import { useAppContext } from "../../state/AppContext";
import { PlaybackTrigger } from "../playback/PlaybackTrigger";
import { formatCurrency, formatNumber } from "../../utils/formatting";
import { StrategyAskBox } from "./StrategyAskBox";
import { StrategyCard } from "./StrategyCard";
import { useStationName } from "../../utils/useStationName";
import { SearchSpace } from "./SearchSpace";
import { scenarioWords, transitionLabel } from "../../utils/scenario";
import { GAP_TITLE, humanizeInternalTokens } from "../../utils/informationGaps";

/** Phase 8B section 20 — the optimization arena. */

function BeforeAfter() {
  const stationLabel = useStationName();
  const { state } = useAppContext();
  const arena = state.arena;
  const selected = arena?.strategies.find((s) => s.strategy_id === state.selectedStrategyId);
  if (!arena || !selected) return null;

  const before = arena.baseline_metrics;
  const after = selected.metrics;
  // Same vocabulary as the Executive comparison: the two levels are a
  // presentation choice over one state and must not name it differently.
  const words = scenarioWords(state);

  return (
    <div className="fm-section" data-testid="before-after">
      <p className="fm-section__title">{transitionLabel(words, selected.label)}</p>
      <PlaybackTrigger label={`▶ Play ${words.baselineShort.toLowerCase()} and ${selected.label}`} />
      <div className="before-after">
        <div className="before-after__col">
          <span className="before-after__heading">{words.baselineShort}</span>
          <span className="before-after__value fm-mono">{formatNumber(before.completed_units)}/day</span>
          <span className="before-after__sub">gap {formatNumber(before.demand_gap_units)}</span>
          <span className="before-after__sub">{stationLabel(before.bottleneck_machine_id)}</span>
        </div>
        <div className="before-after__arrow">→</div>
        <div className="before-after__col">
          <span className="before-after__heading">{selected.label}</span>
          <span className="before-after__value fm-mono">{formatNumber(after.completed_units)}/day</span>
          <span className="before-after__sub">gap {formatNumber(after.demand_gap_units)}</span>
          <span className="before-after__sub">{stationLabel(after.bottleneck_machine_id)}</span>
        </div>
      </div>
      <div className="before-after__changes" data-testid="before-after-changes">
        <span className="before-after__heading">Changes</span>
        <ul>
          {selected.actions.added_machine_ids.map((id) => (
            <li key={id}>+ {stationLabel(id)}</li>
          ))}
          {selected.actions.added_shift_count !== 0 && (
            <li>
              {selected.actions.added_shift_count > 0 ? "+" : ""}
              {selected.actions.added_shift_count} shift/day
            </li>
          )}
          {selected.actions.operator_delta !== 0 && (
            <li>
              {selected.actions.operator_delta > 0 ? "+" : ""}
              {selected.actions.operator_delta} operators
            </li>
          )}
          {selected.actions.buffer_changes.map((change) => (
            <li key={change}>{change}</li>
          ))}
          {selected.actions.action_count === 0 && <li>No changes committed</li>}
        </ul>
      </div>
    </div>
  );
}

function InformationGaps() {
  const { state } = useAppContext();
  const arena = state.arena;
  if (!arena) return null;

  // One row per (plan, gap): two plans can be blocked on the SAME kind of
  // cost, and "Plan B needs shift cost" and "Plan E needs shift cost" are
  // both facts the user has to act on. Deduplicating by gap type would hide
  // which plans are actually blocked.
  const gaps = arena.strategies.flatMap((s) =>
    s.cost.information_gaps.map((gap) => ({ label: s.label, id: s.strategy_id, gap })),
  );
  if (gaps.length === 0) return null;

  return (
    <div className="fm-section" data-testid="information-gaps">
      <p className="fm-section__title">
        Information still needed{" "}
        <span className="fm-badge fm-badge--unknown">{gaps.length}</span>
      </p>
      {/* Stating exactly what is missing is the honest alternative to
          treating an unknown cost as zero. */}
      <ul className="information-gaps">
        {gaps.map(({ label, id, gap }) => (
          <li key={`${id}-${gap.gap_type}`} data-testid={`gap-${id}-${gap.gap_type}`}>
            <span className="information-gaps__plan">{label}</span>{" "}
            {/* The gap TYPE named in words, not as its enum member, then the
                backend's own sentence with any identifier translated. */}
            <strong>{GAP_TITLE[gap.gap_type]}</strong> — {humanizeInternalTokens(gap.description)}{" "}
            <span className="information-gaps__category">({gap.expected_category.replace(/_/g, " ").toLowerCase()})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ComparisonTable() {
  const stationLabel = useStationName();
  const { state, closeStrategyComparison } = useAppContext();
  const comparison = state.strategyComparison;
  if (!comparison) return null;

  const renderValue = (value: number | boolean | string | null, unit: string | null): string => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "boolean") return value ? "YES" : "NO";
    if (typeof value === "string") return stationLabel(value);
    return unit === "EUR" ? formatCurrency(value) : formatNumber(value);
  };

  const renderDelta = (delta: number | null, unit: string | null): string => {
    // An unknown stays an em dash. It must never render as 0, which would
    if (delta === null || delta === undefined) return "—";
    if (delta === 0) return "same";
    const sign = delta > 0 ? "+" : "−";
    const magnitude = Math.abs(delta);
    return `${sign}${unit === "EUR" ? formatCurrency(magnitude) : formatNumber(magnitude)}`;
  };

  return (
    <div className="fm-section comparison-card" data-testid="strategy-comparison">
      <p className="fm-section__title">
        {comparison.label_a} vs {comparison.label_b}{" "}
        <span className="fm-badge fm-badge--verified">Verified</span>
        <button type="button" className="comparison-card__close" onClick={closeStrategyComparison} aria-label="Close comparison">
          ×
        </button>
      </p>

      <p className="comparison-card__headline" data-testid="strategy-comparison-headline">
        {comparison.headline}
      </p>

      {!comparison.comparable_on_cost && (
        <p className="comparison-card__warning" data-testid="not-comparable-on-cost">
          {comparison.notes[0]}
        </p>
      )}

      <table className="comparison-table">
        <thead>
          <tr>
            <th scope="col">Metric</th>
            <th scope="col">{comparison.label_a}</th>
            <th scope="col">{comparison.label_b}</th>
            <th scope="col">Δ</th>
          </tr>
        </thead>
        <tbody>
          {comparison.metrics.map((row) => (
            <tr key={row.metric} data-testid={`strategy-row-${row.metric}`}>
              <td>{row.label}</td>
              <td className="fm-mono">{renderValue(row.value_a, row.unit)}</td>
              <td className="fm-mono">{renderValue(row.value_b, row.unit)}</td>
              <td className="fm-mono">{renderDelta(row.delta, row.unit)}</td>
            </tr>
          ))}
          {/* Cost rows are kept in their own group and never summed across
              categories — CAPEX and OPEX are different kinds of number. */}
          {comparison.cost_rows.map((row) => (
            <tr key={row.metric} data-testid={`strategy-row-${row.metric}`} className="comparison-table__cost">
              <td>{row.label}</td>
              <td className="fm-mono">{renderValue(row.value_a, row.unit)}</td>
              <td className="fm-mono">{renderValue(row.value_b, row.unit)}</td>
              <td className="fm-mono">{renderDelta(row.delta, row.unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyArenaPanel() {
  const { state, selectStrategy, compareWithStrategy } = useAppContext();
  const arena = state.arena;

  if (!arena) return null;

  return (
    <>
      <div className="fm-section" data-testid="strategy-arena">
        <p className="fm-section__title">
          Verified options{" "}
          <span className="fm-badge fm-badge--verified">{arena.strategies.length}</span>
        </p>
        <p className="strategy-arena__summary" data-testid="strategy-arena-summary">
          {arena.summary}
        </p>

        {/* The claim behind the recommendation, stated precisely, with the
            numbers that back it one click away. */}
        <SearchSpace arena={arena} />

        <div className="strategy-list">
          {arena.strategies.map((option) => (
            <StrategyCard
              key={option.strategy_id}
              option={option}
              selected={option.strategy_id === state.selectedStrategyId}
              recommended={option.strategy_id === arena.recommended_strategy_id}
              onSelect={() => selectStrategy(option.strategy_id)}
              onCompare={arena.strategies.length > 1 ? () => void compareWithStrategy(option.strategy_id) : undefined}
              comparing={state.comparing}
            />
          ))}
        </div>

        {arena.families_without_options.length > 0 && (
          <div className="strategy-arena__empty" data-testid="families-without-options">
            {/* Reported rather than hidden: silence would read as "not considered". */}
            <span className="before-after__heading">Not available here</span>
            <ul>
              {arena.families_without_options.map((entry) => (
                <li key={entry}>{entry}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <BeforeAfter />
      <ComparisonTable />
      <InformationGaps />
      <StrategyAskBox />
    </>
  );
}
