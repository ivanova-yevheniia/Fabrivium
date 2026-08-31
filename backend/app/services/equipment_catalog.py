"""Equipment catalogues — the pluggable source layer."""

from __future__ import annotations

import json
import pathlib
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.models.equipment_discovery import (
    CatalogKind,
    EquipmentCandidate,
    EquipmentCapability,
    EquipmentSource,
    PriceStatus,
    PublishedSpec,
)

_DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"


# The interface

class CatalogDescriptor(BaseModel):
    """Who is answering. Travels with every response and every candidate."""

    model_config = {"frozen": True}

    catalog_id: str = Field(..., min_length=1)
    kind: CatalogKind
    display_name: str = Field(..., min_length=1)
    # One sentence an engineer can read to know how much to trust it.
    trust_statement: str = ""


class CatalogQuery(BaseModel):
    """What is being asked for."""

    model_config = {"frozen": True}

    capability: EquipmentCapability


class CatalogResponse(BaseModel):
    """One catalogue's answer, including "I could not answer"."""

    model_config = {"frozen": True}

    descriptor: CatalogDescriptor
    # False means the catalogue could not be consulted at all.
    available: bool = True
    # Always present when `available` is False; shown to the user verbatim.
    unavailable_reason: str = ""
    candidates: list[EquipmentCandidate] = Field(default_factory=list)
    verified_on: date | None = None


@runtime_checkable
class EquipmentCatalog(Protocol):
    """Everything a source has to provide to be pluggable."""

    @property
    def descriptor(self) -> CatalogDescriptor:
        ...

    def search(self, query: CatalogQuery) -> CatalogResponse:
        ...


# Implementation 1 — records held in bundled JSON files

class JsonFileCatalog:
    """A catalogue whose records live in one or more bundled JSON files."""

    def __init__(self, descriptor: CatalogDescriptor, filenames: tuple[str, ...]):
        self._descriptor = descriptor
        self._filenames = filenames

    @property
    def descriptor(self) -> CatalogDescriptor:
        return self._descriptor

    def search(self, query: CatalogQuery) -> CatalogResponse:
        candidates: list[EquipmentCandidate] = []
        verified: list[date] = []

        for filename in self._filenames:
            path = _DATA_DIR / filename
            if not path.exists():
                # A registered file that is not on disk is a packaging
                # error, not a search result. Say so rather than reporting
                # an empty shortlist that reads as "nothing on the market".
                return CatalogResponse(
                    descriptor=self._descriptor,
                    available=False,
                    unavailable_reason=f"The catalogue file '{filename}' is missing from this build.",
                )
            found, file_verified = self._read(path, query.capability)
            if found:
                candidates.extend(found)
                if file_verified is not None:
                    verified.append(file_verified)

        return CatalogResponse(
            descriptor=self._descriptor,
            available=True,
            candidates=candidates,
            verified_on=max(verified) if verified else None,
        )

    def _read(
        self, path: pathlib.Path, capability: EquipmentCapability
    ) -> tuple[list[EquipmentCandidate], date | None]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        sources = {
            raw["source_id"]: EquipmentSource.model_validate(raw)
            for raw in payload.get("sources", [])
        }
        verified_on = (
            date.fromisoformat(payload["verified_on"]) if payload.get("verified_on") else None
        )

        candidates = []
        for raw in payload.get("candidates", []):
            provides = [EquipmentCapability(c) for c in raw.get("provides", [])]
            # The capability filter, applied to a DECLARATION.
            if capability not in provides:
                continue
            candidates.append(_candidate_from(raw, provides, sources, self._descriptor))
        return candidates, verified_on


def _candidate_from(
    raw: dict,
    provides: list[EquipmentCapability],
    sources: dict[str, EquipmentSource],
    descriptor: CatalogDescriptor,
) -> EquipmentCandidate:
    """Build one candidate. Every unpublished field stays unpublished."""
    cited = [sources[sid] for sid in raw.get("sources", []) if sid in sources]
    return EquipmentCandidate(
        candidate_id=raw["candidate_id"],
        manufacturer=raw["manufacturer"],
        model=raw["model"],
        category=raw["category"],
        product_scope=raw["product_scope"],
        description=raw.get("description", ""),
        provides=provides,
        catalog_id=descriptor.catalog_id,
        catalog_kind=descriptor.kind,
        cycle_time_seconds=_spec(raw.get("cycle_time_seconds")),
        capacity=_spec(raw.get("capacity")),
        operators_required=_spec(raw.get("operators_required")),
        width_mm=_spec(raw.get("width_mm")),
        length_mm=_spec(raw.get("length_mm")),
        height_mm=_spec(raw.get("height_mm")),
        weight_kg=_spec(raw.get("weight_kg")),
        torque_min_nm=_spec(raw.get("torque_min_nm")),
        torque_max_nm=_spec(raw.get("torque_max_nm")),
        speed_max_rpm=_spec(raw.get("speed_max_rpm")),
        interfaces=raw.get("interfaces", []),
        interfaces_source_id=raw.get("interfaces_source_id"),
        price=_spec(raw.get("price")),
        price_status=PriceStatus(raw.get("price_status", "UNKNOWN")),
        cad_available=raw.get("cad_available"),
        cad_format=raw.get("cad_format"),
        cad_url=raw.get("cad_url"),
        documentation_url=raw.get("documentation_url"),
        sources=cited,
        caveats=raw.get("caveats", []),
    )


