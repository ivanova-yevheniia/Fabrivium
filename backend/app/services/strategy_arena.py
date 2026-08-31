"""Multi-strategy exploration for Fabrivium Phase 8B."""

from __future__ import annotations

import time

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.orchestrator import PlanningSessionState
from app.models.simulation import SimulationResult
from app.models.strategy import (
    OptimizationStrategyFamily,
    StrategyActionSummary,
    StrategyArenaResult,
    StrategyFrontiers,
    StrategyMetrics,
    StrategySearchBudget,
    StrategySearchStats,
    UserCostInput,
    VerifiedStrategyOption,
)
from app.models.scenario import SUPPORTED_ACTION_TYPES
from app.services.pareto import compute_dominance
from app.services.planning_orchestrator import PlanningOrchestrator
from app.services.simulation import run_simulation, simulation_memo
from app.services.strategy_cost import build_cost_profile

# Which ScenarioAction types each family may use.
FAMILY_ACTION_TYPES: dict[OptimizationStrategyFamily, list[str] | None] = {
    OptimizationStrategyFamily.EQUIPMENT_EXPANSION: ["ADD_PARALLEL_MACHINE", "CHANGE_MACHINE_CAPACITY"],
    OptimizationStrategyFamily.SHIFT_EXPANSION: ["CHANGE_SHIFT_CONFIGURATION"],
    OptimizationStrategyFamily.WORKFORCE_EXPANSION: ["CHANGE_OPERATOR_CAPACITY"],
    OptimizationStrategyFamily.BUFFER_FLOW: ["CHANGE_BUFFER_CAPACITY"],
    OptimizationStrategyFamily.PROCESS_IMPROVEMENT: ["CHANGE_MACHINE_CYCLE_TIME"],
    # None = unrestricted.
    OptimizationStrategyFamily.HYBRID: None,
}

# Fixed exploration order.
FAMILY_ORDER: list[OptimizationStrategyFamily] = [
    OptimizationStrategyFamily.EQUIPMENT_EXPANSION,
    OptimizationStrategyFamily.SHIFT_EXPANSION,
    OptimizationStrategyFamily.WORKFORCE_EXPANSION,
    OptimizationStrategyFamily.BUFFER_FLOW,
    OptimizationStrategyFamily.PROCESS_IMPROVEMENT,
    OptimizationStrategyFamily.HYBRID,
]

_FAMILY_TITLES: dict[OptimizationStrategyFamily, str] = {
    OptimizationStrategyFamily.EQUIPMENT_EXPANSION: "Add production equipment",
    OptimizationStrategyFamily.SHIFT_EXPANSION: "Run the line for longer",
    OptimizationStrategyFamily.WORKFORCE_EXPANSION: "Staff the line more heavily",
    OptimizationStrategyFamily.BUFFER_FLOW: "Decouple stages with more buffer",
    OptimizationStrategyFamily.PROCESS_IMPROVEMENT: "Make a process step faster",
    OptimizationStrategyFamily.HYBRID: "Combine several levers",
}

_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: Rough simulation cost of one planning iteration: the candidate generator
#: simulates the baseline once, then every candidate is evaluated. Used only
#: to decide whether ANOTHER family fits in the budget — the actual count is
#: measured, not estimated.
_ASSUMED_SIMS_PER_ITERATION = 12

# Variant marker for the machine-free hybrid run (see _plans_to_try).
NO_EQUIPMENT_VARIANT = "no-equipment"


def _plan_id(family: OptimizationStrategyFamily, variant: str | None) -> str:
    base = f"strategy-{family.value.lower()}"
    return base if variant is None else f"{base}-{variant}"


def _plan_name(family: OptimizationStrategyFamily, variant: str | None) -> str:
    return family.value if variant is None else f"{family.value} ({variant})"


def _plan_title(family: OptimizationStrategyFamily, variant: str | None) -> str:
    if variant == NO_EQUIPMENT_VARIANT:
        return "Combine several levers without new equipment"
    return _FAMILY_TITLES[family]


def _sims_run(memo) -> int:
    """Simulations actually executed so far."""
    return memo.runs if memo is not None else 0


