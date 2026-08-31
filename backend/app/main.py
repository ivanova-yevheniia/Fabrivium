"""Fabrivium – FastAPI application."""

import json
import logging
import os
import pathlib
from datetime import date
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.llm import LLMProvider, LLMProviderError, build_provider, load_dotenv_file, load_llm_settings
from app.models.concept import ConceptOperationGroup, FactoryConceptDraft, SourcedFloat
from app.models.uncertainty import StationAssumptionProposal
from app.models.process_draft import ManufacturingProcessDraft
from app.models.product import ProductUnderstanding
from app.models.project import (
    ProjectDocument,
    ProjectState,
    ProjectSummary,
    StaleReport,
)
from app.services.project_revisions import stale_report
from app.services.project_store import (
    ProjectNotFound,
    ProjectSchemaTooNew,
    project_store,
)
from app.models.equipment_discovery import (
    CatalogKind,
    DataFreshness,
    EquipmentCandidate,
    EquipmentCapability,
    EquipmentRequirement,
    EquipmentSelection,
    EvidenceSummary,
    MatchClaim,
    ParameterChange,
)
from app.services.equipment_compatibility import CompatibilityReport
from app.models.conversation import BranchComparison, ConversationSession, ConversationTurn
from app.models.strategy import (
    InformationGapType,
    StrategyActionSummary,
    StrategyMetrics,
    StrategyArenaResult,
    StrategyComparison,
    StrategyQueryAnswer,
    StrategySearchBudget,
    UserCostInput,
    VerifiedStrategyOption,
)
from app.models import (
    EquipmentAssetType,
    EquipmentCatalogEntry,
    EquipmentLifecycleStatus,
    EquipmentModelRequest,
    Factory,
    FactoryLayout,
    LayoutValidationResult,
    Machine,
    PlanningExplanation,
    PlanningSessionState,
    RequirementsParseResult,
    Scenario,
    ScenarioResult,
    SimulationResult,
)
from app.services.agent_context import build_factory_context
from app.services.catalog import (
    CatalogError,
    EquipmentCatalog,
    EquipmentModelRequestBook,
    create_machine_from_catalog_entry,
    create_proxy_equipment_spec,
)
from app.services.branch_comparison import compare_branches
from app.services.constraints import validate_layout
from app.services.conversation_orchestrator import ConversationOrchestrator
from app.services.strategy_arena import StrategyArena
from app.services.strategy_comparison import compare_strategies
from app.services.strategy_query import answer_strategy_query, reprice_arena
from app.services.explanation_context import build_explanation_context
from app.services.llm_integration import (
    explain_with_fallback,
    parse_requirements_with_fallback,
    run_planning_session_with_fallback,
)
from app.services.machine_pool import MachinePoolError
from app.services.process_families import ProcessFamilyCatalog, process_family_catalog
from app.services.requirement_precedence import merge_requirements_sequence
from app.services.scenario import ScenarioError, apply_scenario
from app.services.scenario_runner import run_scenario
from app.services.simulation import run_simulation, run_simulation_traced
from app.services.playback_reconstruction import (
    PlaybackNotReplayable,
    reconstruct_factory,
    replay_support,
    verify_reproduces,
)
from app.models.simulation_trace import SimulationTrace, TracePlaybackConfig

app = FastAPI(
    title="Fabrivium",
    version="0.6.0",
    description=(
        "From product requirements to simulation-verified production. A traceable engineering "
        "workspace for designing, simulating, comparing and transferring manufacturing concepts."
    ),
)

# Local-dev/demo only: the Vite dev server runs on a different origin than this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # The browser cannot read a custom response header unless it is exposed.
    expose_headers=["X-FactoryMind-Skills"],
)

#: Header naming the skills that produced this response, as
#: `skill_id@version:STATUS`, in execution order. Absent when no skill ran.
SKILL_TRACE_HEADER = "X-FactoryMind-Skills"


@app.middleware("http")
async def _attach_skill_trace(request, call_next):
    """Report which skills produced the response, in a header."""
    from app.skills.runtime import begin_request_trace

    entries = begin_request_trace()
    response = await call_next(request)
    if entries:
        response.headers[SKILL_TRACE_HEADER] = ", ".join(entries)
    return response


# In-memory, process-lifetime catalog/model-request stores (Phase 3C makes
# no persistence claim — see app.services.catalog module docstring).
_catalog = EquipmentCatalog()
_model_requests = EquipmentModelRequestBook()

# FACTORYMIND_LLM_* environment variables at import time, exactly like the in-memory
# stores above.
_LOGGER = logging.getLogger("factorymind.llm")
_DOTENV_KEYS = load_dotenv_file()
if _DOTENV_KEYS:
    _LOGGER.info("Loaded %d setting(s) from backend/.env: %s", len(_DOTENV_KEYS), ", ".join(sorted(_DOTENV_KEYS)))


def _build_llm_provider() -> LLMProvider | None:
    """
    Resolve the configured provider, degrading to deterministic-only on a
    misconfiguration instead of taking the whole API down with it.
    """
    try:
        return build_provider(load_llm_settings())
    except LLMProviderError as exc:
        # LLMProviderError never carries a credential — see app.llm.errors.
        _LOGGER.error(
            "LLM provider is misconfigured, continuing with the deterministic backend only: %s", exc
        )
        return None


_LLM_PROVIDER: LLMProvider | None = _build_llm_provider()


def _llm_provider() -> LLMProvider | None:
    return _LLM_PROVIDER

_EXAMPLES_DIR = pathlib.Path(__file__).resolve().parents[2] / "examples"


# Health

@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


# Projects — the workspace that survives closing the browser The rest of this API is
# stateless by design and stays that way:


class ProjectResponse(BaseModel):
    """A project and what may still be shown as current within it."""

    project: ProjectDocument
    staleness: StaleReport


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary] = Field(default_factory=list)


class CreateProjectRequest(BaseModel):
    name: str
    #: Optional starting state, so "explore the example project" can create
    #: a real project rather than a special mode.
    state: ProjectState | None = None


class SaveProjectRequest(BaseModel):
    state: ProjectState
    #: Renaming is a save like any other; sending the name only when it
    #: changed keeps the common case small.
    name: str | None = None


def _project_response(document: ProjectDocument) -> ProjectResponse:
    return ProjectResponse(project=document, staleness=project_store.staleness(document))


