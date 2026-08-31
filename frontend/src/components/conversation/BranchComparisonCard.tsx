import { useAppContext } from "../../state/AppContext";
import type { BranchMetricDelta } from "../../api/types";
import { formatCurrency, formatNumber, friendlyMachineName } from "../../utils/formatting";

/** Phase 7C section 19 — side-by-side comparison of two verified options. */

function displayValue(value: BranchMetricDelta["value_a"], unit: string | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "YES" : "NO";
  if (typeof value === "string") return friendlyMachineName(value);
  if (unit === "EUR") return formatCurrency(value);
  return formatNumber(value);
}

function displayDelta(metric: BranchMetricDelta): string {
  // An unknown stays an em dash. It must never render as "0", which would
  // read as "no difference" — see branch_comparison._delta.
  if (metric.delta === null || metric.delta === undefined) return "—";
  if (metric.delta === 0) return "same";
  const sign = metric.delta > 0 ? "+" : "−";
  const magnitude = Math.abs(metric.delta);
  const rendered = metric.unit === "EUR" ? formatCurrency(magnitude) : formatNumber(magnitude);
  return `${sign}${rendered}`;
}

export function BranchComparisonCard() {
  const { state, closeComparison } = useAppContext();
  const comparison = state.branchComparison;

  if (!comparison) return null;

  return (
    <div className="fm-section comparison-card" data-testid="branch-comparison">
      <p className="fm-section__title">
        {comparison.label_a} vs {comparison.label_b}{" "}
        <span className="fm-badge fm-badge--verified">Verified</span>
        <button
          type="button"
          className="comparison-card__close"
          onClick={closeComparison}
          aria-label="Close comparison"
        >
          ×
        </button>
      </p>

      <p className="comparison-card__headline" data-testid="comparison-headline">
        {comparison.headline}
      </p>

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
          {comparison.metrics.map((metric) => (
            <tr key={metric.metric} data-testid={`comparison-row-${metric.metric}`}>
              <td>{metric.label}</td>
              <td className="fm-mono">{displayValue(metric.value_a, metric.unit)}</td>
              <td className="fm-mono">{displayValue(metric.value_b, metric.unit)}</td>
              <td className="fm-mono">{displayDelta(metric)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {(comparison.machines_only_in_a.length > 0 || comparison.machines_only_in_b.length > 0) && (
        <div className="comparison-card__block">
          <p className="comparison-card__subtitle">Machines added</p>
          <p className="comparison-card__line">
            {comparison.label_a}:{" "}
            {comparison.machines_only_in_a.map(friendlyMachineName).join(", ") || "none unique"}
          </p>
          <p className="comparison-card__line">
            {comparison.label_b}:{" "}
            {comparison.machines_only_in_b.map(friendlyMachineName).join(", ") || "none unique"}
          </p>
        </div>
      )}

      {comparison.constraint_differences.length > 0 && (
        <div className="comparison-card__block">
          <p className="comparison-card__subtitle">Constraint differences</p>
          <ul className="comparison-card__list">
            {comparison.constraint_differences.map((difference) => (
              <li key={difference}>{difference}</li>
            ))}
          </ul>
        </div>
      )}

      {comparison.unknown_information.length > 0 && (
        <div className="comparison-card__block">
          <p className="comparison-card__subtitle">Not comparable</p>
          <ul className="comparison-card__list">
            {comparison.unknown_information.map((unknown) => (
              <li key={unknown}>{unknown}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
