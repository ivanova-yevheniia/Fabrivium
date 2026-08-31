import type { FactoryLayout, PlanningIteration, PlanningSessionState, PlanningStateSnapshot } from "../api/types";
import type { AppState, IterationSelection } from "../state/types";
import { stageLayoutKey } from "../state/types";

/** Everything the workspace/KPI panel need to render one selected stage of a planning session. */
export interface StageInfo {
  key: IterationSelection;
  label: string;
  snapshot: PlanningStateSnapshot;
  /** True when this stage is showing a REJECTED candidate's evaluated
   * state rather than the accepted current state (Phase 6A.1 section 3) —
   * must always be labeled explicitly wherever it's true. */
  isRejectedCandidate: boolean;
  accepted: boolean | null;
  actionMachineIds: string[];
  iteration: PlanningIteration | null;
}

function actionMachineIds(iteration: PlanningIteration): string[] {
  const actions = iteration.selected_proposal?.scenario.actions ?? [];
  const ids = new Set<string>();
  for (const action of actions) {
    if (action.machine_id) ids.add(action.machine_id);
  }
  return Array.from(ids);
}

export function resolveStage(session: PlanningSessionState | null, selection: IterationSelection): StageInfo | null {
  if (!session) return null;

  if (selection === "baseline") {
    return {
      key: "baseline",
      label: "Baseline",
      snapshot: session.baseline_snapshot,
      isRejectedCandidate: false,
      accepted: null,
      actionMachineIds: [],
      iteration: null,
    };
  }

  if (selection === "final") {
    return {
      key: "final",
      label: "Final",
      snapshot: session.final_snapshot,
      isRejectedCandidate: false,
      accepted: null,
      actionMachineIds: [],
      iteration: null,
    };
  }

  const iteration = session.iterations.find((it) => it.iteration_index === selection);
  if (!iteration) return null;

  // Accepted -> its exact resulting state. Rejected but evaluated -> the
  // rejected candidate's exact evaluated state, explicitly labeled. Never
  // evaluated at all (e.g. NO_VALID_PROPOSAL) -> the exact state entering
  // this iteration (nothing changed) — still a real snapshot, never a guess.
  const snapshot = iteration.accepted
    ? iteration.state_after
    : (iteration.rejected_candidate_snapshot ?? iteration.state_before);

  if (!snapshot) return null;

  return {
    key: selection,
    label: `Iteration ${iteration.iteration_index + 1}`,
    snapshot,
    isRejectedCandidate: !iteration.accepted && iteration.rejected_candidate_snapshot === snapshot,
    accepted: iteration.accepted,
    actionMachineIds: actionMachineIds(iteration),
    iteration,
  };
}

/** Phase 12.1 — the ONE place that answers "which layout is on screen for this stage". */
export function effectiveStageLayout(
  state: Pick<AppState, "session" | "layout" | "appliedLayouts">,
  selection: IterationSelection,
): FactoryLayout | null {
  const applied = state.appliedLayouts[stageLayoutKey(selection)];
  if (applied) return applied;
  if (state.session) {
    return resolveStage(state.session, selection)?.snapshot.layout ?? null;
  }
  return state.layout;
}
