"""Deterministic candidate ranking / Pareto selection models for Fabrivium Phase 4C."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.optimization import OptimizationGoal
from app.models.simulation import SimulationResult


class CandidateRankStatus(str, Enum):
    """A candidate's place in the ranking — distinct from
    ``app.models.evaluation.CandidateFeasibilityStatus``, which this
    builds on top of (every INFEASIBLE Phase 4B candidate stays
    INFEASIBLE here too; feasibility is never re-decided by ranking).
    """

    RECOMMENDED = "RECOMMENDED"
    PARETO_OPTIMAL = "PARETO_OPTIMAL"
    DOMINATED = "DOMINATED"
    INFEASIBLE = "INFEASIBLE"
    REQUIRES_INFORMATION = "REQUIRES_INFORMATION"


class CandidateRanking(BaseModel):
    """One candidate's ranking record."""

    model_config = {"frozen": True}

    candidate_id: str = Field(..., min_length=1)
    status: CandidateRankStatus
    rank: int | None = Field(
        None, ge=1, description="Position in the objective-specific total order; None for INFEASIBLE/REQUIRES_INFORMATION"
    )
    dominated_by: list[str] = Field(default_factory=list, description="Candidate IDs that Pareto-dominate this one")
    dominates: list[str] = Field(default_factory=list, description="Candidate IDs this one Pareto-dominates")
    rationale: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)


class OptimizationRecommendation(BaseModel):
    """Full output of one ranking run."""

    model_config = {"frozen": True}

    goal: OptimizationGoal
    baseline_result: SimulationResult

    rankings: list[CandidateRanking] = Field(default_factory=list)
    pareto_candidate_ids: list[str] = Field(default_factory=list)
    recommended_candidate_ids: list[str] = Field(default_factory=list)

    summary: str = Field(..., description="Deterministic, templated explanation — never LLM output")
