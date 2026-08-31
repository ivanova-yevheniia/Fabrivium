"""Conversational turn orchestration for Fabrivium Phase 7C (section 7)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.llm.errors import LLMProviderError
from app.llm.models import LLMInvocationRecord
from app.llm.provider import LLMProvider
from app.models.agent import PlanningRequirements
from app.models.conversation import (
    BranchMetrics,
    BranchStatus,
    ClarificationRequest,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
    PlanningBaseMode,
    PlanningBranch,
    RequirementUpdate,
    TurnProvenance,
    TurnStatus,
    UpdateSource,
)
from app.models.explanation import PlanningExplanation
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.optimization import OptimizationObjective
from app.models.orchestrator import PlanningSessionState
from app.services.conversation_context import build_conversation_context
from app.services.conversation_parser import (
    ConservativeFollowUpParser,
    LLMConversationRequirementParser,
    UnsupportedFollowUp,
)
from app.services.explanation_context import build_explanation_context
from app.services.llm_integration import (
    build_update_completion_fn,
    explain_with_fallback,
    run_planning_session_with_fallback,
)
from app.services.requirement_update import apply_requirement_update

_BRANCH_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class TurnResult:
    """What one turn produced."""

    session: ConversationSession
    turn: ConversationTurn
    planning_session: PlanningSessionState | None = None


# Baseline-mode resolution (Phase 7C section 8)


def resolve_base_mode(
    update: RequirementUpdate,
    before: PlanningRequirements | None,
    after: PlanningRequirements,
    active_branch: PlanningBranch | None,
) -> tuple[PlanningBaseMode, list[str]]:
    """Decide which verified state this turn plans FROM, and say why."""
    reasons: list[str] = []

    if active_branch is None:
        return PlanningBaseMode.ORIGINAL_BASELINE, ["No previous plan to continue from."]

    metrics = active_branch.metrics

    if after.max_capex is not None and metrics.cumulative_known_capex > after.max_capex:
        reasons.append(
            f"Replanned from the original factory: the current plan has already committed "
            f"EUR {metrics.cumulative_known_capex:,.0f}, which exceeds the new budget of "
            f"EUR {after.max_capex:,.0f} — that spend cannot be undone by continuing."
        )
        return PlanningBaseMode.ORIGINAL_BASELINE, reasons

    newly_locked = set(after.forbidden_machine_ids) - set(before.forbidden_machine_ids if before else [])
    already_modified = newly_locked & set(metrics.added_machine_ids)
    if already_modified:
        reasons.append(
            f"Replanned from the original factory: the current plan already modified "
            f"{', '.join(sorted(already_modified))}, which this turn asked to leave untouched."
        )
        return PlanningBaseMode.ORIGINAL_BASELINE, reasons

    if before is not None and after.target_units_per_day is not None and before.target_units_per_day is not None:
        if after.target_units_per_day < before.target_units_per_day:
            reasons.append(
                "Replanned from the original factory: the target was lowered, so the existing "
                "plan's added capacity may no longer be needed."
            )
            return PlanningBaseMode.ORIGINAL_BASELINE, reasons

    if update.base_mode is PlanningBaseMode.CURRENT_VERIFIED_STATE:
        reasons.append(f"Continued from the verified result of {active_branch.label}.")
        return PlanningBaseMode.CURRENT_VERIFIED_STATE, reasons

    reasons.append("Replanned from the original factory (default for a constraint change).")
    return PlanningBaseMode.ORIGINAL_BASELINE, reasons


# Branch construction


def _added_machine_ids(session: PlanningSessionState) -> list[str]:
    """Machine ids the ACCEPTED iterations targeted, in order."""
    ids: list[str] = []
    for iteration in session.iterations:
        if not iteration.accepted or iteration.selected_proposal is None:
            continue
        for action in iteration.selected_proposal.scenario.actions:
            machine_id = getattr(action, "machine_id", None)
            if machine_id is not None and machine_id not in ids:
                ids.append(machine_id)
    return ids


def build_branch_metrics(session: PlanningSessionState) -> BranchMetrics:
    """Flatten a verified ``PlanningSessionState`` into comparable KPIs."""
    final = session.final_snapshot
    simulation = final.simulation
    explanation_context = build_explanation_context(session)

    return BranchMetrics(
        goal_reached=session.goal_reached,
        stop_reason=session.stop_reason.value if session.stop_reason else "NONE",
        demand_met=simulation.demand_met,
        completed_units=simulation.completed_units,
        target_units=simulation.target_units,
        demand_gap_units=simulation.demand_gap_units,
        work_in_progress=simulation.system.work_in_progress,
        average_flow_time_seconds=simulation.system.average_flow_time_seconds,
        bottleneck_machine_id=final.bottleneck_machine_id,
        max_capex=session.original_requirements.max_capex,
        cumulative_known_capex=final.cumulative_known_capex,
        remaining_known_capex=final.remaining_known_capex,
        added_machine_ids=_added_machine_ids(session),
        accepted_iterations=sum(1 for it in session.iterations if it.accepted),
        total_iterations=len(session.iterations),
        warnings=list(explanation_context.warnings),
    )


def _branch_summary(metrics: BranchMetrics) -> str:
    """One deterministic sentence."""
    money = f"EUR {metrics.cumulative_known_capex:,.0f}"
    if metrics.goal_reached:
        return f"Target reached at {metrics.completed_units:,}/day for {money}."
    return (
        f"Target not reached: {metrics.completed_units:,}/{metrics.target_units:,}/day "
        f"({metrics.demand_gap_units:,.0f} short) for {money}."
    )


# Orchestrator


class ConversationOrchestrator:
    """Runs one conversational turn end to end."""

    def __init__(self, *, max_context_turns: int = 4) -> None:
        self._max_context_turns = max_context_turns

    # Session lifecycle

    @staticmethod
    def start(
        factory: Factory,
        product_id: str,
        *,
        layout: FactoryLayout | None = None,
        max_iterations: int = 5,
        conversation_id: str | None = None,
    ) -> ConversationSession:
        """Create an empty conversation."""
        if product_id not in {p.id for p in factory.products}:
            raise ValueError(f"Unknown product_id '{product_id}'.")
        return ConversationSession(
            conversation_id=conversation_id or f"conv-{uuid.uuid4().hex[:12]}",
            product_id=product_id,
            baseline_factory=factory,
            baseline_layout=layout,
            max_iterations=max_iterations,
        )

    # The turn

    def run_turn(
        self,
        session: ConversationSession,
        user_message: str,
        provider: LLMProvider | None,
    ) -> TurnResult:
        """Execute one turn against *session*, returning a NEW session."""
        turn_index = len(session.turns)
        records: list[LLMInvocationRecord] = []
        context = build_conversation_context(session, max_turns=self._max_context_turns)

        # 1. interpret
        try:
            update, update_source = self._interpret(user_message, context, provider, records)
        except UnsupportedFollowUp as exc:
            return self._unresolved_turn(
                session, turn_index, user_message,
                status=TurnStatus.PROVIDER_UNAVAILABLE,
                errors=[
                    "The request could not be interpreted right now, so nothing was changed. "
                    "Try stating the constraint explicitly, for example 'keep CAPEX below EUR 150,000'."
                ],
                records=records, provider=provider, detail=str(exc),
            )

        if update.clarification_required:
            return self._unresolved_turn(
                session, turn_index, user_message,
                status=TurnStatus.CLARIFICATION_REQUIRED,
                clarification=update.clarification or _default_clarification(),
                update=update, update_source=update_source,
                records=records, provider=provider,
            )

        # 2. merge deterministically
        before = session.active_requirements
        base_requirements = before if before is not None else _seed_requirements(update)
        application = apply_requirement_update(base_requirements, update, session.baseline_factory)

        if application.rejected:
            return self._unresolved_turn(
                session, turn_index, user_message,
                status=TurnStatus.REJECTED,
                errors=application.rejected, warnings=application.warnings,
                update=update, update_source=update_source,
                records=records, provider=provider,
            )

        after = application.requirements
        first_turn = before is None

        if not first_turn and not application.changed:
            return self._unresolved_turn(
                session, turn_index, user_message,
                status=TurnStatus.NO_CHANGE,
                warnings=[*application.warnings, "Nothing in the active constraints changed, so the current plan still stands."],
                update=update, update_source=update_source,
                records=records, provider=provider,
            )

        # 3. which verified state do we plan FROM?
        base_mode, base_reasons = resolve_base_mode(update, before, after, session.active_branch)
        plan_factory, plan_layout, initial_capex = self._planning_base(session, base_mode)

        # 4. deterministic planning (unmodified Phase 5C)
        session_id = f"{session.conversation_id}-t{turn_index}"
        if initial_capex > 0.0:
            planning_session, planning_fallback = self._run_continuation(
                session, after, provider, plan_factory, plan_layout, initial_capex, records, session_id,
            )
        else:
            planning_session, planning_fallback = run_planning_session_with_fallback(
                plan_factory, session.product_id, after, provider,
                layout=plan_layout, max_iterations=session.max_iterations,
                on_invocation=records.append,
            )
            # The orchestrator's own session_id is per-run; a conversation
            # keys its history on the branch id instead, so stamp this one
            # with the turn it came from for traceability.
            planning_session = planning_session.model_copy(update={"session_id": session_id})

        # 5. explanation (unmodified Phase 5D + hallucination guard)
        explanation_context = build_explanation_context(planning_session)
        explanation_result, explanation_fallback = explain_with_fallback(
            explanation_context, provider, on_invocation=records.append,
        )

        # 6. append an immutable branch and turn
        metrics = build_branch_metrics(planning_session)
        branch = PlanningBranch(
            branch_id=f"branch-{turn_index}-{uuid.uuid4().hex[:6]}",
            parent_branch_id=session.active_branch_id,
            originating_turn_index=turn_index,
            label=f"Plan {_BRANCH_LABELS[len(session.branches) % len(_BRANCH_LABELS)]}",
            base_mode=base_mode,
            status=BranchStatus.GOAL_REACHED if metrics.goal_reached else BranchStatus.GOAL_NOT_REACHED,
            active_requirements=after,
            metrics=metrics,
            verified_factory=planning_session.current_factory,
            verified_layout=planning_session.current_layout,
            summary=_branch_summary(metrics),
        )

        turn = ConversationTurn(
            turn_index=turn_index,
            raw_user_message=user_message,
            status=TurnStatus.APPLIED,
            interpreted_update=update,
            intent_summary=update.intent_summary,
            requirements_before=before,
            requirements_after=after,
            changes=application.changes if not first_turn else _initial_changes(after),
            branch_id=branch.branch_id,
            base_mode=base_mode,
            explanation=explanation_result.explanation,
            provenance=_provenance(
                update_source=update_source,
                planning_session=planning_session,
                explanation=explanation_result.explanation,
                fallback_used=planning_fallback or explanation_fallback,
                provider=provider, records=records,
            ),
            warnings=[*application.warnings, *base_reasons],
        )

        return TurnResult(
            session=session.model_copy(update={
                "turns": [*session.turns, turn],
                "branches": [*session.branches, branch],
                "active_branch_id": branch.branch_id,
                "active_requirements": after,
                "status": ConversationStatus.ACTIVE,
            }),
            turn=turn,
            planning_session=planning_session,
        )

    # Helpers

    def _interpret(
        self,
        user_message: str,
        context,
        provider: LLMProvider | None,
        records: list[LLMInvocationRecord],
    ) -> tuple[RequirementUpdate, UpdateSource]:
        """Interpret via the provider, falling back to the CONSERVATIVE parser only."""
        if provider is not None:
            try:
                parser = LLMConversationRequirementParser(
                    completion_fn=build_update_completion_fn(provider, on_invocation=records.append)
                )
                return parser.parse_update(user_message, context), UpdateSource.LLM
            except (LLMProviderError, UnsupportedFollowUp):
                pass  # fall through to the conservative parser

        return ConservativeFollowUpParser().parse_update(user_message, context), UpdateSource.DETERMINISTIC

    def _planning_base(
        self, session: ConversationSession, base_mode: PlanningBaseMode
    ) -> tuple[Factory, FactoryLayout | None, float]:
        """Resolve (factory, layout, already-committed spend) to plan from."""
        active = session.active_branch
        if base_mode is PlanningBaseMode.CURRENT_VERIFIED_STATE and active is not None:
            return active.verified_factory, active.verified_layout, active.metrics.cumulative_known_capex
        return session.baseline_factory, session.baseline_layout, 0.0

    def _run_continuation(
        self, session, requirements, provider, plan_factory, plan_layout, initial_capex, records, session_id,
    ) -> tuple[PlanningSessionState, bool]:
        """Plan onward from an already-paid-for state, carrying its spend."""
        from app.services.llm_integration import build_planning_completion_fn
        from app.services.planning_agent import LLMPlanningAgent
        from app.services.planning_orchestrator import PlanningOrchestrator

        def _deterministic() -> PlanningSessionState:
            return PlanningOrchestrator().run(
                plan_factory, session.product_id, requirements,
                layout=plan_layout, max_iterations=session.max_iterations,
                session_id=session_id, initial_cumulative_capex=initial_capex,
            )

        if provider is None:
            return _deterministic(), False

        agent = LLMPlanningAgent(
            completion_fn=build_planning_completion_fn(provider, on_invocation=records.append)
        )
        try:
            return PlanningOrchestrator().run(
                plan_factory, session.product_id, requirements,
                layout=plan_layout, max_iterations=session.max_iterations,
                planning_agent=agent, session_id=session_id,
                initial_cumulative_capex=initial_capex,
            ), False
        except LLMProviderError:
            return _deterministic(), True

    def _unresolved_turn(
        self,
        session: ConversationSession,
        turn_index: int,
        user_message: str,
        *,
        status: TurnStatus,
        clarification: ClarificationRequest | None = None,
        update: RequirementUpdate | None = None,
        update_source: UpdateSource = UpdateSource.NONE,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        records: list[LLMInvocationRecord] | None = None,
        provider: LLMProvider | None = None,
        detail: str | None = None,
    ) -> TurnResult:
        """Record a turn that changed NO engineering state."""
        turn = ConversationTurn(
            turn_index=turn_index,
            raw_user_message=user_message,
            status=status,
            interpreted_update=update,
            intent_summary=update.intent_summary if update is not None else "",
            requirements_before=session.active_requirements,
            requirements_after=session.active_requirements,
            changes=[],
            branch_id=None,
            clarification=clarification,
            provenance=_provenance(
                update_source=update_source, planning_session=None, explanation=None,
                fallback_used=status is TurnStatus.PROVIDER_UNAVAILABLE,
                provider=provider, records=records or [],
            ),
            warnings=warnings or [],
            errors=[*(errors or []), *([f"Detail: {detail}"] if detail else [])],
        )
        return TurnResult(
            session=session.model_copy(update={
                "turns": [*session.turns, turn],
                "status": (
                    ConversationStatus.AWAITING_CLARIFICATION
                    if status is TurnStatus.CLARIFICATION_REQUIRED
                    else ConversationStatus.ACTIVE
                ),
            }),
            turn=turn,
        )


# Small pure helpers


def _seed_requirements(update: RequirementUpdate) -> PlanningRequirements:
    """The empty requirements a FIRST turn patches onto."""
    return PlanningRequirements(objective=update.objective or OptimizationObjective.MEET_DEMAND)


def _initial_changes(requirements: PlanningRequirements) -> list[str]:
    """Render the FIRST turn's constraints as changes, so the conversation
    log opens with what was understood rather than an empty diff."""
    changes = [f"Objective: {requirements.objective.value}"]
    if requirements.target_units_per_day is not None:
        changes.append(f"Target: {requirements.target_units_per_day:,.0f}/day")
    if requirements.max_capex is not None:
        changes.append(f"Max CAPEX: EUR {requirements.max_capex:,.0f}")
    for machine_id in requirements.forbidden_machine_ids:
        changes.append(f"Locked: {machine_id} may not be modified")
    if requirements.preserve_existing_layout:
        changes.append("Preserve existing layout: on")
    return changes


def _default_clarification() -> ClarificationRequest:
    return ClarificationRequest(
        question="What should I optimise for?",
        ambiguous_fields=["objective"],
        safe_options=[
            "Meet a specific daily demand target",
            "Maximise throughput",
            "Minimise work in progress",
            "Minimise flow time",
        ],
    )


def _provenance(
    *,
    update_source: UpdateSource,
    planning_session: PlanningSessionState | None,
    explanation: PlanningExplanation | None,
    fallback_used: bool,
    provider: LLMProvider | None,
    records: list[LLMInvocationRecord],
) -> TurnProvenance:
    """Build this turn's provenance, including the tokens it actually spent."""
    planning_source = "NONE"
    if planning_session is not None:
        sources = {it.planning_agent_result.agent_type.value for it in planning_session.iterations}
        if not sources:
            planning_source = "NONE"
        elif sources == {"LLM"}:
            planning_source = "LLM"
        elif sources == {"DETERMINISTIC"}:
            planning_source = "DETERMINISTIC"
        else:
            planning_source = "MIXED"

    def _total(field: str) -> int | None:
        values = [getattr(r, field) for r in records if getattr(r, field) is not None]
        return sum(values) if values else None

    return TurnProvenance(
        update_source=update_source,
        planning_source=planning_source,
        explanation_source=explanation.source_type.value if explanation is not None else "NONE",
        fallback_used=fallback_used,
        provider_name=provider.provider_name if provider is not None else None,
        model_name=provider.model_name if provider is not None else None,
        prompt_tokens=_total("prompt_tokens"),
        completion_tokens=_total("completion_tokens"),
        total_tokens=_total("total_tokens"),
    )
