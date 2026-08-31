"""A Fabrivium project — the unit of work that survives closing the browser."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# Bumped when a stored project can no longer be read by this code.
PROJECT_SCHEMA_VERSION = 1


class Channel(str, Enum):
    """One independently-versioned family of project inputs."""

    # The source text or document the product facts were read from.
    PRODUCT_SOURCE = "PRODUCT_SOURCE"
    # The extracted product facts themselves.
    PRODUCT_FACTS = "PRODUCT_FACTS"
    #: The manufacturing route: which operations, in what order, what each
    #: one is and how many times it happens per unit.
    PROCESS = "PROCESS"
    # Which source requirement each operation is recorded as answering.
    COVERAGE_LINKS = "COVERAGE_LINKS"
    #: Everything the deterministic simulator actually reads: stage cycle
    #: time, capacity and operator demand, buffer sizes, the production
    #: target, the shift pattern and the available workforce.
    SIMULATION_INPUTS = "SIMULATION_INPUTS"
    # Money.
    COMMERCIAL = "COMMERCIAL"
    # Station placement and rotation. Checked for validity, never for speed.
    LAYOUT = "LAYOUT"
    # Equipment recorded as under consideration for a station.
    EQUIPMENT = "EQUIPMENT"


class Artifact(str, Enum):
    """Something Fabrivium produced and may show as evidence."""

    PRODUCT_FACTS = "PRODUCT_FACTS"
    PROCESS_PROPOSAL = "PROCESS_PROPOSAL"
    REQUIREMENT_COVERAGE = "REQUIREMENT_COVERAGE"
    CONCEPT = "CONCEPT"
    SIMULATION_VERIFICATION = "SIMULATION_VERIFICATION"
    STRATEGIES = "STRATEGIES"
    SELECTED_PLAN = "SELECTED_PLAN"
    EQUIPMENT_REQUIREMENTS = "EQUIPMENT_REQUIREMENTS"
    COMMERCIAL_COMPARISON = "COMMERCIAL_COMPARISON"
    LAYOUT_VALIDATION = "LAYOUT_VALIDATION"
    SIEMENS_HANDOFF = "SIEMENS_HANDOFF"


# Which input channels each artifact reads directly.
ARTIFACT_CHANNELS: dict[Artifact, frozenset[Channel]] = {
    Artifact.PRODUCT_FACTS: frozenset({Channel.PRODUCT_SOURCE}),
    Artifact.PROCESS_PROPOSAL: frozenset({Channel.PRODUCT_FACTS}),
    Artifact.REQUIREMENT_COVERAGE: frozenset({Channel.PROCESS, Channel.COVERAGE_LINKS}),
    Artifact.CONCEPT: frozenset({Channel.PROCESS}),
    Artifact.SIMULATION_VERIFICATION: frozenset({Channel.SIMULATION_INPUTS}),
    Artifact.STRATEGIES: frozenset({Channel.SIMULATION_INPUTS}),
    Artifact.SELECTED_PLAN: frozenset({Channel.SIMULATION_INPUTS}),
    Artifact.EQUIPMENT_REQUIREMENTS: frozenset({Channel.SIMULATION_INPUTS}),
    Artifact.COMMERCIAL_COMPARISON: frozenset({Channel.COMMERCIAL, Channel.EQUIPMENT}),
    Artifact.LAYOUT_VALIDATION: frozenset({Channel.LAYOUT, Channel.PROCESS}),
    Artifact.SIEMENS_HANDOFF: frozenset(
        {Channel.SIMULATION_INPUTS, Channel.LAYOUT, Channel.EQUIPMENT}
    ),
}

# Which artifacts each artifact was built on top of.
ARTIFACT_PARENTS: dict[Artifact, tuple[Artifact, ...]] = {
    Artifact.PROCESS_PROPOSAL: (Artifact.PRODUCT_FACTS,),
    Artifact.REQUIREMENT_COVERAGE: (Artifact.PROCESS_PROPOSAL,),
    Artifact.CONCEPT: (Artifact.PROCESS_PROPOSAL,),
    Artifact.SIMULATION_VERIFICATION: (Artifact.CONCEPT,),
    Artifact.STRATEGIES: (Artifact.SIMULATION_VERIFICATION,),
    Artifact.SELECTED_PLAN: (Artifact.STRATEGIES,),
    Artifact.EQUIPMENT_REQUIREMENTS: (Artifact.SIMULATION_VERIFICATION,),
    Artifact.COMMERCIAL_COMPARISON: (Artifact.SELECTED_PLAN,),
    Artifact.LAYOUT_VALIDATION: (Artifact.CONCEPT,),
    Artifact.SIEMENS_HANDOFF: (Artifact.SELECTED_PLAN, Artifact.LAYOUT_VALIDATION),
}


# Stored state

class ProductSlice(BaseModel):
    """What is being manufactured, and what Fabrivium read about it."""

    # Empty for a new manual project.
    name: str = ""
    # The engineer's own description, or the text of the uploaded document.
    description: str = ""
    #: True only when the description came from the bundled example
    #: specification, loaded on an explicit click. Kept so the UI can keep
    #: saying "example", which is what stops it reading as a customer file.
    from_example: bool = False
    # ProductUnderstanding as the /product/describe endpoint returned it.
    understanding: dict[str, Any] | None = None
    understanding_model_used: bool = False


class ProcessSlice(BaseModel):
    """The reviewed manufacturing route."""

    # ManufacturingProcessDraft as the endpoints exchange it.
    draft: dict[str, Any] | None = None
    #: The last CoverageReport, kept so reopening a project shows the same
    #: unresolved requirements it was left with.
    coverage: dict[str, Any] | None = None


class RequirementsSlice(BaseModel):
    """How much, in what space, with which workforce — the engineer's words."""

    text: str = ""


