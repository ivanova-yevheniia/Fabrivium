"""
Deterministic application of a ``RequirementUpdate`` (Fabrivium Phase 7C section 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.agent import PlanningRequirements
from app.models.conversation import RESETTABLE_FIELDS, RequirementUpdate
from app.models.factory import Factory
from app.services.requirements_parser import USER_REQUEST_NOTE_PREFIX, detect_contradictions

#: Value each resettable field returns to when explicitly cleared — the
#: same default ``PlanningRequirements`` declares, so "reset" and "never
#: set" are indistinguishable states rather than two subtly different ones.
_RESET_VALUES: dict[str, object] = {
    "target_units_per_day": None,
    "max_capex": None,
    "max_additional_machines": None,
    "max_additional_operators": None,
    "max_floor_area": None,
    "allowed_action_types": None,
    "forbidden_machine_ids": [],
    "preserve_existing_layout": False,
}


@dataclass(frozen=True)
class UpdateApplication:
    """Result of applying one update."""

    requirements: PlanningRequirements
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


# Machine reference resolution


def resolve_machine_reference(factory: Factory, reference: str) -> list[str]:
    """
    Resolve a user/model-supplied machine *reference* to real machine ids in *factory*.
    """
    needle = reference.strip().lower()
    if not needle:
        return []

    exact = [m.id for m in factory.machines if m.id.lower() == needle]
    if exact:
        return sorted(exact)

    by_name = [m.id for m in factory.machines if m.name.lower() == needle]
    if by_name:
        return sorted(by_name)

    fuzzy = [
        m.id for m in factory.machines
        if needle in m.name.lower() or needle in m.process_type.lower() or needle in m.id.lower()
    ]
    return sorted(fuzzy)


# Change rendering (deterministic — never model prose)


def _fmt_money(value: float | None) -> str:
    return "unlimited" if value is None else f"EUR {value:,.0f}"


def _fmt_units(value: float | None) -> str:
    return "unset" if value is None else f"{value:,.0f}/day"


def _fmt_list(values: list[str] | None) -> str:
    if values is None:
        return "unrestricted"
    return ", ".join(values) if values else "none"


def describe_changes(before: PlanningRequirements, after: PlanningRequirements) -> list[str]:
    """Render a human-readable diff from the TYPED values themselves."""
    changes: list[str] = []

    if before.objective != after.objective:
        changes.append(f"Objective: {before.objective.value} -> {after.objective.value}")
    if before.target_units_per_day != after.target_units_per_day:
        changes.append(f"Target: {_fmt_units(before.target_units_per_day)} -> {_fmt_units(after.target_units_per_day)}")
    if before.max_capex != after.max_capex:
        changes.append(f"Max CAPEX: {_fmt_money(before.max_capex)} -> {_fmt_money(after.max_capex)}")
    if before.max_additional_machines != after.max_additional_machines:
        changes.append(
            f"Max additional machines: {before.max_additional_machines if before.max_additional_machines is not None else 'unlimited'}"
            f" -> {after.max_additional_machines if after.max_additional_machines is not None else 'unlimited'}"
        )
    if before.max_additional_operators != after.max_additional_operators:
        changes.append(
            f"Max additional operators: {before.max_additional_operators if before.max_additional_operators is not None else 'unlimited'}"
            f" -> {after.max_additional_operators if after.max_additional_operators is not None else 'unlimited'}"
        )
    if before.max_floor_area != after.max_floor_area:
        changes.append(
            f"Max floor area: {before.max_floor_area if before.max_floor_area is not None else 'unlimited'}"
            f" -> {after.max_floor_area if after.max_floor_area is not None else 'unlimited'}"
        )
    if before.allowed_action_types != after.allowed_action_types:
        changes.append(f"Allowed actions: {_fmt_list(before.allowed_action_types)} -> {_fmt_list(after.allowed_action_types)}")

    added = [m for m in after.forbidden_machine_ids if m not in before.forbidden_machine_ids]
    removed = [m for m in before.forbidden_machine_ids if m not in after.forbidden_machine_ids]
    for machine_id in added:
        changes.append(f"Locked: {machine_id} may not be modified")
    for machine_id in removed:
        changes.append(f"Unlocked: {machine_id} may be modified again")

    if before.preserve_existing_layout != after.preserve_existing_layout:
        changes.append(
            "Preserve existing layout: on" if after.preserve_existing_layout else "Preserve existing layout: off"
        )

    before_requests = {n for n in before.notes if n.startswith(USER_REQUEST_NOTE_PREFIX)}
    for note in after.notes:
        if note.startswith(USER_REQUEST_NOTE_PREFIX) and note not in before_requests:
            changes.append(f"Requested intervention: {note[len(USER_REQUEST_NOTE_PREFIX):].rstrip('.')}")

    return changes


# The merge


def apply_requirement_update(
    current: PlanningRequirements,
    update: RequirementUpdate,
    factory: Factory,
) -> UpdateApplication:
    """
    Merge *update* into *current*, returning a NEW ``PlanningRequirements`` plus a full
    account of what happened.
    """
    warnings: list[str] = []
    rejected: list[str] = []
    updates: dict[str, object] = {}

    # 1. explicit resets
    for name in update.reset_constraints:
        key = name.strip()
        if key not in RESETTABLE_FIELDS:
            warnings.append(
                f"Ignored request to reset unknown constraint '{name}' "
                f"(resettable: {', '.join(sorted(RESETTABLE_FIELDS))})."
            )
            continue
        updates[key] = _RESET_VALUES[key]

    # 2. explicit scalar values (win over a reset of the same field)
    for name in (
        "objective",
        "target_units_per_day",
        "max_capex",
        "max_additional_machines",
        "max_additional_operators",
        "max_floor_area",
        "allowed_action_types",
        "preserve_existing_layout",
    ):
        value = getattr(update, name)
        if value is not None:
            updates[name] = value

    # 3. forbidden-machine set
    forbidden = list(updates.get("forbidden_machine_ids", current.forbidden_machine_ids))  # type: ignore[arg-type]

    for reference in update.forbidden_machine_ids_remove:
        matches = resolve_machine_reference(factory, reference)
        if not matches:
            warnings.append(f"Cannot unlock '{reference}': no such machine in this factory.")
            continue
        present = [m for m in matches if m in forbidden]
        if not present:
            warnings.append(f"'{reference}' was not locked, so there was nothing to unlock.")
            continue
        forbidden = [m for m in forbidden if m not in present]

    for reference in update.forbidden_machine_ids_add:
        matches = resolve_machine_reference(factory, reference)
        if not matches:
            # A grounding failure, not a warning: silently dropping a
            # requested lock would let planning modify a machine the user
            # explicitly protected.
            rejected.append(f"Cannot lock '{reference}': no such machine in this factory.")
            continue
        for machine_id in matches:
            if machine_id not in forbidden:
                forbidden.append(machine_id)

    if forbidden != list(current.forbidden_machine_ids) or "forbidden_machine_ids" in updates:
        updates["forbidden_machine_ids"] = sorted(set(forbidden))

    # 4. explicit intervention -> the existing note mechanism
    notes = list(current.notes)
    if update.explicit_intervention:
        matches = resolve_machine_reference(factory, update.explicit_intervention)
        if not matches:
            rejected.append(
                f"Cannot honour the requested intervention at '{update.explicit_intervention}': no such machine."
            )
        else:
            # Reuses Phase 5B's existing user-request channel verbatim
            # rather than inventing a parallel one: the planning agent
            # already treats a note with this prefix as an explicitly
            # user-requested (and therefore grounded) intervention.
            for machine_id in matches:
                note = f"{USER_REQUEST_NOTE_PREFIX}{machine_id}."
                if note not in notes:
                    notes.append(note)
            updates["notes"] = notes

    if not updates:
        return UpdateApplication(requirements=current, changes=[], warnings=warnings, rejected=rejected)

    merged = current.model_copy(update=updates)

    # 5. contradictions over the FINAL state
    contradictions = detect_contradictions(merged)
    if contradictions:
        warnings.extend(contradictions)
        merged = merged.model_copy(update={"parse_warnings": [*merged.parse_warnings, *contradictions]})

    return UpdateApplication(
        requirements=merged,
        changes=describe_changes(current, merged),
        warnings=warnings,
        rejected=rejected,
    )
