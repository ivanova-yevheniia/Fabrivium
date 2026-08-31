"""Requirement coverage — did the proposed process answer the document?"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models.process_draft import ManufacturingProcessDraft
from app.models.product import EvidenceRef, ProductFact, ProductUnderstanding


class CoverageStatus(str, Enum):
    # A proposed operation cites this fact as its reason for existing.
    ADDRESSED = "ADDRESSED"
    # The fact is a manufacturing requirement and nothing answers it.
    UNRESOLVED = "UNRESOLVED"
    #: The fact describes the product but implies no operation by itself
    #: (a material, a dimension). Not a gap — it has no action to omit.
    NOT_A_REQUIREMENT = "NOT_A_REQUIREMENT"


class CoverageSeverity(str, Enum):
    # An explicit "shall" in the source.
    CRITICAL = "CRITICAL"
    # Implied work that a reasonable process would include.
    EXPECTED = "EXPECTED"
    # Worth noting; not a conformance issue.
    INFORMATIONAL = "INFORMATIONAL"


# Fact key prefixes that describe MANUFACTURING WORK — something has to happen on the
# line for the finished product to satisfy them.
_REQUIREMENT_PREFIXES: tuple[str, ...] = ("component.", "fastener.", "connection.", "requirement.")

# Requirements the source states with "shall".
_CRITICAL_PREFIXES: tuple[str, ...] = ("requirement.", "component.")


@dataclass(frozen=True)
class RequirementCoverage:
    """One source requirement and what the process did about it."""

    fact_key: str
    label: str
    value: str | None
    status: CoverageStatus
    severity: CoverageSeverity
    # Operations citing this fact. Empty when UNRESOLVED.
    addressed_by: list[str] = field(default_factory=list)
    #: The source sentence, carried through so "why is this a requirement?"
    #: is answerable without going back to the document.
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(frozen=True)
class CoverageReport:
    """What the proposed process covers, and what it leaves open."""

    items: list[RequirementCoverage] = field(default_factory=list)

    @property
    def addressed(self) -> list[RequirementCoverage]:
        return [i for i in self.items if i.status is CoverageStatus.ADDRESSED]

    @property
    def unresolved(self) -> list[RequirementCoverage]:
        return [i for i in self.items if i.status is CoverageStatus.UNRESOLVED]

    @property
    def critical_unresolved(self) -> list[RequirementCoverage]:
        return [i for i in self.unresolved if i.severity is CoverageSeverity.CRITICAL]

    @property
    def complete(self) -> bool:
        """True only when nothing EXTRACTED from the source is left unanswered."""
        return not self.unresolved

    @property
    def approval_blocked(self) -> bool:
        """A CRITICAL requirement with no operation blocks approval."""
        return bool(self.critical_unresolved)

    def summary(self) -> str:
        """The coverage sentence, stated at exactly the strength of the evidence."""
        total = len(self.addressed) + len(self.unresolved)
        if not total:
            return "No manufacturing requirements were extracted from the source."
        if self.complete:
            plural = "" if total == 1 else "s"
            return f"All {total} extracted manufacturing requirement{plural} are addressed."
        unresolved = len(self.unresolved)
        critical = len(self.critical_unresolved)
        text = (
            f"{len(self.addressed)} of {total} extracted manufacturing requirements are "
            f"addressed; {unresolved} unresolved"
        )
        if critical:
            text += f", {critical} of them stated explicitly by the source"
        return text + "."


def _is_requirement(fact: ProductFact) -> bool:
    return fact.key.startswith(_REQUIREMENT_PREFIXES)


def _severity(fact: ProductFact) -> CoverageSeverity:
    if fact.key.startswith(_CRITICAL_PREFIXES):
        return CoverageSeverity.CRITICAL
    return CoverageSeverity.EXPECTED


def coverage_for(
    understanding: ProductUnderstanding, draft: ManufacturingProcessDraft
) -> CoverageReport:
    """Match every manufacturing requirement in the source to an operation."""
    by_fact: dict[str, list[str]] = {}
    for operation in draft.operations:
        for key in operation.source_fact_keys:
            by_fact.setdefault(key, []).append(operation.name)

    items: list[RequirementCoverage] = []
    for fact in understanding.facts:
        if not _is_requirement(fact):
            items.append(
                RequirementCoverage(
                    fact_key=fact.key,
                    label=fact.label,
                    value=fact.value,
                    status=CoverageStatus.NOT_A_REQUIREMENT,
                    severity=CoverageSeverity.INFORMATIONAL,
                    evidence=list(fact.evidence),
                )
            )
            continue

        operations = by_fact.get(fact.key, [])
        items.append(
            RequirementCoverage(
                fact_key=fact.key,
                label=fact.label,
                value=fact.value,
                status=CoverageStatus.ADDRESSED if operations else CoverageStatus.UNRESOLVED,
                severity=_severity(fact),
                addressed_by=operations,
                evidence=list(fact.evidence),
            )
        )

    return CoverageReport(items=items)
