"""What changed in a project, which channel it belongs to, and what that invalidates."""

from __future__ import annotations

from typing import Any

from app.models.concept import FactoryConceptDraft
from app.models.project import (
    ARTIFACT_ACTION,
    ARTIFACT_CHANNELS,
    ARTIFACT_LABEL,
    ARTIFACT_PARENTS,
    Artifact,
    ArtifactStatus,
    Channel,
    ChangeEntry,
    ProjectState,
    Stamp,
    StaleArtifact,
    StaleReport,
)
from app.services.change_impact import diff_inputs
from app.services.input_resolution import Necessity, resolution_plan

# How many change entries a project keeps.
HISTORY_LIMIT = 200


# Channel content

def _concept(state: ProjectState) -> FactoryConceptDraft | None:
    """The concept draft as a model, or None when it is absent or unreadable."""
    raw = state.concept.draft
    if not raw:
        return None
    try:
        return FactoryConceptDraft.model_validate(raw)
    except Exception:  # noqa: BLE001 - an unreadable draft is simply absent
        return None


def _facts_content(state: ProjectState) -> Any:
    understanding = state.product.understanding
    if not understanding:
        return None
    facts = understanding.get("facts") or []
    return [
        (
            fact.get("key"),
            fact.get("value"),
            fact.get("quantity"),
            fact.get("unit"),
            fact.get("status"),
        )
        for fact in facts
    ]


def _process_content(state: ProjectState) -> Any:
    """The route: which operations, in what order, and what each one is."""
    draft = state.process.draft
    if not draft:
        return None
    return [
        (
            op.get("id"),
            op.get("name"),
            op.get("description"),
            op.get("process_type"),
            op.get("repeated_operations"),
            op.get("status"),
        )
        for op in (draft.get("operations") or [])
    ]


def _coverage_links_content(state: ProjectState) -> Any:
    draft = state.process.draft
    if not draft:
        return None
    return {
        op.get("id"): sorted(op.get("source_fact_keys") or [])
        for op in (draft.get("operations") or [])
    }


def _classify(key: str, plan_index: dict[str, Necessity]) -> Channel:
    """Which channel a changed concept input belongs to."""
    necessity = plan_index.get(key)
    if necessity is Necessity.COMMERCIAL_ONLY:
        return Channel.COMMERCIAL
    if necessity is Necessity.AFFECTS_LAYOUT:
        return Channel.LAYOUT
    # BLOCKS_SIMULATION and HAS_DEFAULT alike are read by the simulator:
    # a capacity that falls back to its default still reaches the model.
    return Channel.SIMULATION_INPUTS


def _concept_channel_content(draft: FactoryConceptDraft | None, channel: Channel) -> Any:
    """The part of a concept draft one channel owns."""
    if draft is None:
        return None
    plan = resolution_plan(draft)
    index = {item.key: item.necessity for item in plan.inputs}
    return sorted(
        (item.key, item.value, item.source.value)
        for item in plan.inputs
        if _classify(item.key, index) is channel
    )


def _placements(layout: dict[str, Any] | None) -> list[tuple]:
    """One layout's placements, rounded and ordered."""
    return sorted(
        (
            p.get("machine_id"),
            round(float(p.get("x") or 0.0), 3),
            round(float(p.get("y") or 0.0), 3),
            round(float(p.get("rotation_deg") or 0.0), 3),
        )
        for p in ((layout or {}).get("placements") or [])
    )


def _layout_content(state: ProjectState) -> Any:
    """Placement, as applied."""
    applied = state.layout.applied or {}
    out = {stage_key: _placements(layout) for stage_key, layout in applied.items()}
    return out or None


def _equipment_content(state: ProjectState) -> Any:
    selections = state.equipment.selections or {}
    return {
        station: (
            (sel or {}).get("candidate_id"),
            (sel or {}).get("manufacturer"),
            (sel or {}).get("model"),
        )
        for station, sel in selections.items()
    } or None


def _established_costs_content(state: ProjectState) -> Any:
    """Costs the engineer stated, in comparable form (G13)."""
    costs = state.commercial.established_costs or []
    return sorted(
        (
            str(c.get("gap_type")),
            round(float(c.get("amount") or 0.0), 6),
            str(c.get("category")),
        )
        for c in costs
    ) or None


def _grouping_content(draft: FactoryConceptDraft | None) -> Any:
    """The production architecture: which stages share one resource."""
    if draft is None or not draft.operation_groups:
        return None
    return sorted(
        (group.id, group.name, group.execution_mode.value, tuple(group.stage_ids))
        for group in draft.operation_groups
    )


