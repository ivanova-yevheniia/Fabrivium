"""Typed result models for Fabrivium Phase 3B — the layout constraint engine."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# Enums

class ConstraintSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


class ConstraintType(str, Enum):
    """Declaration order doubles as the deterministic tie-break order used
    by ``app.services.constraints._sort_violations`` — see its docstring."""

    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    MACHINE_OVERLAP = "MACHINE_OVERLAP"
    SAFETY_CLEARANCE_OVERLAP = "SAFETY_CLEARANCE_OVERLAP"
    AISLE_BLOCKED = "AISLE_BLOCKED"
    RESERVED_ZONE_OVERLAP = "RESERVED_ZONE_OVERLAP"
    MISSING_PLACEMENT = "MISSING_PLACEMENT"
    UNKNOWN_MACHINE = "UNKNOWN_MACHINE"
    DUPLICATE_PLACEMENT = "DUPLICATE_PLACEMENT"


# Violation / result

class ConstraintViolation(BaseModel):
    """One concrete, explicit constraint failure (or warning)."""

    model_config = {"frozen": True}

    violation_type: ConstraintType
    severity: ConstraintSeverity
    message: str = Field(..., description="Human-readable explanation")

    machine_ids: list[str] = Field(default_factory=list, description="Machine(s) involved, sorted")
    zone_ids: list[str] = Field(default_factory=list, description="Zone(s) involved, sorted")

    details: dict[str, float] | None = Field(
        None, description="Optional numeric geometry details (e.g. overlap magnitude)"
    )


class LayoutValidationResult(BaseModel):
    """Full output of one layout validation run."""

    model_config = {"frozen": True}

    valid: bool
    error_count: int = Field(..., ge=0)
    warning_count: int = Field(..., ge=0)
    violations: list[ConstraintViolation] = Field(default_factory=list)
