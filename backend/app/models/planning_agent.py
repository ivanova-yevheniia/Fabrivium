"""Planning Agent domain models for Fabrivium Phase 5B."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.agent import PlanningRequirements
from app.models.scenario import Scenario


# Hypothesis

class SuspectedIssueType(str, Enum):
    INSUFFICIENT_CAPACITY = "INSUFFICIENT_CAPACITY"
    HIGH_WIP = "HIGH_WIP"
    HIGH_FLOW_TIME = "HIGH_FLOW_TIME"
    DEMAND_INCREASE = "DEMAND_INCREASE"
    LAYOUT_CONSTRAINT = "LAYOUT_CONSTRAINT"
    UNKNOWN = "UNKNOWN"


class PlanningHypothesis(BaseModel):
    """
    A diagnosed (but NOT verified) explanation for why the factory might not be meeting
    the stated objective.
    """

    model_config = {"frozen": True}

    problem_summary: str = Field(..., min_length=1)
    suspected_bottleneck_machine_id: str | None = None
    suspected_issue_type: SuspectedIssueType
    evidence: list[str] = Field(default_factory=list)


# Proposal

class ProposalSource(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"


class PlanningProposal(BaseModel):
    """One proposed engineering intervention."""

    model_config = {"frozen": True}

    proposal_id: str = Field(..., min_length=1)
    hypothesis: PlanningHypothesis
    scenario: Scenario
    expected_effects: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: ProposalSource


# Compact planning context

class PlanningContextMachineSummary(BaseModel):
    model_config = {"frozen": True}
    id: str
    name: str
    process_type: str
    cycle_time: float
    capacity: int
    # None when the machine has no recorded price.
    purchase_cost: float | None = None


class PlanningContextPoolSummary(BaseModel):
    """Compact per-logical-stage summary — mirrors the fields a
    deterministic hypothesis actually needs from
    ``app.models.simulation.ProcessPoolKPI``, nothing more."""

    model_config = {"frozen": True}
    reference_machine_id: str
    process_step_name: str
    utilization: float
    average_queue_length: float
    average_wait_time_seconds: float


class PlanningContextSimulationSummary(BaseModel):
    model_config = {"frozen": True}
    product_id: str
    completed_units: int
    target_units: int
    demand_met: bool
    demand_gap_units: float
    work_in_progress: int
    average_flow_time_seconds: float
    bottleneck_machine_id: str


class PlanningContextCandidateSummary(BaseModel):
    """One Phase 4-generated candidate, compact enough for an LLM prompt
    but complete enough for ``DeterministicPlanningAgent`` to preserve its
    ``scenario`` EXACTLY when repackaging it as a ``PlanningProposal`` —
    see Phase 5B section 4."""

    model_config = {"frozen": True}
    candidate_id: str
    scenario: Scenario
    status: str = Field(..., description="CandidateFeasibilityStatus or CandidateRankStatus value, as a plain string")
    rank: int | None = None
    generation_source: str
    known_capex: float
    requires_cost_estimate: bool


class PlanningContext(BaseModel):
    """
    Everything a Planning Agent backend needs, deliberately compact — never the raw
    ``Factory``/``OptimizationEvaluationResult`` objects.
    """

    model_config = {"frozen": True}

    requirements: PlanningRequirements
    simulation_summary: PlanningContextSimulationSummary
    pool_summaries: list[PlanningContextPoolSummary] = Field(default_factory=list)
    machines: list[PlanningContextMachineSummary] = Field(default_factory=list)
    candidate_summaries: list[PlanningContextCandidateSummary] = Field(default_factory=list)
    layout_validation_summary: str | None = Field(
        None, description="Compact human-readable summary, e.g. 'valid=True, 0 errors, 2 warnings'; None if no layout was supplied"
    )
    proposal_history: list[str] = Field(default_factory=list, description="Reserved for Phase 5C — always empty in Phase 5B")


# Audit trail

class RejectedProposal(BaseModel):
    """
    A proposal that did not survive validation — kept for the audit trail rather than
    silently discarded.
    """

    model_config = {"frozen": True}

    proposal: PlanningProposal | None = None
    raw_proposal: dict | None = None
    reasons: list[str] = Field(default_factory=list)


class PlanningAgentResult(BaseModel):
    """Full audit record of one ``run_planning_agent`` call."""

    model_config = {"frozen": True}

    proposals: list[PlanningProposal] = Field(default_factory=list)
    context_summary: str
    rejected_proposals: list[RejectedProposal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    agent_type: ProposalSource
    optimizer_grounded: bool
