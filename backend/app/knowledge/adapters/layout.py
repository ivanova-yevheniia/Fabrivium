"""
Layout knowledge — placement and floor-space rules, and the planning
defaults that stand in for equipment nobody has chosen yet.

CANONICAL SOURCES
-----------------
``app.services.concept_validation`` for the planning defaults, and
``app.models.constraints`` / ``app.services.constraints`` for the constraint
policy.

THE ARCHITECTURAL RULE THIS CATEGORY RESTS ON
---------------------------------------------
Layout never feeds simulation mathematics. The simulator reads no dimension,
no coordinate and no clearance, which is why a nominal station footprint can
exist as a disclosed planning default without any risk of it moving a
throughput figure. That rule is the reason the defaults below are allowed to
exist at all, so it is published as a knowledge item in its own right.

WHY THE ERROR/WARNING POLICY IS A POINTER
-----------------------------------------
Which constraint is an ERROR and which is a WARNING is decided per case
inside ``validate_layout`` — a machine footprint outside the floor is an
ERROR, its safety envelope alone extending outside is a WARNING. Restating
those pairings here would be a copy of a policy that lives in branches, and
the copy would go stale silently. What IS derived is the vocabulary: the
constraint types and severities, read live from the enums.
"""

from __future__ import annotations

from app.knowledge.contract import (
    Applicability,
    EngineeringKnowledgeItem,
    KnowledgeCategory,
    KnowledgeDomain,
    KnowledgeExposure,
    KnowledgeKind,
    Provenance,
    SourceKind,
)

LAYOUT_ADAPTER_VERSION = "1.0.0"

_VALIDATION_MODULE = "app.services.concept_validation"


