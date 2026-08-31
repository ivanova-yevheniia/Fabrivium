"""Phase 8C — typed playback trace models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.simulation import SimulationResult


# Trace capture mode


class TraceMode(str, Enum):
    """How much (if any) playback trace a simulation run should retain."""

    NONE = "NONE"
    SUMMARY = "SUMMARY"
    PLAYBACK = "PLAYBACK"


class TracePlaybackConfig(BaseModel):
    """Bounds and sampling parameters for a PLAYBACK-mode trace."""

    model_config = {"frozen": True}

    max_tracked_units: int = Field(
        40, ge=1, le=500,
        description="Units with unit_id below this get individual milestone events. All units (tracked or not) still count toward sampled series.",
    )
    sample_count_target: int = Field(
        240, ge=10, le=2000,
        description="Approximate number of samples per series across the horizon. The actual sample interval is horizon_seconds / sample_count_target, rounded up to a whole second.",
    )


# Unit milestone events


class UnitEventType(str, Enum):
    """Every event type has a direct visual use (Phase 8C section 2) —
    nothing is added 'in case it's useful'."""

    UNIT_RELEASED = "UNIT_RELEASED"
    UNIT_ENTERED_MACHINE_QUEUE = "UNIT_ENTERED_MACHINE_QUEUE"
    UNIT_STARTED_PROCESSING = "UNIT_STARTED_PROCESSING"
    UNIT_FINISHED_PROCESSING = "UNIT_FINISHED_PROCESSING"
    UNIT_ENTERED_BUFFER = "UNIT_ENTERED_BUFFER"
    UNIT_LEFT_BUFFER = "UNIT_LEFT_BUFFER"
    UNIT_COMPLETED = "UNIT_COMPLETED"
    MACHINE_BLOCKED = "MACHINE_BLOCKED"
    MACHINE_UNBLOCKED = "MACHINE_UNBLOCKED"


class UnitEvent(BaseModel):
    """One milestone for one tracked unit (or, for MACHINE_BLOCKED/
    MACHINE_UNBLOCKED, one machine — ``unit_id`` is the unit whose outbound
    buffer being full caused the block)."""

    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0, description="Simulated seconds since horizon start")
    unit_id: int = Field(..., ge=0)
    event_type: UnitEventType
    machine_id: str | None = None
    buffer_id: str | None = None


# Sampled time series


class MachineTraceSample(BaseModel):
    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0)
    machine_id: str
    queue_length: int = Field(..., ge=0)
    processing_count: int = Field(..., ge=0, description="Units currently occupying this machine's capacity")
    blocked: bool = Field(..., description="True iff this machine is currently held by a finished unit that cannot yet enter its outbound buffer")
    utilization_so_far: float = Field(..., ge=0.0, le=1.0, description="busy_time / elapsed_time up to this sample — authoritative, computed the same way as the final MachineKPI.utilization")


class BufferTraceSample(BaseModel):
    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0)
    buffer_id: str
    level: int = Field(..., ge=0)
    capacity: int = Field(..., ge=1)
    blocked_upstream: bool = Field(..., description="True iff the buffer is full AND an upstream unit is currently waiting to enter it")


class OperatorTraceSample(BaseModel):
    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0)
    operators_in_use: int = Field(..., ge=0)
    operators_available: int = Field(..., ge=0)
    waiting_operations: int = Field(..., ge=0, description="Operations currently blocked waiting for staff at this instant")


class SystemTraceSample(BaseModel):
    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0)
    completed_units: int = Field(..., ge=0)
    released_units: int = Field(..., ge=0)
    current_bottleneck_machine_id: str | None = Field(
        None,
        description="Highest-utilization-so-far stage AT THIS SAMPLE, using the exact same saturation/queue-length tie-break as the final SystemKPI.bottleneck_machine_id. None only in the impossible case of zero stages.",
    )


# Story markers (Phase 8C section 18) — deterministic, never LLM-generated


class StoryMarkerType(str, Enum):
    QUEUE_GROWING = "QUEUE_GROWING"
    BUFFER_FULL = "BUFFER_FULL"
    MACHINE_BLOCKED = "MACHINE_BLOCKED"
    OPERATOR_CONSTRAINED = "OPERATOR_CONSTRAINED"
    TARGET_ACHIEVED = "TARGET_ACHIEVED"
    TARGET_MISSED = "TARGET_MISSED"


class StoryMarker(BaseModel):
    model_config = {"frozen": True}

    timestamp: float = Field(..., ge=0.0)
    marker_type: StoryMarkerType
    entity_id: str = Field(..., description="machine_id, buffer_id, or 'system'")
    title: str = Field(..., description="Deterministic templated label, e.g. 'Buffer 1 reaches capacity'")
    evidence_ref: str = Field(..., description="What in the trace/KPI this marker is evidence of, e.g. 'buffer_kpis[buf-1].blocking_observed'")


# Top-level trace


class SimulationTrace(BaseModel):
    """Full playback trace for one simulation run."""

    model_config = {"frozen": True}

    trace_version: int = Field(1, description="Bump when the trace shape changes incompatibly")
    horizon_seconds: float = Field(..., gt=0.0)
    sampled_interval_seconds: float = Field(..., gt=0.0)
    config: TracePlaybackConfig

    events: list[UnitEvent] = Field(default_factory=list)
    machine_series: list[MachineTraceSample] = Field(default_factory=list)
    buffer_series: list[BufferTraceSample] = Field(default_factory=list)
    operator_series: list[OperatorTraceSample] = Field(default_factory=list)
    system_series: list[SystemTraceSample] = Field(default_factory=list)
    story_markers: list[StoryMarker] = Field(default_factory=list)

    tracked_unit_count: int = Field(..., ge=0, description="How many distinct unit_ids appear in `events` — always <= config.max_tracked_units")
    total_unit_count: int = Field(..., ge=0, description="target_units for this run — every unit, tracked or not, is reflected in the sampled series")

    summary: SimulationResult = Field(..., description="The authoritative KPI result for this exact run — trace/KPI consistency invariant (section 8)")

    metadata: dict[str, str] = Field(default_factory=dict, description="Free-form provenance, e.g. factory name, product_id — display only, never parsed for physics")
