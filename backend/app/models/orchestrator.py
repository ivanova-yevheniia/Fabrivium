"""
Iterative Planning Orchestrator domain models for Fabrivium Phase 5C (extended in Phase
6A.1 with per-iteration digital-twin snapshots).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.agent import PlanningRequirements
from app.models.comparison import ScenarioResult
from app.models.constraints import LayoutValidationResult
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.planning_agent import PlanningAgentResult, PlanningProposal
from app.models.ranking import OptimizationRecommendation
from app.models.simulation import SimulationResult


class PlanningStopReason(str, Enum):
    """Every orchestrator run ends with exactly one of these, always
    explicit (Phase 5C section 2) — never a silent/implicit stop."""

    GOAL_REACHED = "GOAL_REACHED"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    NO_VALID_PROPOSAL = "NO_VALID_PROPOSAL"
    NO_FEASIBLE_IMPROVEMENT = "NO_FEASIBLE_IMPROVEMENT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CONSTRAINT_BLOCKED = "CONSTRAINT_BLOCKED"
    REPEATED_PROPOSAL = "REPEATED_PROPOSAL"
    USER_CONSTRAINTS_BLOCK_PROGRESS = "USER_CONSTRAINTS_BLOCK_PROGRESS"
    ERROR = "ERROR"


class PlanningStateSnapshot(BaseModel):
    """
    A complete, reproducible digital-twin state at one point in a planning session —
    never reconstructed later from a scenario string; always the actual typed domain
    values produced by ``apply_scenario``/placement search/``run_simulation`` (Phase
    6A.1 section 2).
    """

    model_config = {"frozen": True}

    factory: Factory
    layout: FactoryLayout | None = Field(
        None, description="None precisely when no layout was supplied to this planning session at all — never fabricated."
    )
    simulation: SimulationResult
    bottleneck_machine_id: str = Field(..., description="== simulation.system.bottleneck_machine_id, surfaced directly for convenience")
    cumulative_known_capex: float = Field(..., ge=0.0, description="Total known CAPEX committed to reach this exact state")
    remaining_known_capex: float | None = Field(
        None,
        description=(
            "Known CAPEX still available AT THIS EXACT STATE — always "
            "app.services.budget.remaining_known_capex(max_capex, cumulative_known_capex). "
            "None when the session set no max_capex constraint at all. "
            "A snapshot is a complete state at one point in time, and "
            "remaining budget is as much a part of that state as cumulative "
            "spend is: pairing this field's session-FINAL counterpart with a "
            "per-iteration cumulative was the temporal inconsistency this "
            "field exists to make impossible. Deliberately not ge=0 — see "
            "app.services.budget for why a hypothetical over-budget "
            "rejected-candidate snapshot reports a negative value rather "
            "than a misleading zero."
        ),
    )


class PlanningIteration(BaseModel):
    """
    One pass of the orchestrator loop: build context, get proposals, select one
    deterministically, evaluate it through the existing Phase 2-4 stack, accept or
    reject.
    """

    model_config = {"frozen": True}

    iteration_index: int = Field(..., ge=0)
    observation: str = Field(..., description="Deterministic, templated summary of the state entering this iteration")
    planning_agent_result: PlanningAgentResult
    selected_proposal: PlanningProposal | None = None
    proposal_validation: list[str] = Field(
        default_factory=list, description="Reasons the selected proposal failed evaluation/acceptance; empty if none or if accepted"
    )
    scenario_result: ScenarioResult | None = Field(None, description="Set if the selected proposal was evaluated through run_scenario/_evaluate_one")
    layout_validation: LayoutValidationResult | None = None
    recommendation_snapshot: OptimizationRecommendation | None = None
    accepted: bool
    rejection_reason: str | None = None
    trace: list[str] = Field(default_factory=list, description="Deterministic templated trace lines for this iteration (Phase 5C section 14)")

    known_capex: float | None = Field(
        None, description="== the evaluated candidate's known_capex; None when no candidate was evaluated this iteration"
    )
    requires_cost_estimate: bool = Field(
        False, description="== the evaluated candidate's requires_cost_estimate; only meaningful when known_capex is not None"
    )

    state_before: PlanningStateSnapshot | None = Field(
        None,
        description=(
            "Exact verified state entering this iteration — set whenever the "
            "orchestrator reached this iteration at all (Phase 6A.1 section 3: "
            "always available, accepted or not)."
        ),
    )
    state_after: PlanningStateSnapshot | None = Field(
        None,
        description=(
            "Exact verified state AFTER this iteration — set if and only if "
            "``accepted`` is True. The next iteration's state_before is built "
            "from the exact same objects (Phase 6A.1 section 2's invariant: "
            "iteration N.state_after == iteration N+1.state_before)."
        ),
    )
    rejected_candidate_snapshot: PlanningStateSnapshot | None = Field(
        None,
        description=(
            "The evaluated-but-NOT-accepted candidate's state, set only when "
            "``accepted`` is False AND a candidate was actually simulated "
            "(i.e. scenario_result is not None). Explicitly separate from "
            "state_after so a rejected candidate can never be mistaken for "
            "accepted factory history (Phase 6A.1 section 3)."
        ),
    )


class PlanningSessionState(BaseModel):
    """
    Full state of one orchestrator run — typed and serializable end to end (Phase 5C
    section 1).
    """

    model_config = {"frozen": True}

    session_id: str
    original_requirements: PlanningRequirements

    current_factory: Factory
    current_layout: FactoryLayout | None = None
    baseline_factory: Factory
    baseline_layout: FactoryLayout | None = None

    baseline_simulation: SimulationResult = Field(
        ..., description="Simulation of current_factory (post apply_target_demand, pre-iteration-0) — the true starting point for explanations."
    )
    current_simulation: SimulationResult
    iterations: list[PlanningIteration] = Field(default_factory=list)

    current_best_result: SimulationResult = Field(
        ...,
        description=(
            "The best verified SimulationResult found so far. In Phase 5C's "
            "monotonic-acceptance design this always equals current_simulation "
            "(a candidate only ever replaces current state when it is proven "
            "an improvement — see app.services.goal_checker), but the field is "
            "kept distinct for a future phase that might explore non-monotonically."
        ),
    )

    cumulative_known_capex: float = Field(0.0, ge=0.0)
    remaining_known_capex: float | None = Field(
        None, description="None when no max_capex constraint is set; otherwise max_capex - cumulative_known_capex"
    )

    stop_reason: PlanningStopReason | None = None
    goal_reached: bool = False

    baseline_snapshot: PlanningStateSnapshot = Field(
        ..., description="== (current_factory, current_layout, baseline_simulation, 0.0) as they stood before iteration 0 — kept for backward-compat alongside the individual baseline_* fields above (Phase 6A.1 section 4)."
    )
    final_snapshot: PlanningStateSnapshot = Field(
        ..., description="Always == (current_factory, current_layout, current_simulation, cumulative_known_capex) by construction — the same objects, not a recomputation."
    )
