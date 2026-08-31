"""Budget arithmetic for Fabrivium planning sessions."""

from __future__ import annotations


def remaining_known_capex(max_capex: float | None, cumulative_known_capex: float) -> float | None:
    """
    Known CAPEX still available given a *max_capex* ceiling and the
    *cumulative_known_capex* committed so far.
    """
    if max_capex is None:
        return None
    return max_capex - cumulative_known_capex
