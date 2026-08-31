"""Process Planning Skill — Phase 19."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.process_draft import ManufacturingProcessDraft, ProposedOperation
from app.models.product import FactStatus, ProductFact, ProductUnderstanding


@dataclass(frozen=True)
class _Rule:
    """One proposal rule: a product fact, and the operation it implies."""

    # The fact whose presence triggers the operation.
    fact_key: str
    process_type: str
    name: str
    # Other facts this operation legitimately answers when the source states them.
    also_covers: tuple[str, ...] = ()
    #: Fire only where the source states an ACTION on the thing, not merely
    #: that the product contains one. See the module docstring.
    requires_action: bool = False
    #: This operation closes an assembly, and these are the words the source
    #: would use for what it closes. Fastening that the source ties to one
    #: of them must follow this operation.
    closes: tuple[str, ...] = ()
    # This operation fastens.
    fastens: bool = False


_RULES: tuple[_Rule, ...] = (
    _Rule("component.pcb", "assembly", "PCB placement"),
    _Rule("connection.cable.count", "assembly", "Cable connection"),
    _Rule(
        "fastener.screw.count", "screwdriving", "Screw fastening",
        also_covers=("fastener.screw.thread", "fastener.screw.drive", "fastener.screw.torque"),
        fastens=True,
    ),
    _Rule(
        "fastener.bolt.count", "screwdriving", "Bolt fastening",
        also_covers=("fastener.bolt.thread", "fastener.bolt.drive", "fastener.bolt.torque"),
        fastens=True,
    ),
    _Rule(
        "component.lid", "assembly", "Enclosure closure",
        closes=("lid", "cover", "enclosure", "housing", "closure"),
    ),
    _Rule("component.label", "labelling", "Product labelling", requires_action=True),
    _Rule("requirement.inspection", "inspection", "Visual inspection"),
    _Rule("requirement.packaging", "packaging", "Packaging"),
)

# Facts whose quantity becomes the operation's repeat count.
_REPEATING = frozenset({"fastener.screw.count", "fastener.bolt.count", "connection.cable.count"})

# Verbs that turn a named part into work somebody has to do.
_ACTION_VERBS = frozenset({
    "applied", "apply", "applies", "attached", "attach", "affixed", "affix",
    "fitted", "fit", "printed", "print", "marked", "mark", "labelled",
    "labeled", "placed", "installed", "fixed",
})


def _tokens(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z]+", text.lower()))


def _cited_words(fact: ProductFact) -> set[str]:
    """Every word the source used in the sentences this fact cites."""
    words: set[str] = set()
    for reference in fact.evidence:
        words |= _tokens(reference.quote or "")
    return words


@dataclass
class _Planned:
    """A rule that fired, with the fact that fired it."""

    rule: _Rule
    fact: ProductFact
    repeats: int | None = None
    covers: list[str] = field(default_factory=list)


def _order_by_precedence(planned: list[_Planned]) -> list[_Planned]:
    """Apply the ordering constraints the SOURCE states, not the table's."""
    ordered = list(planned)

    for fastening in [item for item in planned if item.rule.fastens]:
        words = _cited_words(fastening.fact)
        target: _Planned | None = None
        for closure in [item for item in ordered if item.rule.closes]:
            if ordered.index(closure) <= ordered.index(fastening):
                # Already after it — the table's order is fine here.
                continue
            if words & set(closure.rule.closes):
                # The last closure it must follow wins, so a route with two
                # closures leaves the fastening after both of the ones its
                # own evidence ties it to.
                target = closure
        if target is None:
            continue
        ordered.remove(fastening)
        ordered.insert(ordered.index(target) + 1, fastening)

    return ordered