class ConceptSlice(BaseModel):
    """The concept draft and everything the verified core produced from it."""

    # FactoryConceptDraft.
    draft: dict[str, Any] | None = None
    # The Factory the concept was built into, its product id and layout.
    factory: dict[str, Any] | None = None
    product_id: str | None = None
    layout: dict[str, Any] | None = None
    # The draft the CURRENT verified results were computed from.
    verified_from: dict[str, Any] | None = None


class ResultsSlice(BaseModel):
    """Verified output. Large, and deliberately stored whole."""

    arena: dict[str, Any] | None = None
    selected_strategy_id: str | None = None
    explore_requests: list[str] = Field(default_factory=list)


class CommercialSlice(BaseModel):
    """Commercial facts the engineer ESTABLISHED. An input, not a result."""

    # ``UserCostInput`` objects as the backend produced them, at most one per gap type.
    established_costs: list[dict[str, Any]] = Field(default_factory=list)


class LayoutSlice(BaseModel):
    """Applied placement, per timeline stage."""

    applied: dict[str, Any] = Field(default_factory=dict)


class EquipmentSlice(BaseModel):
    """Equipment recorded as UNDER CONSIDERATION for a station."""

    selections: dict[str, dict[str, Any]] = Field(default_factory=dict)


class Stamp(BaseModel):
    """The channel revisions an artifact was produced at."""

    revisions: dict[str, int] = Field(default_factory=dict)

    def at(self, channel: Channel) -> int:
        return self.revisions.get(channel.value, 0)


class ChangeEntry(BaseModel):
    """One input change, in words an engineer can act on."""

    # Monotonic within a project.
    seq: int
    channel: str
    # The channel revision this change PRODUCED.
    revision: int = 0
    description: str


class ProjectState(BaseModel):
    """Everything a project remembers."""

    product: ProductSlice = Field(default_factory=ProductSlice)
    process: ProcessSlice = Field(default_factory=ProcessSlice)
    requirements: RequirementsSlice = Field(default_factory=RequirementsSlice)
    concept: ConceptSlice = Field(default_factory=ConceptSlice)
    results: ResultsSlice = Field(default_factory=ResultsSlice)
    # Established commercial facts.
    commercial: CommercialSlice = Field(default_factory=CommercialSlice)
    layout: LayoutSlice = Field(default_factory=LayoutSlice)
    equipment: EquipmentSlice = Field(default_factory=EquipmentSlice)
    # True for a project seeded from the bundled example specification.
    is_example: bool = False

    # Where in the workspace the engineer was.
    stage: str = "PRODUCT"

    # Server-owned revision bookkeeping Channel name -> revision.
    revisions: dict[str, int] = Field(default_factory=dict)
    # Artifact name -> the revisions it was produced at.
    evidence: dict[str, Stamp] = Field(default_factory=dict)
    # Change trail, oldest first, capped by the store.
    history: list[ChangeEntry] = Field(default_factory=list)
    # Artifacts the client produced since the last save.
    produced: list[str] = Field(default_factory=list)
    #: Artifacts the client explicitly discarded (a concept rebuilt from
    #: scratch, a handoff withdrawn). Cleared the same way.
    withdrawn: list[str] = Field(default_factory=list)


