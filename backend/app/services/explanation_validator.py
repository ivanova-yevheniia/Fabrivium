"""Hallucination guard for Fabrivium Phase 5D LLM-authored explanations."""

from __future__ import annotations

import re

from app.models.explanation import ExplanationContext, PlanningExplanation

_NEGATION_WINDOW = 24
_NEGATION_WORDS = ("not ", "n't", "without", "never", "isn't", "wasn't", "didn't", "unmet", "failed")

_POSITIVE_DEMAND_PATTERNS = [
    re.compile(r"demand\s*(?:is|was|has been)?\s*met", re.IGNORECASE),
    re.compile(r"target\s*(?:is|was|has been)?\s*reached", re.IGNORECASE),
    re.compile(r"goal\s*(?:is|was|has been)?\s*reached", re.IGNORECASE),
]
_POSITIVE_LAYOUT_PATTERNS = [
    re.compile(r"layout\s*(?:is|was|has been)?\s*valid", re.IGNORECASE),
]

_MACHINE_ID_RE = re.compile(r"\bm-[a-z0-9][a-z0-9\-]*\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"[€$]\s*([\d,]+(?:\.\d+)?)")
_UNITS_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*units(?:\s*/\s*day)?", re.IGNORECASE)
_PERCENT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*%")

_NUMERIC_TOLERANCE = 0.5


def _has_unnegated_match(patterns: list[re.Pattern], text: str) -> bool:
    for pattern in patterns:
        for m in pattern.finditer(text):
            window = text[max(0, m.start() - _NEGATION_WINDOW): m.start()].lower()
            if not any(neg in window for neg in _NEGATION_WORDS):
                return True
    return False


def _text_blob(explanation: PlanningExplanation) -> str:
    return "\n".join([
        explanation.executive_summary,
        explanation.goal_status,
        explanation.stop_explanation,
        *explanation.recommended_changes,
        *explanation.verified_effects,
        *explanation.tradeoffs,
        *explanation.constraints_and_risks,
        *(s.content for s in explanation.sections),
    ])


def _known_numbers(context: ExplanationContext) -> set[float]:
    values = {
        context.baseline_demand_gap, context.final_demand_gap,
        float(context.baseline_completed_units), float(context.final_completed_units),
        float(context.baseline_target_units), float(context.final_target_units),
        context.budget.cumulative_known_capex,
    }
    if context.target_units_per_day is not None:
        values.add(context.target_units_per_day)
    if context.budget.max_capex is not None:
        values.add(context.budget.max_capex)
    if context.budget.remaining_known_capex is not None:
        values.add(context.budget.remaining_known_capex)
    for fact in (*context.accepted_iterations, *context.rejected_iterations):
        for v in (fact.demand_gap_before, fact.demand_gap_after, fact.known_capex):
            if v is not None:
                values.add(v)
    return values


def _machine_id_violations(text: str, context: ExplanationContext) -> list[str]:
    mentioned = {mid.lower() for mid in _MACHINE_ID_RE.findall(text)}
    known = {mid.lower() for mid in context.known_machine_ids}
    unknown = sorted(mentioned - known)
    if unknown:
        return [f"References unknown machine id(s) not present in the verified context: {unknown}."]
    return []


def _numeric_violations(text: str, context: ExplanationContext) -> list[str]:
    known = _known_numbers(context)
    bad: set[float] = set()
    for pattern in (_MONEY_RE, _UNITS_RE, _PERCENT_RE):
        for m in pattern.finditer(text):
            value = float(m.group(1).replace(",", ""))
            if not any(abs(value - k) < _NUMERIC_TOLERANCE for k in known):
                bad.add(value)
    if bad:
        return [f"References numeric value(s) not found in the verified context: {sorted(bad)}."]
    return []


def validate_explanation(explanation: PlanningExplanation, context: ExplanationContext) -> list[str]:
    """
    Return a list of hallucination-guard violations for *explanation* against *context*;
    empty means it passed every check.
    """
    text = _text_blob(explanation)
    violations: list[str] = []

    if not context.final_demand_met and _has_unnegated_match(_POSITIVE_DEMAND_PATTERNS, text):
        violations.append("Claims demand/target/goal was met or reached, but the verified final state has demand_met=False.")

    if context.layout_valid is False and _has_unnegated_match(_POSITIVE_LAYOUT_PATTERNS, text):
        violations.append("Claims the layout is valid, but the verified final layout constraint check failed.")

    violations.extend(_machine_id_violations(text, context))
    violations.extend(_numeric_violations(text, context))

    return violations
