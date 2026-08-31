"""Change impact — what a changed input invalidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.concept import FactoryConceptDraft
from app.services.input_resolution import read_input, resolution_plan


class ResultNode(str, Enum):
    """A derived thing Fabrivium computes and shows."""

    # Concept converted to a runnable Factory.
    SIMULATION_CONFIG = "SIMULATION_CONFIG"
    # The as-is run: throughput, gap, utilisation.
    BASELINE_RESULT = "BASELINE_RESULT"
    # Which stage limits the line.
    BOTTLENECK = "BOTTLENECK"
    # The candidate plans generated for this goal.
    STRATEGIES = "STRATEGIES"
    # Their simulated outcomes and ranking.
    STRATEGY_EVALUATION = "STRATEGY_EVALUATION"
    # The plan put forward.
    RECOMMENDATION = "RECOMMENDATION"
    # Station placement and its validity.
    LAYOUT = "LAYOUT"
    # Threshold and sweep answers for one station.
    SENSITIVITY = "SENSITIVITY"
    # The requirement a station must meet, used for equipment search.
    STATION_REQUIREMENT = "STATION_REQUIREMENT"
    # The exported Plant Simulation model.
    SIEMENS_HANDOFF = "SIEMENS_HANDOFF"


# What each result reads.
STAGE_FIELD = "stage.*"          # any per-stage value
BUFFER_FIELD = "buffer.*"        # any buffer size

_DIRECT_DEPENDENCIES: dict[ResultNode, frozenset[str]] = {
    ResultNode.SIMULATION_CONFIG: frozenset(
        {
            "production_target",
            "shifts_per_day",
            "hours_per_shift",
            "operators_available",
            STAGE_FIELD,
            BUFFER_FIELD,
        }
    ),
    ResultNode.LAYOUT: frozenset({"floor_width", "floor_length", STAGE_FIELD}),
    ResultNode.SENSITIVITY: frozenset(
        {"production_target", "shifts_per_day", "hours_per_shift", STAGE_FIELD, BUFFER_FIELD}
    ),
    ResultNode.STATION_REQUIREMENT: frozenset(
        {"production_target", "shifts_per_day", "hours_per_shift", STAGE_FIELD, "budget"}
    ),
}

# Results that depend on other RESULTS rather than directly on inputs.
_DERIVED_FROM: dict[ResultNode, tuple[ResultNode, ...]] = {
    ResultNode.BASELINE_RESULT: (ResultNode.SIMULATION_CONFIG,),
    ResultNode.BOTTLENECK: (ResultNode.BASELINE_RESULT,),
    ResultNode.STRATEGIES: (ResultNode.BOTTLENECK,),
    ResultNode.STRATEGY_EVALUATION: (ResultNode.STRATEGIES,),
    ResultNode.RECOMMENDATION: (ResultNode.STRATEGY_EVALUATION,),
    ResultNode.SIEMENS_HANDOFF: (ResultNode.SIMULATION_CONFIG, ResultNode.LAYOUT),
}

#: Money changes what a plan COSTS and therefore how plans rank, without
#: changing a single unit of throughput. Kept apart so a price edit does not
#: invalidate the physics.
_COMMERCIAL_KEYS = frozenset({"budget"})
_COMMERCIAL_FIELD = "stage.*.purchase_cost"


class ChangeKind(str, Enum):
    RESOLVED = "RESOLVED"        # was unknown, now has a value
    CLEARED = "CLEARED"          # had a value, now unknown
    VALUE_CHANGED = "VALUE_CHANGED"
    SOURCE_CHANGED = "SOURCE_CHANGED"  # same number, stronger or weaker provenance
    ADDED = "ADDED"              # the input did not exist before
    REMOVED = "REMOVED"


@dataclass(frozen=True)
class InputChange:
    """One input that is not what it was."""

    key: str
    label: str
    kind: ChangeKind
    before: float | None
    after: float | None
    before_source: str | None
    after_source: str | None

    def describe(self) -> str:
        def show(value: float | None) -> str:
            return "unknown" if value is None else f"{value:g}"

        if self.kind is ChangeKind.SOURCE_CHANGED:
            return (
                f"{self.label}: {show(self.after)} — provenance changed from "
                f"{self.before_source} to {self.after_source}"
            )
        return f"{self.label}: {show(self.before)} → {show(self.after)}"


@dataclass(frozen=True)
class ImpactReport:
    """What changed, and what may no longer be shown as current."""

    changes: list[InputChange] = field(default_factory=list)
    stale: set[ResultNode] = field(default_factory=set)
    unaffected: set[ResultNode] = field(default_factory=set)

    @property
    def anything_changed(self) -> bool:
        return bool(self.changes)

    def summary(self) -> str:
        if not self.changes:
            return "Nothing changed."
        if not self.stale:
            return (
                f"{len(self.changes)} input(s) changed. No computed result depends on them, "
                f"so nothing needs recomputing."
            )
        names = ", ".join(sorted(node.value.replace("_", " ").lower() for node in self.stale))
        return f"{len(self.changes)} input(s) changed. Now out of date: {names}."


def _matches(key: str, dependency: str) -> bool:
    """Does an input key satisfy a dependency entry?"""
    if dependency == key:
        return True
    if dependency == STAGE_FIELD:
        return key.startswith("stage.")
    if dependency == BUFFER_FIELD:
        return key.startswith("buffer.")
    return False


def _is_commercial(key: str) -> bool:
    return key in _COMMERCIAL_KEYS or (key.startswith("stage.") and key.endswith(".purchase_cost"))


def diff_inputs(before: FactoryConceptDraft, after: FactoryConceptDraft) -> list[InputChange]:
    """Every input that differs between two versions of a concept."""
    before_map = {i.key: i for i in resolution_plan(before).inputs}
    after_map = {i.key: i for i in resolution_plan(after).inputs}

    changes: list[InputChange] = []

    for key, new in after_map.items():
        old = before_map.get(key)
        if old is None:
            changes.append(
                InputChange(
                    key=key,
                    label=new.label,
                    kind=ChangeKind.ADDED,
                    before=None,
                    after=new.value,
                    before_source=None,
                    after_source=new.source.value,
                )
            )
            continue

        if old.value == new.value and old.source is new.source:
            continue

        if old.value == new.value:
            kind = ChangeKind.SOURCE_CHANGED
        elif old.value is None:
            kind = ChangeKind.RESOLVED
        elif new.value is None:
            kind = ChangeKind.CLEARED
        else:
            kind = ChangeKind.VALUE_CHANGED

        changes.append(
            InputChange(
                key=key,
                label=new.label,
                kind=kind,
                before=old.value,
                after=new.value,
                before_source=old.source.value,
                after_source=new.source.value,
            )
        )

    for key, old in before_map.items():
        if key not in after_map:
            changes.append(
                InputChange(
                    key=key,
                    label=old.label,
                    kind=ChangeKind.REMOVED,
                    before=old.value,
                    after=None,
                    before_source=old.source.value,
                    after_source=None,
                )
            )

    return sorted(changes, key=lambda c: c.key)


def stale_results(changed_keys: set[str]) -> set[ResultNode]:
    """Which results a set of changed inputs invalidates, transitively."""
    stale: set[ResultNode] = set()

    physical = {k for k in changed_keys if not _is_commercial(k)}
    commercial = {k for k in changed_keys if _is_commercial(k)}

    for node, dependencies in _DIRECT_DEPENDENCIES.items():
        if any(_matches(key, dep) for key in physical for dep in dependencies):
            stale.add(node)

    # Propagate downstream until nothing new is added.
    changed = True
    while changed:
        changed = False
        for node, upstream in _DERIVED_FROM.items():
            if node not in stale and any(parent in stale for parent in upstream):
                stale.add(node)
                changed = True

    # A price or a budget re-ranks plans without moving a single unit.
    if commercial:
        for node in (ResultNode.STRATEGY_EVALUATION, ResultNode.RECOMMENDATION):
            stale.add(node)

    return stale


def assess(before: FactoryConceptDraft, after: FactoryConceptDraft) -> ImpactReport:
    """Compare two versions of a concept and report what is now out of date."""
    changes = diff_inputs(before, after)
    stale = stale_results({c.key for c in changes})
    return ImpactReport(
        changes=changes,
        stale=stale,
        unaffected=set(ResultNode) - stale,
    )


def explain(before: FactoryConceptDraft, after: FactoryConceptDraft) -> str:
    """A short account of the change, built from the diff rather than prose."""
    report = assess(before, after)
    if not report.anything_changed:
        return "Nothing changed."

    lines = [report.summary(), ""]
    lines.append("Changed:")
    lines.extend(f"  {change.describe()}" for change in report.changes)

    if report.stale:
        lines.append("")
        lines.append("Must be recomputed before it can be shown as current:")
        lines.extend(
            f"  {node.value.replace('_', ' ').lower()}" for node in sorted(report.stale, key=lambda n: n.value)
        )

    if report.unaffected:
        lines.append("")
        lines.append("Unaffected:")
        lines.extend(
            f"  {node.value.replace('_', ' ').lower()}"
            for node in sorted(report.unaffected, key=lambda n: n.value)
        )

    return "\n".join(lines)
