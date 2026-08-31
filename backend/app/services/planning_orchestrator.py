"""Iterative Planning Orchestrator for Fabrivium Phase 5C."""

from __future__ import annotations

from app.models.constraints import LayoutValidationResult
from app.models.evaluation import CandidateEvaluation, CandidateFeasibilityStatus
from app.models.factory import Factory
from app.models.layout import FactoryLayout
from app.models.optimization import GenerationSource, OptimizationCandidate
from app.models.orchestrator import (
    PlanningIteration,
    PlanningSessionState,
    PlanningStateSnapshot,
    PlanningStopReason,
)
from app.models.agent import PlanningRequirements
from app.models.planning_agent import PlanningContext, PlanningProposal
from app.models.scenario import Scenario
from app.models.simulation import SimulationResult
from app.services.candidate_evaluator import _evaluate_one, evaluate_candidates
from app.services.budget import remaining_known_capex
from app.services.scenario import describe_scenario_action
from app.services.candidate_generator import _expand_forbidden_machine_ids
from app.services.constraints import validate_layout
from app.services.goal_checker import is_acceptable_improvement, is_goal_reached
from app.services.placement_search import DEFAULT_GRID_SPACING, DEFAULT_MAX_POSITION_ATTEMPTS
from app.services.planning_agent import (
    DeterministicPlanningAgent,
    PlanningAgent,
    _scenario_key,
    run_planning_agent,
)
from app.services.planning_context import build_planning_context
from app.services.ranking import rank_candidates
from app.services.requirements_parser import apply_target_demand, planning_requirements_to_optimization_goal
from app.services.simulation import run_simulation

DEFAULT_SESSION_ID = "session"

_NO_PROPOSAL_TEXT = "The planning agent returned no proposals for the current state."
_REPEATED_TEXT = "Every remaining proposal has already been evaluated in this session."
_BUDGET_TEXT = "No remaining proposal fits the remaining known budget without relying on an unknown cost."
_USER_CONSTRAINT_TEXT = (
    "No valid proposal: the current bottleneck sits on the forbidden-machine list, "
    "and no other congestion is available to target."
)

_SELECTION_STOP_TEXT = {
    PlanningStopReason.REPEATED_PROPOSAL: _REPEATED_TEXT,
    PlanningStopReason.NO_VALID_PROPOSAL: _NO_PROPOSAL_TEXT,
    PlanningStopReason.BUDGET_EXHAUSTED: _BUDGET_TEXT,
}

_KNOWN_FEASIBLE_STATUSES = {"RECOMMENDED", "PARETO_OPTIMAL", "FEASIBLE"}
_CAPEX_EPSILON = 1e-6


# Deterministic string rendering (Phase 5C section 14 — never LLM prose)

def _process_name(machine_id: str | None, context: PlanningContext) -> str:
    if machine_id is None:
        return "unknown"
    for pool in context.pool_summaries:
        if pool.reference_machine_id == machine_id:
            return pool.process_step_name
    return machine_id


def _scenario_summary(scenario: Scenario) -> str:
    # See describe_scenario_action: shared with explanation_context so trace
    # lines and explanation facts can never describe the same action
    # differently.
    parts = [describe_scenario_action(a) for a in scenario.actions]
    return "; ".join(parts) if parts else scenario.name


def _render_observation(simulation: SimulationResult, context: PlanningContext) -> str:
    bottleneck_name = _process_name(simulation.system.bottleneck_machine_id, context)
    if simulation.demand_met:
        return f"Demand met ({simulation.completed_units}/{simulation.target_units} units). Bottleneck: {bottleneck_name}."
    return f"Demand gap: {simulation.demand_gap_units:g}. Bottleneck: {bottleneck_name}."


def _render_stop_trace(iteration_index: int, reason: PlanningStopReason, text: str) -> list[str]:
    return [f"Iteration {iteration_index + 1}:", f"Stop: {reason.value}. {text}"]