@app.post("/projects", response_model=ProjectResponse, tags=["projects"])
def create_project(request: CreateProjectRequest) -> ProjectResponse:
    """Create a named project."""
    from fastapi import HTTPException

    try:
        document = project_store.create(request.name, request.state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _project_response(document)


@app.get("/projects", response_model=ProjectListResponse, tags=["projects"])
def list_projects() -> ProjectListResponse:
    """Every project, most recently updated first."""
    return ProjectListResponse(projects=project_store.list_projects())


@app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def get_project(project_id: str) -> ProjectResponse:
    """Reopen a project exactly as it was left."""
    from fastapi import HTTPException

    try:
        document = project_store.load(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProjectSchemaTooNew as exc:
        # 409 rather than 500: the server is fine, the document is from the
        # future, and the engineer needs to be told which it is.
        raise HTTPException(status_code=409, detail=str(exc))
    return _project_response(document)


@app.put("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def save_project(project_id: str, request: SaveProjectRequest) -> ProjectResponse:
    """Store new state, and report what that change invalidated."""
    from fastapi import HTTPException

    try:
        document = project_store.save(project_id, request.state, request.name)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProjectSchemaTooNew as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _project_response(document)


@app.delete("/projects/{project_id}", tags=["projects"])
def delete_project(project_id: str) -> dict[str, str]:
    """Remove a project. The engineer's decision, never Fabrivium's."""
    from fastapi import HTTPException

    try:
        project_store.delete(project_id)
    except ProjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "deleted", "project_id": project_id}


@app.post("/projects/staleness", response_model=StaleReport, tags=["projects"])
def evaluate_staleness(state: ProjectState) -> StaleReport:
    """What a given project state would report as stale, without saving it."""
    return stale_report(state)


# Factory validation

@app.post("/factory/validate", tags=["factory"])
def validate_factory(payload: dict) -> dict:
    """Validate a factory configuration payload."""
    try:
        factory = Factory.model_validate(payload)
    except ValidationError as exc:
        # Use json.loads(exc.json()) so every value is a plain JSON-safe type.
        errors = json.loads(exc.json(include_url=False))
        return JSONResponse({"valid": False, "errors": errors})

    body = {
        "valid": True,
        "summary": {
            "name": factory.name,
            "dimensions_m": {"width": factory.width, "length": factory.length},
            "schedule": {
                "shifts_per_day": factory.shifts_per_day,
                "hours_per_shift": factory.hours_per_shift,
                "total_hours_per_day": factory.shifts_per_day * factory.hours_per_shift,
            },
            "machines_count": len(factory.machines),
            "products_count": len(factory.products),
            "buffers_count": len(factory.buffers),
            "operators_available": factory.operators_available,
            "budget": factory.budget,
        },
    }
    return JSONResponse(body)


@app.get("/factory/example", response_model=Factory, tags=["factory"])
def get_example_factory() -> Factory:
    """
    Serve the bundled ``examples/electronics_line.json`` Factory — the frontend's
    initial selectable demo factory (Phase 6A section 11).
    """
    from fastapi import HTTPException

    path = _EXAMPLES_DIR / "electronics_line.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Example factory file not found on the server.")
    with open(path, encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@app.get("/factory/example/layout", response_model=FactoryLayout, tags=["factory"])
def get_example_layout() -> FactoryLayout:
    """Serve the bundled ``examples/electronics_line_layout.json`` — a
    real, backend-validated ``FactoryLayout`` for the example Factory
    (Phase 6B), so the 2D planner has genuine geometry/zones to render and
    edit rather than the frontend fabricating any (``m-labeling`` is
    intentionally left unplaced — see Phase 6B section 9's "Unplaced
    equipment" workflow).
    """
    from fastapi import HTTPException

    path = _EXAMPLES_DIR / "electronics_line_layout.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Example layout file not found on the server.")
    with open(path, encoding="utf-8") as fh:
        return FactoryLayout.model_validate(json.load(fh))


# Simulation

class SimulationRequest(BaseModel):
    """Request body for POST /simulation/run."""

    factory: dict
    product_id: str


@app.post("/simulation/run", response_model=SimulationResult, tags=["simulation"])
def run_simulation_endpoint(request: SimulationRequest) -> SimulationResult:
    """Run a deterministic discrete-event production simulation."""
    from fastapi import HTTPException

    try:
        factory = Factory.model_validate(request.factory)
    except ValidationError as exc:
        errors = json.loads(exc.json(include_url=False))
        raise HTTPException(status_code=422, detail=errors)

    #
    # The runtime calls the same `run_simulation` with the same arguments
    # and returns the same SimulationResult object — byte-identical to the
    # direct path, and exactly one simulator entry, both asserted in
    # tests/test_skill_runtime_parity.py.
    #
    # Validation stays HERE on purpose. Parsing the factory and mapping a
    # bad route to 400 is HTTP-layer work, not an engineering capability,
    # and moving it into a skill would put transport concerns inside the
    # engineering layer while changing the status codes callers depend on.
    from app.skills.contract import SkillStatus
    from app.skills.runtime import get_runtime

    outcome = get_runtime().execute(
        "factory_simulation", {"factory": factory, "product_id": request.product_id}
    )

    if outcome.status is SkillStatus.SUCCESS:
        return outcome.data

    # The skill catches what `run_simulation` raises and reports it.
    detail = outcome.warnings[0] if outcome.warnings else "Simulation failed."
    raise HTTPException(status_code=400, detail=detail.replace("Simulation failed: ", ""))


# Simulation playback trace (Phase 8C)


class SimulationPlaybackRequest(BaseModel):
    """Request body for POST /simulation/playback."""

    factory: dict
    product_id: str
    layout: dict | None = Field(
        None,
        description=(
            "Accepted and structurally validated for forward compatibility/symmetry with "
            "PlanningStateSnapshot, but NOT read by the simulator — layout never affects "
            "simulation physics (Phase 6A). The caller already holds this layout and maps "
            "trace machine_id/buffer_id fields to coordinates itself (Phase 8C section 6)."
        ),
    )
    trace_config: TracePlaybackConfig | None = Field(
        None, description="Bounds/sampling for the trace. None uses TracePlaybackConfig defaults."
    )


@app.post("/simulation/playback", response_model=SimulationTrace, tags=["simulation"])
def run_simulation_playback_endpoint(request: SimulationPlaybackRequest) -> SimulationTrace:
    """Run *product_id* through *factory* with a full PLAYBACK trace attached."""
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    if request.layout is not None:
        _parse_layout_or_422(request.layout)

    try:
        trace = run_simulation_traced(factory, request.product_id, request.trace_config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return trace



class VerifiedPlaybackRequest(BaseModel):
    """Request body for POST /simulation/playback/verified."""

    factory: dict = Field(
        ..., description="The project's CONCEPT factory — the baseline every strategy was built from."
    )
    product_id: str
    actions: StrategyActionSummary | None = Field(
        None,
        description=(
            "The strategy's persisted action summary, or null for the baseline. Used to rebuild "
            "the factory that strategy was verified on."
        ),
    )
    expected: StrategyMetrics = Field(
        ...,
        description=(
            "The metrics the project stored for this scenario. The rebuilt run must reproduce them "
            "or no trace is returned — this is what stops a concept that has changed since being "
            "animated under its old verified figures."
        ),
    )
    layout: dict | None = Field(
        None, description="Placement for drawing only. Never read by the simulator (Phase 6A)."
    )
    trace_config: TracePlaybackConfig | None = None


@app.post("/simulation/playback/verified", response_model=SimulationTrace, tags=["simulation"])
def run_verified_playback_endpoint(request: VerifiedPlaybackRequest) -> SimulationTrace:
    """Replay an already-verified scenario from a saved project."""
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    if request.layout is not None:
        _parse_layout_or_422(request.layout)

    try:
        candidate = reconstruct_factory(factory, request.actions)
    except PlaybackNotReplayable as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    try:
        trace = run_simulation_traced(candidate, request.product_id, request.trace_config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # The gate.
    try:
        verify_reproduces(trace.summary, request.expected)
    except PlaybackNotReplayable as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return trace

# Scenario apply / run (Phase 2C)

def _parse_factory_or_422(payload: dict):
    from fastapi import HTTPException

    try:
        return Factory.model_validate(payload)
    except ValidationError as exc:
        errors = json.loads(exc.json(include_url=False))
        raise HTTPException(status_code=422, detail=errors)


def _parse_scenario_or_422(payload: dict):
    from fastapi import HTTPException

    try:
        return Scenario.model_validate(payload)
    except ValidationError as exc:
        errors = json.loads(exc.json(include_url=False))
        raise HTTPException(status_code=422, detail=errors)


class ScenarioApplyRequest(BaseModel):
    """Request body for POST /scenario/apply."""

    factory: dict
    scenario: dict


@app.post("/scenario/apply", response_model=Factory, tags=["scenario"])
def apply_scenario_endpoint(request: ScenarioApplyRequest) -> Factory:
    """
    Apply a Scenario to a Factory and return the resulting candidate Factory only (no
    simulation is run).
    """
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    scenario = _parse_scenario_or_422(request.scenario)

    try:
        candidate = apply_scenario(factory, scenario)
    except ScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return candidate


class ScenarioRunRequest(BaseModel):
    """Request body for POST /scenario/run."""

    factory: dict
    product_id: str
    scenario: dict


@app.post("/scenario/run", response_model=ScenarioResult, tags=["scenario"])
def run_scenario_endpoint(request: ScenarioRunRequest) -> ScenarioResult:
    """
    Simulate a Factory baseline and the candidate produced by a Scenario, and return the
    full typed comparison and deterministic verdict.
    """
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    scenario = _parse_scenario_or_422(request.scenario)

    try:
        result = run_scenario(factory, request.product_id, scenario)
    except ScenarioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MachinePoolError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


# Layout validation (Phase 3B)

def _parse_layout_or_422(payload: dict):
    from fastapi import HTTPException

    try:
        return FactoryLayout.model_validate(payload)
    except ValidationError as exc:
        errors = json.loads(exc.json(include_url=False))
        raise HTTPException(status_code=422, detail=errors)


class LayoutValidateRequest(BaseModel):
    """Request body for POST /layout/validate."""

    factory: dict
    layout: dict
    product_id: str | None = None


@app.post("/layout/validate", response_model=LayoutValidationResult, tags=["layout"])
def validate_layout_endpoint(request: LayoutValidateRequest) -> LayoutValidationResult:
    """Validate a FactoryLayout's physical feasibility against a Factory."""
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    layout = _parse_layout_or_422(request.layout)

    try:
        result = validate_layout(factory, layout, request.product_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return result


# Equipment catalog (Phase 3C)

class CatalogRegisterRequest(BaseModel):
    """Request body for POST /equipment/catalog. ``entry`` is a raw
    EquipmentCatalogEntry payload."""

    entry: dict


@app.post("/equipment/catalog", response_model=EquipmentCatalogEntry, tags=["equipment"])
def register_catalog_entry_endpoint(request: CatalogRegisterRequest) -> EquipmentCatalogEntry:
    """Register a new equipment catalog entry."""
    from fastapi import HTTPException

    try:
        entry = EquipmentCatalogEntry.model_validate(request.entry)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json(include_url=False)))

    try:
        return _catalog.register_entry(entry)
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/equipment/catalog", response_model=list[EquipmentCatalogEntry], tags=["equipment"])
def list_catalog_entries_endpoint(
    process_type: str | None = None,
    manufacturer: str | None = None,
    model_number: str | None = None,
    text: str | None = None,
) -> list[EquipmentCatalogEntry]:
    """
    List catalog entries, optionally filtered by process_type, manufacturer,
    model_number, and/or free-text (matched against name and description).
    """
    return _catalog.search(
        process_type=process_type, manufacturer=manufacturer, model_number=model_number, text=text
    )


class ProxyCreateRequest(BaseModel):
    """Request body for POST /equipment/proxy — the minimal-input proxy workflow."""

    catalog_id: str
    name: str
    process_type: str
    width: float
    length: float
    height: float
    cycle_time: float | None = None
    purchase_cost: float = 0.0
    capacity: int = 1
    operators_required: int = 0
    manufacturer: str | None = None
    model_number: str | None = None
    description: str | None = None


@app.post("/equipment/proxy", response_model=EquipmentCatalogEntry, tags=["equipment"])
def create_proxy_endpoint(request: ProxyCreateRequest) -> EquipmentCatalogEntry:
    """Create a PROXY catalog entry from minimal engineering input and register it."""
    from fastapi import HTTPException

    entry = create_proxy_equipment_spec(**request.model_dump())
    try:
        return _catalog.register_entry(entry)
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ModelRequestCreateRequest(BaseModel):
    """Request body for POST /equipment/model-request."""

    request_id: str
    catalog_id: str
    requested_asset_type: str
    notes: str | None = None


@app.post("/equipment/model-request", response_model=EquipmentModelRequest, tags=["equipment"])
def create_model_request_endpoint(request: ModelRequestCreateRequest) -> EquipmentModelRequest:
    """Create a new equipment model request."""
    from fastapi import HTTPException

    try:
        asset_type = EquipmentAssetType(request.requested_asset_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid requested_asset_type '{request.requested_asset_type}'.",
        )

    try:
        return _model_requests.create_request(
            request.request_id, request.catalog_id, asset_type, request.notes
        )
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class MachineFromCatalogRequest(BaseModel):
    """Request body for POST /equipment/from-catalog."""

    catalog_id: str
    machine_id: str
    name: str | None = None
    position_x: float = 0.0
    position_y: float = 0.0
    lifecycle_status: str | None = None
    cycle_time: float | None = None


@app.post("/equipment/from-catalog", response_model=Machine, tags=["equipment"])
def create_machine_from_catalog_endpoint(request: MachineFromCatalogRequest) -> Machine:
    """Build a standalone Machine from a registered catalog entry."""
    from fastapi import HTTPException

    entry = _catalog.get_entry(request.catalog_id)
    if entry is None:
        raise HTTPException(status_code=400, detail=f"Catalog entry '{request.catalog_id}' not found.")

    lifecycle_status = None
    if request.lifecycle_status is not None:
        try:
            lifecycle_status = EquipmentLifecycleStatus(request.lifecycle_status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid lifecycle_status '{request.lifecycle_status}'.",
            )

    try:
        return create_machine_from_catalog_entry(
            entry,
            request.machine_id,
            name=request.name,
            position_x=request.position_x,
            position_y=request.position_y,
            lifecycle_status=lifecycle_status,
            cycle_time=request.cycle_time,
        )
    except CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# Planning (Phase 6A wiring — Phase 5A requirements parsing, Phase 5C
# iterative orchestrator, Phase 5D verified explanation, all reused
# verbatim; no engineering logic is duplicated here)

class PlanningRunRequest(BaseModel):
    """Request body for POST /planning/run."""

    factory: dict
    product_id: str
    user_request: str
    layout: dict | None = None
    max_iterations: int = 5
    max_capex: float | None = None


class PlanningProvenance(BaseModel):
    """
    Where each stage of this planning run's output actually came from (Phase 7A section
    13).
    """

    requirements_source: str = Field(..., description="DETERMINISTIC | LLM")
    planning_source: str = Field(..., description="DETERMINISTIC | LLM | MIXED | NONE (NONE = goal already met, no iterations ran)")
    explanation_source: str = Field(
        ...,
        description=(
            "DETERMINISTIC | LLM | NONE. NONE = no explanation was produced for this response at all "
            "(the strategy arena returns verified options and their deterministic rationales, not a "
            "PlanningExplanation)."
        ),
    )
    fallback_used: bool = Field(..., description="True if ANY stage fell back to its deterministic backend after an LLM attempt/failure.")

    # Phase 7B: which model was actually configured Identity ONLY.
    provider_name: str | None = Field(
        None, description="Configured provider, e.g. 'watsonx' | 'mock'. Null when no LLM is configured."
    )
    model_name: str | None = Field(
        None, description="Configured model id, e.g. 'ibm/granite-4-h-small'. Null when no LLM is configured."
    )


class PlanningRunResponse(BaseModel):
    """Everything the frontend's planning request/timeline/explanation
    panels need from a single round trip."""

    parse_result: RequirementsParseResult
    session: PlanningSessionState
    explanation: PlanningExplanation
    provenance: PlanningProvenance


def _planning_source(session: PlanningSessionState) -> str:
    """
    Derived directly from what each iteration's agent actually was (never from whether a
    provider was merely CONFIGURED) — see
    ``app.models.planning_agent.PlanningAgentResult.agent_type``.
    """
    if not session.iterations:
        return "NONE"
    sources = {it.planning_agent_result.agent_type.value for it in session.iterations}
    if sources == {"LLM"}:
        return "LLM"
    if sources == {"DETERMINISTIC"}:
        return "DETERMINISTIC"
    return "MIXED"


@app.post("/planning/run", response_model=PlanningRunResponse, tags=["planning"])
def run_planning_endpoint(request: PlanningRunRequest) -> PlanningRunResponse:
    """
    Parse *user_request* against *factory*, run the bounded iterative planning
    orchestrator (Phase 5C), and build a verified explanation of the result (Phase 5D) —
    one call, matching the frontend's RUN PLAN flow.
    """
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    layout = _parse_layout_or_422(request.layout) if request.layout is not None else None

    if request.product_id not in {p.id for p in factory.products}:
        raise HTTPException(status_code=400, detail=f"Unknown product_id '{request.product_id}'.")

    provider = _llm_provider()

    factory_context = build_factory_context(factory)
    parse_result, requirements_fallback = parse_requirements_with_fallback(request.user_request, factory_context, provider)
    requirements = parse_result.parsed_requirements
    if request.max_capex is not None and requirements.max_capex is None:
        requirements = requirements.model_copy(update={"max_capex": request.max_capex})

    try:
        session, planning_fallback = run_planning_session_with_fallback(
            factory, request.product_id, requirements, provider,
            layout=layout, max_iterations=request.max_iterations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    explanation_context = build_explanation_context(session)
    explanation_result, explanation_fallback = explain_with_fallback(explanation_context, provider)

    provenance = PlanningProvenance(
        requirements_source="LLM" if (provider is not None and not requirements_fallback) else "DETERMINISTIC",
        planning_source=_planning_source(session),
        explanation_source=explanation_result.explanation.source_type.value,
        fallback_used=requirements_fallback or planning_fallback or explanation_fallback,
        provider_name=provider.provider_name if provider is not None else None,
        model_name=provider.model_name if provider is not None else None,
    )

    return PlanningRunResponse(
        parse_result=parse_result, session=session, explanation=explanation_result.explanation, provenance=provenance,
    )


# Conversation (Phase 7C — conversational engineering copilot) Deliberately STATELESS:

class ConversationStartRequest(BaseModel):
    """Request body for POST /conversation/start."""

    factory: dict
    product_id: str
    user_message: str
    layout: dict | None = None
    max_iterations: int = Field(5, ge=1, le=20)


class ConversationTurnRequest(BaseModel):
    """Request body for POST /conversation/turn."""

    session: ConversationSession
    user_message: str


class ConversationTurnResponse(BaseModel):
    """Everything the copilot UI needs from one turn."""

    session: ConversationSession
    turn: ConversationTurn
    planning_session: PlanningSessionState | None = None


class BranchComparisonRequest(BaseModel):
    """Request body for POST /conversation/compare."""

    session: ConversationSession
    branch_a_id: str
    branch_b_id: str


def _run_conversation_turn(session: ConversationSession, user_message: str) -> ConversationTurnResponse:
    from fastapi import HTTPException

    if not user_message.strip():
        raise HTTPException(status_code=400, detail="user_message must not be empty.")

    try:
        result = ConversationOrchestrator().run_turn(session, user_message, _llm_provider())
    except ValueError as exc:
        # A genuine engineering error from the deterministic pipeline (e.g.
        raise HTTPException(status_code=400, detail=str(exc))

    return ConversationTurnResponse(
        session=result.session, turn=result.turn, planning_session=result.planning_session,
    )


@app.post("/conversation/start", response_model=ConversationTurnResponse, tags=["conversation"])
def start_conversation(request: ConversationStartRequest) -> ConversationTurnResponse:
    """Begin a conversation and run its first turn."""
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    layout = _parse_layout_or_422(request.layout) if request.layout is not None else None

    try:
        session = ConversationOrchestrator.start(
            factory, request.product_id, layout=layout, max_iterations=request.max_iterations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return _run_conversation_turn(session, request.user_message)


@app.post("/conversation/turn", response_model=ConversationTurnResponse, tags=["conversation"])
def conversation_turn(request: ConversationTurnRequest) -> ConversationTurnResponse:
    """Run one follow-up turn against an existing conversation."""
    return _run_conversation_turn(request.session, request.user_message)


@app.post("/conversation/compare", response_model=BranchComparison, tags=["conversation"])
def compare_conversation_branches(request: BranchComparisonRequest) -> BranchComparison:
    """Compare two verified branches."""
    from fastapi import HTTPException

    branch_a = request.session.branch(request.branch_a_id)
    branch_b = request.session.branch(request.branch_b_id)
    missing = [
        bid for bid, branch in ((request.branch_a_id, branch_a), (request.branch_b_id, branch_b))
        if branch is None
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown branch id(s): {missing}.")

    return compare_branches(branch_a, branch_b)


# Strategy arena (Phase 8B — multi-strategy optimization) Stateless, like the
# conversation API:

class StrategyExploreRequest(BaseModel):
    """Request body for POST /strategies/explore."""

    factory: dict
    product_id: str
    user_request: str = Field(
        ..., description="Free text. Parsed server-side into requirements AND soft strategy preferences."
    )
    prior_requests: list[str] = Field(
        default_factory=list,
        description=(
            "Earlier turns of this refinement, oldest first, WITHOUT the current one. Each is parsed "
            "on its own and folded into the current request by app.services.requirement_precedence, so "
            "a constraint stated earlier survives unless a later turn replaces or explicitly releases "
            "it. Sending the joined text as one request instead would silently take the FIRST figure "
            "mentioned and let a softening word in any turn downgrade an absolute restriction stated "
            "in another. Empty (the default) preserves the previous single-request behaviour exactly."
        ),
    )
    layout: dict | None = None
    max_capex: float | None = Field(None, description="Optional hard budget override when the text carries no figure.")
    budget: StrategySearchBudget | None = Field(
        None, description="Search bounds. Omit for the defaults (see StrategySearchBudget)."
    )
    user_costs: list[UserCostInput] = Field(
        default_factory=list,
        description="Costs the operator already knows, filling previously-unknown components. Never alters simulation.",
    )


class StrategyExploreResponse(BaseModel):
    """Everything the optimization arena UI needs from one exploration."""

    parse_result: RequirementsParseResult
    arena: StrategyArenaResult
    sessions: dict[str, PlanningSessionState] = Field(
        ...,
        description=(
            "strategy_id -> the exact verified session behind it. Sent in full so a strategy card "
            "can be opened into its real timeline, snapshots and 2D/3D state without any recomputation."
        ),
    )
    provenance: PlanningProvenance


class StrategyCompareRequest(BaseModel):
    """Request body for POST /strategies/compare."""

    strategy_a: VerifiedStrategyOption
    strategy_b: VerifiedStrategyOption


@app.post("/strategies/explore", response_model=StrategyExploreResponse, tags=["strategy"])
def explore_strategies(request: StrategyExploreRequest) -> StrategyExploreResponse:
    """Explore several verified engineering strategies for one goal."""
    from fastapi import HTTPException

    factory = _parse_factory_or_422(request.factory)
    layout = _parse_layout_or_422(request.layout) if request.layout is not None else None

    if request.product_id not in {p.id for p in factory.products}:
        raise HTTPException(status_code=400, detail=f"Unknown product_id '{request.product_id}'.")

    provider = _llm_provider()
    factory_context = build_factory_context(factory)
    parse_result, requirements_fallback = parse_requirements_with_fallback(
        request.user_request, factory_context, provider,
    )
    requirements = parse_result.parsed_requirements

    # Fold earlier turns in, oldest first.
    if request.prior_requests:
        earlier = [
            parse_requirements_with_fallback(text, factory_context, provider)[0].parsed_requirements
            for text in request.prior_requests
        ]
        requirements = merge_requirements_sequence(
            [*earlier, requirements],
            [*request.prior_requests, request.user_request],
        )

    if request.max_capex is not None and requirements.max_capex is None:
        requirements = requirements.model_copy(update={"max_capex": request.max_capex})

    # The returned parse_result reports what is ACTUALLY ENFORCED for this run, not just
    # what the newest sentence said in isolation.
    parse_result = parse_result.model_copy(update={"parsed_requirements": requirements})

    try:
        arena, sessions = StrategyArena(budget=request.budget).explore(
            factory, request.product_id, requirements,
            layout=layout, user_costs=list(request.user_costs),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return StrategyExploreResponse(
        parse_result=parse_result,
        arena=arena,
        sessions=sessions,
        provenance=PlanningProvenance(
            requirements_source="LLM" if (provider is not None and not requirements_fallback) else "DETERMINISTIC",
            # Strategy KPIs are ALWAYS deterministic: the arena runs the
            # simulator, never a model. Reported as such regardless of who
            # interpreted the sentence.
            planning_source="DETERMINISTIC",
            explanation_source="NONE",
            fallback_used=requirements_fallback,
            provider_name=provider.provider_name if provider is not None else None,
            model_name=provider.model_name if provider is not None else None,
        ),
    )


@app.post("/strategies/compare", response_model=StrategyComparison, tags=["strategy"])
def compare_strategy_options(request: StrategyCompareRequest) -> StrategyComparison:
    """Deterministic comparison of two verified strategies."""
    return compare_strategies(request.strategy_a, request.strategy_b)


class StrategyAskRequest(BaseModel):
    """Request body for POST /strategies/ask (Phase 8B section 15)."""

    arena: StrategyArenaResult
    question: str
    sessions: dict[str, PlanningSessionState] = Field(
        default_factory=dict,
        description="strategy_id -> verified session. Required only for cost statements (repricing).",
    )
    established_costs: list[UserCostInput] = Field(
        default_factory=list,
        description=(
            "Costs the engineer established EARLIER in this project. Repricing rebuilds each cost "
            "profile from its session, so a profile is only as complete as the costs handed to it: "
            "repricing with this message's cost alone would re-open every gap a previous message had "
            "already closed. Sent so that stating a second cost adds to the first instead of "
            "replacing it (G13)."
        ),
    )


class StrategyAskResponse(BaseModel):
    """A deterministic answer, plus the repriced arena when one was needed."""

    answer: StrategyQueryAnswer
    arena: StrategyArenaResult = Field(
        ..., description="Unchanged unless the question supplied costs, in which case only MONEY was re-derived."
    )
    repriced: bool = False


@app.post("/strategies/ask", response_model=StrategyAskResponse, tags=["strategy"])
def ask_about_strategies(request: StrategyAskRequest) -> StrategyAskResponse:
    """Answer a follow-up about already-verified strategies."""
    answer = answer_strategy_query(request.arena, request.question)

    if not answer.requires_repricing or not answer.cost_inputs:
        return StrategyAskResponse(answer=answer, arena=request.arena, repriced=False)

    # Everything established so far, with this message last so a restatement
    # of the same cost supersedes the earlier figure rather than sitting
    # beside it. Merged by gap type for the same reason the client merges:
    # two sentences about one cost are one fact.
    merged: dict[InformationGapType, UserCostInput] = {
        c.gap_type: c for c in [*request.established_costs, *answer.cost_inputs]
    }

    arena = reprice_arena(request.arena, request.sessions, list(merged.values()))
    return StrategyAskResponse(answer=answer, arena=arena, repriced=arena is not request.arena)


# Factory concept builder (Phase 13) Stateless, exactly like every other endpoint here:


class ConceptGapOut(BaseModel):
    """One missing piece of information, as returned to the UI."""

    key: str
    label: str
    severity: str
    reason: str
    stage_id: str | None = None


class ConceptValidationOut(BaseModel):
    """Whether a concept can be simulated, and what is still missing."""

    simulation_ready: bool
    blocking_gaps: list[ConceptGapOut]
    optional_gaps: list[ConceptGapOut]
    errors: list[str]


def _gaps_out(gaps) -> list[ConceptGapOut]:
    return [
        ConceptGapOut(
            key=g.key,
            label=g.label,
            severity=g.severity.value,
            reason=g.reason,
            stage_id=g.stage_id,
        )
        for g in gaps
    ]


def _validation_out(draft: FactoryConceptDraft) -> ConceptValidationOut:
    from app.services.concept_validation import validate_concept

    result = validate_concept(draft)
    return ConceptValidationOut(
        simulation_ready=result.simulation_ready,
        blocking_gaps=_gaps_out(result.blocking_gaps),
        optional_gaps=_gaps_out(result.optional_gaps),
        errors=list(result.errors),
    )


class ConceptResponse(BaseModel):
    """The concept plus everything the UI needs to render it honestly."""

    draft: FactoryConceptDraft
    validation: ConceptValidationOut


class ConceptFromBriefRequest(BaseModel):
    """Request body for POST /concept/from-brief."""

    brief: str = Field(..., min_length=1, description="The customer's own words.")
    name: str | None = Field(None, description="Optional concept name.")


@app.post("/concept/from-brief", response_model=ConceptResponse, tags=["concept"])
def concept_from_brief_endpoint(request: ConceptFromBriefRequest) -> ConceptResponse:
    """Structure a customer brief into a factory concept draft."""
    from app.services.concept_builder import concept_from_brief

    draft = concept_from_brief(request.brief, name=request.name)
    return ConceptResponse(draft=draft, validation=_validation_out(draft))


class ConceptDraftRequest(BaseModel):
    """Request body for endpoints that operate on an existing draft."""

    draft: FactoryConceptDraft


@app.post("/concept/example-data", response_model=ConceptResponse, tags=["concept"])
def concept_example_data_endpoint(request: ConceptDraftRequest) -> ConceptResponse:
    """Fill missing ENGINEERING values from the bundled demo dataset."""
    from app.services.concept_example_data import apply_example_engineering_data

    draft = apply_example_engineering_data(request.draft)
    return ConceptResponse(draft=draft, validation=_validation_out(draft))


# Engineering input resolution — real data first

class ResolvableInputOut(BaseModel):
    """One value the engineer may resolve, with the context to decide."""

    key: str
    label: str
    unit: str | None = None
    value: float | None = None
    source: str
    detail: str | None = None
    # BLOCKS_SIMULATION / AFFECTS_LAYOUT / COMMERCIAL_ONLY / HAS_DEFAULT.
    necessity: str
    consequence: str
    # Legitimate ways to obtain THIS quantity.
    actions: list[str] = Field(default_factory=list)
    stage_id: str | None = None
    #: Absent, and only obtainable commercially — render as "quote required",
    #: never as a zero.
    quote_required: bool = False
    resolved: bool = False
    #: The estimate contract for this value, when it currently IS an
    #: estimate: low/working/high, unit, method, confidence, basis and the
    #: model name where one was involved. The shape is
    #: `app.models.uncertainty.EstimatedRange`; it is passed through rather
    #: than re-declared so the two can never describe different fields.
    estimate: dict[str, Any] | None = None
    superseded: str | None = None


class ComputedValueOut(BaseModel):
    """A quantity Fabrivium derives. Shown with its arithmetic, never edited."""

    key: str
    label: str
    unit: str | None = None
    value: float | None = None
    formula: str
    blocked_by: str | None = None
    source: str


class ResolutionPlanResponse(BaseModel):
    inputs: list[ResolvableInputOut] = Field(default_factory=list)
    computed: list[ComputedValueOut] = Field(default_factory=list)
    # Inputs that are both unresolved and genuinely required to simulate.
    blocking_unresolved: int = 0
    ready_to_simulate: bool = False


def _estimate_out(estimate: object | None) -> dict[str, Any] | None:
    """An `EstimatedRange` as JSON, whichever form it arrived in."""
    if estimate is None:
        return None
    if isinstance(estimate, dict):
        return estimate
    dump = getattr(estimate, "model_dump", None)
    return dump(mode="json") if callable(dump) else None


def _plan_out(plan) -> ResolutionPlanResponse:
    return ResolutionPlanResponse(
        inputs=[
            ResolvableInputOut(
                key=i.key,
                label=i.label,
                unit=i.unit,
                value=i.value,
                source=i.source.value,
                detail=i.detail,
                necessity=i.necessity.value,
                consequence=i.consequence,
                actions=[a.value for a in i.actions],
                stage_id=i.stage_id,
                quote_required=i.quote_required,
                resolved=i.resolved,
                estimate=_estimate_out(i.estimate),
                superseded=i.superseded,
            )
            for i in plan.inputs
        ],
        computed=[
            ComputedValueOut(
                key=c.key,
                label=c.label,
                unit=c.unit,
                value=c.value,
                formula=c.formula,
                blocked_by=c.blocked_by,
                source=c.source.value,
            )
            for c in plan.computed
        ],
        blocking_unresolved=len(plan.blocking_unresolved),
        ready_to_simulate=plan.ready_to_simulate,
    )


@app.post("/concept/resolution-plan", response_model=ResolutionPlanResponse, tags=["concept"])
def concept_resolution_plan_endpoint(request: ConceptDraftRequest) -> ResolutionPlanResponse:
    """Every input this concept needs, and everything it works out itself."""
    from app.services.input_resolution import resolution_plan

    return _plan_out(resolution_plan(request.draft))


class ResolveInputRequest(BaseModel):
    draft: FactoryConceptDraft
    # Address of the value, e.g. "stage.m-screwdriving.cycle_time".
    key: str
    # The new value, or null to put it back to UNKNOWN.
    value: float | None = None
    # How it was obtained.
    source: str
    detail: str | None = None


class GroupOperationsRequest(BaseModel):
    """Put several operations on one physical resource."""

    draft: FactoryConceptDraft
    # Stages the cell performs. Must be a contiguous run of the route.
    stage_ids: list[str] = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="e.g. 'Assembly cell'")
    # Why.
    basis: str = Field(..., min_length=1)
    group_id: str | None = Field(None, description="Optional stable id; derived from the name if absent.")


class UngroupOperationsRequest(BaseModel):
    draft: FactoryConceptDraft
    group_id: str


@app.post("/concept/group-operations", response_model=ConceptResponse, tags=["concept"])
def concept_group_operations_endpoint(request: GroupOperationsRequest):
    """Declare that one resource performs several operations."""
    from app.services.concept_validation import operation_group_errors

    existing = {g.id for g in request.draft.operation_groups}
    group_id = request.group_id or _derive_group_id(request.name, existing)

    candidate = request.draft.model_copy(
        update={
            "operation_groups": [
                *request.draft.operation_groups,
                ConceptOperationGroup(
                    id=group_id,
                    name=request.name.strip(),
                    stage_ids=list(request.stage_ids),
                    basis=request.basis.strip(),
                ),
            ]
        }
    )

    errors = operation_group_errors(candidate)
    if errors:
        return JSONResponse(status_code=422, content={"detail": " ".join(errors)})

    return ConceptResponse(draft=candidate, validation=_validation_out(candidate))


@app.post("/concept/ungroup-operations", response_model=ConceptResponse, tags=["concept"])
def concept_ungroup_operations_endpoint(request: UngroupOperationsRequest):
    """Dissolve a cell back into one station per operation."""
    remaining = [g for g in request.draft.operation_groups if g.id != request.group_id]
    if len(remaining) == len(request.draft.operation_groups):
        return JSONResponse(
            status_code=404,
            content={"detail": f"This concept has no operation group '{request.group_id}'."},
        )
    draft = request.draft.model_copy(update={"operation_groups": remaining})
    return ConceptResponse(draft=draft, validation=_validation_out(draft))


def _derive_group_id(name: str, existing: set[str]) -> str:
    """A readable, stable id from the cell's name, uniquified if needed."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.strip().lower()).strip("-")
    slug = "-".join(part for part in slug.split("-") if part) or "cell"
    base = f"cell-{slug}"
    if base not in existing:
        return base
    index = 2
    while f"{base}-{index}" in existing:
        index += 1
    return f"{base}-{index}"


@app.post("/concept/resolve-input", response_model=ConceptResponse, tags=["concept"])
def concept_resolve_input_endpoint(request: ResolveInputRequest) -> ConceptResponse:
    """Resolve ONE value, leaving every other value exactly as it was."""
    from app.models.concept import ValueSource
    from app.services.input_resolution import UnknownInputKey, write_input

    try:
        source = ValueSource(request.source)
    except ValueError:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={"detail": f"'{request.source}' is not a value source Fabrivium records."},
        )

    # A caller may not assert the two strongest provenances.
    if source in (ValueSource.CUSTOMER, ValueSource.MEASURED):
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content={
                "detail": (
                    f"{source.value} cannot be assigned through this endpoint. A value typed here "
                    f"is ENGINEER; CUSTOMER comes from the brief and MEASURED from an observation."
                )
            },
        )

    try:
        draft = write_input(request.draft, request.key, request.value, source, request.detail)
    except UnknownInputKey as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})  # type: ignore[return-value]
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})  # type: ignore[return-value]

    return ConceptResponse(draft=draft, validation=_validation_out(draft))


# Credibility: requirement coverage and change impact

class RequirementCoverageOut(BaseModel):
    """One source requirement and what the proposed process did about it."""

    fact_key: str
    label: str
    value: str | None = None
    # ADDRESSED / UNRESOLVED / NOT_A_REQUIREMENT.
    status: str
    # CRITICAL / EXPECTED / INFORMATIONAL.
    severity: str
    # Operations citing this fact. Empty when unresolved.
    addressed_by: list[str] = Field(default_factory=list)
    #: The source sentences, so "why is this a requirement?" is answerable
    #: without reopening the document.
    quotes: list[str] = Field(default_factory=list)


class CoverageResponse(BaseModel):
    items: list[RequirementCoverageOut] = Field(default_factory=list)
    summary: str
    # True only when nothing the source states is left unanswered.
    complete: bool
    #: A requirement the source states explicitly, with no operation
    #: answering it, blocks approval. Deliberately not a percentage.
    approval_blocked: bool
    unresolved_count: int = 0
    critical_unresolved_count: int = 0


class CoverageRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft


@app.post("/product/requirement-coverage", response_model=CoverageResponse, tags=["product"])
def product_requirement_coverage_endpoint(request: CoverageRequest) -> CoverageResponse:
    """Did the proposed process answer everything the document requires?"""
    from app.services.requirement_coverage import coverage_for

    report = coverage_for(request.understanding, request.draft)
    return CoverageResponse(
        items=[
            RequirementCoverageOut(
                fact_key=item.fact_key,
                label=item.label,
                value=item.value,
                status=item.status.value,
                severity=item.severity.value,
                addressed_by=item.addressed_by,
                quotes=[e.quote for e in item.evidence if e.quote],
            )
            for item in report.items
        ],
        summary=report.summary(),
        complete=report.complete,
        approval_blocked=report.approval_blocked,
        unresolved_count=len(report.unresolved),
        critical_unresolved_count=len(report.critical_unresolved),
    )


class ProcessDraftResponse(BaseModel):
    """The process after an engineer edit, with coverage recomputed."""

    draft: ManufacturingProcessDraft
    coverage: CoverageResponse


def _with_coverage(
    understanding: ProductUnderstanding, draft: ManufacturingProcessDraft
) -> ProcessDraftResponse:
    return ProcessDraftResponse(
        draft=draft,
        coverage=product_requirement_coverage_endpoint(
            CoverageRequest(understanding=understanding, draft=draft)
        ),
    )


@app.get("/process/families", response_model=ProcessFamilyCatalog, tags=["product"])
def process_families_endpoint():
    """The canonical process-family vocabulary, with per-family coverage."""
    return process_family_catalog()


class AddOperationRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft
    name: str
    process_type: str
    # Why this operation exists.
    basis: str
    # Source requirements this operation answers.
    source_fact_keys: list[str] = Field(default_factory=list)
    repeated_operations: int | None = None
    position: int | None = None


@app.post("/product/process/add-operation", response_model=ProcessDraftResponse, tags=["product"])
def product_add_operation_endpoint(request: AddOperationRequest):
    """Add an operation the engineer decided the process needs."""
    from app.services.process_editing import add_operation

    try:
        draft = add_operation(
            request.draft,
            name=request.name,
            process_type=request.process_type,
            basis=request.basis,
            source_fact_keys=request.source_fact_keys,
            repeated_operations=request.repeated_operations,
            position=request.position,
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


class EditOperationRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft
    operation_id: str
    name: str | None = None
    process_type: str | None = None
    repeated_operations: int | None = None
    # What the operation does.
    description: str | None = None
    basis: str | None = None


@app.post("/product/process/edit-operation", response_model=ProcessDraftResponse, tags=["product"])
def product_edit_operation_endpoint(request: EditOperationRequest):
    """Change an operation, keeping the original proposal visible."""
    from app.services.process_editing import OperationNotFound, edit_operation

    try:
        draft = edit_operation(
            request.draft,
            request.operation_id,
            name=request.name,
            process_type=request.process_type,
            repeated_operations=request.repeated_operations,
            description=request.description,
            basis=request.basis,
        )
    except OperationNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


class RemoveOperationRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft
    operation_id: str


@app.post("/product/process/remove-operation", response_model=ProcessDraftResponse, tags=["product"])
def product_remove_operation_endpoint(request: RemoveOperationRequest):
    """Reject an operation. Kept in the draft so the decision stays visible."""
    from app.services.process_editing import OperationNotFound, remove_operation

    try:
        draft = remove_operation(request.draft, request.operation_id)
    except OperationNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


class LinkOperationRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft
    operation_id: str
    fact_keys: list[str]


@app.post("/product/process/link-requirement", response_model=ProcessDraftResponse, tags=["product"])
def product_link_requirement_endpoint(request: LinkOperationRequest):
    """Record that an existing operation satisfies these source requirements."""
    from app.services.process_editing import OperationNotFound, link_to_requirements

    try:
        draft = link_to_requirements(request.draft, request.operation_id, request.fact_keys)
    except OperationNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


@app.post("/product/process/unlink-requirement", response_model=ProcessDraftResponse, tags=["product"])
def product_unlink_requirement_endpoint(request: LinkOperationRequest):
    """Record that an operation does NOT satisfy these source requirements."""
    from app.services.process_editing import OperationNotFound, unlink_requirements

    try:
        draft = unlink_requirements(request.draft, request.operation_id, request.fact_keys)
    except OperationNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


@app.post("/product/process/restore-operation", response_model=ProcessDraftResponse, tags=["product"])
def product_restore_operation_endpoint(request: RemoveOperationRequest):
    """Bring a rejected operation back into the route."""
    from app.services.process_editing import OperationNotFound, restore_operation

    try:
        draft = restore_operation(request.draft, request.operation_id)
    except OperationNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


class ReorderOperationsRequest(BaseModel):
    understanding: ProductUnderstanding
    draft: ManufacturingProcessDraft
    # Every existing operation id, exactly once, in the new order.
    ordered_ids: list[str]


@app.post("/product/process/reorder", response_model=ProcessDraftResponse, tags=["product"])
def product_reorder_operations_endpoint(request: ReorderOperationsRequest):
    """Put the route in the order the engineer chose."""
    from app.services.process_editing import reorder_operations

    try:
        draft = reorder_operations(request.draft, request.ordered_ids)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return _with_coverage(request.understanding, draft)


class InputChangeOut(BaseModel):
    key: str
    label: str
    # RESOLVED / CLEARED / VALUE_CHANGED / SOURCE_CHANGED / ADDED / REMOVED.
    kind: str
    before: float | None = None
    after: float | None = None
    before_source: str | None = None
    after_source: str | None = None
    description: str


class ChangeImpactResponse(BaseModel):
    changes: list[InputChangeOut] = Field(default_factory=list)
    # Results that may no longer be shown as current.
    stale: list[str] = Field(default_factory=list)
    # Results the change cannot have affected.
    unaffected: list[str] = Field(default_factory=list)
    summary: str
    explanation: str


class ChangeImpactRequest(BaseModel):
    before: FactoryConceptDraft
    after: FactoryConceptDraft


@app.post("/concept/change-impact", response_model=ChangeImpactResponse, tags=["concept"])
def concept_change_impact_endpoint(request: ChangeImpactRequest) -> ChangeImpactResponse:
    """What a changed input invalidates."""
    from app.services.change_impact import assess, explain

    report = assess(request.before, request.after)
    return ChangeImpactResponse(
        changes=[
            InputChangeOut(
                key=change.key,
                label=change.label,
                kind=change.kind.value,
                before=change.before,
                after=change.after,
                before_source=change.before_source,
                after_source=change.after_source,
                description=change.describe(),
            )
            for change in report.changes
        ],
        stale=sorted(node.value for node in report.stale),
        unaffected=sorted(node.value for node in report.unaffected),
        summary=report.summary(),
        explanation=explain(request.before, request.after),
    )


# Skills — read-only introspection GET only, deliberately.

class SkillOut(BaseModel):
    """One declared engineering capability."""

    id: str
    version: str
    # namespace/id@version — what an execution trace records.
    qualified_id: str
    name: str
    description: str
    category: str
    capabilities: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    input_types: list[str] = Field(default_factory=list)
    output_types: list[str] = Field(default_factory=list)
    # Media this skill can consume — the multimodal extension point.
    supported_inputs: list[str] = Field(default_factory=list)
    deterministic: bool
    uses_llm: bool
    uses_external_data: bool
    side_effects: list[str] = Field(default_factory=list)
    execution_mode: str
    supported_provenance: list[str] = Field(default_factory=list)
    namespace: str
    owner: str
    enabled: bool


class SkillListResponse(BaseModel):
    skills: list[SkillOut] = Field(default_factory=list)
    #: Declared product paths, so the Architecture view can show which
    #: skills a journey actually uses.
    workflows: list[dict] = Field(default_factory=list)


def _skill_out(definition) -> SkillOut:
    return SkillOut(
        id=definition.id,
        version=definition.version,
        qualified_id=definition.qualified_id,
        name=definition.name,
        description=definition.description,
        category=definition.category.value,
        capabilities=list(definition.capabilities),
        prerequisites=list(definition.prerequisites),
        input_types=list(definition.input_types),
        output_types=list(definition.output_types),
        supported_inputs=list(definition.supported_inputs),
        deterministic=definition.deterministic,
        uses_llm=definition.uses_llm,
        uses_external_data=definition.uses_external_data,
        side_effects=[e.value for e in definition.side_effects],
        execution_mode=definition.execution_mode.value,
        supported_provenance=list(definition.supported_provenance),
        namespace=definition.namespace,
        owner=definition.owner,
        enabled=definition.enabled,
    )


@app.get("/skills", response_model=SkillListResponse, tags=["skills"])
def list_skills_endpoint() -> SkillListResponse:
    """Every engineering capability Fabrivium declares, and the paths using them."""
    from app.skills.builtin import register_builtin_skills
    from app.skills.workflows import ALL_WORKFLOWS

    registry = register_builtin_skills()
    return SkillListResponse(
        skills=[_skill_out(d) for d in registry.list_enabled()],
        workflows=[
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "skills": list(w.skill_ids),
            }
            for w in ALL_WORKFLOWS
        ],
    )


@app.get("/skills/{skill_id}", response_model=SkillOut, tags=["skills"])
def get_skill_endpoint(skill_id: str):
    """One skill's declaration."""
    from app.skills.builtin import register_builtin_skills
    from app.skills.registry import SkillNotFound

    registry = register_builtin_skills()
    try:
        return _skill_out(registry.definition(skill_id))
    except SkillNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})


class BulkResolveRequest(BaseModel):
    draft: FactoryConceptDraft


class BulkResolveResponse(BaseModel):
    draft: FactoryConceptDraft
    validation: ConceptValidationOut
    # Keys that were blank and now hold a value.
    filled: list[str] = Field(default_factory=list)
    #: Keys that did not exist before — the dataset wires buffers between
    #: stages, which creates inputs rather than filling them.
    added: list[str] = Field(default_factory=list)
    # Keys deliberately left alone because a person had already decided them.
    protected: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


@app.post("/concept/use-example-data-for-unresolved", response_model=BulkResolveResponse, tags=["concept"])
def concept_bulk_example_data_endpoint(request: BulkResolveRequest) -> BulkResolveResponse:
    """Fill everything still unresolved from the bundled demo dataset."""
    from app.services.input_resolution import apply_example_data_to_unresolved

    outcome = apply_example_data_to_unresolved(request.draft)
    return BulkResolveResponse(
        draft=outcome.draft,
        validation=_validation_out(outcome.draft),
        filled=outcome.filled,
        added=outcome.added,
        protected=outcome.protected,
        unavailable=outcome.unavailable,
    )


class BufferPointOut(BaseModel):
    size: int
    completed_units: float
    target_units: float
    meets_target: bool
    limiting_stage_id: str | None = None
    average_level: float | None = None
    upstream_blocked_seconds: float
    blocking_observed: bool


class BufferSensitivityResponse(BaseModel):
    points: list[BufferPointOut] = Field(default_factory=list)
    simulations_run: int = 0
    #: True when every size produced the same output — the finding that lets
    #: an engineer stop thinking about buffers for this target.
    indifferent: bool = False
    smallest_size_meeting_target: int | None = None
    summary: str = ""


@app.post("/concept/buffer-sensitivity", response_model=BufferSensitivityResponse, tags=["concept"])
def concept_buffer_sensitivity_endpoint(request: ConceptDraftRequest) -> BufferSensitivityResponse:
    """Ask the simulator whether buffer size matters on this line."""
    from app.services.buffer_sensitivity import sweep_buffer_sizes

    try:
        result = sweep_buffer_sizes(request.draft)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})  # type: ignore[return-value]

    return BufferSensitivityResponse(
        points=[
            BufferPointOut(
                size=p.size,
                completed_units=p.completed_units,
                target_units=p.target_units,
                meets_target=p.meets_target,
                limiting_stage_id=p.limiting_stage_id,
                average_level=p.average_level,
                upstream_blocked_seconds=p.upstream_blocked_seconds,
                blocking_observed=p.blocking_observed,
            )
            for p in result.points
        ],
        simulations_run=result.simulations_run,
        indifferent=result.indifferent,
        smallest_size_meeting_target=result.smallest_size_meeting_target,
        summary=result.summary,
    )


@app.post("/concept/validate", response_model=ConceptValidationOut, tags=["concept"])
def concept_validate_endpoint(request: ConceptDraftRequest) -> ConceptValidationOut:
    """Report what still blocks simulation, and what is merely missing."""
    return _validation_out(request.draft)


class ConceptBuildResponse(BaseModel):
    """A concept converted into the existing, simulation-ready models."""

    factory: Factory
    product_id: str
    layout: FactoryLayout
    validation: ConceptValidationOut


@app.post("/concept/build", response_model=ConceptBuildResponse, tags=["concept"])
def concept_build_endpoint(request: ConceptDraftRequest) -> ConceptBuildResponse:
    """Convert a validated concept into a Factory plus an initial layout."""
    from fastapi import HTTPException

    from app.skills.orchestrator import EngineeringSkillOrchestrator
    from app.skills.runtime import get_runtime
    from app.skills.workflows import BUILD_CONCEPT

    run = EngineeringSkillOrchestrator(get_runtime().registry).run(
        BUILD_CONCEPT, {"draft": request.draft}
    )

    if not run.completed:
        # The conversion refused.
        raise HTTPException(status_code=400, detail=run.stopped_because)

    factory, product_id = run.outputs["factory_and_product"]
    return ConceptBuildResponse(
        factory=factory,
        product_id=product_id,
        layout=run.outputs["layout"],
        validation=_validation_out(request.draft),
    )


# Engineering handoff — Siemens Plant Simulation (Phase 15C) Stateless like every other
# endpoint here:


class PlantSimulationHandoffRequest(BaseModel):
    """Request body for POST /handoff/plant-simulation."""

    factory: dict
    product_id: str
    # Concept-level placement, when the session has one.
    layout: dict | None = None
    # Where to write the .spp.
    save_path: str | None = None
    run_simulation: bool = False
    # Skip the short verification run that proves a unit can traverse the route.
    skip_traversal_check: bool = False
    #: Phase 16 — selected equipment per station id, as
    #: {"manufacturer": ..., "model": ..., "source_url": ...}. Metadata
    #: only: it names the machine under consideration and never changes a
    #: station's process values.
    equipment_selections: dict[str, dict] | None = None


class PlantSimulationHandoffResponse(BaseModel):
    """The outcome of one handoff attempt."""

    # COMPLETE — everything created AND verified.
    status: str
    model_path: str | None = None
    # Measured size, so the UI can show evidence rather than the word "saved".
    model_bytes: int | None = None
    #: The directory holding it, so the UI can offer "open containing
    #: folder" without parsing a path.
    export_directory: str | None = None
    # Whether the SAVED FILE was re-opened and read back successfully.
    saved_model_verified: bool | None = None
    # Stations and connections found in the REOPENED file.
    saved_stations_verified: int | None = None
    saved_connections_verified: int | None = None
    #: Which Plant Simulation release wrote the file, as its own automation
    #: type library reports it. None means UNKNOWN — an .spp is version-bound,
    #: so a guess here would mislead whoever tries to open it.
    product_version: str | None = None
    language: str | None = None

    stations_created: int = 0
    stations_verified: int = 0
    connections_created: int = 0
    connections_verified: int = 0
    cycle_times_verified: int = 0

    # Geometry (Phase 15D) A model can hold every station, every cycle time and every
    # connection and still be unusable:
    layout_mode: str | None = None
    # Why the conceptual arrangement was not used, when it was not.
    layout_reason: str | None = None
    # Objects whose read-back position matched the position they were given.
    positions_verified: int = 0
    positions_checked: int = 0

    # The four independent verdicts — STRUCTURE / LAYOUT / FLOW / RUNTIME — each derived
    # from evidence already read back.
    verification: list[dict] = Field(default_factory=list)

    # What the .spp actually contains — "BASELINE_CONCEPT" today.
    export_scope: str = "BASELINE_CONCEPT"
    export_scope_label: str = "Baseline engineering concept"
    # Named changes the selected plan would make that are NOT in the file.
    export_excludes: list[str] = Field(default_factory=list)
    # Where the engineering manifest was written, if it was.
    manifest_path: str | None = None
    # Smallest centre-to-centre separation in the model, in frame units.
    layout_min_separation: int | None = None
    # Pairs of objects whose icons overlap. Empty is the only passing value.
    overlaps: list[str] = Field(default_factory=list)

    # Route (Phase 15D)
    #: True only when the model was WALKED from Source to Drain and the walk
    #: passed through every object that was created.
    route_complete: bool | None = None
    # The route as walked out of the model itself.
    route_walked: list[str] = Field(default_factory=list)
    # Objects that exist in the model but are not on that route.
    disconnected: list[str] = Field(default_factory=list)

    # Units that reached the drain in the short verification run.
    traversal_units: int | None = None
    traversal_verified: bool | None = None

    # Stations whose selected-equipment metadata was read back and matched.
    equipment_verified: int = 0
    equipment_transferred: int = 0

    # Present only when run_simulation was requested and the run completed.
    simulated_units: float | None = None
    simulated_seconds: float | None = None
    station_utilisation: dict[str, float] = Field(default_factory=dict)

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@app.post("/handoff/plant-simulation", response_model=PlantSimulationHandoffResponse, tags=["handoff"])
def plant_simulation_handoff(request: PlantSimulationHandoffRequest) -> PlantSimulationHandoffResponse:
    """Generate a Siemens Plant Simulation model from the current concept."""
    from app.integrations.plant_simulation import (
        PlantSimulationAdapter,
        PlantSimulationUnavailable,
        exchange_from_factory,
    )

    factory = _parse_factory_or_422(request.factory)
    layout = _parse_layout_or_422(request.layout) if request.layout is not None else None

    try:
        package = exchange_from_factory(
            factory,
            request.product_id,
            layout=layout,
            equipment_selections=request.equipment_selections,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc))

    save_path = request.save_path or _export_destination(factory.name)

    # COM apartments are per-THREAD, and a sync endpoint runs on one of
    # uvicorn's worker threads rather than the main thread. Without this the
    # never appears in the adapter's own tests, because those call it
    # directly on the main thread.
    try:
        import pythoncom  # noqa: PLC0415 - optional, Windows-only

        pythoncom.CoInitialize()
        release_com = pythoncom.CoUninitialize
    except ImportError:
        release_com = None

    adapter = PlantSimulationAdapter()
    try:
        adapter.connect(visible=False)
    except PlantSimulationUnavailable as exc:
        if release_com:
            release_com()
        return PlantSimulationHandoffResponse(status="UNAVAILABLE", errors=[str(exc)])

    try:
        result = adapter.build(
            package,
            save_path=save_path,
            verify_traversal=not request.skip_traversal_check,
        )

        if result.fully_verified and request.run_simulation:
            try:
                adapter.run(package)
                adapter.read_results(package, result)
            except Exception as exc:  # noqa: BLE001 - a failed run must not void a good build
                result.errors.append(f"The model was built and verified, but the run failed: {str(exc)[:200]}")

        warnings: list[str] = []
        # Station names are identifiers in Plant Simulation, so a name with a
        # space is rewritten. Saying so keeps the model recognisable to an
        # engineer who opens it and sees Assembly_Station.
        renamed = [s for s in result.stations if s.source_name != s.name_expected]
        if renamed:
            warnings.append(
                "Station names were adjusted to Plant Simulation identifiers: "
                + ", ".join(f"{s.source_name} → {s.name_expected}" for s in renamed)
            )

        # A multi-capacity stage is not built from the class its name would
        # suggest, and an engineer opening the model deserves to be told
        # which object carries their station rather than to work it out.
        multi = [st for st in package.stations if st.capacity > 1]
        if multi:
            warnings.append(
                "Stages that run more than one unit at a time are built as Plant Simulation "
                "Buffer objects with Capacity = the stage capacity and ProcTime = the cycle time: "
                + ", ".join(f"{st.name} (×{st.capacity})" for st in multi)
                + ". Measured against 2404, that is N independent servers; a ParallelProc is a "
                "BATCH of N and holds units until all N places fill."
            )

        # A generated layout is a good deliverable and a silent one is not.
        if result.layout_mode == "generated-line" and result.layout_reason:
            warnings.append(
                "The concept arrangement could not be transferred as drawn, so Plant Simulation "
                f"received a generated engineering line instead — {result.layout_reason}. Station "
                "order, cycle times, capacities and material flow are unaffected."
            )

        manifest_path, manifest_warning = _write_handoff_manifest(package, result)
        if manifest_warning:
            warnings.append(manifest_warning)

        return PlantSimulationHandoffResponse(
            status="COMPLETE" if result.fully_verified else "INCOMPLETE",
            model_path=result.model_path,
            model_bytes=result.model_bytes,
            export_directory=(str(pathlib.Path(result.model_path).parent) if result.model_path else None),
            saved_model_verified=result.saved_model_verified,
            saved_stations_verified=(
                result.reopened_stations_verified if result.reopened_stations else None
            ),
            saved_connections_verified=(
                result.reopened_links_verified if result.reopened_links else None
            ),
            product_version=result.product_version,
            language=result.language,
            stations_created=len(result.stations),
            stations_verified=result.stations_verified,
            connections_created=len(result.links),
            connections_verified=result.links_verified,
            cycle_times_verified=result.stations_verified,
            layout_mode=result.layout_mode,
            layout_reason=result.layout_reason,
            positions_verified=result.positions_verified,
            positions_checked=len(result.positions),
            layout_min_separation=result.layout_min_separation,
            overlaps=result.overlaps,
            route_complete=result.route_complete,
            route_walked=result.route_walked,
            disconnected=result.disconnected,
            traversal_units=result.traversal_units,
            traversal_verified=result.traversal_verified,
            equipment_verified=result.equipment_verified,
            equipment_transferred=len(result.equipment),
            simulated_units=result.simulated_units,
            simulated_seconds=result.simulated_seconds,
            station_utilisation=result.station_utilisation,
            verification=[
                {"tier": tier.tier, "status": tier.status, "detail": tier.detail}
                for tier in result.tiers()
            ],
            export_scope="BASELINE_CONCEPT",
            export_scope_label="Baseline engineering concept",
            export_excludes=_export_excludes(request),
            manifest_path=manifest_path,
            warnings=warnings,
            errors=result.errors,
        )
    finally:
        adapter.close()
        if release_com:
            release_com()


