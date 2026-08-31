"""Conversational-copilot domain models for Fabrivium Phase 7C."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.agent import PlanningRequirements
from app.models.explanation import PlanningExplanation
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.optimization import OptimizationObjective


# Enums


class PlanningBaseMode(str, Enum):
    """Which verified state a turn's planning run starts FROM (Phase 7C section 8)."""

    ORIGINAL_BASELINE = "ORIGINAL_BASELINE"
    CURRENT_VERIFIED_STATE = "CURRENT_VERIFIED_STATE"


class TurnStatus(str, Enum):
    """How one conversational turn resolved."""

    APPLIED = "APPLIED"
    #: Understood, but nothing about the constraints actually changed, so
    #: no planning was re-run and no branch was created (saves a full
    #: optimizer pass and an explanation call for a no-op).
    NO_CHANGE = "NO_CHANGE"
    # Genuinely ambiguous — Fabrivium asked instead of guessing.
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    # The interpreted update was structurally valid but not admissible (e.g.
    REJECTED = "REJECTED"
    #: The LLM could not be reached / returned unusable output, and the
    #: message was not one the conservative deterministic parser can handle
    #: confidently. State is untouched (Phase 7C section 22: never corrupt
    #: conversational state because of a provider outage).
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


class UpdateSource(str, Enum):
    LLM = "LLM"
    DETERMINISTIC = "DETERMINISTIC"
    # No interpretation was performed (clarification/provider failure).
    NONE = "NONE"


class BranchStatus(str, Enum):
    GOAL_REACHED = "GOAL_REACHED"
    GOAL_NOT_REACHED = "GOAL_NOT_REACHED"


class ConversationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"


# Clarification


class ClarificationRequest(BaseModel):
    """A question Fabrivium asks instead of guessing (Phase 7C section 9)."""

    model_config = {"frozen": True}

    question: str = Field(..., min_length=1)
    ambiguous_fields: list[str] = Field(
        default_factory=list, description="Which requirement fields could not be resolved, e.g. ['objective']."
    )
    safe_options: list[str] = Field(
        default_factory=list,
        description="Concrete choices the user can pick from. Every option must be something Fabrivium can actually execute — never a suggestion it cannot honour.",
    )


# RequirementUpdate — UNTRUSTED external input


# Requirement fields a user can explicitly CLEAR ("remove the budget cap").
RESETTABLE_FIELDS = frozenset({
    "target_units_per_day",
    "max_capex",
    "max_additional_machines",
    "max_additional_operators",
    "max_floor_area",
    "allowed_action_types",
    "forbidden_machine_ids",
    "preserve_existing_layout",
})


class RequirementUpdate(BaseModel):
    """
    A PATCH over ``PlanningRequirements``, not a replacement for it (Phase 7C section
    2).
    """

    model_config = {"frozen": True}

    # Scalar set-if-mentioned
    objective: OptimizationObjective | None = Field(
        None, description="Set only if the user changed what to optimize for. Null = unchanged."
    )
    target_units_per_day: float | None = Field(
        None, gt=0.0, description="New daily production target. Null = unchanged."
    )
    max_capex: float | None = Field(
        None, ge=0.0, description="New maximum capital spend, in euros. Null = unchanged."
    )
    max_additional_machines: int | None = Field(
        None, ge=0, description="New cap on how many machines may be added. Null = unchanged."
    )
    max_additional_operators: int | None = Field(None, ge=0, description="Null = unchanged.")
    max_floor_area: float | None = Field(None, ge=0.0, description="Null = unchanged.")
    allowed_action_types: list[str] | None = Field(
        None, description="Restrict planning to these action types. Null = unchanged."
    )
    preserve_existing_layout: bool | None = Field(
        None, description="True to forbid moving existing machines, false to allow it. Null = unchanged."
    )

    forbidden_machine_ids_add: list[str] = Field(
        default_factory=list,
        description="Machine ids or names the user just asked NOT to modify. Added to the existing set; never replaces it.",
    )
    forbidden_machine_ids_remove: list[str] = Field(
        default_factory=list,
        description="Machine ids or names the user just released, e.g. 'Packaging is allowed again'. Removed from the existing set.",
    )

    # Explicit clearing
    reset_constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Names of constraints to clear entirely, e.g. ['max_capex'] for 'remove the budget limit'. "
            "Only these names are recognised: " + ", ".join(sorted(RESETTABLE_FIELDS)) + "."
        ),
    )

    # Intent
    explicit_intervention: str | None = Field(
        None,
        description="A specific machine the user explicitly asked to duplicate, e.g. 'add a second Packaging machine' -> 'Packaging'. Null if none.",
    )
    base_mode: PlanningBaseMode | None = Field(
        None,
        description=(
            "ORIGINAL_BASELINE when the user wants a different alternative from the original factory "
            "(cheaper, other constraints). CURRENT_VERIFIED_STATE when they want to build further on the "
            "plan already accepted ('now increase it further'). Null if not clearly inferable."
        ),
    )
    clarification_required: bool = Field(
        False,
        description="True when the request has no unique engineering meaning (e.g. 'make it better'). Set this instead of guessing.",
    )
    clarification: ClarificationRequest | None = Field(
        None, description="The question to ask. Required when clarification_required is true."
    )
    intent_summary: str = Field(
        "", description="One short factual sentence describing what the user asked to change. No claims about outcomes."
    )

    def is_empty(self) -> bool:
        """True when this update would change nothing at all."""
        return not any((
            self.objective is not None,
            self.target_units_per_day is not None,
            self.max_capex is not None,
            self.max_additional_machines is not None,
            self.max_additional_operators is not None,
            self.max_floor_area is not None,
            self.allowed_action_types is not None,
            self.preserve_existing_layout is not None,
            self.forbidden_machine_ids_add,
            self.forbidden_machine_ids_remove,
            self.reset_constraints,
            self.explicit_intervention,
        ))


