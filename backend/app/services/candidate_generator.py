"""Deterministic optimization candidate generator for Fabrivium Phase 4A."""

from __future__ import annotations

from app.models.factory import Factory, Machine
from app.models.layout import FactoryLayout
from app.models.optimization import GenerationSource, OptimizationCandidate, OptimizationGoal, OptimizationObjective
from app.models.scenario import (
    AddParallelMachineAction,
    ChangeBufferCapacityAction,
    ChangeOperatorCapacityAction,
    ChangeShiftConfigurationAction,
    ChangeMachineCapacityAction,
    ChangeMachineCycleTimeAction,
    Scenario,
)
from app.models.simulation import ProcessPoolKPI, SimulationResult
from app.services.machine_pool import MachinePoolError, resolve_pool
from app.services.simulation import run_simulation


#: Minimum time-weighted average queue length (units) for a process pool to
#: be considered genuinely congested, as opposed to merely "busiest of an
#: otherwise-clear system". See module docstring.
CONGESTION_QUEUE_THRESHOLD = 0.5

# Phase 8A.
BLOCKED_STAGE_UTILIZATION_FLOOR = 0.95

#: Hypothetical cycle-time reductions to propose for each congested pool's
#: reference machine, in generation order.
CYCLE_TIME_IMPROVEMENT_PERCENTAGES: tuple[int, ...] = (5, 10, 20)

#: Minimum baseline utilization for a SECOND pool to be treated as "likely
#: to become the next constraint" once the primary bottleneck is relieved,
#: for the purposes of proposing a COMBINED candidate. This is a baseline-
#: only heuristic — Phase 4A never simulates the primary action to check
#: what the new bottleneck would actually be (that belongs to a later
#: ranking phase).
COMBINED_SECOND_POOL_UTILIZATION_THRESHOLD = 0.5


# Public entry point

# How many extra operators to offer when the workforce is the constraint.
OPERATOR_INCREMENTS = (2, 4)


def generate_candidates(
    factory: Factory,
    product_id: str,
    goal: OptimizationGoal,
    layout: FactoryLayout | None = None,
) -> list[OptimizationCandidate]:
    """
    Generate a deterministic set of candidate ``Scenario`` objects for *factory* against
    *goal*.
    """
    if product_id != goal.target_product_id:
        raise ValueError(
            f"product_id '{product_id}' does not match "
            f"goal.target_product_id '{goal.target_product_id}'."
        )

    baseline = run_simulation(factory, product_id)
    machine_index: dict[str, Machine] = {m.id: m for m in factory.machines}
    forbidden_ids = _expand_forbidden_machine_ids(factory, goal.forbidden_machine_ids)

    congested_pools = _congested_pools(baseline) if _objective_requires_relief(baseline, goal.objective) else []

    candidates: list[OptimizationCandidate] = []
    seen_keys: set[tuple] = set()

    # A. ADD_PARALLEL_MACHINE
    for pool in congested_pools:
        _maybe_add(
            candidates, seen_keys, goal, forbidden_ids,
            _add_parallel_candidate(baseline, pool, machine_index),
        )

    # B.
    _maybe_add(candidates, seen_keys, goal, forbidden_ids, _shift_candidate(factory, baseline, goal))
    for extra in OPERATOR_INCREMENTS:
        _maybe_add(candidates, seen_keys, goal, forbidden_ids, _operator_candidate(factory, baseline, goal, extra))
    _maybe_add(candidates, seen_keys, goal, forbidden_ids, _buffer_candidate(factory, baseline, goal))

    # C. CHANGE_MACHINE_CYCLE_TIME (-5% / -10% / -20%)
    for pool in congested_pools:
        for pct in CYCLE_TIME_IMPROVEMENT_PERCENTAGES:
            _maybe_add(
                candidates, seen_keys, goal, forbidden_ids,
                _cycle_time_candidate(baseline, pool, machine_index, pct),
            )

    # D. CHANGE_MACHINE_CAPACITY (+1)
    for pool in congested_pools:
        _maybe_add(
            candidates, seen_keys, goal, forbidden_ids,
            _capacity_candidate(baseline, pool, machine_index),
        )

    # E.
    combined = _combined_candidate(baseline, congested_pools, machine_index)
    _maybe_add(candidates, seen_keys, goal, forbidden_ids, combined)

    return candidates[: goal.max_candidates]