def _export_excludes(request: "PlantSimulationHandoffRequest") -> list[str]:
    """Named things the .spp does NOT contain."""
    excludes = [
        "The shared operator pool. Plant Simulation receives no workforce "
        "constraint, so a run of this model is not workforce-limited and can "
        "report a higher throughput than Fabrivium verified.",
        "The shift and hours operating model. The model runs on Plant "
        "Simulation's own clock, not Fabrivium's 2x8h day.",
        "Every strategy Fabrivium explored, and the plan selected from "
        "them. What is exported is the concept as it stands, not the "
        "recommended changes to it — those are described as actions and no "
        "factory has been materialised for them.",
        "Fabrivium's own verification evidence, assumptions and their "
        "provenance.",
    ]
    if request.equipment_selections:
        excludes.append(
            "Equipment geometry. A selected candidate travels as text on the "
            "station — manufacturer, model, source — and no supplier CAD is "
            "instantiated, so the shapes in the model are Plant Simulation's "
            "generic ones."
        )
    return excludes


def _write_handoff_manifest(package, result) -> tuple[str | None, str | None]:
    """A short engineering manifest beside the .spp."""
    if not result.model_path:
        return None, None

    try:
        model = pathlib.Path(result.model_path)
        target = model.with_suffix(".manifest.md")
        names = {station.id: station.name for station in package.stations}

        lines = [
            f"# Fabrivium handoff — {package.project_name}",
            "",
            f"- Product: {package.product_name}",
            f"- Exported scenario: baseline engineering concept",
            f"- Model: {model.name}",
            f"- Plant Simulation: {result.product_version or 'version not reported'}",
            f"- Stations: {len(result.stations)}   Connections: {len(result.links)}",
            "",
            "## Verification",
            "",
        ]
        for tier in result.tiers():
            lines.append(f"- {tier.tier}: {tier.status} — {tier.detail}")

        lines += ["", "## Stations", "",
                  "| Fabrivium name | Plant Simulation object | Cycle time (s) | Capacity | Equipment under consideration |",
                  "|---|---|---|---|---|"]
        for check in result.stations:
            station = next((s for s in package.stations if s.id == check.station_id), None)
            equipment = "—"
            if station is not None and station.selected_model:
                equipment = f"{station.selected_manufacturer or ''} {station.selected_model}".strip()
            lines.append(
                f"| {names.get(check.station_id, check.source_name)} | {check.name_expected} | "
                f"{check.cycle_time_expected:g} | {check.capacity_expected} | {equipment} |"
            )

        lines += ["", "## Not carried into this model", ""]
        lines += [
            "- Shared operator pool — this model is NOT workforce-constrained.",
            "- Shift and hours operating model.",
            "- Explored strategies and the selected plan.",
            "- Fabrivium's verification evidence and assumptions.",
            "- Supplier CAD. Equipment above is UNDER CONSIDERATION, not verified,",
            "  and its published cycle time was not written into the model.",
        ]

        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(target), None
    except Exception as exc:  # noqa: BLE001 - a manifest must never fail a handoff
        # Reported, not swallowed.
        _LOGGER.warning("Could not write the handoff manifest: %s", exc)
        return None, (
            f"The engineering manifest could not be written beside the model ({exc}). "
            "The model itself is unaffected."
        )


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower() or "concept"


