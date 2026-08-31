"""Deterministic strategy comparison for Fabrivium Phase 8B (section 16)."""

from __future__ import annotations

from app.models.strategy import (
    CostCategory,
    StrategyComparison,
    StrategyMetricDelta,
    VerifiedStrategyOption,
)
from app.services.strategy_language import category_title

# (attribute path, label, unit, comparable-as-number)
_METRIC_ROWS: list[tuple[str, str, str | None]] = [
    ("completed_units", "Completed units", "units/day"),
    ("demand_gap_units", "Demand gap", "units/day"),
    ("throughput_per_hour", "Throughput", "units/h"),
    ("work_in_progress", "Work in progress", "units"),
    ("average_flow_time_seconds", "Average flow time", "s"),
]

_ACTION_ROWS: list[tuple[str, str, str | None]] = [
    ("action_count", "Changes required", None),
    ("added_machine_count", "Machines added", None),
    ("added_shift_count", "Shifts/day change", None),
    ("operator_delta", "Operator change", None),
]


def _delta(a: float | int | None, b: float | int | None) -> float | None:
    """B minus A, or ``None`` when either side is unknown."""
    if a is None or b is None:
        return None
    return float(b) - float(a)


def compare_strategies(a: VerifiedStrategyOption, b: VerifiedStrategyOption) -> StrategyComparison:
    """Compare two verified strategies. *a* is the reference; deltas are
    B minus A."""
    metrics: list[StrategyMetricDelta] = [
        StrategyMetricDelta(
            metric="goal_met", label="Target reached",
            value_a=a.metrics.goal_met, value_b=b.metrics.goal_met,
        ),
    ]

    for attribute, label, unit in _METRIC_ROWS:
        value_a = getattr(a.metrics, attribute)
        value_b = getattr(b.metrics, attribute)
        metrics.append(StrategyMetricDelta(
            metric=attribute, label=label, value_a=value_a, value_b=value_b,
            delta=_delta(value_a, value_b), unit=unit,
        ))

    metrics.append(StrategyMetricDelta(
        metric="bottleneck_machine_id", label="Final bottleneck",
        value_a=a.metrics.bottleneck_machine_id, value_b=b.metrics.bottleneck_machine_id,
    ))

    for attribute, label, unit in _ACTION_ROWS:
        value_a = getattr(a.actions, attribute)
        value_b = getattr(b.actions, attribute)
        metrics.append(StrategyMetricDelta(
            metric=attribute, label=label, value_a=value_a, value_b=value_b,
            delta=_delta(value_a, value_b), unit=unit,
        ))

    metrics.append(StrategyMetricDelta(
        metric="operationally_verified", label="Operationally verified",
        value_a=a.operationally_verified, value_b=b.operationally_verified,
    ))
    metrics.append(StrategyMetricDelta(
        metric="commercially_complete", label="Commercially complete",
        value_a=a.commercially_complete, value_b=b.commercially_complete,
    ))

    comparable_on_cost = a.commercially_complete and b.commercially_complete

    notes: list[str] = []
    if not comparable_on_cost:
        incomplete = [o.label for o in (a, b) if not o.commercially_complete]
        notes.append(
            f"Not comparable on cost: {' and '.join(incomplete)} still "
            f"{'have' if len(incomplete) > 1 else 'has'} unpriced components. "
            f"Lower known CAPEX does not mean cheaper."
        )

    return StrategyComparison(
        strategy_a_id=a.strategy_id,
        strategy_b_id=b.strategy_id,
        label_a=a.label,
        label_b=b.label,
        family_a=a.family,
        family_b=b.family,
        metrics=metrics,
        cost_rows=_cost_rows(a, b),
        machines_only_in_a=[m for m in a.actions.added_machine_ids if m not in b.actions.added_machine_ids],
        machines_only_in_b=[m for m in b.actions.added_machine_ids if m not in a.actions.added_machine_ids],
        information_gaps_a=list(a.cost.information_gaps),
        information_gaps_b=list(b.cost.information_gaps),
        comparable_on_cost=comparable_on_cost,
        headline=_headline(a, b, comparable_on_cost),
        notes=notes,
    )


