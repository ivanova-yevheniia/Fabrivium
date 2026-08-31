import type { StrategyActionSummary } from "../api/types";
import { stationName, type NamedThing } from "./formatting";

/**
 * Phase 12 — turns a verified `StrategyActionSummary` into the short
 * human phrases the recommendation hero leads with ("+1 shift/day",
 * "+2 machines").
 *
 * This is FORMATTING ONLY, in the same spirit as utils/formatting.ts: every
 * phrase is built from a field the backend already computed, and nothing
 * here derives, sums or infers an engineering quantity. A lever the
 * strategy did not use produces no phrase at all — the hero must never
 * imply a change that the simulation did not actually run.
 */

/** The headline intervention: what a plan commits to, in one line. */
export function primaryInterventionPhrase(actions: StrategyActionSummary): string | null {
  const parts: string[] = [];

  if (actions.added_machine_count > 0) {
    parts.push(`+${actions.added_machine_count} machine${actions.added_machine_count === 1 ? "" : "s"}`);
  }
  if (actions.added_shift_count !== 0) {
    const sign = actions.added_shift_count > 0 ? "+" : "";
    parts.push(`${sign}${actions.added_shift_count} shift/day`);
  }
  if (actions.operator_delta !== 0) {
    const sign = actions.operator_delta > 0 ? "+" : "";
    parts.push(
      `${sign}${actions.operator_delta} operator${Math.abs(actions.operator_delta) === 1 ? "" : "s"}`,
    );
  }

  if (parts.length > 0) return parts.join(" · ");

  // Nothing was bought, scheduled or staffed. Say what DID change rather
  // than nothing at all — a cycle-time plan commits to something real.
  if (actions.buffer_changes.length > 0) return "buffer capacity change";
  if (actions.action_count > 0) {
    return `${actions.action_count} change${actions.action_count === 1 ? "" : "s"}`;
  }
  return null;
}

/** Every change the plan commits to, as separate phrases — used where the
 * full list belongs (Before/After, the hero's change list). Same rule: a
 * lever that was not used contributes nothing. */
export function interventionPhrases(
  actions: StrategyActionSummary,
  /** The machines that define the names, when the caller has them. */
  known?: readonly NamedThing[] | null,
): string[] {
  const phrases: string[] = [];

  for (const id of actions.added_machine_ids) phrases.push(`Add ${stationName(id, known)}`);

  if (actions.added_shift_count !== 0) {
    const sign = actions.added_shift_count > 0 ? "+" : "";
    phrases.push(`${sign}${actions.added_shift_count} shift/day`);
  }
  if (actions.operator_delta !== 0) {
    const sign = actions.operator_delta > 0 ? "+" : "";
    phrases.push(
      `${sign}${actions.operator_delta} operator${Math.abs(actions.operator_delta) === 1 ? "" : "s"}`,
    );
  }
  for (const change of actions.buffer_changes) phrases.push(change);

  // A plan that changed nothing says so explicitly rather than rendering an
  // empty list, which would read as "the data is missing".
  if (phrases.length === 0 && actions.action_count === 0) phrases.push("No changes committed");

  return phrases;
}
