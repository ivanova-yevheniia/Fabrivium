"""Domain models for Fabrivium – Phase 0."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.equipment import EquipmentAsset, EquipmentLifecycleStatus


# Reusable annotated types

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


# MachineEnvelopeExtras (Phase 3A)

class MachineEnvelopeExtras(BaseModel):
    """
    Physical envelope properties NOT already captured by ``Machine``'s own
    ``width``/``length`` fields.
    """

    model_config = {"frozen": True}

    height: PositiveFloat | None = Field(None, description="Machine height (m)")
    safety_clearance_front: NonNegativeFloat = Field(0.0, description="Required clear space in front (m)")
    safety_clearance_back: NonNegativeFloat = Field(0.0, description="Required clear space behind (m)")
    safety_clearance_left: NonNegativeFloat = Field(0.0, description="Required clear space to the left (m)")
    safety_clearance_right: NonNegativeFloat = Field(0.0, description="Required clear space to the right (m)")


# ProcessStep

class ProcessStep(BaseModel):
    """A single operation within a product's manufacturing route."""

    model_config = {"frozen": True}

    name: str = Field(..., min_length=1, description="Step name, e.g. 'Assembly'")
    machine_id: str = Field(..., min_length=1, description="ID of the machine that performs this step")
    cycle_time: PositiveFloat = Field(..., description="Net processing time per unit (seconds)")


# Machine

class Machine(BaseModel):
    """A physical production machine on the factory floor."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    process_type: str = Field(..., min_length=1, description="E.g. 'assembly', 'welding'")

    # Timing (seconds unless noted)
    cycle_time: PositiveFloat = Field(..., description="Processing time per unit (s)")
    setup_time: NonNegativeFloat = Field(0.0, description="Changeover time (s)")

    # Operational
    capacity: PositiveInt = Field(1, description="Max concurrent units in process")
    failure_rate: NonNegativeFloat = Field(0.0, description="Failures per operating hour")
    mean_repair_time: NonNegativeFloat = Field(0.0, description="Average repair duration (hours)")
    operators_required: NonNegativeInt = Field(0, description="Operators needed to run this machine")

    # Financial NULLABLE ON PURPOSE.
    purchase_cost: NonNegativeFloat | None = Field(
        None, description="Capital expenditure (currency units); None = not priced"
    )

    # Layout (metres)
    position_x: float = Field(0.0, description="Centre X on factory floor (m)")
    position_y: float = Field(0.0, description="Centre Y on factory floor (m)")
    width: PositiveFloat = Field(..., description="Machine width (m)")
    length: PositiveFloat = Field(..., description="Machine length (m)")

    # Service-pool metadata (Phase 2B)
    parallel_of_machine_id: str | None = Field(
        None,
        description=(
            "If set, this machine is a scenario-created parallel clone that "
            "serves the same logical process step as the machine with this "
            "ID. Used by app.services.machine_pool to resolve deterministic "
            "machine service pools for simulation dispatch. None for a "
            "normal, non-cloned machine."
        ),
    )

    # Layout / equipment metadata (Phase 3A) ARCHITECTURAL RULE:

    asset: EquipmentAsset | None = Field(
        None,
        description=(
            "Visual/CAD asset metadata (Phase 3A). None means no asset has "
            "been recorded at all — this is always valid for simulation, "
            "scenarios, and layout planning; see create_proxy_asset for the "
            "'we know the dimensions but have no CAD model' case."
        ),
    )
    lifecycle_status: EquipmentLifecycleStatus = Field(
        EquipmentLifecycleStatus.EXISTING,
        description=(
            "Procurement/installation lifecycle stage (Phase 3A). Pure "
            "planning metadata — never affects simulation. Defaults to "
            "EXISTING, matching every machine defined before Phase 3A, so "
            "old Factory JSON continues to validate unmodified."
        ),
    )
    physical_envelope: MachineEnvelopeExtras | None = Field(
        None,
        description=(
            "Physical envelope details beyond width/length (Phase 3A): "
            "height and safety clearances. None means no extra envelope "
            "data has been recorded — 2D floor planning with width/length "
            "alone is still fully valid. See MachineEnvelopeExtras for why "
            "width/length are not duplicated here."
        ),
    )


# Product

class Product(BaseModel):
    """A finished good manufactured in this factory."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    demand_per_day: PositiveFloat = Field(..., description="Required daily output (units/day)")
    route: list[ProcessStep] = Field(..., min_length=1, description="Ordered manufacturing route")


