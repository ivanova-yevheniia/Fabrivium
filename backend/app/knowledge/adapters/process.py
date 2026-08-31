"""
Process knowledge — which operations a product's facts imply, and in what order.

CANONICAL SOURCE
----------------
``app.services.process_planning``. Its ``_RULES`` table IS the process
knowledge: one row per product fact that implies a manufacturing operation.
Every item below is read out of that table, so the knowledge base cannot
describe a rule the planner does not have, or miss one it does.

WHAT IS A POINTER AND WHY
-------------------------
Two pieces of process knowledge are not tabular and are published as
pointers rather than restated:

* precedence ordering — ``_order_by_precedence`` decides from the SOURCE
  DOCUMENT's own words that a lid cannot be fastened before it is fitted.
  The knowledge is the procedure, and a prose summary of a procedure is the
  kind of copy that drifts.
* requirement coverage — ``app.services.requirement_coverage`` decides when
  a stated requirement has gone unanswered. Same reason.
"""

from __future__ import annotations

from app.knowledge.contract import (
    Applicability,
    EngineeringKnowledgeItem,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeExposure,
    KnowledgeKind,
    Provenance,
    SourceKind,
)

#: Bump when the SHAPE or SELECTION of what this adapter publishes changes.
PROCESS_ADAPTER_VERSION = "1.0.0"

_MODULE = "app.services.process_planning"


def _slug(fact_key: str) -> str:
    return fact_key.replace(".", "_")


def process_knowledge() -> list[EngineeringKnowledgeItem]:
    """Every process rule Fabrivium applies, read from the planner's own table."""
    from app.services import process_planning

    rules = process_planning._RULES
    repeating = process_planning._REPEATING

    items: list[EngineeringKnowledgeItem] = []

    for position, rule in enumerate(rules, start=1):
        items.append(
            EngineeringKnowledgeItem(
                id=f"process.rule.{_slug(rule.fact_key)}",
                version=PROCESS_ADAPTER_VERSION,
                kind=KnowledgeKind.RULE,
                category=KnowledgeCategory.PROCESS,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"{rule.name} implied by {rule.fact_key}",
                description=(
                    f"When the product understanding carries the fact '{rule.fact_key}', "
                    f"Fabrivium proposes a '{rule.name}' operation of process type "
                    f"'{rule.process_type}'."
                    + (
                        " The operation repeats once per unit of the fact's quantity."
                        if rule.fact_key in repeating
                        else " The operation is proposed once, not per unit of any quantity."
                    )
                    + (
                        " It fires only where the source document states an ACTION on the "
                        "thing — a specification listing a part says the product HAS one, "
                        "not that anybody fits it."
                        if rule.requires_action
                        else ""
                    )
                ),
                provenance=Provenance(
                    source_kind=SourceKind.IMPLEMENTED_RULE,
                    source_reference=f"{_MODULE}._RULES",
                    statement=(
                        "A rule implemented in Fabrivium's process planner. Every proposed "
                        "operation names the product fact that triggered it and the cited "
                        "sentence that fact came from."
                    ),
                ),
                applicability=Applicability(
                    scope=(
                        "Applies wherever the named fact is extracted from a product "
                        "specification. The proposal is a draft for engineering review; it "
                        "sets no cycle time, capacity or operator count."
                    ),
                    process_categories=(rule.process_type,),
                    not_valid_for=(
                        "Deciding that the operation is correct. The planner proposes; the "
                        "engineer accepts, edits or rejects."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "fact_key": rule.fact_key,
                    "process_type": rule.process_type,
                    "operation_name": rule.name,
                    "also_covers": list(rule.also_covers),
                    "requires_stated_action": rule.requires_action,
                    "repeats_with_quantity": rule.fact_key in repeating,
                    "closes": list(rule.closes),
                    "fastens": rule.fastens,
                    "default_build_position": position,
                },
                tags=("process-rule", "operation-derivation", rule.process_type),
            )
        )

    items.append(
        EngineeringKnowledgeItem(
            id="process.default_build_order",
            version=PROCESS_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Default build order of proposed operations",
            description=(
                "The order of the rule table is the default route order: place, connect, "
                "close, fasten, mark, inspect, pack. A route is a sequence, and proposing "
                "one unordered would hand the sequencing work back to the engineer."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference=f"{_MODULE}._RULES",
                statement="Read from the declaration order of the planner's rule table.",
            ),
            applicability=Applicability(
                scope=(
                    "The starting order for any proposed route. Overridden per document by "
                    "the product's own precedence constraints."
                ),
                not_valid_for="A final manufacturing sequence. It is a default, not a plan.",
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={"order": [rule.name for rule in rules]},
            tags=("process-rule", "route-order"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="process.precedence_from_source",
            version=PROCESS_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Ordering constraints read from the product document",
            description=(
                "One ordering constraint is a fact about the PRODUCT rather than about the "
                "rule table: a lid cannot be fastened before it is fitted. Fabrivium applies "
                "that constraint only where the source document ties the fastening to the "
                "closure in its own words, and moves the operation accordingly. The "
                "procedure is the knowledge; it is located here, not restated."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference=f"{_MODULE}._order_by_precedence",
                statement="A procedure implemented in Fabrivium's process planner.",
            ),
            applicability=Applicability(
                scope="Applies to a proposed route derived from a product document.",
                not_valid_for=(
                    "Documents that state no relationship between a fastening and a "
                    "closure. Nothing is reordered on a guess."
                ),
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("process-rule", "route-order", "precedence"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="process.requirement_coverage",
            version=PROCESS_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="A stated requirement that no operation answers is reported, not dropped",
            description=(
                "A product fact with no matching rule produces no operation. Fabrivium "
                "reports that as an unaddressed requirement with a severity rather than "
                "letting it disappear — a silently dropped requirement is worse than a "
                "missing feature, because the output still looks complete. Coverage is a "
                "list, never a percentage: one unaddressed critical requirement matters "
                "more than ten addressed cosmetic ones."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.requirement_coverage",
                statement="A rule implemented in Fabrivium's requirement coverage service.",
            ),
            applicability=Applicability(
                scope="Applies to every proposed route built from a product document.",
                not_valid_for=(
                    "Inventing the missing operation. Whether labelling is in scope for a "
                    "line is an engineering decision, and this rule only makes the omission "
                    "visible."
                ),
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("process-rule", "coverage", "fail-visible"),
        )
    )

    return items
