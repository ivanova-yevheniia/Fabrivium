"""
Fabrivium Phase 1.2 -> Phase 2B - deterministic discrete-event production simulation.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Generator

import simpy

from app.models.factory import Buffer, Factory, Machine, Product
from app.models.simulation import (
    BufferKPI,
    MachineKPI,
    OperatorKPI,
    ProcessPoolKPI,
    SimulationResult,
    SystemKPI,
)
from app.models.simulation_trace import (
    BufferTraceSample,
    MachineTraceSample,
    OperatorTraceSample,
    SimulationTrace,
    SystemTraceSample,
    TraceMode,
    TracePlaybackConfig,
    UnitEvent,
    UnitEventType,
)
from app.services.machine_pool import resolve_pool
from app.services.route_validator import validate_route
from app.services.simulation_trace import derive_story_markers


# Internal measurement containers

class _QueueWaitTracker:
    """Shared time-weighted queue-depth and wait-time bookkeeping."""

    def __init__(self, horizon: float) -> None:
        self.horizon = horizon  # total simulated seconds

        # (time, depth) samples recorded whenever the queue depth changes.
        self._queue_samples: list[tuple[float, int]] = [(0.0, 0)]
        self._current_queue: int = 0

        # Per-unit wait times (seconds spent waiting before being dispatched).
        self._wait_times: list[float] = []

    # Queue tracking

    def queue_arrived(self, env_now: float) -> None:
        """Call when a unit joins the queue."""
        self._flush_queue_sample(env_now)
        self._current_queue += 1

    def queue_left(self, env_now: float) -> None:
        """Call when a unit leaves the queue (starts processing)."""
        self._flush_queue_sample(env_now)
        self._current_queue = max(0, self._current_queue - 1)

    def _flush_queue_sample(self, env_now: float) -> None:
        """Record a new sample only if time has advanced."""
        last_t, _ = self._queue_samples[-1]
        if env_now > last_t:
            self._queue_samples.append((env_now, self._current_queue))

    def record_wait(self, wait_seconds: float) -> None:
        self._wait_times.append(wait_seconds)

    # Derived queue/wait KPIs

    @property
    def average_queue_length(self) -> float:
        """Time-weighted average queue depth over the full horizon."""
        samples = self._queue_samples + [(self.horizon, self._current_queue)]
        total_area = 0.0
        for i in range(len(samples) - 1):
            t_start, depth = samples[i]
            t_end, _ = samples[i + 1]
            total_area += depth * (t_end - t_start)
        return total_area / self.horizon if self.horizon > 0 else 0.0

    def average_queue_length_up_to(self, now: float) -> float:
        """Same integration as ``average_queue_length``, but over [0, now]
        instead of the full horizon — Phase 8C's live trace sampler calls
        this mid-run, when every recorded sample already has timestamp
        <= now (the sampler and the events it observes share one
        simulated clock), to report the SAME 'which stage is congested'
        signal the final KPI uses, just as of this instant."""
        if now <= 0:
            return 0.0
        samples = self._queue_samples + [(now, self._current_queue)]
        total_area = 0.0
        for i in range(len(samples) - 1):
            t_start, depth = samples[i]
            t_end, _ = samples[i + 1]
            t_end = min(t_end, now)
            if t_end <= t_start:
                continue
            total_area += depth * (t_end - t_start)
        return total_area / now

    @property
    def current_queue_depth(self) -> int:
        """Live queue depth right now — used only by the Phase 8C trace
        sampler; the final KPIs still use the time-integrated properties
        above."""
        return self._current_queue

    @property
    def max_queue_length(self) -> int:
        return max((depth for _, depth in self._queue_samples), default=0)

    @property
    def average_wait_time(self) -> float:
        if not self._wait_times:
            return 0.0
        return sum(self._wait_times) / len(self._wait_times)

    @property
    def max_wait_time(self) -> float:
        return max(self._wait_times, default=0.0)


class _MachineStats(_QueueWaitTracker):
    """Accumulates statistics for one physical machine during a simulation run."""

    def __init__(self, machine: Machine, horizon: float, pooled: bool) -> None:
        super().__init__(horizon)
        self.machine = machine
        # True iff this machine belongs to a service pool of size >= 2.
        self.pooled = pooled

        self.processed_units: int = 0
        self.busy_time: float = 0.0

    def record_processing(self, duration: float) -> None:
        self.busy_time += duration
        self.processed_units += 1

    @property
    def utilization(self) -> float:
        if self.horizon <= 0:
            return 0.0
        return min(1.0, self.busy_time / (self.horizon * self.machine.capacity))

    def to_kpi(self) -> MachineKPI:
        # Pooled machines never have a local queue (the queue is shared at
        # the pool level — see ProcessPoolKPI), so report 0 rather than an
        # arbitrary/misleading per-machine figure.
        avg_q = 0.0 if self.pooled else round(self.average_queue_length, 6)
        max_q = 0 if self.pooled else self.max_queue_length
        return MachineKPI(
            machine_id=self.machine.id,
            machine_name=self.machine.name,
            processed_units=self.processed_units,
            busy_time_seconds=round(self.busy_time, 6),
            utilization=round(self.utilization, 6),
            average_queue_length=avg_q,
            max_queue_length=max_q,
            average_wait_time_seconds=round(self.average_wait_time, 6),
            max_wait_time_seconds=round(self.max_wait_time, 6),
        )


class _PoolStats(_QueueWaitTracker):
    """Time-weighted queue-depth and wait-time accumulator for one logical
    service pool, shared across every physical machine in that pool."""


# Shared bottleneck ranking (final KPI *and* Phase 8C live trace samples)

# See the "Bottleneck detection" section of this module's docstring for the full
# rationale.
_SATURATION_THRESHOLD = 0.999

#: How far past the nominal horizon the run continues so that events landing
#: exactly ON the horizon are processed rather than cut off — a unit whose
#: last operation finishes at t == horizon has been made, and a horizon is a
#: closed interval in every other part of this product's arithmetic.
#:
#: One value, read in two places, and it has to stay that way: the run stops
#: at horizon + epsilon and the trace sampler takes its terminal frame at
#: horizon + epsilon/2, so the frame is always taken after the boundary
#: events and always before the run ends. Two independent constants here
#: would let the playback counter and the verified KPI drift apart again by
#: exactly the units finishing on the boundary (G: Plan B showed 1,899 at
#: 24:00 against a verified 1,900).
#:
#: Negligible against any cycle time, and it does not lengthen the
#: production window: nothing is released after the horizon.
_HORIZON_BOUNDARY_EPSILON = 1e-6


def _rank_bottleneck(entries: list[tuple[str, float, float, int]]) -> str:
    """
    entries: (reference_machine_id, utilization, average_queue_length, stage_order).
    """

    def key(entry: tuple[str, float, float, int]) -> tuple[int, float, float, int]:
        _mid, utilization, avg_queue, order = entry
        if utilization >= _SATURATION_THRESHOLD:
            return (0, -avg_queue, -utilization, order)
        return (1, -utilization, -avg_queue, order)

    return min(entries, key=key)[0]


# Machine pool dispatcher (Phase 2B)

class _MachinePoolDispatcher:
    """
    Deterministic dispatcher for a service pool of >= 2 physical machines jointly
    serving one logical ProcessStep.
    """

    def __init__(self, machines: list[Machine]) -> None:
        # Deterministic, capacity-independent ordering used for every
        # idle-machine / tie-break decision.
        self._machines = sorted(machines, key=lambda m: m.id)
        self._used: dict[str, int] = {m.id: 0 for m in machines}
        self._pending: list[simpy.Event] = []  # FIFO, shared by the whole pool

    def _idle_machines(self) -> list[Machine]:
        return sorted(
            (m for m in self._machines if self._used[m.id] < m.capacity),
            key=lambda m: m.id,
        )

    def acquire(self, env: simpy.Environment) -> Generator[simpy.Event, None, str]:
        """Generator: grants a slot to this request."""
        grant: simpy.Event = env.event()
        self._pending.append(grant)
        self._schedule_dispatch(env)
        yield grant
        return grant.value

    def release(self, machine_id: str, env: simpy.Environment) -> None:
        """Free *machine_id*'s slot and re-evaluate the pending queue."""
        self._used[machine_id] -= 1
        self._schedule_dispatch(env)

    def _schedule_dispatch(self, env: simpy.Environment) -> None:
        def _deferred() -> Generator:
            yield env.timeout(0)
            self._try_dispatch()

        env.process(_deferred())

    def _try_dispatch(self) -> None:
        """Synchronously grant free slots to the oldest waiting requests."""
        while self._pending:
            idle = self._idle_machines()
            if not idle:
                break
            chosen = idle[0]
            grant = self._pending.pop(0)
            self._used[chosen.id] += 1
            grant.succeed(chosen.id)


