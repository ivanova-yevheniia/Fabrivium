"""Factory-layout domain models for Fabrivium Phase 3A."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

# Reusable annotated types (mirrors app.models.factory)

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


def _require_finite(v: float, field_name: str) -> float:
    if not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number, got {v!r}.")
    return v


# MachinePlacement

class MachinePlacement(BaseModel):
    """Where one machine sits on the factory floor."""

    model_config = {"frozen": True}

    machine_id: str = Field(..., min_length=1)
    x: float = Field(..., description="Centre X on factory floor (m)")
    y: float = Field(..., description="Centre Y on factory floor (m)")
    z: float = Field(0.0, description="Elevation (m); 0 for ground-level floor placement")
    rotation_deg: float = Field(0.0, description="Rotation about the Z axis, degrees")

    @field_validator("x", "y", "z", "rotation_deg")
    @classmethod
    def _must_be_finite(cls, v: float, info) -> float:
        return _require_finite(v, info.field_name)


# MachinePhysicalEnvelope

class MachinePhysicalEnvelope(BaseModel):
    """A fully-specified physical envelope: footprint + height + clearances."""

    model_config = {"frozen": True}

    width: PositiveFloat = Field(..., description="Footprint width (m)")
    length: PositiveFloat = Field(..., description="Footprint length (m)")
    height: PositiveFloat | None = Field(
        None, description="Height (m); optional — 2D floor planning does not require it"
    )

    safety_clearance_front: NonNegativeFloat = Field(0.0, description="Required clear space in front (m)")
    safety_clearance_back: NonNegativeFloat = Field(0.0, description="Required clear space behind (m)")
    safety_clearance_left: NonNegativeFloat = Field(0.0, description="Required clear space to the left (m)")
    safety_clearance_right: NonNegativeFloat = Field(0.0, description="Required clear space to the right (m)")


# Zones

class LayoutZoneType(str, Enum):
    AISLE = "AISLE"
    SAFETY = "SAFETY"
    RESERVED = "RESERVED"
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class LayoutZone(BaseModel):
    """A simple axis-aligned rectangular zone on the factory floor."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    x: float = Field(..., description="Bottom-left corner X (m)")
    y: float = Field(..., description="Bottom-left corner Y (m)")
    width: PositiveFloat = Field(..., description="Zone width (m)")
    length: PositiveFloat = Field(..., description="Zone length (m)")
    zone_type: LayoutZoneType

    @field_validator("x", "y")
    @classmethod
    def _must_be_finite(cls, v: float, info) -> float:
        return _require_finite(v, info.field_name)


# FactoryLayout

class FactoryLayout(BaseModel):
    """The full floor layout for one Factory: machine placements + zones."""

    model_config = {"frozen": True}

    factory_width: PositiveFloat = Field(..., description="Factory floor width (m)")
    factory_length: PositiveFloat = Field(..., description="Factory floor length (m)")

    placements: list[MachinePlacement] = Field(default_factory=list)
    reserved_zones: list[LayoutZone] = Field(default_factory=list)
    aisle_zones: list[LayoutZone] = Field(default_factory=list)
