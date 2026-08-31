"""Explanation Agent domain models for Fabrivium Phase 5D."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# Source type


class ExplanationSourceType(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    LLM = "LLM"


# Compact verified-facts payload (Phase 5D section 7)


class ExplanationIterationFact(BaseModel):
    """
    One iteration's facts, already flattened to plain values — never a raw
    ``ScenarioResult``/``Factory``.
    """

    model_config = {"frozen": True}

    iteration_number: int = Field(..., ge=1, description="1-based — matches the trace/user-facing numbering, not PlanningIteration.iteration_index")
    accepted: bool
    action_summary: str
    machine_ids: list[str] = Field(default_factory=list)
    verdict: str | None = Field(None, description="IMPROVED/NEUTRAL/DEGRADED — None if the scenario was never evaluated (e.g. no valid proposal)")
    demand_gap_before: float | None = None
    demand_gap_after: float | None = None
    demand_met_after: bool | None = None
    bottleneck_before: str | None = None
    bottleneck_after: str | None = None
    known_capex: float | None = None
    requires_cost_estimate: bool = False
    rejection_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ExplanationBudgetFacts(BaseModel):
    model_config = {"frozen": True}
    max_capex: float | None = None
    cumulative_known_capex: float = 0.0
    remaining_known_capex: float | None = None


class ExplanationContext(BaseModel):
    """
    The ONLY input an ``ExplanationAgent`` receives — a compact, already-verified fact
    payload built once by
    ``app.services.explanation_context.build_explanation_context``.
    """

    model_config = {"frozen": True}

    session_id: str
    objective: str
    target_units_per_day: float | None = None
    forbidden_machine_ids: list[str] = Field(default_factory=list)

    baseline_demand_met: bool
    baseline_demand_gap: float
    baseline_bottleneck: str | None = None
    baseline_completed_units: int
    baseline_target_units: int

    final_demand_met: bool
    final_demand_gap: float
    final_bottleneck: str | None = None
    final_completed_units: int
    final_target_units: int

    layout_supplied: bool = False
    layout_valid: bool | None = Field(None, description="None when no layout was supplied at all")

    accepted_iterations: list[ExplanationIterationFact] = Field(default_factory=list)
    rejected_iterations: list[ExplanationIterationFact] = Field(default_factory=list)

    budget: ExplanationBudgetFacts

    stop_reason: str
    goal_reached: bool

    known_machine_ids: list[str] = Field(
        default_factory=list, description="Every machine_id that may legitimately be mentioned — hallucination-guard reference set"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Information gaps — e.g. unresolved unknown-cost candidates — never fabricated, only reported"
    )


# Explanation output


class ExplanationSection(BaseModel):
    model_config = {"frozen": True}

    title: str = Field(..., min_length=1)
    content: str
    evidence_refs: list[str] = Field(default_factory=list)


class PlanningExplanation(BaseModel):
    """The full, user-facing explanation of one planning session."""

    model_config = {"frozen": True}

    executive_summary: str
    goal_status: str
    recommended_changes: list[str] = Field(default_factory=list)
    verified_effects: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    constraints_and_risks: list[str] = Field(default_factory=list)
    stop_explanation: str
    sections: list[ExplanationSection] = Field(default_factory=list)
    source_type: ExplanationSourceType


# Orchestration result (Phase 5D section 8 — hallucination guard audit trail)


class ExplanationResult(BaseModel):
    """Full audit record of one ``app.services.explanation_agent.generate_explanation``
    call — makes the hallucination-guard fallback observable/testable."""

    model_config = {"frozen": True}

    explanation: PlanningExplanation
    llm_attempted: bool = False
    llm_validation_errors: list[str] = Field(default_factory=list)
    used_fallback: bool = False