# Equipment discovery — Phase 16 Turns one planning station into engineering
# requirements and real, source-backed candidates.


class EquipmentDiscoveryRequest(BaseModel):
    """Request body for POST /equipment/discover."""

    draft: FactoryConceptDraft
    # Which stage of the concept to source equipment for.
    station_id: str
    #: The strategy the engineer was looking at, recorded on the requirement
    #: so a shortlist can be traced back to the plan it was made under.
    strategy_context: str | None = None
    #: Phase 18 — when true, Fabrivium first derives what this station's
    #: cycle time must be for the concept to meet its target, and judges
    #: candidates against THAT rather than against the current assumption.
    #: Costs a bounded set of simulations, so it is opt-in.
    use_derived_cycle_time_limit: bool = False


class CandidateAssessment(BaseModel):
    """One candidate and its comparison, carried side by side."""

    candidate: EquipmentCandidate
    compatibility: CompatibilityReport
    #: The strongest claim allowed about this candidate. Never "compatible" —
    #: see ``MatchClaim``.
    claim: MatchClaim
    claim_text: str
    pass_count: int
    fail_count: int
    unknown_count: int
    specs_published: int
    specs_considered: int
    # How the candidate's comparable values are supported, by evidence level.
    evidence: EvidenceSummary
    #: Which catalogue this record came out of, so the UI never has to infer
    #: it from the manufacturer's name.
    catalog_id: str
    catalog_kind: CatalogKind


