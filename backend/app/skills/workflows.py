"""Declared workflows — the product's paths, written down."""

from __future__ import annotations

from app.skills.orchestrator import WorkflowDefinition, WorkflowStage

# Product document -> understood product -> proposed process.
PRODUCT_TO_PROCESS = WorkflowDefinition(
    id="PRODUCT_TO_PROCESS",
    name="Product document to manufacturing process",
    description=(
        "Reads a supplied product document into structured facts, then proposes the "
        "manufacturing operations those facts imply. Every operation cites the fact and "
        "the sentence behind it. Stops at the proposal: acceptance is the engineer's."
    ),
    stages=(
        WorkflowStage(
            skill_id="product_understanding",
            payload=lambda bag: {
                "ingestion": bag.get("ingestion"),
                "product_name": bag.get("product_name", "Product"),
            },
            output_key="understanding",
        ),
        WorkflowStage(
            skill_id="process_planning",
            payload=lambda bag: {"understanding": bag.get("understanding")},
            output_key="process_draft",
        ),
    ),
)


# Customer brief -> concept draft -> runnable factory -> layout.
FACTORY_REQUIREMENTS_TO_CONCEPT = WorkflowDefinition(
    id="FACTORY_REQUIREMENTS_TO_CONCEPT",
    name="Requirements to simulation-ready concept",
    description=(
        "Structures a customer brief into a concept, converts it into the Factory model "
        "the simulator reads, and places the stations. Refuses to convert while a value "
        "the simulator needs is missing."
    ),
    stages=(
        WorkflowStage(
            skill_id="requirements_extraction",
            payload=lambda bag: {"brief": bag.get("brief")},
            output_key="draft",
        ),
        WorkflowStage(
            skill_id="factory_concept_builder",
            payload=lambda bag: {"draft": bag.get("draft")},
            output_key="factory_and_product",
        ),
        WorkflowStage(
            skill_id="layout_generation",
            # The DRAFT, not the converted factory: the layout generator
            # reads stage footprints and the floor envelope, which live on
            # the concept.
            payload=lambda bag: {"draft": bag.get("draft")} if bag.get("draft") else None,
            output_key="layout",
            # Placement does not affect throughput, so a layout problem must
            # not stop a verification the engineer can still act on.
            required=False,
        ),
    ),
)


# Resolved concept draft -> runnable factory -> layout.
BUILD_CONCEPT = WorkflowDefinition(
    id="BUILD_CONCEPT",
    name="Build the concept",
    description=(
        "Converts a resolved concept draft into the Factory model the simulator reads and "
        "places the stations. Refuses to convert while a value the simulator needs is "
        "missing, rather than defaulting it."
    ),
    stages=(
        WorkflowStage(
            skill_id="factory_concept_builder",
            payload=lambda bag: {"draft": bag.get("draft")},
            output_key="factory_and_product",
        ),
        WorkflowStage(
            skill_id="layout_generation",
            payload=lambda bag: {"draft": bag.get("draft")},
            output_key="layout",
            # Placement cannot change throughput, so a layout problem must
            # not block a concept the engineer can still verify.
            required=False,
        ),
    ),
)


# Factory -> simulated result -> limiting stage.
VERIFY_CONCEPT = WorkflowDefinition(
    id="VERIFY_CONCEPT",
    name="Verify the concept",
    description=(
        "Runs the deterministic simulation and reports the limiting stage. Every headline "
        "number on the results screen comes from here."
    ),
    stages=(
        WorkflowStage(
            skill_id="factory_simulation",
            payload=lambda bag: {
                "factory": bag.get("factory"),
                "product_id": bag.get("product_id"),
            },
            output_key="simulation",
        ),
        WorkflowStage(
            skill_id="bottleneck_analysis",
            payload=lambda bag: {"simulation": bag.get("simulation")},
            output_key="limiting_stage",
        ),
    ),
)


# Verified baseline -> candidate plans.
IMPROVE_CONCEPT = WorkflowDefinition(
    id="IMPROVE_CONCEPT",
    name="Explore improvements",
    description=(
        "Generates candidate plans against a goal. Evaluation and ranking remain in the "
        "strategy arena, which owns the simulation budget and the search statistics that "
        "back the recommendation."
    ),
    stages=(
        WorkflowStage(
            skill_id="strategy_generation",
            payload=lambda bag: {
                "factory": bag.get("factory"),
                "product_id": bag.get("product_id"),
                "goal": bag.get("goal"),
                "layout": bag.get("layout"),
            },
            output_key="candidates",
        ),
    ),
)


# Concept -> station requirement -> equipment -> Siemens model.
ENGINEERING_HANDOFF = WorkflowDefinition(
    id="ENGINEERING_HANDOFF",
    name="Engineering handoff",
    description=(
        "Derives what the limiting station must achieve, looks for source-backed equipment, "
        "and transfers the model to Plant Simulation. Equipment discovery is optional: an "
        "unpriced or empty result must not stop the handoff."
    ),
    stages=(
        WorkflowStage(
            skill_id="station_requirement_derivation",
            payload=lambda bag: (
                {"draft": bag.get("draft"), "station_id": bag.get("station_id")}
                if bag.get("draft") and bag.get("station_id")
                else None
            ),
            output_key="station_requirement",
            required=False,
        ),
        WorkflowStage(
            skill_id="equipment_discovery",
            payload=lambda bag: (
                {"requirement": bag["station_requirement"]}
                if bag.get("station_requirement")
                else None
            ),
            output_key="equipment",
            # Every price being QUOTE_REQUIRED is the normal case, and it
            # must never block the transfer.
            required=False,
        ),
        WorkflowStage(
            skill_id="siemens_handoff",
            payload=lambda bag: (
                {"package": bag.get("package"), "save_path": bag.get("save_path")}
                if bag.get("package")
                else None
            ),
            output_key="handoff",
            required=False,
        ),
    ),
)


ALL_WORKFLOWS: tuple[WorkflowDefinition, ...] = (
    PRODUCT_TO_PROCESS,
    FACTORY_REQUIREMENTS_TO_CONCEPT,
    BUILD_CONCEPT,
    VERIFY_CONCEPT,
    IMPROVE_CONCEPT,
    ENGINEERING_HANDOFF,
)


def workflow_by_id(workflow_id: str) -> WorkflowDefinition:
    for workflow in ALL_WORKFLOWS:
        if workflow.id == workflow_id:
            return workflow
    known = ", ".join(w.id for w in ALL_WORKFLOWS)
    raise KeyError(f"No workflow '{workflow_id}'. Known workflows: {known}.")
