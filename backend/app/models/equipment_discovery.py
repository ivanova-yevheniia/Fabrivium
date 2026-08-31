"""Equipment discovery domain models — Phase 16."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.concept import SourcedFloat, SourcedInt, ValueSource


# Provenance

class EquipmentCapability(str, Enum):
    """What a piece of equipment can actually DO, independent of its name."""

    # Driving threaded fasteners — screws, bolts. Phase 16.
    SCREW_FASTENING = "SCREW_FASTENING"
    # Camera-based presence / position / defect checking.
    VISUAL_INSPECTION = "VISUAL_INSPECTION"
    # Printing and/or applying a label or a mark onto the product.
    LABEL_APPLICATION = "LABEL_APPLICATION"


class EvidenceLevel(str, Enum):
    """How well one value is actually supported. Never cosmetic."""

    KNOWN_SPECIFICATION = "KNOWN_SPECIFICATION"
    # Arithmetic on a published value, with the arithmetic written down — e.g.
    SOURCE_DERIVED = "SOURCE_DERIVED"
    # An explicit engineering estimate.
    ESTIMATED = "ESTIMATED"
    # Nothing is known. Not zero, not a default, not "probably fine".
    UNKNOWN = "UNKNOWN"
    # A commercial value the supplier does not publish because their model is to quote.
    QUOTE_REQUIRED = "QUOTE_REQUIRED"


class MatchClaim(str, Enum):
    """The strongest thing Fabrivium is allowed to say about a candidate."""

    # Every requirement the concept states was matched, and none was left unchecked.
    POTENTIALLY_SUITABLE = "POTENTIALLY_SUITABLE"
    #: Provides the capability and nothing contradicts the requirement, but
    #: at least one stated requirement could not be checked.
    CANDIDATE = "CANDIDATE"
    # At least one stated requirement is contradicted by a published value.
    CONSTRAINT_MISMATCH = "CONSTRAINT_MISMATCH"


class CatalogKind(str, Enum):
    """Which KIND of source a candidate came out of."""

    # Fabrivium's own researched dataset of manufacturer-published data.
    RESEARCHED_MANUFACTURER = "RESEARCHED_MANUFACTURER"
    # Equipment the customer already owns. Prices here are legitimately 0.
    INTERNAL_ASSET_POOL = "INTERNAL_ASSET_POOL"
    # A supplier list the customer maintains, with their own commercial terms.
    APPROVED_SUPPLIER = "APPROVED_SUPPLIER"
    # Anything reached over a network at request time.
    EXTERNAL_SOURCE = "EXTERNAL_SOURCE"


class SourceType(str, Enum):
    """How authoritative the document is, in the order we prefer them."""

    # The manufacturer's own product page.
    MANUFACTURER_PAGE = "MANUFACTURER_PAGE"
    # The manufacturer's own datasheet / catalogue / manual PDF.
    MANUFACTURER_DATASHEET = "MANUFACTURER_DATASHEET"
    # An official distributor.
    DISTRIBUTOR_PAGE = "DISTRIBUTOR_PAGE"
    # The customer's own asset register — the record of a machine they already own.
    INTERNAL_ASSET_RECORD = "INTERNAL_ASSET_RECORD"
    # A supplier list the customer maintains, including their own agreed prices.
    APPROVED_SUPPLIER_LIST = "APPROVED_SUPPLIER_LIST"


class DataFreshness(str, Enum):
    """Where the candidate list in front of the user came from."""

    # Retrieved from the web during this request.
    LIVE = "LIVE"
    # The bundled dataset, each entry carrying the date it was verified.
    CACHED = "CACHED"


class PriceStatus(str, Enum):
    """Why a price is or is not shown."""

    PUBLISHED = "PUBLISHED"
    QUOTE_REQUIRED = "QUOTE_REQUIRED"
    UNKNOWN = "UNKNOWN"


class EquipmentSource(BaseModel):
    """One document, cited once and referenced by every value taken from it."""

    model_config = {"frozen": True}

    source_id: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    source_type: SourceType
    title: str = Field(..., min_length=1)
    # The day the values were read out of this document.
    retrieved_at: date


class PublishedSpec(BaseModel):
    """One specification a manufacturer published — or explicitly did not."""

    model_config = {"frozen": True}

    value: float | None = None
    unit: str | None = None
    # For facts that are published but not numeric ("Modbus TCP", "on request").
    text: str | None = None
    source_id: str | None = None

    # How well this one value is supported.
    evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    #: Required for SOURCE_DERIVED and ESTIMATED: the arithmetic or the
    #: reasoning, in one sentence. Enforced below — a derived number with no
    #: derivation written down is indistinguishable from an invented one.
    basis: str | None = None

    @model_validator(mode="after")
    def _evidence_matches_content(self) -> "PublishedSpec":
        if not self.published:
            # An empty spec is UNKNOWN whatever the file said.
            if self.evidence is not EvidenceLevel.UNKNOWN:
                object.__setattr__(self, "evidence", EvidenceLevel.UNKNOWN)
            return self
        if self.evidence is EvidenceLevel.UNKNOWN:
            object.__setattr__(self, "evidence", EvidenceLevel.KNOWN_SPECIFICATION)
        if self.evidence in (EvidenceLevel.SOURCE_DERIVED, EvidenceLevel.ESTIMATED) and not self.basis:
            raise ValueError(
                f"A {self.evidence.value} value must carry the basis it was derived from."
            )
        return self

    @property
    def published(self) -> bool:
        return self.value is not None or self.text is not None

    @property
    def traceable(self) -> bool:
        """Whether an engineer can get back to a document from this value."""
        return self.evidence in (EvidenceLevel.KNOWN_SPECIFICATION, EvidenceLevel.SOURCE_DERIVED)

    @classmethod
    def not_published(cls) -> "PublishedSpec":
        return cls()

    @classmethod
    def of(cls, value: float, unit: str, source_id: str) -> "PublishedSpec":
        return cls(value=value, unit=unit, source_id=source_id, evidence=EvidenceLevel.KNOWN_SPECIFICATION)

    @classmethod
    def stated(cls, text: str, source_id: str) -> "PublishedSpec":
        return cls(text=text, source_id=source_id, evidence=EvidenceLevel.KNOWN_SPECIFICATION)

    @classmethod
    def derived(cls, value: float, unit: str, source_id: str, basis: str) -> "PublishedSpec":
        """Our arithmetic on someone else's published number."""
        return cls(
            value=value,
            unit=unit,
            source_id=source_id,
            evidence=EvidenceLevel.SOURCE_DERIVED,
            basis=basis,
        )

    @classmethod
    def estimated(cls, value: float, unit: str, basis: str) -> "PublishedSpec":
        """An engineering estimate, with no document behind it."""
        return cls(value=value, unit=unit, evidence=EvidenceLevel.ESTIMATED, basis=basis)