def _render_accept_trace(iteration_index: int, selected: PlanningProposal, scenario_result, new_bottleneck_name: str) -> list[str]:
    before, after = scenario_result.baseline_result, scenario_result.candidate_result
    return [
        f"Iteration {iteration_index + 1}:",
        f"Proposed: {_scenario_summary(selected.scenario)}.",
        "Validation: passed.",
        f"Simulation: {scenario_result.verdict.value.lower()}.",
        f"Demand gap: {before.demand_gap_units:g} -> {after.demand_gap_units:g}.",
        f"New bottleneck: {new_bottleneck_name}.",
        "Accepted.",
    ]


def _render_reject_trace(iteration_index: int, selected: PlanningProposal, scenario_result, reason_text: str) -> list[str]:
    before, after = scenario_result.baseline_result, scenario_result.candidate_result
    return [
        f"Iteration {iteration_index + 1}:",
        f"Proposed: {_scenario_summary(selected.scenario)}.",
        "Validation: passed.",
        f"Simulation: {scenario_result.verdict.value.lower()}.",
        f"Demand gap: {before.demand_gap_units:g} -> {after.demand_gap_units:g}.",
        f"Rejected: {reason_text}",
    ]


def _render_infeasible_trace(iteration_index: int, selected: PlanningProposal, reason_text: str) -> list[str]:
    return [
        f"Iteration {iteration_index + 1}:",
        f"Proposed: {_scenario_summary(selected.scenario)}.",
        f"Rejected: {reason_text}",
    ]


def render_trace(state: PlanningSessionState) -> str:
    """
    Assemble the full compact, deterministic session trace (Phase 5C section 14) —
    suitable for later frontend display.
    """
    lines: list[str] = ["Iteration 0:", "Baseline simulated."]
    if state.iterations:
        lines.append(state.iterations[0].observation)
    else:
        sim = state.current_simulation
        if sim.demand_met:
            lines.append(f"Demand met ({sim.completed_units}/{sim.target_units} units).")
        else:
            lines.append(f"Demand gap: {sim.demand_gap_units:g}.")
        lines.append(f"Bottleneck: {sim.system.bottleneck_machine_id}.")

    blocks = ["\n".join(lines)]
    blocks.extend("\n".join(it.trace) for it in state.iterations)
    blocks.append(f"Stop reason: {state.stop_reason.value if state.stop_reason else 'NONE'}.")
    return "\n\n".join(blocks)


# Cost estimation for a proposal outside Phase 4A's own candidate universe

def _estimate_capex(scenario: Scenario, factory: Factory) -> tuple[float, bool]:
    """
    Mirrors ``app.services.candidate_generator``'s known-cost rule exactly
    (ADD_PARALLEL_MACHINE contributes its source machine's ``purchase_cost``; anything
    else is unknown) — used only to build a synthetic ``OptimizationCandidate`` for a
    proposal the optimizer itself never generated (e.g.
    """
    machine_by_id = {m.id: m for m in factory.machines}
    known = 0.0
    requires_estimate = False
    for action in scenario.actions:
        if action.action_type == "ADD_PARALLEL_MACHINE":
            source = machine_by_id.get(action.machine_id)
            if source is None or source.purchase_cost is None:
                # No machine, or a machine nobody has priced.
                requires_estimate = True
            else:
                known += source.purchase_cost
        else:
            requires_estimate = True
    return known, requires_estimate


def _candidate_status_and_cost(proposal: PlanningProposal, context: PlanningContext, factory: Factory) -> tuple[str | None, float, bool]:
    key = _scenario_key(proposal.scenario)
    for c in context.candidate_summaries:
        if _scenario_key(c.scenario) == key:
            return c.status, c.known_capex, c.requires_cost_estimate
    known, requires_estimate = _estimate_capex(proposal.scenario, factory)
    return None, known, requires_estimate


