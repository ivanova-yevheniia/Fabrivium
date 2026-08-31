"""Deterministic placement search for Fabrivium Phase 4B."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.factory import Factory
from app.models.layout import FactoryLayout, MachinePlacement
from app.services.constraints import validate_layout
from app.services.layout import LayoutError, get_placement, place_machine

# Default distance (m) between adjacent grid points.
DEFAULT_GRID_SPACING = 0.5

# Default hard cap on the number of position+rotation combinations tried.
DEFAULT_MAX_POSITION_ATTEMPTS = 2000

# Orientations tried at every candidate position, in this fixed order.
ROTATIONS: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)


@dataclass(frozen=True)
class PlacementSearchResult:
    """Outcome of one ``find_placement`` call."""

    placement: MachinePlacement | None
    attempts: int


def _ring_offsets(ring: int, spacing: float) -> list[tuple[float, float]]:
    """
    Deterministic (dx, dy) offsets forming the boundary of a square "ring" at Chebyshev
    distance ``ring`` grid-steps from the origin.
    """
    if ring == 0:
        return [(0.0, 0.0)]
    offsets: list[tuple[float, float]] = []
    for i in range(-ring, ring + 1):
        for j in range(-ring, ring + 1):
            if max(abs(i), abs(j)) == ring:
                offsets.append((i * spacing, j * spacing))
    return offsets


def find_placement(
    factory: Factory,
    layout: FactoryLayout,
    machine_id: str,
    near_machine_id: str | None = None,
    grid_spacing: float = DEFAULT_GRID_SPACING,
    max_position_attempts: int = DEFAULT_MAX_POSITION_ATTEMPTS,
) -> PlacementSearchResult:
    """
    Search for a valid placement for *machine_id* (already present in *factory* but NOT
    yet in *layout*) without moving any existing placement in *layout*.
    """
    state = {"attempts": 0}

    def _try(x: float, y: float, rotation: float) -> MachinePlacement | None:
        if not (0.0 <= x <= factory.width and 0.0 <= y <= factory.length):
            return None
        state["attempts"] += 1
        try:
            trial_layout = place_machine(factory, layout, machine_id, x=x, y=y, rotation_deg=rotation)
        except LayoutError:
            return None
        result = validate_layout(factory, trial_layout)
        if result.error_count == 0:
            return get_placement(trial_layout, machine_id)
        return None

    def _exhausted() -> bool:
        return state["attempts"] >= max_position_attempts

    near = get_placement(layout, near_machine_id) if near_machine_id is not None else None

    if near is not None:
        max_ring = int(math.ceil(max(factory.width, factory.length) / grid_spacing)) + 1
        for ring in range(0, max_ring + 1):
            if _exhausted():
                return PlacementSearchResult(None, state["attempts"])
            for dx, dy in _ring_offsets(ring, grid_spacing):
                x, y = near.x + dx, near.y + dy
                for rotation in ROTATIONS:
                    if _exhausted():
                        return PlacementSearchResult(None, state["attempts"])
                    placement = _try(x, y, rotation)
                    if placement is not None:
                        return PlacementSearchResult(placement, state["attempts"])
        return PlacementSearchResult(None, state["attempts"])

    # Fallback: row-major global grid scan.
    y = 0.0
    while y <= factory.length:
        x = 0.0
        while x <= factory.width:
            for rotation in ROTATIONS:
                if _exhausted():
                    return PlacementSearchResult(None, state["attempts"])
                placement = _try(x, y, rotation)
                if placement is not None:
                    return PlacementSearchResult(placement, state["attempts"])
            x += grid_spacing
        y += grid_spacing

    return PlacementSearchResult(None, state["attempts"])
