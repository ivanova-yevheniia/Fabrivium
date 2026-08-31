import type { ReactNode } from "react";
import { useAppContext } from "../../state/AppContext";
import { PlaybackTrigger } from "../playback/PlaybackTrigger";
import { formatCurrency, formatNumber, formatPercent } from "../../utils/formatting";
import { limitingStageLabel } from "../../utils/limitingStage";
import { resolveStage } from "../../utils/stage";
import { useStationName } from "../../utils/useStationName";

/** Phase 12 §12 — one row of the KPI panel. */
function KpiRow({
  label,
  value,
  badge,
}: {
  label: string;
  value: string;
  badge?: "verified" | "unknown";
}) {
  return (
    <div className="kpi-item">
      <span className="kpi-item__label">{label}</span>
      <span className="kpi-item__value fm-mono">
        {value}
        {badge === "unknown" && (
          <>
            {" "}
            <span className="fm-badge fm-badge--unknown">Unknown</span>
          </>
        )}
      </span>
    </div>
  );
}

/** A KPI section heading that states, once, where everything under it came from. */
function VerifiedSection({
  title,
  extra,
  badge = "Simulated",
}: {
  title: ReactNode;
  extra?: ReactNode;
  badge?: string;
}) {
  return (
    <p className="fm-section__title kpi-section__title">
      <span>{title}</span>
      <span className="fm-badge fm-badge--verified">{badge}</span>
      {extra}
    </p>
  );
}