class StrategyArena:
    """Explores several verified strategies for one planning goal."""

    def __init__(self, *, budget: StrategySearchBudget | None = None, use_cache: bool = True) -> None:
        self._budget = budget or StrategySearchBudget()
        self._use_cache = use_cache
        self._product_id: str = ""

    # Public API

    def explore(
        self,
        factory: Factory,
        product_id: str,
        requirements: PlanningRequirements,
        *,
        layout: FactoryLayout | None = None,
        user_costs: list[UserCostInput] | None = None,
    ) -> tuple[StrategyArenaResult, dict[str, PlanningSessionState]]:
        """Explore strategy families for *requirements*."""
        started = time.monotonic()
        # Always open the memo: even with reuse switched off it is what
        # COUNTS simulations, and the budget below is enforced against that
        # count. Opening it only when caching was on meant an explicit
        # max_total_simulations silently did nothing.
        with simulation_memo(enabled=self._use_cache) as memo:
            return self._explore(factory, product_id, requirements, layout, user_costs, started, memo)

    def _explore(self, factory, product_id, requirements, layout, user_costs, started, memo):
        self._product_id = product_id
        baseline_simulation = run_simulation(_with_target_demand(factory, product_id, requirements), product_id)
        baseline_metrics = build_metrics(baseline_simulation, goal_met=baseline_simulation.demand_met, stop_reason="BASELINE")

        plans, skipped_families = self._plans_to_try(requirements)

        options: list[VerifiedStrategyOption] = []
        sessions: dict[str, PlanningSessionState] = {}
        empty_families: list[str] = list(skipped_families)
        discarded = 0
        budget_exhausted = False

        for family, variant in plans:
            if _sims_run(memo) + _ASSUMED_SIMS_PER_ITERATION > self._budget.max_total_simulations:
                # half-explored strategy is an unverified strategy.
                budget_exhausted = True
                empty_families.append(f"{family.value} (simulation budget exhausted)")
                continue

            session, reason = self._run_family(factory, product_id, requirements, family, layout, variant)
            if session is None:
                empty_families.append(f"{_plan_name(family, variant)} ({reason})")
                continue

            accepted = [it for it in session.iterations if it.accepted]
            if not accepted:
                # The candidate generator is already evidence-gated (a buffer
                # candidate only appears where blocking exists, a workforce one
                # only where operators are constrained), so a family that
                # proposed nothing acceptable genuinely has no evidence behind
                # it here.
                empty_families.append(
                    f"{_plan_name(family, variant)} (no evidence supports this lever here)"
                )
                continue

            option = self._build_option(
                session, family, label=_LABELS[len(options) % len(_LABELS)],
                user_costs=user_costs, variant=variant,
            )
            if _is_duplicate(option, options):
                discarded += 1
                continue

            options.append(option)
            sessions[option.strategy_id] = session

        frontiers = compute_frontiers(options)
        options = _with_tradeoffs(options, frontiers)
        # Rebuild the session map against the re-created options (ids are stable).
        sessions = {o.strategy_id: sessions[o.strategy_id] for o in options}

        stats = StrategySearchStats(
            families_attempted=len(plans),
            strategies_retained=len(options),
            strategies_discarded=discarded,
            simulations_run=_sims_run(memo),
            budget_exhausted=budget_exhausted,
            cache_hits=memo.hits if memo is not None else 0,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )

        result = StrategyArenaResult(
            product_id=product_id,
            baseline_metrics=baseline_metrics,
            strategies=options,
            frontiers=frontiers,
            recommended_strategy_id=recommend(options, requirements),
            stats=stats,
            families_without_options=empty_families,
            summary=_summarize(options, baseline_metrics),
        )
        return result, sessions

    # Internals

    def _plans_to_try(
        self, requirements: PlanningRequirements
    ) -> tuple[list[tuple[OptimizationStrategyFamily, str | None]], list[str]]:
        """The (family, variant) runs to attempt, in fixed order."""
        families, skipped = self._families_to_try(requirements)
        plans: list[tuple[OptimizationStrategyFamily, str | None]] = [(family, None) for family in families]

        wants_machine_free_variant = (
            requirements.prefer_no_new_machines
            and not requirements.allowed_action_types  # a hard rule already covers it
            and any(family is OptimizationStrategyFamily.HYBRID for family, _ in plans)
        )
        if wants_machine_free_variant:
            plans.append((OptimizationStrategyFamily.HYBRID, NO_EQUIPMENT_VARIANT))
        return plans, skipped

    def _families_to_try(
        self, requirements: PlanningRequirements
    ) -> tuple[list[OptimizationStrategyFamily], list[str]]:
        """Fixed order, filtered by explicit user restrictions only."""
        allowed_families = set(requirements.allowed_strategy_families or [])
        hard_actions = set(requirements.allowed_action_types or [])

        families: list[OptimizationStrategyFamily] = []
        skipped: list[str] = []
        for family in FAMILY_ORDER:
            if family is OptimizationStrategyFamily.HYBRID and not self._budget.include_hybrid:
                skipped.append(f"{family.value} (hybrid exploration is switched off)")
                continue
            if allowed_families and family.value not in allowed_families:
                skipped.append(f"{family.value} (not in the requested strategy families)")
                continue
            if hard_actions:
                family_actions = FAMILY_ACTION_TYPES[family]
                # HYBRID (None) is always compatible with a hard restriction:
                # it simply inherits it.
                if family_actions is not None and not (set(family_actions) & hard_actions):
                    skipped.append(f"{family.value} (every lever in this family was excluded by the request)")
                    continue
            if len(families) >= self._budget.max_strategy_families:
                skipped.append(f"{family.value} (family limit of {self._budget.max_strategy_families} reached)")
                continue
            families.append(family)
        return families, skipped

    def _run_family(
        self,
        factory: Factory,
        product_id: str,
        requirements: PlanningRequirements,
        family: OptimizationStrategyFamily,
        layout: FactoryLayout | None,
        variant: str | None = None,
    ) -> tuple[PlanningSessionState | None, str]:
        """Run ONE ordinary planning session restricted to *family*'s levers."""
        family_actions = FAMILY_ACTION_TYPES[family]
        user_actions = requirements.allowed_action_types

        if variant == NO_EQUIPMENT_VARIANT:
            # The machine-free hybrid: everything except buying equipment.
            base = sorted(SUPPORTED_ACTION_TYPES - {"ADD_PARALLEL_MACHINE"})
            allowed = base if user_actions is None else sorted(set(base) & set(user_actions))
            if not allowed:
                return None, "every lever in this family was excluded by the request"
        elif family_actions is None:
            allowed = user_actions  # HYBRID inherits whatever the user allowed
        elif user_actions is None:
            allowed = list(family_actions)
        else:
            allowed = sorted(set(family_actions) & set(user_actions))
            if not allowed:
                return None, "every lever in this family was excluded by the request"

        family_requirements = requirements.model_copy(update={"allowed_action_types": allowed})

        try:
            session = PlanningOrchestrator().run(
                factory, product_id, family_requirements,
                layout=layout,
                # Exactly the action budget, not one more: the orchestrator
                # counts ALL iterations, so N iterations can accept at most N
                # interventions. The "+1" this replaced was intended to leave
                # room for a final stopping pass, but it silently let a
                # strategy commit one action beyond its stated ceiling.
                max_iterations=self._budget.max_actions_per_strategy,
                session_id=_plan_id(family, variant),
            )
        except ValueError as exc:
            # A genuine engineering error for this family (e.g.
            return None, f"this lever is not applicable here ({exc})"
        return session, ""

    def _build_option(
        self,
        session: PlanningSessionState,
        family: OptimizationStrategyFamily,
        *,
        label: str,
        user_costs: list[UserCostInput] | None,
        variant: str | None = None,
    ) -> VerifiedStrategyOption:
        metrics = build_metrics(
            session.final_snapshot.simulation,
            goal_met=session.goal_reached,
            stop_reason=session.stop_reason.value if session.stop_reason else "NONE",
        )
        # A plan that CLAIMS the target gets its claim checked: one extra
        # simulation at a demand the line cannot satisfy, measuring the line
        # instead of the pacing. Only claimants are measured, so the cost is
        # bounded by how many options actually reach the target — usually one
        # or two, not the whole set.
        if metrics.goal_met:
            from app.services.capacity import CapacityNotMeasurable, measure_capacity

            try:
                measured = measure_capacity(
                    session.final_snapshot.factory,
                    self._product_id,
                    target_units_per_day=float(metrics.target_units),
                )
            except (CapacityNotMeasurable, ValueError):
                # Unmeasurable is not the same as "meets target".
                pass
            else:
                metrics = metrics.model_copy(
                    update={
                        "capacity_units_per_day": measured.capacity_units_per_day,
                        "capacity_headroom_percent": measured.headroom_percent,
                        "sustains_target_at_capacity": measured.meets_target_at_capacity,
                    }
                )

        actions = summarize_actions(session)
        cost = build_cost_profile(session, user_costs=user_costs)

        return VerifiedStrategyOption(
            strategy_id=_plan_id(family, variant),
            family=family,
            label=f"Plan {label}",
            title=_plan_title(family, variant),
            requirements=session.original_requirements,
            metrics=metrics,
            actions=actions,
            cost=cost,
            operationally_verified=True,
            commercially_complete=cost.commercially_complete,
            rationale=_rationale(family, metrics, actions, cost, variant),
            warnings=list(_warnings(metrics, cost)),
        )