# The requirement

class EquipmentRequirement(BaseModel):
    """What the concept needs from this station, derived from the concept."""

    model_config = {"frozen": True}

    station_id: str = Field(..., min_length=1)
    station_name: str = Field(..., min_length=1)
    # Free text taken from the concept stage, e.g. "screwdriving".
    process_category: str = Field(..., min_length=1)

    # WHAT THE STATION MUST BE ABLE TO DO.
    required_capability: EquipmentCapability | None = None
    #: One sentence naming what the equipment has to accomplish, written for
    #: an engineer to take to a vendor.
    capability_statement: str = ""

    #: The station must keep up with the concept's cycle time, so the
    #: equipment's own cycle must not exceed it.
    max_cycle_time_seconds: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    required_capacity: SourcedInt = Field(default_factory=SourcedInt.unknown)
    operator_requirement: SourcedInt = Field(default_factory=SourcedInt.unknown)

    # How many times this station performs its operation per unit — four screws, one
    # label, one inspection.
    operations_per_unit: SourcedInt = Field(default_factory=SourcedInt.unknown)

    # Planning envelope in metres — what the layout allocated to this station.
    max_width_m: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    max_length_m: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    max_height_m: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # What the equipment has to hold, move or present.
    max_payload_kg: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    # The product's own overall dimensions as the source stated them, e.g.
    part_dimensions_text: str | None = None
    part_dimensions_provenance: str | None = None

    # What may be spent on THIS station, not the whole project.
    budget_limit: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # Only ever populated from an explicit statement.
    required_interfaces: list[str] = Field(default_factory=list)
    # Soft — recorded and shown, never turned into a PASS/FAIL.
    optional_preferences: list[str] = Field(default_factory=list)

    # Which strategy the engineer was looking at when this was derived.
    strategy_context: str | None = None
    # Human-readable note about how the requirement was built.
    provenance: str = Field("", description="How this requirement was derived")

    @property
    def known_bounds(self) -> int:
        """How many bounds the concept actually establishes."""
        return sum(
            1
            for bound in (
                self.max_cycle_time_seconds,
                self.required_capacity,
                self.operator_requirement,
                self.max_width_m,
                self.max_length_m,
                self.budget_limit,
                self.max_payload_kg,
            )
            if bound.known
        )