export function KpiPanel() {
  const stationLabel = useStationName();
  const { state } = useAppContext();
  const stage = resolveStage(state.session, state.selectedIteration);

  if (!state.session || !stage) {
    return (
      <div data-testid="kpi-panel">
        <div className="fm-section">
          <p className="fm-section__title">Verified KPIs</p>
          <p className="fm-empty">Run a plan to see verified metrics.</p>
        </div>
      </div>
    );
  }

  const sim = stage.snapshot.simulation;
  // Both budget figures come from the SELECTED STAGE's snapshot, so they
  // always describe the same point in time. Reading remaining from
  // `state.session` instead made Iteration 1 of a €220,000 session render
  // "cumulative €85,000 / remaining €15,000" — the latter being the
  // session-FINAL figure — with both labeled Verified.
  const budget = stage.snapshot;
  const hasBudget = budget.remaining_known_capex != null;

  // Phase 8A. All three read from the SELECTED STAGE, like every other row
  // here, so switching timeline stage or branch moves them in step with the
  // KPIs above rather than showing the session's final state.
  //
  // `?? null` / `?? []` rather than a default object: a run that reports no
  // workforce or buffer data must render nothing at all, never a row of
  // zeros that looks like a measurement.
  const factory = stage.snapshot.factory;
  const operatorKpi = sim.operator_kpi ?? null;
  const bufferKpis = sim.buffer_kpis ?? [];

  return (
    <div data-testid="kpi-panel">
      <div className="fm-section">
        <VerifiedSection
          title={`Verified KPIs — ${stage.label}`}
          extra={stage.isRejectedCandidate ? <span className="fm-badge fm-badge--bad">Rejected candidate</span> : undefined}
        />
        {!stage.isRejectedCandidate && <PlaybackTrigger />}

        <div className="kpi-grid">
          <KpiRow label="Target units/day" value={formatNumber(sim.target_units)} badge="verified" />
          <KpiRow label="Completed units" value={formatNumber(sim.completed_units)} badge="verified" />
          <KpiRow label="Demand gap" value={formatNumber(sim.demand_gap_units)} badge="verified" />
          <KpiRow label="Demand met" value={sim.demand_met ? "YES" : "NO"} badge="verified" />
          <KpiRow label="WIP" value={formatNumber(sim.system.work_in_progress)} badge="verified" />
          <KpiRow
            label="Avg flow time (s)"
            value={formatNumber(sim.system.average_flow_time_seconds)}
            badge="verified"
          />
          <KpiRow
            label={limitingStageLabel(sim)}
            value={
              sim.demand_met
                ? `${stationLabel(stage.snapshot.bottleneck_machine_id)} · target achieved`
                : stationLabel(stage.snapshot.bottleneck_machine_id)
            }
            badge="verified"
          />
        </div>

        {stage.isRejectedCandidate && (
          <p className="factory-workspace__notice" style={{ marginTop: 8 }}>
            This is the evaluated candidate for a REJECTED proposal — it was never adopted as the current
            state. See "Final" for the actual accepted outcome.
          </p>
        )}
      </div>

      <div className="fm-section">
        <VerifiedSection title="Budget" badge="Known costs" />
        <div className="kpi-grid">
          <KpiRow
            label={stage.isRejectedCandidate ? "Hypothetical cumulative CAPEX" : "Cumulative known CAPEX"}
            value={formatCurrency(budget.cumulative_known_capex)}
            badge="verified"
          />
          {hasBudget ? (
            <KpiRow
              label={stage.isRejectedCandidate ? "Hypothetical remaining CAPEX" : "Remaining known CAPEX"}
              value={formatCurrency(budget.remaining_known_capex as number)}
              badge="verified"
            />
          ) : (
            <KpiRow label="Remaining known CAPEX" value="No budget constraint set" badge="unknown" />
          )}
        </div>
      </div>

      {/* Phase 8A: production time, workforce, buffers */}

      <div className="fm-section" data-testid="kpi-shift">
        <VerifiedSection title="Production time" />
        <div className="kpi-grid">
          <KpiRow
            label="Shift configuration"
            value={`${factory.shifts_per_day} × ${formatNumber(factory.hours_per_shift)} h`}
            badge="verified"
          />
          <KpiRow
            label="Production hours/day"
            value={`${formatNumber(factory.shifts_per_day * factory.hours_per_shift)} h`}
            badge="verified"
          />
          {/* Rate and daily volume are shown side by side on purpose: an extra
              shift raises the second without touching the first, and seeing
              them together is what stops "we added a shift" being read as
              "the line got faster". */}
          <KpiRow label="Throughput/hour" value={formatNumber(sim.throughput_per_hour)} badge="verified" />
        </div>
      </div>

      {operatorKpi && (
        <div className="fm-section" data-testid="kpi-operators">
          <VerifiedSection
            title="Workforce"
            extra={
              operatorKpi.operator_constrained ? (
                <span className="fm-badge fm-badge--bad" data-testid="operator-constrained-badge">
                  Constrained
                </span>
              ) : undefined
            }
          />
          <div className="kpi-grid">
            <KpiRow label="Operators available" value={formatNumber(operatorKpi.operators_available)} badge="verified" />
            <KpiRow label="Peak operators in use" value={formatNumber(operatorKpi.peak_operators_in_use)} badge="verified" />
            <KpiRow label="Operator utilization" value={formatPercent(operatorKpi.utilization)} badge="verified" />
            <KpiRow
              label="Avg operator wait (s)"
              value={formatNumber(operatorKpi.average_operator_wait_seconds)}
              badge="verified"
            />
            <KpiRow
              label="Operations delayed by staff"
              value={formatNumber(operatorKpi.operations_delayed_by_operators)}
              badge="verified"
            />
          </div>
        </div>
      )}

      {bufferKpis.length > 0 && (
        <div className="fm-section" data-testid="kpi-buffers">
          <VerifiedSection title="Buffers" />
          <div className="kpi-grid">
            {bufferKpis.map((buffer) => (
              <KpiRow
                key={buffer.buffer_id}
                label={`${buffer.buffer_name} (${formatNumber(buffer.max_level)}/${formatNumber(buffer.capacity)})`}
                value={
                  buffer.blocking_observed
                    ? `full ${formatPercent(buffer.full_fraction)} · blocked ${formatNumber(buffer.upstream_blocked_seconds)}s`
                    : `avg ${formatNumber(buffer.average_level)} · no blocking`
                }
                badge="verified"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
