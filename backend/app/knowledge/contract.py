"""The Engineering Knowledge Base contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from app.knowledge.standards import StandardReference


class KnowledgeCategory(str, Enum):
    """What kind of engineering question the item helps answer."""

    # Requirement → operation mappings, route ordering, coverage.
    PROCESS = "PROCESS"
    # Cycle-time bands, automation factors, how an estimate is composed.
    ESTIMATION = "ESTIMATION"
    #: Real equipment records, the catalogues they come from, what a
    #: published specification may and may not be read as.
    EQUIPMENT = "EQUIPMENT"
    # What must be known before something may run, and what fails closed.
    VALIDATION = "VALIDATION"
    # Placement, clearance and floor-space rules.
    LAYOUT = "LAYOUT"
    # What kind of money a decision costs, and what an unknown price means.
    COMMERCIAL = "COMMERCIAL"


class KnowledgeKind(str, Enum):
    """The epistemic type of the item — what sort of thing it asserts."""

    # Something that is the case.
    FACT = "FACT"
    # A conditional Fabrivium applies: if this holds, that follows.
    RULE = "RULE"
    # A documented way of producing a number nobody has measured.
    ESTIMATION_METHOD = "ESTIMATION_METHOD"
    # A rule that decides whether something may proceed.
    VALIDATION_RULE = "VALIDATION_RULE"
    # A record of real equipment, traceable to a document or an asset register.
    EQUIPMENT_EVIDENCE = "EQUIPMENT_EVIDENCE"
    #: A pointer to an organisation's own standing decision — an approved
    #: supplier list, an internal SOP. Fabrivium holds the reference and the
    #: scope, not the policy document.
    COMPANY_POLICY_REFERENCE = "COMPANY_POLICY_REFERENCE"
    #: A pointer to a published standard. NEVER its content — see
    #: app.knowledge.standards.
    STANDARD_REFERENCE = "STANDARD_REFERENCE"


class KnowledgeDomain(str, Enum):
    """How widely the item applies."""

    # Holds for any discrete manufacturing line Fabrivium can model.
    DISCRETE_MANUFACTURING = "DISCRETE_MANUFACTURING"
    # Specific to the electronics assembly work the bundled data covers.
    ELECTRONICS_ASSEMBLY = "ELECTRONICS_ASSEMBLY"


class SourceKind(str, Enum):
    """What the canonical source physically IS."""

    # A rule encoded in Fabrivium's own source code.
    IMPLEMENTED_RULE = "IMPLEMENTED_RULE"
    # A documented constant table in Fabrivium's source code.
    REFERENCE_TABLE = "REFERENCE_TABLE"
    # A dataset file that ships with the build.
    BUNDLED_DATASET = "BUNDLED_DATASET"
    # A document a manufacturer published, cited by URL and retrieval date.
    MANUFACTURER_DOCUMENT = "MANUFACTURER_DOCUMENT"
    # A customer's own record — an asset register, an approved supplier list.
    CUSTOMER_RECORD = "CUSTOMER_RECORD"
    # A live external service — a supplier portal, a manufacturer search.
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    # A published standard. Referenced only; Fabrivium holds no content.
    EXTERNAL_STANDARD = "EXTERNAL_STANDARD"
    # An organisation's internal policy or SOP. Referenced only.
    COMPANY_POLICY = "COMPANY_POLICY"


class KnowledgeExposure(str, Enum):
    """How the item relates to its canonical source. See the module docstring."""

    # `values` were read from the canonical object at build time.
    DERIVED_VALUE = "DERIVED_VALUE"
    # The item locates the knowledge and holds none of it.
    POINTER = "POINTER"


@dataclass(frozen=True)
class Provenance:
    """Where an item's knowledge comes from, and how far it may be trusted."""

    source_kind: SourceKind
    # Something a reader can open: a dotted Python path, a bundled file name, or a URL.
    source_reference: str
    #: One sentence naming what the source actually is, in the source's own
    #: terms where it has any.
    statement: str

    #: The canonical vocabulary this item's trust classification comes from
    #: — "ReferenceClass", "ValueSource", "CatalogKind", "EvidenceLevel",
    #: "PriceStatus" — and the member's value in it. Carried verbatim, never
    #: re-mapped into a vocabulary of this layer's own.
    classification_vocabulary: str | None = None
    classification: str | None = None

    # The day the source records having been checked, where it records one.
    verified_on: date | None = None

    def __post_init__(self) -> None:
        if not self.source_reference.strip():
            raise ValueError("Provenance needs a source reference someone can open.")
        if not self.statement.strip():
            raise ValueError("Provenance needs a statement of what the source is.")
        if bool(self.classification) != bool(self.classification_vocabulary):
            raise ValueError(
                "A classification and the vocabulary it belongs to travel together. "
                f"Got vocabulary={self.classification_vocabulary!r}, "
                f"classification={self.classification!r} — a bare word nobody can look "
                f"up is the thing this field exists to prevent."
            )