def _snapshot(
    factory: Factory,
    layout: FactoryLayout | None,
    simulation: SimulationResult,
    cumulative_known_capex: float,
    max_capex: float | None,
) -> PlanningStateSnapshot:
    """
    Build a ``PlanningStateSnapshot`` from the exact typed domain values already at hand
    — never re-derived from a scenario string (Phase 6A.1 section 2).
    """
    return PlanningStateSnapshot(
        factory=factory,
        layout=layout,
        simulation=simulation,
        bottleneck_machine_id=simulation.system.bottleneck_machine_id,
        cumulative_known_capex=cumulative_known_capex,
        remaining_known_capex=remaining_known_capex(max_capex, cumulative_known_capex),
    )


def _find_matching_evaluation(scenario: Scenario, eval_result) -> CandidateEvaluation | None:
    key = _scenario_key(scenario)
    return next((e for e in eval_result.candidates if _scenario_key(e.candidate.scenario) == key), None)


def _evaluate_proposal(
    proposal: PlanningProposal,
    factory: Factory,
    product_id: str,
    goal,
    layout: FactoryLayout | None,
    baseline_layout_validation: LayoutValidationResult | None,
    eval_result,
    grid_spacing: float,
    max_position_attempts: int,
) -> CandidateEvaluation:
    """Evaluate *proposal* through the EXISTING Phase 4B pipeline."""
    matching = _find_matching_evaluation(proposal.scenario, eval_result)
    if matching is not None:
        return matching

    known_capex, requires_estimate = _estimate_capex(proposal.scenario, factory)
    synthetic = OptimizationCandidate(
        candidate_id=proposal.proposal_id,
        scenario=proposal.scenario,
        rationale="Orchestrator-evaluated proposal outside the optimizer's own candidate universe (e.g. user-requested).",
        generation_source=GenerationSource.BOTTLENECK_RELIEF,
        estimated_capex=known_capex,
        requires_cost_estimate=requires_estimate,
        requires_layout_placement=any(a.action_type == "ADD_PARALLEL_MACHINE" for a in proposal.scenario.actions),
        affected_processes=[],
    )
    return _evaluate_one(
        factory, product_id, goal, layout, baseline_layout_validation, synthetic, grid_spacing, max_position_attempts,
    )


# Deterministic proposal selection (Phase 5C section 5, 8, 9)

def _select_proposal(
    proposals: list[PlanningProposal],
    context: PlanningContext,
    factory: Factory,
    primary_candidate_id: str | None,
    seen_fingerprints: set[tuple],
    remaining_capex: float | None,
) -> tuple[PlanningProposal | None, PlanningStopReason | None]:
    """
    Deterministically choose the next proposal to execute, or explain why none can be
    chosen.
    """
    unseen = []
    for p in proposals:
        key = _scenario_key(p.scenario)
        if key in seen_fingerprints:
            continue
        status, known_capex, requires_estimate = _candidate_status_and_cost(p, context, factory)
        unseen.append((p, status, known_capex, requires_estimate))

    if not unseen:
        reason = PlanningStopReason.REPEATED_PROPOSAL if proposals else PlanningStopReason.NO_VALID_PROPOSAL
        return None, reason

    if remaining_capex is not None:
        affordable = [t for t in unseen if not t[3] and t[2] <= remaining_capex + _CAPEX_EPSILON]
        if not affordable:
            return None, PlanningStopReason.BUDGET_EXHAUSTED
    else:
        affordable = unseen

    def sort_key(t: tuple) -> tuple:
        proposal, status, _known_capex, _requires_estimate = t
        is_primary = 0 if (primary_candidate_id and proposal.proposal_id == f"proposal-{primary_candidate_id}") else 1
        is_known_feasible = 0 if status in _KNOWN_FEASIBLE_STATUSES else 1
        return (is_primary, is_known_feasible, -proposal.confidence, proposal.proposal_id)

    affordable.sort(key=sort_key)
    return affordable[0][0], None


# Orchestrator

