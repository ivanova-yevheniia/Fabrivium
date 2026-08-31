"""Pure comparison engine for Fabrivium Phase 2C."""

from __future__ import annotations

from app.models.comparison import (
    ProcessPoolComparison,
    ScenarioComparison,
    ScenarioComparisonKind,
    Verdict,
)
from app.models.factory import Factory
from app.models.scenario import AddParallelMachineAction, ChangeDemandAction, Scenario
from app.models.simulation import SimulationResult
from app.services.scenario import apply_scenario

# Numerical tolerances (documented, fixed — never tuned per-scenario)

#: Absolute tolerance (units) below which two demand-gap or completed-unit
#: counts are treated as "effectively equal" for verdict purposes. Both
#: quantities are whole numbers in practice, so this only guards against
#: floating-point noise.
UNIT_TOLERANCE = 0.5

#: Absolute tolerance (seconds) below which two average-flow-time values are
#: treated as "effectively equal" for verdict purposes.
FLOW_TIME_TOLERANCE_SECONDS = 1.0


# Safe percent-change helper

def _safe_percent_change(before: float, after: float) -> float | None:
    """(after - before) / before * 100, with explicit zero handling."""
    if before == 0:
        return 0.0 if after == 0 else None
    return (after - before) / before * 100.0


# CAPEX

def calculate_capex_delta(factory: Factory, scenario: Scenario) -> float | None:
    """Sum CAPEX for *scenario*'s actions against *factory*, per Phase 2C rules:"""
    capex = 0.0
    state = factory
    for action in scenario.actions:
        if isinstance(action, AddParallelMachineAction):
            source = next((m for m in state.machines if m.id == action.machine_id), None)
            if source is not None:
                if source.purchase_cost is None:
                    # The machine exists but nobody has priced it.
                    return None
                capex += source.purchase_cost
        state = apply_scenario(
            state, Scenario(id="_capex_walk", name="_capex_walk", actions=[action])
        )
    return capex


# Comparison kind

def determine_comparison_kind(scenario: Scenario) -> ScenarioComparisonKind:
    """
    Classify *scenario* by whether it changes the planning requirement (CHANGE_DEMAND)
    versus the factory's engineering configuration (every other action type).
    """
    has_demand_change = any(isinstance(a, ChangeDemandAction) for a in scenario.actions)
    has_engineering_change = any(not isinstance(a, ChangeDemandAction) for a in scenario.actions)

    if has_demand_change and has_engineering_change:
        return ScenarioComparisonKind.MIXED_CHANGE
    if has_demand_change:
        return ScenarioComparisonKind.REQUIREMENT_CHANGE
    return ScenarioComparisonKind.ENGINEERING_CHANGE


# Per-pool comparison

def _compare_pools(
    baseline: SimulationResult, candidate: SimulationResult
) -> list[ProcessPoolComparison]:
    """
    Match baseline/candidate process_pool_kpis by reference_machine_id (stable across a
    scenario — routes are never modified) and compute before/after/delta for each.
    """
    baseline_map = {p.reference_machine_id: p for p in baseline.process_pool_kpis}
    comparisons: list[ProcessPoolComparison] = []
    for cand_pool in candidate.process_pool_kpis:
        base_pool = baseline_map.get(cand_pool.reference_machine_id)
        if base_pool is None:
            continue
        comparisons.append(
            ProcessPoolComparison(
                reference_machine_id=cand_pool.reference_machine_id,
                process_step_name=cand_pool.process_step_name,
                machine_ids_before=base_pool.machine_ids,
                machine_ids_after=cand_pool.machine_ids,
                utilization_before=base_pool.utilization,
                utilization_after=cand_pool.utilization,
                utilization_delta=round(cand_pool.utilization - base_pool.utilization, 6),
                average_queue_before=base_pool.average_queue_length,
                average_queue_after=cand_pool.average_queue_length,
                average_queue_delta=round(
                    cand_pool.average_queue_length - base_pool.average_queue_length, 6
                ),
                max_queue_before=base_pool.max_queue_length,
                max_queue_after=cand_pool.max_queue_length,
                average_wait_before=base_pool.average_wait_time_seconds,
                average_wait_after=cand_pool.average_wait_time_seconds,
                average_wait_delta=round(
                    cand_pool.average_wait_time_seconds - base_pool.average_wait_time_seconds, 6
                ),
            )
        )
    return comparisons


# compare_results