# Buffer

class Buffer(BaseModel):
    """An in-process inventory buffer between two workstations."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    capacity: PositiveInt = Field(
        ...,
        description=(
            "Maximum units the buffer can hold at once. Always >= 1 — 'no intermediate "
            "storage' is expressed by having no buffer between two stages, not by a "
            "zero-capacity one, so this field's long-standing positive-integer contract "
            "is preserved rather than widened (Phase 8A section 13)."
        ),
    )
    upstream_machine_id: str | None = Field(
        None,
        description="Route stage that FEEDS this buffer. None = the buffer is not wired into any route and has no simulation effect.",
    )
    downstream_machine_id: str | None = Field(
        None,
        description="Route stage that DRAWS from this buffer. None = the buffer is not wired into any route and has no simulation effect.",
    )
    position_x: float = Field(0.0)
    position_y: float = Field(0.0)

    @property
    def is_wired(self) -> bool:
        """True when this buffer sits explicitly between two named stages
        and therefore participates in the simulation."""
        return self.upstream_machine_id is not None and self.downstream_machine_id is not None


# Factory

class Factory(BaseModel):
    """Top-level factory configuration."""

    name: str = Field(..., min_length=1)

    # Physical dimensions (metres)
    width: PositiveFloat = Field(..., description="Factory floor width (m)")
    length: PositiveFloat = Field(..., description="Factory floor length (m)")

    # Operational schedule
    shifts_per_day: PositiveInt = Field(..., description="Number of production shifts per day")
    hours_per_shift: PositiveFloat = Field(..., description="Working hours per shift")

    # Resources
    operators_available: NonNegativeInt = Field(
        ...,
        description=(
            "Total operators available SIMULTANEOUSLY — the size of the shared workforce "
            "pool the simulation enforces (Phase 8A section 6). Before Phase 8A this was "
            "metadata only and its wording said 'across all shifts'; it is now a real "
            "constraint, so the wording is corrected to match what it actually means."
        ),
    )
    # None = no capital budget has been set.
    budget: NonNegativeFloat | None = Field(
        None, description="Capital budget (currency units); None = not set"
    )

    # Children
    machines: list[Machine] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    buffers: list[Buffer] = Field(default_factory=list)

    # Cross-field validators

    @model_validator(mode="after")
    def _unique_machine_ids(self) -> "Factory":
        ids = [m.id for m in self.machines]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for mid in ids:
            if mid in seen:
                duplicates.add(mid)
            seen.add(mid)
        if duplicates:
            raise ValueError(
                f"Duplicate machine ID(s) detected: {sorted(duplicates)}"
            )
        return self

    @model_validator(mode="after")
    def _unique_product_ids(self) -> "Factory":
        ids = [p.id for p in self.products]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for pid in ids:
            if pid in seen:
                duplicates.add(pid)
            seen.add(pid)
        if duplicates:
            raise ValueError(
                f"Duplicate product ID(s) detected: {sorted(duplicates)}"
            )
        return self

    @model_validator(mode="after")
    def _unique_buffer_ids(self) -> "Factory":
        ids = [b.id for b in self.buffers]
        seen: set[str] = set()
        duplicates: set[str] = set()
        for bid in ids:
            if bid in seen:
                duplicates.add(bid)
            seen.add(bid)
        if duplicates:
            raise ValueError(
                f"Duplicate buffer ID(s) detected: {sorted(duplicates)}"
            )
        return self

    @model_validator(mode="after")
    def _cycle_times_agree(self) -> "Factory":
        """A route step and its machine must state the same cycle time."""
        by_id = {m.id: m for m in self.machines}
        for product in self.products:
            for step in product.route:
                machine = by_id.get(step.machine_id)
                if machine is None:
                    continue  # referential integrity is checked elsewhere
                if step.cycle_time != machine.cycle_time:
                    raise ValueError(
                        f"Cycle time disagrees for '{step.machine_id}': the route step "
                        f"states {step.cycle_time} s and the machine states "
                        f"{machine.cycle_time} s. The simulator reads the route value, "
                        f"so the machine value would be silently ignored. Set both, or "
                        f"change the route step."
                    )
        return self

    @field_validator("machines", mode="before")
    @classmethod
    def _machines_not_none(cls, v: object) -> object:
        return v if v is not None else []