# Per-route execution context

# Phase 8A: operator pool


class _OperatorPool:
    """The shared workforce, as a real finite resource."""

    def __init__(self, env: simpy.Environment, capacity: int, horizon: float) -> None:
        self.capacity = capacity
        self.horizon = horizon
        self._container = simpy.Container(env, capacity=capacity, init=capacity) if capacity > 0 else None
        self._in_use = 0
        self._samples: list[tuple[float, int]] = [(0.0, 0)]
        self.peak_in_use = 0
        self.waits: list[float] = []
        self.delayed_operations = 0

    def acquire(
        self,
        env: simpy.Environment,
        amount: int,
        trace: "_TraceRecorder | None" = None,
    ) -> Generator:
        """Acquire *amount* operators, blocking until they are free."""
        if amount <= 0 or self._container is None:
            return

        start = env.now
        request = self._container.get(amount)
        waiting_now = not request.triggered
        if waiting_now:
            self.delayed_operations += 1
            if trace is not None:
                trace.operators_waiting += 1
        yield request

        waited = env.now - start
        if waited > 0:
            self.waits.append(waited)
        self._record(env.now, self._in_use + amount)
        if waiting_now and trace is not None:
            trace.operators_waiting -= 1

    def release(self, env: simpy.Environment, amount: int) -> None:
        if amount <= 0 or self._container is None:
            return
        self._container.put(amount)
        self._record(env.now, self._in_use - amount)

    def _record(self, now: float, level: int) -> None:
        if self._samples and self._samples[-1][0] == now:
            self._samples[-1] = (now, level)
        else:
            self._samples.append((now, level))
        self._in_use = level
        self.peak_in_use = max(self.peak_in_use, level)

    def average_in_use(self) -> float:
        """Time-weighted mean, integrating the step function over the
        horizon — the same technique the queue trackers already use, so
        operator and machine numbers stay comparable."""
        if self.horizon <= 0:
            return 0.0
        samples = self._samples + [(self.horizon, self._in_use)]
        area = 0.0
        for (t0, level), (t1, _unused) in zip(samples, samples[1:]):
            span = min(t1, self.horizon) - min(t0, self.horizon)
            if span > 0:
                area += level * span
        return area / self.horizon

    def to_kpi(self, operators_required_peak: int) -> OperatorKPI:
        average = self.average_in_use()
        return OperatorKPI(
            operators_available=self.capacity,
            operators_required_peak=operators_required_peak,
            peak_operators_in_use=self.peak_in_use,
            average_operators_in_use=average,
            utilization=min(1.0, average / self.capacity) if self.capacity > 0 else 0.0,
            total_operator_wait_seconds=sum(self.waits),
            average_operator_wait_seconds=(sum(self.waits) / len(self.waits)) if self.waits else 0.0,
            max_operator_wait_seconds=max(self.waits) if self.waits else 0.0,
            operations_delayed_by_operators=self.delayed_operations,
            operator_constrained=bool(self.waits),
        )


