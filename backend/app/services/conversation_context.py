"""Compact conversation context for Fabrivium Phase 7C (sections 6 and 21)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.agent import PlanningRequirements
from app.models.conversation import ConversationSession, TurnStatus
from app.models.factory import Factory

# How many previous turns to show.
DEFAULT_MAX_TURNS = 4


class ConversationMachineRef(BaseModel):
    """The minimum a model needs to resolve "Packaging" to a real id."""

    model_config = {"frozen": True}
    id: str
    name: str
    process_type: str


class ConversationTurnSummary(BaseModel):
    model_config = {"frozen": True}
    turn: int
    user_message: str
    outcome: str = Field(..., description="The turn's status, e.g. APPLIED / CLARIFICATION_REQUIRED.")
    changes: list[str] = Field(default_factory=list)


class ConversationPlanSummary(BaseModel):
    """The active branch's VERIFIED outcome, flattened to plain values."""

    model_config = {"frozen": True}
    branch_id: str
    label: str
    goal_reached: bool
    stop_reason: str
    completed_units: int
    target_units: int
    demand_gap_units: float
    cumulative_known_capex: float
    remaining_known_capex: float | None = None
    bottleneck_machine_id: str
    added_machine_ids: list[str] = Field(default_factory=list)


class ConversationContext(BaseModel):
    """The ONLY conversational payload an update parser receives."""

    model_config = {"frozen": True}

    factory_name: str
    machines: list[ConversationMachineRef] = Field(default_factory=list)
    active_requirements: PlanningRequirements | None = None
    recent_turns: list[ConversationTurnSummary] = Field(default_factory=list)
    current_plan: ConversationPlanSummary | None = None
    other_branch_labels: list[str] = Field(
        default_factory=list, description="Labels of the other alternatives that exist, so references like 'the first option' are resolvable."
    )
    turn_count: int = 0


def build_conversation_context(
    session: ConversationSession,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> ConversationContext:
    """Build the compact context for *session*'s NEXT turn."""
    factory: Factory = session.baseline_factory

    machines = [
        ConversationMachineRef(id=m.id, name=m.name, process_type=m.process_type)
        for m in factory.machines
    ]

    # Only turns that actually meant something.
    meaningful = [
        turn for turn in session.turns
        if turn.status in (TurnStatus.APPLIED, TurnStatus.CLARIFICATION_REQUIRED, TurnStatus.REJECTED)
    ]
    recent = [
        ConversationTurnSummary(
            turn=turn.turn_index,
            user_message=turn.raw_user_message,
            outcome=turn.status.value,
            changes=list(turn.changes),
        )
        for turn in meaningful[-max_turns:]
    ]

    active = session.active_branch
    current_plan = None
    if active is not None:
        metrics = active.metrics
        current_plan = ConversationPlanSummary(
            branch_id=active.branch_id,
            label=active.label,
            goal_reached=metrics.goal_reached,
            stop_reason=metrics.stop_reason,
            completed_units=metrics.completed_units,
            target_units=metrics.target_units,
            demand_gap_units=metrics.demand_gap_units,
            cumulative_known_capex=metrics.cumulative_known_capex,
            remaining_known_capex=metrics.remaining_known_capex,
            bottleneck_machine_id=metrics.bottleneck_machine_id,
            added_machine_ids=list(metrics.added_machine_ids),
        )

    return ConversationContext(
        factory_name=factory.name,
        machines=machines,
        active_requirements=session.active_requirements,
        recent_turns=recent,
        current_plan=current_plan,
        other_branch_labels=[b.label for b in session.branches if b.branch_id != session.active_branch_id],
        turn_count=len(session.turns),
    )