def compare_results(
    baseline: SimulationResult,
    candidate: SimulationResult,
    scenario: Scenario,
    capex_delta: float | None,
) -> ScenarioComparison:
    """
    Pure function: baseline + candidate ``SimulationResult`` -> ``ScenarioComparison``.
    """
    throughput_percent_change = _safe_percent_change(
        baseline.throughput_per_hour, candidate.throughput_per_hour
    )
    average_flow_time_percent_change = _safe_percent_change(
        baseline.system.average_flow_time_seconds, candidate.system.average_flow_time_seconds
    )

    return ScenarioComparison(
        comparison_kind=determine_comparison_kind(scenario),
        baseline_target_units=baseline.target_units,
        candidate_target_units=candidate.target_units,
        target_units_changed=baseline.target_units != candidate.target_units,
        demand_met_before=baseline.demand_met,
        demand_met_after=candidate.demand_met,
        demand_gap_units_before=baseline.demand_gap_units,
        demand_gap_units_after=candidate.demand_gap_units,
        demand_gap_delta=round(candidate.demand_gap_units - baseline.demand_gap_units, 6),
        completed_units_before=baseline.completed_units,
        completed_units_after=candidate.completed_units,
        completed_units_delta=candidate.completed_units - baseline.completed_units,
        throughput_per_hour_delta=round(
            candidate.throughput_per_hour - baseline.throughput_per_hour, 6
        ),
        throughput_percent_change=(
            round(throughput_percent_change, 6) if throughput_percent_change is not None else None
        ),
        wip_before=baseline.system.work_in_progress,
        wip_after=candidate.system.work_in_progress,
        wip_delta=candidate.system.work_in_progress - baseline.system.work_in_progress,
        average_flow_time_before_seconds=baseline.system.average_flow_time_seconds,
        average_flow_time_after_seconds=candidate.system.average_flow_time_seconds,
        average_flow_time_delta_seconds=round(
            candidate.system.average_flow_time_seconds - baseline.system.average_flow_time_seconds, 6
        ),
        average_flow_time_percent_change=(
            round(average_flow_time_percent_change, 6)
            if average_flow_time_percent_change is not None
            else None
        ),
        bottleneck_before=baseline.system.bottleneck_machine_id,
        bottleneck_after=candidate.system.bottleneck_machine_id,
        bottleneck_changed=(
            baseline.system.bottleneck_machine_id != candidate.system.bottleneck_machine_id
        ),
        capex_delta=round(capex_delta, 6) if capex_delta is not None else None,
        process_pool_comparisons=_compare_pools(baseline, candidate),
    )


# Verdict reason formatting helpers

def _fmt(x: float) -> str:
    """Format a number for a human-readable reason string, dropping a
    trailing '.0' for whole numbers."""
    return f"{x:g}"


def _gap_reason(comparison: ScenarioComparison) -> str:
    direction = "decreased" if comparison.demand_gap_delta < 0 else "increased"
    return (
        f"Demand gap {direction} from {_fmt(comparison.demand_gap_units_before)} to "
        f"{_fmt(comparison.demand_gap_units_after)} units."
    )


def _wip_reason(comparison: ScenarioComparison) -> str | None:
    if comparison.wip_delta == 0:
        return None
    direction = "decreased" if comparison.wip_delta < 0 else "increased"
    return f"WIP {direction} from {comparison.wip_before} to {comparison.wip_after} units."


def _flow_reason(comparison: ScenarioComparison) -> str | None:
    if abs(comparison.average_flow_time_delta_seconds) <= FLOW_TIME_TOLERANCE_SECONDS:
        return None
    direction = "decreased" if comparison.average_flow_time_delta_seconds < 0 else "increased"
    return (
        f"Average flow time {direction} from "
        f"{_fmt(comparison.average_flow_time_before_seconds)} to "
        f"{_fmt(comparison.average_flow_time_after_seconds)} seconds."
    )


def _wip_and_flow_reasons(comparison: ScenarioComparison) -> list[str]:
    reasons = []
    for reason in (_wip_reason(comparison), _flow_reason(comparison)):
        if reason is not None:
            reasons.append(reason)
    return reasons


# Verdict logic

