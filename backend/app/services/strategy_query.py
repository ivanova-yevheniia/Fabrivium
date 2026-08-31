"""Follow-up questions about an already-explored arena (Phase 8B section 15)."""

from __future__ import annotations

import re

from app.models.orchestrator import PlanningSessionState
from app.models.strategy import (
    CostCategory,
    InformationGapType,
    StrategyArenaResult,
    StrategyQueryAnswer,
    StrategyQueryIntent,
    UserCostInput,
    VerifiedStrategyOption,
)
from app.services.strategy_arena import compute_frontiers, recommend
from app.services.strategy_comparison import compare_strategies
from app.services.strategy_cost import build_cost_profile
from app.services.strategy_language import (
    action_phrase,
    category_phrase,
    gap_phrase,
    gap_phrases_for,
    join_phrases,
    known_cost_phrase,
)

# Intent detection

#: Order matters: PROVIDE_COST is tested first because "an extra shift
#: costs EUR 18k/day" contains "cost", which would otherwise read as a
#: request for a cheaper option. A statement of fact and a request are
#: different acts, and confusing them would silently discard the number the
#: user just supplied.
_COST_STATEMENT_RE = re.compile(
    r"\b(?:costs?|is|are|would\s+be|price[ds]?\s+at|budget)\b[^.]{0,20}?"
    r"(?:€|eur|euro|\$|£)?\s*\d",
    re.IGNORECASE,
)

_CHEAPER_RE = re.compile(
    r"\bcheap(?:er|est)\b"
    r"|\bless\s+expensive\b"
    r"|\blower\s+(?:cost|capex|spend|budget)\b"
    r"|\bsomething\s+cheaper\b",
    re.IGNORECASE,
)

_NO_MACHINE_RE = re.compile(
    r"\b(?:without|no|avoid|skip|not?)\b[^.]{0,30}\b(?:new\s+|another\s+|extra\s+|additional\s+)?"
    r"(?:machine|machines|equipment)\b",
    re.IGNORECASE,
)

_FEWEST_CHANGES_RE = re.compile(
    r"\b(?:fewest|least|minimum|smallest\s+number|simplest)\b[^.]{0,30}"
    r"\b(?:changes?|interventions?|actions?|steps?|modifications?)\b"
    r"|\bsimplest\s+(?:plan|option|strategy)\b",
    re.IGNORECASE,
)

_COMPARE_RE = re.compile(
    r"\b(?:compare|versus|vs\.?|difference\s+between|side\s+by\s+side)\b", re.IGNORECASE
)

_INFORMATION_RE = re.compile(
    r"\bwhat\b[^.]{0,40}\b(?:information|data|numbers?|costs?|inputs?)\b[^.]{0,40}\b(?:need|missing|required|still)\b"
    r"|\b(?:information|data)\b[^.]{0,20}\b(?:still\s+)?(?:needed|missing|required)\b"
    r"|\bwhat\s+(?:is|are)\s+missing\b"
    r"|\bwhat\s+(?:do\s+we|do\s+I)\s+(?:still\s+)?need\b",
    re.IGNORECASE,
)

# "Plan A", "plan c", "option B".
_PLAN_LABEL_RE = re.compile(r"\b(?:plan|option|strategy)\s+([A-Z])\b", re.IGNORECASE)


def detect_intent(text: str) -> StrategyQueryIntent:
    """Classify a follow-up."""
    if _COST_STATEMENT_RE.search(text) and _parse_cost_inputs(text):
        return StrategyQueryIntent.PROVIDE_COST
    if _COMPARE_RE.search(text):
        return StrategyQueryIntent.COMPARE
    if _INFORMATION_RE.search(text):
        return StrategyQueryIntent.INFORMATION_NEEDED
    if _FEWEST_CHANGES_RE.search(text):
        return StrategyQueryIntent.FEWEST_CHANGES
    if _NO_MACHINE_RE.search(text):
        return StrategyQueryIntent.NO_NEW_MACHINE
    if _CHEAPER_RE.search(text):
        return StrategyQueryIntent.CHEAPER_OPTION
    return StrategyQueryIntent.UNRECOGNIZED


# Cost statements (section 18)