class ConsultedCatalog(BaseModel):
    """One source's answer, including the sources that could not answer."""

    catalog_id: str
    kind: CatalogKind
    display_name: str
    trust_statement: str
    available: bool
    unavailable_reason: str = ""
    candidate_count: int
    verified_on: date | None = None


class EquipmentDiscoveryResponse(BaseModel):
    requirement: EquipmentRequirement
    assessments: list[CandidateAssessment]
    # What the station must be able to DO.
    capability: EquipmentCapability | None = None
    capability_statement: str = ""
    # Every catalogue that was asked, and what each one said.
    catalogs: list[ConsultedCatalog] = Field(default_factory=list)
    # LIVE or CACHED. The UI must show which, and never imply the other.
    freshness: DataFreshness
    #: The oldest verification date among the catalogues that answered — a
    #: shortlist is only as fresh as its least recently checked entry.
    verified_on: date | None = None
    #: Present when the station maps to no researched capability, or when
    #: every catalogue came back empty — said plainly rather than returning
    #: an empty list that looks like "we searched the market and found
    #: nothing".
    note: str | None = None


@app.post("/equipment/discover", response_model=EquipmentDiscoveryResponse, tags=["equipment"])
def discover_equipment(request: EquipmentDiscoveryRequest) -> EquipmentDiscoveryResponse:
    """Derive requirements for one station and return real candidates."""
    from fastapi import HTTPException

    from app.services.equipment_compatibility import check_compatibility
    from app.services.equipment_discovery import (
        UnknownStationError,
        requirement_from_concept,
        search_catalogs,
        source_backed_only,
    )

    derived_limit = None
    if request.use_derived_cycle_time_limit:
        from app.services.concept_validation import ConceptNotReadyError
        from app.services.sensitivity import derive_cycle_time_requirement

        try:
            derived_limit = derive_cycle_time_requirement(
                request.draft, request.station_id, fastest=5.0, slowest=120.0
            ).as_sourced()
        except (ValueError, ConceptNotReadyError):
            # No threshold could be established — the concept may not be
            # simulatable yet, or this station may not be the constraint.
            # The requirement then falls back to the stage's own value
            # rather than the shortlist silently disappearing.
            derived_limit = None

    try:
        requirement = requirement_from_concept(
            request.draft,
            request.station_id,
            strategy_context=request.strategy_context,
            derived_cycle_time_limit=derived_limit,
        )
    except UnknownStationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    search = search_catalogs(requirement)
    candidates = source_backed_only(search.candidates)

    assessments = []
    for candidate in candidates:
        report = check_compatibility(requirement, candidate)
        completeness = candidate.completeness
        assessments.append(
            CandidateAssessment(
                candidate=candidate,
                compatibility=report,
                claim=report.claim,
                claim_text=report.claim_text,
                pass_count=report.pass_count,
                fail_count=report.fail_count,
                unknown_count=report.unknown_count,
                specs_published=completeness.published,
                specs_considered=completeness.considered,
                evidence=candidate.evidence_summary,
                catalog_id=candidate.catalog_id,
                catalog_kind=candidate.catalog_kind,
            )
        )

    catalogs = [
        ConsultedCatalog(
            catalog_id=response.descriptor.catalog_id,
            kind=response.descriptor.kind,
            display_name=response.descriptor.display_name,
            trust_statement=response.descriptor.trust_statement,
            available=response.available,
            unavailable_reason=response.unavailable_reason,
            candidate_count=len(response.candidates),
            verified_on=response.verified_on,
        )
        for response in search.responses
    ]

    # Three different empty results, said three different ways.
    note = None
    if requirement.required_capability is None:
        note = (
            f"Fabrivium has no researched equipment capability for a '"
            f"{requirement.process_category}' station, so no catalogue was searched. "
            "This is a gap in our data, not a statement about the market."
        )
    elif not assessments:
        consulted = ", ".join(r.descriptor.display_name for r in search.consulted) or "no catalogue"
        note = (
            f"No record in {consulted} declares the capability this station needs. "
            "Other equipment on the market may; these catalogues do not cover it."
        )

    return EquipmentDiscoveryResponse(
        requirement=requirement,
        assessments=assessments,
        capability=requirement.required_capability,
        capability_statement=requirement.capability_statement,
        catalogs=catalogs,
        # Everything currently served is bundled.
        freshness=DataFreshness.CACHED,
        verified_on=search.verified_on,
        note=note,
    )