# Phase 8A — non-machine levers, strictly evidence-gated The rule that matters here
# (Phase 8A section 18):

# Adding a shift is only sensible while there is room in the day.
MAX_PRODUCTION_HOURS_PER_DAY = 24.0

#: A buffer must be full-and-blocking for at least this fraction of the
#: horizon before enlarging it is worth simulating. Blocking that lasts a
#: rounding error is not a capacity problem.
BUFFER_BLOCKING_FRACTION_THRESHOLD = 0.01

#: Operator utilisation above this, combined with observed waiting, is what
#: counts as a workforce constraint.
OPERATOR_UTILIZATION_THRESHOLD = 0.85


def _shift_candidate(
    factory: Factory, baseline: SimulationResult, goal: OptimizationGoal
) -> OptimizationCandidate | None:
    """Propose one extra shift."""
    if goal.objective is not OptimizationObjective.MEET_DEMAND:
        return None
    if baseline.demand_met:
        return None

    current_hours = factory.shifts_per_day * factory.hours_per_shift
    new_shifts = factory.shifts_per_day + 1
    if new_shifts * factory.hours_per_shift > MAX_PRODUCTION_HOURS_PER_DAY:
        return None

    new_hours = new_shifts * factory.hours_per_shift
    scenario = Scenario(
        id=f"cand-add-shift-{new_shifts}",
        name=f"Run {new_shifts} shifts per day",
        description=f"Increase from {factory.shifts_per_day} to {new_shifts} shifts of {factory.hours_per_shift:g} h.",
        actions=[ChangeShiftConfigurationAction(shifts_per_day=new_shifts)],
    )
    return OptimizationCandidate(
        candidate_id=scenario.id,
        scenario=scenario,
        rationale=(
            f"Demand is short by {baseline.demand_gap_units:g} units/day. Extending production time "
            f"from {current_hours:g} h to {new_hours:g} h per day gives the existing line more time to "
            f"reach the daily target without buying equipment. Operating cost is not known."
        ),
        generation_source=GenerationSource.SHIFT_EXPANSION,
        estimated_capex=0.0,
        requires_cost_estimate=True,
        requires_layout_placement=False,
    )


def _operator_candidate(
    factory: Factory, baseline: SimulationResult, goal: OptimizationGoal, extra: int
) -> OptimizationCandidate | None:
    """Propose hiring *extra* operators."""
    kpi = baseline.operator_kpi
    if kpi is None or not kpi.operator_constrained:
        return None
    if kpi.utilization < OPERATOR_UTILIZATION_THRESHOLD:
        return None
    if goal.max_additional_operators is not None and extra > goal.max_additional_operators:
        return None

    new_total = kpi.operators_available + extra
    scenario = Scenario(
        id=f"cand-add-operators-{extra}",
        name=f"Add {extra} operator{'s' if extra != 1 else ''}",
        description=f"Increase the workforce from {kpi.operators_available} to {new_total} operators.",
        actions=[ChangeOperatorCapacityAction(operators_available=new_total)],
    )
    return OptimizationCandidate(
        candidate_id=scenario.id,
        scenario=scenario,
        rationale=(
            f"Operators were the binding constraint in the baseline: {kpi.operations_delayed_by_operators} "
            f"operation(s) waited for staff (mean {kpi.average_operator_wait_seconds:.1f} s) at "
            f"{kpi.utilization:.0%} workforce utilisation. Raising the pool to {new_total} lets machines "
            f"that are already installed actually run. Labour cost is not known."
        ),
        generation_source=GenerationSource.OPERATOR_EXPANSION,
        estimated_capex=0.0,
        requires_cost_estimate=True,
        requires_layout_placement=False,
    )