#: Which gap a cost statement is about, and the category it defaults to
#: when the sentence names no time basis. Same source of truth as
#: ``strategy_cost._ACTION_COST_RULES``, expressed from the user's side.
_SUBJECT_RULES: list[tuple[re.Pattern[str], InformationGapType, CostCategory]] = [
    (re.compile(r"\bshifts?\b", re.IGNORECASE), InformationGapType.SHIFT_COST, CostCategory.OPEX_PER_DAY),
    (
        re.compile(r"\boperators?\b|\bstaff\b|\bworkers?\b|\bpeople\b|\bhead\s?count\b", re.IGNORECASE),
        InformationGapType.OPERATOR_COST,
        CostCategory.OPEX_PER_YEAR,
    ),
    (
        re.compile(r"\bbuffers?\b|\bwip\s+cap\b", re.IGNORECASE),
        InformationGapType.BUFFER_MODIFICATION_COST,
        CostCategory.ONE_TIME_OTHER,
    ),
    (
        re.compile(r"\bcycle\s?time\b|\bprocess\s+improvement\b|\bspeed\s?up\b|\bfaster\s+cycle\b", re.IGNORECASE),
        InformationGapType.PROCESS_IMPROVEMENT_COST,
        CostCategory.ONE_TIME_OTHER,
    ),
    (
        re.compile(r"\bmachine\s+capacity\b|\bcapacity\s+upgrade\b", re.IGNORECASE),
        InformationGapType.MACHINE_CAPACITY_COST,
        CostCategory.ONE_TIME_OTHER,
    ),
]

_AMOUNT_RE = re.compile(
    r"(?:€|eur|euro|\$|£)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|m|million)?\s*(?:€|eur|euros?)?",
    re.IGNORECASE,
)

_PER_DAY_RE = re.compile(r"(?:/|\bper\s+|\ba\s+)day\b|\bdaily\b", re.IGNORECASE)
_PER_YEAR_RE = re.compile(r"(?:/|\bper\s+|\ba\s+)(?:year|annum)\b|\bannual(?:ly)?\b|\bp\.?a\.?\b", re.IGNORECASE)
_ONE_OFF_RE = re.compile(r"\bone[-\s]?off\b|\bone[-\s]?time\b|\bup[-\s]?front\b", re.IGNORECASE)


def _scale(digits: str, suffix: str | None) -> float:
    value = float(digits.replace(",", ""))
    unit = (suffix or "").lower()
    if unit in ("k", "thousand"):
        value *= 1_000
    elif unit in ("m", "million"):
        value *= 1_000_000
    return value


def _parse_cost_inputs(text: str) -> list[UserCostInput]:
    """Extract explicit costs the user stated."""
    inputs: list[UserCostInput] = []
    seen: set[InformationGapType] = set()

    for clause in re.split(r"\band\b|[;,]|\.", text):
        if not clause.strip():
            continue

        subject = next(
            ((gap, default) for pattern, gap, default in _SUBJECT_RULES if pattern.search(clause)),
            None,
        )
        if subject is None:
            continue
        gap_type, default_category = subject
        if gap_type in seen:
            continue

        # Take the LAST number in the clause: "two additional operators cost
        # EUR 90k/year" mentions a quantity before it mentions a price, and
        # the price is the fact being supplied.
        amounts = [m for m in _AMOUNT_RE.finditer(clause) if m.group(1)]
        if not amounts:
            continue
        match = amounts[-1]
        amount = _scale(match.group(1), match.group(2))
        if amount <= 0:
            continue

        if _PER_DAY_RE.search(clause):
            category = CostCategory.OPEX_PER_DAY
        elif _PER_YEAR_RE.search(clause):
            category = CostCategory.OPEX_PER_YEAR
        elif _ONE_OFF_RE.search(clause):
            category = CostCategory.ONE_TIME_OTHER
        else:
            category = default_category

        seen.add(gap_type)
        inputs.append(UserCostInput(
            gap_type=gap_type,
            amount=amount,
            category=category,
            note=clause.strip(),
        ))

    return inputs


def parse_cost_inputs(text: str) -> list[UserCostInput]:
    """Public wrapper — see ``_parse_cost_inputs``."""
    return _parse_cost_inputs(text)


# Answering


def _by_label(arena: StrategyArenaResult, text: str) -> list[VerifiedStrategyOption]:
    """Resolve "Plan A"/"Option C" mentions, in the order written."""
    wanted = [m.group(1).upper() for m in _PLAN_LABEL_RE.finditer(text)]
    resolved: list[VerifiedStrategyOption] = []
    for letter in wanted:
        match = next((o for o in arena.strategies if o.label.upper().endswith(f" {letter}")), None)
        if match is not None and match not in resolved:
            resolved.append(match)
    return resolved