# Phase 8A: finite buffers


class _BufferState:
    """One wired buffer between two route stages."""

    def __init__(self, env: simpy.Environment, buffer: Buffer, horizon: float) -> None:
        self.buffer = buffer
        self.horizon = horizon
        self.container = simpy.Container(env, capacity=buffer.capacity, init=0)
        self._level = 0
        self._samples: list[tuple[float, int]] = [(0.0, 0)]
        self.max_level = 0
        self.blocked_seconds = 0.0
        self.blocked_events = 0

    def put(
        self,
        env: simpy.Environment,
        trace: "_TraceRecorder | None" = None,
        unit_id: int | None = None,
        machine_id: str | None = None,
    ) -> Generator:
        """Place one finished unit."""
        start = env.now
        request = self.container.put(1)
        blocked_now = not request.triggered
        if blocked_now:
            self.blocked_events += 1
            if trace is not None:
                trace.buffer_pending_puts[self.buffer.id] = trace.buffer_pending_puts.get(self.buffer.id, 0) + 1
                if machine_id is not None:
                    trace.machine_blocked[machine_id] = True
                if unit_id is not None:
                    trace.emit(unit_id, UnitEventType.MACHINE_BLOCKED, machine_id=machine_id, buffer_id=self.buffer.id)
        yield request
        blocked = env.now - start
        if blocked > 0:
            self.blocked_seconds += blocked
        self._record(env.now, self._level + 1)
        if blocked_now and trace is not None:
            trace.buffer_pending_puts[self.buffer.id] -= 1
            if machine_id is not None:
                trace.machine_blocked[machine_id] = False
            if unit_id is not None:
                trace.emit(unit_id, UnitEventType.MACHINE_UNBLOCKED, machine_id=machine_id, buffer_id=self.buffer.id)
        if trace is not None and unit_id is not None:
            trace.emit(unit_id, UnitEventType.UNIT_ENTERED_BUFFER, buffer_id=self.buffer.id)

    def get(
        self,
        env: simpy.Environment,
        trace: "_TraceRecorder | None" = None,
        unit_id: int | None = None,
    ) -> Generator:
        yield self.container.get(1)
        self._record(env.now, self._level - 1)
        if trace is not None and unit_id is not None:
            trace.emit(unit_id, UnitEventType.UNIT_LEFT_BUFFER, buffer_id=self.buffer.id)

    def _record(self, now: float, level: int) -> None:
        if self._samples and self._samples[-1][0] == now:
            self._samples[-1] = (now, level)
        else:
            self._samples.append((now, level))
        self._level = level
        self.max_level = max(self.max_level, level)

    def _time_where(self, predicate) -> float:
        samples = self._samples + [(self.horizon, self._level)]
        total = 0.0
        for (t0, level), (t1, _unused) in zip(samples, samples[1:]):
            span = min(t1, self.horizon) - min(t0, self.horizon)
            if span > 0 and predicate(level):
                total += span
        return total

    def average_level(self) -> float:
        if self.horizon <= 0:
            return 0.0
        samples = self._samples + [(self.horizon, self._level)]
        area = 0.0
        for (t0, level), (t1, _unused) in zip(samples, samples[1:]):
            span = min(t1, self.horizon) - min(t0, self.horizon)
            if span > 0:
                area += level * span
        return area / self.horizon

    def to_kpi(self) -> BufferKPI:
        capacity = self.buffer.capacity
        time_full = self._time_where(lambda level: level >= capacity)
        time_empty = self._time_where(lambda level: level <= 0)
        average = self.average_level()
        return BufferKPI(
            buffer_id=self.buffer.id,
            buffer_name=self.buffer.name,
            capacity=capacity,
            upstream_machine_id=self.buffer.upstream_machine_id or "",
            downstream_machine_id=self.buffer.downstream_machine_id or "",
            average_level=average,
            max_level=self.max_level,
            utilization=min(1.0, average / capacity) if capacity > 0 else 0.0,
            time_full_seconds=time_full,
            time_empty_seconds=time_empty,
            full_fraction=min(1.0, time_full / self.horizon) if self.horizon > 0 else 0.0,
            empty_fraction=min(1.0, time_empty / self.horizon) if self.horizon > 0 else 0.0,
            upstream_blocked_seconds=self.blocked_seconds,
            upstream_blocked_events=self.blocked_events,
            blocking_observed=self.blocked_seconds > 0,
        )


# Phase 8C: trace recorder (only instantiated when trace_mode=PLAYBACK)