def _buffer_candidate(
    factory: Factory, baseline: SimulationResult, goal: OptimizationGoal
) -> OptimizationCandidate | None:
    """Propose enlarging the single worst blocking buffer."""
    bottleneck = baseline.system.bottleneck_machine_id
    blocking = [
        kpi for kpi in baseline.buffer_kpis
        if kpi.blocking_observed
        and kpi.full_fraction >= BUFFER_BLOCKING_FRACTION_THRESHOLD
        # THE decisive gate.
        and kpi.downstream_machine_id != bottleneck
    ]
    if not blocking:
        return None

    worst = max(blocking, key=lambda k: (k.upstream_blocked_seconds, k.full_fraction, k.buffer_id))
    new_capacity = worst.capacity * 2
    scenario = Scenario(
        id=f"cand-buffer-{worst.buffer_id}-{new_capacity}",
        name=f"Double {worst.buffer_name} to {new_capacity}",
        description=f"Increase buffer '{worst.buffer_id}' from {worst.capacity} to {new_capacity} units.",
        actions=[ChangeBufferCapacityAction(buffer_id=worst.buffer_id, new_capacity=new_capacity)],
    )
    return OptimizationCandidate(
        candidate_id=scenario.id,
        scenario=scenario,
        rationale=(
            f"'{worst.buffer_name}' was full for {worst.full_fraction:.0%} of the horizon and blocked its "
            f"upstream machine for {worst.upstream_blocked_seconds:.0f} s across "
            f"{worst.upstream_blocked_events} event(s). Decoupling the two stages with more storage may "
            f"recover that lost upstream time. Installation cost is not known."
        ),
        generation_source=GenerationSource.BUFFER_EXPANSION,
        estimated_capex=0.0,
        requires_cost_estimate=True,
        requires_layout_placement=False,
    )


def _expand_forbidden_machine_ids(factory: Factory, forbidden_ids: list[str]) -> frozenset[str]:
    """
    Expand each id in *forbidden_ids* to the full set of physical machine ids no
    candidate action may ever target — using existing machine-pool relationships
    (``app.services.machine_pool.resolve_pool`` / ``Machine.parallel_of_machine_id``),
    never string-name inference (Phase 5A.1 section 2).
    """
    machine_index = {m.id: m for m in factory.machines}
    expanded: set[str] = set()
    for forbidden_id in forbidden_ids:
        machine = machine_index.get(forbidden_id)
        if machine is None:
            expanded.add(forbidden_id)
            continue
        if machine.parallel_of_machine_id is None:
            try:
                pool = resolve_pool(factory, forbidden_id)
                expanded.update(m.id for m in pool)
            except MachinePoolError:  # pragma: no cover - defensive; machine is known to exist
                expanded.add(forbidden_id)
        else:
            expanded.add(forbidden_id)
    return frozenset(expanded)


# Baseline analysis

def _objective_requires_relief(baseline: SimulationResult, objective: OptimizationObjective) -> bool:
    if objective == OptimizationObjective.MEET_DEMAND:
        # Nothing left to fix for THIS objective once demand is already met
        # — see the low-demand control (Phase 4A section 10).
        return not baseline.demand_met
    return True


def _congested_pools(baseline: SimulationResult) -> list[ProcessPoolKPI]:
    """Stages whose OWN service rate is the binding constraint."""
    blocked_upstream = {
        kpi.upstream_machine_id for kpi in baseline.buffer_kpis if kpi.blocking_observed
    }

    congested = [
        pool for pool in baseline.process_pool_kpis
        if pool.average_queue_length > CONGESTION_QUEUE_THRESHOLD
        and not (
            pool.reference_machine_id in blocked_upstream
            and pool.utilization < BLOCKED_STAGE_UTILIZATION_FLOOR
        )
    ]
    return sorted(congested, key=lambda p: (-p.average_queue_length, -p.utilization, p.reference_machine_id))


# Candidate builders

def _bottleneck_phrase(baseline: SimulationResult, pool: ProcessPoolKPI) -> str:
    if pool.reference_machine_id == baseline.system.bottleneck_machine_id:
        return "the baseline bottleneck"
    return "a congested baseline process"


def _add_parallel_candidate(
    baseline: SimulationResult, pool: ProcessPoolKPI, machine_index: dict[str, Machine]
) -> OptimizationCandidate | None:
    source = machine_index.get(pool.reference_machine_id)
    if source is None:
        return None  # pragma: no cover - defensive; pool root always exists

    candidate_id = f"cand-add-parallel-{pool.reference_machine_id}"
    action = AddParallelMachineAction(machine_id=pool.reference_machine_id)
    scenario = Scenario(
        id=candidate_id,
        name=f"Add parallel machine at {pool.process_step_name}",
        description=f"Clone {source.name} to relieve congestion at {pool.process_step_name}.",
        actions=[action],
    )
    rationale = (
        f"Generated because {pool.process_step_name} is {_bottleneck_phrase(baseline, pool)} "
        f"with {pool.utilization * 100:.2f}% utilization and {pool.average_queue_length:.2f} "
        f"average queue length."
    )
    return OptimizationCandidate(
        candidate_id=candidate_id,
        scenario=scenario,
        rationale=rationale,
        generation_source=GenerationSource.BOTTLENECK_RELIEF,
        # An unpriced source machine makes this an unknown-cost action, which
        # the model already knows how to express: the known portion is 0.0 and
        # `requires_cost_estimate` says the figure is incomplete. Passing the
        # price straight through would report "this costs nothing".
        estimated_capex=source.purchase_cost if source.purchase_cost is not None else 0.0,
        requires_cost_estimate=source.purchase_cost is None,
        requires_layout_placement=True,
        affected_processes=[pool.reference_machine_id],
    )


