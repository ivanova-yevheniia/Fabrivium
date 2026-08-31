"""Pydantic response models for Fabrivium Phase 1 simulation output."""

from __future__ import annotations

from pydantic import BaseModel, Field


# Per-machine KPIs

class MachineKPI(BaseModel):
    """Measured statistics for a single machine over the simulation horizon."""

    machine_id: str = Field(..., description="Machine identifier")
    machine_name: str = Field(..., description="Human-readable machine name")

    processed_units: int = Field(..., ge=0, description="Units that completed processing on this machine")
    busy_time_seconds: float = Field(..., ge=0.0, description="Total seconds machine was actively processing")
    utilization: float = Field(..., ge=0.0, le=1.0,
                               description="busy_time / simulation_horizon (0–1)")

    average_queue_length: float = Field(..., ge=0.0,
                                        description="Time-weighted mean number of units waiting")
    max_queue_length: int = Field(..., ge=0, description="Peak observed queue depth")

    average_wait_time_seconds: float = Field(..., ge=0.0,
                                             description="Mean time a unit spent waiting before processing")
    max_wait_time_seconds: float = Field(..., ge=0.0,
                                         description="Worst-case wait time observed")


# Per-logical-stage (machine service pool) KPIs — Phase 2B

class ProcessPoolKPI(BaseModel):
    """
    Aggregate statistics for one logical ProcessStep, across every physical machine in
    its service pool.
    """

    process_step_name: str = Field(..., description="ProcessStep.name for this logical stage")
    reference_machine_id: str = Field(
        ..., description="ProcessStep.machine_id — the pool's reference/root machine id"
    )
    machine_ids: list[str] = Field(
        ..., min_length=1, description="Physical machines serving this stage, sorted by id"
    )

    processed_units: int = Field(..., ge=0, description="Units completed across the whole pool")
    utilization: float = Field(
        ..., ge=0.0, le=1.0,
        description="Aggregate busy_time / (horizon * total pool capacity)"
    )

    average_queue_length: float = Field(
        ..., ge=0.0,
        description="Time-weighted mean number of units waiting for the pool (shared queue)"
    )
    max_queue_length: int = Field(..., ge=0, description="Peak observed pool queue depth")

    average_wait_time_seconds: float = Field(
        ..., ge=0.0,
        description="Mean time a unit spent waiting before being dispatched to any pool machine"
    )
    max_wait_time_seconds: float = Field(
        ..., ge=0.0,
        description="Worst-case wait time observed at this stage"
    )


# Global / system KPIs

class SystemKPI(BaseModel):
    """Line-level production metrics."""

    average_flow_time_seconds: float = Field(
        ..., ge=0.0,
        description="Mean elapsed time from unit creation to completion"
    )
    max_flow_time_seconds: float = Field(
        ..., ge=0.0,
        description="Worst-case unit flow time"
    )
    work_in_progress: int = Field(
        ..., ge=0,
        description=(
            "Units that entered the line but had not yet completed "
            "the full route when the simulation horizon elapsed. "
            "These are NOT counted in completed_units."
        )
    )
    bottleneck_machine_id: str = Field(
        ...,
        description=(
            "Reference machine_id of the logical stage (service pool) with "
            "the highest aggregate utilization across the simulation — see "
            "ProcessPoolKPI. In the case of a tie the stage with the longest "
            "average queue length wins; further ties are broken by stage "
            "order in the product route. For every Phase 0-2A factory "
            "(every pool has exactly one machine) this is identical to "
            "'the machine with the highest utilization', matching Phase 1.2 "
            "behaviour exactly."
        )
    )


# Top-level result

# Phase 8A — workforce and buffer KPIs


