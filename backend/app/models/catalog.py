"""Equipment catalog domain models for Fabrivium Phase 3C."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.equipment import EquipmentAsset, EquipmentAssetType
from app.models.factory import NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt


# Enums

class EquipmentSourceType(str, Enum):
    """Where a catalog entry's data originated."""

    INTERNAL_LIBRARY = "INTERNAL_LIBRARY"    # Fabrivium's own curated library.
    USER_UPLOAD = "USER_UPLOAD"              # An engineer entered/uploaded this directly.
    EXTERNAL_CATALOG = "EXTERNAL_CATALOG"    # A third-party catalog/marketplace (e.g. GrabCAD-like).
    MANUFACTURER = "MANUFACTURER"            # Sourced directly from the equipment manufacturer.
    CUSTOM_REQUEST = "CUSTOM_REQUEST"        # An ad-hoc engineering spec with no external source yet.


class EquipmentAvailability(str, Enum):
    """How generally obtainable a catalog entry is — independent of any
    one Factory (see module docstring for how this differs from
    ``app.models.equipment.EquipmentLifecycleStatus``)."""

    AVAILABLE = "AVAILABLE"                  # A real, obtainable piece of equipment.
    PURCHASE_CANDIDATE = "PURCHASE_CANDIDATE"  # Being evaluated; not committed to.
    CUSTOM_BUILD = "CUSTOM_BUILD"             # Would need to be custom-designed/built.
    UNKNOWN = "UNKNOWN"                       # Not yet determined.


class ModelRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"


# EquipmentCatalogEntry

class EquipmentCatalogEntry(BaseModel):
    """One reusable piece of equipment in the catalog."""

    model_config = {"frozen": True}

    catalog_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    manufacturer: str | None = None
    model_number: str | None = None
    process_type: str = Field(..., min_length=1)
    description: str | None = None

    # Engineering specification — mirrors app.models.factory.Machine's
    # fields exactly (same names, same units) so
    # create_machine_from_catalog_entry is a straightforward field copy.
    width: PositiveFloat
    length: PositiveFloat
    height: PositiveFloat | None = None
    cycle_time: PositiveFloat | None = Field(
        None, description="Optional — None means timing has not been confirmed yet"
    )
    capacity: PositiveInt = 1
    setup_time: NonNegativeFloat = 0.0
    operators_required: NonNegativeInt = 0
    purchase_cost: NonNegativeFloat = 0.0
    failure_rate: NonNegativeFloat = 0.0
    mean_repair_time: NonNegativeFloat = 0.0

    # Asset metadata
    asset: EquipmentAsset

    # Source metadata
    source_type: EquipmentSourceType
    source_uri: str | None = None
    source_name: str | None = None
    external_reference_id: str | None = None

    # Lifecycle / availability
    equipment_availability: EquipmentAvailability = EquipmentAvailability.UNKNOWN


# External reference (Phase 3C section 6)

class ExternalEquipmentReference(BaseModel):
    """A reference to equipment listed on an external source (e.g."""

    model_config = {"frozen": True}

    provider_name: str = Field(..., min_length=1, description="e.g. 'GrabCAD', 'TraceParts', a manufacturer's own site")
    source_uri: str = Field(..., min_length=1)
    external_id: str | None = None
    title: str = Field(..., min_length=1)
    manufacturer: str | None = None
    model_number: str | None = None
    license_name: str | None = None


# Model request (Phase 3C section 7)

class EquipmentModelRequest(BaseModel):
    """
    Tracks a request for a visual asset (a proxy needing a real model, or a custom
    design needing one built) to become available.
    """

    model_config = {"frozen": True}

    request_id: str = Field(..., min_length=1)
    catalog_id: str = Field(..., min_length=1, description="The EquipmentCatalogEntry this request is for")
    requested_asset_type: EquipmentAssetType
    status: ModelRequestStatus = ModelRequestStatus.REQUESTED
    notes: str | None = None
    sequence: int = Field(..., ge=1, description="Deterministic creation order (see class docstring)")


# Readiness (Phase 3C section 9)

class EquipmentReadiness(BaseModel):
    """
    Explicit, rule-based (never LLM-based) readiness evaluation for one
    ``EquipmentCatalogEntry``.
    """

    model_config = {"frozen": True}

    layout_ready: bool
    simulation_ready: bool
    visual_ready: bool
    reasons: list[str] = Field(
        default_factory=list, description="Explanation for every False flag above, in flag order"
    )
