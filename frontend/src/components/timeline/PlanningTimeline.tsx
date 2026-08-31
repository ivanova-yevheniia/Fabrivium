import { Fragment } from "react";
import type { ReactNode } from "react";
import type { PlanningIteration } from "../../api/types";
import { useAppContext } from "../../state/AppContext";
import { formatNumber, friendlyMachineName } from "../../utils/formatting";
import type { IterationSelection } from "../../state/types";
import { useStationName } from "../../utils/useStationName";
import { limitingStageLabel } from "../../utils/limitingStage";

function actionSummary(iteration: PlanningIteration): string {
  const actions = iteration.selected_proposal?.scenario.actions ?? [];
  if (actions.length === 0) return iteration.rejection_reason ?? "No proposal selected";
  return actions
    .map((a) => {
      const name = friendlyMachineName(a.machine_id);
      if (a.action_type === "ADD_PARALLEL_MACHINE") return `Add parallel ${name}`;
      if (a.action_type === "CHANGE_MACHINE_CYCLE_TIME") return `Change cycle time at ${name}`;
      if (a.action_type === "CHANGE_MACHINE_CAPACITY") return `Change capacity at ${name}`;
      // Phase 8A levers. Each reads as the engineering change it is, so a
      // timeline node never shows a raw enum name to a planner. Only the
      // fields the action actually carries are rendered — a shift action that
      // changes shifts alone must not invent an hours figure.
      if (a.action_type === "CHANGE_SHIFT_CONFIGURATION") {
        const parts: string[] = [];
        if (a.shifts_per_day != null) parts.push(`${a.shifts_per_day} shifts/day`);
        if (a.hours_per_shift != null) parts.push(`${formatNumber(a.hours_per_shift)} h/shift`);
        return `Change shifts to ${parts.join(", ")}`;
      }
      if (a.action_type === "CHANGE_OPERATOR_CAPACITY") {
        return `Set operators to ${a.operators_available}`;
      }
      if (a.action_type === "CHANGE_BUFFER_CAPACITY") {
        return `Set ${a.buffer_id} capacity to ${a.new_capacity}`;
      }
      return `${a.action_type} ${name}`;
    })
    .join("; ");
}

function TimelineNode({
  selected,
  onSelect,
  children,
  rejected,
  testId,
}: {
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
  rejected?: boolean;
  testId: string;
}) {
  return (
    <button
      type="button"
      className={[
        "timeline__node",
        selected ? "timeline__node--selected" : "",
        rejected ? "timeline__node--rejected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={onSelect}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

export function PlanningTimeline() {
  const { state, selectIteration } = useAppContext();
  const stationLabel = useStationName();
  const session = state.session;

  if (!session) {
    return (
      <section className="bottom-panel fm-panel" data-testid="planning-timeline">
        <p className="fm-empty">Run a plan to see the iteration timeline.</p>
      </section>
    );
  }

  const isSelected = (key: IterationSelection) => state.selectedIteration === key;

  return (
    <section className="bottom-panel fm-panel" data-testid="planning-timeline">
      <div className="timeline">
        <TimelineNode selected={isSelected("baseline")} onSelect={() => selectIteration("baseline")} testId="timeline-baseline">
          <span className="timeline__node-title">Baseline</span>
          <span className="fm-mono">{formatNumber(session.baseline_simulation.completed_units)}/day</span>
          {/* §2/§3 — the station is named as the factory names it, and the
              word follows the same rule the KPI panel uses: "Bottleneck"
              only when demand was actually missed. */}
          <span>
            {limitingStageLabel(session.baseline_simulation)}:{" "}
            {stationLabel(session.baseline_simulation.system.bottleneck_machine_id)}
          </span>
        </TimelineNode>

        {session.iterations.map((iteration) => (
          <Fragment key={iteration.iteration_index}>
            <span className="timeline__arrow" aria-hidden="true">
              →
            </span>
            <TimelineNode
              selected={isSelected(iteration.iteration_index)}
              onSelect={() => selectIteration(iteration.iteration_index)}
              rejected={!iteration.accepted}
              testId={`timeline-iteration-${iteration.iteration_index}`}
            >
              <span className="timeline__node-title">Iteration {iteration.iteration_index + 1}</span>
              <span>{actionSummary(iteration)}</span>
              {iteration.scenario_result && (
                <span className="fm-mono">
                  Gap {formatNumber(iteration.scenario_result.baseline_result.demand_gap_units)} →{" "}
                  {formatNumber(iteration.scenario_result.candidate_result.demand_gap_units)}
                </span>
              )}
              <span className={`fm-badge fm-badge--${iteration.accepted ? "verified" : "bad"}`}>
                {iteration.accepted ? "Accepted" : "Rejected"}
              </span>
            </TimelineNode>
          </Fragment>
        ))}

        <span className="timeline__arrow" aria-hidden="true">
          →
        </span>
        <TimelineNode selected={isSelected("final")} onSelect={() => selectIteration("final")} testId="timeline-final">
          <span className="timeline__node-title">Final</span>
          <span className="fm-mono">{formatNumber(session.current_simulation.completed_units)}/day</span>
          <span>{session.goal_reached ? "GOAL REACHED" : session.stop_reason ?? "IN PROGRESS"}</span>
        </TimelineNode>
      </div>
    </section>
  );
}