def _describe(option: VerifiedStrategyOption) -> str:
    """One clause of verified fact about a strategy — never a value judgement."""
    goal = "reaches the target" if option.metrics.goal_met else f"falls {option.metrics.demand_gap_units:,.0f} units/day short"
    return (
        f"{option.label} ({option.title.lower()}) {goal} at {option.metrics.completed_units:,}/day "
        f"with {option.actions.action_count} change{'s' if option.actions.action_count != 1 else ''}"
    )


def _cost_clause(option: VerifiedStrategyOption) -> str:
    # Every category that HAS a price, not just the capital one — a plan
    # whose only cost is an extra shift has EUR 0 CAPEX and is not free
    # (G14). `known_cost_phrase` returns "" when nothing is priced, which is
    # said in words rather than as a zero.
    known = known_cost_phrase(option.cost)
    if option.commercially_complete:
        return f"{known}, fully priced" if known else "nothing priced"
    missing = len(option.cost.information_gaps)
    unknown = f"{missing} cost input{'s' if missing != 1 else ''} still unknown"
    return f"{known}, but {unknown}" if known else f"nothing priced yet — {unknown}"


def _answer_cheaper(arena: StrategyArenaResult) -> StrategyQueryAnswer:
    """"Show me a cheaper option."""
    if not arena.strategies:
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.CHEAPER_OPTION,
            answer="No verified options are available to compare on cost.",
        )

    reaching = [o for o in arena.strategies if o.metrics.goal_met]
    pool = reaching or list(arena.strategies)
    # Phrased for singular agreement: it follows "option" in both sentences.
    scope = "that reaches the target" if reaching else "explored"

    by_capex = lambda o: (o.cost.known_capex, o.strategy_id)  # noqa: E731
    priced = sorted((o for o in pool if o.commercially_complete), key=by_capex)
    unpriced = sorted((o for o in pool if not o.commercially_complete), key=by_capex)

    parts: list[str] = []
    ids: list[str] = []

    if priced:
        best = priced[0]
        ids.append(best.strategy_id)
        superlative = "The lowest fully-priced option" if len(priced) > 1 else "The only fully-priced option"
        # Every priced category, so "EUR 0 CAPEX" can never stand as the
        # whole cost of a plan that also runs an extra shift (G14).
        money = known_cost_phrase(best.cost) or "no cost recorded"
        parts.append(
            f"{superlative} {scope} is {best.label}, at {money} "
            f"({best.metrics.completed_units:,}/day, {best.actions.action_count} "
            f"change{'s' if best.actions.action_count != 1 else ''})."
        )
        # Naming a "lowest" across plans whose money is of different kinds
        # would be a comparison nobody can make. Say which, rather than
        # ranking on the one category they happen to share.
        if len(priced) > 1:
            kinds = {c for o in priced for c in o.cost.known_by_category}
            if len(kinds) > 1:
                parts.append(
                    "Ranked on capital cost; the fully-priced options also differ in operating "
                    "cost, which is a different kind of money and is not added to it."
                )
    else:
        parts.append(
            f"No option {scope} is fully priced, so none of them can be called cheaper on established cost."
        )

    for option in unpriced:
        # The gaps NAMED, not their enum members.
        gap_names = gap_phrases_for(g.gap_type for g in option.cost.information_gaps)
        # "lower" only when there is a priced option it is actually lower than.
        cheaper_than_priced = priced and option.cost.known_capex < priced[0].cost.known_capex
        known = known_cost_phrase(option.cost)
        if not known:
            # Nothing at all is priced.
            figure = "no established cost yet"
        elif cheaper_than_priced:
            figure = f"a lower known capital cost, {known}"
        else:
            figure = f"a known {known}"
        ids.append(option.strategy_id)
        parts.append(
            f"{option.label} shows {figure}, but that is not a full price — "
            f"{gap_names} must be supplied before it can be ranked financially."
        )

    # A fully-priced plan that merely falls short is still worth naming when
    # the pool excluded it: the user asked about money, and hiding the one
    # plan whose money is actually settled would answer badly.
    if reaching:
        outside = sorted(
            (o for o in arena.strategies if o.commercially_complete and not o.metrics.goal_met),
            key=by_capex,
        )
        if outside and (not priced or outside[0].cost.known_capex < priced[0].cost.known_capex):
            other = outside[0]
            ids.append(other.strategy_id)
            money = known_cost_phrase(other.cost) or "no cost recorded"
            parts.append(
                f"{other.label} is fully priced at {money}, but falls "
                f"{other.metrics.demand_gap_units:,.0f} units/day short of the target."
            )

        # An unpriced plan that fell outside the goal-reaching pool was
        # dropped silently, which made the answer read as a settled ranking
        # over the whole arena (G14). It is not one: an option whose price
        # nobody has established cannot be placed against a priced plan at
        # all, and saying so is the difference between "Plan B is cheapest"
        # and "Plan B is the only one that can be ranked yet".
        for option in arena.strategies:
            if option.strategy_id in ids or option.commercially_complete:
                continue
            gap_names = gap_phrases_for(g.gap_type for g in option.cost.information_gaps)
            ids.append(option.strategy_id)
            parts.append(
                f"{option.label} cannot be ranked financially at all until {gap_names} "
                f"is supplied, so no cheapest option across every plan can be named yet."
            )

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.CHEAPER_OPTION,
        answer=" ".join(parts),
        strategy_ids=ids,
        information_gaps=[g for o in unpriced for g in o.cost.information_gaps],
    )


