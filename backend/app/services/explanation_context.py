"""Compact verified-facts payload builder for Fabrivium Phase 5D."""

from __future__ import annotations

from app.models.explanation import ExplanationBudgetFacts, ExplanationContext, ExplanationIterationFact
from app.models.orchestrator import PlanningIteration, PlanningSessionState
from app.services.scenario import describe_scenario_action

_UNKNOWN_COST_RISK_TEXT = "Cost impact is not yet estimated."


def _action_summary(iteration: PlanningIteration) -> str:
    if iteration.selected_proposal is None:
        return iteration.rejection_reason or "No proposal was selected."
    # Rendering lives in app.services.scenario.describe_scenario_action —
    # one implementation shared with the orchestrator's trace lines, so a
    # new action type can never be readable in one place and nonsense in
    # the other (Phase 8A found exactly that: "CHANGE_SHIFT_CONFIGURATION
    # at None." in verified explanations).
    parts = [describe_scenario_action(a) for a in iteration.selected_proposal.scenario.actions]
    return "; ".join(parts) if parts else iteration.selected_proposal.scenario.name


def _machine_ids(iteration: PlanningIteration) -> list[str]:
    if iteration.selected_proposal is None:
        return []
    ids = {
        getattr(a, "machine_id", None)
        for a in iteration.selected_proposal.scenario.actions
        if getattr(a, "machine_id", None) is not None
    }
    return sorted(ids)


def _iteration_fact(iteration: PlanningIteration) -> ExplanationIterationFact:
    n = iteration.iteration_index + 1
    refs = [f"iteration:{n}:action"]

    verdict = None
    demand_gap_before = demand_gap_after = None
    demand_met_after = None
    bottleneck_before = bottleneck_after = None

    if iteration.scenario_result is not None:
        refs.append(f"iteration:{n}:scenario_result")
        refs.append(f"iteration:{n}:simulation:demand_gap")
        refs.append(f"iteration:{n}:bottleneck")
        verdict = iteration.scenario_result.verdict.value
        before, after = iteration.scenario_result.baseline_result, iteration.scenario_result.candidate_result
        demand_gap_before, demand_gap_after = before.demand_gap_units, after.demand_gap_units
        demand_met_after = after.demand_met
        bottleneck_before = before.system.bottleneck_machine_id
        bottleneck_after = after.system.bottleneck_machine_id

    if iteration.known_capex is not None:
        refs.append(f"iteration:{n}:capex")

    return ExplanationIterationFact(
        iteration_number=n,
        accepted=iteration.accepted,
        action_summary=_action_summary(iteration),
        machine_ids=_machine_ids(iteration),
        verdict=verdict,
        demand_gap_before=demand_gap_before,
        demand_gap_after=demand_gap_after,
        demand_met_after=demand_met_after,
        bottleneck_before=bottleneck_before,
        bottleneck_after=bottleneck_after,
        known_capex=iteration.known_capex,
        requires_cost_estimate=iteration.requires_cost_estimate,
        rejection_reason=iteration.rejection_reason,
        evidence_refs=refs,
    )


def _unresolved_cost_warnings(session_state: PlanningSessionState) -> list[str]:
    if session_state.goal_reached or not session_state.iterations:
        return []
    last = session_state.iterations[-1]
    machine_ids: set[str] = set()
    for proposal in last.planning_agent_result.proposals:
        if any(_UNKNOWN_COST_RISK_TEXT in risk for risk in proposal.risks):
            for action in proposal.scenario.actions:
                machine_id = getattr(action, "machine_id", None)
                if machine_id is not None:
                    machine_ids.add(machine_id)
    if not machine_ids:
        return []
    return [
        f"Cost impact of a candidate intervention at {', '.join(sorted(machine_ids))} is unknown; "
        f"Fabrivium never autonomously executes an unknown-cost change — provide a cost estimate "
        f"for it to be considered."
    ]


def build_explanation_context(session_state: PlanningSessionState) -> ExplanationContext:
    """Build a compact ``ExplanationContext`` from *session_state*."""
    requirements = session_state.original_requirements
    baseline = session_state.baseline_simulation
    final = session_state.current_simulation

    accepted = [_iteration_fact(it) for it in session_state.iterations if it.accepted]
    rejected = [_iteration_fact(it) for it in session_state.iterations if not it.accepted]

    layout_supplied = session_state.current_layout is not None
    layout_valid: bool | None = None
    if layout_supplied:
        for it in reversed(session_state.iterations):
            if it.layout_validation is not None:
                layout_valid = it.layout_validation.valid
                break

    known_machine_ids = sorted({m.id for m in session_state.current_factory.machines} | {m.id for m in session_state.baseline_factory.machines})

    warnings = _unresolved_cost_warnings(session_state)
    if session_state.stop_reason is not None and session_state.stop_reason.value == "BUDGET_EXHAUSTED":
        warnings.append(
            "No remaining known-cost intervention fit the remaining budget — "
            f"€{session_state.remaining_known_capex:,.0f} known remaining." if session_state.remaining_known_capex is not None
            else "No remaining known-cost intervention fit the budget."
        )

    return ExplanationContext(
        session_id=session_state.session_id,
        objective=requirements.objective.value,
        target_units_per_day=requirements.target_units_per_day,
        forbidden_machine_ids=list(requirements.forbidden_machine_ids),
        baseline_demand_met=baseline.demand_met,
        baseline_demand_gap=baseline.demand_gap_units,
        baseline_bottleneck=baseline.system.bottleneck_machine_id,
        baseline_completed_units=baseline.completed_units,
        baseline_target_units=baseline.target_units,
        final_demand_met=final.demand_met,
        final_demand_gap=final.demand_gap_units,
        final_bottleneck=final.system.bottleneck_machine_id,
        final_completed_units=final.completed_units,
        final_target_units=final.target_units,
        layout_supplied=layout_supplied,
        layout_valid=layout_valid,
        accepted_iterations=accepted,
        rejected_iterations=rejected,
        budget=ExplanationBudgetFacts(
            max_capex=requirements.max_capex,
            cumulative_known_capex=session_state.cumulative_known_capex,
            remaining_known_capex=session_state.remaining_known_capex,
        ),
        stop_reason=session_state.stop_reason.value if session_state.stop_reason is not None else "NONE",
        goal_reached=session_state.goal_reached,
        known_machine_ids=known_machine_ids,
        warnings=warnings,
    )
