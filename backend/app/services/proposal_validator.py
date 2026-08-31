"""Planning proposal validation for Fabrivium Phase 5B."""

from __future__ import annotations

from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.planning_agent import PlanningProposal
from app.services.candidate_generator import _expand_forbidden_machine_ids


def validate_planning_proposal(
    proposal: PlanningProposal,
    requirements: PlanningRequirements,
    factory: Factory,
) -> list[str]:
    """Validate *proposal* against *requirements* and *factory*."""
    reasons: list[str] = []

    machine_ids = {m.id for m in factory.machines}
    product_ids = {p.id for p in factory.products}

    action_machine_ids: set[str] = set()
    for action in proposal.scenario.actions:
        machine_id = getattr(action, "machine_id", None)
        if machine_id is not None:
            action_machine_ids.add(machine_id)
            if machine_id not in machine_ids:
                reasons.append(f"Action references unknown machine_id '{machine_id}'.")

        product_id = getattr(action, "product_id", None)
        if product_id is not None and product_id not in product_ids:
            reasons.append(f"Action references unknown product_id '{product_id}'.")

    forbidden = _expand_forbidden_machine_ids(factory, requirements.forbidden_machine_ids)
    violating = sorted(action_machine_ids & forbidden)
    if violating:
        reasons.append(f"Scenario targets forbidden machine(s): {violating}.")

    if requirements.allowed_action_types is not None:
        disallowed = sorted({
            a.action_type for a in proposal.scenario.actions
            if a.action_type not in requirements.allowed_action_types
        })
        if disallowed:
            reasons.append(f"Scenario uses disallowed action type(s): {disallowed}.")

    new_machine_count = sum(1 for a in proposal.scenario.actions if a.action_type == "ADD_PARALLEL_MACHINE")
    if requirements.max_additional_machines is not None and new_machine_count > requirements.max_additional_machines:
        reasons.append(
            f"Scenario adds {new_machine_count} machine(s), exceeding "
            f"max_additional_machines={requirements.max_additional_machines}."
        )

    return reasons
