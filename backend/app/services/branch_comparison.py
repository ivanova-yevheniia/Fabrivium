"""Deterministic branch comparison for Fabrivium Phase 7C (section 11)."""

from __future__ import annotations

from app.models.conversation import (
    BranchComparison,
    BranchMetricDelta,
    PlanningBranch,
)

#: (metric attribute, human label, unit, lower_is_better | None)
#: ``None`` means the metric has no universally better direction, so no
#: judgement is attached to it.
_NUMERIC_METRICS: list[tuple[str, str, str | None, bool | None]] = [
    ("completed_units", "Completed units", "units/day", False),
    ("demand_gap_units", "Demand gap", "units/day", True),
    ("cumulative_known_capex", "Known CAPEX", "EUR", True),
    ("work_in_progress", "Work in progress", "units", True),
    ("average_flow_time_seconds", "Average flow time", "s", True),
]


def _delta(a: float | int | None, b: float | int | None) -> float | None:
    """B minus A, or ``None`` when either side is unknown."""
    if a is None or b is None:
        return None
    return float(b) - float(a)


def compare_branches(branch_a: PlanningBranch, branch_b: PlanningBranch) -> BranchComparison:
    """Compare two verified branches. *branch_a* is the reference; deltas
    are expressed as B minus A."""
    a, b = branch_a.metrics, branch_b.metrics

    metrics: list[BranchMetricDelta] = [
        BranchMetricDelta(
            metric="goal_reached", label="Target reached",
            value_a=a.goal_reached, value_b=b.goal_reached,
        ),
        BranchMetricDelta(
            metric="demand_met", label="Demand met",
            value_a=a.demand_met, value_b=b.demand_met,
        ),
    ]

    for attribute, label, unit, _lower_is_better in _NUMERIC_METRICS:
        value_a = getattr(a, attribute)
        value_b = getattr(b, attribute)
        metrics.append(BranchMetricDelta(
            metric=attribute, label=label,
            value_a=value_a, value_b=value_b,
            delta=_delta(value_a, value_b), unit=unit,
        ))

    metrics.append(BranchMetricDelta(
        metric="bottleneck_machine_id", label="Final bottleneck",
        value_a=a.bottleneck_machine_id, value_b=b.bottleneck_machine_id,
    ))
    metrics.append(BranchMetricDelta(
        metric="accepted_iterations", label="Accepted changes",
        value_a=a.accepted_iterations, value_b=b.accepted_iterations,
        delta=_delta(a.accepted_iterations, b.accepted_iterations),
    ))

    only_a = [m for m in a.added_machine_ids if m not in b.added_machine_ids]
    only_b = [m for m in b.added_machine_ids if m not in a.added_machine_ids]

    unknown: list[str] = []
    if a.remaining_known_capex is None or b.remaining_known_capex is None:
        unknown.append("Remaining CAPEX is not comparable: at least one option was planned with no budget ceiling.")
    else:
        metrics.append(BranchMetricDelta(
            metric="remaining_known_capex", label="Remaining CAPEX",
            value_a=a.remaining_known_capex, value_b=b.remaining_known_capex,
            delta=_delta(a.remaining_known_capex, b.remaining_known_capex), unit="EUR",
        ))
    for branch, side in ((branch_a, "A"), (branch_b, "B")):
        for warning in branch.metrics.warnings:
            unknown.append(f"{branch.label} ({side}): {warning}")

    return BranchComparison(
        branch_a_id=branch_a.branch_id,
        branch_b_id=branch_b.branch_id,
        label_a=branch_a.label,
        label_b=branch_b.label,
        metrics=metrics,
        machines_only_in_a=only_a,
        machines_only_in_b=only_b,
        constraint_differences=_constraint_differences(branch_a, branch_b),
        unknown_information=unknown,
        headline=_headline(branch_a, branch_b),
    )


def _constraint_differences(branch_a: PlanningBranch, branch_b: PlanningBranch) -> list[str]:
    """What the two options were ALLOWED to do differently."""
    req_a, req_b = branch_a.active_requirements, branch_b.active_requirements
    differences: list[str] = []

    if req_a.objective != req_b.objective:
        differences.append(f"Objective: {branch_a.label} {req_a.objective.value}, {branch_b.label} {req_b.objective.value}")
    if req_a.target_units_per_day != req_b.target_units_per_day:
        differences.append(
            f"Target: {branch_a.label} {_units(req_a.target_units_per_day)}, "
            f"{branch_b.label} {_units(req_b.target_units_per_day)}"
        )
    if req_a.max_capex != req_b.max_capex:
        differences.append(
            f"Budget: {branch_a.label} {_money(req_a.max_capex)}, {branch_b.label} {_money(req_b.max_capex)}"
        )
    if req_a.max_additional_machines != req_b.max_additional_machines:
        differences.append(
            f"Max additional machines: {branch_a.label} {req_a.max_additional_machines}, "
            f"{branch_b.label} {req_b.max_additional_machines}"
        )
    if set(req_a.forbidden_machine_ids) != set(req_b.forbidden_machine_ids):
        differences.append(
            f"Locked machines: {branch_a.label} [{', '.join(req_a.forbidden_machine_ids) or 'none'}], "
            f"{branch_b.label} [{', '.join(req_b.forbidden_machine_ids) or 'none'}]"
        )
    if req_a.preserve_existing_layout != req_b.preserve_existing_layout:
        differences.append(
            f"Preserve existing layout: {branch_a.label} {req_a.preserve_existing_layout}, "
            f"{branch_b.label} {req_b.preserve_existing_layout}"
        )
    return differences


def _headline(branch_a: PlanningBranch, branch_b: PlanningBranch) -> str:
    """One deterministic sentence stating the primary difference."""
    a, b = branch_a.metrics, branch_b.metrics
    cost_delta = b.cumulative_known_capex - a.cumulative_known_capex

    if a.goal_reached != b.goal_reached:
        reached, missed = (branch_a, branch_b) if a.goal_reached else (branch_b, branch_a)
        extra = abs(cost_delta)
        cost_phrase = f" and costs EUR {extra:,.0f} more" if (
            reached.metrics.cumulative_known_capex > missed.metrics.cumulative_known_capex
        ) else ""
        return f"{reached.label} reaches the target{cost_phrase}; {missed.label} does not."

    if not a.goal_reached and not b.goal_reached:
        if a.demand_gap_units != b.demand_gap_units:
            closer = branch_a if a.demand_gap_units < b.demand_gap_units else branch_b
            other = branch_b if closer is branch_a else branch_a
            return (
                f"Neither option reaches the target; {closer.label} gets closer "
                f"({closer.metrics.demand_gap_units:,.0f} short vs {other.metrics.demand_gap_units:,.0f})."
            )
        return "Neither option reaches the target, and both fall short by the same amount."

    if cost_delta == 0:
        return f"{branch_a.label} and {branch_b.label} both reach the target at the same known CAPEX."
    cheaper, dearer = (branch_b, branch_a) if cost_delta < 0 else (branch_a, branch_b)
    return (
        f"Both options reach the target; {cheaper.label} costs EUR {abs(cost_delta):,.0f} less "
        f"(EUR {cheaper.metrics.cumulative_known_capex:,.0f} vs EUR {dearer.metrics.cumulative_known_capex:,.0f})."
    )


def _money(value: float | None) -> str:
    return "unlimited" if value is None else f"EUR {value:,.0f}"


def _units(value: float | None) -> str:
    return "unset" if value is None else f"{value:,.0f}/day"