class OperatorKPI(BaseModel):
    """Workforce utilisation for one simulation run."""

    model_config = {"frozen": True}

    operators_available: int = Field(..., ge=0, description="Size of the shared workforce pool")
    operators_required_peak: int = Field(
        ..., ge=0,
        description="Operators the line would need if every machine on the route ran at once — the demand ceiling, not a measurement.",
    )
    peak_operators_in_use: int = Field(..., ge=0, description="Highest simultaneous operator usage actually observed")
    average_operators_in_use: float = Field(..., ge=0.0, description="Time-weighted mean operators in use over the horizon")
    utilization: float = Field(
        ..., ge=0.0, le=1.0,
        description="average_operators_in_use / operators_available; 0 when there are no operators to use.",
    )
    total_operator_wait_seconds: float = Field(..., ge=0.0)
    average_operator_wait_seconds: float = Field(..., ge=0.0, description="Mean wait per operation that needed operators")
    max_operator_wait_seconds: float = Field(..., ge=0.0)
    operations_delayed_by_operators: int = Field(
        ..., ge=0, description="How many machine operations had to wait for staff before they could start",
    )
    operator_constrained: bool = Field(
        ..., description="True iff at least one operation actually waited for an operator. The evidence gate for proposing more staff.",
    )


class BufferKPI(BaseModel):
    """Occupancy and blocking for one wired buffer."""

    model_config = {"frozen": True}

    buffer_id: str
    buffer_name: str
    capacity: int = Field(..., ge=1)
    upstream_machine_id: str
    downstream_machine_id: str

    average_level: float = Field(..., ge=0.0, description="Time-weighted mean units held")
    max_level: int = Field(..., ge=0)
    utilization: float = Field(..., ge=0.0, le=1.0, description="average_level / capacity")

    time_full_seconds: float = Field(..., ge=0.0)
    time_empty_seconds: float = Field(..., ge=0.0)
    full_fraction: float = Field(..., ge=0.0, le=1.0)
    empty_fraction: float = Field(..., ge=0.0, le=1.0)

    upstream_blocked_seconds: float = Field(
        ..., ge=0.0, description="Time an upstream machine was held by a finished unit that could not be handed on because this buffer was full.",
    )
    upstream_blocked_events: int = Field(..., ge=0)
    blocking_observed: bool = Field(
        ..., description="True iff the buffer was ever full while an upstream unit was waiting. The evidence gate for proposing more storage.",
    )


class SimulationResult(BaseModel):
    """Full output of one simulation run."""

    # Simulation horizon meta
    simulation_time_seconds: float = Field(..., gt=0.0,
                                           description="Total simulated time (seconds)")

    # Release-schedule parameters (exposed for downstream optimisation agents)
    target_units: int = Field(..., ge=1, description="ceil(demand_per_day); units the simulation targets")
    nominal_route_time_seconds: float = Field(
        ..., ge=0.0,
        description="Sum of all ProcessStep cycle times (minimum possible flow time)"
    )
    release_interval_seconds: float = Field(
        ..., ge=0.0,
        description=(
            "(horizon - nominal_route_time) / (target_units - 1), "
            "or 0 when target_units == 1"
        )
    )

    # Throughput
    completed_units: int = Field(..., ge=0)
    throughput_per_hour: float = Field(..., ge=0.0)

    # Demand
    demand_per_day: float = Field(..., gt=0.0)
    demand_met: bool = Field(..., description="completed_units >= target_units")
    demand_gap_units: float = Field(
        ..., ge=0.0,
        description="max(target_units - completed_units, 0); 0 when demand is met"
    )

    # Children
    machine_kpis: list[MachineKPI]
    system: SystemKPI
    # Phase 8A.
    operator_kpi: OperatorKPI | None = Field(
        None,
        description=(
            "Workforce utilisation. None only when the run predates Phase 8A; a route whose "
            "machines need zero operators still reports a KPI, with zeros."
        ),
    )
    buffer_kpis: list[BufferKPI] = Field(
        default_factory=list,
        description="One entry per WIRED buffer on this product's route. Buffers with no explicit upstream/downstream stage do not participate and are absent.",
    )
    process_pool_kpis: list[ProcessPoolKPI] = Field(
        default_factory=list,
        description=(
            "One entry per logical ProcessStep (route order), aggregating "
            "across its machine service pool. See ProcessPoolKPI for the "
            "pool- vs per-machine queue semantics. This is the authoritative "
            "source for bottleneck detection."
        ),
    )
