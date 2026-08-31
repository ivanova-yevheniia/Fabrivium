"""Equipment discovery — Phase 16."""

from __future__ import annotations

from datetime import date

from app.models.concept import ConceptStage, FactoryConceptDraft, SourcedFloat, SourcedInt, ValueSource
from app.models.equipment_discovery import (
    CatalogKind,
    DataFreshness,
    EquipmentCandidate,
    EquipmentCapability,
    EquipmentRequirement,
    EquipmentSelection,
    ParameterChange,
)
from app.services.equipment_catalog import (
    CatalogSearchResult,
    EquipmentCatalogRegistry,
    default_registry,
)

# The ONE place a process name becomes a capability.
CAPABILITY_BY_PROCESS_TYPE: dict[str, EquipmentCapability] = {
    "screwdriving": EquipmentCapability.SCREW_FASTENING,
    "inspection": EquipmentCapability.VISUAL_INSPECTION,
    "labelling": EquipmentCapability.LABEL_APPLICATION,
    "labeling": EquipmentCapability.LABEL_APPLICATION,
    "marking": EquipmentCapability.LABEL_APPLICATION,
}

# What the equipment has to accomplish, in words an engineer would use with a vendor.
CAPABILITY_STATEMENTS: dict[EquipmentCapability, str] = {
    EquipmentCapability.SCREW_FASTENING: (
        "Drive and control threaded fasteners into the product at this station's rate."
    ),
    EquipmentCapability.VISUAL_INSPECTION: (
        "Acquire an image of the product at this station and decide pass or fail from it."
    ),
    EquipmentCapability.LABEL_APPLICATION: (
        "Print and/or apply a label or mark onto the product at this station's rate."
    ),
}
assert set(CAPABILITY_STATEMENTS) == set(EquipmentCapability), (
    "every EquipmentCapability needs a statement an engineer can take to a vendor"
)

# Fields whose adoption would change what the simulator computes.
SIMULATION_PARAMETERS = frozenset({"cycle_time", "capacity", "operators_required"})


class UnknownStationError(ValueError):
    """The concept has no such stage. Never silently substituted."""


# 1. Requirement derivation

def capability_for(process_type: str) -> EquipmentCapability | None:
    """The capability a station of this process type needs, or None."""
    return CAPABILITY_BY_PROCESS_TYPE.get(process_type.strip().lower())


def requirement_from_concept(
    draft: FactoryConceptDraft,
    station_id: str,
    *,
    strategy_context: str | None = None,
    derived_cycle_time_limit: SourcedFloat | None = None,
    station_context: dict | None = None,
) -> EquipmentRequirement:
    """Build the requirement for one station out of the concept draft."""
    stage = next((s for s in draft.stages if s.id == station_id), None)
    if stage is None:
        known = ", ".join(s.id for s in draft.stages) or "none"
        raise UnknownStationError(
            f"The concept has no stage '{station_id}'. Stages present: {known}."
        )

    context = station_context or {}
    capability = capability_for(stage.process_type)

    return EquipmentRequirement(
        station_id=stage.id,
        station_name=stage.name,
        process_category=stage.process_type,
        required_capability=capability,
        capability_statement=(
            CAPABILITY_STATEMENTS[capability] if capability is not None else ""
        ),
        # The equipment has to keep up with the station, so the concept's
        # cycle time is an upper bound on the equipment's — unless a
        # simulated threshold has established a stricter, better-founded one.
        max_cycle_time_seconds=(
            derived_cycle_time_limit
            if derived_cycle_time_limit is not None and derived_cycle_time_limit.known
            else stage.cycle_time
        ),
        required_capacity=stage.capacity,
        operator_requirement=stage.operators_required,
        operations_per_unit=_operations_per_unit(context),
        max_width_m=stage.width,
        max_length_m=stage.length,
        # Concept layouts have no height, and inventing a ceiling would
        # produce FAILs against real equipment for no reason.
        max_height_m=SourcedFloat.unknown(),
        # Nothing in a concept establishes how heavy a product is.
        max_payload_kg=SourcedFloat.unknown(),
        part_dimensions_text=_part_dimensions(context),
        part_dimensions_provenance=(
            "Quoted from the product source document, via the product understanding."
            if _part_dimensions(context)
            else None
        ),
        budget_limit=stage.purchase_cost,
        # Never inferred from the process type — see the interface check.
        required_interfaces=[],
        optional_preferences=_preferences(draft),
        strategy_context=strategy_context,
        provenance=_describe_provenance(stage, derived_cycle_time_limit),
    )


def _operations_per_unit(context: dict) -> SourcedInt:
    """How many times this station performs its operation, per unit."""
    repeats = context.get("repeated_operations")
    if not isinstance(repeats, int) or repeats <= 0:
        return SourcedInt.unknown()
    operation = context.get("operation") or "this operation"
    return SourcedInt.of(
        repeats,
        ValueSource.DOCUMENT,
        f"{repeats} x '{operation}' per unit, from the product source document",
    )


def _part_dimensions(context: dict) -> str | None:
    """The product's overall dimensions, quoted rather than parsed."""
    value = context.get("product_dimensions")
    return str(value) if value else None


def _preferences(draft: FactoryConceptDraft) -> list[str]:
    """Soft preferences, recorded and displayed but never scored."""
    preferences: list[str] = []
    if draft.prefer_no_new_machines:
        preferences.append("Customer would prefer not to buy unnecessary equipment")
    return preferences