def _answer_no_machine(arena: StrategyArenaResult) -> StrategyQueryAnswer:
    """"Can we do it without another machine?"""
    machine_free = [o for o in arena.strategies if o.actions.added_machine_count == 0]
    reaching = [o for o in machine_free if o.metrics.goal_met]

    if reaching:
        best = min(reaching, key=lambda o: (o.actions.action_count, o.cost.known_capex, o.strategy_id))
        answer = (
            f"Yes — {_describe(best)} and no new equipment. Its cost profile: {_cost_clause(best)}."
        )
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.NO_NEW_MACHINE,
            answer=answer,
            strategy_ids=[best.strategy_id],
            information_gaps=list(best.cost.information_gaps),
        )

    if machine_free:
        best = max(machine_free, key=lambda o: (o.metrics.completed_units, o.strategy_id))
        # _describe already states the shortfall, so this sentence must not
        # repeat it — it names the option and stops.
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.NO_NEW_MACHINE,
            answer=(
                f"Not with the levers explored so far. The best machine-free option is {best.label} "
                f"({best.title.lower()}), which reaches {best.metrics.completed_units:,}/day with "
                f"{best.actions.action_count} change{'s' if best.actions.action_count != 1 else ''} "
                f"and still leaves a gap of {best.metrics.demand_gap_units:,.0f} units/day."
            ),
            strategy_ids=[best.strategy_id],
            information_gaps=list(best.cost.information_gaps),
        )

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.NO_NEW_MACHINE,
        answer="None of the explored options avoids new equipment.",
    )


def _answer_fewest_changes(arena: StrategyArenaResult) -> StrategyQueryAnswer:
    """"Which plan uses the fewest changes?"""
    if not arena.strategies:
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.FEWEST_CHANGES,
            answer="No verified options are available.",
        )

    reaching = [o for o in arena.strategies if o.metrics.goal_met]
    pool = reaching or list(arena.strategies)
    best = min(pool, key=lambda o: (o.actions.action_count, o.cost.known_capex, o.strategy_id))
    tied = [o for o in pool if o.actions.action_count == best.actions.action_count and o is not best]

    qualifier = " among the options that reach the target" if reaching else ""
    # The levers pulled, in words.
    levers = join_phrases([action_phrase(a) for a in best.actions.action_types]) or "none"
    answer = (
        f"{best.label} uses the fewest changes{qualifier}: {best.actions.action_count} "
        f"({levers}). {_describe(best)}, "
        f"{_cost_clause(best)}."
    )
    if tied:
        answer += f" Tied on change count with {', '.join(o.label for o in tied)}."

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.FEWEST_CHANGES,
        answer=answer,
        strategy_ids=[best.strategy_id] + [o.strategy_id for o in tied],
    )


def _answer_compare(arena: StrategyArenaResult, text: str) -> StrategyQueryAnswer:
    """"Compare Plan A and Plan C." — delegates every number to
    ``compare_strategies``, the same deterministic function the UI uses."""
    named = _by_label(arena, text)
    if len(named) < 2:
        available = ", ".join(o.label for o in arena.strategies) or "none"
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.COMPARE,
            answer=f"Name two options to compare. Available: {available}.",
            strategy_ids=[o.strategy_id for o in named],
        )

    a, b = named[0], named[1]
    comparison = compare_strategies(a, b)
    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.COMPARE,
        answer=" ".join([comparison.headline, *comparison.notes]),
        strategy_ids=[a.strategy_id, b.strategy_id],
        comparison=comparison,
        information_gaps=[*comparison.information_gaps_a, *comparison.information_gaps_b],
    )