def evaluate_verdict(comparison: ScenarioComparison) -> tuple[Verdict, list[str]]:
    """Deterministic, lexicographic verdict — never a weighted black-box score."""
    if comparison.comparison_kind == ScenarioComparisonKind.REQUIREMENT_CHANGE:
        verdict, reasons = _evaluate_requirement_change(comparison)
    else:
        verdict, reasons = _evaluate_engineering_change(comparison)
        if comparison.comparison_kind == ScenarioComparisonKind.MIXED_CHANGE:
            reasons.append(
                f"Note: this scenario also changed the demand target from "
                f"{comparison.baseline_target_units} to {comparison.candidate_target_units} "
                f"units (MIXED_CHANGE) — some of the measured effect may reflect the new "
                f"target rather than the engineering change alone."
            )

    if comparison.capex_delta is not None and comparison.capex_delta > 0:
        reasons.append(
            f"CAPEX delta: +{_fmt(comparison.capex_delta)} (informational only; "
            f"not used to determine the verdict)."
        )

    return verdict, reasons


def _evaluate_requirement_change(comparison: ScenarioComparison) -> tuple[Verdict, list[str]]:
    reasons = [
        f"Demand target changed from {comparison.baseline_target_units} to "
        f"{comparison.candidate_target_units} units (REQUIREMENT_CHANGE) — no "
        f"engineering/capacity action was applied, so this is not evaluated as an "
        f"operational improvement or degradation."
    ]
    if not comparison.demand_met_before and comparison.demand_met_after:
        reasons.append(
            f"The new target of {comparison.candidate_target_units} units is now met; "
            f"this reflects a changed requirement, not added factory capacity."
        )
    elif comparison.demand_met_before and not comparison.demand_met_after:
        reasons.append(
            f"The new target of {comparison.candidate_target_units} units is no longer "
            f"met, with unchanged factory capacity."
        )
    return Verdict.NEUTRAL, reasons


def _evaluate_engineering_change(comparison: ScenarioComparison) -> tuple[Verdict, list[str]]:
    # Priority 1: demand fulfillment transition
    if not comparison.demand_met_before and comparison.demand_met_after:
        reasons = ["Demand changed from unmet to met."]
        if comparison.demand_gap_delta != 0:
            reasons.append(_gap_reason(comparison))
        reasons.extend(_wip_and_flow_reasons(comparison))
        return Verdict.IMPROVED, reasons

    if comparison.demand_met_before and not comparison.demand_met_after:
        reasons = ["Demand changed from met to unmet."]
        if comparison.demand_gap_delta != 0:
            reasons.append(_gap_reason(comparison))
        reasons.extend(_wip_and_flow_reasons(comparison))
        return Verdict.DEGRADED, reasons

    # Priority 2: demand gap, when both fail demand
    if not comparison.demand_met_before and not comparison.demand_met_after:
        if comparison.demand_gap_delta < -UNIT_TOLERANCE:
            reasons = [_gap_reason(comparison)]
            reasons.extend(_wip_and_flow_reasons(comparison))
            return Verdict.IMPROVED, reasons
        if comparison.demand_gap_delta > UNIT_TOLERANCE:
            reasons = [_gap_reason(comparison)]
            reasons.extend(_wip_and_flow_reasons(comparison))
            return Verdict.DEGRADED, reasons
        # Gap effectively unchanged -> fall through to completed-units tie-break.

    # Priority 3: completed units, when demand status/gap are tied
    if comparison.completed_units_delta > 0:
        reasons = [
            f"Completed units increased from {comparison.completed_units_before} to "
            f"{comparison.completed_units_after}."
        ]
        reasons.extend(_wip_and_flow_reasons(comparison))
        return Verdict.IMPROVED, reasons
    if comparison.completed_units_delta < 0:
        reasons = [
            f"Completed units decreased from {comparison.completed_units_before} to "
            f"{comparison.completed_units_after}."
        ]
        reasons.extend(_wip_and_flow_reasons(comparison))
        return Verdict.DEGRADED, reasons

    # Priority 4: WIP / average flow time, when output is tied
    wip_improved = comparison.wip_delta < 0
    wip_degraded = comparison.wip_delta > 0
    flow_improved = comparison.average_flow_time_delta_seconds < -FLOW_TIME_TOLERANCE_SECONDS
    flow_degraded = comparison.average_flow_time_delta_seconds > FLOW_TIME_TOLERANCE_SECONDS

    if (wip_improved or flow_improved) and not (wip_degraded or flow_degraded):
        return Verdict.IMPROVED, _wip_and_flow_reasons(comparison)
    if (wip_degraded or flow_degraded) and not (wip_improved or flow_improved):
        return Verdict.DEGRADED, _wip_and_flow_reasons(comparison)

    # Priority 5: no material operational difference
    return Verdict.NEUTRAL, ["No material operational difference detected between baseline and candidate."]
