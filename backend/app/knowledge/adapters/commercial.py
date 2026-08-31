"""
Commercial knowledge — what kind of money a decision costs, and what an
unknown price means.

CANONICAL SOURCE
----------------
``app.services.strategy_cost``. Its ``_ACTION_COST_RULES`` table maps each
engineering lever to the CATEGORY of money it costs and the information gap
it opens when that money is unknown. One row per lever, read here directly.

THE RULE THE WHOLE CATEGORY EXISTS TO ENFORCE
---------------------------------------------
    an unknown cost is not a zero cost

A caller comparing EUR 205,000 against EUR 0 has no structural reason not to
call the second one cheaper. So every unpriced action produces an explicit
information gap naming exactly what must be supplied, and the strategy stays
commercially incomplete until it is.

AND THERE IS NO TOTAL
---------------------
A machine purchase is capital, a third shift is an operating cost per day,
two more operators are an operating cost per year. Those are not addable,
and Fabrivium never adds them — there is deliberately no total-cost function
anywhere in the costing module. The categories exist to keep unlike things
apart, not to convert between them, and no net present value, total cost of
ownership or depreciation is computed.
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

COMMERCIAL_ADAPTER_VERSION = "1.0.0"

_COST_MODULE = "app.services.strategy_cost"


def commercial_knowledge() -> list[EngineeringKnowledgeItem]:
    """Cost semantics and the rules governing missing commercial data."""
    from app.models.equipment_discovery import PriceStatus
    from app.models.strategy import CostCategory, InformationGapType
    from app.services import strategy_cost

    rules = strategy_cost._ACTION_COST_RULES

    items: list[EngineeringKnowledgeItem] = []

    for action_type, (category, gap_type, description) in sorted(rules.items()):
        items.append(
            EngineeringKnowledgeItem(
                id=f"commercial.cost_semantics.{action_type.lower()}",
                version=COMMERCIAL_ADAPTER_VERSION,
                kind=KnowledgeKind.RULE,
                category=KnowledgeCategory.COMMERCIAL,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"Cost category of {action_type} — {category.value}",
                description=(
                    f"Choosing this lever incurs {category.value}: the {description}. "
                    f"Fabrivium does not hold that figure, so the strategy carries an "
                    f"explicit {gap_type.value} information gap until somebody supplies it, "
                    f"and is marked commercially incomplete meanwhile. Supplying the price "
                    f"changes the commercial picture only — it never re-runs a simulation, "
                    f"because a number cannot move a machine."
                ),
                provenance=Provenance(
                    source_kind=SourceKind.IMPLEMENTED_RULE,
                    source_reference=f"{_COST_MODULE}._ACTION_COST_RULES['{action_type}']",
                    statement=(
                        "A cost-semantics rule implemented in Fabrivium's strategy costing "
                        "module. It classifies money; it does not price anything."
                    ),
                ),
                applicability=Applicability(
                    scope="Any accepted strategy iteration that uses this lever.",
                    not_valid_for=(
                        "Producing a number. Fabrivium states the category and the gap; the "
                        "amount comes from the organisation."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "action_type": action_type,
                    "cost_category": category.value,
                    "information_gap_type": gap_type.value,
                    "what_is_unknown": description,
                },
                status="UNKNOWN_UNTIL_SUPPLIED",
                tags=("commercial", "cost-semantics", category.value.lower()),
            )
        )

    items.append(
        EngineeringKnowledgeItem(
            id="commercial.priced_from_factory_data",
            version=COMMERCIAL_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.COMMERCIAL,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Adding a parallel machine is the one lever the factory data already prices",
            description=(
                "It is priced from the machine's own recorded purchase cost and opens no "
                "information gap — which is why it is absent from the cost-semantics table. "
                "Where the factory records no purchase cost for that station, the gap is "
                "reported against the station in the words the rest of the product uses for "
                "it, not against a database key."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference=f"{_COST_MODULE}.build_cost_profile",
                statement="The one directly-priced lever in Fabrivium's costing module.",
            ),
            applicability=Applicability(
                scope="Strategies that add a parallel machine at an existing station.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("commercial", "cost-semantics", "capex"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="commercial.unknown_is_not_zero",
            version=COMMERCIAL_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.COMMERCIAL,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="An unknown cost is not a zero cost, and unlike costs are never totalled",
            description=(
                "Every unpriced action produces an explicit information gap naming what must "
                "be supplied. Categories keep unlike money apart — capital, operating cost "
                "per day, operating cost per year, one-off other — and there is deliberately "
                "no total-cost function anywhere in the costing module. No net present "
                "value, total cost of ownership or depreciation is computed."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference=_COST_MODULE,
                statement="The costing rule Fabrivium's strategy cost module exists to enforce.",
            ),
            applicability=Applicability(
                scope="Every commercial comparison of two verified strategies.",
                not_valid_for=(
                    "Financial appraisal. Fabrivium classifies and reports money; it does "
                    "not evaluate an investment."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={
                "cost_categories": [c.value for c in CostCategory],
                "information_gap_types": [g.value for g in InformationGapType],
                "total_cost_function_exists": False,
            },
            tags=("commercial", "cost-semantics", "fail-visible"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="commercial.price_status_semantics",
            version=COMMERCIAL_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.COMMERCIAL,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Three distinct answers to 'what does this equipment cost?'",
            description=(
                "PUBLISHED — the supplier states a price. QUOTE_REQUIRED — they price on "
                "request, which is a commercial answer rather than a gap in Fabrivium's "
                "data. UNKNOWN — nobody has told us. The three are kept apart because "
                "collapsing them would either invent a missing price or report a normal "
                "commercial practice as a defect."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.models.equipment_discovery.PriceStatus",
                statement="The price vocabulary Fabrivium's equipment records use.",
                classification_vocabulary="PriceStatus",
                classification="UNKNOWN",
            ),
            applicability=Applicability(
                scope="Every equipment record from every catalogue.",
                not_valid_for=(
                    "Treating a zero as an unknown or an unknown as a zero. The only "
                    "legitimate zero is equipment the customer already owns."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={"price_statuses": [p.value for p in PriceStatus]},
            tags=("commercial", "equipment", "provenance"),
        )
    )

    return items