class PlanningOrchestrator:
    """Bounded iterative planning loop (Phase 5C). See module docstring."""

    def run(
        self,
        factory: Factory,
        product_id: str,
        requirements: PlanningRequirements,
        layout: FactoryLayout | None = None,
        max_iterations: int = 5,
        planning_agent: PlanningAgent | None = None,
        session_id: str = DEFAULT_SESSION_ID,
        grid_spacing: float = DEFAULT_GRID_SPACING,
        max_position_attempts: int = DEFAULT_MAX_POSITION_ATTEMPTS,
        initial_cumulative_capex: float = 0.0,
    ) -> PlanningSessionState:
        """
        Run the bounded planning loop for *factory*/*product_id* against *requirements*.
        """
        if initial_cumulative_capex < 0.0:
            raise ValueError("initial_cumulative_capex must be >= 0")
        agent = planning_agent or DeterministicPlanningAgent()

        baseline_factory = factory
        baseline_layout = layout

        current_factory = apply_target_demand(factory, product_id, requirements)
        current_layout = layout

        if current_layout is not None:
            initial_layout_validation = validate_layout(current_factory, current_layout, product_id)
            if initial_layout_validation.error_count > 0:
                current_simulation = run_simulation(current_factory, product_id)
                error_snapshot = _snapshot(current_factory, current_layout, current_simulation, initial_cumulative_capex, requirements.max_capex)
                return PlanningSessionState(
                    session_id=session_id,
                    original_requirements=requirements,
                    current_factory=current_factory,
                    current_layout=current_layout,
                    baseline_factory=baseline_factory,
                    baseline_layout=baseline_layout,
                    baseline_simulation=current_simulation,
                    current_simulation=current_simulation,
                    current_best_result=current_simulation,
                    iterations=[],
                    stop_reason=PlanningStopReason.ERROR,
                    goal_reached=False,
                    baseline_snapshot=error_snapshot,
                    final_snapshot=error_snapshot,
                )

        current_simulation = run_simulation(current_factory, product_id)
        baseline_simulation = current_simulation
        baseline_snapshot = _snapshot(current_factory, current_layout, current_simulation, initial_cumulative_capex, requirements.max_capex)

        forbidden_expanded = _expand_forbidden_machine_ids(current_factory, requirements.forbidden_machine_ids)

        cumulative_capex = initial_cumulative_capex
        remaining_capex = remaining_known_capex(requirements.max_capex, cumulative_capex)

        seen_fingerprints: set[tuple] = set()
        history_lines: list[str] = []
        iterations: list[PlanningIteration] = []

        goal_reached = is_goal_reached(requirements.objective, current_simulation)
        stop_reason: PlanningStopReason | None = PlanningStopReason.GOAL_REACHED if goal_reached else None

        iteration_index = 0
        while stop_reason is None:
            if iteration_index >= max_iterations:
                stop_reason = PlanningStopReason.MAX_ITERATIONS
                break

            goal = planning_requirements_to_optimization_goal(
                requirements.model_copy(update={"max_capex": remaining_capex}),
                target_product_id=product_id,
            ).goal

            eval_result = evaluate_candidates(
                current_factory, product_id, goal, layout=current_layout,
                grid_spacing=grid_spacing, max_position_attempts=max_position_attempts,
            )
            recommendation = rank_candidates(eval_result, goal)
            layout_validation = (
                validate_layout(current_factory, current_layout, product_id) if current_layout is not None else None
            )

            context = build_planning_context(
                current_factory, product_id, requirements, current_simulation,
                eval_result, recommendation, layout_validation, proposal_history=history_lines,
            )
            observation = _render_observation(current_simulation, context)
            state_before = _snapshot(current_factory, current_layout, current_simulation, cumulative_capex, requirements.max_capex)

            agent_result = run_planning_agent(agent, context, requirements, current_factory, optimizer_grounded=True)

            if not agent_result.proposals:
                if requirements.forbidden_machine_ids and current_simulation.system.bottleneck_machine_id in forbidden_expanded:
                    stop_reason = PlanningStopReason.USER_CONSTRAINTS_BLOCK_PROGRESS
                    text = _USER_CONSTRAINT_TEXT
                elif requirements.objective.value != "MEET_DEMAND":
                    stop_reason = PlanningStopReason.NO_FEASIBLE_IMPROVEMENT
                    text = _NO_PROPOSAL_TEXT
                else:
                    stop_reason = PlanningStopReason.NO_VALID_PROPOSAL
                    text = _NO_PROPOSAL_TEXT
                iterations.append(PlanningIteration(
                    iteration_index=iteration_index,
                    observation=observation,
                    planning_agent_result=agent_result,
                    accepted=False,
                    rejection_reason=text,
                    trace=_render_stop_trace(iteration_index, stop_reason, text),
                    state_before=state_before,
                ))
                break

            primary_candidate_id = recommendation.recommended_candidate_ids[0] if recommendation.recommended_candidate_ids else None
            selected, failure_reason = _select_proposal(
                agent_result.proposals, context, current_factory, primary_candidate_id, seen_fingerprints, remaining_capex,
            )

            if selected is None:
                stop_reason = failure_reason
                text = _SELECTION_STOP_TEXT[stop_reason]
                iterations.append(PlanningIteration(
                    iteration_index=iteration_index,
                    observation=observation,
                    planning_agent_result=agent_result,
                    accepted=False,
                    rejection_reason=text,
                    trace=_render_stop_trace(iteration_index, stop_reason, text),
                    state_before=state_before,
                ))
                break

            seen_fingerprints.add(_scenario_key(selected.scenario))

            candidate_evaluation = _evaluate_proposal(
                selected, current_factory, product_id, goal, current_layout, layout_validation,
                eval_result, grid_spacing, max_position_attempts,
            )

            if candidate_evaluation.status != CandidateFeasibilityStatus.FEASIBLE:
                reasons = [r.value for r in candidate_evaluation.rejection_reasons] or ["INFEASIBLE"]
                text = f"Constraint-blocked: {', '.join(reasons)}."
                stop_reason = PlanningStopReason.CONSTRAINT_BLOCKED
                iterations.append(PlanningIteration(
                    iteration_index=iteration_index,
                    observation=observation,
                    planning_agent_result=agent_result,
                    selected_proposal=selected,
                    proposal_validation=[text],
                    layout_validation=candidate_evaluation.constraint_result,
                    accepted=False,
                    rejection_reason=text,
                    trace=_render_infeasible_trace(iteration_index, selected, text),
                    known_capex=candidate_evaluation.known_capex,
                    requires_cost_estimate=candidate_evaluation.requires_cost_estimate,
                    state_before=state_before,
                ))
                history_lines.append(f"iteration {iteration_index}: {_scenario_summary(selected.scenario)} -> {text}")
                break

            scenario_result = candidate_evaluation.scenario_result
            if scenario_result is None:
                stop_reason = PlanningStopReason.ERROR
                iterations.append(PlanningIteration(
                    iteration_index=iteration_index,
                    observation=observation,
                    planning_agent_result=agent_result,
                    selected_proposal=selected,
                    accepted=False,
                    rejection_reason="Internal error: evaluated candidate has no scenario_result.",
                    trace=_render_stop_trace(iteration_index, stop_reason, "Internal evaluation error."),
                    state_before=state_before,
                ))
                break

            accept = is_acceptable_improvement(requirements.objective, current_simulation, scenario_result.candidate_result)

            if accept:
                current_factory = candidate_evaluation.candidate_factory
                current_layout = candidate_evaluation.candidate_layout
                current_simulation = scenario_result.candidate_result
                cumulative_capex += candidate_evaluation.known_capex
                remaining_capex = remaining_known_capex(requirements.max_capex, cumulative_capex)

                # Built from the EXACT SAME objects just assigned to
                # current_factory/current_layout/current_simulation/
                # cumulative_capex above — guarantees, by construction, the
                # invariant that this iteration's state_after equals the
                # NEXT iteration's state_before (Phase 6A.1 section 2).
                state_after = _snapshot(current_factory, current_layout, current_simulation, cumulative_capex, requirements.max_capex)

                new_bottleneck_name = _process_name(current_simulation.system.bottleneck_machine_id, context)
                history_lines.append(
                    f"iteration {iteration_index}: {_scenario_summary(selected.scenario)} -> accepted; "
                    f"new_bottleneck={current_simulation.system.bottleneck_machine_id}"
                )
                iterations.append(PlanningIteration(
                    iteration_index=iteration_index,
                    observation=observation,
                    planning_agent_result=agent_result,
                    selected_proposal=selected,
                    scenario_result=scenario_result,
                    layout_validation=candidate_evaluation.constraint_result,
                    recommendation_snapshot=recommendation,
                    accepted=True,
                    trace=_render_accept_trace(iteration_index, selected, scenario_result, new_bottleneck_name),
                    known_capex=candidate_evaluation.known_capex,
                    requires_cost_estimate=candidate_evaluation.requires_cost_estimate,
                    state_before=state_before,
                    state_after=state_after,
                ))
                iteration_index += 1
                if is_goal_reached(requirements.objective, current_simulation):
                    stop_reason = PlanningStopReason.GOAL_REACHED
                    goal_reached = True
                    break
                continue

            text = "no verified improvement over the current state."
            history_lines.append(f"iteration {iteration_index}: {_scenario_summary(selected.scenario)} -> rejected ({text})")
            # Explicitly separate from state_after (Phase 6A.1 section 3) —
            # this candidate was evaluated but never accepted, so it must
            # never be mistaken for accepted factory history. Its
            # cumulative_known_capex is the HYPOTHETICAL spend had it been
            # accepted — cumulative_capex itself is left untouched.
            rejected_candidate_snapshot = _snapshot(
                candidate_evaluation.candidate_factory, candidate_evaluation.candidate_layout,
                scenario_result.candidate_result, cumulative_capex + candidate_evaluation.known_capex,
                requirements.max_capex,
            )
            iterations.append(PlanningIteration(
                iteration_index=iteration_index,
                observation=observation,
                planning_agent_result=agent_result,
                selected_proposal=selected,
                scenario_result=scenario_result,
                layout_validation=candidate_evaluation.constraint_result,
                recommendation_snapshot=recommendation,
                accepted=False,
                rejection_reason=f"No verified improvement ({text})",
                trace=_render_reject_trace(iteration_index, selected, scenario_result, text),
                known_capex=candidate_evaluation.known_capex,
                requires_cost_estimate=candidate_evaluation.requires_cost_estimate,
                state_before=state_before,
                rejected_candidate_snapshot=rejected_candidate_snapshot,
            ))
            iteration_index += 1

        # Built from the exact same current_factory/current_layout/
        # current_simulation/cumulative_capex returned below — guarantees
        # final_snapshot == (current_factory, current_layout,
        # current_simulation, cumulative_known_capex) by construction
        # (Phase 6A.1 section 4), not by a separate recomputation.
        final_snapshot = _snapshot(current_factory, current_layout, current_simulation, cumulative_capex, requirements.max_capex)

        return PlanningSessionState(
            session_id=session_id,
            original_requirements=requirements,
            current_factory=current_factory,
            current_layout=current_layout,
            baseline_factory=baseline_factory,
            baseline_layout=baseline_layout,
            baseline_simulation=baseline_simulation,
            current_simulation=current_simulation,
            current_best_result=current_simulation,
            iterations=iterations,
            cumulative_known_capex=cumulative_capex,
            # Taken from the final snapshot rather than recomputed, so the
            # session-level figure and the final stage's figure are the same
            # value by construction and cannot drift apart.
            remaining_known_capex=final_snapshot.remaining_known_capex,
            stop_reason=stop_reason,
            goal_reached=goal_reached,
            baseline_snapshot=baseline_snapshot,
            final_snapshot=final_snapshot,
        )
