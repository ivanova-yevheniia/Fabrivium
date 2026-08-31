"""Deterministic engineering estimator — Phase 18B."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.data.engineering_reference_data import (
    AUTOMATION_FACTORS,
    REFERENCE_DATASET_NAME,
    UNKNOWN_AUTOMATION_WIDENING,
    covered_categories,
    profile_for,
)
from app.models.uncertainty import Confidence, EstimateMethod, EstimatedRange

# Words that identify a sub-operation in a free-text description, per family.
_SUB_OPERATIONS: dict[str, tuple[tuple[str, ...], bool]] = {
    # Distinct steps: placing, connecting and closing are different actions.
    "assembly": (("place", "insert", "fit", "connect", "clip", "close", "mount", "attach"), False),
    # Synonyms: every one of these names the same fastening operation.
    "screwdriving": (("screw", "fasten", "bolt", "tighten"), True),
    # Synonyms, conservatively: distinguishing a "check" from a "test" in
    # free text would over-count more often than it would be right.
    "inspection": (("check", "inspect", "measure", "test", "verify", "scan"), True),
    # Distinct steps: bagging, cartoning, sealing and labelling are separate.
    "packaging": (("bag", "carton", "seal", "label", "wrap", "pack"), False),
    # Synonyms: every one of these names the same label application.
    "labelling": (("label", "mark", "apply", "affix"), True),
}

# High-confidence wording only.
_MANUAL_MARKERS = (
    "manual", "manually", "by hand", "operator places", "operator picks",
    "hand-held", "handheld", "hand tool", "by an operator",
)
_AUTOMATIC_MARKERS = (
    "robot", "robotic", "automatic", "automated", "automatically",
    "unattended", "machine places", "gantry", "pick-and-place", "pick and place",
)


@dataclass(frozen=True)
class MissingInformation:
    """Why no deterministic estimate could be produced, and what would help."""

    reason: str
    questions: list[str]


@dataclass(frozen=True)
class Contradiction:
    """The description and the selected automation level disagree."""

    message: str
    described_as: str
    selected_as: str


def detect_contradiction(description: str, automation_level: str) -> Contradiction | None:
    """Flag a clear manual/automatic disagreement, or return None."""
    selected = automation_level.strip().upper()
    if selected not in ("MANUAL", "AUTOMATIC"):
        # ASSISTED sits legitimately between the two readings, and UNKNOWN
        # cannot contradict anything.
        return None

    text = description.lower()
    says_manual = any(marker in text for marker in _MANUAL_MARKERS)
    says_automatic = any(marker in text for marker in _AUTOMATIC_MARKERS)

    # Both readings present, or neither: not a high-confidence contradiction.
    if says_manual == says_automatic:
        return None

    described = "MANUAL" if says_manual else "AUTOMATIC"
    if described == selected:
        return None

    return Contradiction(
        message=(
            f"Your description reads as {described.lower()}, but automation is set to "
            f"{selected.lower()}. Which should Fabrivium use?"
        ),
        described_as=described,
        selected_as=selected,
    )


def count_operations(description: str, process_category: str) -> int | None:
    """How many characteristic operations the description implies."""
    entry = _SUB_OPERATIONS.get(process_category.strip().lower())
    if entry is None:
        return None
    stems, synonyms = entry

    stated = _stated_repetitions(description)
    if stated is not None:
        return stated

    tokens = _tokenise(description)
    counts = [
        _quantity_near(tokens, index)
        for index, token in enumerate(tokens)
        if any(token.startswith(stem) for stem in stems)
    ]
    if not counts:
        return None

    # Synonym families name one operation several ways, so the largest
    # stated quantity is the answer. Distinct-step families genuinely add up.
    return max(counts) if synonyms else sum(counts)


# An outright statement of how many times the operation happens:
_REPETITION_RE = re.compile(
    # Not a raw string on the second line: the multiplication sign is
    # written as an escape so this file stays ASCII, and a raw string
    # would leave the escape undecoded inside the character class.
    r"(?:(\d{1,3})|\b(two|three|four|five|six|seven|eight|nine|ten)\b)\s*"
    "(?:times\\b|[x\u00d7])(?!\\s*\\d)",
    re.IGNORECASE,
)


def _stated_repetitions(description: str) -> int | None:
    """The repeat count the description states outright, if it states one."""
    found = [
        int(digits) if digits else _NUMERALS[word.lower()]
        for digits, word in _REPETITION_RE.findall(description)
    ]
    return max(found) if found else None


# Written numbers an engineer actually uses in a one-line description.
_NUMERALS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Words that end a clause.
_CLAUSE_BREAKS = frozenset({"and", "then", "before", "after", "but", "or"})


def _tokenise(text: str) -> list[str]:
    """Lower-case word tokens, with punctuation acting as a clause break."""
    return re.findall(r"[a-z0-9]+|[,;.]", text.lower())


def _quantity_near(tokens: list[str], index: int) -> int:
    """How many times the operation at `index` is stated to happen."""
    for direction in (-1, 1):
        for step in (1, 2):
            position = index + direction * step
            if not 0 <= position < len(tokens):
                break
            token = tokens[position]
            if token in _CLAUSE_BREAKS or token in (",", ";", "."):
                break
            if token.isdigit():
                return int(token)
            if token in _NUMERALS:
                return _NUMERALS[token]
    return 1


def estimate(
    *,
    process_category: str,
    description: str,
    automation_level: str,
    operations_per_unit: int | None,
) -> EstimatedRange | MissingInformation:
    """Compose a cycle-time band from documented reference data."""
    profile = profile_for(process_category)
    if profile is None:
        return MissingInformation(
            reason=(
                f"Fabrivium has no engineering reference data for '{process_category}'. "
                f"Reference bands currently exist for: {', '.join(covered_categories())}."
            ),
            questions=[
                "Enter the cycle time directly, or a range if you know one.",
                "If you have a comparable line, its measured cycle time is the strongest basis.",
            ],
        )

    operations = operations_per_unit or count_operations(description, process_category)
    level = automation_level.strip().upper()

    if operations is None and level == "UNKNOWN":
        # With neither a repetition count nor an automation level there is
        # nothing to compose from but the family name, and a band that wide
        # would not be an estimate.
        return MissingInformation(
            reason=(
                f"Not enough information to estimate this {process_category} operation. "
                "The description does not say how many operations are involved, and the automation "
                "level is not set."
            ),
            questions=[
                f"How many {profile.operation_noun}s are there per unit?",
                "Is the operation manual, assisted or automatic?",
            ],
        )

    operations = operations or 1
    factor = AUTOMATION_FACTORS.get(level, AUTOMATION_FACTORS["MANUAL"])

    low = profile.handling.low + operations * profile.per_operation.low * factor.low
    high = profile.handling.high + operations * profile.per_operation.high * factor.high

    if level == "UNKNOWN":
        # Widen rather than shift: not knowing should make the answer less
        # precise, not differently precise.
        low *= UNKNOWN_AUTOMATION_WIDENING.low

    working = (low + high) / 2.0

    return EstimatedRange(
        low=round(low, 1),
        working_value=round(working, 1),
        high=round(high, 1),
        unit="s",
        confidence=_confidence(level, operations_per_unit is not None),
        method=EstimateMethod.LOCAL_HEURISTIC,
        basis=_basis(profile, operations, level, factor),
        # The count the arithmetic above actually used — whether it was
        # propagated from the reviewed process, typed by the engineer or
        # read out of the description. Recorded so a later change to the
        # route can be compared against it (G11).
        operations_per_unit=operations,
    )


def _confidence(level: str, operations_were_stated: bool) -> Confidence:
    """Coarse, and tied to what the input actually pinned down."""
    if level == "UNKNOWN":
        return Confidence.LOW
    return Confidence.MEDIUM if operations_were_stated else Confidence.LOW


def _basis(profile, operations: int, level: str, factor) -> str:
    """The arithmetic in words, so the number can be argued with."""
    parts = [
        f"{profile.handling.low:g}–{profile.handling.high:g} s handling",
        f"{operations} × {profile.per_operation.low:g}–{profile.per_operation.high:g} s per {profile.operation_noun}",
    ]
    if level not in ("MANUAL", "UNKNOWN"):
        parts.append(f"{level.lower()} factor {factor.low:g}–{factor.high:g}")
    if level == "UNKNOWN":
        parts.append("range widened because automation level is unstated")

    # Deduped and order-preserving: the two bands often share a limit, and
    # printing it twice reads as two different warnings.
    limits = list(dict.fromkeys(
        limit for limit in (profile.handling.applicability, profile.per_operation.applicability) if limit
    ))
    return (
        f"Local engineering heuristic: {' + '.join(parts)}. "
        f"Reference bands are Fabrivium's own stated assumptions, anchored to the "
        f"{REFERENCE_DATASET_NAME}; they are not an industry standard. "
        f"They apply to: {' '.join(limits)} Check this station against that before accepting."
    )


# Capacity and operators — Phase 18B These are NOT derived from the cycle time.

# Wording that implies more than one unit is worked on at once.
_PARALLEL_MARKERS = (
    "two fixtures", "twin fixture", "dual fixture", "two nests", "parallel",
    "simultaneously", "at the same time", "two stations in one", "duplex",
)

# Wording that means many units are inside the station but are processed as a BATCH.
_BATCH_MARKERS = (
    "batch", "oven", "curing", "tray of", "carousel", "magazine",
    "soak", "reflow", "load of",
)

# Wording that says the station runs without a person attending it.
_UNATTENDED_MARKERS = ("unattended", "no operator", "without an operator", "lights out", "lights-out")


def propose_capacity(
    *,
    process_category: str,
    description: str,
    automation_level: str,
) -> EstimatedRange | None:
    """How many units the station works on at once, or None if unclear."""
    text = description.lower()

    if any(marker in text for marker in _BATCH_MARKERS):
        # Deliberately no number.
        return None

    if any(marker in text for marker in _PARALLEL_MARKERS):
        return EstimatedRange(
            low=2, working_value=2, high=2, unit="units",
            confidence=Confidence.LOW,
            method=EstimateMethod.LOCAL_HEURISTIC,
            basis=(
                "The description mentions parallel fixtures or simultaneous work, so at least two "
                "units are in process at once. The exact number is not stated — confirm it."
            ),
        )

    if automation_level.strip().upper() in ("MANUAL", "ASSISTED"):
        return EstimatedRange(
            low=1, working_value=1, high=1, unit="units",
            confidence=Confidence.MEDIUM,
            method=EstimateMethod.LOCAL_HEURISTIC,
            basis=(
                "A person works on one unit at a time, so the station holds one unit in process. "
                "Raise this only if the station has parallel fixtures."
            ),
        )

    # AUTOMATIC or UNKNOWN with nothing else to go on: an automatic station
    # may well be single-piece, but it may equally be a multi-nest cell, and
    # the description does not say which.
    return None


def propose_operators(
    *,
    description: str,
    automation_level: str,
) -> EstimatedRange | None:
    """How many people the station occupies while it runs, or None."""
    text = description.lower()
    level = automation_level.strip().upper()

    stated = _stated_operator_count(text)
    if stated is not None:
        return EstimatedRange(
            low=stated, working_value=stated, high=stated, unit="operators",
            confidence=Confidence.MEDIUM,
            method=EstimateMethod.LOCAL_HEURISTIC,
            basis=f"The description states {stated} operator(s) at this station.",
        )

    if any(marker in text for marker in _UNATTENDED_MARKERS):
        return EstimatedRange(
            low=1, working_value=1, high=1, unit="operators",
            confidence=Confidence.LOW,
            method=EstimateMethod.LOCAL_HEURISTIC,
            basis=(
                "Described as unattended. Note that Fabrivium models operators as occupied for "
                "the whole cycle, so a value of 0 would model a station nobody ever loads — "
                "reduce this only if loading is genuinely automatic too."
            ),
        )

    if level in ("MANUAL", "ASSISTED"):
        return EstimatedRange(
            low=1, working_value=1, high=1, unit="operators",
            confidence=Confidence.MEDIUM,
            method=EstimateMethod.LOCAL_HEURISTIC,
            basis=(
                "A manual or tool-assisted operation occupies one person for its duration. "
                "Increase it if the operation needs a second pair of hands."
            ),
        )

    # AUTOMATIC: the machine runs itself, but somebody usually still loads
    # and unloads it, and the description does not say whether that is
    # inside this station's cycle. An unattended assumption here would
    # silently free an operator the line may actually need.
    return None


# Nouns that name the people at a station.
_OPERATOR_NOUNS = ("operator", "operators", "people", "person", "persons", "worker", "workers")

# Words that mean "one" without being a numeral.
_SINGULAR_WORDS = frozenset({"one", "a", "an", "single"})


def _stated_operator_count(text: str) -> int | None:
    """A count the description gives explicitly, e.g. "two operators"."""
    tokens = _tokenise(text)
    for index, token in enumerate(tokens):
        if token not in _OPERATOR_NOUNS:
            continue
        for step in (1, 2):
            position = index - step
            if position < 0:
                break
            candidate = tokens[position]
            if candidate in _CLAUSE_BREAKS or candidate in (",", ";", "."):
                break
            if candidate.isdigit():
                return int(candidate)
            if candidate in _NUMERALS:
                return _NUMERALS[candidate]
            if candidate in _SINGULAR_WORDS:
                return 1
    return None


def propose_station_assumptions(
    *,
    process_category: str,
    description: str,
    automation_level: str,
    operations_per_unit: int | None,
) -> tuple[EstimatedRange | MissingInformation, EstimatedRange | None, EstimatedRange | None]:
    """All three parameters from one description."""
    cycle = estimate(
        process_category=process_category,
        description=description,
        automation_level=automation_level,
        operations_per_unit=operations_per_unit,
    )
    capacity = propose_capacity(
        process_category=process_category,
        description=description,
        automation_level=automation_level,
    )
    operators = propose_operators(description=description, automation_level=automation_level)
    return cycle, capacity, operators
