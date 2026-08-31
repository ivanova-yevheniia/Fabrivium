"""Equipment asset & lifecycle domain models for Fabrivium Phase 3A."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


# Enums

class EquipmentAssetType(str, Enum):
    """What kind of visual representation (if any) backs a machine."""

    EXACT_CAD = "EXACT_CAD"    # A real CAD model of the exact purchased/installed unit.
    LIBRARY = "LIBRARY"        # A reusable stock/library model (not the exact unit).
    PROXY = "PROXY"            # A generic engineering box (dimensions only, no real geometry).
    MISSING = "MISSING"        # No visual representation recorded at all.


class EquipmentAssetStatus(str, Enum):
    """Where the asset's underlying file(s) currently stand."""

    AVAILABLE = "AVAILABLE"    # The asset (or, for PROXY, the generic proxy) is ready to use.
    MISSING = "MISSING"        # Nothing has been sourced yet.
    REQUESTED = "REQUESTED"    # Someone has asked for it (e.g. from a vendor) but it hasn't arrived.
    PROCESSING = "PROCESSING"  # It has arrived and is being converted/prepared for use.


class EquipmentLifecycleStatus(str, Enum):
    """Where a machine stands in its procurement/installation lifecycle."""

    EXISTING = "EXISTING"                          # Already on the floor.
    PURCHASE_CANDIDATE = "PURCHASE_CANDIDATE"       # Being evaluated for purchase (e.g. a what-if clone).
    CUSTOM_DESIGN = "CUSTOM_DESIGN"                 # A bespoke design, not yet an off-the-shelf product.
    ORDERED = "ORDERED"                             # Purchase order placed.
    APPROVED = "APPROVED"                           # Approved for purchase/build but not yet ordered.
    INSTALLED = "INSTALLED"                         # Physically installed on the floor.


# EquipmentAsset

class EquipmentAsset(BaseModel):
    """Visual/CAD asset metadata for a machine."""

    model_config = {"frozen": True}

    asset_type: EquipmentAssetType
    status: EquipmentAssetStatus

    asset_uri: str | None = Field(None, description="Where the renderable/importable asset file lives")
    source_uri: str | None = Field(None, description="Where the asset was sourced from (vendor page, GrabCAD, etc.)")
    manufacturer: str | None = Field(None, description="Equipment manufacturer name")
    model_number: str | None = Field(None, description="Manufacturer model/part number")
    license_name: str | None = Field(None, description="License the asset file is distributed under")
    attribution: str | None = Field(None, description="Required attribution text, if any")
    file_format: str | None = Field(None, description="e.g. 'STEP', 'glTF', 'FBX'")
    notes: str | None = Field(None, description="Free-text notes")

    @model_validator(mode="after")
    def _available_exact_or_library_requires_uri(self) -> "EquipmentAsset":
        needs_uri = (
            self.asset_type in (EquipmentAssetType.EXACT_CAD, EquipmentAssetType.LIBRARY)
            and self.status == EquipmentAssetStatus.AVAILABLE
        )
        if needs_uri and not self.asset_uri:
            raise ValueError(
                f"EquipmentAsset(asset_type={self.asset_type.value}, "
                f"status={self.status.value}) requires asset_uri to be set."
            )
        return self


# Proxy helper

def create_proxy_asset(
    *,
    manufacturer: str | None = None,
    model_number: str | None = None,
    notes: str | None = None,
) -> EquipmentAsset:
    """Build a generic engineering-proxy ``EquipmentAsset``."""
    return EquipmentAsset(
        asset_type=EquipmentAssetType.PROXY,
        status=EquipmentAssetStatus.AVAILABLE,
        manufacturer=manufacturer,
        model_number=model_number,
        notes=notes,
    )


# Exact CAD registration helper (Phase 3C)

# Documented, non-enforced set of common CAD/3D file formats (Phase 3C section 5).
KNOWN_CAD_FILE_FORMATS = frozenset({"STEP", "STP", "IGES", "IGS", "STL", "OBJ", "GLB", "GLTF"})


def create_exact_cad_asset(
    *,
    asset_uri: str,
    file_format: str | None = None,
    source_uri: str | None = None,
    manufacturer: str | None = None,
    model_number: str | None = None,
    license_name: str | None = None,
    attribution: str | None = None,
    notes: str | None = None,
) -> EquipmentAsset:
    """Register metadata for an exact CAD asset (Phase 3C section 5)."""
    return EquipmentAsset(
        asset_type=EquipmentAssetType.EXACT_CAD,
        status=EquipmentAssetStatus.AVAILABLE,
        asset_uri=asset_uri,
        source_uri=source_uri,
        manufacturer=manufacturer,
        model_number=model_number,
        license_name=license_name,
        attribution=attribution,
        file_format=file_format,
        notes=notes,
    )
