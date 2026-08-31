"""Requirements-agent domain models for Fabrivium Phase 5A."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.models.optimization import OptimizationObjective


# Enums

class ParserType(str, Enum):
    """Which backend produced a ``RequirementsParseResult`` — always
    recorded, so agent traces can distinguish a network-free deterministic
    parse from an LLM-backed one."""

    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    LLM = "LLM"


# PlanningRequirements

class PlanningRequirements(BaseModel):
    """
    A validated, typed description of what a user asked for — reusing
    ``OptimizationObjective`` from Phase 4A rather than inventing a parallel enum.
    """

    model_config = {"frozen": True}

    objective: OptimizationObjective

    target_units_per_day: float | None = Field(None, gt=0.0)
    max_capex: float | None = Field(None, ge=0.0)
    max_additional_machines: int | None = Field(None, ge=0)
    max_additional_operators: int | None = Field(
        None, ge=0,
        description="Cap on how many operators may be hired. Phase 8A changes TOTAL headcount only — no skills, rosters or named staff.",
    )
    max_floor_area: float | None = Field(None, ge=0.0)
    allowed_action_types: list[str] | None = Field(
        None,
        description=(
            "Restrict planning to these action types; null = no restriction. Use it to honour a "
            "request like 'do not buy another machine' or 'solve it with an extra shift instead'. "
            "Valid values ONLY: ADD_PARALLEL_MACHINE, CHANGE_MACHINE_CAPACITY, "
            "CHANGE_MACHINE_CYCLE_TIME, CHANGE_SHIFT_CONFIGURATION, CHANGE_OPERATOR_CAPACITY, "
            "CHANGE_BUFFER_CAPACITY, CHANGE_DEMAND, REMOVE_MACHINE. Never invent another value — "
            "an unrecognised one matches no candidate and blocks all planning."
        ),
    )
    forbidden_machine_ids: list[str] = Field(
        default_factory=list, description="Machine IDs the optimizer must never modify or clone"
    )
    preserve_existing_layout: bool = Field(
        False, description="If True, no new machine placement should be introduced (not yet enforced by Phase 4 — see mapping docs)"
    )
    notes: list[str] = Field(default_factory=list, description="Free-text fragments the parser could not map to a typed field")

    confidence: float = Field(
        1.0, ge=0.0, le=1.0,
        description="Parser's own confidence in this parse; 1.0 for exact deterministic matches, lower for guesses"
    )
    parse_warnings: list[str] = Field(
        default_factory=list, description="Contradictions or ambiguities detected during parsing — never silently dropped"
    )

    # Phase 8B: SOFT strategy preferences The distinction from the hard constraints
    # above is the whole point (Phase 8B section 13).
    prefer_no_new_machines: bool = Field(
        False, description="Soft: rank options needing no new equipment first. Never forbids equipment."
    )
    prefer_low_known_capex: bool = Field(
        False, description="Soft: rank lower known CAPEX first. Never treats an unknown cost as low."
    )
    prefer_few_changes: bool = Field(
        False, description="Soft: rank options with fewer accepted interventions first."
    )
    allowed_strategy_families: list[str] | None = Field(
        None,
        description=(
            "Restrict exploration to these OptimizationStrategyFamily values; null = explore all. "
            "This IS a hard restriction on which families are explored, unlike the prefer_* flags."
        ),
    )
    # No `prefer_existing_layout`, though section 13 lists one.


# RequirementsParseResult — audit trail

class RequirementsParseResult(BaseModel):
    """Full audit record of one parse — everything an agent trace needs to
    show a user (or a debugger) exactly what was understood, by which
    backend, and how confidently."""

    model_config = {"frozen": True}

    raw_user_request: str
    parsed_requirements: PlanningRequirements
    warnings: list[str] = Field(default_factory=list)
    parser_type: ParserType
    structured_output_valid: bool = Field(
        ..., description="False iff the backend's raw output failed PlanningRequirements validation (LLM backend only)"
    )


# Compact factory context for LLM use (Phase 5A section 6)

class FactoryContextProduct(BaseModel):
    model_config = {"frozen": True}
    id: str
    name: str
    demand_per_day: float


class FactoryContextMachine(BaseModel):
    model_config = {"frozen": True}
    id: str
    name: str
    process_type: str
    cycle_time: float
    capacity: int
    # None when the machine has no recorded price.
    purchase_cost: float | None = None


class FactoryContextSimulationSummary(BaseModel):
    model_config = {"frozen": True}
    product_id: str
    completed_units: int
    target_units: int
    demand_met: bool
    bottleneck_machine_id: str


class FactoryContext(BaseModel):
    """A compact, deterministic summary of a Factory for LLM consumption —
    deliberately NOT the full raw Factory JSON (Phase 5A section 6).
    """

    model_config = {"frozen": True}

    factory_name: str
    products: list[FactoryContextProduct]
    machines: list[FactoryContextMachine]
    layout_available: bool
    simulation_summary: FactoryContextSimulationSummary | None = None