# Deterministic derivations


def _with_target_demand(factory: Factory, product_id: str, requirements: PlanningRequirements) -> Factory:
    """
    Apply the requested target so the baseline is measured against the SAME demand every
    strategy is judged on.
    """
    from app.services.requirements_parser import apply_target_demand

    return apply_target_demand(factory, product_id, requirements)


def build_metrics(simulation: SimulationResult, *, goal_met: bool, stop_reason: str) -> StrategyMetrics:
    """Flatten a verified simulation into comparable KPIs."""
    operator_kpi = simulation.operator_kpi
    buffers = simulation.buffer_kpis or []

    return StrategyMetrics(
        goal_met=goal_met,
        stop_reason=stop_reason,
        completed_units=simulation.completed_units,
        target_units=simulation.target_units,
        demand_gap_units=simulation.demand_gap_units,
        throughput_per_hour=simulation.throughput_per_hour,
        work_in_progress=simulation.system.work_in_progress,
        average_flow_time_seconds=simulation.system.average_flow_time_seconds,
        bottleneck_machine_id=simulation.system.bottleneck_machine_id,
        operator_utilization=operator_kpi.utilization if operator_kpi else None,
        operator_constrained=bool(operator_kpi and operator_kpi.operator_constrained),
        max_buffer_full_fraction=max((b.full_fraction for b in buffers), default=0.0),
        total_upstream_blocked_seconds=sum(b.upstream_blocked_seconds for b in buffers),
    )


