"""Deterministic optimization candidate-generation models for Fabrivium Phase 4A."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.scenario import Scenario


# Goal

class OptimizationObjective(str, Enum):
    MEET_DEMAND = "MEET_DEMAND"
    MAXIMIZE_THROUGHPUT = "MAXIMIZE_THROUGHPUT"
    MINIMIZE_WIP = "MINIMIZE_WIP"
    MINIMIZE_FLOW_TIME = "MINIMIZE_FLOW_TIME"


class OptimizationGoal(BaseModel):
    """
    What the candidate generator should look for, and the guardrails on what it's
    allowed to propose.
    """

    model_config = {"frozen": True}

    objective: OptimizationObjective
    target_product_id: str = Field(..., min_length=1)

    max_capex: float | None = Field(None, ge=0.0, description="Hard cap; see CAPEX pre-filter semantics")
    max_additional_machines: int | None = Field(None, ge=0)
    allowed_action_types: list[str] | None = Field(
        None, description="Restrict generation to these ScenarioAction.action_type values; None = no restriction"
    )
    max_candidates: int = Field(10, ge=0, description="Truncates the deterministically-ordered candidate list")

    forbidden_machine_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Machine IDs (or process-pool roots) that no candidate action may ever "
            "target. A root machine id expands to its whole service pool (root + "
            "existing clones); an explicitly-named clone id does not expand — see "
            "app.services.candidate_generator._expand_forbidden_machine_ids."
        ),
    )
    preserve_existing_layout: bool = Field(
        False,
        description=(
            "If True, every EXISTING machine placement/rotation and every zone must "
            "remain byte-for-byte unchanged in any candidate layout; only newly-added "
            "machines may be placed, into unused legal space. Phase 4B's placement "
            "search already never moves existing placements regardless of this flag — "
            "setting it makes that behaviour an explicit, verified contract (see "
            "app.services.candidate_evaluator._verify_existing_placements_preserved) "
            "rather than an incidental implementation detail, and reserves the right "
            "to REJECT a future action type that would need to rearrange machines."
        ),
    )

    # Reserved for a future phase — not implemented, not read, in Phase 4A.
    max_additional_operators: int | None = Field(None, ge=0)
    max_floor_area: float | None = Field(None, ge=0.0)


# Candidate

class GenerationSource(str, Enum):
    BOTTLENECK_RELIEF = "BOTTLENECK_RELIEF"          # ADD_PARALLEL_MACHINE at a congested pool
    CAPACITY_EXPANSION = "CAPACITY_EXPANSION"        # CHANGE_MACHINE_CAPACITY +1
    CYCLE_TIME_IMPROVEMENT = "CYCLE_TIME_IMPROVEMENT"  # CHANGE_MACHINE_CYCLE_TIME -X%
    COMBINED = "COMBINED"                            # multi-action candidate
    # Phase 8A: levers that are not "buy a machine"
    SHIFT_EXPANSION = "SHIFT_EXPANSION"              # CHANGE_SHIFT_CONFIGURATION +1 shift
    OPERATOR_EXPANSION = "OPERATOR_EXPANSION"        # CHANGE_OPERATOR_CAPACITY +N staff
    BUFFER_EXPANSION = "BUFFER_EXPANSION"            # CHANGE_BUFFER_CAPACITY on a blocking buffer


class OptimizationCandidate(BaseModel):
    """One deterministically-generated, not-yet-evaluated candidate scenario."""

    model_config = {"frozen": True}

    candidate_id: str = Field(..., min_length=1)
    scenario: Scenario
    rationale: str = Field(..., description="Deterministic, template-generated explanation — never LLM output")
    generation_source: GenerationSource

    estimated_capex: float = Field(
        ..., ge=0.0,
        description=(
            "Known-cost portion only. 0.0 when no cost is known at all "
            "(see requires_cost_estimate) — never a placeholder guess."
        ),
    )
    requires_cost_estimate: bool = Field(
        ..., description="True when estimated_capex is incomplete/unknown for at least one action in this scenario"
    )
    requires_layout_placement: bool = Field(
        False,
        description=(
            "True whenever this scenario introduces a new physical machine "
            "(ADD_PARALLEL_MACHINE) — it always needs a floor position "
            "eventually, regardless of whether a FactoryLayout was supplied "
            "to the generator. Phase 4B is responsible for actually placing "
            "it and running constraint validation."
        ),
    )
    affected_processes: list[str] = Field(
        default_factory=list, description="reference_machine_id(s) (ProcessPoolKPI) this candidate targets"
    )
