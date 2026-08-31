"""Cost and information-gap derivation for Fabrivium Phase 8B."""

from __future__ import annotations

from app.models.orchestrator import PlanningSessionState
from app.models.strategy import (
    CostCategory,
    CostComponent,
    InformationGap,
    InformationGapType,
    StrategyCostProfile,
    UserCostInput,
)
from app.services.strategy_language import action_phrase

# What kind of money each action type costs, and which gap it opens when that money is
# unknown.
_ACTION_COST_RULES: dict[str, tuple[CostCategory, InformationGapType, str]] = {
    "CHANGE_SHIFT_CONFIGURATION": (
        CostCategory.OPEX_PER_DAY,
        InformationGapType.SHIFT_COST,
        "operating cost of the changed shift pattern",
    ),
    "CHANGE_OPERATOR_CAPACITY": (
        CostCategory.OPEX_PER_YEAR,
        InformationGapType.OPERATOR_COST,
        "employment cost of the additional operators",
    ),
    "CHANGE_BUFFER_CAPACITY": (
        CostCategory.ONE_TIME_OTHER,
        InformationGapType.BUFFER_MODIFICATION_COST,
        "cost of enlarging the buffer",
    ),
    "CHANGE_MACHINE_CYCLE_TIME": (
        CostCategory.ONE_TIME_OTHER,
        InformationGapType.PROCESS_IMPROVEMENT_COST,
        "cost of achieving the faster cycle time",
    ),
    "CHANGE_MACHINE_CAPACITY": (
        CostCategory.ONE_TIME_OTHER,
        InformationGapType.MACHINE_CAPACITY_COST,
        "cost of raising the machine's capacity",
    ),
}


def build_cost_profile(
    session: PlanningSessionState,
    *,
    user_costs: list[UserCostInput] | None = None,
) -> StrategyCostProfile:
    """Derive the cost profile of one verified strategy."""
    supplied = {c.gap_type: c for c in (user_costs or [])}

    components: list[CostComponent] = []
    gaps: list[InformationGap] = []
    known_capex = 0.0
    seen_gap_types: set[InformationGapType] = set()

    for iteration in session.iterations:
        if not iteration.accepted or iteration.selected_proposal is None:
            continue

        for action in iteration.selected_proposal.scenario.actions:
            action_type = action.action_type

            if action_type == "ADD_PARALLEL_MACHINE":
                # The one lever whose price the factory already states.
                machine_id = getattr(action, "machine_id", None)
                source = next((m for m in session.baseline_factory.machines if m.id == machine_id), None)
                amount = source.purchase_cost if source is not None else None
                # The STATION, in the words the rest of the product uses for it.
                station = source.name if source is not None else machine_id
                components.append(CostComponent(
                    label=f"Parallel machine at {station}",
                    category=CostCategory.CAPEX,
                    amount=amount,
                    source="CATALOG",
                ))
                if amount is not None:
                    known_capex += amount
                else:
                    # A machine with no recorded purchase cost is a genuine
                    # gap too — do not let it silently read as free.
                    gaps.append(InformationGap(
                        gap_type=InformationGapType.MACHINE_CAPACITY_COST,
                        action_type=action_type,
                        description=(
                            f"Purchase cost of a parallel machine at {station} "
                            f"is not recorded in the factory data."
                        ),
                        expected_category=CostCategory.CAPEX,
                    ))
                continue

            rule = _ACTION_COST_RULES.get(action_type)
            if rule is None:
                continue  # pragma: no cover - every current action type is covered

            category, gap_type, what = rule
            user_value = supplied.get(gap_type)

            components.append(CostComponent(
                # The lever named, not its scenario identifier: this label is
                # API output and reaches a reader unchanged.
                label=f"{what.capitalize()} ({action_phrase(action_type)})",
                category=user_value.category if user_value is not None else category,
                amount=user_value.amount if user_value is not None else None,
                source="USER" if user_value is not None else "CATALOG",
            ))

            if user_value is None and gap_type not in seen_gap_types:
                seen_gap_types.add(gap_type)
                gaps.append(InformationGap(
                    gap_type=gap_type,
                    action_type=action_type,
                    description=(
                        f"The {what} is not known. Supply it to compare this option financially "
                        f"against options whose cost is already established."
                    ),
                    expected_category=category,
                ))

    return StrategyCostProfile(
        known_capex=round(known_capex, 6),
        components=components,
        information_gaps=gaps,
    )