def _cycle_time_candidate(
    baseline: SimulationResult, pool: ProcessPoolKPI, machine_index: dict[str, Machine], pct: int
) -> OptimizationCandidate | None:
    source = machine_index.get(pool.reference_machine_id)
    if source is None:
        return None  # pragma: no cover - defensive

    new_cycle_time = round(source.cycle_time * (1 - pct / 100.0), 4)
    if new_cycle_time <= 0:
        return None  # would be an invalid ScenarioAction; skip rather than crash

    candidate_id = f"cand-cycle-time-{pool.reference_machine_id}-neg{pct}pct"
    action = ChangeMachineCycleTimeAction(machine_id=pool.reference_machine_id, cycle_time=new_cycle_time)
    scenario = Scenario(
        id=candidate_id,
        name=f"{pct}% cycle-time improvement at {pool.process_step_name}",
        description=f"Hypothetical engineering improvement — not a costed proposal.",
        actions=[action],
    )
    rationale = (
        f"Generated as a hypothetical {pct}% cycle-time improvement "
        f"({source.cycle_time:g}s -> {new_cycle_time:g}s) for {pool.process_step_name}, "
        f"{_bottleneck_phrase(baseline, pool)} ({pool.utilization * 100:.2f}% utilization, "
        f"{pool.average_wait_time_seconds:.2f}s average wait). Cost impact is not yet "
        f"estimated (requires_cost_estimate=True)."
    )
    return OptimizationCandidate(
        candidate_id=candidate_id,
        scenario=scenario,
        rationale=rationale,
        generation_source=GenerationSource.CYCLE_TIME_IMPROVEMENT,
        estimated_capex=0.0,
        requires_cost_estimate=True,
        requires_layout_placement=False,
        affected_processes=[pool.reference_machine_id],
    )


def _capacity_candidate(
    baseline: SimulationResult, pool: ProcessPoolKPI, machine_index: dict[str, Machine]
) -> OptimizationCandidate | None:
    source = machine_index.get(pool.reference_machine_id)
    if source is None:
        return None  # pragma: no cover - defensive

    new_capacity = source.capacity + 1
    candidate_id = f"cand-capacity-{pool.reference_machine_id}-plus1"
    action = ChangeMachineCapacityAction(machine_id=pool.reference_machine_id, capacity=new_capacity)
    scenario = Scenario(
        id=candidate_id,
        name=f"Capacity +1 at {pool.process_step_name}",
        description="Hypothetical engineering improvement — not a costed proposal.",
        actions=[action],
    )
    rationale = (
        f"Generated as a capacity increase ({source.capacity} -> {new_capacity}) for "
        f"{pool.process_step_name}, {_bottleneck_phrase(baseline, pool)} "
        f"({pool.utilization * 100:.2f}% utilization). Cost impact is not yet estimated "
        f"(requires_cost_estimate=True)."
    )
    return OptimizationCandidate(
        candidate_id=candidate_id,
        scenario=scenario,
        rationale=rationale,
        generation_source=GenerationSource.CAPACITY_EXPANSION,
        estimated_capex=0.0,
        requires_cost_estimate=True,
        requires_layout_placement=False,
        affected_processes=[pool.reference_machine_id],
    )


