"""Planning Agent for Fabrivium Phase 5B."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from pydantic import ValidationError

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.planning_agent import (
    PlanningAgentResult,
    PlanningContext,
    PlanningContextCandidateSummary,
    PlanningHypothesis,
    PlanningProposal,
    ProposalSource,
    RejectedProposal,
    SuspectedIssueType,
)
from app.models.scenario import AddParallelMachineAction, Scenario
from app.services.proposal_validator import validate_planning_proposal
from app.services.requirements_parser import USER_REQUEST_NOTE_PREFIX

_INFEASIBLE_STATUSES = {"INFEASIBLE"}
_UNKNOWN_COST_HINT = "Cost impact is not yet estimated."


# Abstract interface


class PlanningAgent(ABC):
    """Common interface for every planning-agent backend."""

    @abstractmethod
    def propose(self, context: PlanningContext) -> list[PlanningProposal]:
        """Return candidate proposals for *context*."""
        raise NotImplementedError


# Deterministic backend


def _extract_user_requested_machine_ids(notes: list[str]) -> set[str]:
    return {
        note[len(USER_REQUEST_NOTE_PREFIX):].rstrip(".")
        for note in notes
        if note.startswith(USER_REQUEST_NOTE_PREFIX)
    }


class DeterministicPlanningAgent(PlanningAgent):
    """
    Repackages Phase 4 output as proposals — never invents logic independently (Phase 5B
    section 4).
    """

    def __init__(self, max_proposals: int = 3) -> None:
        self._max_proposals = max_proposals

    def propose(self, context: PlanningContext) -> list[PlanningProposal]:
        proposals: list[PlanningProposal] = []
        sim = context.simulation_summary
        pool_by_id = {p.reference_machine_id: p for p in context.pool_summaries}

        eligible = [c for c in context.candidate_summaries if c.status not in _INFEASIBLE_STATUSES]
        eligible.sort(key=lambda c: (c.rank if c.rank is not None else 10_000, c.candidate_id))

        covered_machine_ids: set[str] = set()
        for cand in eligible[: self._max_proposals]:
            proposals.append(self._build_from_candidate(cand, sim, pool_by_id))
            for action in cand.scenario.actions:
                machine_id = getattr(action, "machine_id", None)
                if machine_id is not None:
                    covered_machine_ids.add(machine_id)

        requested_ids = _extract_user_requested_machine_ids(context.requirements.notes)
        for machine_id in sorted(requested_ids - covered_machine_ids):
            existing = next(
                (c for c in context.candidate_summaries if self._targets(c, machine_id)), None
            )
            if existing is not None:
                proposals.append(self._build_from_candidate(existing, sim, pool_by_id, user_requested=True))
            else:
                machine = next((m for m in context.machines if m.id == machine_id), None)
                if machine is not None:
                    proposals.append(self._build_user_requested_proposal(machine_id, machine.purchase_cost))

        return proposals

    @staticmethod
    def _targets(candidate: PlanningContextCandidateSummary, machine_id: str) -> bool:
        return any(getattr(a, "machine_id", None) == machine_id for a in candidate.scenario.actions)

    def _build_from_candidate(
        self, cand: PlanningContextCandidateSummary, sim, pool_by_id, *, user_requested: bool = False
    ) -> PlanningProposal:
        target_machine_id = next(
            (getattr(a, "machine_id", None) for a in cand.scenario.actions if getattr(a, "machine_id", None)),
            None,
        )
        pool = pool_by_id.get(target_machine_id) if target_machine_id else None
        is_bottleneck = pool is not None and pool.reference_machine_id == sim.bottleneck_machine_id

        evidence: list[str] = []
        if pool is not None:
            if is_bottleneck:
                evidence.append(f"{pool.process_step_name} is the measured bottleneck.")
            evidence.append(f"Pool utilization is {pool.utilization * 100:.2f}%.")
            evidence.append(f"Average queue length is {pool.average_queue_length:.2f} units.")
            if not sim.demand_met:
                evidence.append(f"Current demand gap is {sim.demand_gap_units:g} units.")

        if user_requested:
            issue_type = SuspectedIssueType.UNKNOWN
            summary = (
                f"User explicitly requested this intervention at {target_machine_id}; "
                f"included regardless of optimizer priority."
            )
        elif is_bottleneck and not sim.demand_met:
            issue_type = SuspectedIssueType.INSUFFICIENT_CAPACITY
            summary = f"Current demand shortfall is primarily constrained by {pool.process_step_name} capacity."
        elif pool is not None and not sim.demand_met:
            issue_type = SuspectedIssueType.UNKNOWN
            summary = f"Demand is not currently met; {pool.process_step_name} is a candidate contributing factor."
        elif pool is not None:
            issue_type = SuspectedIssueType.HIGH_WIP if sim.work_in_progress > 0 else SuspectedIssueType.UNKNOWN
            summary = f"Demand is currently met; this proposal targets {pool.process_step_name} for further improvement."
        else:
            issue_type = SuspectedIssueType.UNKNOWN
            summary = f"Proposal targets {target_machine_id or 'the factory'} based on optimizer-generated evidence."

        hypothesis = PlanningHypothesis(
            problem_summary=summary,
            suspected_bottleneck_machine_id=sim.bottleneck_machine_id if (is_bottleneck and not sim.demand_met) else None,
            suspected_issue_type=issue_type,
            evidence=evidence,
        )

        return PlanningProposal(
            proposal_id=f"proposal-{cand.candidate_id}",
            hypothesis=hypothesis,
            scenario=cand.scenario,
            expected_effects=_expected_effects(cand.scenario, user_requested=user_requested),
            risks=_risks(cand),
            confidence=self._confidence(cand, user_requested),
            source=ProposalSource.DETERMINISTIC,
        )

    def _build_user_requested_proposal(self, machine_id: str, purchase_cost: float | None) -> PlanningProposal:
        scenario = Scenario(
            id=f"user-requested-{machine_id}",
            name=f"Add parallel machine at {machine_id} (user-requested)",
            description="Explicit user request; not generated by the optimizer (no measured congestion evidence).",
            actions=[AddParallelMachineAction(machine_id=machine_id)],
        )
        hypothesis = PlanningHypothesis(
            problem_summary=(
                f"User explicitly requested a parallel machine at {machine_id}; no measured "
                f"congestion evidence identifies it as an optimizer-prioritized action."
            ),
            suspected_bottleneck_machine_id=None,
            suspected_issue_type=SuspectedIssueType.UNKNOWN,
            evidence=[f"{machine_id} was not among the optimizer's congestion-driven candidates."],
        )
        return PlanningProposal(
            proposal_id=f"proposal-user-requested-{machine_id}",
            hypothesis=hypothesis,
            scenario=scenario,
            expected_effects=[f"Adds requested capacity at {machine_id}, per explicit user instruction."],
            risks=[
                f"{machine_id} is not identified as a measured bottleneck; this may provide no operational benefit.",
                (
                    "Cost impact is not yet estimated."
                    if purchase_cost is None
                    else f"Requires €{purchase_cost:,.0f} known CAPEX."
                ),
                "Actual impact is not verified until simulated and evaluated.",
            ],
            confidence=0.3,
            source=ProposalSource.DETERMINISTIC,
        )

    @staticmethod
    def _confidence(cand: PlanningContextCandidateSummary, user_requested: bool) -> float:
        if user_requested:
            return 0.4
        if cand.status == "RECOMMENDED":
            return 0.85
        if cand.status in ("PARETO_OPTIMAL", "FEASIBLE"):
            return 0.65
        return 0.5


def _expected_effects(scenario, *, user_requested: bool = False) -> list[str]:
    effects: list[str] = []
    for action in scenario.actions:
        machine_id = getattr(action, "machine_id", None)
        if action.action_type == "ADD_PARALLEL_MACHINE":
            if user_requested:
                effects.append(f"Adds requested capacity at {machine_id}, per explicit user instruction.")
            else:
                effects.append(f"Increase process capacity at the {machine_id} stage.")
                effects.append(f"Reduce queueing at the {machine_id} stage.")
        elif action.action_type == "CHANGE_MACHINE_CYCLE_TIME":
            effects.append(f"Reduce per-unit cycle time at {machine_id}.")
        elif action.action_type == "CHANGE_MACHINE_CAPACITY":
            effects.append(f"Increase concurrent processing capacity at {machine_id}.")
    return effects


def _risks(cand: PlanningContextCandidateSummary) -> list[str]:
    risks = ["A new bottleneck may emerge after this change is applied."]
    if cand.requires_cost_estimate:
        risks.append(_UNKNOWN_COST_HINT)
    elif cand.known_capex > 0:
        risks.append(f"Requires €{cand.known_capex:,.0f} known CAPEX.")
    risks.append("Actual impact is not verified until simulated and evaluated.")
    return risks


# LLM structured-output interface/stub

# (prompt, context) -> list of raw structured proposal dicts.
PlanningCompletionFn = Callable[[str, PlanningContext], list[dict]]

DEFAULT_PLANNING_SYSTEM_PROMPT = (
    "You propose production-planning interventions as a JSON array of objects, "
    "each matching the PlanningProposal schema exactly. Return ONLY the JSON "
    "array — no prose, no markdown fences. Every 'scenario' must use only the "
    "action types already present in the provided candidate list unless "
    "optimizer_grounded is explicitly false. Never invent an unsupported action "
    "type. Never claim a verified outcome (no 'demand_will_be_met', no "
    "guarantees) — expected_effects are directional hypotheses only."
)


class LLMPlanningAgent(PlanningAgent):
    """Structured-output LLM-backed planning agent."""

    def __init__(self, completion_fn: PlanningCompletionFn | None = None, system_prompt: str | None = None) -> None:
        self._completion_fn = completion_fn
        self._system_prompt = system_prompt or DEFAULT_PLANNING_SYSTEM_PROMPT

    def propose(self, context: PlanningContext) -> list[PlanningProposal]:
        proposals, _rejections = self.propose_with_rejections(context)
        return proposals

    def propose_with_rejections(self, context: PlanningContext) -> tuple[list[PlanningProposal], list[RejectedProposal]]:
        if self._completion_fn is None:
            raise NotImplementedError(
                "LLMPlanningAgent has no completion_fn configured. Phase 5B ships this as "
                "a structured-output interface/stub only — construct it with "
                "completion_fn=<your transport callable> to actually propose, or use "
                "DeterministicPlanningAgent for network-free planning."
            )

        prompt = self._build_prompt(context)
        raw_outputs = self._completion_fn(prompt, context)

        proposals: list[PlanningProposal] = []
        rejections: list[RejectedProposal] = []
        for raw in raw_outputs:
            try:
                proposals.append(PlanningProposal.model_validate(raw))
            except ValidationError as exc:
                raw_dict = raw if isinstance(raw, dict) else {"_raw": repr(raw)}
                rejections.append(RejectedProposal(raw_proposal=raw_dict, reasons=[f"Structured output validation failed: {exc}"]))

        return proposals, rejections

    def _build_prompt(self, context: PlanningContext) -> str:
        return f"{self._system_prompt}\n\ncontext = {context.model_dump_json()}"


# Orchestration


def _scenario_key(scenario) -> tuple:
    """Order-sensitive, semantically-meaningful key for a Scenario's
    actions — used both to dedup proposals and to check whether a
    proposal's scenario matches a Phase 4-generated candidate exactly."""
    parts = []
    for action in scenario.actions:
        if action.action_type == "ADD_PARALLEL_MACHINE":
            parts.append(("ADD_PARALLEL_MACHINE", action.machine_id))
        elif action.action_type == "CHANGE_MACHINE_CYCLE_TIME":
            parts.append(("CHANGE_MACHINE_CYCLE_TIME", action.machine_id, round(action.cycle_time, 6)))
        elif action.action_type == "CHANGE_MACHINE_CAPACITY":
            parts.append(("CHANGE_MACHINE_CAPACITY", action.machine_id, action.capacity))
        else:
            parts.append((action.action_type, getattr(action, "machine_id", None)))
    return tuple(parts)