def _cost_rows(a: VerifiedStrategyOption, b: VerifiedStrategyOption) -> list[StrategyMetricDelta]:
    """One row per cost category present on either side."""
    rows: list[StrategyMetricDelta] = []
    categories = sorted(
        {c.category for c in a.cost.components} | {c.category for c in b.cost.components},
        key=lambda c: list(CostCategory).index(c),
    )

    for category in categories:
        total_a, known_a = _category_total(a, category)
        total_b, known_b = _category_total(b, category)
        rows.append(StrategyMetricDelta(
            metric=f"cost_{category.value.lower()}",
            # ``metric`` is the machine key and stays the enum; ``label`` is
            # the row heading a reader sees, so it is words. "Opex Per Day"
            # is a Title-cased identifier, not a heading.
            label=category_title(category),
            value_a=total_a if known_a else None,
            value_b=total_b if known_b else None,
            delta=_delta(total_a if known_a else None, total_b if known_b else None),
            unit="EUR",
        ))
    return rows


def _category_total(option: VerifiedStrategyOption, category: CostCategory) -> tuple[float, bool]:
    """(sum of known amounts in this category, whether ALL of them are known)."""
    relevant = [c for c in option.cost.components if c.category is category]
    if not relevant:
        return 0.0, True
    known = [c.amount for c in relevant if c.amount is not None]
    return sum(known), len(known) == len(relevant)


def _headline(a: VerifiedStrategyOption, b: VerifiedStrategyOption, comparable_on_cost: bool) -> str:
    """One deterministic sentence stating the primary difference."""
    if a.metrics.goal_met != b.metrics.goal_met:
        reached, missed = (a, b) if a.metrics.goal_met else (b, a)
        tail = (
            f" for EUR {reached.cost.known_capex:,.0f} known CAPEX"
            if reached.commercially_complete
            else " (its full cost is not yet known)"
        )
        return (
            f"{reached.label} reaches the target{tail}; {missed.label} falls "
            f"{missed.metrics.demand_gap_units:,.0f} units/day short."
        )

    if not a.metrics.goal_met and not b.metrics.goal_met:
        if a.metrics.demand_gap_units != b.metrics.demand_gap_units:
            closer, other = (a, b) if a.metrics.demand_gap_units < b.metrics.demand_gap_units else (b, a)
            return (
                f"Neither option reaches the target; {closer.label} gets closer "
                f"({closer.metrics.demand_gap_units:,.0f} short vs {other.metrics.demand_gap_units:,.0f})."
            )
        return "Neither option reaches the target, and both fall short by the same amount."

    # Both reach the target — now cost and complexity may decide.
    if not comparable_on_cost:
        return (
            f"{a.label} and {b.label} both reach the target, but they cannot be compared on cost "
            f"until the missing cost inputs are supplied."
        )

    capex_delta = b.cost.known_capex - a.cost.known_capex
    if capex_delta == 0:
        fewer = min((a, b), key=lambda o: o.actions.action_count)
        other = b if fewer is a else a
        if fewer.actions.action_count != other.actions.action_count:
            return (
                f"Both reach the target at the same known CAPEX; {fewer.label} does it with "
                f"{fewer.actions.action_count} change(s) instead of {other.actions.action_count}."
            )
        return f"{a.label} and {b.label} reach the target at the same known CAPEX and the same number of changes."

    cheaper, dearer = (b, a) if capex_delta < 0 else (a, b)
    return (
        f"Both reach the target; {cheaper.label} costs EUR {abs(capex_delta):,.0f} less in known CAPEX "
        f"(EUR {cheaper.cost.known_capex:,.0f} vs EUR {dearer.cost.known_capex:,.0f})."
    )