def _combined_candidate(
    baseline: SimulationResult,
    congested_pools: list[ProcessPoolKPI],
    machine_index: dict[str, Machine],
) -> OptimizationCandidate | None:
    """
    ADD_PARALLEL_MACHINE at the primary (most-congested) pool, plus a hypothetical -10%
    cycle-time improvement at whichever OTHER pool has the next-highest baseline
    utilization — a deterministic proxy for "the process likely to become the new
    bottleneck", per the module docstring.
    """
    if not congested_pools:
        return None

    primary = congested_pools[0]
    all_pools_by_util = sorted(
        baseline.process_pool_kpis, key=lambda p: (-p.utilization, p.reference_machine_id)
    )
    secondary = next(
        (p for p in all_pools_by_util if p.reference_machine_id != primary.reference_machine_id), None
    )
    if secondary is None or secondary.utilization < COMBINED_SECOND_POOL_UTILIZATION_THRESHOLD:
        return None

    primary_source = machine_index.get(primary.reference_machine_id)
    secondary_source = machine_index.get(secondary.reference_machine_id)
    if primary_source is None or secondary_source is None:
        return None  # pragma: no cover - defensive

    pct = 10
    new_cycle_time = round(secondary_source.cycle_time * (1 - pct / 100.0), 4)
    if new_cycle_time <= 0:
        return None

    candidate_id = f"cand-combined-{primary.reference_machine_id}-{secondary.reference_machine_id}"
    actions = [
        AddParallelMachineAction(machine_id=primary.reference_machine_id),
        ChangeMachineCycleTimeAction(machine_id=secondary.reference_machine_id, cycle_time=new_cycle_time),
    ]
    scenario = Scenario(
        id=candidate_id,
        name=f"Add parallel {primary.process_step_name} + improve {secondary.process_step_name}",
        description="Combined candidate: primary bottleneck relief plus a hypothetical improvement at the next-likely constraint.",
        actions=actions,
    )
    rationale = (
        f"Generated because relieving {primary.process_step_name} "
        f"({_bottleneck_phrase(baseline, primary)}, {primary.utilization * 100:.2f}% utilization) "
        f"would likely expose {secondary.process_step_name} (baseline utilization "
        f"{secondary.utilization * 100:.2f}%) as the next constraint; combines adding a "
        f"parallel machine at {primary.process_step_name} with a hypothetical {pct}% "
        f"cycle-time improvement at {secondary.process_step_name}."
    )
    return OptimizationCandidate(
        candidate_id=candidate_id,
        scenario=scenario,
        rationale=rationale,
        generation_source=GenerationSource.COMBINED,
        # Already declared incomplete; the known portion is the priced part
        # only, and is 0.0 when even that is unknown.
        estimated_capex=primary_source.purchase_cost if primary_source.purchase_cost is not None else 0.0,
        requires_cost_estimate=True,
        requires_layout_placement=True,
        affected_processes=[primary.reference_machine_id, secondary.reference_machine_id],
    )


# Filtering / dedup

def _dedup_key(candidate: OptimizationCandidate) -> tuple:
    parts: list[tuple] = []
    for action in candidate.scenario.actions:
        if action.action_type == "ADD_PARALLEL_MACHINE":
            parts.append(("ADD_PARALLEL_MACHINE", action.machine_id))
        elif action.action_type == "CHANGE_MACHINE_CYCLE_TIME":
            parts.append(("CHANGE_MACHINE_CYCLE_TIME", action.machine_id, round(action.cycle_time, 6)))
        elif action.action_type == "CHANGE_MACHINE_CAPACITY":
            parts.append(("CHANGE_MACHINE_CAPACITY", action.machine_id, action.capacity))
        else:  # pragma: no cover - Phase 4A never generates other action types
            parts.append((action.action_type, getattr(action, "machine_id", None)))
    return tuple(parts)


def _maybe_add(
    candidates: list[OptimizationCandidate],
    seen_keys: set[tuple],
    goal: OptimizationGoal,
    forbidden_ids: frozenset[str],
    candidate: OptimizationCandidate | None,
) -> None:
    if candidate is None:
        return

    action_machine_ids = {getattr(a, "machine_id", None) for a in candidate.scenario.actions}
    action_machine_ids.discard(None)
    if action_machine_ids & forbidden_ids:
        # No silent redirection to a different machine (Phase 5A.1 section 1)
        # — the candidate is simply never produced.
        return

    action_types = [a.action_type for a in candidate.scenario.actions]
    if goal.allowed_action_types is not None and not all(t in goal.allowed_action_types for t in action_types):
        return

    new_machine_count = sum(1 for t in action_types if t == "ADD_PARALLEL_MACHINE")
    if goal.max_additional_machines is not None and new_machine_count > goal.max_additional_machines:
        return

    if goal.max_capex is not None and candidate.estimated_capex > goal.max_capex:
        return

    key = _dedup_key(candidate)
    if key in seen_keys:
        return

    seen_keys.add(key)
    candidates.append(candidate)
