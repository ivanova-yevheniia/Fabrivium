"""Compact planning-context builder for Fabrivium Phase 5B."""

from __future__ import annotations

from app.models.agent import PlanningRequirements
from app.models.constraints import LayoutValidationResult
from app.models.evaluation import OptimizationEvaluationResult
from app.models.factory import Factory
from app.models.planning_agent import (
    PlanningContext,
    PlanningContextCandidateSummary,
    PlanningContextMachineSummary,
    PlanningContextPoolSummary,
    PlanningContextSimulationSummary,
)
from app.models.ranking import OptimizationRecommendation
from app.models.simulation import SimulationResult


def _summarize_layout_validation(result: LayoutValidationResult) -> str:
    return f"valid={result.valid}, {result.error_count} error(s), {result.warning_count} warning(s)"


def build_planning_context(
    factory: Factory,
    product_id: str,
    requirements: PlanningRequirements,
    simulation_result: SimulationResult,
    evaluation_result: OptimizationEvaluationResult | None = None,
    recommendation: OptimizationRecommendation | None = None,
    layout_validation: LayoutValidationResult | None = None,
    proposal_history: list[str] | None = None,
) -> PlanningContext:
    """Build a compact ``PlanningContext``."""
    pool_summaries = [
        PlanningContextPoolSummary(
            reference_machine_id=p.reference_machine_id,
            process_step_name=p.process_step_name,
            utilization=p.utilization,
            average_queue_length=p.average_queue_length,
            average_wait_time_seconds=p.average_wait_time_seconds,
        )
        for p in simulation_result.process_pool_kpis
    ]

    machines = [
        PlanningContextMachineSummary(
            id=m.id, name=m.name, process_type=m.process_type,
            cycle_time=m.cycle_time, capacity=m.capacity, purchase_cost=m.purchase_cost,
        )
        for m in factory.machines
    ]

    candidate_summaries = _build_candidate_summaries(evaluation_result, recommendation)

    layout_summary = _summarize_layout_validation(layout_validation) if layout_validation is not None else None

    simulation_summary = PlanningContextSimulationSummary(
        product_id=product_id,
        completed_units=simulation_result.completed_units,
        target_units=simulation_result.target_units,
        demand_met=simulation_result.demand_met,
        demand_gap_units=simulation_result.demand_gap_units,
        work_in_progress=simulation_result.system.work_in_progress,
        average_flow_time_seconds=simulation_result.system.average_flow_time_seconds,
        bottleneck_machine_id=simulation_result.system.bottleneck_machine_id,
    )

    return PlanningContext(
        requirements=requirements,
        simulation_summary=simulation_summary,
        pool_summaries=pool_summaries,
        machines=machines,
        candidate_summaries=candidate_summaries,
        layout_validation_summary=layout_summary,
        proposal_history=list(proposal_history) if proposal_history else [],
    )


def _build_candidate_summaries(
    evaluation_result: OptimizationEvaluationResult | None,
    recommendation: OptimizationRecommendation | None,
) -> list[PlanningContextCandidateSummary]:
    if evaluation_result is None:
        return []

    rank_by_id = {}
    status_by_id = {}
    if recommendation is not None:
        for r in recommendation.rankings:
            rank_by_id[r.candidate_id] = r.rank
            status_by_id[r.candidate_id] = r.status.value

    summaries = []
    for evaluation in evaluation_result.candidates:
        cid = evaluation.candidate.candidate_id
        status = status_by_id.get(cid, evaluation.status.value)
        summaries.append(
            PlanningContextCandidateSummary(
                candidate_id=cid,
                scenario=evaluation.candidate.scenario,
                status=status,
                rank=rank_by_id.get(cid),
                generation_source=evaluation.candidate.generation_source.value,
                known_capex=evaluation.known_capex,
                requires_cost_estimate=evaluation.requires_cost_estimate,
            )
        )
    return summaries
