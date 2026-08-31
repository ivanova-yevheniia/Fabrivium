"""Product understanding — Phase 19."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FactStatus(str, Enum):
    """How a fact came to be, and how far it has been trusted."""

    EXTRACTED = "EXTRACTED"
    # A language model read it out of, or inferred it from, the source.
    AI_INFERRED = "AI_INFERRED"
    # Derived from other facts by a deterministic rule, with no model involved.
    RULE_DERIVED = "RULE_DERIVED"
    # Stated by the customer or engineer in their own words.
    STATED = "STATED"
    # An engineer has looked at it and accepted it.
    ENGINEER_VERIFIED = "ENGINEER_VERIFIED"
    # Sources disagree. Carries the alternatives; blocks whatever needs it.
    CONFLICT = "CONFLICT"
    # Not known. Never rendered as a value, never defaulted.
    UNKNOWN = "UNKNOWN"


class EvidenceRef(BaseModel):
    """Where a fact was found, precisely enough to go and look."""

    model_config = {"frozen": True}

    document_id: str = Field(..., min_length=1)
    document_name: str = Field(..., min_length=1)
    # 1-based, as a reader would count. None for non-paginated sources.
    page: int | None = Field(None, ge=1)
    # The sentence the fact was taken from, so the reading can be argued with.
    quote: str | None = None


class ProductFact(BaseModel):
    """One thing Fabrivium believes about the product."""

    model_config = {"frozen": True}

    # Stable key, e.g. "fastener.screw.count", "material.enclosure".
    key: str = Field(..., min_length=1)
    # What kind of thing this is, for grouping in the UI.
    category: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)

    value: str | None = None
    quantity: float | None = None
    unit: str | None = None

    status: FactStatus = FactStatus.UNKNOWN
    confidence: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    #: Populated only when `status` is CONFLICT: the readings that disagree,
    #: each with its own evidence, so the engineer chooses rather than
    #: Fabrivium guessing.
    alternatives: list["ProductFact"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unknown_carries_no_value(self) -> "ProductFact":
        if self.status is FactStatus.UNKNOWN and (self.value is not None or self.quantity is not None):
            raise ValueError(f"Fact '{self.key}' is UNKNOWN but carries a value.")
        if self.status is FactStatus.EXTRACTED and not self.evidence:
            # An extracted fact with nothing to point at is indistinguishable
            # from an invented one.
            raise ValueError(f"Fact '{self.key}' claims EXTRACTED but cites no evidence.")
        return self

    @property
    def known(self) -> bool:
        return self.status not in (FactStatus.UNKNOWN, FactStatus.CONFLICT)


class SourceDocument(BaseModel):
    """A document that was supplied, and what could be read from it."""

    model_config = {"frozen": True}

    document_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    media_type: str = Field(..., min_length=1)
    pages: int | None = None
    ingested_on: date
    # Pages that yielded no extractable text.
    pages_without_text: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class InformationGap(BaseModel):
    """Something Fabrivium does not know, and what it blocks."""

    model_config = {"frozen": True}

    key: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    # BLOCKS_EQUIPMENT_SELECTION | LIMITS_EQUIPMENT_VALIDATION |
    # BLOCKS_DETAILED_ENGINEERING | OPTIONAL.
    severity: str = "OPTIONAL"
    reason: str = ""


class SourceProductionRequirement(BaseModel):
    """A production boundary condition the SOURCE DOCUMENT itself states."""

    model_config = {"frozen": True}

    # Stable key, e.g. "production.target_per_day", "production.floor_area".
    key: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    # The reading, as text: "1900 units/day", "30 × 18 m".
    value: str = Field(..., min_length=1)
    # The number, for comparison against a parsed requirement.
    quantity: float
    # The second number, where the value has two — a floor is 30 BY 18.
    quantity_secondary: float | None = None
    evidence: EvidenceRef


class UnresolvedSourceStatement(BaseModel):
    """A sentence that reads as manufacturing work and was not mapped."""

    model_config = {"frozen": True}

    # The sentence, verbatim.
    statement: str = Field(..., min_length=1)
    evidence: EvidenceRef
    #: Why it is here, in words, so the panel does not have to invent a
    #: caption that overstates what was detected.
    reason: str = ""


class ProductUnderstanding(BaseModel):
    """Everything Fabrivium believes about one product, with its evidence."""

    model_config = {"frozen": True}

    product_name: str = Field("Product", min_length=1)
    description: str = ""

    facts: list[ProductFact] = Field(default_factory=list)
    source_documents: list[SourceDocument] = Field(default_factory=list)
    information_gaps: list[InformationGap] = Field(default_factory=list)
    #: Sentences that state work on the product which structured extraction
    #: could not map. Candidates for an engineer to triage — never operations,
    #: never requirements, and never counted as facts.
    unresolved_statements: list[UnresolvedSourceStatement] = Field(default_factory=list)
    # What the source says about PRODUCTION rather than about the product — a volume, a
    # floor, a headcount.
    source_production_requirements: list[SourceProductionRequirement] = Field(default_factory=list)

    #: How the facts were obtained overall, for the provenance line:
    #: "DOCUMENT_EXTRACTION", "LANGUAGE_MODEL", "REFERENCE_EXAMPLE".
    interpretation_method: str = "DOCUMENT_EXTRACTION"
    # Named when a model was involved, so the UI can say which rather than saying "AI".
    model_name: str | None = None

    def fact(self, key: str) -> ProductFact | None:
        return next((f for f in self.facts if f.key == key), None)

    @property
    def conflicts(self) -> list[ProductFact]:
        return [f for f in self.facts if f.status is FactStatus.CONFLICT]

    @property
    def unresolved_conflict_keys(self) -> list[str]:
        return [f.key for f in self.conflicts]


ProductFact.model_rebuild()