def layout_knowledge() -> list[EngineeringKnowledgeItem]:
    """Planning defaults and the deterministic layout constraint vocabulary."""
    from app.models.constraints import ConstraintSeverity, ConstraintType
    from app.services.concept_validation import (
        DEFAULT_BUFFER_CAPACITY,
        DEFAULT_STATION_CAPACITY,
        DEFAULT_STATION_LENGTH_M,
        DEFAULT_STATION_WIDTH_M,
    )

    items: list[EngineeringKnowledgeItem] = [
        EngineeringKnowledgeItem(
            id="layout.default_station_footprint",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Nominal planning footprint for a station with no chosen equipment",
            description=(
                f"{DEFAULT_STATION_WIDTH_M} m x {DEFAULT_STATION_LENGTH_M} m. A layout "
                f"figure only. It exists because the factory model requires a width and a "
                f"length to be constructed at all, and it is attributed as a catalogue "
                f"default and visible as one on the concept BEFORE conversion — so a "
                f"default can never be presented as something the customer said."
            ),
            provenance=Provenance(
                source_kind=SourceKind.REFERENCE_TABLE,
                source_reference=(
                    f"{_VALIDATION_MODULE}.DEFAULT_STATION_WIDTH_M / DEFAULT_STATION_LENGTH_M"
                ),
                statement="A disclosed planning default in Fabrivium's concept converter.",
                classification_vocabulary="ValueSource",
                classification="CATALOG_DEFAULT",
            ),
            applicability=Applicability(
                scope="Stations whose equipment has not been selected yet.",
                not_valid_for=(
                    "Any throughput figure. The simulator reads no dimension, so this "
                    "value cannot influence a KPI. It is also not a procurement figure."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={
                "width_m": DEFAULT_STATION_WIDTH_M,
                "length_m": DEFAULT_STATION_LENGTH_M,
            },
            status="CATALOG_DEFAULT",
            tags=("layout", "planning-default"),
        ),
        EngineeringKnowledgeItem(
            id="layout.default_station_capacity",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Default station capacity",
            description=(
                f"{DEFAULT_STATION_CAPACITY} — one unit at a time. This is the factory "
                f"model's own default, restated on the concept so its origin is visible "
                f"there rather than appearing silently at conversion."
            ),
            provenance=Provenance(
                source_kind=SourceKind.REFERENCE_TABLE,
                source_reference=f"{_VALIDATION_MODULE}.DEFAULT_STATION_CAPACITY",
                statement="A disclosed planning default in Fabrivium's concept converter.",
                classification_vocabulary="ValueSource",
                classification="CATALOG_DEFAULT",
            ),
            applicability=Applicability(
                scope="A station whose concurrency the engineer has not stated.",
                not_valid_for=(
                    "A station that genuinely processes several units at once. That is a "
                    "value the engineer states."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={"capacity": DEFAULT_STATION_CAPACITY},
            status="CATALOG_DEFAULT",
            tags=("layout", "planning-default"),
        ),
        EngineeringKnowledgeItem(
            id="layout.default_buffer_capacity",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Default buffer capacity when a size is not named",
            description=(
                f"{DEFAULT_BUFFER_CAPACITY} units. Applied only on an explicit action — "
                f"the engineer asking for buffers between stages without naming a size. "
                f"Never applied silently."
            ),
            provenance=Provenance(
                source_kind=SourceKind.REFERENCE_TABLE,
                source_reference=f"{_VALIDATION_MODULE}.DEFAULT_BUFFER_CAPACITY",
                statement="A disclosed planning default in Fabrivium's concept converter.",
                classification_vocabulary="ValueSource",
                classification="CATALOG_DEFAULT",
            ),
            applicability=Applicability(
                scope="An explicitly requested buffer with no stated size.",
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={"capacity_units": DEFAULT_BUFFER_CAPACITY},
            status="CATALOG_DEFAULT",
            tags=("layout", "planning-default", "buffer"),
        ),
        EngineeringKnowledgeItem(
            id="layout.constraint_policy",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Deterministic layout constraint checking",
            description=(
                "Placements are checked against a fixed set of constraint types, each "
                "reported at ERROR or WARNING. The severity for a given case is decided in "
                "the constraint engine — a machine footprint outside the floor is an error, "
                "its safety envelope alone extending outside is a warning — and is not "
                "restated here. The check is a pure function: it never mutates a layout and "
                "never touches simulation or scenario logic."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.constraints.validate_layout",
                statement=(
                    "The policy layer of Fabrivium's layout constraint engine. Rectangle "
                    "mathematics lives separately in app.services.geometry."
                ),
            ),
            applicability=Applicability(
                scope="Every factory layout Fabrivium validates.",
                not_valid_for=(
                    "Judging that a layout is buildable. It checks the geometric "
                    "constraints it holds, not material flow, services or ergonomics."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={
                "constraint_types": [c.value for c in ConstraintType],
                "severities": [s.value for s in ConstraintSeverity],
            },
            tags=("layout", "constraints", "deterministic"),
        ),
        EngineeringKnowledgeItem(
            id="layout.never_feeds_simulation",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Layout never feeds simulation mathematics",
            description=(
                "Placements, footprints and clearances have no bearing on what the "
                "simulator computes; it reads no dimension and no coordinate. The "
                "separation is architectural, not incidental, and it is what allows a "
                "disclosed planning footprint to exist without any risk of it moving a "
                "throughput figure."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.layout",
                statement=(
                    "An architectural rule stated on Fabrivium's factory model and enforced "
                    "by keeping layout logic out of the simulation service."
                ),
            ),
            applicability=Applicability(
                scope="Every layout operation and every simulation run.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("layout", "architecture", "separation"),
        ),
        EngineeringKnowledgeItem(
            id="layout.placement_search",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Placement search is deterministic, local and bounded",
            description=(
                "A newly added machine is placed by an expanding-ring search around a "
                "reference machine, falling back to a row-major scan of the floor, trying "
                "each rotation at each point and stopping at the first position that passes "
                "constraint validation with no errors. No randomness, no global "
                "rearrangement of existing placements, and a hard bound on attempts. It "
                "finds a valid position, not the best one, and does not claim otherwise."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.placement_search",
                statement="The search procedure implemented in Fabrivium's placement service.",
            ),
            applicability=Applicability(
                scope="Placing one newly added machine on an existing layout.",
                not_valid_for=(
                    "Layout optimisation. Rearranging a whole floor is a capability "
                    "Fabrivium does not have."
                ),
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("layout", "placement", "deterministic"),
        ),
        EngineeringKnowledgeItem(
            id="layout.geometry_conventions",
            version=LAYOUT_ADAPTER_VERSION,
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Coordinate and rotation conventions for the factory floor",
            description=(
                "A machine placement's x and y are the footprint's CENTRE; a layout zone's "
                "x and y are its lower-left corner. Rotation is counter-clockwise about the "
                "placement centre. Width is the left-right extent and length the front-back "
                "extent, and safety clearances expand the local rectangle before rotation, "
                "so an asymmetric envelope rotates with the machine. The conventions are "
                "stated once and never silently redefined."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.geometry",
                statement="The coordinate conventions Fabrivium's geometry module fixes.",
            ),
            applicability=Applicability(
                scope="Every placement, zone and clearance calculation.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("layout", "geometry", "conventions"),
        ),
    ]

    return items