def _describe_provenance(stage: ConceptStage, derived_limit: SourcedFloat | None = None) -> str:
    """One sentence naming where the bounds came from."""
    sources = {
        value.source
        for value in (stage.cycle_time, stage.capacity, stage.operators_required, stage.purchase_cost)
        if value.known
    }
    if not sources:
        return f"Derived from the '{stage.name}' stage, which has no engineering values yet."

    # EVERY member of ValueSource, deliberately.
    names = {
        ValueSource.CUSTOMER: "the customer brief",
        ValueSource.EXAMPLE_DATA: "the bundled example dataset",
        ValueSource.CATALOG_DEFAULT: "a catalog default",
        ValueSource.CALCULATED: "a calculated concept value",
        ValueSource.MANUFACTURER: "a manufacturer's published specification",
        ValueSource.ENGINEERING_ESTIMATE: "an engineering estimate",
        ValueSource.ENGINEER: "a value the engineer entered",
        ValueSource.DOCUMENT: "a supplied document",
        ValueSource.MEASURED: "a measurement from a real line",
        ValueSource.EXTERNAL_DATA: "an external catalog or price list",
        ValueSource.SIMULATED: "a Fabrivium simulation run",
        ValueSource.UNKNOWN: "a value that is still unknown",
    }
    assert set(names) == set(ValueSource), "every ValueSource needs a human-readable phrase"
    listed = sorted(names[s] for s in sources)
    joined = listed[0] if len(listed) == 1 else ", ".join(listed[:-1]) + " and " + listed[-1]
    base = f"Derived from the '{stage.name}' stage of this concept; its values come from {joined}."
    if derived_limit is not None and derived_limit.known:
        # Say plainly that the cycle bound is no longer the concept's own
        # number — an engineer comparing this against a datasheet needs to
        # know which question the bound answers.
        base += (
            f" The cycle-time limit is not the stage's own value but a requirement Fabrivium"
            f" derived by simulation: {derived_limit.detail or 'simulated threshold'}."
        )
    return base


# 2. Candidates — asked of every registered catalogue

def search_catalogs(
    requirement: EquipmentRequirement,
    *,
    registry: EquipmentCatalogRegistry | None = None,
) -> CatalogSearchResult:
    """Ask every catalogue for records declaring the required capability."""
    return (registry or default_registry()).search(requirement.required_capability)


def load_cached_candidates(
    process_category: str,
) -> tuple[list[EquipmentCandidate], date | None]:
    """The researched manufacturer dataset for one process category."""
    capability = capability_for(process_category)
    if capability is None:
        return [], None

    result = default_registry().search(capability)
    researched = [
        response
        for response in result.consulted
        if response.descriptor.kind is CatalogKind.RESEARCHED_MANUFACTURER
    ]
    candidates = [c for response in researched for c in response.candidates]
    dates = [r.verified_on for r in researched if r.verified_on is not None]
    return candidates, (min(dates) if dates else None)


def source_backed_only(candidates: list[EquipmentCandidate]) -> list[EquipmentCandidate]:
    """Drop anything that cannot cite a document."""
    return [c for c in candidates if c.source_backed]


# 3. Selection

def select_candidate(
    requirement: EquipmentRequirement,
    candidate: EquipmentCandidate,
    *,
    freshness: DataFreshness = DataFreshness.CACHED,
) -> EquipmentSelection:
    """Record a choice. Changes nothing the simulator reads."""
    source = candidate.primary_source
    return EquipmentSelection(
        station_id=requirement.station_id,
        candidate_id=candidate.candidate_id,
        manufacturer=candidate.manufacturer,
        model=candidate.model,
        source_url=source.url if source else None,
        selected_from=freshness,
        adopted_parameters=[],
    )


def proposed_parameter_changes(
    requirement: EquipmentRequirement,
    candidate: EquipmentCandidate,
    stage: ConceptStage,
) -> list[ParameterChange]:
    """What COULD be adopted from this manufacturer, itemised for review."""
    changes: list[ParameterChange] = []

    for field, label, current, spec, unit in (
        ("cycle_time", "Cycle time", stage.cycle_time, candidate.cycle_time_seconds, "s"),
        ("capacity", "Capacity", stage.capacity, candidate.capacity, ""),
        ("operators_required", "Operators", stage.operators_required, candidate.operators_required, ""),
    ):
        if spec.value is None:
            continue
        if current.known and float(current.value or 0.0) == float(spec.value):
            continue
        changes.append(
            ParameterChange(
                field=field,
                label=label,
                current_value=float(current.value) if current.known else None,
                current_source=current.source,
                proposed_value=float(spec.value),
                proposed_unit=unit,
                proposed_source_url=_source_url(candidate, spec.source_id),
                affects_simulation=field in SIMULATION_PARAMETERS,
            )
        )

    # FOOTPRINT IS DELIBERATELY NOT PROPOSED.

    return changes


def _source_url(candidate: EquipmentCandidate, source_id: str | None) -> str | None:
    if not source_id:
        return None
    return next((s.url for s in candidate.sources if s.source_id == source_id), None)


def adopt_parameters(
    stage: ConceptStage,
    changes: list[ParameterChange],
    approved_fields: list[str],
) -> tuple[ConceptStage, list[ParameterChange]]:
    """Apply ONLY the changes the engineer named, and say which were applied."""
    approved = set(approved_fields)
    applied = [c for c in changes if c.field in approved]
    if not applied:
        return stage, []

    updates: dict[str, object] = {}
    for change in applied:
        detail = f"Adopted from {change.proposed_source_url or 'the manufacturer'}"
        if change.field in ("capacity", "operators_required"):
            updates[change.field] = SourcedInt.of(int(change.proposed_value), ValueSource.MANUFACTURER, detail)
        else:
            updates[change.field] = SourcedFloat.of(change.proposed_value, ValueSource.MANUFACTURER, detail)

    return stage.model_copy(update=updates), applied
