"""
Plant Simulation layout transform 

* ``obj.getIconSize(w, h)`` answers **41 x 41** for Source, SingleProc,
  ParallelProc, Buffer and Drain alike and stays 41 x 41 for a
  ParallelProc with ``XDim := 6``. A frame unit is therefore roughly 1/41 of
  an object, NOT a metre. Fabrivium's own 5.5 m station pitch became a
  5-unit pitch: an eighth of one icon.

* ``createObject`` **silently clamps** any coordinate below 20 to 20. Sent
  4.25 / 9.75 / 15.25 / 31.75, the product returned XPos 20 / 20 / 20 / 31.
  Four of the six stations in the demo line were therefore created at
  literally the same point, and nothing in the old exporter ever read a
  position back to notice. 20 is ``floor(41 / 2)``, which also tells us the
  anchor is the icon CENTRE.

* Coordinates are truncated to integers (``XPos := 4.7`` reads back 4) and
  writing XPos/YPos afterwards sticks.

* The frame network ends between 30 000 and 32 000: x = 30 000 is accepted,
  x = 32 000 is refused with *"Das Objekt würde sich außerhalb des
  Netzwerks befinden."*

Two icons anchored at their centres do not overlap exactly when their
centres are at least ``ICON_UNITS`` apart along one axis. That is the
verification threshold; the planner targets a far wider pitch so a
connector is visibly drawn between neighbours.

``plan_layout`` never returns a plan that overlaps. It first tries to
PRESERVE the conceptual arrangement by normalising it — a single uniform
scale plus a Y flip, so relative positions survive — and it only accepts
that result if the collision check passes. When the concept cannot be
normalised safely (coincident stations, missing coordinates, an extent that
will not fit the network), it falls back to a generated engineering line,
which is collision-free by construction. Which of the two was used is
reported, never hidden: a transform that quietly redraws the engineer's
layout must say that it did.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


ICON_UNITS = 41

MIN_ANCHOR = 20

# was accepted
MAX_COORDINATE = 30_000

MARGIN = 80

COLUMN_PITCH = 90

ROW_PITCH = 130

MAX_PER_ROW = 12

MIN_SEPARATION_UNITS = ICON_UNITS


@dataclass(frozen=True)
class LayoutPlan:
    """Where every object goes, and how that was decided."""

    #: Object name (the SimTalk identifier) → integer frame coordinates.
    positions: dict[str, tuple[int, int]]
    #: "normalised-concept" — the conceptual arrangement, uniformly scaled.
    #: "generated-line"    — a clean engineering line down the route order.
    mode: str
    #: Present only for "generated-line": why the concept was not usable.
    #: Shown to the engineer, because silently replacing their arrangement
    #: with a different one would be a lie of omission.
    reason: str | None = None
    #: The smallest centre-to-centre separation in the plan, on the axis
    #: that separates each pair. Reported so the check has a number behind
    #: it rather than a boolean.
    min_separation: int = 0
    #: Ordered route the plan was built along: Source … Drain.
    chain: list[str] = field(default_factory=list)

    def position(self, name: str) -> tuple[int, int]:
        return self.positions[name]


def separation(a: tuple[int, int], b: tuple[int, int]) -> int:
    """How far apart two icon centres are, on the axis that separates them.

    Chebyshev distance.
    """
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def collisions(positions: dict[str, tuple[int, int]]) -> list[tuple[str, str, int]]:
    """Every pair whose icons would overlap, with the measured separation."""
    names = list(positions)
    found: list[tuple[str, str, int]] = []
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            gap = separation(positions[first], positions[second])
            if gap < MIN_SEPARATION_UNITS:
                found.append((first, second, gap))
    return found


def _min_separation(positions: dict[str, tuple[int, int]]) -> int:
    names = list(positions)
    if len(names) < 2:
        return MAX_COORDINATE
    return min(
        separation(positions[a], positions[b])
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    )


def _in_bounds(positions: dict[str, tuple[int, int]]) -> bool:
    return all(
        MIN_ANCHOR < x <= MAX_COORDINATE and MIN_ANCHOR < y <= MAX_COORDINATE
        for x, y in positions.values()
    )


# The generated engineering line — the fallback that always works


def generated_line(chain: list[str], reason: str | None = None) -> LayoutPlan:
    """Lay the route out left to right, wrapping in a serpentine.
    """
    positions: dict[str, tuple[int, int]] = {}
    for index, name in enumerate(chain):
        row, column = divmod(index, MAX_PER_ROW)
        if row % 2 == 1:
            # Serpentine: odd rows run back the other way.
            column = MAX_PER_ROW - 1 - column
        positions[name] = (MARGIN + column * COLUMN_PITCH, MARGIN + row * ROW_PITCH)
    return LayoutPlan(
        positions=positions,
        mode="generated-line",
        reason=reason,
        min_separation=_min_separation(positions),
        chain=list(chain),
    )


# The normalised concept layout — preferred, but only when it is provable


def _normalised_concept(
    chain: list[str],
    concept_points: dict[str, tuple[float, float]],
    neighbours: dict[str, tuple[str | None, str | None]],
) -> tuple[LayoutPlan | None, str | None]:
    """Scale the conceptual arrangement into frame units, or explain why not.
    """
    placed = {name: p for name, p in concept_points.items() if name in chain}
    if len(placed) < 2:
        return None, "the concept layout places fewer than two stations"

    distinct = set(placed.values())
    if len(distinct) < len(placed):
        return None, "two stations share the same conceptual coordinate"

    closest = min(
        separation_float(a, b)
        for i, a in enumerate(placed.values())
        for b in list(placed.values())[i + 1 :]
    )
    if closest <= 0:
        return None, "two stations share the same conceptual coordinate"


    interleaved = any(
        name not in placed
        and all(neighbour in placed for neighbour in neighbours.get(name, (None, None)) if neighbour)
        and all(neighbours.get(name, (None, None)))
        for name in chain
    )
    target_pitch = COLUMN_PITCH * 2 if interleaved else COLUMN_PITCH
    scale = target_pitch / closest

    xs = [p[0] for p in placed.values()]
    ys = [p[1] for p in placed.values()]
    span_x = (max(xs) - min(xs)) * scale
    span_y = (max(ys) - min(ys)) * scale

    if MARGIN + span_x + 2 * target_pitch > MAX_COORDINATE:
        return None, "the concept layout is too wide to fit a Plant Simulation frame at a legible scale"
    if MARGIN + span_y + 2 * ROW_PITCH > MAX_COORDINATE:
        return None, "the concept layout is too deep to fit a Plant Simulation frame at a legible scale"

    origin_x, top_y = min(xs), max(ys)

    def to_frame(point: tuple[float, float]) -> tuple[int, int]:
        return (
            int(round(MARGIN + target_pitch + (point[0] - origin_x) * scale)),
            int(round(MARGIN + (top_y - point[1]) * scale)),
        )

    positions: dict[str, tuple[int, int]] = {name: to_frame(p) for name, p in placed.items()}


    for name in chain:
        if name in positions:
            continue
        before, after = neighbours.get(name, (None, None))
        anchor_before = positions.get(before or "")
        anchor_after = positions.get(after or "")
        if anchor_before and anchor_after:
            
            midpoint = (
                (anchor_before[0] + anchor_after[0]) // 2,
                (anchor_before[1] + anchor_after[1]) // 2,
            )
            if _clear_of(midpoint, positions.values()):
                positions[name] = midpoint
            else:
                positions[name] = _free_row_below(
                    x=midpoint[0],
                    start_y=max(anchor_before[1], anchor_after[1]),
                    occupied=positions.values(),
                )
        elif anchor_after:
            positions[name] = (anchor_after[0] - target_pitch, anchor_after[1])
        elif anchor_before:
            positions[name] = (anchor_before[0] + target_pitch, anchor_before[1])
        else:
            return None, "an object on the route has no placed neighbour to derive a position from"

    if not _in_bounds(positions):
        return None, "the normalised concept layout falls outside the Plant Simulation frame"

    clashes = collisions(positions)
    if clashes:
        first = clashes[0]
        return None, (
            f"the concept layout cannot be separated without distorting it "
            f"({first[0]} and {first[1]} stay {first[2]} units apart, under the "
            f"{MIN_SEPARATION_UNITS}-unit icon)"
        )

    return (
        LayoutPlan(
            positions=positions,
            mode="normalised-concept",
            reason=None,
            min_separation=_min_separation(positions),
            chain=list(chain),
        ),
        None,
    )


def _clear_of(point: tuple[int, int], occupied: "Iterable[tuple[int, int]]") -> bool:
    """Does an icon at `point` clear every icon already placed?"""
    return all(separation(point, other) >= MIN_SEPARATION_UNITS for other in occupied)


def _free_row_below(
    x: int,
    start_y: int,
    occupied: "Iterable[tuple[int, int]]",
) -> tuple[int, int]:
    """The first row below `start_y` where an icon at `x` clears everything.

    """
    placed = list(occupied)
    y = start_y + ROW_PITCH
    while y <= MAX_COORDINATE:
        if all(separation((x, y), other) >= MIN_SEPARATION_UNITS for other in placed):
            return (x, y)
        y += ROW_PITCH
    return (x, start_y + ROW_PITCH)


def separation_float(a: tuple[float, float], b: tuple[float, float]) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# Entry point


def plan_layout(
    chain: list[str],
    concept_points: dict[str, tuple[float, float]] | None = None,
    neighbours: dict[str, tuple[str | None, str | None]] | None = None,
    fallback_reason: str | None = None,
) -> LayoutPlan:
    """Place every object on ``chain`` so that none of them overlap.

    ``chain`` is the route in order — Source, the stations and any buffers
    between them, Drain — named exactly as they will be named in Plant
    Simulation. ``concept_points`` carries Fabrivium's own coordinates for
    the objects that have them; ``neighbours`` says which chain members sit
    either side of an object that does not.
    """
    if not chain:
        return LayoutPlan(positions={}, mode="generated-line", reason="the route is empty")

    reason = fallback_reason or "the concept carries no layout coordinates"
    if concept_points:
        plan, rejected = _normalised_concept(chain, concept_points, neighbours or {})
        if plan is not None:
            return plan
        reason = rejected or reason

    return generated_line(chain, reason=reason)