def summarize_actions(session: PlanningSessionState) -> StrategyActionSummary:
    """Count what the strategy actually does, from ACCEPTED iterations only."""
    added_machines: list[str] = []
    buffer_changes: list[str] = []
    action_types: set[str] = set()
    action_count = 0

    baseline = session.baseline_factory
    final = session.current_factory

    for iteration in session.iterations:
        if not iteration.accepted or iteration.selected_proposal is None:
            continue
        for action in iteration.selected_proposal.scenario.actions:
            action_count += 1
            action_types.add(action.action_type)
            if action.action_type == "ADD_PARALLEL_MACHINE":
                machine_id = getattr(action, "machine_id", None)
                if machine_id is not None:
                    added_machines.append(machine_id)
            elif action.action_type == "CHANGE_BUFFER_CAPACITY":
                buffer = next((b for b in baseline.buffers if b.id == action.buffer_id), None)
                before = buffer.capacity if buffer is not None else None
                # The buffer's NAME, not its key: this string is rendered on
                # the plan card, and "b-1: 50 -> 100" is a database row shown
                # to a manufacturing engineer.
                label = buffer.name if buffer is not None else action.buffer_id
                buffer_changes.append(f"{label}: {before} -> {action.new_capacity}")

    return StrategyActionSummary(
        action_count=action_count,
        added_machine_ids=added_machines,
        # Counted from the FACTORY, not from the action list: this is the
        # number of machines that actually exist now.
        added_machine_count=len(final.machines) - len(baseline.machines),
        added_shift_count=final.shifts_per_day - baseline.shifts_per_day,
        hours_per_shift_delta=round(final.hours_per_shift - baseline.hours_per_shift, 6),
        operator_delta=final.operators_available - baseline.operators_available,
        buffer_changes=buffer_changes,
        action_types=sorted(action_types),
    )


