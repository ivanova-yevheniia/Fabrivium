import { useAppContext } from "../../state/AppContext";
import { formatCurrency, formatNumber } from "../../utils/formatting";

/**
 * Phase 11 §4 — "What was requested?" is the first question a judge has to
 * be able to answer, and until now the app never showed what it actually
 * understood. `parse_result` was already in state and already typed; it was
 * simply never rendered.
 *
 * This matters for truthfulness, not just orientation. The audit found that
 * "That's too expensive. Keep it below EUR 150k." — one of the app's OWN
 * suggested refinements — parsed to `max_capex: null`, so the ceiling was
 * dropped and the same options came back as though no budget had been
 * given, with nothing on screen to say so. The parser is fixed, but the
 * general failure mode is not: any phrasing the deterministic fallback
 * cannot read will silently vanish. Showing the constraints that WERE
 * understood turns that silent drop into a visible absence.
 *
 * Every chip is read straight from `parsed_requirements`. Nothing is
 * inferred, and a constraint that was not parsed is simply not shown —
 * this never claims a constraint the engine is not actually enforcing.
 *
 * Hard constraints and soft preferences are rendered as visibly different
 * chips, because the distinction is real in the engine: "avoid buying new
 * machines if possible" orders the options, "do not buy any new machines"
 * removes the lever entirely.
 */
export function InterpretedRequirement({
  /**
   * Phase 12 — Executive View now states the production target as the
   * headline figure of the goal block, so repeating it here as a chip
   * would say the same number twice on one screen. The chip is suppressed
   * ONLY when the caller is already displaying the target itself; every
   * other constraint is rendered exactly as before, and nothing about
   * which constraints were understood changes.
   */
  omitTarget = false,
}: { omitTarget?: boolean } = {}) {
  const { state } = useAppContext();
  const parse = state.parseResult;
  if (!parse) return null;

  const req = parse.parsed_requirements;
  const hard: string[] = [];
  const soft: string[] = [];

  if (req.target_units_per_day !== null && !omitTarget) {
    hard.push(`reach ${formatNumber(req.target_units_per_day)} units/day`);
  }
  if (req.max_capex !== null) {
    hard.push(`spend at most ${formatCurrency(req.max_capex)}`);
  }
  if (req.max_additional_machines !== null) {
    hard.push(
      `at most ${formatNumber(req.max_additional_machines)} new machine${req.max_additional_machines === 1 ? "" : "s"}`,
    );
  }
  if (req.max_additional_operators !== null) {
    hard.push(
      `at most ${formatNumber(req.max_additional_operators)} new operator${req.max_additional_operators === 1 ? "" : "s"}`,
    );
  }
  // A restricted lever list is a HARD ban on everything absent from it —
  // the "do not buy any new machines" case.
  if (req.allowed_action_types !== null && !req.allowed_action_types.some((a) => a.startsWith("ADD_"))) {
    hard.push("no new machines");
  }
  if (req.preserve_existing_layout) hard.push("keep the existing layout");
  for (const machineId of req.forbidden_machine_ids) hard.push(`do not change ${machineId}`);

  if (req.prefer_no_new_machines) soft.push("avoid new machines");
  if (req.prefer_low_known_capex) soft.push("prefer lower cost");
  if (req.prefer_few_changes) soft.push("prefer fewer changes");

  if (hard.length === 0 && soft.length === 0) return null;

  return (
    <div className="interpreted-req" data-testid="interpreted-requirement">
      <span className="interpreted-req__label">Understood as</span>
      {hard.map((text) => (
        <span key={`h-${text}`} className="interpreted-req__chip interpreted-req__chip--hard">
          {text}
        </span>
      ))}
      {soft.map((text) => (
        <span
          key={`s-${text}`}
          className="interpreted-req__chip interpreted-req__chip--soft"
          title="A preference: it orders the options, but never blocks the plan that reaches the target."
        >
          {text}
          <span className="interpreted-req__soft-tag">preference</span>
        </span>
      ))}
    </div>
  );
}