def _matches_known_scenario(proposal: PlanningProposal, context: PlanningContext) -> bool:
    known_keys = {_scenario_key(c.scenario) for c in context.candidate_summaries}
    return _scenario_key(proposal.scenario) in known_keys


def _is_user_requested(proposal: PlanningProposal, context: PlanningContext) -> bool:
    requested_ids = _extract_user_requested_machine_ids(context.requirements.notes)
    if not requested_ids:
        return False
    action_ids = {getattr(a, "machine_id", None) for a in proposal.scenario.actions}
    action_ids.discard(None)
    return bool(action_ids & requested_ids)


def run_planning_agent(
    agent: PlanningAgent,
    context: PlanningContext,
    requirements: PlanningRequirements,
    factory: Factory,
    optimizer_grounded: bool = True,
) -> PlanningAgentResult:
    """
    Run *agent* end to end: propose, validate every proposal (Phase 5B section 6),
    enforce optimizer-grounding (section 7), and assemble the full audit trail.
    """
    warnings: list[str] = []

    if hasattr(agent, "propose_with_rejections"):
        raw_proposals, rejected = agent.propose_with_rejections(context)
    else:
        raw_proposals = agent.propose(context)
        rejected = []

    accepted: list[PlanningProposal] = []
    seen_keys: set[tuple] = set()

    for proposal in raw_proposals:
        reasons = validate_planning_proposal(proposal, requirements, factory)

        if optimizer_grounded and not reasons:
            grounded = _matches_known_scenario(proposal, context) or _is_user_requested(proposal, context)
            if not grounded:
                reasons = [
                    *reasons,
                    "optimizer_grounded=True: scenario does not match any Phase 4-generated "
                    "candidate and is not an explicit user-requested intervention.",
                ]

        if reasons:
            rejected.append(RejectedProposal(proposal=proposal, reasons=reasons))
            continue

        key = _scenario_key(proposal.scenario)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        accepted.append(proposal)

    agent_type = ProposalSource.LLM if isinstance(agent, LLMPlanningAgent) else ProposalSource.DETERMINISTIC

    return PlanningAgentResult(
        proposals=accepted,
        context_summary=_summarize_context(context),
        rejected_proposals=rejected,
        warnings=warnings,
        agent_type=agent_type,
        optimizer_grounded=optimizer_grounded,
    )


def _summarize_context(context: PlanningContext) -> str:
    sim = context.simulation_summary
    return (
        f"objective={context.requirements.objective.value}, "
        f"demand_met={sim.demand_met}, demand_gap={sim.demand_gap_units:g}, "
        f"bottleneck={sim.bottleneck_machine_id}, "
        f"candidates_considered={len(context.candidate_summaries)}"
    )
