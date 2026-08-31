"""Follow-up interpretation for Fabrivium Phase 7C (sections 4 and 22)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable

from pydantic import ValidationError

from app.models.conversation import (
    ClarificationRequest,
    PlanningBaseMode,
    RequirementUpdate,
)
from app.services.conversation_context import ConversationContext
from app.services.requirements_parser import (
    _CAPEX_RE,
    _DEMAND_RE,
    _FORBID_MACHINE_ALONE_RE,
    _FORBID_MACHINE_VERB_RE,
    _PRESERVE_LAYOUT_RE,
    DeterministicFallbackRequirementsParser,
)

# (prompt, context) -> raw structured output shaped like RequirementUpdate.
UpdateCompletionFn = Callable[[str, ConversationContext], dict]


DEFAULT_UPDATE_SYSTEM_PROMPT = (
    "You maintain a set of factory production-planning constraints across a conversation. "
    "The user sends a follow-up message. Return ONLY a JSON object describing WHAT CHANGES — "
    "no prose, no markdown fences.\n"
    "\n"
    "Critical rules:\n"
    "1. This is a PATCH, not a replacement. Set a field ONLY if the user changed it. Leave every "
    "other field null. Never repeat a constraint that did not change — the system already has it.\n"
    "2. To CLEAR a constraint entirely (e.g. 'remove the budget limit'), name it in "
    "reset_constraints. Do not use null for that; null means 'unchanged'.\n"
    "3. Use forbidden_machine_ids_add when the user protects a machine ('don't touch Assembly') and "
    "forbidden_machine_ids_remove when they release one ('Packaging is allowed again'). Refer to "
    "machines only by an id or name that appears in the provided machine list. Never invent one.\n"
    "4. Set base_mode to ORIGINAL_BASELINE when the user wants a DIFFERENT alternative planned from "
    "scratch (cheaper, other constraints, 'instead'), and CURRENT_VERIFIED_STATE when they want to "
    "build FURTHER on the plan already accepted ('now increase it further', 'on top of that'). "
    "Leave it null if you genuinely cannot tell.\n"
    "5. If the request has no unique engineering meaning — 'make it better', 'optimise it' — set "
    "clarification_required true and supply a clarification with concrete safe_options. Do not guess "
    "an objective.\n"
    "6. Fabrivium can change more than equipment. If the user asks to solve the problem WITHOUT "
    "buying a machine, or names a specific lever, express that through allowed_action_types using "
    "ONLY these values: ADD_PARALLEL_MACHINE, CHANGE_MACHINE_CAPACITY, CHANGE_MACHINE_CYCLE_TIME, "
    "CHANGE_SHIFT_CONFIGURATION (run more or longer shifts), CHANGE_OPERATOR_CAPACITY (more staff), "
    "CHANGE_BUFFER_CAPACITY (more intermediate storage), CHANGE_DEMAND, REMOVE_MACHINE. Examples: "
    "'try an extra shift' -> allowed_action_types: ['CHANGE_SHIFT_CONFIGURATION']; 'use operators "
    "instead of a machine' -> ['CHANGE_OPERATOR_CAPACITY']; 'without buying a machine' -> every "
    "value EXCEPT ADD_PARALLEL_MACHINE. Never invent a value outside that list.\n"
    "7. Never claim an outcome. You are describing a constraint change, not a result."
)


# Interface


class ConversationRequirementParser(ABC):
    """Common interface for every follow-up interpretation backend."""

    @abstractmethod
    def parse_update(self, user_message: str, context: ConversationContext) -> RequirementUpdate:
        """Interpret *user_message* against *context*."""
        raise NotImplementedError


class UnsupportedFollowUp(Exception):
    """Raised by a backend that cannot confidently interpret a message."""


# LLM backend


class LLMConversationRequirementParser(ConversationRequirementParser):
    """Structured-output backend."""

    def __init__(
        self,
        completion_fn: UpdateCompletionFn | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._completion_fn = completion_fn
        self._system_prompt = system_prompt or DEFAULT_UPDATE_SYSTEM_PROMPT

    def parse_update(self, user_message: str, context: ConversationContext) -> RequirementUpdate:
        if self._completion_fn is None:
            raise NotImplementedError(
                "LLMConversationRequirementParser has no completion_fn configured — construct it "
                "with completion_fn=<your transport callable>, or use ConservativeFollowUpParser "
                "for network-free interpretation."
            )

        raw = self._completion_fn(self._build_prompt(user_message, context), context)
        try:
            update = RequirementUpdate.model_validate(raw)
        except ValidationError as exc:
            raise UnsupportedFollowUp(f"Structured output failed RequirementUpdate validation: {exc}") from exc

        # A model that says "I need to ask" but supplies no question has
        # not actually produced a usable clarification — fill in a safe,
        # deterministic one rather than showing the user an empty card.
        if update.clarification_required and update.clarification is None:
            update = update.model_copy(update={
                "clarification": ClarificationRequest(
                    question="Could you say more precisely what you would like changed?",
                    ambiguous_fields=[],
                    safe_options=[],
                )
            })
        return update

    def _build_prompt(self, user_message: str, context: ConversationContext) -> str:
        return (
            f"{self._system_prompt}\n\n"
            f"context = {context.model_dump_json()}\n\n"
            f"user_message = {user_message!r}"
        )


# Conservative network-free backend

# Phrases whose meaning depends entirely on conversational context.
_CONTEXT_SENSITIVE_RE = re.compile(
    r"\b(cheaper|better|faster|improve it|optimi[sz]e it|undo|revert|previous|earlier|"
    r"the first|the last|that one|instead|again|same as|like before|more|less)\b",
    re.IGNORECASE,
)

_CAPEX_LIMIT_RE = re.compile(
    r"(?:below|under|less than|at most|no more than|max(?:imum)?(?:\s+of)?|cap(?:ped)?\s+at|"
    r"budget\s+of|within|allow(?:ing)?|up\s+to|spend)\s*"
    r"(?:€|EUR|\$|£)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?",
    re.IGNORECASE,
)

#: A standalone monetary amount — either currency-marked (€180,000) or
#: magnitude-suffixed (180k). Used only when no verb-anchored budget phrase
#: matched, and only when the number is NOT a production quantity: "2200
#: units/day" must never be read as a budget, which is why anything
#: followed by a unit word is excluded outright.
_BARE_MONEY_RE = re.compile(
    r"(?:(?:€|EUR|\$|£)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?"
    r"|\b(\d[\d,]*(?:\.\d+)?)\s*(k|m)\b)"
    r"(?!\s*(?:units?|pcs|pieces|/|per\s*day|a\s*day|daily))",
    re.IGNORECASE,
)

_ALLOW_MACHINE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z0-9\s\-]*?)\s+(?:is|are)\s+(?:allowed|permitted|fine|ok|okay)\s+again\b",
    re.IGNORECASE,
)

_INCREMENTAL_RE = re.compile(
    r"\b(now|then|further|additionally|on top of (?:that|this)|continue|build on)\b", re.IGNORECASE
)


def _scale(value: str, suffix: str | None) -> float:
    amount = float(value.replace(",", ""))
    unit = (suffix or "").lower()
    if unit in ("k", "thousand"):
        return amount * 1_000
    if unit in ("m", "million"):
        return amount * 1_000_000
    return amount


class ConservativeFollowUpParser(ConversationRequirementParser):
    """Network-free PATCH parser for unambiguous follow-ups only."""

    def parse_update(self, user_message: str, context: ConversationContext) -> RequirementUpdate:
        text = user_message.strip()
        if not text:
            raise UnsupportedFollowUp("Empty message.")

        # "<machine> is allowed again" is an unambiguous release even
        # though it contains "again", which is otherwise a context-
        # sensitivity marker. Recognise it first and remove it from the
        # text before the guard runs, so one safe construction is not
        # blocked by a word it happens to share with unsafe ones.
        forbidden_remove = self._machine_phrase(text, context, _ALLOW_MACHINE_RE)
        residual = _ALLOW_MACHINE_RE.sub(" ", text) if forbidden_remove else text

        if _CONTEXT_SENSITIVE_RE.search(residual):
            raise UnsupportedFollowUp(
                "Message depends on conversational context that only a language model can resolve."
            )

        target: float | None = None
        demand = _DEMAND_RE.search(text)
        if demand:
            target = float(demand.group(1).replace(",", ""))

        # Budget is resolved most-explicit-first: a verb-anchored limit
        # ("below 150k"), then the Phase 5A keyword form ("budget 220k"),
        # then a bare monetary amount ("allow €180,000"). The target is
        # parsed BEFORE this so a production quantity can never be
        # mistaken for money.
        max_capex: float | None = None
        limit = _CAPEX_LIMIT_RE.search(text)
        if limit:
            max_capex = _scale(limit.group(1), limit.group(2))
        else:
            capex = _CAPEX_RE.search(text)
            if capex:
                max_capex = _scale(capex.group(1), capex.group(2))
            else:
                bare = _BARE_MONEY_RE.search(text)
                if bare:
                    amount = bare.group(1) or bare.group(3)
                    suffix = bare.group(2) if bare.group(1) else bare.group(4)
                    value = _scale(amount, suffix)
                    # Guard against re-reading the target as a budget when
                    # the sentence only ever mentioned one number.
                    if target is None or value != target:
                        max_capex = value

        forbidden_add = self._machine_phrase(text, context, _FORBID_MACHINE_VERB_RE, _FORBID_MACHINE_ALONE_RE)

        preserve_layout = True if _PRESERVE_LAYOUT_RE.search(text) else None

        # Phase 8A levers.
        allowed_action_types = DeterministicFallbackRequirementsParser._parse_allowed_action_types(text)

        update = RequirementUpdate(
            target_units_per_day=target,
            max_capex=max_capex,
            forbidden_machine_ids_add=forbidden_add,
            forbidden_machine_ids_remove=forbidden_remove,
            preserve_existing_layout=preserve_layout,
            allowed_action_types=allowed_action_types,
            # Only ever the safe default: a conservative parser must never
            # decide to build on top of an existing plan, because getting
            # that wrong spends money that was never authorised.
            base_mode=PlanningBaseMode.ORIGINAL_BASELINE,
            intent_summary="Interpreted without the language model, from explicit values only.",
        )
        if update.is_empty():
            raise UnsupportedFollowUp("No unambiguous constraint change found in the message.")
        return update

    @staticmethod
    def _machine_phrase(text: str, context: ConversationContext, *patterns: re.Pattern) -> list[str]:
        """Extract a machine phrase and keep it ONLY if it resolves against
        the real machine list — never pass an unresolvable phrase forward."""
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            phrase = match.group(1).strip().lower()
            if not phrase:
                continue
            if any(
                phrase in m.name.lower() or phrase in m.process_type.lower() or phrase in m.id.lower()
                for m in context.machines
            ):
                return [phrase]
        return []