class EquipmentSelectRequest(BaseModel):
    """Request body for POST /equipment/select."""

    draft: FactoryConceptDraft
    station_id: str
    candidate_id: str


class EquipmentSelectResponse(BaseModel):
    selection: EquipmentSelection
    #: Every change the manufacturer's published data COULD make to the
    #: concept, itemised. Nothing here has been applied.
    proposed_changes: list[ParameterChange]
    #: True when at least one proposal would change a value the simulator
    #: reads, so the UI can warn that adopting it invalidates verification.
    affects_simulation: bool


@app.post("/equipment/select", response_model=EquipmentSelectResponse, tags=["equipment"])
def select_equipment(request: EquipmentSelectRequest) -> EquipmentSelectResponse:
    """Record a candidate as selected for a station."""
    from fastapi import HTTPException

    from app.services.equipment_discovery import (
        UnknownStationError,
        proposed_parameter_changes,
        requirement_from_concept,
        search_catalogs,
        select_candidate,
    )

    try:
        requirement = requirement_from_concept(request.draft, request.station_id)
    except UnknownStationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Searched across every catalogue, exactly as /discover did — otherwise a
    # candidate the user can see would not be selectable.
    candidates = search_catalogs(requirement).candidates
    candidate = next((c for c in candidates if c.candidate_id == request.candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"No candidate '{request.candidate_id}'.")

    stage = next(s for s in request.draft.stages if s.id == request.station_id)
    changes = proposed_parameter_changes(requirement, candidate, stage)

    return EquipmentSelectResponse(
        selection=select_candidate(requirement, candidate),
        proposed_changes=changes,
        affects_simulation=any(c.affects_simulation for c in changes),
    )


class EquipmentAdoptRequest(BaseModel):
    """Request body for POST /equipment/adopt."""

    draft: FactoryConceptDraft
    station_id: str
    candidate_id: str
    # The exact fields the engineer confirmed.
    approved_fields: list[str] = Field(default_factory=list)


class EquipmentAdoptResponse(BaseModel):
    draft: FactoryConceptDraft
    applied: list[ParameterChange]
    #: True when an adopted field feeds the simulator, so the concept's
    #: verified KPIs no longer describe this factory and must be re-run.
    requires_reverification: bool


@app.post("/equipment/adopt", response_model=EquipmentAdoptResponse, tags=["equipment"])
def adopt_equipment_parameters(request: EquipmentAdoptRequest) -> EquipmentAdoptResponse:
    """Replace named planning values with the manufacturer's published ones."""
    from fastapi import HTTPException

    from app.services.equipment_discovery import (
        UnknownStationError,
        adopt_parameters,
        proposed_parameter_changes,
        requirement_from_concept,
        search_catalogs,
    )

    try:
        requirement = requirement_from_concept(request.draft, request.station_id)
    except UnknownStationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    candidates = search_catalogs(requirement).candidates
    candidate = next((c for c in candidates if c.candidate_id == request.candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"No candidate '{request.candidate_id}'.")

    stage = next(s for s in request.draft.stages if s.id == request.station_id)
    changes = proposed_parameter_changes(requirement, candidate, stage)
    updated_stage, applied = adopt_parameters(stage, changes, request.approved_fields)

    stages = [updated_stage if s.id == request.station_id else s for s in request.draft.stages]
    return EquipmentAdoptResponse(
        draft=request.draft.model_copy(update={"stages": stages}),
        applied=applied,
        requires_reverification=any(c.affects_simulation for c in applied),
    )


# Uncertainty-aware concept assistance — Phase 18 The layering the audit settled on:


class ConceptReadinessResponse(BaseModel):
    """What the concept is made of, by provenance."""

    counts: dict
    simulation_ready: bool
    verdict: str
    unknown_critical: int
    unknown_commercial: int
    missing: list[str]
    # Definitional arithmetic: production seconds ÷ target.
    takt_seconds: SourcedFloat


@app.post("/concept/readiness", response_model=ConceptReadinessResponse, tags=["concept"])
def concept_readiness(request: ConceptDraftRequest) -> ConceptReadinessResponse:
    """Report what the concept holds and whether it can be simulated."""
    from app.services.estimation import derive_takt_seconds
    from app.services.readiness import assess_readiness

    readiness = assess_readiness(request.draft)
    return ConceptReadinessResponse(
        counts=readiness.counts.model_dump(),
        simulation_ready=readiness.simulation_ready,
        verdict=readiness.verdict,
        unknown_critical=readiness.unknown_critical,
        unknown_commercial=readiness.unknown_commercial,
        missing=readiness.missing,
        takt_seconds=derive_takt_seconds(request.draft),
    )


class EstimateCycleTimeRequest(BaseModel):
    """Request body for POST /concept/estimate."""

    draft: FactoryConceptDraft
    stage_id: str
    # What the engineer knows about the operation, in their own words.
    description: str
    automation_level: str = "UNKNOWN"
    operations_per_unit: int | None = None
    part_information: str | None = None
    other_constraints: str | None = None
    # AUTO (default) | LLM_ONLY | LOCAL_ONLY.
    mode: str | None = None


class EstimateCycleTimeResponse(BaseModel):
    """A proposed range, a request for information, or a contradiction."""

    estimate: dict | None = None
    #: Phase 18B — the whole station in one answer: cycle time, capacity and
    #: operator demand, each independently proposed or independently absent.
    proposal: dict | None = None
    # What Fabrivium still needs, with the specific questions.
    needs_information: dict | None = None
    #: The description and the selected automation level disagree; the
    #: engineer resolves it before anything is estimated.
    contradiction: dict | None = None

    #: True when the language model could not be reached and the local
    #: heuristic produced the range instead.
    fell_back: bool = False
    # Developer-facing provider detail.
    provider_note: str | None = None

    #: Present for context whether or not an estimate was produced: the
    #: engineer can judge a proposed range against the line's takt.
    takt_seconds: SourcedFloat


@app.post("/concept/estimate", response_model=EstimateCycleTimeResponse, tags=["concept"])
def estimate_cycle_time_endpoint(request: EstimateCycleTimeRequest) -> EstimateCycleTimeResponse:
    """Propose a preliminary cycle-time range for one operation."""
    from fastapi import HTTPException

    from app.services.estimation import (
        AutomationLevel,
        EstimationRequest,
        derive_takt_seconds,
        propose_station_assumptions,
    )

    stage = next((s for s in request.draft.stages if s.id == request.stage_id), None)
    if stage is None:
        raise HTTPException(status_code=400, detail=f"The concept has no stage '{request.stage_id}'.")

    try:
        automation = AutomationLevel(request.automation_level.upper())
    except ValueError:
        automation = AutomationLevel.UNKNOWN

    outcome = propose_station_assumptions(
        EstimationRequest(
            stage_id=stage.id,
            stage_name=stage.name,
            # From the stage, never typed: the local heuristic picks its
            # reference bands by family, and a typed value could drift.
            process_category=stage.process_type,
            description=request.description,
            automation_level=automation,
            operations_per_unit=request.operations_per_unit,
            part_information=request.part_information,
            other_constraints=request.other_constraints,
        ),
        _llm_provider_or_none(),
        mode=_estimation_mode(request.mode),
    )

    takt = derive_takt_seconds(request.draft)
    proposal = outcome.proposal
    return EstimateCycleTimeResponse(
        # `estimate` stays for the cycle time alone so nothing that already
        # reads it has to change; `proposal` carries the whole station.
        estimate=proposal.cycle_time.model_dump() if proposal and proposal.cycle_time else None,
        proposal=proposal.model_dump() if proposal else None,
        needs_information=(
            {"reason": outcome.missing.reason, "questions": outcome.missing.questions}
            if outcome.missing
            else None
        ),
        contradiction=(
            {
                "message": outcome.contradiction.message,
                "described_as": outcome.contradiction.described_as,
                "selected_as": outcome.contradiction.selected_as,
            }
            if outcome.contradiction
            else None
        ),
        fell_back=proposal.fell_back if proposal else False,
        provider_note=proposal.provider_note if proposal else None,
        takt_seconds=takt,
    )


def _estimation_mode(raw: str | None):
    """AUTO unless the caller asked otherwise, and AUTO on anything unknown."""
    from app.services.estimation import EstimationMode

    try:
        return EstimationMode((raw or "AUTO").upper())
    except ValueError:
        return EstimationMode.AUTO


def _llm_provider_or_none():
    """The configured provider, or None when there is not one."""
    try:
        return _llm_provider()
    except Exception:  # noqa: BLE001 - an unusable provider is simply absent
        return None


class ApplyEstimateRequest(BaseModel):
    """Request body for POST /concept/apply-estimate."""

    draft: FactoryConceptDraft
    stage_id: str
    low: float
    working_value: float
    high: float
    basis: str
    confidence: str = "MEDIUM"
    #: ENGINEER when the engineer typed the range, LANGUAGE_MODEL when they
    #: accepted the assistant's proposal. Recorded, not inferred.
    method: str = "ENGINEER"
    model_name: str | None = None
    #: Required before an estimate may replace a value that came from a
    #: person, a document, a measurement or a manufacturer. Defaults to
    #: False so the destructive case is never the one that happens by
    #: accident — see `_refuse_to_overwrite`.
    replace_existing: bool = False


def _refuse_to_overwrite(
    draft: FactoryConceptDraft,
    stage_id: str,
    fields: list[str],
    replace_existing: bool,
) -> JSONResponse | None:
    """Stop an estimate from silently replacing something stronger."""
    from app.services.estimation import protected_values

    if replace_existing:
        return None

    protected = protected_values(draft, stage_id, fields)
    if not protected:
        return None

    # Structured, and inside `detail`: the API client unwraps `body.detail`
    # on every non-2xx response, so anything beside it never reaches the
    # caller. The message stays human-readable for the generic error path,
    # and the machine-readable half is what lets the panel ask the engineer
    # rather than simply reporting a failure.
    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "conflict": "PROTECTED_VALUE",
                "message": (
                    "This station already holds a value that did not come from an estimate: "
                    + "; ".join(item.describe() for item in protected)
                    + ". Confirm the replacement to apply the estimate instead."
                ),
                "protected": [
                    {
                        "field": item.field,
                        "label": item.label,
                        "value": item.value,
                        "source": item.source,
                        "detail": item.detail,
                    }
                    for item in protected
                ],
            }
        },
    )


