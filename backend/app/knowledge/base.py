"""
The Engineering Knowledge Base 
An in-memory index over knowledge items that adapters derived from
Fabrivium's canonical sources. It answers "what does this system know, where
did it come from, and what are its limits?" without running anything.

Every query returns items in one stable order — category, then kind, then
id, then version — regardless of registration order. Query results are what
a report cites, and a report whose lines reshuffle between runs cannot be
diffed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Iterator

from app.knowledge.contract import (
    EngineeringKnowledgeItem,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeExposure,
    KnowledgeKind,
    SourceKind,
)
from app.knowledge.standards import StandardReference


class KnowledgeItemNotFound(KeyError):
    """No item matches the request."""


class KnowledgeRegistrationError(ValueError):
    """A set of items could not form a knowledge base."""


def _version_key(version: str) -> tuple[int, ...]:
    """Sort key for a dotted version.

    Same treatment as ``app.skills.registry._version_key``: non-numeric
    parts sort as 0 rather than raising. 
    """
    parts: list[int] = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _order(item: EngineeringKnowledgeItem) -> tuple:
    return (item.category.value, item.kind.value, item.id, _version_key(item.version))


@dataclass(frozen=True)
class CategorySummary:
    """One line of the architectural summary."""

    category: KnowledgeCategory
    items: int
    derived: int
    pointers: int
    kinds: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeBaseSummary:
    """What the knowledge base contains, for architecture inspection."""

    version: str
    items: int
    categories: tuple[CategorySummary, ...]
    by_source_kind: tuple[tuple[str, int], ...]
    by_kind: tuple[tuple[str, int], ...]
    standard_references: int
    claims_standards_compliance: bool = False


class EngineeringKnowledgeBase:
    """The registry. Construct it from adapters; read it; do not mutate it."""

    def __init__(self, items: Iterable[EngineeringKnowledgeItem], *, version: str):
        if not version.strip():
            raise KnowledgeRegistrationError("A knowledge base needs a version.")

        ordered = sorted(items, key=_order)

        seen: set[tuple[str, str]] = set()
        for item in ordered:
            key = (item.id, item.version)
            if key in seen:
                raise KnowledgeRegistrationError(
                    f"Two knowledge items share id '{item.id}' at version "
                    f"'{item.version}'. One of them would silently win, and which "
                    f"one would depend on adapter order."
                )
            seen.add(key)

        self._items: tuple[EngineeringKnowledgeItem, ...] = tuple(ordered)
        self._version = version

    # identity 
    @property
    def version(self) -> str:
        """The version of this knowledge base as a whole.

        Bumped when the SET of published knowledge changes — an adapter
        added, an item retired. Individual items carry their own adapter
        version; see ``app.knowledge.contract``.
        """
        return self._version

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[EngineeringKnowledgeItem]:
        return iter(self._items)

    def __contains__(self, item_id: object) -> bool:
        return any(i.id == item_id for i in self._items)

    # reading 
    def all(self, *, include_deprecated: bool = False) -> tuple[EngineeringKnowledgeItem, ...]:
        if include_deprecated:
            return self._items
        return tuple(i for i in self._items if not i.deprecated)

    def get(self, item_id: str, version: str | None = None) -> EngineeringKnowledgeItem:
        """One item by id, highest version by default.

        Asking for an exact version is supported and is what a stored
        citation should do: a report that says "per estimation.profile.
        screwdriving@1.0.0" means that item, not whatever succeeded it.
        """
        matches = [i for i in self._items if i.id == item_id]
        if version is not None:
            matches = [i for i in matches if i.version == version]
        if not matches:
            asked = f"'{item_id}'" + (f" at version '{version}'" if version else "")
            raise KnowledgeItemNotFound(f"No knowledge item {asked}.")
        return max(matches, key=lambda i: _version_key(i.version))

    def versions_of(self, item_id: str) -> tuple[str, ...]:
        """Every version of one item, oldest first."""
        matches = sorted(
            (i for i in self._items if i.id == item_id),
            key=lambda i: _version_key(i.version),
        )
        if not matches:
            raise KnowledgeItemNotFound(f"No knowledge item '{item_id}'.")
        return tuple(i.version for i in matches)

    def query(
        self,
        *,
        category: KnowledgeCategory | None = None,
        kind: KnowledgeKind | None = None,
        domain: KnowledgeDomain | None = None,
        source_kind: SourceKind | None = None,
        exposure: KnowledgeExposure | None = None,
        tag: str | None = None,
        process_category: str | None = None,
        include_deprecated: bool = False,
    ) -> tuple[EngineeringKnowledgeItem, ...]:
        """Filter the base. Every filter is AND; every result is ordered.

        *process_category* filters by APPLICABILITY, not by tag: an item
        that declares no family limit is returned for every family asked
        for, because that is what "not limited by family" means. Filtering
        it out would quietly hide the general rules from every specific
        question.
        """
        results = self.all(include_deprecated=include_deprecated)

        if category is not None:
            results = tuple(i for i in results if i.category is category)
        if kind is not None:
            results = tuple(i for i in results if i.kind is kind)
        if domain is not None:
            results = tuple(i for i in results if i.domain is domain)
        if source_kind is not None:
            results = tuple(i for i in results if i.provenance.source_kind is source_kind)
        if exposure is not None:
            results = tuple(i for i in results if i.exposure is exposure)
        if tag is not None:
            wanted = tag.strip().lower()
            results = tuple(i for i in results if wanted in i.tags)
        if process_category is not None:
            results = tuple(
                i for i in results if i.applicability.covers(process_category)
            )
        return results

    def provenance_of(self, item_id: str, version: str | None = None):
        """The provenance record of one item. The inspection entry point."""
        return self.get(item_id, version).provenance

    def standard_references(self) -> tuple[StandardReference, ...]:
        """Every standard this build references.

        Returns the references, never their content — there is none to
        return. See ``app.knowledge.standards``.
        """
        return tuple(
            i.standard
            for i in self.query(kind=KnowledgeKind.STANDARD_REFERENCE)
            if i.standard is not None
        )

    # -- inspection -------------------------------------------------------

    def summary(self) -> KnowledgeBaseSummary:
        """A read-only architectural picture of what is held."""
        live = self.all()

        categories = []
        for category in KnowledgeCategory:
            in_category = [i for i in live if i.category is category]
            if not in_category:
                continue
            categories.append(
                CategorySummary(
                    category=category,
                    items=len(in_category),
                    derived=sum(1 for i in in_category if i.derived),
                    pointers=sum(1 for i in in_category if not i.derived),
                    kinds=tuple(sorted({i.kind.value for i in in_category})),
                )
            )

        by_source = Counter(i.provenance.source_kind.value for i in live)
        by_kind = Counter(i.kind.value for i in live)

        return KnowledgeBaseSummary(
            version=self._version,
            items=len(live),
            categories=tuple(categories),
            by_source_kind=tuple(sorted(by_source.items())),
            by_kind=tuple(sorted(by_kind.items())),
            standard_references=len(self.standard_references()),
            claims_standards_compliance=any(
                s.establishes_compliance for s in self.standard_references()
            ),
        )