def plan_process(understanding: ProductUnderstanding) -> ManufacturingProcessDraft:
    """Propose the manufacturing operations the product facts imply."""
    planned: list[_Planned] = []
    questions: list[str] = []

    for rule in _RULES:
        key = rule.fact_key
        fact = understanding.fact(key)
        if fact is None or fact.status is FactStatus.UNKNOWN:
            continue

        if rule.requires_action and not (_cited_words(fact) & _ACTION_VERBS):
            # The source names the part and never says anybody does anything with it.
            continue

        repeats: int | None = None
        if key in _REPEATING:
            if fact.status is FactStatus.CONFLICT:
                # The operation is real; how many times it happens is not settled.
                questions.append(
                    f"{fact.label}: sources disagree "
                    f"({', '.join(a.value or '?' for a in fact.alternatives)}). "
                    "Resolve it before the repeat count can be used."
                )
            elif fact.quantity:
                repeats = int(fact.quantity)
            else:
                # The source names the thing without counting it.
                questions.append(
                    f"{fact.label}: the source does not state how many. "
                    "Enter the count before a cycle time is estimated from it."
                )

        covers = [key] + [
            extra
            for extra in rule.also_covers
            if (found := understanding.fact(extra)) is not None
            and found.status is not FactStatus.UNKNOWN
        ]
        planned.append(_Planned(rule=rule, fact=fact, repeats=repeats, covers=covers))

    # Ids are assigned only after ordering, so the number in an operation's
    # id still matches its position in the route it was proposed as.
    operations: list[ProposedOperation] = []
    for item in _order_by_precedence(planned):
        rule, fact, repeats = item.rule, item.fact, item.repeats
        operations.append(
            ProposedOperation(
                id=f"op-{len(operations) + 1}-{rule.process_type}",
                process_type=rule.process_type,
                name=rule.name if repeats is None else f"{rule.name} ×{repeats}",
                description=_describe(rule.name, fact.label, repeats),
                repeated_operations=repeats,
                basis=_basis(fact.label, fact.value, repeats),
                source_fact_keys=item.covers,
                evidence=list(fact.evidence[:2]),
                # RULE_DERIVED, not AI_INFERRED: this function is a rule
                # table and the draft it returns records method="LOCAL_RULES".
                # Claiming a model inferred the operation would credit the AI
                # with deterministic work — the direction of error a reviewer
                # is most entitled to object to.
                fact_status=FactStatus.RULE_DERIVED,
                confidence="HIGH" if fact.status is FactStatus.EXTRACTED else "MEDIUM",
            )
        )

    if not operations:
        questions.append(
            "No manufacturing operations could be derived. The source does not name components, "
            "fasteners, connections, inspection or packaging."
        )

    # An inspection stage is proposed only when something asks for one.
    if operations and understanding.fact("requirement.inspection") is None:
        questions.append("Is any inspection required? The source does not say.")

    return ManufacturingProcessDraft(
        product_name=understanding.product_name,
        operations=operations,
        method="LOCAL_RULES",
        open_questions=questions,
    )


def _describe(name: str, fact_label: str, repeats: int | None) -> str:
    if repeats:
        return f"{name}, {repeats} times per unit, implied by {fact_label.lower()}."
    return f"{name}, implied by {fact_label.lower()}."


def _basis(fact_label: str, value: str | None, repeats: int | None) -> str:
    """One sentence naming the fact that produced the operation."""
    if repeats:
        return f"The product information states {repeats} × {fact_label.lower()}."
    if value and value not in ("present", "stated"):
        return f"The product information states {fact_label.lower()}: {value}."
    return f"The product information states {fact_label.lower()}."


# Conversion into the existing concept

def draft_to_stages(draft: ManufacturingProcessDraft) -> list[dict]:
    """Accepted operations as ConceptStage constructor arguments."""
    stages: list[dict] = []
    used: set[str] = set()

    for operation in draft.accepted:
        # A stable, readable id in the same shape the concept builder
        # produces, so Phase 18B's reference bands and the existing UI both
        # recognise it.
        base = f"m-{operation.process_type}"
        stage_id = base
        suffix = 2
        while stage_id in used:
            stage_id = f"{base}-{suffix}"
            suffix += 1
        used.add(stage_id)

        stages.append(
            {
                "id": stage_id,
                "name": operation.name,
                "process_type": operation.process_type,
                "repeated_operations": operation.repeated_operations,
                "source_operation_id": operation.id,
            }
        )
    return stages
