"""Pure Pareto dominance math for Fabrivium Phase 4C."""

from __future__ import annotations

from typing import Literal

# A dimension is (key, direction). "min" = lower is better, "max" = higher is better.
Direction = Literal["min", "max"]
Dimension = tuple[str, Direction]

PARETO_EPSILON = 1e-6


def dominates(a: dict[str, float], b: dict[str, float], dims: list[Dimension], epsilon: float = PARETO_EPSILON) -> bool:
    """
    True iff *a* Pareto-dominates *b* over *dims*: no worse than *b* on every dimension
    (within *epsilon*), and strictly better on at least one.
    """
    at_least_as_good_everywhere = True
    strictly_better_somewhere = False

    for key, direction in dims:
        va, vb = a[key], b[key]
        if direction == "max":
            va, vb = -va, -vb

        if va > vb + epsilon:
            at_least_as_good_everywhere = False
            break
        if va < vb - epsilon:
            strictly_better_somewhere = True

    return at_least_as_good_everywhere and strictly_better_somewhere


def compute_dominance(
    items: list[tuple[str, dict[str, float]]], dims: list[Dimension], epsilon: float = PARETO_EPSILON
) -> tuple[set[str], dict[str, list[str]], dict[str, list[str]]]:
    """Compute pairwise dominance over *items* = [(id, values), ...]."""
    ids = [item_id for item_id, _ in items]
    values = dict(items)

    dominated_by: dict[str, list[str]] = {i: [] for i in ids}
    dominates_map: dict[str, list[str]] = {i: [] for i in ids}

    for a_id in ids:
        for b_id in ids:
            if a_id == b_id:
                continue
            if dominates(values[a_id], values[b_id], dims, epsilon):
                dominates_map[a_id].append(b_id)
                dominated_by[b_id].append(a_id)

    for i in ids:
        dominated_by[i] = sorted(set(dominated_by[i]))
        dominates_map[i] = sorted(set(dominates_map[i]))

    frontier = {i for i in ids if not dominated_by[i]}
    return frontier, dominated_by, dominates_map
