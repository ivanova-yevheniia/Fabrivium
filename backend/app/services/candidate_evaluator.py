"""Candidate feasibility evaluation pipeline for Fabrivium Phase 4B."""

from __future__ import annotations

from app.models.constraints import LayoutValidationResult
from app.models.evaluation import (
    CandidateEvaluation,
    CandidateFeasibilityStatus,
    CandidateRejectionReason,
    OptimizationEvaluationResult,
)
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.optimization import OptimizationCandidate, OptimizationGoal
from app.services.candidate_generator import generate_candidates
from app.services.constraints import validate_layout
from app.services.layout import place_machine
from app.services.placement_search import (
    DEFAULT_GRID_SPACING,
    DEFAULT_MAX_POSITION_ATTEMPTS,
    find_placement,
)
from app.services.scenario import ScenarioError, apply_scenario
from app.services.scenario_runner import run_scenario
from app.services.simulation import run_simulation


class BaselineLayoutInvalidError(Exception):
    """
    Raised when a supplied baseline ``FactoryLayout`` already has ERROR violations.
    """


# Public entry point

def evaluate_candidates(
    factory: Factory,
    product_id: str,
    goal: OptimizationGoal,
    layout: FactoryLayout | None = None,
    grid_spacing: float = DEFAULT_GRID_SPACING,
    max_position_attempts: int = DEFAULT_MAX_POSITION_ATTEMPTS,
) -> OptimizationEvaluationResult:
    """Generate (Phase 4A) and evaluate (Phase 4B) candidates for *factory*."""
    baseline_simulation = run_simulation(factory, product_id)

    baseline_layout_validation: LayoutValidationResult | None = None
    if layout is not None:
        baseline_layout_validation = validate_layout(factory, layout, product_id)
        if baseline_layout_validation.error_count > 0:
            raise BaselineLayoutInvalidError(
                f"Baseline layout has {baseline_layout_validation.error_count} ERROR "
                f"violation(s); refusing to generate/evaluate optimization candidates "
                f"from invalid geometry. Fix the baseline layout first."
            )

    # Generate WITHOUT goal.max_capex: Phase 4A's own generator silently
    # drops capex-exceeding candidates, but Phase 4B needs them to be
    # generated so it can reject them ITSELF with a visible, reported
    # CAPEX_LIMIT evaluation (see experiment D) rather than have them
    # vanish before evaluation ever sees them. max_additional_machines and
    # allowed_action_types are left as-is — Phase 4B has no requirement to
    # surface those as evaluated-and-rejected candidates.
    generation_goal = goal.model_copy(update={"max_capex": None}) if goal.max_capex is not None else goal
    candidates = generate_candidates(factory, product_id, generation_goal, layout)

    evaluations = [
        _evaluate_one(
            factory, product_id, goal, layout, baseline_layout_validation,
            candidate, grid_spacing, max_position_attempts,
        )
        for candidate in candidates
    ]

    feasible = sum(1 for e in evaluations if e.status == CandidateFeasibilityStatus.FEASIBLE)
    infeasible = sum(1 for e in evaluations if e.status == CandidateFeasibilityStatus.INFEASIBLE)
    requires_info = sum(1 for e in evaluations if e.status == CandidateFeasibilityStatus.REQUIRES_INFORMATION)

    return OptimizationEvaluationResult(
        baseline_simulation=baseline_simulation,
        baseline_layout_validation=baseline_layout_validation,
        candidates=evaluations,
        feasible_count=feasible,
        infeasible_count=infeasible,
        requires_information_count=requires_info,
    )


# Per-candidate pipeline

def _reject(
    candidate: OptimizationCandidate,
    reason: CandidateRejectionReason,
    *,
    operationally_feasible: bool,
    candidate_factory: Factory | None = None,
    candidate_layout: FactoryLayout | None = None,
    constraint_result: LayoutValidationResult | None = None,
    placement_attempts: int | None = None,
) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate=candidate,
        status=CandidateFeasibilityStatus.INFEASIBLE,
        rejection_reasons=[reason],
        candidate_factory=candidate_factory,
        candidate_layout=candidate_layout,
        constraint_result=constraint_result,
        known_capex=candidate.estimated_capex,
        requires_cost_estimate=candidate.requires_cost_estimate,
        operationally_feasible=operationally_feasible,
        placement_attempts=placement_attempts,
    )


def _verify_existing_placements_preserved(baseline_layout: FactoryLayout, candidate_layout: FactoryLayout) -> bool:
    """
    The ``preserve_existing_layout=True`` contract (Phase 5A.1 section 3): every
    placement already present in *baseline_layout* — position, rotation, elevation — is
    byte-for-byte unchanged in *candidate_layout*, and every zone
    (aisle/reserved/safety) is unchanged.
    """
    baseline_by_id = {p.machine_id: p for p in baseline_layout.placements}
    for placement in candidate_layout.placements:
        original = baseline_by_id.get(placement.machine_id)
        if original is None:
            continue
        if (original.x, original.y, original.z, original.rotation_deg) != (
            placement.x, placement.y, placement.z, placement.rotation_deg
        ):
            return False
    return (
        candidate_layout.reserved_zones == baseline_layout.reserved_zones
        and candidate_layout.aisle_zones == baseline_layout.aisle_zones
    )