@app.post("/concept/apply-estimate", response_model=ConceptResponse, tags=["concept"])
def apply_estimate_endpoint(request: ApplyEstimateRequest):
    """Write an estimate's working value onto a stage."""
    from fastapi import HTTPException

    from app.models.uncertainty import Confidence, EstimatedRange, EstimateMethod
    from app.services.estimation import apply_estimate

    if not any(s.id == request.stage_id for s in request.draft.stages):
        raise HTTPException(status_code=400, detail=f"The concept has no stage '{request.stage_id}'.")

    try:
        estimate = EstimatedRange(
            low=request.low,
            working_value=request.working_value,
            high=request.high,
            unit="s",
            confidence=Confidence(request.confidence.upper()),
            method=EstimateMethod(request.method.upper()),
            basis=request.basis,
            model_name=request.model_name,
        )
    except ValueError as exc:
        # An inverted range or a working value outside its own bounds is a
        # contradiction, not something to quietly repair.
        raise HTTPException(status_code=400, detail=str(exc))

    refusal = _refuse_to_overwrite(
        request.draft, request.stage_id, ["cycle_time"], request.replace_existing
    )
    if refusal is not None:
        return refusal

    updated = apply_estimate(request.draft, request.stage_id, estimate)
    return ConceptResponse(draft=updated, validation=_validation_out(updated))


class SensitivityRequest(BaseModel):
    """Request body for POST /concept/sensitivity."""

    draft: FactoryConceptDraft
    stage_id: str
    #: The cycle times to evaluate. Defaults to the stage's own estimated
    #: range when it has one.
    values: list[float] | None = None


class SensitivityResponse(BaseModel):
    stage_id: str
    stage_name: str
    parameter: str
    unit: str
    points: list[dict]
    simulations_run: int
    monotonic: bool
    summary: str


