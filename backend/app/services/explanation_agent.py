"""Explanation Agent for Fabrivium Phase 5D."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from pydantic import ValidationError

from app.models.explanation import (
    ExplanationContext,
    ExplanationIterationFact,
    ExplanationResult,
    ExplanationSection,
    ExplanationSourceType,
    PlanningExplanation,
)
from app.services.explanation_validator import validate_explanation

# Abstract interface


class ExplanationAgent(ABC):
    """Common interface for every explanation-agent backend."""

    @abstractmethod
    def explain(self, context: ExplanationContext) -> PlanningExplanation:
        """Build a ``PlanningExplanation`` from *context* only. Never
        mutates *context*."""
        raise NotImplementedError


# Deterministic text templates (never LLM prose)

_ORDINALS = [
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
]


def _ordinal(i: int) -> str:
    return _ORDINALS[i] if i < len(_ORDINALS) else f"{i + 1}th"


def _friendly_name(machine_id: str | None) -> str:
    if not machine_id:
        return "the process"
    name = machine_id[2:] if machine_id.startswith("m-") else machine_id
    return name.replace("-", " ").replace("_", " ").title()


def _capitalize_first(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


def _action_phrase(fact: ExplanationIterationFact) -> str:
    summary = fact.action_summary
    names = ", ".join(_friendly_name(m) for m in fact.machine_ids) or "the process"
    if summary.startswith("Add parallel machine"):
        return f"added parallel {names} capacity"
    if summary.startswith("Change cycle time"):
        return f"reduced cycle time at {names}"
    if summary.startswith("Change capacity"):
        return f"increased capacity at {names}"
    return summary


def _accepted_narrative(accepted: list[ExplanationIterationFact]) -> str:
    sentences: list[str] = []
    for i, fact in enumerate(accepted):
        sentence = f"The {_ordinal(i)} intervention {_action_phrase(fact)}"
        if fact.demand_gap_before is not None and fact.demand_gap_after is not None:
            sentence += f", reducing the demand gap from {fact.demand_gap_before:g} to {fact.demand_gap_after:g} units/day"
        sentence += "."
        sentences.append(sentence)
        is_last = i == len(accepted) - 1
        if not is_last and fact.bottleneck_after:
            sentences.append(f"Simulation then identified {_friendly_name(fact.bottleneck_after)} as the next bottleneck.")
    return " ".join(sentences)


def _stop_explanation(context: ExplanationContext) -> str:
    reason = context.stop_reason
    if reason == "GOAL_REACHED":
        return "Planning stopped because the target was reached and verified by simulation."
    if reason == "BUDGET_EXHAUSTED":
        return (
            "The target was not reached because the remaining known-cost capacity intervention "
            "exceeded the remaining CAPEX budget. Fabrivium stopped rather than executing an "
            "unverified or over-budget change."
        )
    if reason == "USER_CONSTRAINTS_BLOCK_PROGRESS":
        forbidden = ", ".join(_friendly_name(m) for m in context.forbidden_machine_ids) or "a forbidden machine"
        return (
            f"The target was not reached because the measured bottleneck sits on {forbidden}, "
            f"which the user forbade Fabrivium from modifying, and no alternative verified "
            f"intervention was available."
        )
    if reason == "REPEATED_PROPOSAL":
        return (
            "Fabrivium stopped because the only available proposal had already been evaluated "
            "without producing a verified improvement; repeating it would not change the outcome."
        )
    if reason == "NO_VALID_PROPOSAL":
        return "Fabrivium stopped because no valid proposal could be generated for the current state."
    if reason == "NO_FEASIBLE_IMPROVEMENT":
        return "Fabrivium stopped because no further verified improvement could be identified for the current objective."
    if reason == "CONSTRAINT_BLOCKED":
        return "Fabrivium stopped because the selected intervention failed a hard physical/layout constraint check."
    if reason == "MAX_ITERATIONS":
        return "Fabrivium stopped after reaching the maximum number of planning iterations before the target was reached."
    if reason == "ERROR":
        return "Fabrivium stopped because the supplied baseline could not be verified (e.g. an already-invalid layout)."
    return f"Fabrivium stopped (reason: {reason})."


def _executive_summary(context: ExplanationContext) -> str:
    n = len(context.accepted_iterations)
    target_phrase = f"{context.target_units_per_day:g} units/day" if context.target_units_per_day is not None else "the requested target"
    narrative = _accepted_narrative(context.accepted_iterations)

    if context.goal_reached:
        count_phrase = "one verified iteration" if n == 1 else f"{n} verified iterations"
        summary = f"Fabrivium reached the target of {target_phrase} in {count_phrase}."
        return f"{summary} {narrative}" if narrative else summary

    stop_text = _stop_explanation(context)
    if n == 0:
        return f"Fabrivium did not reach the target. {stop_text}"
    return f"Fabrivium made {n} verified improvement(s) but did not reach the target. {narrative} {stop_text}"


def _goal_status(context: ExplanationContext) -> str:
    target_phrase = f"{context.target_units_per_day:g} units/day" if context.target_units_per_day is not None else "no explicit numeric target"
    if context.goal_reached:
        return (
            f"Goal reached: target {target_phrase}; final verified output is "
            f"{context.final_completed_units}/{context.final_target_units} units (demand met)."
        )
    return (
        f"Goal not reached: target {target_phrase}; final verified output is "
        f"{context.final_completed_units}/{context.final_target_units} units "
        f"(demand gap: {context.final_demand_gap:g} units, demand not met)."
    )


def _recommended_changes(context: ExplanationContext) -> list[str]:
    return [f"{_capitalize_first(_action_phrase(f))}." for f in context.accepted_iterations]


def _verified_effects(context: ExplanationContext) -> list[str]:
    effects: list[str] = []
    for f in context.accepted_iterations:
        if f.demand_gap_before is not None and f.demand_gap_after is not None:
            met_clause = " Demand met." if f.demand_met_after else ""
            effects.append(
                f"Iteration {f.iteration_number}: verified demand gap reduced from "
                f"{f.demand_gap_before:g} to {f.demand_gap_after:g} units/day.{met_clause}"
            )
    if context.final_demand_met:
        effects.append(f"Final verified state meets demand: {context.final_completed_units}/{context.final_target_units} units/day.")
    else:
        effects.append(f"Final verified state does not meet demand: a gap of {context.final_demand_gap:g} units/day remains.")
    return effects


def _tradeoffs(context: ExplanationContext) -> list[str]:
    tradeoffs: list[str] = []
    if context.budget.cumulative_known_capex > 0:
        tradeoffs.append(f"Known CAPEX committed: €{context.budget.cumulative_known_capex:,.0f}.")
    if context.budget.max_capex is not None:
        remaining = context.budget.remaining_known_capex
        if remaining is not None:
            tradeoffs.append(f"Remaining known budget: €{remaining:,.0f} of €{context.budget.max_capex:,.0f}.")
        else:
            tradeoffs.append("Remaining budget is unknown.")
    tradeoffs.extend(context.warnings)
    if context.accepted_iterations and not context.final_demand_met:
        last_bottleneck = context.accepted_iterations[-1].bottleneck_after
        if last_bottleneck:
            tradeoffs.append(f"A new constraint is now exposed at {_friendly_name(last_bottleneck)}.")
    if not tradeoffs:
        tradeoffs.append("No CAPEX was committed and no tradeoffs were incurred.")
    return tradeoffs


def _constraints_and_risks(context: ExplanationContext) -> list[str]:
    items: list[str] = []
    if context.forbidden_machine_ids:
        items.append(f"Forbidden machine(s) respected — never modified: {', '.join(context.forbidden_machine_ids)}.")
    if context.layout_supplied:
        if context.layout_valid is True:
            items.append("Final layout passed constraint validation.")
        elif context.layout_valid is False:
            items.append("Final layout has unresolved constraint violations.")
        else:
            items.append("Layout validity for the final state was not verified.")
    for r in context.rejected_iterations:
        items.append(f"Iteration {r.iteration_number} rejected: {r.rejection_reason or 'not accepted (no verified improvement)'}")
    if not items:
        items.append("No layout was supplied and no machines were forbidden.")
    return items


def _next_info_text(context: ExplanationContext) -> str:
    if not context.warnings:
        return "No further information is required based on verified results."
    return " ".join(context.warnings)


def _what_changed_text(context: ExplanationContext) -> str:
    if not context.accepted_iterations:
        return "No verified changes were made."
    parts = []
    for f in context.accepted_iterations:
        result = f"gap {f.demand_gap_before:g} -> {f.demand_gap_after:g} units/day" if f.demand_gap_before is not None else "verified"
        parts.append(f"Iteration {f.iteration_number}: {_action_phrase(f)} (result: {result}).")
    return " ".join(parts)


def _sections(context: ExplanationContext, executive_summary: str, goal_status: str, stop_explanation: str, tradeoffs: list[str]) -> list[ExplanationSection]:
    accepted_refs = [ref for f in context.accepted_iterations for ref in f.evidence_refs]
    return [
        ExplanationSection(
            title="Executive Summary", content=executive_summary,
            evidence_refs=["stop_reason", "budget:cumulative_capex"],
        ),
        ExplanationSection(
            title="Goal Status", content=goal_status,
            evidence_refs=["baseline:demand_gap", "final:demand_gap"],
        ),
        ExplanationSection(
            title="What Changed", content=_what_changed_text(context),
            evidence_refs=accepted_refs,
        ),
        ExplanationSection(
            title="Tradeoffs", content=" ".join(tradeoffs),
            evidence_refs=["budget:cumulative_capex", "budget:remaining_capex"],
        ),
        ExplanationSection(
            title="Why Planning Stopped", content=stop_explanation,
            evidence_refs=["stop_reason"],
        ),
        ExplanationSection(
            title="Next Information Needed", content=_next_info_text(context),
            evidence_refs=["information_gap"] if context.warnings else [],
        ),
    ]


# Deterministic backend


class DeterministicExplanationAgent(ExplanationAgent):
    """Builds a full ``PlanningExplanation`` from ``ExplanationContext``
    using fixed, deterministic templates only — no network, identical
    output for identical input (Phase 5D section 3)."""

    def explain(self, context: ExplanationContext) -> PlanningExplanation:
        executive_summary = _executive_summary(context)
        goal_status = _goal_status(context)
        stop_explanation = _stop_explanation(context)
        tradeoffs = _tradeoffs(context)

        return PlanningExplanation(
            executive_summary=executive_summary,
            goal_status=goal_status,
            recommended_changes=_recommended_changes(context),
            verified_effects=_verified_effects(context),
            tradeoffs=tradeoffs,
            constraints_and_risks=_constraints_and_risks(context),
            stop_explanation=stop_explanation,
            sections=_sections(context, executive_summary, goal_status, stop_explanation, tradeoffs),
            source_type=ExplanationSourceType.DETERMINISTIC,
        )


# LLM structured-output interface/stub

#: (prompt, context) -> a raw structured dict shaped like PlanningExplanation
#: (source_type is set by this module, never trusted from raw output).
ExplanationCompletionFn = Callable[[str, ExplanationContext], dict]

DEFAULT_EXPLANATION_SYSTEM_PROMPT = (
    "You rewrite a verified production-planning result for readability. You "
    "receive a compact JSON payload of ALREADY-VERIFIED facts. Return ONLY a "
    "JSON object matching the PlanningExplanation schema exactly — no prose, "
    "no markdown fences. You may rephrase for clarity but must NEVER invent a "
    "new number, machine id, feasibility claim, or causal claim that is not "
    "already present in the payload. If a fact is not present, say it is "
    "unknown rather than guessing."
)


class LLMExplanationAgent(ExplanationAgent):
    """Structured-output LLM-backed explanation agent."""

    def __init__(self, completion_fn: ExplanationCompletionFn | None = None, system_prompt: str | None = None) -> None:
        self._completion_fn = completion_fn
        self._system_prompt = system_prompt or DEFAULT_EXPLANATION_SYSTEM_PROMPT

    def explain(self, context: ExplanationContext) -> PlanningExplanation:
        if self._completion_fn is None:
            raise NotImplementedError(
                "LLMExplanationAgent has no completion_fn configured. Phase 5D ships this as "
                "a structured-output interface/stub only — construct it with "
                "completion_fn=<your transport callable> to actually explain, or use "
                "DeterministicExplanationAgent for network-free explanations."
            )

        prompt = self._build_prompt(context)
        raw = self._completion_fn(prompt, context)
        data = dict(raw)
        data["source_type"] = ExplanationSourceType.LLM
        return PlanningExplanation.model_validate(data)

    def _build_prompt(self, context: ExplanationContext) -> str:
        return f"{self._system_prompt}\n\ncontext = {context.model_dump_json()}"


# Orchestration — hallucination guard + fallback (Phase 5D section 8)


def generate_explanation(agent: ExplanationAgent, context: ExplanationContext) -> ExplanationResult:
    """Run *agent* against *context*."""
    if not isinstance(agent, LLMExplanationAgent):
        explanation = agent.explain(context)
        return ExplanationResult(explanation=explanation, llm_attempted=False, llm_validation_errors=[], used_fallback=False)

    try:
        candidate = agent.explain(context)
    except ValidationError as exc:
        fallback = DeterministicExplanationAgent().explain(context)
        return ExplanationResult(
            explanation=fallback, llm_attempted=True,
            llm_validation_errors=[f"Structured output validation failed: {exc}"], used_fallback=True,
        )

    violations = validate_explanation(candidate, context)
    if violations:
        fallback = DeterministicExplanationAgent().explain(context)
        return ExplanationResult(explanation=fallback, llm_attempted=True, llm_validation_errors=violations, used_fallback=True)

    return ExplanationResult(explanation=candidate, llm_attempted=True, llm_validation_errors=[], used_fallback=False)