def channel_content(state: ProjectState) -> dict[Channel, Any]:
    """Everything each channel currently holds, in comparable form."""
    draft = _concept(state)
    return {
        Channel.PRODUCT_SOURCE: state.product.description,
        Channel.PRODUCT_FACTS: _facts_content(state),
        Channel.PROCESS: _process_content(state),
        Channel.COVERAGE_LINKS: _coverage_links_content(state),
        Channel.SIMULATION_INPUTS: (
            _concept_channel_content(draft, Channel.SIMULATION_INPUTS),
            state.requirements.text,
            _grouping_content(draft),
        ),
        Channel.COMMERCIAL: (
            _concept_channel_content(draft, Channel.COMMERCIAL),
            _established_costs_content(state),
        ),
        Channel.LAYOUT: (
            _concept_channel_content(draft, Channel.LAYOUT),
            _layout_content(state),
        ),
        Channel.EQUIPMENT: _equipment_content(state),
    }


# Describing a change

def _describe_product_source(before: ProjectState, after: ProjectState) -> list[str]:
    """What changed about the SOURCE — never about what it is called."""
    lines: list[str] = []
    if before.product.description != after.product.description:
        if not before.product.description:
            lines.append("A product specification was supplied.")
        else:
            lines.append("Product specification changed.")
    return lines


def _describe_process(before: ProjectState, after: ProjectState) -> list[str]:
    old_ops = {op.get("id"): op for op in ((before.process.draft or {}).get("operations") or [])}
    new_ops = {op.get("id"): op for op in ((after.process.draft or {}).get("operations") or [])}
    old_order = [op.get("id") for op in ((before.process.draft or {}).get("operations") or [])]
    new_order = [op.get("id") for op in ((after.process.draft or {}).get("operations") or [])]

    lines: list[str] = []

    for op_id, op in new_ops.items():
        if op_id not in old_ops:
            lines.append(f"Operation added: {op.get('name')}.")
            continue
        old = old_ops[op_id]
        if old.get("status") != op.get("status"):
            was, now = old.get("status"), op.get("status")
            if now == "REJECTED":
                lines.append(f"Operation rejected: {op.get('name')}.")
            elif was == "REJECTED":
                lines.append(f"Operation restored: {op.get('name')}.")
            else:
                lines.append(f"Operation {op.get('name')}: {was} → {now}.")
        if old.get("name") != op.get("name"):
            lines.append(f"Operation renamed: “{old.get('name')}” → “{op.get('name')}”.")
        if old.get("description") != op.get("description"):
            lines.append(f"Operation description changed: {op.get('name')}.")
        if old.get("repeated_operations") != op.get("repeated_operations"):
            lines.append(
                f"Repeated operations per unit for {op.get('name')}: "
                f"{old.get('repeated_operations') or 'unspecified'} → "
                f"{op.get('repeated_operations') or 'unspecified'}."
            )

    for op_id, op in old_ops.items():
        if op_id not in new_ops:
            lines.append(f"Operation removed: {op.get('name')}.")

    # Order is compared over the ids the two versions share, so an addition
    # or a removal is not also reported as a reorder.
    shared_old = [i for i in old_order if i in new_ops]
    shared_new = [i for i in new_order if i in old_ops]
    if shared_old != shared_new:
        lines.append("Operation order changed.")

    return lines or ["The manufacturing process changed."]


def _describe_concept_inputs(
    before: ProjectState, after: ProjectState
) -> dict[Channel, list[str]]:
    """Per-channel descriptions of every changed concept value."""
    old, new = _concept(before), _concept(after)
    out: dict[Channel, list[str]] = {}
    if old is None or new is None:
        return out

    index = {item.key: item.necessity for item in resolution_plan(new).inputs}
    for change in diff_inputs(old, new):
        channel = _classify(change.key, index)
        out.setdefault(channel, []).append(change.describe())
    return out


def _describe_layout(before: ProjectState, after: ProjectState) -> list[str]:
    """How many stations actually moved, and the reassurance that goes with it."""
    old = _layout_content(before) or {}
    new = _layout_content(after) or {}
    generated = {p[0]: p[1:] for p in _placements(after.concept.layout)}

    moved = 0
    for stage_key, placements in new.items():
        previous = (
            {p[0]: p[1:] for p in old[stage_key]} if stage_key in old else dict(generated)
        )
        for placement in placements:
            if previous.get(placement[0]) != placement[1:]:
                moved += 1

    if moved:
        return [
            f"Station placement changed ({moved} station{'' if moved == 1 else 's'} moved). "
            "Placement is checked for validity, never for speed — throughput is unaffected."
        ]
    return ["The layout changed."]


def _describe_equipment(before: ProjectState, after: ProjectState) -> list[str]:
    old = before.equipment.selections or {}
    new = after.equipment.selections or {}
    lines: list[str] = []
    for station, selection in new.items():
        if old.get(station) != selection:
            model = (selection or {}).get("model") or "a candidate"
            lines.append(f"Equipment under consideration for {station}: {model}.")
    for station in old:
        if station not in new:
            lines.append(f"Equipment under consideration withdrawn for {station}.")
    return lines or ["Equipment selection changed."]