def _answer_information_needed(arena: StrategyArenaResult, text: str) -> StrategyQueryAnswer:
    """"What information do we still need before choosing Plan B?"""
    named = _by_label(arena, text)
    targets = named or [o for o in arena.strategies if not o.commercially_complete]

    if not targets:
        return StrategyQueryAnswer(
            intent=StrategyQueryIntent.INFORMATION_NEEDED,
            answer="Every explored option is fully priced — nothing further is required to rank them on cost.",
        )

    parts: list[str] = []
    gaps = []
    for option in targets:
        if option.commercially_complete:
            # By category: a plan with no capital cost still has a price
            # to state, and "EUR 0 CAPEX" alone would not state it (G14).
            money = known_cost_phrase(option.cost) or "no cost recorded"
            parts.append(f"{option.label} is fully priced at {money}.")
            continue
        gaps.extend(option.cost.information_gaps)
        needed = "; ".join(g.description.rstrip(".") for g in option.cost.information_gaps)
        parts.append(
            f"{option.label} reaches {option.metrics.completed_units:,}/day, but cannot be ranked "
            f"financially until this is provided: {needed}."
        )

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.INFORMATION_NEEDED,
        answer=" ".join(parts),
        strategy_ids=[o.strategy_id for o in targets],
        information_gaps=gaps,
    )


def _answer_provide_cost(arena: StrategyArenaResult, inputs: list[UserCostInput]) -> StrategyQueryAnswer:
    """Acknowledge supplied costs."""
    filled = {c.gap_type for c in inputs}
    still_open = gap_phrases_for(
        g.gap_type
        for o in arena.strategies
        for g in o.cost.information_gaps
        if g.gap_type not in filled
    )

    stated = join_phrases([
        f"{gap_phrase(c.gap_type)} = EUR {c.amount:,.0f} ({category_phrase(c.category)})"
        for c in inputs
    ])
    answer = f"Recorded: {stated}. Cost comparison updated; the engineering is unchanged."
    if still_open:
        answer += f" Still unknown: {still_open}."

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.PROVIDE_COST,
        answer=answer,
        cost_inputs=inputs,
        requires_repricing=True,
    )


def answer_strategy_query(arena: StrategyArenaResult, text: str) -> StrategyQueryAnswer:
    """Answer a follow-up about *arena* using ONLY data it already holds."""
    intent = detect_intent(text)

    if intent is StrategyQueryIntent.PROVIDE_COST:
        return _answer_provide_cost(arena, _parse_cost_inputs(text))
    if intent is StrategyQueryIntent.COMPARE:
        return _answer_compare(arena, text)
    if intent is StrategyQueryIntent.INFORMATION_NEEDED:
        return _answer_information_needed(arena, text)
    if intent is StrategyQueryIntent.FEWEST_CHANGES:
        return _answer_fewest_changes(arena)
    if intent is StrategyQueryIntent.NO_NEW_MACHINE:
        return _answer_no_machine(arena)
    if intent is StrategyQueryIntent.CHEAPER_OPTION:
        return _answer_cheaper(arena)

    return StrategyQueryAnswer(
        intent=StrategyQueryIntent.UNRECOGNIZED,
        answer="That is not a question about the explored options.",
    )


# Repricing (section 18)


def reprice_arena(
    arena: StrategyArenaResult,
    sessions: dict[str, PlanningSessionState],
    user_costs: list[UserCostInput],
) -> StrategyArenaResult:
    """Fold newly-supplied costs into an existing arena."""
    if not user_costs:
        return arena

    repriced: list[VerifiedStrategyOption] = []
    for option in arena.strategies:
        session = sessions.get(option.strategy_id)
        if session is None:
            # Without its session the cost cannot be re-derived from source data.
            repriced.append(option)
            continue
        profile = build_cost_profile(session, user_costs=user_costs)
        repriced.append(option.model_copy(update={
            "cost": profile,
            "commercially_complete": profile.commercially_complete,
        }))

    frontiers = compute_frontiers(repriced)

    # ``recommend`` reads only the SOFT preference fields, and
    # ``StrategyArena._run_family`` overrides nothing but
    # ``allowed_action_types`` — so every option carries the same
    # preferences and any one of them can stand for the user's. If a future
    # family run starts overriding a preference field too, this has to
    # become the original request rather than a sample of it.
    requirements = repriced[0].requirements if repriced else None

    from app.services.strategy_arena import _with_tradeoffs  # local: avoids an import cycle at module load

    with_tradeoffs = _with_tradeoffs(repriced, frontiers)

    return arena.model_copy(update={
        "strategies": with_tradeoffs,
        "frontiers": frontiers,
        "recommended_strategy_id": (
            recommend(with_tradeoffs, requirements) if requirements is not None else arena.recommended_strategy_id
        ),
    })