@app.post("/concept/sensitivity", response_model=SensitivityResponse, tags=["concept"])
def concept_sensitivity(request: SensitivityRequest) -> SensitivityResponse:
    """Run the deterministic simulator once per value and report what changed."""
    from fastapi import HTTPException

    from app.services.concept_validation import ConceptNotReadyError
    from app.services.sensitivity import sweep_cycle_time

    values = request.values
    if not values:
        stage = next((s for s in request.draft.stages if s.id == request.stage_id), None)
        estimate = getattr(stage, "cycle_time_estimate", None) if stage else None
        if isinstance(estimate, dict):
            values = sorted({estimate["low"], estimate["working_value"], estimate["high"]})
        elif estimate is not None:
            values = estimate.sweep_points()
    if not values:
        raise HTTPException(
            status_code=400,
            detail="No values to sweep: supply them, or give the stage an estimated range first.",
        )

    try:
        result = sweep_cycle_time(request.draft, request.stage_id, values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ConceptNotReadyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SensitivityResponse(
        stage_id=result.stage_id,
        stage_name=result.stage_name,
        parameter=result.parameter,
        unit=result.unit,
        points=[p.model_dump() for p in result.points],
        simulations_run=result.simulations_run,
        monotonic=result.monotonic,
        summary=result.summary(),
    )


class ThresholdRequest(BaseModel):
    """Request body for POST /concept/threshold."""

    draft: FactoryConceptDraft
    stage_id: str
    fastest: float = 5.0
    slowest: float = 120.0


class ThresholdResponse(BaseModel):
    stage_id: str
    stage_name: str
    parameter: str
    unit: str
    # None whenever no honest single number exists. `statement` says why.
    threshold: float | None
    target_units: float
    simulations_run: int
    monotonic: bool
    statement: str
    requirement_value: SourcedFloat


@app.post("/concept/threshold", response_model=ThresholdResponse, tags=["concept"])
def concept_threshold(request: ThresholdRequest) -> ThresholdResponse:
    """What this parameter must achieve for the concept to meet its target."""
    from fastapi import HTTPException

    from app.services.concept_validation import ConceptNotReadyError
    from app.services.sensitivity import derive_cycle_time_requirement

    try:
        requirement = derive_cycle_time_requirement(
            request.draft, request.stage_id, fastest=request.fastest, slowest=request.slowest
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ConceptNotReadyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ThresholdResponse(
        stage_id=requirement.stage_id,
        stage_name=requirement.stage_name,
        parameter=requirement.parameter,
        unit=requirement.unit,
        threshold=requirement.threshold,
        target_units=requirement.target_units,
        simulations_run=requirement.simulations_run,
        monotonic=requirement.monotonic,
        statement=requirement.statement(),
        requirement_value=requirement.as_sourced(),
    )

class AcceptStationAssumptionsRequest(BaseModel):
    """Request body for POST /concept/accept-assumptions."""

    draft: FactoryConceptDraft
    #: The proposal exactly as it was reviewed, so what is written is what
    #: the engineer saw rather than a re-derivation that may have drifted.
    proposal: StationAssumptionProposal
    # Which parameters the engineer accepted: "cycle_time", "capacity", "operators".
    accepted_fields: list[str] = Field(default_factory=list)
    #: Required before these assumptions may replace values that came from a
    #: person, a document, a measurement or a manufacturer.
    replace_existing: bool = False


class AcceptStationAssumptionsResponse(BaseModel):
    draft: FactoryConceptDraft
    validation: ConceptValidationOut
    #: What was actually written, so the UI reports the truth rather than
    #: what it asked for.
    applied: list[str] = Field(default_factory=list)


@app.post("/concept/accept-assumptions", response_model=AcceptStationAssumptionsResponse, tags=["concept"])
def accept_station_assumptions(request: AcceptStationAssumptionsRequest):
    """Write the accepted station assumptions into the concept."""
    from fastapi import HTTPException

    from app.services.estimation import apply_station_assumptions

    if not any(s.id == request.proposal.stage_id for s in request.draft.stages):
        raise HTTPException(
            status_code=400, detail=f"The concept has no stage '{request.proposal.stage_id}'."
        )

    refusal = _refuse_to_overwrite(
        request.draft,
        request.proposal.stage_id,
        request.accepted_fields,
        request.replace_existing,
    )
    if refusal is not None:
        return refusal

    updated, applied = apply_station_assumptions(
        request.draft, request.proposal, request.accepted_fields
    )
    return AcceptStationAssumptionsResponse(
        draft=updated, validation=_validation_out(updated), applied=applied
    )


# Product understanding — Phase 19 The first multipart endpoint in the product, and with
# it the first untrusted-binary surface.


class DescribeProductRequest(BaseModel):
    """Request body for POST /product/describe."""

    # The engineer's own words about the product.
    description: str
    product_name: str = "Product"
    # AUTO (default) | LLM_ONLY | LOCAL_ONLY.
    mode: str | None = None


class ProductUnderstandingResponse(BaseModel):
    understanding: ProductUnderstanding
    # True when the language model contributed facts.
    model_used: bool = False
    # Provider detail for developers.
    provider_note: str | None = None


def _understand_via_skill(
    ingestion, *, product_name: str, description: str | None = None, mode=None
) -> "ProductUnderstandingResponse":
    """Run `product_understanding` and rebuild the existing response."""
    from fastapi import HTTPException

    from app.skills import SkillContext
    from app.skills.contract import SkillStatus
    from app.skills.runtime import SkillExecutionError, get_runtime

    payload = {"ingestion": ingestion, "product_name": product_name}
    if description is not None:
        payload["description"] = description
    if mode is not None:
        payload["mode"] = mode

    try:
        result = get_runtime().execute(
            "product_understanding",
            payload,
            context=SkillContext(llm_provider=_llm_provider_or_none()),
        )
    except SkillExecutionError as exc:  # pragma: no cover - execute() reports
        raise HTTPException(status_code=500, detail=str(exc))

    if result.status in (SkillStatus.BLOCKED, SkillStatus.FAILED):
        raise HTTPException(
            status_code=500,
            detail=result.warnings[0] if result.warnings else "Product understanding failed.",
        )

    return ProductUnderstandingResponse(
        understanding=result.data,
        model_used=bool(result.provenance.get("model_used", False)),
        provider_note=result.provenance.get("provider_note"),
    )


@app.post("/product/describe", response_model=ProductUnderstandingResponse, tags=["product"])
def describe_product(request: DescribeProductRequest) -> ProductUnderstandingResponse:
    """Read product facts out of a written description."""
    from fastapi import HTTPException

    from app.services.input_adapters import ingest_text

    if not request.description.strip():
        raise HTTPException(status_code=400, detail="Describe the product first.")

    return _understand_via_skill(
        ingest_text(request.description, name="Product description"),
        product_name=request.product_name,
        description=request.description,
        mode=_estimation_mode(request.mode),
    )


@app.post("/product/upload", response_model=ProductUnderstandingResponse, tags=["product"])
async def upload_product_document(
    file: UploadFile = File(...),
    product_name: str = Form("Product"),
    mode: str | None = Form(None),
) -> ProductUnderstandingResponse:
    """Read product facts out of an uploaded specification."""
    from fastapi import HTTPException

    from app.services.input_adapters import MAX_DOCUMENT_BYTES, UnsupportedDocument, ingest

    payload = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"The file is larger than {MAX_DOCUMENT_BYTES // 1_048_576} MB.",
        )
    if not payload:
        raise HTTPException(status_code=400, detail="The file is empty.")

    try:
        ingestion = ingest(payload, name=file.filename or "document", media_type=file.content_type)
    except UnsupportedDocument as exc:
        # A document we cannot read is a 400 with a plain reason, never a
        # stack trace and never a silent empty result.
        raise HTTPException(status_code=400, detail=str(exc))

    return _understand_via_skill(
        ingestion, product_name=product_name, mode=_estimation_mode(mode)
    )


class PlanProcessRequest(BaseModel):
    """Request body for POST /product/plan-process."""

    understanding: ProductUnderstanding


class PlanProcessResponse(BaseModel):
    draft: ManufacturingProcessDraft


@app.post("/product/plan-process", response_model=PlanProcessResponse, tags=["product"])
def plan_manufacturing_process(request: PlanProcessRequest) -> PlanProcessResponse:
    """Propose the operations the product facts imply."""
    from app.models.process_draft import ManufacturingProcessDraft
    from app.skills.contract import SkillStatus
    from app.skills.runtime import get_runtime

    result = get_runtime().execute(
        "process_planning", {"understanding": request.understanding}
    )

    if result.usable:
        return PlanProcessResponse(draft=result.data)

    if result.status is SkillStatus.NOT_APPLICABLE:
        # The direct path returned a draft with no operations and the open
        # question attached. Same shape, same meaning.
        return PlanProcessResponse(
            draft=ManufacturingProcessDraft(
                product_name=request.understanding.product_name,
                operations=[],
                method="LOCAL_RULES",
                open_questions=list(result.warnings),
            )
        )

    # BLOCKED or FAILED: propagate honestly rather than returning an empty
    # draft that would read as "this product needs no manufacturing".
    return JSONResponse(  # type: ignore[return-value]
        status_code=422,
        content={"detail": result.warnings[0] if result.warnings else "Process planning failed."},
    )


class BuildConceptFromProductRequest(BaseModel):
    """Request body for POST /product/build-concept."""

    understanding: ProductUnderstanding
    # The process draft as the engineer left it — accepted, edited, reordered.
    process: ManufacturingProcessDraft
    # Production requirements in the customer's words.
    requirements_brief: str
    name: str | None = None


class BuildConceptFromProductResponse(BaseModel):
    draft: FactoryConceptDraft
    validation: ConceptValidationOut
    #: Per-stage product context for the Station Assumption Assistant, so
    #: the estimator sees "6 screws into an ABS enclosure" rather than
    #: "screwdriving".
    station_context: dict[str, dict]


@app.post("/product/build-concept", response_model=BuildConceptFromProductResponse, tags=["product"])
def build_concept_from_product(
    request: BuildConceptFromProductRequest,
) -> BuildConceptFromProductResponse:
    """Turn an accepted process into the existing FactoryConceptDraft."""
    from fastapi import HTTPException

    from app.services.product_to_concept import (
        ProcessNotAcceptedError,
        RequirementsUnresolvedError,
        concept_from_product,
        describe_for_estimator,
        station_context,
    )

    try:
        draft = concept_from_product(
            request.understanding, request.process, request.requirements_brief, name=request.name
        )
    except ProcessNotAcceptedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RequirementsUnresolvedError as exc:
        # The approval gate.
        raise HTTPException(status_code=400, detail=str(exc))

    contexts: dict[str, dict] = {}
    for stage in draft.stages:
        context = station_context(request.understanding, request.process, stage.id)
        if context:
            contexts[stage.id] = {**context, "estimator_description": describe_for_estimator(context)}

    return BuildConceptFromProductResponse(
        draft=draft, validation=_validation_out(draft), station_context=contexts
    )


class ReferenceProductResponse(BaseModel):
    """The bundled competition reference document."""

    name: str
    text: str
    # Stated so nothing mistakes this for a customer document.
    classification: str = "EXAMPLE / REFERENCE DATA"


@app.get("/product/reference", response_model=ReferenceProductResponse, tags=["product"])
def reference_product() -> ReferenceProductResponse:
    """The bundled reference product specification."""
    from fastapi import HTTPException

    path = pathlib.Path(__file__).resolve().parent / "data" / "electronics_controller_reference_product.txt"
    if not path.exists():  # pragma: no cover - packaging error
        raise HTTPException(status_code=500, detail="The reference product document is missing.")

    return ReferenceProductResponse(
        name="electronics_controller_reference_product.txt",
        text=path.read_text(encoding="utf-8"),
    )

def _export_destination(factory_name: str) -> str:
    """Where a Siemens handoff is written."""
    root = os.environ.get("FACTORYMIND_EXPORT_DIR")
    base = pathlib.Path(root) if root else pathlib.Path(__file__).resolve().parents[2] / "exports"
    directory = base / "siemens"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / f"{_slug(factory_name)}.spp")


# Engineering Knowledge Base — read-only inspection Two GET endpoints and nothing else.


class KnowledgeItemOut(BaseModel):
    """One piece of engineering knowledge, as declared."""

    id: str
    version: str
    # id@version — what a citation records.
    qualified_id: str
    kind: str
    category: str
    domain: str
    title: str
    description: str

    # Where it came from and how far it may be trusted.
    source_kind: str
    source_reference: str
    provenance_statement: str
    classification_vocabulary: str | None = None
    classification: str | None = None
    verified_on: date | None = None

    scope: str
    process_categories: list[str] = Field(default_factory=list)
    not_valid_for: str = ""

    # DERIVED_VALUE — `values` were read from the canonical source.
    exposure: str
    values: dict = Field(default_factory=dict)

    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    deprecated: bool = False

    # Present only on a standard reference.
    standard: dict | None = None


class KnowledgeCategoryOut(BaseModel):
    category: str
    items: int
    derived: int
    pointers: int
    kinds: list[str] = Field(default_factory=list)


class KnowledgeBaseOut(BaseModel):
    """The knowledge base, for architecture inspection."""

    version: str
    items: int
    categories: list[KnowledgeCategoryOut] = Field(default_factory=list)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_source_kind: dict[str, int] = Field(default_factory=dict)
    standard_references: int = 0
    # Always false.
    claims_standards_compliance: bool = False
    knowledge: list[KnowledgeItemOut] = Field(default_factory=list)
    #: The built-in knowledge described under the future Engineering Skill
    #: packaging contract. Not an installed package — see app.knowledge.packaging.
    builtin_package: dict = Field(default_factory=dict)


def _knowledge_out(item) -> KnowledgeItemOut:
    return KnowledgeItemOut(
        id=item.id,
        version=item.version,
        qualified_id=item.qualified_id,
        kind=item.kind.value,
        category=item.category.value,
        domain=item.domain.value,
        title=item.title,
        description=item.description,
        source_kind=item.provenance.source_kind.value,
        source_reference=item.provenance.source_reference,
        provenance_statement=item.provenance.statement,
        classification_vocabulary=item.provenance.classification_vocabulary,
        classification=item.provenance.classification,
        verified_on=item.provenance.verified_on,
        scope=item.applicability.scope,
        process_categories=list(item.applicability.process_categories),
        not_valid_for=item.applicability.not_valid_for,
        exposure=item.exposure.value,
        values=dict(item.values),
        status=item.status,
        tags=list(item.tags),
        deprecated=item.deprecated,
        standard=(
            {
                "identifier": item.standard.identifier,
                "title": item.standard.title,
                "edition": item.standard.edition,
                "cited_by": item.standard.cited_by,
                "scope_note": item.standard.scope_note,
                "verification": item.standard.verification.value,
                "content_available": item.standard.content_available,
                "establishes_compliance": item.standard.establishes_compliance,
                "disclosure": item.standard.disclosure,
            }
            if item.standard is not None
            else None
        ),
    )


@app.get("/knowledge", response_model=KnowledgeBaseOut, tags=["knowledge"])
def list_knowledge_endpoint(category: str | None = None, kind: str | None = None):
    """Every piece of engineering knowledge Fabrivium holds, with provenance."""
    from app.knowledge.builtin import build_knowledge_base
    from app.knowledge.contract import KnowledgeCategory, KnowledgeKind
    from app.knowledge.packaging import builtin_manifest

    base = build_knowledge_base()

    try:
        wanted_category = KnowledgeCategory(category) if category else None
        wanted_kind = KnowledgeKind(kind) if kind else None
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    summary = base.summary()
    package = builtin_manifest(base)

    return KnowledgeBaseOut(
        version=summary.version,
        items=summary.items,
        categories=[
            KnowledgeCategoryOut(
                category=c.category.value,
                items=c.items,
                derived=c.derived,
                pointers=c.pointers,
                kinds=list(c.kinds),
            )
            for c in summary.categories
        ],
        by_kind=dict(summary.by_kind),
        by_source_kind=dict(summary.by_source_kind),
        standard_references=summary.standard_references,
        claims_standards_compliance=summary.claims_standards_compliance,
        knowledge=[
            _knowledge_out(i)
            for i in base.query(category=wanted_category, kind=wanted_kind)
        ],
        builtin_package={
            "skill_id": package.skill_id,
            "name": package.name,
            "version": package.version,
            "organization_scope": package.organization_scope.value,
            "validation_status": package.validation_status.value,
            "owner": package.owner,
            "knowledge_items": len(package.knowledge_items),
            "implemented": False,
            "note": (
                "Engineering Skills are a roadmap contract. Fabrivium has no package "
                "loader, and this describes the built-in knowledge rather than an "
                "installed package."
            ),
        },
    )


@app.get("/knowledge/{item_id}", response_model=KnowledgeItemOut, tags=["knowledge"])
def get_knowledge_endpoint(item_id: str):
    """One knowledge item, including its full provenance record."""
    from app.knowledge.base import KnowledgeItemNotFound
    from app.knowledge.builtin import build_knowledge_base

    try:
        return _knowledge_out(build_knowledge_base().get(item_id))
    except KnowledgeItemNotFound as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