def _rationale(family, metrics: StrategyMetrics, actions: StrategyActionSummary, cost, variant=None) -> str:
    """Deterministic template over verified values. Never model prose."""
    outcome = (
        f"reaches {metrics.completed_units:,}/day"
        if metrics.goal_met
        else f"reaches {metrics.completed_units:,}/{metrics.target_units:,}/day ({metrics.demand_gap_units:,.0f} short)"
    )
    changes: list[str] = []
    if actions.added_machine_count:
        changes.append(f"{actions.added_machine_count} new machine(s)")
    if actions.added_shift_count:
        changes.append(f"{actions.added_shift_count:+d} shift(s)/day")
    if actions.operator_delta:
        changes.append(f"{actions.operator_delta:+d} operator(s)")
    if actions.buffer_changes:
        changes.append(f"{len(actions.buffer_changes)} buffer change(s)")
    if not changes and actions.action_count:
        # Some levers change no COUNT — a cycle-time improvement adds no
        # machine, shift, operator or buffer. Reporting "no committed
        # changes" for a plan that committed three of them would be plainly
        # wrong, so fall back to naming what it did.
        readable = ", ".join(t.replace("CHANGE_", "").replace("_", " ").lower() for t in actions.action_types)
        changes.append(f"{actions.action_count} change(s) to {readable}")
    change_text = ", ".join(changes) if changes else "no committed changes"

    money = (
        f"EUR {cost.known_capex:,.0f} known CAPEX"
        if cost.commercially_complete
        else f"EUR {cost.known_capex:,.0f} known CAPEX plus {len(cost.information_gaps)} unpriced item(s)"
    )
    return f"{_plan_title(family, variant)}: {outcome} with {change_text}, for {money}."


def _warnings(metrics: StrategyMetrics, cost) -> list[str]:
    warnings: list[str] = []
    if not metrics.goal_met:
        warnings.append(f"Does not reach the target: {metrics.demand_gap_units:,.0f} units/day short.")
    if not cost.commercially_complete:
        warnings.append("Cannot be ranked on cost until the missing cost inputs are supplied.")
    if metrics.operator_constrained:
        warnings.append("The workforce is still the binding constraint in the final state.")
    return warnings


def _is_duplicate(option: VerifiedStrategyOption, existing: list[VerifiedStrategyOption]) -> bool:
    """
    Two strategies are the same option if they commit the same changes and reach the
    same verified outcome — regardless of which family proposed them.
    """
    signature = _signature(option)
    return any(_signature(other) == signature for other in existing)


def _signature(option: VerifiedStrategyOption) -> tuple:
    actions = option.actions
    return (
        tuple(sorted(actions.added_machine_ids)),
        actions.added_shift_count,
        actions.hours_per_shift_delta,
        actions.operator_delta,
        tuple(sorted(actions.buffer_changes)),
        option.metrics.completed_units,
    )


# Pareto (section 8) — two frontiers, deliberately not one

# Engineering dimensions only. Every strategy is comparable on these, priced or not.
_OPERATIONAL_DIMENSIONS: list[tuple[str, str]] = [
    ("demand_gap_units", "min"),
    ("work_in_progress", "min"),
    ("average_flow_time_seconds", "min"),
    ("action_count", "min"),
]

# Adds money.
_COMMERCIAL_DIMENSIONS: list[tuple[str, str]] = _OPERATIONAL_DIMENSIONS + [("known_capex", "min")]


def _dimension_values(option: VerifiedStrategyOption) -> dict[str, float]:
    return {
        "demand_gap_units": float(option.metrics.demand_gap_units),
        "work_in_progress": float(option.metrics.work_in_progress),
        "average_flow_time_seconds": float(option.metrics.average_flow_time_seconds),
        "action_count": float(option.actions.action_count),
        "known_capex": float(option.cost.known_capex),
    }


def compute_frontiers(options: list[VerifiedStrategyOption]) -> StrategyFrontiers:
    """Compute the operational and commercially-complete frontiers."""
    if not options:
        return StrategyFrontiers(
            commercial_dimensions=[d for d, _ in _COMMERCIAL_DIMENSIONS],
            operational_dimensions=[d for d, _ in _OPERATIONAL_DIMENSIONS],
        )

    operational_items = [(o.strategy_id, _dimension_values(o)) for o in options]
    operational_frontier, dominated_by, _ = compute_dominance(operational_items, _OPERATIONAL_DIMENSIONS)

    complete = [o for o in options if o.commercially_complete]
    if complete:
        commercial_items = [(o.strategy_id, _dimension_values(o)) for o in complete]
        commercial_frontier, _, _ = compute_dominance(commercial_items, _COMMERCIAL_DIMENSIONS)
    else:
        commercial_frontier = set()

    return StrategyFrontiers(
        commercially_complete_frontier=sorted(commercial_frontier),
        operational_frontier=sorted(operational_frontier),
        dominated_by={k: v for k, v in sorted(dominated_by.items())},
        commercial_dimensions=[d for d, _ in _COMMERCIAL_DIMENSIONS],
        operational_dimensions=[d for d, _ in _OPERATIONAL_DIMENSIONS],
    )


