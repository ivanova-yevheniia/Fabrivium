"""Does buffer size actually matter here? — answered by simulating, not assuming."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.concept import FactoryConceptDraft, SourcedInt, ValueSource
from app.services.concept_validation import concept_to_factory
from app.services.simulation import run_simulation

# Sizes probed, smallest first.
CANDIDATE_SIZES: tuple[int, ...] = (0, 5, 10, 20, 50, 100)

# Throughput differences below this are treated as no difference.
INDIFFERENCE_UNITS = 1.0


@dataclass(frozen=True)
class BufferPoint:
    """One buffer size, and what the simulator did with it."""

    size: int
    completed_units: float
    target_units: float
    meets_target: bool
    # The limiting stage at this size, as the run reported it.
    limiting_stage_id: str | None
    # Time-weighted mean units held, averaged over the buffers.
    average_level: float | None
    #: Seconds an upstream station finished a unit and could not hand it on
    #: because the buffer was full. BufferKPI's own docstring calls this the
    #: only thing that makes a buffer worth enlarging, so it is the queue
    #: impact reported here rather than a raw queue length.
    upstream_blocked_seconds: float
    # True when the buffer was ever full with a unit waiting on it.
    blocking_observed: bool


@dataclass(frozen=True)
class BufferSensitivity:
    """The whole sweep, plus the finding an engineer actually needs."""

    points: list[BufferPoint] = field(default_factory=list)
    simulations_run: int = 0
    # True when every size produced the same output within INDIFFERENCE_UNITS.
    indifferent: bool = False
    # Smallest size that meets the target, or None when none does.
    smallest_size_meeting_target: int | None = None
    # One sentence stating the finding, written from the numbers above.
    summary: str = ""

    @property
    def throughput_span(self) -> float:
        if not self.points:
            return 0.0
        outputs = [p.completed_units for p in self.points]
        return max(outputs) - min(outputs)


def _with_all_buffers(draft: FactoryConceptDraft, size: int) -> FactoryConceptDraft:
    """Every buffer set to `size`, attributed to this sweep."""
    if size == 0:
        return draft.model_copy(update={"buffers": []})

    buffers = [
        b.model_copy(
            update={
                "capacity": SourcedInt.of(
                    size, ValueSource.CALCULATED, f"Buffer sweep probe at {size} units"
                )
            }
        )
        for b in draft.buffers
    ]
    return draft.model_copy(update={"buffers": buffers})


def sweep_buffer_sizes(
    draft: FactoryConceptDraft, sizes: tuple[int, ...] = CANDIDATE_SIZES
) -> BufferSensitivity:
    """Run the concept once per candidate buffer size."""
    if not draft.buffers:
        raise ValueError(
            "This concept has no buffers between stages, so there is no buffer size to sweep."
        )

    points: list[BufferPoint] = []
    for size in sizes:
        factory, product_id = concept_to_factory(_with_all_buffers(draft, size))
        result = run_simulation(factory, product_id)
        kpis = result.buffer_kpis or []
        levels = [b.average_level for b in kpis]
        points.append(
            BufferPoint(
                size=size,
                completed_units=float(result.completed_units),
                target_units=float(result.target_units),
                meets_target=bool(result.demand_met),
                limiting_stage_id=result.system.bottleneck_machine_id,
                average_level=(sum(levels) / len(levels)) if levels else None,
                upstream_blocked_seconds=sum(b.upstream_blocked_seconds for b in kpis),
                blocking_observed=any(b.blocking_observed for b in kpis),
            )
        )

    span = max(p.completed_units for p in points) - min(p.completed_units for p in points)
    indifferent = span < INDIFFERENCE_UNITS
    meeting = [p.size for p in points if p.meets_target]
    smallest = min(meeting) if meeting else None

    if indifferent:
        summary = (
            f"Buffer size does not change this line's output: every size from {sizes[0]} to "
            f"{sizes[-1]} units produced {points[0].completed_units:,.0f} units/day. The "
            f"constraint is elsewhere, so this value can be left at its default."
        )
        if not any(p.blocking_observed for p in points):
            summary += (
                " No upstream station was ever blocked waiting for buffer space, which is the "
                "evidence behind that."
            )
    elif smallest is not None:
        summary = (
            f"Buffering matters here: output spans {span:,.0f} units/day across the sizes tried. "
            f"{smallest} units is the smallest size that reaches the target."
        )
    else:
        best = max(points, key=lambda p: p.completed_units)
        summary = (
            f"Buffering changes output by {span:,.0f} units/day, but no size tried reaches the "
            f"target: the best, {best.size} units, gives {best.completed_units:,.0f} of "
            f"{best.target_units:,.0f}. The shortfall is not a buffering problem."
        )

    return BufferSensitivity(
        points=points,
        simulations_run=len(points),
        indifferent=indifferent,
        smallest_size_meeting_target=smallest,
        summary=summary,
    )