def _spec(raw: dict | None) -> PublishedSpec:
    if not raw:
        return PublishedSpec.not_published()
    return PublishedSpec.model_validate(raw)


# Implementation 2 — a source that is not connected

class UnavailableCatalog:
    """An external source declared but not reachable from this build."""

    def __init__(self, descriptor: CatalogDescriptor, reason: str):
        self._descriptor = descriptor
        self._reason = reason

    @property
    def descriptor(self) -> CatalogDescriptor:
        return self._descriptor

    def search(self, query: CatalogQuery) -> CatalogResponse:
        return CatalogResponse(
            descriptor=self._descriptor,
            available=False,
            unavailable_reason=self._reason,
        )


# The registry

class CatalogSearchResult(BaseModel):
    """What every registered catalogue said, merged but not flattened."""

    model_config = {"frozen": True}

    #: None when the station's process type maps to no researched
    #: capability — no catalogue was consulted and none should be reported
    #: as having come back empty.
    capability: EquipmentCapability | None = None
    candidates: list[EquipmentCandidate] = Field(default_factory=list)
    responses: list[CatalogResponse] = Field(default_factory=list)

    @property
    def verified_on(self) -> date | None:
        """The oldest verification date among the catalogues that answered."""
        dates = [r.verified_on for r in self.responses if r.verified_on is not None]
        return min(dates) if dates else None

    @property
    def unavailable(self) -> list[CatalogResponse]:
        return [r for r in self.responses if not r.available]

    @property
    def consulted(self) -> list[CatalogResponse]:
        return [r for r in self.responses if r.available]


class EquipmentCatalogRegistry:
    """Holds the catalogues and asks all of them."""

    def __init__(self, catalogs: tuple[EquipmentCatalog, ...]):
        ids = [c.descriptor.catalog_id for c in catalogs]
        assert len(ids) == len(set(ids)), f"duplicate catalog ids: {ids}"
        self._catalogs = catalogs

    @property
    def descriptors(self) -> list[CatalogDescriptor]:
        return [c.descriptor for c in self._catalogs]

    def search(self, capability: EquipmentCapability | None) -> CatalogSearchResult:
        """Ask every catalogue, keep every answer including the failures."""
        if capability is None:
            return CatalogSearchResult(capability=None, candidates=[], responses=[])

        query = CatalogQuery(capability=capability)
        responses = [c.search(query) for c in self._catalogs]
        candidates = [c for r in responses if r.available for c in r.candidates]
        return CatalogSearchResult(
            capability=capability, candidates=candidates, responses=responses
        )


# What ships

RESEARCHED = CatalogDescriptor(
    catalog_id="factorymind-researched",
    kind=CatalogKind.RESEARCHED_MANUFACTURER,
    display_name="Fabrivium researched manufacturer data",
    trust_statement=(
        "Every value was read out of the manufacturer document cited beside it, on the "
        "date shown. Nothing is averaged, inferred or estimated."
    ),
)

INTERNAL_POOL = CatalogDescriptor(
    catalog_id="customer-asset-pool",
    kind=CatalogKind.INTERNAL_ASSET_POOL,
    display_name="Customer's existing equipment",
    trust_statement=(
        "Equipment the customer already owns, as recorded in their own asset register. "
        "Authoritative for them; not a manufacturer publication. A purchase price of €0 "
        "means the machine is already owned, and excludes moving and requalification."
    ),
)

APPROVED_SUPPLIERS = CatalogDescriptor(
    catalog_id="customer-approved-suppliers",
    kind=CatalogKind.APPROVED_SUPPLIER,
    display_name="Customer's approved supplier list",
    trust_statement=(
        "Models and commercial terms the customer's procurement function has already "
        "approved. Prices are their agreed prices, not public list prices."
    ),
)

LIVE_WEB = CatalogDescriptor(
    catalog_id="live-manufacturer-web",
    kind=CatalogKind.EXTERNAL_SOURCE,
    display_name="Live manufacturer web search",
    trust_statement="Not connected in this build.",
)


def default_registry() -> EquipmentCatalogRegistry:
    """The catalogues this build ships with."""
    return EquipmentCatalogRegistry(
        (
            JsonFileCatalog(INTERNAL_POOL, ("internal_asset_pool.json",)),
            JsonFileCatalog(APPROVED_SUPPLIERS, ("approved_supplier_catalog.json",)),
            JsonFileCatalog(
                RESEARCHED,
                (
                    "screwdriving_candidates.json",
                    "visual_inspection_candidates.json",
                    "label_application_candidates.json",
                ),
            ),
            UnavailableCatalog(
                LIVE_WEB,
                "Live manufacturer search is not connected in this build; only bundled "
                "catalogues were consulted.",
            ),
        )
    )
