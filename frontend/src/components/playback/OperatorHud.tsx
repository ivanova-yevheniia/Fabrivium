import { useMemo } from "react";
import { TraceIndex } from "../../utils/traceIndex";
import { useStationName } from "../../utils/useStationName";

/** Phase 8C section 14 — operator capacity as a resource HUD, not animated human figures. */
export function OperatorHud({ traceIndex, simTime }: { traceIndex: TraceIndex; simTime: number }) {
  const stationLabel = useStationName();
  const state = useMemo(() => traceIndex.stateAt(simTime), [traceIndex, simTime]);
  if (!state.operators && !state.system) return null;

  return (
    <div className="operator-hud" data-testid="operator-hud">
      {state.operators && (
        <div className="operator-hud__row">
          <span className="operator-hud__label">Operators</span>
          <span className="fm-mono">
            {state.operators.operators_in_use}/{state.operators.operators_available} in use
          </span>
          {state.operators.waiting_operations > 0 && (
            <span className="fm-badge fm-badge--bad" data-testid="operator-hud-constrained">
              CONSTRAINED · {state.operators.waiting_operations} waiting
            </span>
          )}
        </div>
      )}
      {state.system && (
        <div className="operator-hud__row">
          <span className="operator-hud__label">Completed</span>
          <span className="fm-mono">{state.system.completed_units}</span>
          {state.system.current_bottleneck_machine_id && (
            <span className="fm-badge fm-badge--unknown" data-testid="operator-hud-bottleneck">
              {/* Audit §3. */}
              Busiest stage: {stationLabel(state.system.current_bottleneck_machine_id)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