@dataclass(frozen=True)
class Applicability:
    """The limits of the item. Never empty by accident."""

    # What the item covers, in the source's own words where it has them.
    scope: str
    process_categories: tuple[str, ...] = ()
    # What the source explicitly excludes.
    not_valid_for: str = ""

    def __post_init__(self) -> None:
        if not self.scope.strip():
            raise ValueError("An applicability with no scope states nothing.")

    def covers(self, process_category: str) -> bool:
        """Whether this applies to *process_category*."""
        if not self.process_categories:
            return True
        return process_category.strip().lower() in self.process_categories


@dataclass(frozen=True)
class EngineeringKnowledgeItem:
    """One addressable piece of engineering knowledge Fabrivium holds."""

    id: str
    version: str
    kind: KnowledgeKind
    category: KnowledgeCategory
    domain: KnowledgeDomain
    title: str
    # What the knowledge says, in a sentence or two an engineer can read.
    description: str
    provenance: Provenance
    applicability: Applicability
    exposure: KnowledgeExposure

    # The values read from the canonical source, for a DERIVED_VALUE item.
    values: Mapping[str, object] = field(default_factory=dict)

    # The source's own status or confidence word, where the source has one.
    status: str | None = None

    tags: tuple[str, ...] = ()

    standard: StandardReference | None = None

    deprecated_on: date | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("A knowledge item needs an id.")
        if not self.version.strip():
            raise ValueError(f"Knowledge item '{self.id}' needs a version.")
        if not self.title.strip():
            raise ValueError(f"Knowledge item '{self.id}' needs a title.")
        if not self.description.strip():
            raise ValueError(f"Knowledge item '{self.id}' needs a description.")

        # Freeze the mapping.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

        if self.exposure is KnowledgeExposure.POINTER and self.values:
            raise ValueError(
                f"Knowledge item '{self.id}' is a POINTER but carries values "
                f"{sorted(self.values)}. A pointer that holds the value is a copy, "
                f"and a copy can drift from the source it was copied out of."
            )
        if self.exposure is KnowledgeExposure.DERIVED_VALUE and not self.values:
            raise ValueError(
                f"Knowledge item '{self.id}' claims DERIVED_VALUE and derived nothing. "
                f"Declare it a POINTER."
            )

        if (self.kind is KnowledgeKind.STANDARD_REFERENCE) != (self.standard is not None):
            raise ValueError(
                f"Knowledge item '{self.id}': a STANDARD_REFERENCE carries a "
                f"StandardReference and nothing else may. This one has "
                f"kind={self.kind.value} and standard={'set' if self.standard else 'None'}."
            )

    @property
    def qualified_id(self) -> str:
        """`id@version` — what a citation records."""
        return f"{self.id}@{self.version}"

    @property
    def deprecated(self) -> bool:
        return self.deprecated_on is not None

    @property
    def derived(self) -> bool:
        """True when the item's values were read from the canonical source."""
        return self.exposure is KnowledgeExposure.DERIVED_VALUE
