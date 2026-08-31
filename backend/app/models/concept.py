"""Factory concept draft — Phase 13."""

from __future__ import annotations

from enum import Enum
from typing import Any
from typing import Annotated

from pydantic import BaseModel, Field

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


# Provenance

class ValueSource(str, Enum):
    """Where one concept value came from."""

    # Stated by the user/customer, in the brief or a later answer.
    CUSTOMER = "CUSTOMER"
    # Taken from a bundled, named example dataset (the demo line).
    EXAMPLE_DATA = "EXAMPLE_DATA"
    # A planning default from an approved catalog/table, e.g.
    CATALOG_DEFAULT = "CATALOG_DEFAULT"
    #: Derived deterministically from other known values by Fabrivium
    #: (never by a language model). This is the "DERIVED" category — the
    #: name predates Phase 18 and was left alone rather than renamed
    #: through every existing test and stored draft.
    CALCULATED = "CALCULATED"
    # Published by an equipment manufacturer in a cited document (Phase 16).
    MANUFACTURER = "MANUFACTURER"
    #: A preliminary engineering assumption produced with Fabrivium's
    #: help during concept design (Phase 18). Good enough to simulate a
    #: concept with; NEVER a specification, and never presentable as a
    #: customer fact or a manufacturer figure.
    ENGINEERING_ESTIMATE = "ENGINEERING_ESTIMATE"
    # Typed in by the engineer using Fabrivium.
    ENGINEER = "ENGINEER"
    DOCUMENT = "DOCUMENT"
    # Observed on a real line — a stopwatch study, an MES export.
    MEASURED = "MEASURED"
    # Supplied by a named external system: a company catalog, a supplier price list.
    EXTERNAL_DATA = "EXTERNAL_DATA"
    # Produced by running Fabrivium's own simulator.
    SIMULATED = "SIMULATED"
    # Not known yet. The value itself is None wherever this appears.
    UNKNOWN = "UNKNOWN"


class SourcedFloat(BaseModel):
    """A float that knows where it came from, and may legitimately be absent."""

    model_config = {"frozen": True}

    value: float | None = None
    source: ValueSource = ValueSource.UNKNOWN
    # Free-text attribution shown in the provenance view, e.g.
    detail: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None

    @staticmethod
    def unknown() -> "SourcedFloat":
        return SourcedFloat(value=None, source=ValueSource.UNKNOWN)

    @staticmethod
    def of(value: float, source: ValueSource, detail: str | None = None) -> "SourcedFloat":
        return SourcedFloat(value=value, source=source, detail=detail)


class SourcedInt(BaseModel):
    """Integer counterpart of :class:`SourcedFloat` (operators, capacity,
    shifts) — kept separate so a headcount can never arrive as 2.5."""

    model_config = {"frozen": True}

    value: int | None = None
    source: ValueSource = ValueSource.UNKNOWN
    detail: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None

    @staticmethod
    def unknown() -> "SourcedInt":
        return SourcedInt(value=None, source=ValueSource.UNKNOWN)

    @staticmethod
    def of(value: int, source: ValueSource, detail: str | None = None) -> "SourcedInt":
        return SourcedInt(value=value, source=source, detail=detail)


# Stages

class ConceptStage(BaseModel):
    """One process stage in the concept's route."""

    model_config = {"frozen": True}

    # Stable id used for the generated Machine and for route references.
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="e.g. 'Screwdriving'")
    #: Free text, matched by the existing asset resolver's substring aliases
    #: and falling back to a generic planning asset for anything unknown.
    process_type: str = Field(..., min_length=1)

    # Net processing time per unit, seconds.
    cycle_time: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    # Concurrent units the station can process.
    capacity: SourcedInt = Field(default_factory=SourcedInt.unknown)
    # Operators the station occupies while running.
    operators_required: SourcedInt = Field(default_factory=SourcedInt.unknown)

    # Planning footprint (m). Not a simulation input.
    width: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    length: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # Known equipment cost, if any.
    purchase_cost: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # Phase 18 — the range `cycle_time` was resolved from, when it came from an estimate
    # rather than a fact.
    cycle_time_estimate: Any | None = None

    # Phase 18 — why this stage's values changed, newest last.
    revisions: list[Any] = Field(default_factory=list)

    # G10/G11 — the reviewed manufacturing operation this stage was built from, when the
    # concept came from the product route.
    source_operation_id: str | None = None


class CellExecutionMode(str, Enum):
    """How the operations inside one group are performed on the resource."""

    # The resource performs the grouped operations one after another.
    SEQUENTIAL = "SEQUENTIAL"


class ConceptOperationGroup(BaseModel):
    """Several operations performed by ONE physical resource."""

    model_config = {"frozen": True}

    #: Stable id. Becomes the generated Machine's id, so it must not collide
    #: with a stage id.
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="e.g. 'Assembly cell'")

    # The stages this resource performs, in route order.
    stage_ids: list[str] = Field(..., min_length=1)

    execution_mode: CellExecutionMode = CellExecutionMode.SEQUENTIAL

    # Why the engineer grouped these.
    basis: str = Field("", description="The engineer's reason for this grouping.")


class ConceptBuffer(BaseModel):
    """Intermediate storage between two consecutive stages."""

    model_config = {"frozen": True}

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    upstream_stage_id: str = Field(..., min_length=1)
    downstream_stage_id: str = Field(..., min_length=1)
    capacity: SourcedInt = Field(default_factory=SourcedInt.unknown)


# The draft

class FactoryConceptDraft(BaseModel):
    """A factory concept that may still be incomplete."""

    # Human-readable concept name, used as the generated Factory's name.
    name: str = Field("New factory concept", min_length=1)

    # The customer's own words, kept verbatim for the provenance view.
    customer_brief: str = Field("", description="The brief this concept was built from, unmodified.")

    # What the line has to produce (units/day).
    production_target: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    product_name: str = Field("Product", min_length=1)

    # Ordered route.
    stages: list[ConceptStage] = Field(default_factory=list)

    buffers: list[ConceptBuffer] = Field(default_factory=list)

    #: Engineer-defined production architecture: which stages share one
    #: physical resource. EMPTY IS THE DEFAULT AND MEANS "one operation, one
    #: station" — every existing concept keeps exactly the behaviour it had,
    #: and a concept that has never been grouped is not silently a cell.
    operation_groups: list[ConceptOperationGroup] = Field(default_factory=list)

    def group_for_stage(self, stage_id: str) -> ConceptOperationGroup | None:
        for group in self.operation_groups:
            if stage_id in group.stage_ids:
                return group
        return None

    def ungrouped_stage_ids(self) -> list[str]:
        """Stages that are still their own station, in route order."""
        grouped = {sid for group in self.operation_groups for sid in group.stage_ids}
        return [s.id for s in self.stages if s.id not in grouped]

    # Operating schedule: production physics, never defaulted
    shifts_per_day: SourcedInt = Field(default_factory=SourcedInt.unknown)
    hours_per_shift: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # Workforce: a real shared pool since Phase 8A
    operators_available: SourcedInt = Field(default_factory=SourcedInt.unknown)

    # Building: layout only, never a simulation input
    floor_width: SourcedFloat = Field(default_factory=SourcedFloat.unknown)
    floor_length: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    # Capital budget, if the customer stated one.
    budget: SourcedFloat = Field(default_factory=SourcedFloat.unknown)

    #: Soft preferences captured from the brief, carried through to the
    #: optimization request rather than enforced here.
    prefer_no_new_machines: bool = False

    def stage_by_id(self, stage_id: str) -> ConceptStage | None:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        return None