class ProjectDocument(BaseModel):
    """A stored project, exactly as it lives on disk."""

    schema_version: int = PROJECT_SCHEMA_VERSION
    project_id: str
    name: str
    created_at: str
    updated_at: str
    state: ProjectState = Field(default_factory=ProjectState)


class ProjectSummary(BaseModel):
    """One row of the recent-projects list."""

    project_id: str
    name: str
    created_at: str
    updated_at: str
    # The product the project is about, when it has one yet.
    product_name: str = ""
    #: True for the bundled example project, so the landing page can keep
    #: it visibly apart from an engineer's own work.
    is_example: bool = False


# Stale evidence

class ArtifactStatus(str, Enum):
    """The only four things the UI is allowed to say about evidence."""

    # Produced, and every input it depends on is unchanged since.
    CURRENT = "CURRENT"
    # Produced, but an input it depends on has moved. Must never render green.
    STALE = "STALE"
    # Never produced.
    UNVERIFIED = "UNVERIFIED"


class StaleArtifact(BaseModel):
    """One artifact that no longer answers the current inputs."""

    artifact: str
    status: str
    # Channels whose revision moved since this artifact was produced.
    changed_channels: list[str] = Field(default_factory=list)
    # Upstream artifacts that are themselves stale.
    stale_parents: list[str] = Field(default_factory=list)
    # The actual changes, newest last — "Cycle time (Screw fastening): 48 → 44".
    reasons: list[str] = Field(default_factory=list)
    # What the engineer has to do about it.
    action: str


class StaleReport(BaseModel):
    """Everything the UI needs to stop showing a green badge."""

    stale: list[StaleArtifact] = Field(default_factory=list)
    current: list[str] = Field(default_factory=list)
    unverified: list[str] = Field(default_factory=list)
    summary: str = "Nothing has been verified yet."

    def status_of(self, artifact: Artifact) -> ArtifactStatus:
        if any(item.artifact == artifact.value for item in self.stale):
            return ArtifactStatus.STALE
        if artifact.value in self.current:
            return ArtifactStatus.CURRENT
        return ArtifactStatus.UNVERIFIED


# What the engineer must do to make each artifact current again.
ARTIFACT_ACTION: dict[Artifact, str] = {
    Artifact.PRODUCT_FACTS: "Re-read the product specification",
    Artifact.PROCESS_PROPOSAL: "Propose the manufacturing process again",
    Artifact.REQUIREMENT_COVERAGE: "Recheck requirement coverage",
    Artifact.CONCEPT: "Rebuild the concept",
    Artifact.SIMULATION_VERIFICATION: "Re-run verification",
    Artifact.STRATEGIES: "Explore the options again",
    Artifact.SELECTED_PLAN: "Re-select a plan from re-explored options",
    Artifact.EQUIPMENT_REQUIREMENTS: "Recompute station requirements",
    Artifact.COMMERCIAL_COMPARISON: "Recompare the commercial options",
    Artifact.LAYOUT_VALIDATION: "Re-validate the layout",
    Artifact.SIEMENS_HANDOFF: "Export to Plant Simulation again",
}

ARTIFACT_LABEL: dict[Artifact, str] = {
    Artifact.PRODUCT_FACTS: "product facts",
    Artifact.PROCESS_PROPOSAL: "the proposed manufacturing process",
    Artifact.REQUIREMENT_COVERAGE: "requirement coverage",
    Artifact.CONCEPT: "the factory concept",
    Artifact.SIMULATION_VERIFICATION: "the verified simulation",
    Artifact.STRATEGIES: "the explored plans",
    Artifact.SELECTED_PLAN: "the selected plan",
    Artifact.EQUIPMENT_REQUIREMENTS: "station equipment requirements",
    Artifact.COMMERCIAL_COMPARISON: "the commercial comparison",
    Artifact.LAYOUT_VALIDATION: "layout validation",
    Artifact.SIEMENS_HANDOFF: "the Plant Simulation export",
}