def _with_tradeoffs(
    options: list[VerifiedStrategyOption], frontiers: StrategyFrontiers
) -> list[VerifiedStrategyOption]:
    """Attach deterministic, comparative trade-off statements."""
    if not options:
        return options

    goal_met_ids = {o.strategy_id for o in options if o.metrics.goal_met}
    fewest_actions = min(o.actions.action_count for o in options)
    lowest_known_capex = min(o.cost.known_capex for o in options)
    no_machine_ids = {o.strategy_id for o in options if o.actions.added_machine_count == 0}

    # "LOWEST" HAS TO BE LOWER THAN SOMETHING.
    capex_distinguishes = len({o.cost.known_capex for o in options}) > 1

    rebuilt: list[VerifiedStrategyOption] = []
    for option in options:
        tradeoffs: list[str] = []

        if option.metrics.goal_met and len(goal_met_ids) == 1:
            tradeoffs.append("The only explored option that reaches the target.")
        elif not option.metrics.goal_met and goal_met_ids:
            tradeoffs.append(f"Falls {option.metrics.demand_gap_units:,.0f} units/day short; other options reach the target.")

        if option.actions.action_count == fewest_actions and len(options) > 1:
            tradeoffs.append(f"Fewest changes of any option ({fewest_actions}).")

        if option.cost.known_capex == lowest_known_capex and capex_distinguishes:
            if option.commercially_complete:
                tradeoffs.append(f"Lowest known CAPEX (EUR {lowest_known_capex:,.0f}) and fully priced.")
            else:
                # The wording matters: NOT "cheapest".
                tradeoffs.append(
                    f"Lowest known CAPEX (EUR {lowest_known_capex:,.0f}), but its commercial cost is incomplete."
                )

        if option.strategy_id in no_machine_ids and option.actions.action_count:
            tradeoffs.append("Requires no new equipment.")

        if option.strategy_id in frontiers.operational_frontier:
            tradeoffs.append("On the operational Pareto frontier — no explored option is better on every engineering measure.")
        else:
            dominators = frontiers.dominated_by.get(option.strategy_id, [])
            if dominators:
                # "Dominated" is a precise word about the OPERATIONAL dimensions only,
                # and it was being read as a verdict on the plan as a whole.
                names = ", ".join(dominators)
                tradeoffs.append(f"Requires more operational changes than {names}.")
                if not option.commercially_complete:
                    tradeoffs.append("Financial ranking pending the missing cost inputs.")

        rebuilt.append(option.model_copy(update={"tradeoffs": tradeoffs}))
    return rebuilt


# Recommendation


def recommend(options: list[VerifiedStrategyOption], requirements: PlanningRequirements) -> str | None:
    """Which option a careful engineer would look at FIRST."""
    if not options:
        return None

    def sort_key(option: VerifiedStrategyOption) -> tuple:
        preference_penalty = 0
        if requirements.prefer_no_new_machines and option.actions.added_machine_count > 0:
            preference_penalty += 1
        if requirements.prefer_few_changes:
            preference_penalty += min(option.actions.action_count, 9)
        if requirements.prefer_low_known_capex and option.cost.known_capex > 0:
            preference_penalty += 1

        return (
            0 if option.metrics.goal_met else 1,
            preference_penalty,
            0 if option.commercially_complete else 1,
            option.actions.action_count,
            option.cost.known_capex,
            option.strategy_id,
        )

    return sorted(options, key=sort_key)[0].strategy_id


def _summarize(options: list[VerifiedStrategyOption], baseline: StrategyMetrics) -> str:
    if not options:
        return (
            f"No verified strategy was found. Baseline produces {baseline.completed_units:,}/day "
            f"against a target of {baseline.target_units:,}."
        )
    reaching = [o for o in options if o.metrics.goal_met]
    complete = [o for o in reaching if o.commercially_complete]
    return (
        f"{len(options)} verified option(s); {len(reaching)} reach the target, "
        f"{len(complete)} of those are fully priced. Baseline: {baseline.completed_units:,}/day "
        f"against {baseline.target_units:,}."
    )