def _evaluate_one(
    factory: Factory,
    product_id: str,
    goal: OptimizationGoal,
    layout: FactoryLayout | None,
    baseline_layout_validation: LayoutValidationResult | None,
    candidate: OptimizationCandidate,
    grid_spacing: float,
    max_position_attempts: int,
) -> CandidateEvaluation:
    # 1.
    if goal.max_capex is not None and candidate.estimated_capex > goal.max_capex:
        return _reject(candidate, CandidateRejectionReason.CAPEX_LIMIT, operationally_feasible=False)

    # 2. Apply the scenario
    try:
        candidate_factory = apply_scenario(factory, candidate.scenario)
    except ScenarioError:
        return _reject(candidate, CandidateRejectionReason.SCENARIO_INVALID, operationally_feasible=False)

    candidate_layout: FactoryLayout | None = None
    constraint_result: LayoutValidationResult | None = None
    placement_attempts: int | None = None

    # 3 & 4. Placement + layout constraint validation
    if layout is not None:
        new_machine_ids = sorted(
            {m.id for m in candidate_factory.machines} - {m.id for m in factory.machines}
        )

        if not new_machine_ids:
            # Nothing new to place — geometry is byte-for-byte identical to
            # the already-validated baseline; no need to recheck it.
            candidate_layout = layout
            constraint_result = baseline_layout_validation
        else:
            candidate_layout = layout
            placement_attempts = 0
            machine_index = {m.id: m for m in candidate_factory.machines}

            for new_id in new_machine_ids:
                near_id = machine_index[new_id].parallel_of_machine_id
                search = find_placement(
                    candidate_factory, candidate_layout, new_id,
                    near_machine_id=near_id,
                    grid_spacing=grid_spacing,
                    max_position_attempts=max_position_attempts,
                )
                placement_attempts += search.attempts
                if search.placement is None:
                    return _reject(
                        candidate, CandidateRejectionReason.PLACEMENT_NOT_FOUND,
                        operationally_feasible=False,
                        candidate_factory=candidate_factory,
                        placement_attempts=placement_attempts,
                    )
                candidate_layout = place_machine(
                    candidate_factory, candidate_layout, new_id,
                    x=search.placement.x, y=search.placement.y,
                    rotation_deg=search.placement.rotation_deg,
                )

            constraint_result = validate_layout(candidate_factory, candidate_layout, product_id)
            if constraint_result.error_count > 0:
                return _reject(
                    candidate, CandidateRejectionReason.LAYOUT_INFEASIBLE,
                    operationally_feasible=False,
                    candidate_factory=candidate_factory,
                    candidate_layout=candidate_layout,
                    constraint_result=constraint_result,
                    placement_attempts=placement_attempts,
                )

        if goal.preserve_existing_layout and not _verify_existing_placements_preserved(layout, candidate_layout):
            # Defensive, always-checked contract (Phase 5A.1 section 3):
            # currently unreachable, since no Phase 4A action type ever
            # repositions an existing machine — placement_search only ever
            # ADDS placements. Enforced explicitly anyway so a future
            # is rejected here rather than silently allowed through.
            return _reject(
                candidate, CandidateRejectionReason.LAYOUT_INFEASIBLE,
                operationally_feasible=False,
                candidate_factory=candidate_factory,
                candidate_layout=candidate_layout,
                constraint_result=constraint_result,
                placement_attempts=placement_attempts,
            )

    # 5. Simulation + scenario comparison (Phase 2C, not duplicated)
    try:
        scenario_result = run_scenario(factory, product_id, candidate.scenario)
    except ValueError:
        return _reject(
            candidate, CandidateRejectionReason.SIMULATION_INVALID,
            operationally_feasible=False,
            candidate_factory=candidate_factory,
            candidate_layout=candidate_layout,
            constraint_result=constraint_result,
            placement_attempts=placement_attempts,
        )

    # 6. Final status: operational vs. commercial feasibility
    if goal.max_capex is not None and candidate.requires_cost_estimate:
        status = CandidateFeasibilityStatus.REQUIRES_INFORMATION
        rejection_reasons = [CandidateRejectionReason.COST_UNKNOWN]
    else:
        status = CandidateFeasibilityStatus.FEASIBLE
        rejection_reasons = []

    return CandidateEvaluation(
        candidate=candidate,
        status=status,
        rejection_reasons=rejection_reasons,
        candidate_factory=candidate_factory,
        candidate_layout=candidate_layout,
        simulation_result=scenario_result.candidate_result,
        scenario_result=scenario_result,
        constraint_result=constraint_result,
        known_capex=candidate.estimated_capex,
        requires_cost_estimate=candidate.requires_cost_estimate,
        operationally_feasible=True,
        placement_attempts=placement_attempts,
    )
