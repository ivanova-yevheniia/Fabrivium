"""Phase 8C — deterministic story-marker derivation."""

from __future__ import annotations

from app.models.simulation_trace import SimulationTrace, StoryMarker, StoryMarkerType

#: A machine queue has to reach this depth before "a queue is forming" is
#: worth calling out — small transient queues of 1-2 units are normal
#: line noise, not a story beat.
_QUEUE_GROWING_THRESHOLD = 5


def _friendly(machine_or_buffer_id: str) -> str:
    """Mirrors app.services.explanation_agent._friendly_name — kept as its
    own small copy (that module's helper is private) rather than a cross-
    module import of a private name."""
    name = machine_or_buffer_id[2:] if machine_or_buffer_id.startswith(("m-", "b-")) else machine_or_buffer_id
    return name.replace("-", " ").replace("_", " ").title()


def derive_story_markers(trace: SimulationTrace) -> list[StoryMarker]:
    """Deterministically derive presentation markers from *trace*."""
    markers: list[StoryMarker] = []

    # Queue growth, per machine (first crossing of the threshold)
    machine_ids = sorted({s.machine_id for s in trace.machine_series})
    for machine_id in machine_ids:
        for sample in trace.machine_series:
            if sample.machine_id != machine_id:
                continue
            if sample.queue_length >= _QUEUE_GROWING_THRESHOLD:
                markers.append(
                    StoryMarker(
                        timestamp=sample.timestamp,
                        marker_type=StoryMarkerType.QUEUE_GROWING,
                        entity_id=machine_id,
                        title=f"Queue begins growing at {_friendly(machine_id)}",
                        evidence_ref=f"machine_series[{machine_id}].queue_length >= {_QUEUE_GROWING_THRESHOLD}",
                    )
                )
                break

    # Buffer reaches capacity, per buffer
    buffer_names = {b.buffer_id: b.buffer_name for b in trace.summary.buffer_kpis}
    blocking_observed = {b.buffer_id for b in trace.summary.buffer_kpis if b.blocking_observed}
    buffer_ids = sorted({s.buffer_id for s in trace.buffer_series})
    for buffer_id in buffer_ids:
        if buffer_id not in blocking_observed:
            continue
        for sample in trace.buffer_series:
            if sample.buffer_id != buffer_id:
                continue
            if sample.level >= sample.capacity:
                markers.append(
                    StoryMarker(
                        timestamp=sample.timestamp,
                        marker_type=StoryMarkerType.BUFFER_FULL,
                        entity_id=buffer_id,
                        title=f"{buffer_names.get(buffer_id, _friendly(buffer_id))} reaches capacity",
                        evidence_ref=f"buffer_kpis[{buffer_id}].blocking_observed",
                    )
                )
                break

    # Upstream machine becomes blocked, per machine
    for machine_id in machine_ids:
        for sample in trace.machine_series:
            if sample.machine_id != machine_id:
                continue
            if sample.blocked:
                markers.append(
                    StoryMarker(
                        timestamp=sample.timestamp,
                        marker_type=StoryMarkerType.MACHINE_BLOCKED,
                        entity_id=machine_id,
                        title=f"{_friendly(machine_id)} becomes blocked by a full downstream buffer",
                        evidence_ref=f"machine_series[{machine_id}].blocked",
                    )
                )
                break

    # Operator capacity becomes constrained: one marker for the whole system.
    operator_kpi = trace.summary.operator_kpi
    if operator_kpi is not None and operator_kpi.operator_constrained:
        for sample in trace.operator_series:
            if sample.waiting_operations > 0:
                markers.append(
                    StoryMarker(
                        timestamp=sample.timestamp,
                        marker_type=StoryMarkerType.OPERATOR_CONSTRAINED,
                        entity_id="system",
                        title="Operator capacity becomes constrained",
                        evidence_ref="operator_kpi.operator_constrained",
                    )
                )
                break

    # Target achieved or missed: always exactly one, at the last sample.
    if trace.system_series:
        last = trace.system_series[-1]
        if trace.summary.demand_met:
            markers.append(
                StoryMarker(
                    timestamp=last.timestamp,
                    marker_type=StoryMarkerType.TARGET_ACHIEVED,
                    entity_id="system",
                    title=f"Target achieved — {trace.summary.completed_units}/{trace.summary.target_units} units",
                    evidence_ref="summary.demand_met",
                )
            )
        else:
            markers.append(
                StoryMarker(
                    timestamp=last.timestamp,
                    marker_type=StoryMarkerType.TARGET_MISSED,
                    entity_id="system",
                    title=(
                        f"{trace.summary.completed_units}/{trace.summary.target_units} units — "
                        f"gap {trace.summary.demand_gap_units:g}"
                    ),
                    evidence_ref="summary.demand_met",
                )
            )

    markers.sort(key=lambda m: m.timestamp)
    return markers
