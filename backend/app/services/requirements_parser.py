"""Natural-language requirements parsing for Fabrivium Phase 5A."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from app.models.agent import FactoryContext, ParserType, PlanningRequirements, RequirementsParseResult
from app.models.factory import Factory
from app.models.optimization import OptimizationGoal, OptimizationObjective
from app.models.scenario import SUPPORTED_ACTION_TYPES

# Abstract interface


class RequirementsParser(ABC):
    """Common interface for every requirements-parsing backend."""

    @abstractmethod
    def parse(self, user_request: str, factory_context: FactoryContext | None = None) -> RequirementsParseResult:
        """Parse *user_request* (optionally informed by *factory_context*, e.g."""
        raise NotImplementedError


# Contradiction detection (pure, reusable — not tied to any one backend)


def detect_contradictions(requirements: PlanningRequirements) -> list[str]:
    """
    Return human-readable warnings for LOGICALLY contradictory (but individually valid)
    field combinations.
    """
    warnings: list[str] = []

    if (
        requirements.max_additional_machines == 0
        and requirements.allowed_action_types is not None
        and set(requirements.allowed_action_types) and set(requirements.allowed_action_types) <= {"ADD_PARALLEL_MACHINE"}
    ):
        warnings.append(
            "Contradiction: max_additional_machines=0 forbids any new machine, but "
            "allowed_action_types only permits ADD_PARALLEL_MACHINE — no candidate "
            "could ever be generated under these constraints."
        )

    if (
        requirements.allowed_action_types is not None
        and len(requirements.allowed_action_types) == 0
    ):
        warnings.append(
            "Contradiction: allowed_action_types is an empty list — every action type "
            "is forbidden, so no candidate could ever be generated."
        )

    # Phase 8A: an unrecognised action_type silently filters every candidate
    # out, so a session would report "no feasible improvement" when the real
    # cause was a name a language model invented. Name it instead.
    if requirements.allowed_action_types:
        unknown = sorted(set(requirements.allowed_action_types) - SUPPORTED_ACTION_TYPES)
        if unknown:
            warnings.append(
                f"Unsupported action type(s) requested: {unknown}. Fabrivium can only execute "
                f"{sorted(SUPPORTED_ACTION_TYPES)}. Those entries will match no candidate."
            )

    if requirements.max_capex == 0 and requirements.allowed_action_types != ["CHANGE_MACHINE_CYCLE_TIME"] and (
        requirements.allowed_action_types is None or "ADD_PARALLEL_MACHINE" in requirements.allowed_action_types
    ):
        warnings.append(
            "Contradiction: max_capex=0 forbids any spend, but ADD_PARALLEL_MACHINE "
            "(the only Phase 4A action with a non-zero known cost) is not excluded "
            "from allowed_action_types — it will always be rejected on cost."
        )

    return warnings


# Deterministic fallback parser — no network, used by tests and as a
# safety net when no LLM backend is configured.

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "zero": 0, "no": 0,
}

_THROUGHPUT_RE = re.compile(r"\b(maximi[sz]e|increase|improve)\b.{0,15}\bthroughput\b", re.IGNORECASE)
_WIP_RE = re.compile(r"\b(reduce|minimi[sz]e|lower|decrease)\b.{0,15}\bwip\b", re.IGNORECASE)
_FLOW_TIME_RE = re.compile(r"\b(reduce|minimi[sz]e|lower|decrease)\b.{0,20}\bflow[\s-]?time\b", re.IGNORECASE)

_DEMAND_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*units?\s*(?:per\s*day|/\s*day|a\s*day|daily)", re.IGNORECASE
)

_CAPEX_RE = re.compile(
    r"(?:capex|budget|spend|cost)\D{0,15}?"
    r"(?:€|\$|£)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?",
    re.IGNORECASE,
)

# A spending ceiling expressed as a LIMIT phrase rather than with an explicit
# "budget"/"capex" keyword — e.g.
_CAPEX_LIMIT_RE = re.compile(
    r"\b(?:below|under|less\s+than|no\s+more\s+than|not\s+more\s+than|at\s+most|"
    r"max(?:imum)?(?:\s+of)?|cap(?:ped)?(?:\s+it)?\s+at|within|up\s+to)\b"
    r"\D{0,12}?"
    r"(?:"
    r"(?:€|\$|£)\s*(?P<sym>\d[\d,]*(?:\.\d+)?)\s*(?P<symsuffix>k|thousand|m|million)?"
    r"|"
    r"(?P<bare>\d[\d,]*(?:\.\d+)?)\s*(?P<baresuffix>k|thousand|m|million)\b"
    r")"
    r"(?!\s*(?:units?|machines?|operators?|shifts?|people|staff|workers?))",
    re.IGNORECASE,
)

_MAX_MACHINES_DIGIT_RE = re.compile(
    r"(?:no more than|not more than|at most|maximum of|max)\s+(\d+)\s+(?:more\s+|additional\s+|new\s+)?machines?",
    re.IGNORECASE,
)
_MAX_MACHINES_WORD_RE = re.compile(
    r"(?:do not|don't|dont|never)\s+add\s+more\s+than\s+(\w+)\s+machines?",
    re.IGNORECASE,
)
_ZERO_MACHINES_RE = re.compile(
    r"(?:do not|don't|dont|never)\s+add\s+(?:any\s+)?(?:new\s+|more\s+)?machines?", re.IGNORECASE
)

# Two precise patterns rather than one loose one: the action verb is
# mandatory in each, so an unrelated "do not <do something else>" sentence
# (e.g. "do not add more than one machine") is never mistaken for a
# forbidden-machine mention.
_FORBID_MACHINE_VERB_RE = re.compile(
    r"(?:do not|don't|dont|never)\s+(?:modify|change|touch|alter|rearrange)\s+"
    r"(?:the\s+)?([A-Za-z][A-Za-z0-9\s\-]*?)[.,]?$",
    re.IGNORECASE | re.MULTILINE,
)
_FORBID_MACHINE_ALONE_RE = re.compile(
    r"\bleave\s+(?:the\s+)?([A-Za-z][A-Za-z0-9\s\-]*?)\s+alone\b", re.IGNORECASE
)

# Phase 8A.
_NO_NEW_MACHINE_RE = re.compile(
    r"(?:do not|don't|dont|no|without|avoid)\s+(?:add(?:ing)?|buy(?:ing)?|purchas\w*)\s+"
    r"(?:(?:another|any|additional|more|new|a)\s+)*machine",
    re.IGNORECASE,
)
_SHIFT_LEVER_RE = re.compile(
    r"\b(?:extra|another|additional|more|third|3rd|second|2nd)\s+shift\b"
    r"|\bshifts?\s+instead\b"
    r"|\brun\s+(?:it\s+)?longer\b",
    re.IGNORECASE,
)
_OPERATOR_LEVER_RE = re.compile(
    r"\b(?:add(?:ing)?|hire|hiring|more|extra|additional)\s+(?:\w+\s+)?(?:operators?|staff|people|workers?)\b",
    re.IGNORECASE,
)
_BUFFER_LEVER_RE = re.compile(
    r"\b(?:increase|raise|double|expand|bigger|larger|more)\b[^.]{0,30}\bbuffer\b"
    r"|\bbuffer\b[^.]{0,20}\b(?:capacity|size)\b",
    re.IGNORECASE,
)

# REFUSALS OF A LEVER, one pattern per lever, shaped like ``_NO_NEW_MACHINE_RE`` above —
# because they answer the same question about a different resource.
_NO_MORE_SHIFTS_RE = re.compile(
    r"(?:no|not|never|cannot|can'?t|without|do\s+not|don'?t)\s+"
    r"(?:(?:add(?:ing)?|run(?:ning)?|work(?:ing)?|use|using|introduce|introducing)\s+)?"
    r"(?:(?:a|an|any|another|additional|extra|more|second|2nd|third|3rd|new|further)\s+)*shifts?"
    r"|\bshifts?\s+(?:is|are)\s+not\s+(?:available|possible|an\s+option)",
    re.IGNORECASE,
)
_NO_MORE_OPERATORS_RE = re.compile(
    r"(?:no|not|never|cannot|can'?t|without|do\s+not|don'?t)\s+"
    r"(?:(?:hire|hiring|add(?:ing)?|recruit(?:ing)?|employ(?:ing)?)\s+)?"
    r"(?:(?:a|an|any|another|additional|extra|more|new|further)\s+)*"
    r"(?:operators?|staff|people|workers?|headcount)"
    r"|\b(?:operators?|staff|workers?|headcount)\s+(?:is|are)\s+not\s+(?:available|possible)",
    re.IGNORECASE,
)

# lever action type -> the pattern that refuses it.
_LEVER_DENIALS: dict[str, re.Pattern[str]] = {
    "CHANGE_SHIFT_CONFIGURATION": _NO_MORE_SHIFTS_RE,
    "CHANGE_OPERATOR_CAPACITY": _NO_MORE_OPERATORS_RE,
}

# Phase 8B.
_SOFTENING_RE = re.compile(
    r"\b(?:if\s+possible|if\s+we\s+can|if\s+you\s+can|where\s+possible|preferab\w+|"
    r"prefer(?:red|ably)?|ideally|rather\s+not|try\s+to|would\s+rather|avoid)\b",
    re.IGNORECASE,
)

# Clause boundaries for softener locality.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[.;!?\n]+|\b(?:but|however|although|though|and)\b|,\s*(?=(?:but|however|and)\b))",
    re.IGNORECASE,
)


def _restriction_clauses(text: str, restriction: re.Pattern[str]) -> list[str]:
    """Every clause of *text* in which *restriction* actually appears."""
    if not restriction.search(text):
        return []
    clauses = [c for c in (part.strip() for part in _CLAUSE_SPLIT_RE.split(text)) if c]
    matching = [c for c in clauses if restriction.search(c)]
    return matching or [text]


def _unsoftened_restriction(text: str, restriction: re.Pattern[str]) -> bool:
    """Whether *text* states *restriction* absolutely at least once."""
    clauses = _restriction_clauses(text, restriction)
    return any(not _SOFTENING_RE.search(clause) for clause in clauses)


# A soft "keep the equipment spend down" wish, distinct from a hard max_capex ceiling.
_PREFER_LOW_CAPEX_RE = re.compile(
    r"\bas\s+cheap\w*"
    r"|\bcheapest\b"
    r"|\blow(?:est)?\s+(?:cost|capex|spend)\b"
    r"|\bminimi[sz]e\s+(?:cost|capex|spend)\b"
    r"|\bkeep\s+(?:the\s+)?(?:cost|capex|spend)\s+(?:down|low)\b",
    re.IGNORECASE,
)

# "with the fewest changes", "as few interventions as possible".
_PREFER_FEW_CHANGES_RE = re.compile(
    r"\b(?:fewest|least\s+number\s+of|as\s+few\s+as\s+possible|minimal|minimi[sz]e\s+the\s+number)\b"
    r"[^.]{0,24}\b(?:changes?|interventions?|modifications?|steps?)\b"
    r"|\bsimplest\s+(?:plan|option|solution)\b",
    re.IGNORECASE,
)

#: Equipment mentioned as something to steer away from, without requiring
#: the explicit verb shape _NO_NEW_MACHINE_RE needs.
_EQUIPMENT_MENTION_RE = re.compile(
    r"\b(?:new\s+)?(?:machine|machines|equipment)\b", re.IGNORECASE
)

_PRESERVE_LAYOUT_RE = re.compile(
    r"(?:keep|preserve|maintain|don't\s+(?:change|rearrange|move))\b.{0,25}\blayout\b", re.IGNORECASE
)

# Detects an explicit, positive user ask to add capacity at a named machine/process —
# e.g.
_ADD_MACHINE_REQUEST_RE = re.compile(
    r"\badd\s+(?:a\s+)?(?:second|another|new|one\s+more)\s+([A-Za-z][A-Za-z0-9\s\-]*?)\s*(?:machine)?[.,]?$",
    re.IGNORECASE | re.MULTILINE,
)

#: Prefix marking a note as a captured explicit user request, followed by
#: the resolved machine_id. Kept as a single well-known constant (rather
#: than a new PlanningRequirements field) so this stays a Phase 5A-scoped,
#: minimal extension — see module docstring.
USER_REQUEST_NOTE_PREFIX = "User explicitly requested: ADD_PARALLEL_MACHINE at "


class DeterministicFallbackRequirementsParser(RequirementsParser):
    """Regex/keyword-based parser."""

    def parse(self, user_request: str, factory_context: FactoryContext | None = None) -> RequirementsParseResult:
        text = user_request.strip()
        objective = self._parse_objective(text)
        target_demand = self._parse_target_demand(text)
        max_capex = self._parse_capex(text)
        max_additional_machines = self._parse_max_additional_machines(text)
        forbidden_ids, forbid_notes = self._parse_forbidden_machines(text, factory_context)
        preserve_layout = bool(_PRESERVE_LAYOUT_RE.search(text))
        request_notes = self._parse_add_machine_request(text, factory_context)
        allowed_action_types = self._parse_allowed_action_types(text)
        preferences = self._parse_preferences(text)

        # PRECEDENCE: a hard constraint supersedes a soft preference about the same
        # subject.
        if allowed_action_types is not None and not any(a.startswith("ADD_") for a in allowed_action_types):
            preferences = {**preferences, "prefer_no_new_machines": False}

        notes: list[str] = [*forbid_notes, *request_notes]
        confidence = 1.0
        if objective is None:
            objective = OptimizationObjective.MEET_DEMAND
            notes.append("No explicit objective phrase recognized; defaulted to MEET_DEMAND.")
            confidence = min(confidence, 0.5)

        requirements = PlanningRequirements(
            objective=objective,
            target_units_per_day=target_demand,
            max_capex=max_capex,
            max_additional_machines=max_additional_machines,
            forbidden_machine_ids=list(forbidden_ids),
            preserve_existing_layout=preserve_layout,
            allowed_action_types=allowed_action_types,
            notes=notes,
            confidence=confidence,
            **preferences,
        )

        warnings = detect_contradictions(requirements)
        return RequirementsParseResult(
            raw_user_request=user_request,
            parsed_requirements=requirements,
            warnings=warnings,
            parser_type=ParserType.DETERMINISTIC_FALLBACK,
            structured_output_valid=True,
        )

    # Field-level extractors

    @staticmethod
    def _parse_objective(text: str) -> OptimizationObjective | None:
        # Checked in this fixed priority order — most specific intents first, so e.g.
        if _THROUGHPUT_RE.search(text):
            return OptimizationObjective.MAXIMIZE_THROUGHPUT
        if _WIP_RE.search(text):
            return OptimizationObjective.MINIMIZE_WIP
        if _FLOW_TIME_RE.search(text):
            return OptimizationObjective.MINIMIZE_FLOW_TIME
        if _DEMAND_RE.search(text) or re.search(r"\bmeet\b.{0,10}\bdemand\b", text, re.IGNORECASE):
            return OptimizationObjective.MEET_DEMAND
        return None

    @staticmethod
    def _parse_target_demand(text: str) -> float | None:
        match = _DEMAND_RE.search(text)
        if not match:
            return None
        return float(match.group(1).replace(",", ""))

    @staticmethod
    def _parse_capex(text: str) -> float | None:
        def scale(raw: str, suffix: str | None) -> float:
            value = float(raw.replace(",", ""))
            s = (suffix or "").lower()
            if s in ("k", "thousand"):
                value *= 1_000
            elif s in ("m", "million"):
                value *= 1_000_000
            return value

        # Explicit "budget/capex/spend/cost" phrasing wins — it is the most
        # direct statement of a ceiling.
        match = _CAPEX_RE.search(text)
        if match:
            return scale(match.group(1), match.group(2))

        # Otherwise accept a limit phrase carrying a money amount, e.g.
        limit = _CAPEX_LIMIT_RE.search(text)
        if limit:
            if limit.group("sym") is not None:
                return scale(limit.group("sym"), limit.group("symsuffix"))
            return scale(limit.group("bare"), limit.group("baresuffix"))

        return None

    @staticmethod
    def _parse_max_additional_machines(text: str) -> int | None:
        if _ZERO_MACHINES_RE.search(text) and not _MAX_MACHINES_DIGIT_RE.search(text) and not _MAX_MACHINES_WORD_RE.search(text):
            return 0
        match = _MAX_MACHINES_DIGIT_RE.search(text)
        if match:
            return int(match.group(1))
        match = _MAX_MACHINES_WORD_RE.search(text)
        if match:
            word = match.group(1).lower()
            if word in _NUMBER_WORDS:
                return _NUMBER_WORDS[word]
            if word.isdigit():
                return int(word)
        return None

    @staticmethod
    def _parse_forbidden_machines(text: str, factory_context: FactoryContext | None) -> tuple[tuple[str, ...], list[str]]:
        notes: list[str] = []
        match = _FORBID_MACHINE_VERB_RE.search(text) or _FORBID_MACHINE_ALONE_RE.search(text)
        if not match:
            return (), notes

        phrase = match.group(1).strip().lower()
        if not phrase:
            return (), notes

        if factory_context is None:
            notes.append(
                f"Detected a 'do not modify' phrase ('{phrase}') but no factory_context was "
                f"provided to resolve it to a machine_id; ignored."
            )
            return (), notes

        matches = [
            m.id for m in factory_context.machines
            if phrase in m.name.lower() or phrase in m.process_type.lower() or phrase in m.id.lower()
        ]
        if not matches:
            notes.append(
                f"Detected a 'do not modify' phrase ('{phrase}') but no machine in "
                f"factory_context matched it; ignored."
            )
            return (), notes

        return tuple(sorted(matches)), notes

    @staticmethod
    def _parse_allowed_action_types(text: str) -> list[str] | None:
        """
        Map an explicit "use THIS lever" / "not that one" phrase onto
        ``allowed_action_types`` (Phase 8A section 21).
        """
        # Refusals are read FIRST.
        denied = {
            action
            for action, pattern in _LEVER_DENIALS.items()
            if _unsoftened_restriction(text, pattern)
        }

        wanted: list[str] = []
        if _SHIFT_LEVER_RE.search(text) and "CHANGE_SHIFT_CONFIGURATION" not in denied:
            wanted.append("CHANGE_SHIFT_CONFIGURATION")
        if _OPERATOR_LEVER_RE.search(text) and "CHANGE_OPERATOR_CAPACITY" not in denied:
            wanted.append("CHANGE_OPERATOR_CAPACITY")
        if _BUFFER_LEVER_RE.search(text):
            wanted.append("CHANGE_BUFFER_CAPACITY")
        if wanted:
            return wanted

        # A softened restriction is a preference, never a rule — see _SOFTENING_RE.
        excluded = set(denied)
        if _unsoftened_restriction(text, _NO_NEW_MACHINE_RE):
            excluded.add("ADD_PARALLEL_MACHINE")
        if excluded:
            return sorted(SUPPORTED_ACTION_TYPES - excluded)
        return None

    @staticmethod
    def _parse_preferences(text: str) -> dict[str, bool]:
        """Extract SOFT Phase 8B strategy preferences."""
        # Clause-local for the same reason as _parse_allowed_action_types:
        # the softener has to govern the equipment mention itself. Whole-text
        # matching made "Use more operators if possible, but do not buy any
        # new machines" report BOTH a hard ban and a soft preference against
        # equipment, from two unrelated clauses.
        equipment_clauses = _restriction_clauses(text, _EQUIPMENT_MENTION_RE)
        return {
            "prefer_no_new_machines": any(_SOFTENING_RE.search(clause) for clause in equipment_clauses),
            "prefer_low_known_capex": bool(_PREFER_LOW_CAPEX_RE.search(text)),
            "prefer_few_changes": bool(_PREFER_FEW_CHANGES_RE.search(text)),
        }

    @staticmethod
    def _parse_add_machine_request(text: str, factory_context: FactoryContext | None) -> list[str]:
        """Detect an explicit 'add a second X' style request and, if it
        resolves to a real machine, record it as a
        ``USER_REQUEST_NOTE_PREFIX``-prefixed note (Phase 5B section 8) —
        never a hard constraint, never a claim that it will help; just a
        captured user intent for the Planning Agent to optionally surface.
        """
        match = _ADD_MACHINE_REQUEST_RE.search(text)
        if not match:
            return []

        phrase = match.group(1).strip().lower()
        if not phrase or factory_context is None:
            return []

        matches = [
            m.id for m in factory_context.machines
            if phrase in m.name.lower() or phrase in m.process_type.lower() or phrase in m.id.lower()
        ]
        if not matches:
            return []

        return [f"{USER_REQUEST_NOTE_PREFIX}{machine_id}." for machine_id in sorted(matches)]


# LLM structured-output interface/stub

#: A completion function: (prompt, factory_context) -> raw structured output
#: (a plain dict/mapping, JSON-compatible, shaped like PlanningRequirements).
#: Injected by the caller — this module has no idea which provider (if any)
#: it comes from. See module docstring.
LLMCompletionFn = Callable[[str, "FactoryContext | None"], dict]

DEFAULT_SYSTEM_PROMPT = (
    "You convert a production-planning request into a single JSON object "
    "matching the PlanningRequirements schema exactly. Return ONLY the JSON "
    "object — no prose, no markdown fences, no explanation. Every field you "
    "are not confident about should be omitted (defaults to null/empty), "
    "never guessed. Do not claim any engineering outcome; you are only "
    "describing constraints and an objective, not a solution."
)


class LLMRequirementsParser(RequirementsParser):
    """Structured-output LLM-backed parser."""

    def __init__(self, completion_fn: LLMCompletionFn | None = None, system_prompt: str | None = None) -> None:
        self._completion_fn = completion_fn
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    def parse(self, user_request: str, factory_context: FactoryContext | None = None) -> RequirementsParseResult:
        if self._completion_fn is None:
            raise NotImplementedError(
                "LLMRequirementsParser has no completion_fn configured. Phase 5A ships "
                "this as a structured-output interface/stub only — construct it with "
                "completion_fn=<your transport callable> to actually parse, or use "
                "DeterministicFallbackRequirementsParser for network-free parsing."
            )

        prompt = self._build_prompt(user_request, factory_context)
        raw_output = self._completion_fn(prompt, factory_context)

        try:
            requirements = PlanningRequirements.model_validate(raw_output)
        except ValidationError as exc:
            fallback = PlanningRequirements(
                objective=OptimizationObjective.MEET_DEMAND,
                notes=["LLM structured output failed validation; defaulted to MEET_DEMAND with no other constraints."],
                confidence=0.0,
            )
            return RequirementsParseResult(
                raw_user_request=user_request,
                parsed_requirements=fallback,
                warnings=[f"Structured output validation failed: {exc}"],
                parser_type=ParserType.LLM,
                structured_output_valid=False,
            )

        warnings = detect_contradictions(requirements)
        return RequirementsParseResult(
            raw_user_request=user_request,
            parsed_requirements=requirements,
            warnings=warnings,
            parser_type=ParserType.LLM,
            structured_output_valid=True,
        )

    def _build_prompt(self, user_request: str, factory_context: FactoryContext | None) -> str:
        context_json = factory_context.model_dump_json() if factory_context is not None else "null"
        return (
            f"{self._system_prompt}\n\n"
            f"factory_context = {context_json}\n\n"
            f"user_request = {user_request!r}"
        )


# Mapping to Phase 4's OptimizationGoal (see module docstring)


@dataclass(frozen=True)
class OptimizationGoalMapping:
    """Result of mapping ``PlanningRequirements`` -> ``OptimizationGoal``."""

    goal: OptimizationGoal
    unmapped_constraints: list[str]


def planning_requirements_to_optimization_goal(
    requirements: PlanningRequirements,
    target_product_id: str,
    max_candidates: int = 10,
) -> OptimizationGoalMapping:
    """Map validated *requirements* onto a Phase 4A ``OptimizationGoal``."""
    goal = OptimizationGoal(
        objective=requirements.objective,
        target_product_id=target_product_id,
        max_capex=requirements.max_capex,
        max_additional_machines=requirements.max_additional_machines,
        allowed_action_types=requirements.allowed_action_types,
        max_candidates=max_candidates,
        max_additional_operators=requirements.max_additional_operators,
        max_floor_area=requirements.max_floor_area,
        forbidden_machine_ids=requirements.forbidden_machine_ids,
        preserve_existing_layout=requirements.preserve_existing_layout,
    )

    return OptimizationGoalMapping(goal=goal, unmapped_constraints=[])


def apply_target_demand(factory: Factory, product_id: str, requirements: PlanningRequirements) -> Factory:
    """
    If ``requirements.target_units_per_day`` is set, return a NEW Factory with that
    product's ``demand_per_day`` updated to it — this is how a parsed target demand
    reaches the optimizer (see module docstring).
    """
    if requirements.target_units_per_day is None:
        return factory
    new_products = [
        p.model_copy(update={"demand_per_day": requirements.target_units_per_day}) if p.id == product_id else p
        for p in factory.products
    ]
    return factory.model_copy(update={"products": new_products})
