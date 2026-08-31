"""Deterministic precedence for requirements accumulated across conversation turns."""

from __future__ import annotations

import re

from app.models.planning_agent import PlanningRequirements

#: Optional scalars where "the newest stated value wins" and ``None`` means
#: "this turn did not mention it".
_LAST_WINS_SCALARS = (
    "target_units_per_day",
    "max_capex",
    "max_additional_machines",
    "max_additional_operators",
    "max_floor_area",
)

#: Soft preferences — accumulate, then let rule 5 drop any that a hard
#: constraint has superseded.
_ACCUMULATING_FLAGS = (
    "prefer_no_new_machines",
    "prefer_low_known_capex",
    "prefer_few_changes",
    "preserve_existing_layout",
)

# An explicit release of the equipment ban.
_ALLOW_NEW_MACHINES_RE = re.compile(
    r"\b(?:new|additional|more|another|extra)\s+(?:machines?|equipment)\b[^.]{0,20}\b"
    r"(?:are|is)\s+(?:ok|okay|fine|allowed|acceptable|permitted)\b"
    r"|\b(?:you\s+)?(?:can|may|could)\s+(?:now\s+)?(?:buy|add|purchase)\b[^.]{0,25}\bmachines?\b"
    r"|\b(?:allow|permit)\s+(?:buying|adding|purchasing|new)\b[^.]{0,20}\bmachines?\b"
    r"|\b(?:lift|remove|drop|forget)\s+(?:the\s+)?(?:machine|equipment)\s+(?:ban|restriction|limit)\b",
    re.IGNORECASE,
)


def relaxes_equipment_ban(text: str) -> bool:
    """Whether *text* explicitly permits buying machines again."""
    return bool(_ALLOW_NEW_MACHINES_RE.search(text))


def merge_requirements_sequence(
    parsed: list[PlanningRequirements],
    texts: list[str] | None = None,
) -> PlanningRequirements:
    """Fold requirements parsed from consecutive turns, oldest first."""
    if not parsed:
        raise ValueError("merge_requirements_sequence needs at least one parsed requirement.")

    turn_texts = list(texts or [])
    merged = parsed[0]

    for index, incoming in enumerate(parsed[1:], start=1):
        updates: dict[str, object] = {}

        # 1. newest stated scalar wins; silence carries the old value.
        for field in _LAST_WINS_SCALARS:
            value = getattr(incoming, field)
            if value is not None:
                updates[field] = value

        # An objective is always populated (it defaults), so it can only be
        # taken from a turn that actually recognised one — otherwise every
        # follow-up would reset the goal to the default.
        if incoming.confidence >= 1.0 and incoming.objective != merged.objective:
            updates["objective"] = incoming.objective

        # 2. hard restrictions: newest wins; explicit relaxation clears.
        turn_text = turn_texts[index] if index < len(turn_texts) else ""
        if incoming.allowed_action_types is not None:
            updates["allowed_action_types"] = list(incoming.allowed_action_types)
        elif turn_text and relaxes_equipment_ban(turn_text):
            updates["allowed_action_types"] = None

        # 3/4. preferences, layout locks and machine locks accumulate.
        for flag in _ACCUMULATING_FLAGS:
            if getattr(incoming, flag):
                updates[flag] = True
        if incoming.forbidden_machine_ids:
            updates["forbidden_machine_ids"] = sorted(
                set(merged.forbidden_machine_ids) | set(incoming.forbidden_machine_ids)
            )

        notes = list(merged.notes)
        for note in incoming.notes:
            if note not in notes:
                notes.append(note)
        updates["notes"] = notes
        updates["confidence"] = min(merged.confidence, incoming.confidence)

        warnings = list(merged.parse_warnings)
        for warning in incoming.parse_warnings:
            if warning not in warnings:
                warnings.append(warning)
        updates["parse_warnings"] = warnings

        merged = merged.model_copy(update=updates)

    # 5. hard supersedes soft, over the FINAL merged state.
    allowed = merged.allowed_action_types
    if allowed is not None and not any(a.startswith("ADD_") for a in allowed) and merged.prefer_no_new_machines:
        merged = merged.model_copy(update={"prefer_no_new_machines": False})

    return merged
