import type { StrategyActionSummary } from "../api/types";

/** Can a saved strategy be replayed from what the project keeps? */

/** Levers whose effect the summary determines exactly. */
const REPLAYABLE_ACTION_TYPES = new Set([
  "ADD_PARALLEL_MACHINE",
  "CHANGE_SHIFT_CONFIGURATION",
  "CHANGE_OPERATOR_CAPACITY",
]);

export interface ReplaySupport {
  replayable: boolean;
  /** Why not, in the words an engineer needs. Null when replayable. */
  reason: string | null;
}

const OK: ReplaySupport = { replayable: true, reason: null };

/** `null` actions mean the baseline, which needs no reconstruction at all:
 * the concept factory IS the factory the baseline was verified on. */
export function replaySupport(actions: StrategyActionSummary | null | undefined): ReplaySupport {
  if (!actions) return OK;

  for (const actionType of actions.action_types) {
    if (!REPLAYABLE_ACTION_TYPES.has(actionType)) {
      return {
        replayable: false,
        reason: `This plan cannot be replayed from the saved project: it uses ${actionType}, which the saved summary does not record in full.`,
      };
    }
  }

  // A machine exists that no recorded clone accounts for — rebuilding would
  // produce a different, smaller factory than the one verified.
  if (actions.added_machine_count !== actions.added_machine_ids.length) {
    return {
      replayable: false,
      reason:
        "This plan cannot be replayed from the saved project: it added " +
        `${actions.added_machine_count} machine(s) and the saved summary identifies ` +
        `${actions.added_machine_ids.length} of them.`,
    };
  }

  if (actions.buffer_changes.length > 0) {
    return {
      replayable: false,
      reason:
        "This plan cannot be replayed from the saved project: it resizes a buffer, " +
        "and the saved summary records that only as a line of text rather than a number.",
    };
  }

  return OK;
}