def describe_changes(before: ProjectState, after: ProjectState) -> list[tuple[Channel, str]]:
    """Every input change between two project states, attributed to a channel."""
    old_content = channel_content(before)
    new_content = channel_content(after)
    concept_lines = _describe_concept_inputs(before, after)

    changes: list[tuple[Channel, str]] = []
    for channel in Channel:
        if old_content.get(channel) == new_content.get(channel):
            continue

        if channel is Channel.PRODUCT_SOURCE:
            lines = _describe_product_source(before, after)
        elif channel is Channel.PRODUCT_FACTS:
            lines = ["The extracted product facts changed."]
        elif channel is Channel.PROCESS:
            lines = _describe_process(before, after)
        elif channel is Channel.COVERAGE_LINKS:
            lines = ["Requirement coverage links changed."]
        elif channel is Channel.LAYOUT:
            lines = concept_lines.get(channel, []) + _describe_layout(before, after)
        elif channel is Channel.EQUIPMENT:
            lines = _describe_equipment(before, after)
        else:
            lines = concept_lines.get(channel) or [
                f"{channel.value.replace('_', ' ').capitalize()} changed."
            ]

        changes.extend((channel, line) for line in lines if line)

    return changes


# Applying a save

def apply_revisions(previous: ProjectState | None, incoming: ProjectState) -> ProjectState:
    """Fold a client's new state into the project's revision bookkeeping."""
    base = previous or ProjectState()
    revisions = dict(base.revisions)
    for channel in Channel:
        revisions.setdefault(channel.value, 1)

    history = list(base.history)
    next_seq = (history[-1].seq + 1) if history else 1

    changes = describe_changes(base, incoming)
    bumped: set[str] = set()
    for channel, description in changes:
        if channel.value not in bumped:
            revisions[channel.value] = revisions.get(channel.value, 1) + 1
            bumped.add(channel.value)
        history.append(
            ChangeEntry(
                seq=next_seq,
                channel=channel.value,
                revision=revisions[channel.value],
                description=description,
            )
        )
        next_seq += 1

    evidence = {name: Stamp(revisions=dict(stamp.revisions)) for name, stamp in base.evidence.items()}
    for name in incoming.withdrawn:
        evidence.pop(name, None)
    # Stamped AFTER the diff, at the revisions the artifact was actually computed from.
    for name in incoming.produced:
        try:
            Artifact(name)
        except ValueError:
            continue
        evidence[name] = Stamp(revisions=dict(revisions))

    return incoming.model_copy(
        update={
            "revisions": revisions,
            "evidence": evidence,
            "history": history[-HISTORY_LIMIT:],
            "produced": [],
            "withdrawn": [],
        }
    )


# Reading staleness back out

def stale_report(state: ProjectState) -> StaleReport:
    """Which artifacts may still be shown as current, and why the rest may not."""
    revisions = state.revisions or {channel.value: 1 for channel in Channel}
    produced = {
        artifact: state.evidence[artifact.value]
        for artifact in Artifact
        if artifact.value in state.evidence
    }

    stale: dict[Artifact, StaleArtifact] = {}

    def changed_channels(artifact: Artifact) -> list[Channel]:
        stamp = produced[artifact]
        return [
            channel
            for channel in sorted(ARTIFACT_CHANNELS[artifact], key=lambda c: c.value)
            if revisions.get(channel.value, 1) > stamp.at(channel)
        ]

    # Direct channel movement first, then propagation through parents until
    # nothing new is added. The graph is a DAG of eleven nodes; a fixpoint
    for artifact in produced:
        moved = changed_channels(artifact)
        if moved:
            stamp = produced[artifact]
            moved_names = {c.value for c in moved}
            # Only the changes that landed AFTER this artifact was produced.
            reasons = [
                entry.description
                for entry in state.history
                if entry.channel in moved_names
                and entry.revision > stamp.at(Channel(entry.channel))
            ]
            stale[artifact] = StaleArtifact(
                artifact=artifact.value,
                status=ArtifactStatus.STALE.value,
                changed_channels=[c.value for c in moved],
                reasons=reasons[-6:],
                action=ARTIFACT_ACTION[artifact],
            )

    growing = True
    while growing:
        growing = False
        for artifact in produced:
            if artifact in stale:
                continue
            stale_parents = [
                parent.value for parent in ARTIFACT_PARENTS.get(artifact, ()) if parent in stale
            ]
            if stale_parents:
                stale[artifact] = StaleArtifact(
                    artifact=artifact.value,
                    status=ArtifactStatus.STALE.value,
                    stale_parents=stale_parents,
                    reasons=[
                        f"Built on {ARTIFACT_LABEL[Artifact(name)]}, which is out of date."
                        for name in stale_parents
                    ],
                    action=ARTIFACT_ACTION[artifact],
                )
                growing = True

    current = [a.value for a in produced if a not in stale]
    unverified = [a.value for a in Artifact if a not in produced]

    if not produced:
        summary = "Nothing has been verified yet."
    elif not stale:
        summary = "Every result on screen answers the current inputs."
    else:
        names = ", ".join(sorted(ARTIFACT_LABEL[a] for a in stale))
        summary = f"Inputs changed since this was verified. Now out of date: {names}."

    return StaleReport(
        stale=[stale[a] for a in sorted(stale, key=lambda a: a.value)],
        current=sorted(current),
        unverified=sorted(unverified),
        summary=summary,
    )
