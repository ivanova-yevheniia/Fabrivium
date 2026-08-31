"""Candidate feasibility evaluation models for Fabrivium Phase 4B."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.comparison import ScenarioResult
from app.models.constraints import LayoutValidationResult
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.optimization import OptimizationCandidate
from app.models.simulation import SimulationResult


# Enums

class CandidateFeasibilityStatus(str, Enum):
    """A verdict about VALIDITY, never about quality — see module docstring."""

    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    REQUIRES_INFORMATION = "REQUIRES_INFORMATION"


class CandidateRejectionReason(str, Enum):
    CAPEX_LIMIT = "CAPEX_LIMIT"
    LAYOUT_INFEASIBLE = "LAYOUT_INFEASIBLE"
    SCENARIO_INVALID = "SCENARIO_INVALID"
    SIMULATION_INVALID = "SIMULATION_INVALID"
    COST_UNKNOWN = "COST_UNKNOWN"
    PLACEMENT_NOT_FOUND = "PLACEMENT_NOT_FOUND"
    OTHER = "OTHER"


# Per-candidate evaluation

class CandidateEvaluation(BaseModel):
    """The full evaluation record for one ``OptimizationCandidate``."""

    model_config = {"frozen": True}

    candidate: OptimizationCandidate
    status: CandidateFeasibilityStatus
    rejection_reasons: list[CandidateRejectionReason] = Field(default_factory=list)

    candidate_factory: Factory | None = Field(None, description="Set once apply_scenario succeeds")
    candidate_layout: FactoryLayout | None = Field(
        None, description="Baseline layout plus any newly-placed machine(s); None if no layout was supplied"
    )
    simulation_result: SimulationResult | None = Field(None, description="== scenario_result.candidate_result")
    scenario_result: ScenarioResult | None = Field(
        None, description="Full Phase 2C comparison/verdict — reused, not recomputed, from app.services.scenario_runner"
    )
    constraint_result: LayoutValidationResult | None = Field(
        None, description="Phase 3B LayoutValidationResult for candidate_layout, when a layout was supplied"
    )

    known_capex: float = Field(..., ge=0.0, description="== candidate.estimated_capex")
    requires_cost_estimate: bool = Field(..., description="== candidate.requires_cost_estimate")

    operationally_feasible: bool = Field(
        ...,
        description=(
            "True iff the scenario applies, the (if supplied) layout/placement "
            "checks pass, and simulation runs successfully — independent of "
            "commercial (CAPEX) feasibility. False when any operational check "
            "genuinely fails, OR when the pipeline stopped before the "
            "operational checks ran at all (currently only CAPEX_LIMIT does "
            "this, as a deliberate 'skip expensive work once already "
            "disqualified' optimization) — rejection_reasons disambiguates "
            "which case applies."
        ),
    )
    placement_attempts: int | None = Field(
        None, ge=0, description="Number of grid positions/rotations tried by the placement search, if it ran"
    )


# Top-level result

class OptimizationEvaluationResult(BaseModel):
    """Full output of one candidate-generation-and-evaluation run."""

    model_config = {"frozen": True}

    baseline_simulation: SimulationResult
    baseline_layout_validation: LayoutValidationResult | None = None

    candidates: list[CandidateEvaluation] = Field(default_factory=list)

    feasible_count: int = Field(..., ge=0)
    infeasible_count: int = Field(..., ge=0)
    requires_information_count: int = Field(..., ge=0)