# Branch


class BranchMetrics(BaseModel):
    """A branch's verified KPI summary, flattened to plain values."""

    model_config = {"frozen": True}

    goal_reached: bool
    stop_reason: str
    demand_met: bool
    completed_units: int
    target_units: int
    demand_gap_units: float
    work_in_progress: int
    average_flow_time_seconds: float
    bottleneck_machine_id: str

    max_capex: float | None = None
    cumulative_known_capex: float = 0.0
    remaining_known_capex: float | None = None

    added_machine_ids: list[str] = Field(
        default_factory=list, description="Machine ids targeted by the actions this branch actually accepted, in order."
    )
    accepted_iterations: int = 0
    total_iterations: int = 0
    warnings: list[str] = Field(
        default_factory=list, description="Information gaps carried from the verified session — e.g. unresolved unknown costs. Never fabricated."
    )


class PlanningBranch(BaseModel):
    """One verified planning alternative produced by one turn."""

    model_config = {"frozen": True}

    branch_id: str
    parent_branch_id: str | None = None
    originating_turn_index: int = Field(..., ge=0)
    # Display only — branches are identified by `branch_id`.
    label: str = Field(..., min_length=1, description="Short human label for display, e.g. 'Option 2'.")
    base_mode: PlanningBaseMode
    status: BranchStatus

    active_requirements: PlanningRequirements = Field(
        ..., description="The exact merged requirements this branch was planned under — its full audit record."
    )
    metrics: BranchMetrics

    verified_factory: Factory = Field(
        ...,
        description=(
            "This branch's verified final factory. Carried so a later turn can continue planning "
            "FROM it (PlanningBaseMode.CURRENT_VERIFIED_STATE) without re-running, and therefore "
            "without any risk of producing a different answer than the one already shown."
        ),
    )
    verified_layout: FactoryLayout | None = None

    summary: str = Field("", description="One deterministic sentence describing this branch's outcome.")


# Comparison


class BranchMetricDelta(BaseModel):
    """One compared metric."""

    model_config = {"frozen": True}

    metric: str
    label: str
    value_a: float | int | bool | str | None = None
    value_b: float | int | bool | str | None = None
    delta: float | None = None
    unit: str | None = None


class BranchComparison(BaseModel):
    """A fully deterministic comparison of two branches (Phase 7C section 11)."""

    model_config = {"frozen": True}

    branch_a_id: str
    branch_b_id: str
    label_a: str
    label_b: str
    metrics: list[BranchMetricDelta] = Field(default_factory=list)
    machines_only_in_a: list[str] = Field(default_factory=list)
    machines_only_in_b: list[str] = Field(default_factory=list)
    constraint_differences: list[str] = Field(default_factory=list)
    unknown_information: list[str] = Field(
        default_factory=list, description="Facts that could not be compared, stated rather than silently omitted."
    )
    headline: str = Field("", description="One deterministic sentence stating the primary difference.")


# Turn


class TurnProvenance(BaseModel):
    """Where each stage of ONE turn's output came from."""

    model_config = {"frozen": True}

    update_source: UpdateSource
    planning_source: str = Field("NONE", description="DETERMINISTIC | LLM | MIXED | NONE")
    explanation_source: str = Field("NONE", description="DETERMINISTIC | LLM | NONE")
    fallback_used: bool = False
    provider_name: str | None = None
    model_name: str | None = None

    prompt_tokens: int | None = Field(None, ge=0)
    completion_tokens: int | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, ge=0, description="Tokens consumed by THIS turn across every LLM call it made.")


class ConversationTurn(BaseModel):
    """One user message and everything Fabrivium did about it."""

    model_config = {"frozen": True}

    turn_index: int = Field(..., ge=0)
    raw_user_message: str
    status: TurnStatus

    interpreted_update: RequirementUpdate | None = None
    intent_summary: str = ""

    requirements_before: PlanningRequirements | None = None
    requirements_after: PlanningRequirements | None = None
    changes: list[str] = Field(
        default_factory=list,
        description="Deterministic, human-readable diff of requirements_before -> requirements_after, e.g. 'Max CAPEX: EUR 220,000 -> EUR 150,000'. Rendered from the typed values, never model prose.",
    )

    branch_id: str | None = Field(None, description="The branch this turn produced; null when no planning ran.")
    base_mode: PlanningBaseMode | None = None
    clarification: ClarificationRequest | None = None
    explanation: PlanningExplanation | None = None

    provenance: TurnProvenance
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        """True when this turn actually changed planning state."""
        return self.status is TurnStatus.APPLIED


# Session


class ConversationSession(BaseModel):
    """The whole conversation, round-tripped between client and server."""

    model_config = {"frozen": True}

    conversation_id: str
    product_id: str

    baseline_factory: Factory = Field(
        ..., description="The factory the conversation started from. NEVER mutated by any turn — every branch plans from a copy."
    )
    baseline_layout: FactoryLayout | None = None

    turns: list[ConversationTurn] = Field(default_factory=list)
    branches: list[PlanningBranch] = Field(default_factory=list)
    active_branch_id: str | None = None

    active_requirements: PlanningRequirements | None = Field(
        None, description="The constraints Fabrivium currently believes. Null before the first turn resolves."
    )
    status: ConversationStatus = ConversationStatus.ACTIVE
    max_iterations: int = Field(5, ge=1, le=20)

    def branch(self, branch_id: str | None) -> PlanningBranch | None:
        if branch_id is None:
            return None
        return next((b for b in self.branches if b.branch_id == branch_id), None)

    @property
    def active_branch(self) -> PlanningBranch | None:
        return self.branch(self.active_branch_id)