# The candidate

class EquipmentCandidate(BaseModel):
    """Real equipment, as its manufacturer describes it."""

    model_config = {"frozen": True}

    candidate_id: str = Field(..., min_length=1)
    manufacturer: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    # e.g. "Fixtured screwdriving system", "Assembly cell".
    category: str = Field(..., min_length=1)

    # WHAT THIS EQUIPMENT DOES, declared in its catalogue record.
    provides: list[EquipmentCapability] = Field(default_factory=list)

    # Which catalogue this record came out of.
    catalog_id: str = ""
    catalog_kind: CatalogKind = CatalogKind.RESEARCHED_MANUFACTURER
    #: What the product IS relative to a station — a complete cell, or a
    #: component that has to be integrated into one. An engineer must not
    #: have to infer this from the model name.
    product_scope: str = Field(..., min_length=1)
    description: str = ""

    # The fields a requirement can be checked against
    cycle_time_seconds: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    capacity: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    operators_required: PublishedSpec = Field(default_factory=PublishedSpec.not_published)

    width_mm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    length_mm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    height_mm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    weight_kg: PublishedSpec = Field(default_factory=PublishedSpec.not_published)

    torque_min_nm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    torque_max_nm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    speed_max_rpm: PublishedSpec = Field(default_factory=PublishedSpec.not_published)

    interfaces: list[str] = Field(default_factory=list)
    interfaces_source_id: str | None = None

    price: PublishedSpec = Field(default_factory=PublishedSpec.not_published)
    price_status: PriceStatus = PriceStatus.UNKNOWN

    # None means "we do not know", which is different from False.
    cad_available: bool | None = None
    cad_format: str | None = None
    cad_url: str | None = None
    documentation_url: str | None = None

    sources: list[EquipmentSource] = Field(default_factory=list)
    # Anything an engineer must know that is not a spec — e.g.
    caveats: list[str] = Field(default_factory=list)

    @property
    def source_backed(self) -> bool:
        """Whether this may be shown as real equipment at all."""
        return bool(self.sources)

    @property
    def primary_source(self) -> EquipmentSource | None:
        """The best document we have, manufacturer first."""
        order = {
            SourceType.MANUFACTURER_DATASHEET: 0,
            SourceType.MANUFACTURER_PAGE: 1,
            SourceType.DISTRIBUTOR_PAGE: 2,
            # A customer's own records are authoritative about THEIR
            # equipment but are not a publication, so they rank below every
            # document a third party could open and check.
            SourceType.APPROVED_SUPPLIER_LIST: 3,
            SourceType.INTERNAL_ASSET_RECORD: 4,
        }
        assert set(order) == set(SourceType), "every SourceType needs a rank"
        return min(self.sources, key=lambda s: order[s.source_type], default=None)

    @property
    def completeness(self) -> "SpecCompleteness":
        """How much of the comparable data the manufacturer publishes."""
        specs = [
            self.cycle_time_seconds,
            self.capacity,
            self.operators_required,
            self.width_mm,
            self.length_mm,
            self.height_mm,
            self.weight_kg,
            self.price,
        ]
        return SpecCompleteness(
            published=sum(1 for s in specs if s.published),
            considered=len(specs),
        )

    @property
    def comparable_specs(self) -> list[PublishedSpec]:
        """The values a requirement can be checked against."""
        return [
            self.cycle_time_seconds,
            self.capacity,
            self.operators_required,
            self.width_mm,
            self.length_mm,
            self.height_mm,
            self.weight_kg,
            self.price,
        ]

    @property
    def evidence_summary(self) -> "EvidenceSummary":
        """One count per evidence level across the comparable values."""
        counts = {level: 0 for level in EvidenceLevel}
        for spec in self.comparable_specs:
            counts[spec.evidence] += 1
        if self.price_status is PriceStatus.QUOTE_REQUIRED:
            # The price contributed UNKNOWN above; move it out, because
            # "they quote" is not the same as "we could not find out".
            counts[EvidenceLevel.UNKNOWN] = max(0, counts[EvidenceLevel.UNKNOWN] - 1)
            counts[EvidenceLevel.QUOTE_REQUIRED] += 1
        return EvidenceSummary(
            known_specification=counts[EvidenceLevel.KNOWN_SPECIFICATION],
            source_derived=counts[EvidenceLevel.SOURCE_DERIVED],
            estimated=counts[EvidenceLevel.ESTIMATED],
            unknown=counts[EvidenceLevel.UNKNOWN],
            quote_required=counts[EvidenceLevel.QUOTE_REQUIRED],
        )

    def provides_capability(self, capability: "EquipmentCapability | None") -> bool:
        """Whether this record DECLARES the capability asked for."""
        return capability is not None and capability in self.provides


