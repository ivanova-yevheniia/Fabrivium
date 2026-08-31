"""The words Fabrivium uses for its own internal identifiers."""

from __future__ import annotations

from app.models.strategy import CostCategory, InformationGapType

# Information gaps

#: Mid-sentence phrase, article included, in the words an engineer would use
#: for the same missing number. Deliberately identical to the frontend's
#: ``GAP_PHRASE`` (``frontend/src/utils/informationGaps.ts``) so the sentence
#: reads the same whether or not the display-layer net ever fires.
_GAP_PHRASE: dict[InformationGapType, str] = {
    InformationGapType.SHIFT_COST: "the cost of an additional shift",
    InformationGapType.OPERATOR_COST: "the cost of an additional operator",
    InformationGapType.BUFFER_MODIFICATION_COST: "the cost of changing buffer capacity",
    InformationGapType.PROCESS_IMPROVEMENT_COST: "the cost of the process improvement",
    InformationGapType.MACHINE_CAPACITY_COST: "the cost of increasing station capacity",
}

# Sentence-initial / heading form of the same phrase.
_GAP_TITLE: dict[InformationGapType, str] = {
    InformationGapType.SHIFT_COST: "Cost of an additional shift",
    InformationGapType.OPERATOR_COST: "Cost of an additional operator",
    InformationGapType.BUFFER_MODIFICATION_COST: "Cost of changing buffer capacity",
    InformationGapType.PROCESS_IMPROVEMENT_COST: "Cost of the process improvement",
    InformationGapType.MACHINE_CAPACITY_COST: "Cost of increasing station capacity",
}

# Cost categories

# What KIND of money, in words.
_CATEGORY_PHRASE: dict[CostCategory, str] = {
    CostCategory.CAPEX: "one-off capital cost",
    CostCategory.OPEX_PER_DAY: "operating cost per day",
    CostCategory.OPEX_PER_YEAR: "operating cost per year",
    CostCategory.ONE_TIME_OTHER: "one-off cost",
}

# Heading form, for a comparison-table row label.
_CATEGORY_TITLE: dict[CostCategory, str] = {
    CostCategory.CAPEX: "Capital cost (CAPEX)",
    CostCategory.OPEX_PER_DAY: "Operating cost per day",
    CostCategory.OPEX_PER_YEAR: "Operating cost per year",
    CostCategory.ONE_TIME_OTHER: "One-off cost",
}

# Scenario actions

# The lever an action pulls, in words.
_ACTION_PHRASE: dict[str, str] = {
    "ADD_PARALLEL_MACHINE": "adding a parallel machine",
    "CHANGE_SHIFT_CONFIGURATION": "changing the shift pattern",
    "CHANGE_OPERATOR_CAPACITY": "changing operator capacity",
    "CHANGE_BUFFER_CAPACITY": "changing buffer capacity",
    "CHANGE_MACHINE_CYCLE_TIME": "changing machine cycle time",
}


class UnmappedInternalTerm(KeyError):
    """An internal identifier reached user-facing prose with no phrase."""


def gap_phrase(gap_type: InformationGapType) -> str:
    """Mid-sentence phrase for an information gap ("the cost of ...")."""
    try:
        return _GAP_PHRASE[InformationGapType(gap_type)]
    except (KeyError, ValueError) as exc:  # pragma: no cover - guarded by test
        raise UnmappedInternalTerm(
            f"No user-facing phrase for information gap {gap_type!r}. "
            f"Add one to strategy_language._GAP_PHRASE before it can be shown."
        ) from exc


def gap_title(gap_type: InformationGapType) -> str:
    """Sentence-initial form of :func:`gap_phrase`."""
    try:
        return _GAP_TITLE[InformationGapType(gap_type)]
    except (KeyError, ValueError) as exc:  # pragma: no cover - guarded by test
        raise UnmappedInternalTerm(
            f"No user-facing title for information gap {gap_type!r}."
        ) from exc


def category_phrase(category: CostCategory) -> str:
    """Mid-sentence phrase for a cost category ("operating cost per day")."""
    try:
        return _CATEGORY_PHRASE[CostCategory(category)]
    except (KeyError, ValueError) as exc:  # pragma: no cover - guarded by test
        raise UnmappedInternalTerm(
            f"No user-facing phrase for cost category {category!r}."
        ) from exc


def category_title(category: CostCategory) -> str:
    """Heading form of :func:`category_phrase`."""
    try:
        return _CATEGORY_TITLE[CostCategory(category)]
    except (KeyError, ValueError) as exc:  # pragma: no cover - guarded by test
        raise UnmappedInternalTerm(
            f"No user-facing title for cost category {category!r}."
        ) from exc


def action_phrase(action_type: str) -> str:
    """The lever an action pulls, in words."""
    known = _ACTION_PHRASE.get(action_type)
    if known is not None:
        return known
    return action_type.replace("_", " ").lower()


def join_phrases(phrases: list[str]) -> str:
    """Join human phrases as English, not as a CSV dump."""
    items = [p for p in phrases if p]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def gap_phrases_for(gap_types) -> str:
    """The distinct gaps named once each, in a stable order, as English."""
    seen: list[InformationGapType] = []
    for gap_type in gap_types:
        member = InformationGapType(gap_type)
        if member not in seen:
            seen.append(member)
    ordered = sorted(seen, key=lambda g: list(InformationGapType).index(g))
    return join_phrases([gap_phrase(g) for g in ordered])


# Money, said in full (G14)

# Compact per-category suffix, for a figure quoted mid-sentence.
_CATEGORY_SUFFIX: dict[CostCategory, str] = {
    CostCategory.CAPEX: " CAPEX",
    CostCategory.OPEX_PER_DAY: "/day operating cost",
    CostCategory.OPEX_PER_YEAR: "/year operating cost",
    CostCategory.ONE_TIME_OTHER: " one-off cost",
}

# The order money is quoted in.
_CATEGORY_ORDER: tuple[CostCategory, ...] = (
    CostCategory.CAPEX,
    CostCategory.ONE_TIME_OTHER,
    CostCategory.OPEX_PER_DAY,
    CostCategory.OPEX_PER_YEAR,
)


def money_phrase(category: CostCategory, amount: float) -> str:
    """One figure with its kind attached — "EUR 18,000/day operating cost"."""
    member = CostCategory(category)
    try:
        suffix = _CATEGORY_SUFFIX[member]
    except KeyError as exc:  # pragma: no cover - guarded by test
        raise UnmappedInternalTerm(
            f"No user-facing suffix for cost category {category!r}. "
            f"Add one to strategy_language._CATEGORY_SUFFIX before it can be shown."
        ) from exc
    return f"EUR {amount:,.0f}{suffix}"


def known_cost_phrase(profile) -> str:
    """Everything a strategy is KNOWN to cost, in one clause (G14)."""
    known = dict(profile.known_by_category)
    if profile.commercially_complete:
        known.setdefault(CostCategory.CAPEX, profile.known_capex)
    parts = [
        money_phrase(category, known[category])
        for category in _CATEGORY_ORDER
        if category in known
    ]
    return join_phrases(parts)
