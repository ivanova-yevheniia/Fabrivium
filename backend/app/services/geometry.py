"""Pure 2D rectangle geometry for Fabrivium Phase 3B."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.factory import Machine
    from app.models.layout import MachinePlacement

Point = tuple[float, float]

#: Numerical tolerance used throughout this module — small enough to never
#: mask a genuine violation, large enough to absorb floating-point noise
#: from rotation (sin/cos) so that exact-edge-touching layouts are never
#: misreported as overlapping.
EPSILON = 1e-9


# Rectangle construction

def _rotate(point: Point, angle_rad: float) -> Point:
    x, y = point
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def oriented_rectangle(
    center_x: float,
    center_y: float,
    rotation_deg: float,
    min_local_x: float,
    max_local_x: float,
    min_local_y: float,
    max_local_y: float,
) -> list[Point]:
    """
    Return the 4 global-space corners of a rectangle defined in a local frame (possibly
    asymmetric about the local origin — e.g.
    """
    angle_rad = math.radians(rotation_deg)
    local_corners = [
        (min_local_x, min_local_y),
        (max_local_x, min_local_y),
        (max_local_x, max_local_y),
        (min_local_x, max_local_y),
    ]
    return [
        (center_x + rx, center_y + ry)
        for rx, ry in (_rotate(c, angle_rad) for c in local_corners)
    ]


def axis_aligned_rectangle(x: float, y: float, width: float, length: float) -> list[Point]:
    """Corners of an axis-aligned rectangle with (*x*, *y*) as its
    LOWER-LEFT corner — the ``LayoutZone`` convention."""
    return [(x, y), (x + width, y), (x + width, y + length), (x, y + length)]


def get_machine_footprint(machine: "Machine", placement: "MachinePlacement") -> list[Point]:
    """The 4 global corners of *machine*'s physical footprint at
    *placement*, using ``Machine.width``/``Machine.length`` as the single
    source of truth (see module docstring for the width=left-right,
    length=front-back convention) and honouring arbitrary rotation."""
    half_w = machine.width / 2.0
    half_l = machine.length / 2.0
    return oriented_rectangle(
        placement.x, placement.y, placement.rotation_deg,
        -half_w, half_w, -half_l, half_l,
    )


def get_machine_safety_envelope(machine: "Machine", placement: "MachinePlacement") -> list[Point]:
    """The 4 global corners of *machine*'s expanded safety envelope at
    *placement*: the footprint grown by ``Machine.physical_envelope``'s
    directional clearances (0 on every side when ``physical_envelope`` is
    None), rotated rigidly with the machine.
    """
    half_w = machine.width / 2.0
    half_l = machine.length / 2.0
    extras = machine.physical_envelope

    clearance_front = extras.safety_clearance_front if extras is not None else 0.0
    clearance_back = extras.safety_clearance_back if extras is not None else 0.0
    clearance_left = extras.safety_clearance_left if extras is not None else 0.0
    clearance_right = extras.safety_clearance_right if extras is not None else 0.0

    return oriented_rectangle(
        placement.x, placement.y, placement.rotation_deg,
        -half_w - clearance_left, half_w + clearance_right,
        -half_l - clearance_back, half_l + clearance_front,
    )


# Separating Axis Theorem (SAT) — convex polygon overlap

def _edge_axes(corners: list[Point]) -> list[Point]:
    """Unit outward-normal directions of each edge of a convex polygon
    (up to 4 for a rectangle; fewer if some are numerically parallel)."""
    axes: list[Point] = []
    n = len(corners)
    for i in range(n):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % n]
        edge = (x2 - x1, y2 - y1)
        normal = (-edge[1], edge[0])
        norm = math.hypot(*normal)
        if norm > EPSILON:
            axes.append((normal[0] / norm, normal[1] / norm))
    return axes


def _project(corners: list[Point], axis: Point) -> tuple[float, float]:
    dots = [px * axis[0] + py * axis[1] for px, py in corners]
    return min(dots), max(dots)


def rectangles_overlap(rect_a: list[Point], rect_b: list[Point], epsilon: float = EPSILON) -> bool:
    """
    True iff *rect_a* and *rect_b* (each a list of 4 corners from
    ``oriented_rectangle``/``axis_aligned_rectangle``) have a strictly POSITIVE-AREA
    intersection.
    """
    for axis in (*_edge_axes(rect_a), *_edge_axes(rect_b)):
        min_a, max_a = _project(rect_a, axis)
        min_b, max_b = _project(rect_b, axis)
        overlap = min(max_a, max_b) - max(min_a, min_b)
        if overlap <= epsilon:
            return False
    return True


def rectangle_within_bounds(rect: list[Point], width: float, length: float, epsilon: float = EPSILON) -> bool:
    """
    True iff every corner of *rect* lies within [0, *width*] x [0, *length*] (inclusive
    of the boundary).
    """
    return all(
        -epsilon <= x <= width + epsilon and -epsilon <= y <= length + epsilon
        for x, y in rect
    )