class SpecCompleteness(BaseModel):
    model_config = {"frozen": True}

    published: int
    considered: int


class EvidenceSummary(BaseModel):
    """How this candidate's comparable values are supported, by level."""

    model_config = {"frozen": True}

    known_specification: int = 0
    source_derived: int = 0
    estimated: int = 0
    unknown: int = 0
    # Commercial values the supplier quotes rather than publishes.
    quote_required: int = 0

    @property
    def traceable(self) -> int:
        """Values that lead back to a document."""
        return self.known_specification + self.source_derived


# Selection

class EquipmentSelection(BaseModel):
    """The engineer's choice, recorded as metadata."""

    model_config = {"frozen": True}

    station_id: str = Field(..., min_length=1)
    candidate_id: str = Field(..., min_length=1)
    manufacturer: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    source_url: str | None = None
    #: Copied from the candidate so a selection stays interpretable even if
    #: the dataset is later refreshed.
    selected_from: DataFreshness = DataFreshness.CACHED
    # Which published values, if any, the engineer explicitly adopted into the concept.
    adopted_parameters: list[str] = Field(default_factory=list)


class ParameterChange(BaseModel):
    """One proposed replacement of a planning value by a published one."""

    model_config = {"frozen": True}

    field: str
    label: str
    current_value: float | None
    current_source: ValueSource
    proposed_value: float
    proposed_unit: str
    proposed_source_url: str | None = None
    #: True when this field feeds the simulator, so adopting it will change
    #: verified KPIs and the concept must be re-verified.
    affects_simulation: bool = False