class _TraceRecorder:
    """Live, opt-in bookkeeping for one PLAYBACK-mode simulation run."""

    def __init__(
        self,
        env: simpy.Environment,
        config: TracePlaybackConfig,
        total_units: int = 0,
    ) -> None:
        self.env = env
        self.config = config
        self.events: list[UnitEvent] = []
        self._tracked_ids: set[int] = set()
        # Total units this run will release, known before the run starts
        # (``target_units``). Used ONLY to space out which units get
        # milestone events — never read by any simulation decision.
        self._total_units = max(0, total_units)
        self._stride = max(1, self._total_units // max(1, config.max_tracked_units))

        # Live gauges the periodic sampler reads. Keyed by machine_id/buffer_id.
        self.machine_processing: dict[str, int] = {}
        self.machine_blocked: dict[str, bool] = {}
        self.buffer_pending_puts: dict[str, int] = {}
        self.operators_waiting: int = 0
        self.completed_units: int = 0
        self.released_units: int = 0

        # Filled in by the sampler process as the run proceeds.
        self.machine_series: list[MachineTraceSample] = []
        self.buffer_series: list[BufferTraceSample] = []
        self.operator_series: list[OperatorTraceSample] = []
        self.system_series: list[SystemTraceSample] = []

    def is_tracked(self, unit_id: int) -> bool:
        """Whether *unit_id* gets individual milestone events."""
        if unit_id % self._stride != 0:
            return False
        return unit_id // self._stride < self.config.max_tracked_units

    def emit(
        self,
        unit_id: int,
        event_type: UnitEventType,
        machine_id: str | None = None,
        buffer_id: str | None = None,
    ) -> None:
        if not self.is_tracked(unit_id):
            return
        self._tracked_ids.add(unit_id)
        self.events.append(
            UnitEvent(
                timestamp=self.env.now,
                unit_id=unit_id,
                event_type=event_type,
                machine_id=machine_id,
                buffer_id=buffer_id,
            )
        )

    @property
    def tracked_unit_count(self) -> int:
        return len(self._tracked_ids)


@dataclass
class _RouteContext:
    """Everything a unit process needs to traverse one product's route."""

    pools: dict[str, list[Machine]]  # step.machine_id -> sorted physical machines
    resources: dict[str, simpy.Resource]  # machine_id -> resource
    stats: dict[str, _MachineStats]  # machine_id -> stats
    dispatchers: dict[str, _MachinePoolDispatcher] = field(default_factory=dict)  # step.machine_id -> dispatcher (only for pools >= 2)
    pool_stats: dict[str, _PoolStats] = field(default_factory=dict)  # step.machine_id -> pool stats (only for pools >= 2)
    # Phase 8C. None on every normal (trace_mode=NONE) run.
    trace: _TraceRecorder | None = None

    # Phase 8A Shared workforce.
    operators: "_OperatorPool | None" = None
    #: How many operators one operation at this stage consumes, by
    #: ProcessStep.machine_id. Read from the POOL's reference machine so
    #: every machine serving a stage costs the same staffing — a parallel
    #: clone is a copy of its source and inherits its operator requirement.
    operators_per_step: dict[str, int] = field(default_factory=dict)
    #: Buffer a finished unit must be placed into BEFORE the upstream
    #: machine is released, by ProcessStep.machine_id of the upstream stage.
    outbound_buffers: dict[str, "_BufferState"] = field(default_factory=dict)
    #: Buffer a unit must be drawn from once the downstream machine is
    #: acquired, by ProcessStep.machine_id of the downstream stage.
    inbound_buffers: dict[str, "_BufferState"] = field(default_factory=dict)


# Unit process

def _run_step(
    env: simpy.Environment,
    step_machine_id: str,
    cycle_time: float,
    ctx: _RouteContext,
    unit_id: int,
) -> Generator:
    """Execute one ProcessStep for one unit."""
    pool = ctx.pools[step_machine_id]
    operators_needed = ctx.operators_per_step.get(step_machine_id, 0)
    inbound = ctx.inbound_buffers.get(step_machine_id)
    outbound = ctx.outbound_buffers.get(step_machine_id)
    trace = ctx.trace

    if len(pool) == 1:
        # Byte-for-byte identical to Phase 1.2 when no operators/buffers apply.
        machine_id = pool[0].id
        resource = ctx.resources[machine_id]
        mstats = ctx.stats[machine_id]

        arrival_time = env.now
        mstats.queue_arrived(env.now)
        if trace is not None:
            trace.emit(unit_id, UnitEventType.UNIT_ENTERED_MACHINE_QUEUE, machine_id=step_machine_id)

        with resource.request() as req:
            yield req

            wait_duration = env.now - arrival_time
            mstats.queue_left(env.now)
            mstats.record_wait(wait_duration)

            if inbound is not None:
                yield from inbound.get(env, trace, unit_id)
            if ctx.operators is not None and operators_needed > 0:
                yield from ctx.operators.acquire(env, operators_needed, trace)

            if trace is not None:
                trace.emit(unit_id, UnitEventType.UNIT_STARTED_PROCESSING, machine_id=machine_id)
                trace.machine_processing[machine_id] = trace.machine_processing.get(machine_id, 0) + 1
            yield env.timeout(cycle_time)
            mstats.record_processing(cycle_time)
            if trace is not None:
                trace.machine_processing[machine_id] -= 1
                trace.emit(unit_id, UnitEventType.UNIT_FINISHED_PROCESSING, machine_id=machine_id)

            if ctx.operators is not None and operators_needed > 0:
                ctx.operators.release(env, operators_needed)
            if outbound is not None:
                yield from outbound.put(env, trace, unit_id, machine_id)
        return

    # Pooled step (>= 2 physical machines) — dispatch via the shared pool queue.
    dispatcher = ctx.dispatchers[step_machine_id]
    pstats = ctx.pool_stats[step_machine_id]

    arrival_time = env.now
    pstats.queue_arrived(env.now)
    if trace is not None:
        trace.emit(unit_id, UnitEventType.UNIT_ENTERED_MACHINE_QUEUE, machine_id=step_machine_id)

    machine_id = yield from dispatcher.acquire(env)

    wait_duration = env.now - arrival_time
    pstats.queue_left(env.now)
    pstats.record_wait(wait_duration)
    ctx.stats[machine_id].record_wait(wait_duration)

    try:
        if inbound is not None:
            yield from inbound.get(env, trace, unit_id)
        if ctx.operators is not None and operators_needed > 0:
            yield from ctx.operators.acquire(env, operators_needed, trace)

        if trace is not None:
            trace.emit(unit_id, UnitEventType.UNIT_STARTED_PROCESSING, machine_id=machine_id)
            trace.machine_processing[machine_id] = trace.machine_processing.get(machine_id, 0) + 1
        yield env.timeout(cycle_time)
        ctx.stats[machine_id].record_processing(cycle_time)
        if trace is not None:
            trace.machine_processing[machine_id] -= 1
            trace.emit(unit_id, UnitEventType.UNIT_FINISHED_PROCESSING, machine_id=machine_id)

        if ctx.operators is not None and operators_needed > 0:
            ctx.operators.release(env, operators_needed)
        if outbound is not None:
            yield from outbound.put(env, trace, unit_id, machine_id)
    finally:
        dispatcher.release(machine_id, env)


def _unit_process(
    env: simpy.Environment,
    unit_id: int,
    product: Product,
    ctx: _RouteContext,
    completed_flow_times: list[float],
    wip_counter: list[int],
    horizon: float,
) -> Generator:
    """SimPy process representing one production unit moving through the route."""
    start_time = env.now
    wip_counter[0] += 1
    if ctx.trace is not None:
        ctx.trace.released_units += 1
        ctx.trace.emit(unit_id, UnitEventType.UNIT_RELEASED)

    for step in product.route:
        cycle_time = step.cycle_time  # always from ProcessStep in Phase 1+
        yield from _run_step(env, step.machine_id, cycle_time, ctx, unit_id)

    # Unit has completed the full route
    flow_time = env.now - start_time
    completed_flow_times.append(flow_time)
    wip_counter[0] -= 1
    if ctx.trace is not None:
        ctx.trace.completed_units += 1
        ctx.trace.emit(unit_id, UnitEventType.UNIT_COMPLETED)


# Feeder process

def _feeder_process(
    env: simpy.Environment,
    product: Product,
    ctx: _RouteContext,
    completed_flow_times: list[float],
    wip_counter: list[int],
    horizon: float,
    release_interval: float,
    target_units: int,
) -> Generator:
    """Production-target source: releases exactly ``target_units`` units."""
    for unit_id in range(target_units):
        # Defensive guard: SimPy stops the env at horizon, but be explicit.
        if env.now >= horizon:
            break
        env.process(
            _unit_process(
                env, unit_id, product, ctx,
                completed_flow_times, wip_counter, horizon,
            )
        )
        # Wait release_interval before injecting the next unit.
        if unit_id < target_units - 1:
            yield env.timeout(release_interval)


# Phase 8C: periodic trace sampler (only started when trace_mode=PLAYBACK)


def _bottleneck_so_far(
    ctx: _RouteContext,
    step_order: list[str],
    now: float,
) -> str | None:
    """
    Same rule as the final ``SystemKPI.bottleneck_machine_id`` (via the shared
    ``_rank_bottleneck``), evaluated against LIVE so-far accumulators instead of final
    ones.
    """
    if not step_order:
        return None
    entries: list[tuple[str, float, float, int]] = []
    for order, step_machine_id in enumerate(step_order):
        pool_machines = ctx.pools[step_machine_id]
        machine_ids = [m.id for m in pool_machines]
        total_capacity = sum(m.capacity for m in pool_machines)
        total_busy = sum(ctx.stats[mid].busy_time for mid in machine_ids)
        utilization = (
            min(1.0, total_busy / (now * total_capacity))
            if now > 0 and total_capacity > 0
            else 0.0
        )
        qw = ctx.pool_stats.get(step_machine_id, ctx.stats[machine_ids[0]])
        avg_queue = qw.average_queue_length_up_to(now)
        entries.append((step_machine_id, utilization, avg_queue, order))
    return _rank_bottleneck(entries)


def _trace_sampler_process(
    env: simpy.Environment,
    ctx: _RouteContext,
    step_order: list[str],
    buffer_states: list[_BufferState],
    trace: _TraceRecorder,
    sample_interval: float,
    horizon: float,
) -> Generator:
    """
    Appends one sample to every series in *trace* at t=0, then every ``sample_interval``
    seconds, and always exactly at t=horizon (the loop step size is clamped so the last
    tick lands precisely on the horizon — Phase 8C section 16: seeking to 100% must
    always resolve to the true final state, never an interpolation short of it).
    """

    def sample_once(stamp: float | None = None) -> None:
        # `stamp` is the instant the frame DESCRIBES; it differs from
        # `env.now` only for the terminal frame, which is taken just after
        # the horizon so that boundary completions are included but belongs
        # to the horizon itself. Used for the utilization denominator too,
        # so the terminal frame's utilization matches the final MachineKPI
        # rather than being divided by a microsecond more elapsed time.
        now = env.now if stamp is None else stamp
        for step_machine_id in step_order:
            for m in ctx.pools[step_machine_id]:
                mstats = ctx.stats[m.id]
                utilization = (
                    min(1.0, mstats.busy_time / (now * m.capacity))
                    if now > 0 and m.capacity > 0
                    else 0.0
                )
                trace.machine_series.append(
                    MachineTraceSample(
                        timestamp=now,
                        machine_id=m.id,
                        queue_length=mstats.current_queue_depth,
                        processing_count=trace.machine_processing.get(m.id, 0),
                        blocked=trace.machine_blocked.get(m.id, False),
                        utilization_so_far=round(utilization, 6),
                    )
                )

        for bstate in buffer_states:
            trace.buffer_series.append(
                BufferTraceSample(
                    timestamp=now,
                    buffer_id=bstate.buffer.id,
                    level=bstate._level,  # noqa: SLF001 — sampler is part of the simulation module, not an external reader
                    capacity=bstate.buffer.capacity,
                    blocked_upstream=trace.buffer_pending_puts.get(bstate.buffer.id, 0) > 0,
                )
            )

        if ctx.operators is not None:
            trace.operator_series.append(
                OperatorTraceSample(
                    timestamp=now,
                    operators_in_use=ctx.operators._in_use,  # noqa: SLF001
                    operators_available=ctx.operators.capacity,
                    waiting_operations=trace.operators_waiting,
                )
            )

        trace.system_series.append(
            SystemTraceSample(
                timestamp=now,
                completed_units=trace.completed_units,
                released_units=trace.released_units,
                current_bottleneck_machine_id=_bottleneck_so_far(ctx, step_order, now),
            )
        )

    sample_once()
    while env.now < horizon:
        yield env.timeout(min(sample_interval, horizon - env.now))
        if env.now < horizon:
            sample_once()

    # The terminal frame, taken after the units finishing exactly on the
    # horizon have been processed. Half the run's own epsilon, so this
    # always resumes strictly before `env.run` stops.
    yield env.timeout(_HORIZON_BOUNDARY_EPSILON / 2)
    sample_once(stamp=horizon)


# Public entry point

# Phase 8B: opt-in, scope-local simulation memo

_SIMULATION_MEMO: ContextVar["_SimulationMemo | None"] = ContextVar("factorymind_simulation_memo", default=None)


@dataclass
class _SimulationMemo:
    """Content-keyed simulation results plus hit/run counters."""

    entries: dict[tuple[str, str], SimulationResult] = field(default_factory=dict)
    runs: int = 0
    hits: int = 0
    enabled: bool = True


@contextmanager
def simulation_memo(*, enabled: bool = True) -> "Generator[_SimulationMemo, None, None]":
    """Memoize ``run_simulation`` for the duration of this block."""
    memo = _SimulationMemo(enabled=enabled)
    token = _SIMULATION_MEMO.set(memo)
    try:
        yield memo
    finally:
        _SIMULATION_MEMO.reset(token)


def run_simulation(factory: Factory, product_id: str) -> SimulationResult:
    """Run a deterministic simulation of *product_id* through *factory*."""
    memo = _SIMULATION_MEMO.get()
    if memo is None:
        result, _trace = _run_simulation_uncached(factory, product_id)
        return result

    key = (factory.model_dump_json(), product_id)
    if memo.enabled:
        cached = memo.entries.get(key)
        if cached is not None:
            memo.hits += 1
            return cached

    memo.runs += 1
    result, _trace = _run_simulation_uncached(factory, product_id)
    if memo.enabled:
        memo.entries[key] = result
    return result


def run_simulation_traced(
    factory: Factory,
    product_id: str,
    trace_config: TracePlaybackConfig | None = None,
) -> SimulationTrace:
    """
    Run *product_id* through *factory* with a full PLAYBACK trace attached (Phase 8C).
    """
    _result, trace = _run_simulation_uncached(factory, product_id, trace_config or TracePlaybackConfig())
    assert trace is not None  # a non-None trace_config always produces one
    return trace


def _run_simulation_uncached(
    factory: Factory,
    product_id: str,
    trace_config: TracePlaybackConfig | None = None,
) -> tuple[SimulationResult, SimulationTrace | None]:
    """The real simulation."""
    # Locate product
    product_map: dict[str, Product] = {p.id: p for p in factory.products}
    if product_id not in product_map:
        raise ValueError(
            f"Product '{product_id}' not found in factory '{factory.name}'. "
            f"Available IDs: {sorted(product_map)}"
        )
    product = product_map[product_id]

    # Validate route
    result = validate_route(factory, product)
    if not result.valid:
        raise ValueError(
            f"Route validation failed for product '{product_id}':\n"
            + "\n".join(f"  • {e}" for e in result.errors)
        )

    # Simulation horizon (seconds)
    horizon_hours = factory.shifts_per_day * factory.hours_per_shift
    horizon_seconds = horizon_hours * 3600.0

    # Nominal route traversal time
    # Sum of ProcessStep cycle times — the minimum possible flow time when
    # there is no queuing.  Used to anchor the release schedule so that the
    # last unit has exactly enough nominal time to complete by the horizon.
    nominal_route_time = sum(step.cycle_time for step in product.route)

    # Infeasibility guard: if even a single unit cannot traverse the route
    # within the horizon there is nothing to simulate.
    if nominal_route_time > horizon_seconds:
        raise ValueError(
            f"Simulation infeasible for product '{product_id}': "
            f"nominal route time {nominal_route_time:.3f} s exceeds "
            f"horizon {horizon_seconds:.3f} s "
            f"(factory '{factory.name}', "
            f"{factory.shifts_per_day} shift(s) × {factory.hours_per_shift} h)."
        )

    # Production-target release schedule (Phase 1.2)
    demand_per_day = product.demand_per_day
    target_units = math.ceil(demand_per_day)
    latest_release_time = horizon_seconds - nominal_route_time
    release_interval = (
        latest_release_time / (target_units - 1)
        if target_units > 1
        else 0.0
    )

    env = simpy.Environment()

    # Resolve machine service pools (Phase 2B)
    # One pool per unique logical step, keyed by ProcessStep.machine_id, in
    # first-appearance route order (matches Phase 1.2's resource build order
    # for the common case where every pool has exactly one machine).
    pools: dict[str, list[Machine]] = {}
    for step in product.route:
        if step.machine_id not in pools:
            pools[step.machine_id] = resolve_pool(factory, step.machine_id)

    resources: dict[str, simpy.Resource] = {}
    stats: dict[str, _MachineStats] = {}
    dispatchers: dict[str, _MachinePoolDispatcher] = {}
    pool_stats: dict[str, _PoolStats] = {}

    for step_machine_id, pool_machines in pools.items():
        pooled = len(pool_machines) > 1
        for m in pool_machines:
            if m.id not in resources:
                resources[m.id] = simpy.Resource(env, capacity=m.capacity)
                stats[m.id] = _MachineStats(m, horizon_seconds, pooled=pooled)
        if pooled:
            dispatchers[step_machine_id] = _MachinePoolDispatcher(pool_machines)
            pool_stats[step_machine_id] = _PoolStats(horizon_seconds)

    # Phase 8A: workforce
    # Staffing per stage is read from the pool's REFERENCE machine: a
    # parallel clone is a copy of its source (see AddParallelMachineAction)
    # and therefore needs the same crew, and reading it once per stage keeps
    # the requirement stable no matter how the dispatcher assigns work.
    operators_per_step: dict[str, int] = {}
    for step_machine_id, pool_machines in pools.items():
        reference = next((m for m in pool_machines if m.id == step_machine_id), pool_machines[0])
        operators_per_step[step_machine_id] = reference.operators_required

    # Structural infeasibility: a stage needing more operators than exist
    # could never start, and the simulation would simply hang. Refuse up
    # front with a message that names the offender.
    needed_max = max(operators_per_step.values(), default=0)
    if needed_max > factory.operators_available:
        offenders = sorted(sid for sid, n in operators_per_step.items() if n > factory.operators_available)
        raise ValueError(
            f"Simulation infeasible for product '{product_id}': stage(s) {offenders} each require "
            f"{needed_max} operator(s), but factory '{factory.name}' has only "
            f"{factory.operators_available} available. No unit could ever start there."
        )

    operator_pool = _OperatorPool(env, factory.operators_available, horizon_seconds)

    # Phase 8A: finite buffers
    # Only buffers that EXPLICITLY name an adjacent pair of stages on THIS
    # route participate. No name parsing, no inference: a buffer that does
    # not say where it sits is inert, exactly as before Phase 8A.
    route_pairs: dict[tuple[str, str], int] = {}
    for index in range(len(product.route) - 1):
        route_pairs[(product.route[index].machine_id, product.route[index + 1].machine_id)] = index

    outbound_buffers: dict[str, _BufferState] = {}
    inbound_buffers: dict[str, _BufferState] = {}
    buffer_states: list[_BufferState] = []
    for buf in factory.buffers:
        if not buf.is_wired:
            continue
        pair = (buf.upstream_machine_id, buf.downstream_machine_id)
        if pair not in route_pairs:
            # Wired, but not between two consecutive stages of THIS product's
            # route — correct to ignore, and not an error: a factory may hold
            # buffers belonging to other products' routes.
            continue
        state = _BufferState(env, buf, horizon_seconds)
        outbound_buffers[buf.upstream_machine_id] = state
        inbound_buffers[buf.downstream_machine_id] = state
        buffer_states.append(state)

    # Phase 8C: opt-in trace recorder + step order for the sampler
    trace: _TraceRecorder | None = None
    step_order: list[str] = []
    seen_order: set[str] = set()
    for step in product.route:
        if step.machine_id not in seen_order:
            seen_order.add(step.machine_id)
            step_order.append(step.machine_id)
    if trace_config is not None:
        # target_units (computed above) is how many units the feeder will
        # release — passed in so tracked units can be spaced across the
        # whole run rather than taken from its start. Display/selection
        # only; nothing in the simulation reads it back.
        trace = _TraceRecorder(env, trace_config, total_units=target_units)

    ctx = _RouteContext(
        pools=pools,
        resources=resources,
        stats=stats,
        dispatchers=dispatchers,
        pool_stats=pool_stats,
        operators=operator_pool,
        operators_per_step=operators_per_step,
        outbound_buffers=outbound_buffers,
        inbound_buffers=inbound_buffers,
        trace=trace,
    )

    # Shared accumulators passed by reference to unit processes
    completed_flow_times: list[float] = []
    wip_counter: list[int] = [0]  # mutable single-element list

    env.process(
        _feeder_process(
            env, product, ctx,
            completed_flow_times, wip_counter, horizon_seconds,
            release_interval, target_units,
        )
    )
    sample_interval = 1.0
    if trace is not None:
        sample_interval = max(1.0, horizon_seconds / trace_config.sample_count_target)
        env.process(
            _trace_sampler_process(
                env, ctx, step_order, buffer_states, trace, sample_interval, horizon_seconds,
            )
        )
    # scheduled at exactly t == horizon_seconds (e.g.
    env.run(until=horizon_seconds + _HORIZON_BOUNDARY_EPSILON)

    # Per-machine KPIs, in route order.
    machine_kpis: list[MachineKPI] = []
    seen_steps: set[str] = set()
    for step in product.route:
        if step.machine_id in seen_steps:
            continue
        seen_steps.add(step.machine_id)
        for m in pools[step.machine_id]:
            machine_kpis.append(stats[m.id].to_kpi())

    # Derive per-logical-stage pool KPIs (route order)
    process_pool_kpis: list[ProcessPoolKPI] = []
    seen_steps = set()
    for step in product.route:
        if step.machine_id in seen_steps:
            continue
        seen_steps.add(step.machine_id)

        pool_machines = pools[step.machine_id]
        machine_ids = [m.id for m in pool_machines]
        total_capacity = sum(m.capacity for m in pool_machines)
        total_busy = sum(stats[mid].busy_time for mid in machine_ids)
        total_processed = sum(stats[mid].processed_units for mid in machine_ids)
        utilization = (
            min(1.0, total_busy / (horizon_seconds * total_capacity))
            if horizon_seconds > 0 and total_capacity > 0
            else 0.0
        )

        if step.machine_id in pool_stats:
            qw = pool_stats[step.machine_id]
        else:
            # Singleton pool: reuse the one machine's own queue/wait tracker
            # verbatim so pool-level and per-machine numbers agree exactly.
            qw = stats[machine_ids[0]]

        process_pool_kpis.append(
            ProcessPoolKPI(
                process_step_name=step.name,
                reference_machine_id=step.machine_id,
                machine_ids=machine_ids,
                processed_units=total_processed,
                utilization=round(utilization, 6),
                average_queue_length=round(qw.average_queue_length, 6),
                max_queue_length=qw.max_queue_length,
                average_wait_time_seconds=round(qw.average_wait_time, 6),
                max_wait_time_seconds=round(qw.max_wait_time, 6),
            )
        )

    completed_units = len(completed_flow_times)
    avg_flow = (sum(completed_flow_times) / completed_units
                if completed_units > 0 else 0.0)
    max_flow = max(completed_flow_times, default=0.0)

    # WIP: units that were started but have not yet completed
    wip = wip_counter[0]

    # Bottleneck: highest utilization *at the logical-stage (pool) level* —
    # so a step split across several parallel machines is judged by its
    # combined congestion, not any single clone's individual utilization.
    #
    # Subtlety (found via the real 1900/day demo, Phase 6C.1 closure
    # audit): the release schedule is demand/horizon-driven, not
    # bottleneck-paced (see this module's docstring), so when demand is
    # pushed high enough, the release rate can exceed MULTIPLE stages'
    # service rates at once — not just the true rate-limiting stage.
    # Every such stage ends up individually "saturated" (busy ~100% of the
    # horizon), and raw utilization can no longer reliably rank them: the
    # schedule from t=0 with zero start-up latency, so it can edge out a
    # downstream stage's utilization by a fraction of a percent even while
    # that downstream stage is far more severely congested (bigger,
    # faster-growing queue and wait time). Concretely, at 1900 units/day on
    # the example line: Assembly (util 0.999566) narrowly "beat"
    # Screwdriving (util 0.999375) despite Screwdriving's average queue and
    # wait both being ~2x worse.
    #
    # So: among stages that are effectively saturated (utilization at/above
    # _SATURATION_THRESHOLD), rank by average queue length instead — that
    # directly measures which stage's own service rate is falling behind
    # its (already-throttled-by-upstream) actual arrival rate, the real
    # engineering definition of "the bottleneck". Only fall back to
    # ranking by raw utilization when nothing is saturated. Final tie-break
    # is stage order in the product route (mirrors Phase 1.2's "machine
    # order in the factory definition" tie-break, generalised to logical
    # stages). Shared with the Phase 8C live trace sampler via
    # ``_rank_bottleneck`` — see that function's docstring.
    bottleneck_id = _rank_bottleneck(
        [(p.reference_machine_id, p.utilization, p.average_queue_length, i) for i, p in enumerate(process_pool_kpis)]
    )

    # Global throughput
    throughput_per_hour = completed_units / horizon_hours if horizon_hours > 0 else 0.0

    # Demand comparison demand_met: True iff every target unit completed the full route.
    demand_met = completed_units >= target_units
    demand_gap = max(target_units - completed_units, 0)

    system = SystemKPI(
        average_flow_time_seconds=round(avg_flow, 6),
        max_flow_time_seconds=round(max_flow, 6),
        work_in_progress=wip,
        bottleneck_machine_id=bottleneck_id,
    )

    final_result = SimulationResult(
        simulation_time_seconds=horizon_seconds,
        target_units=target_units,
        nominal_route_time_seconds=round(nominal_route_time, 6),
        release_interval_seconds=round(release_interval, 6),
        completed_units=completed_units,
        throughput_per_hour=round(throughput_per_hour, 6),
        demand_per_day=demand_per_day,
        demand_met=demand_met,
        demand_gap_units=float(demand_gap),
        machine_kpis=machine_kpis,
        system=system,
        process_pool_kpis=process_pool_kpis,
        operator_kpi=operator_pool.to_kpi(operators_required_peak=sum(operators_per_step.values())),
        buffer_kpis=[state.to_kpi() for state in buffer_states],
    )

    if trace is None:
        return final_result, None

    # Phase 8C: assemble the typed SimulationTrace
    simulation_trace = SimulationTrace(
        horizon_seconds=horizon_seconds,
        sampled_interval_seconds=sample_interval,
        config=trace_config,
        events=trace.events,
        machine_series=trace.machine_series,
        buffer_series=trace.buffer_series,
        operator_series=trace.operator_series,
        system_series=trace.system_series,
        story_markers=[],  # filled in below, once the full series exist
        tracked_unit_count=trace.tracked_unit_count,
        total_unit_count=target_units,
        summary=final_result,
        metadata={"factory": factory.name, "product_id": product_id, "product_name": product.name},
    )
    simulation_trace = simulation_trace.model_copy(
        update={"story_markers": derive_story_markers(simulation_trace)}
    )
    return final_result, simulation_trace
