import { useAppContext } from "../../state/AppContext";
import { formatCurrency, formatNumber, friendlyMachineName } from "../../utils/formatting";

/**
 * Phase 7C section 17 — the constraints Fabrivium currently believes,
 * always visible as compact chips.
 *
 * This is a safety feature, not decoration. In a conversation the active
 * constraint set is built up across several turns, and the user needs to be
 * able to see it without re-reading the transcript: "did it keep my 1900
 * target when I changed the budget?" must be answerable at a glance.
 * Hiding critical planning state inside chat prose is exactly how a
 * conversational tool starts quietly disagreeing with its user.
 *
 * Rendered from the TYPED active_requirements, never from a model's
 * summary of them.
 */
/** Short, readable name for one action type. */
const LEVER_LABELS: Record<string, string> = {
  ADD_PARALLEL_MACHINE: "new machines",
  CHANGE_MACHINE_CAPACITY: "machine capacity",
  CHANGE_MACHINE_CYCLE_TIME: "cycle time",
  CHANGE_SHIFT_CONFIGURATION: "shifts",
  CHANGE_OPERATOR_CAPACITY: "operators",
  CHANGE_BUFFER_CAPACITY: "buffers",
  CHANGE_DEMAND: "demand",
  REMOVE_MACHINE: "machine removal",
};

function leverLabel(actionType: string): string {
  return LEVER_LABELS[actionType] ?? actionType;
}

export function ActiveConstraints() {
  const { state } = useAppContext();
  const requirements = state.conversation?.active_requirements ?? null;

  if (!requirements) return null;

  const chips: { key: string; text: string; tone: "objective" | "limit" | "lock" }[] = [
    { key: "objective", text: requirements.objective.replace(/_/g, " "), tone: "objective" },
  ];

  if (requirements.target_units_per_day != null) {
    chips.push({
      key: "target",
      text: `Target ${formatNumber(requirements.target_units_per_day)}/day`,
      tone: "limit",
    });
  }
  if (requirements.max_capex != null) {
    chips.push({ key: "capex", text: `CAPEX ≤ ${formatCurrency(requirements.max_capex)}`, tone: "limit" });
  }
  if (requirements.max_additional_machines != null) {
    chips.push({
      key: "machines",
      text: `≤ ${requirements.max_additional_machines} new machine${requirements.max_additional_machines === 1 ? "" : "s"}`,
      tone: "limit",
    });
  }
  if (requirements.max_additional_operators != null) {
    chips.push({
      key: "operators",
      text: `≤ ${requirements.max_additional_operators} new operator${requirements.max_additional_operators === 1 ? "" : "s"}`,
      tone: "limit",
    });
  }
  for (const machineId of requirements.forbidden_machine_ids) {
    chips.push({ key: `lock-${machineId}`, text: `${friendlyMachineName(machineId)} locked`, tone: "lock" });
  }
  if (requirements.preserve_existing_layout) {
    chips.push({ key: "layout", text: "Preserve layout", tone: "lock" });
  }
  // Phase 8A. A lever restriction is one of the most consequential things
  // Fabrivium can currently believe — "shifts only" changes what every
  // subsequent plan is even allowed to consider — so it must be visible
  // rather than buried in the transcript (section 17).
  if (requirements.allowed_action_types != null) {
    chips.push({
      key: "levers",
      text: `Only: ${requirements.allowed_action_types.map(leverLabel).join(", ")}`,
      tone: "lock",
    });
  }

  return (
    <div className="fm-section" data-testid="active-constraints">
      <p className="fm-section__title">Active constraints</p>
      <div className="constraint-chips">
        {chips.map((chip) => (
          <span key={chip.key} className={`constraint-chip constraint-chip--${chip.tone}`}>
            {chip.text}
          </span>
        ))}
      </div>
    </div>
  );
}
