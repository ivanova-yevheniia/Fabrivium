"""First-party skills — adapters over existing production code."""

from __future__ import annotations

import time
from typing import Any

from app.skills.contract import (
    ExecutionMode,
    SideEffect,
    Skill,
    SkillCategory,
    SkillContext,
    SkillDefinition,
    SkillResult,
    SkillStatus,
)
from app.skills.registry import SkillRegistry, default_registry

_VERSION = "1.0.0"


# UNDERSTANDING

class ProductUnderstandingSkill(Skill):
    """Read a supplied document into structured product facts."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="product_understanding",
            version=_VERSION,
            name="Product understanding",
            description=(
                "Reads a product document into structured facts with citations. "
                "Deterministic extraction runs first; a language model, when available, "
                "may add facts but never overrides an extracted one."
            ),
            category=SkillCategory.UNDERSTANDING,
            capabilities=("extract_product_facts", "understand_product_document"),
            input_types=("IngestionResult",),
            output_types=("ProductUnderstanding",),
            supported_inputs=("text", "pdf"),
            deterministic=False,
            uses_llm=True,
            execution_mode=ExecutionMode.MODEL_WITH_FALLBACK,
            supported_provenance=("EXTRACTED", "AI_INFERRED", "CONFLICT", "UNKNOWN"),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.product_intelligence import understand_product

        ingestion = payload.get("ingestion") if isinstance(payload, dict) else payload
        if ingestion is None:
            return self._blocked("No document was supplied.", missing=["ingestion"])

        # `description` and `mode` are forwarded rather than dropped.
        options = payload if isinstance(payload, dict) else {}
        call_kwargs: dict[str, Any] = {
            "product_name": options.get("product_name", "Product"),
        }
        if options.get("description") is not None:
            call_kwargs["description"] = options["description"]
        if options.get("mode") is not None:
            call_kwargs["mode"] = options["mode"]

        started = time.perf_counter()
        try:
            result = understand_product(ingestion, context.llm_provider, **call_kwargs)
        except Exception as exc:  # noqa: BLE001 - a skill reports, never raises
            return self._failed(f"Product understanding failed: {str(exc)[:200]}")

        understanding = result.understanding
        elapsed = time.perf_counter() - started

        # Gaps the extractor itself declared are unresolved inputs, not
        # warnings: they are what the engineer has to supply next.
        gaps = [g.key for g in understanding.information_gaps]
        status = SkillStatus.PARTIAL if gaps else SkillStatus.SUCCESS

        return SkillResult(
            status=status,
            data=understanding,
            provenance={
                "interpretation_method": understanding.interpretation_method,
                # Whether a model contributed is a property of HOW these
                # facts were obtained, so it belongs with the provenance
                # rather than being lost between the skill and the caller.
                "model_used": result.model_used,
                "provider_note": result.provider_note,
            },
            evidence=[e for fact in understanding.facts for e in fact.evidence],
            unresolved_inputs=gaps,
            trace=[
                self._entry(
                    status,
                    f"{len(understanding.facts)} facts extracted"
                    + (f", {len(gaps)} gap(s) declared" if gaps else ""),
                    elapsed_seconds=elapsed,
                )
            ],
        )


class RequirementsExtractionSkill(Skill):
    """Structure a customer brief into a concept draft."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="requirements_extraction",
            version=_VERSION,
            name="Requirements extraction",
            description=(
                "Reads production requirements — target, floor, workforce, schedule — "
                "out of a customer brief. Anything the brief states is CUSTOMER-sourced; "
                "anything it does not state stays UNKNOWN."
            ),
            category=SkillCategory.UNDERSTANDING,
            capabilities=("parse_production_requirements",),
            input_types=("str",),
            output_types=("FactoryConceptDraft",),
            supported_inputs=("text",),
            supported_provenance=("CUSTOMER", "UNKNOWN"),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.concept_builder import concept_from_brief

        brief = payload.get("brief") if isinstance(payload, dict) else payload
        if not brief or not str(brief).strip():
            return self._blocked("No requirements brief was supplied.", missing=["brief"])

        # The concept name is the engineer's label for this project.
        name = payload.get("name") if isinstance(payload, dict) else None

        started = time.perf_counter()
        try:
            draft = (
                concept_from_brief(str(brief), name=name)
                if name is not None
                else concept_from_brief(str(brief))
            )
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Requirements extraction failed: {str(exc)[:200]}")

        from app.services.concept_validation import required_gaps

        missing = [g.key for g in required_gaps(draft)]
        status = SkillStatus.PARTIAL if missing else SkillStatus.SUCCESS
        return SkillResult(
            status=status,
            data=draft,
            provenance={"production_target": draft.production_target.source.value},
            unresolved_inputs=missing,
            trace=[
                self._entry(
                    status,
                    f"{len(draft.stages)} stage(s) named"
                    + (f", {len(missing)} required input(s) still missing" if missing else ""),
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


# PLANNING

class ProcessPlanningSkill(Skill):
    """Propose the manufacturing operations the product facts imply."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="process_planning",
            version=_VERSION,
            name="Process planning",
            description=(
                "Turns product facts into a proposed manufacturing route. A rule table, "
                "not a model: each operation records the facts that caused it and quotes "
                "the source sentence."
            ),
            category=SkillCategory.PLANNING,
            capabilities=("derive_manufacturing_process",),
            prerequisites=("product_understanding",),
            input_types=("ProductUnderstanding",),
            output_types=("ManufacturingProcessDraft",),
            supported_provenance=("RULE_DERIVED",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.process_planning import plan_process
        from app.services.requirement_coverage import coverage_for

        understanding = payload.get("understanding") if isinstance(payload, dict) else payload
        if understanding is None:
            return self._blocked("No product understanding was supplied.", missing=["understanding"])

        started = time.perf_counter()
        try:
            draft = plan_process(understanding)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Process planning failed: {str(exc)[:200]}")

        if not draft.operations:
            return self._not_applicable(
                "The source names no components, fasteners, connections, inspection or packaging, "
                "so no manufacturing operation follows from it."
            )

        # A source requirement nothing answers is exactly an unresolved input.
        coverage = coverage_for(understanding, draft)
        unresolved = [item.fact_key for item in coverage.unresolved]
        status = SkillStatus.PARTIAL if unresolved else SkillStatus.SUCCESS

        return SkillResult(
            status=status,
            data=draft,
            provenance={"method": draft.method},
            evidence=[e for op in draft.operations for e in op.evidence],
            unresolved_inputs=unresolved,
            warnings=list(draft.open_questions),
            trace=[
                self._entry(
                    status,
                    f"{len(draft.operations)} operation(s) proposed; {coverage.summary()}",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


# ESTIMATION

class EngineeringEstimationSkill(Skill):
    """Propose a cycle time, capacity and operator count for one station."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="engineering_estimation",
            version=_VERSION,
            name="Engineering estimation",
            description=(
                "Produces a preliminary engineering assumption with a range, a confidence "
                "and a stated basis. Prefers a language model and falls back to a "
                "deterministic estimator over classified reference data."
            ),
            category=SkillCategory.ESTIMATION,
            capabilities=("estimate_station_assumptions", "estimate_cycle_time"),
            input_types=("EstimationRequest",),
            output_types=("StationAssumptionProposal",),
            deterministic=False,
            uses_llm=True,
            execution_mode=ExecutionMode.MODEL_WITH_FALLBACK,
            supported_provenance=("ENGINEERING_ESTIMATE", "UNKNOWN"),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.estimation import propose_station_assumptions

        request = payload.get("request") if isinstance(payload, dict) else payload
        if request is None:
            return self._blocked("No estimation request was supplied.", missing=["request"])

        started = time.perf_counter()
        try:
            outcome = propose_station_assumptions(request, context.llm_provider)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Estimation failed: {str(exc)[:200]}")

        proposal = outcome.proposal
        # Capacity and operators are legitimately UNKNOWN — the estimator
        # says so rather than guessing, and that is a PARTIAL result.
        unresolved = [
            field
            for field in ("capacity", "operators")
            if getattr(proposal, field, None) is None
        ]
        status = SkillStatus.PARTIAL if unresolved else SkillStatus.SUCCESS

        method = getattr(proposal.cycle_time, "method", None)
        return SkillResult(
            status=status,
            data=proposal,
            provenance={"method": method.value if method else "UNKNOWN"},
            confidence=getattr(getattr(proposal, "cycle_time", None), "confidence", None)
            and proposal.cycle_time.confidence.value,
            unresolved_inputs=unresolved,
            warnings=list(getattr(outcome, "warnings", []) or []),
            trace=[
                self._entry(
                    status,
                    f"cycle time proposed by {method.value if method else 'unknown method'}"
                    + (f"; {', '.join(unresolved)} left unknown" if unresolved else ""),
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


# VALIDATION

class FactoryConceptBuilderSkill(Skill):
    """Convert a resolved concept draft into a runnable Factory."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="factory_concept_builder",
            version=_VERSION,
            name="Factory concept builder",
            description=(
                "Converts a concept draft into the Factory model the simulator reads. "
                "Refuses while a value the simulator needs is missing, rather than "
                "defaulting it."
            ),
            category=SkillCategory.VALIDATION,
            capabilities=("build_simulation_ready_factory",),
            prerequisites=("requirements_extraction",),
            input_types=("FactoryConceptDraft",),
            output_types=("tuple[Factory, str]",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.concept_validation import (
            ConceptNotReadyError,
            concept_to_factory,
            required_gaps,
        )

        draft = payload.get("draft") if isinstance(payload, dict) else payload
        if draft is None:
            return self._blocked("No concept draft was supplied.", missing=["draft"])

        started = time.perf_counter()
        try:
            factory, product_id = concept_to_factory(draft)
        except ConceptNotReadyError as exc:
            # The DOMAIN's own message, verbatim.
            return self._blocked(str(exc), missing=[g.key for g in required_gaps(draft)])
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Concept conversion failed: {str(exc)[:200]}")

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=(factory, product_id),
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{len(factory.machines)} machine(s), {len(factory.buffers)} buffer(s)",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


class LayoutGenerationSkill(Skill):
    """Place stations on the floor."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="layout_generation",
            version=_VERSION,
            name="Layout generation",
            description="Produces an initial placement for every station. Affects layout validity, never throughput.",
            category=SkillCategory.PLANNING,
            capabilities=("generate_factory_layout",),
            prerequisites=("requirements_extraction",),
            # Takes the DRAFT, not the Factory: `generate_initial_layout`
            # reads stage footprints and the floor envelope, which live on
            # the concept rather than on the converted model.
            input_types=("FactoryConceptDraft",),
            output_types=("FactoryLayout",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        # Imported inside the try: an ImportError here would otherwise
        # escape, and a skill that raises breaks the contract every caller
        # relies on.
        started = time.perf_counter()
        try:
            from app.services.concept_builder import generate_initial_layout
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Layout generation is unavailable: {str(exc)[:200]}")

        draft = payload.get("draft") if isinstance(payload, dict) else payload
        if draft is None:
            return self._blocked("No concept draft was supplied.", missing=["draft"])

        try:
            layout = generate_initial_layout(draft)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Layout generation failed: {str(exc)[:200]}")

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=layout,
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{len(layout.placements)} station(s) placed",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


class LayoutValidationSkill(Skill):
    """Check a layout against the floor and the clearances."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="layout_validation",
            version=_VERSION,
            name="Layout validation",
            description="Checks placement against floor bounds, overlaps and clearances.",
            category=SkillCategory.VALIDATION,
            capabilities=("validate_factory_layout",),
            prerequisites=("layout_generation",),
            input_types=("Factory", "FactoryLayout", "str"),
            output_types=("LayoutValidationResult",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        started = time.perf_counter()
        try:
            from app.services.constraints import validate_layout
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Layout validation is unavailable: {str(exc)[:200]}")

        if not isinstance(payload, dict):
            return self._blocked(
                "Layout validation needs a factory, a layout and a product id.",
                missing=["factory", "layout", "product_id"],
            )
        factory, layout = payload.get("factory"), payload.get("layout")
        product_id = payload.get("product_id")
        if factory is None or layout is None or product_id is None:
            return self._blocked(
                "Layout validation needs a factory, a layout and a product id.",
                missing=["factory", "layout", "product_id"],
            )

        try:
            report = validate_layout(factory, layout, product_id)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Layout validation failed: {str(exc)[:200]}")

        violations = list(getattr(report, "violations", report) or [])
        errors = [v for v in violations if getattr(v, "severity", "") == "ERROR"]
        status = SkillStatus.PARTIAL if errors else SkillStatus.SUCCESS
        return SkillResult(
            status=status,
            data=report,
            warnings=[getattr(v, "message", str(v)) for v in violations],
            trace=[
                self._entry(
                    status,
                    f"{len(violations)} violation(s), {len(errors)} blocking",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


# SIMULATION

class FactorySimulationSkill(Skill):
    """Run the deterministic simulation."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="factory_simulation",
            version=_VERSION,
            name="Factory simulation",
            description=(
                "Runs the deterministic discrete-event simulation. Bit-identical for "
                "identical inputs. No language model is involved at any point."
            ),
            category=SkillCategory.SIMULATION,
            capabilities=("simulate_factory", "verify_throughput"),
            prerequisites=("factory_concept_builder",),
            input_types=("Factory", "str"),
            output_types=("SimulationResult",),
            supported_provenance=("SIMULATED",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.simulation import run_simulation

        if not isinstance(payload, dict):
            return self._blocked("Simulation needs a factory and a product id.", missing=["factory", "product_id"])
        factory, product_id = payload.get("factory"), payload.get("product_id")
        if factory is None or product_id is None:
            return self._blocked(
                "Simulation needs a factory and a product id.", missing=["factory", "product_id"]
            )

        started = time.perf_counter()
        try:
            result = run_simulation(factory, product_id)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Simulation failed: {str(exc)[:200]}")

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=result,
            provenance={"throughput": "SIMULATED"},
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{result.completed_units:,.0f} of {result.target_units:,.0f} units/day",
                    elapsed_seconds=time.perf_counter() - started,
                    simulations_run=1,
                )
            ],
        )


class BottleneckAnalysisSkill(Skill):
    """Report the limiting stage of a completed simulation."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="bottleneck_analysis",
            version=_VERSION,
            name="Bottleneck analysis",
            description=(
                "Reports the limiting stage of a completed run. This reads the "
                "simulator's own ranking rather than recomputing it, so it can never "
                "disagree with the result it describes."
            ),
            category=SkillCategory.SIMULATION,
            capabilities=("identify_limiting_stage",),
            prerequisites=("factory_simulation",),
            input_types=("SimulationResult",),
            output_types=("str",),
            supported_provenance=("SIMULATED",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        result = payload.get("simulation") if isinstance(payload, dict) else payload
        if result is None:
            return self._blocked("No simulation result was supplied.", missing=["simulation"])

        # No None check: SystemKPI.bottleneck_machine_id is a required str,
        # so every completed run has one. A guard here would be unreachable
        # code implying a state the domain model forbids.
        stage = result.system.bottleneck_machine_id
        met = result.demand_met
        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=stage,
            provenance={"limiting_stage": "SIMULATED"},
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{'limiting stage' if met else 'bottleneck'}: {stage}",
                )
            ],
        )


# OPTIMIZATION

class StrategyGenerationSkill(Skill):
    """Generate candidate plans for a goal."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="strategy_generation",
            version=_VERSION,
            name="Strategy generation",
            description=(
                "Generates candidate plans from the baseline. Candidate generation only — "
                "no candidate is preferred until it has been simulated."
            ),
            category=SkillCategory.OPTIMIZATION,
            capabilities=("generate_improvement_candidates",),
            prerequisites=("factory_simulation",),
            input_types=("Factory", "OptimizationGoal"),
            output_types=("list[Candidate]",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.candidate_generator import generate_candidates

        if not isinstance(payload, dict):
            return self._blocked("Strategy generation needs a factory, product and goal.", missing=["factory", "product_id", "goal"])
        factory, product_id, goal = payload.get("factory"), payload.get("product_id"), payload.get("goal")
        if factory is None or product_id is None or goal is None:
            return self._blocked(
                "Strategy generation needs a factory, a product id and a goal.",
                missing=["factory", "product_id", "goal"],
            )

        started = time.perf_counter()
        try:
            candidates = generate_candidates(factory, product_id, goal, payload.get("layout"))
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Strategy generation failed: {str(exc)[:200]}")

        if not candidates:
            return self._not_applicable(
                "No lever the generator knows about applies to this factory and goal."
            )

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=candidates,
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{len(candidates)} candidate(s) generated",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


class SensitivityAnalysisSkill(Skill):
    """Test whether an uncertain estimate changes the decision."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="sensitivity_analysis",
            version=_VERSION,
            name="Sensitivity analysis",
            description=(
                "Runs the concept across an estimate's plausible range and reports whether "
                "the engineering decision changes: ROBUST, SENSITIVE, NOT ACHIEVABLE or "
                "CRITICAL UNKNOWN. Every probe is a real simulation."
            ),
            category=SkillCategory.OPTIMIZATION,
            capabilities=("assess_decision_robustness",),
            prerequisites=("factory_concept_builder",),
            input_types=("FactoryConceptDraft",),
            output_types=("RobustnessResult",),
            supported_provenance=("SIMULATED",),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.robustness import assess_robustness

        if not isinstance(payload, dict):
            return self._blocked("Robustness needs a draft, a stage and a range.", missing=["draft", "stage_id", "low", "high"])
        draft, stage_id = payload.get("draft"), payload.get("stage_id")
        low, high, working = payload.get("low"), payload.get("high"), payload.get("working")
        if draft is None or stage_id is None or low is None or high is None:
            return self._blocked(
                "Robustness needs a draft, a stage and a plausible range.",
                missing=["draft", "stage_id", "low", "high"],
            )

        started = time.perf_counter()
        try:
            result = assess_robustness(
                draft, stage_id, low=float(low), high=float(high), working=float(working or low)
            )
        except ValueError as exc:
            return self._blocked(str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Robustness assessment failed: {str(exc)[:200]}")

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=result,
            provenance={"verdict": "SIMULATED"},
            trace=[
                self._entry(
                    SkillStatus.SUCCESS,
                    f"{result.verdict.value}: {result.statement[:90]}",
                    elapsed_seconds=time.perf_counter() - started,
                    simulations_run=result.simulations_run,
                )
            ],
        )


# DISCOVERY

class StationRequirementSkill(Skill):
    """Derive what a station must achieve, before searching for equipment."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="station_requirement_derivation",
            version=_VERSION,
            name="Station requirement derivation",
            description=(
                "Derives a structured requirement for one station from the concept. "
                "Fields the concept does not state stay UNKNOWN rather than being invented."
            ),
            category=SkillCategory.DISCOVERY,
            capabilities=("derive_station_requirement",),
            prerequisites=("factory_concept_builder",),
            input_types=("FactoryConceptDraft", "str"),
            output_types=("EquipmentRequirement",),
            supported_provenance=("CUSTOMER", "ENGINEERING_ESTIMATE", "CALCULATED", "UNKNOWN"),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.services.equipment_discovery import requirement_from_concept

        if not isinstance(payload, dict):
            return self._blocked("A concept draft and station id are needed.", missing=["draft", "station_id"])
        draft, station_id = payload.get("draft"), payload.get("station_id")
        if draft is None or station_id is None:
            return self._blocked(
                "A concept draft and a station id are needed.", missing=["draft", "station_id"]
            )

        try:
            requirement = requirement_from_concept(draft, station_id)
        except ValueError as exc:
            return self._blocked(str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Requirement derivation failed: {str(exc)[:200]}")

        return SkillResult(
            status=SkillStatus.SUCCESS,
            data=requirement,
            provenance={"basis": requirement.provenance},
            trace=[self._entry(SkillStatus.SUCCESS, requirement.provenance[:100])],
        )


class EquipmentDiscoverySkill(Skill):
    """Find source-backed equipment candidates and check them."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="equipment_discovery",
            version=_VERSION,
            name="Equipment discovery",
            description=(
                "Matches a station requirement against source-backed equipment data. "
                "Every check is PASS, FAIL or UNKNOWN — UNKNOWN never counts as PASS, "
                "and no price is ever invented."
            ),
            category=SkillCategory.DISCOVERY,
            capabilities=("find_equipment_candidates",),
            prerequisites=("station_requirement_derivation",),
            input_types=("EquipmentRequirement",),
            output_types=("list[CompatibilityReport]",),
            uses_external_data=True,
            side_effects=(SideEffect.READS_LOCAL_DATA,),
            supported_provenance=("MANUFACTURER", "UNKNOWN"),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        """Search every registered catalogue for the required capability."""
        from app.models.equipment_discovery import PriceStatus
        from app.services.equipment_compatibility import check_compatibility
        from app.services.equipment_discovery import search_catalogs, source_backed_only

        requirement = payload.get("requirement") if isinstance(payload, dict) else payload
        if requirement is None:
            return self._blocked("No station requirement was supplied.", missing=["requirement"])

        started = time.perf_counter()
        try:
            search = search_catalogs(requirement)
            candidates = source_backed_only(search.candidates)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Equipment lookup failed: {str(exc)[:200]}")

        if requirement.required_capability is None:
            return self._not_applicable(
                f"No researched equipment capability exists for a "
                f"'{requirement.process_category}' station."
            )
        if not candidates:
            return self._not_applicable(
                f"No catalogue record declares "
                f"{requirement.required_capability.value} for this station."
            )

        # Zipped rather than looked up: the report deliberately does not
        # carry its candidate, so the pairing is made here and kept local.
        pairs = [(c, check_compatibility(requirement, c)) for c in candidates]
        reports = [report for _, report in pairs]

        unpriced = [c for c, _ in pairs if c.price_status is PriceStatus.QUOTE_REQUIRED]
        unavailable = search.unavailable

        # SUCCESS IS UNREACHABLE IN THIS BUILD, DELIBERATELY.
        status = SkillStatus.PARTIAL if (unpriced or unavailable) else SkillStatus.SUCCESS

        detail = f"{len(reports)} candidate(s) checked"
        if unpriced:
            detail += f"; {len(unpriced)} need a quotation"
        if unavailable:
            detail += f"; {len(unavailable)} catalogue(s) could not be consulted"

        return SkillResult(
            status=status,
            data=reports,
            evidence=[s for c in candidates for s in c.sources],
            unresolved_inputs=(
                [f"price:{c.model}" for c in unpriced]
                + [f"catalog:{r.descriptor.catalog_id}" for r in unavailable]
            ),
            trace=[
                self._entry(status, detail, elapsed_seconds=time.perf_counter() - started)
            ],
        )


# INTEGRATION

class SiemensHandoffSkill(Skill):
    """Build the model in Plant Simulation and verify it by reading it back."""

    @property
    def definition(self) -> SkillDefinition:
        return SkillDefinition(
            id="siemens_handoff",
            version=_VERSION,
            name="Siemens Plant Simulation handoff",
            description=(
                "Builds the model through Plant Simulation's automation interface, saves "
                "it, reopens the saved file and reads the topology back out of it. "
                "Reports what was verified, never what was merely attempted."
            ),
            category=SkillCategory.INTEGRATION,
            capabilities=("export_to_plant_simulation",),
            prerequisites=("factory_concept_builder",),
            input_types=("FactoryMindExchange",),
            output_types=("HandoffResult",),
            uses_external_data=True,
            side_effects=(SideEffect.WRITES_FILE, SideEffect.CONTROLS_EXTERNAL_TOOL),
        )

    def execute(self, payload: Any, context: SkillContext) -> SkillResult:
        from app.integrations.plant_simulation import (
            PlantSimulationAdapter,
            PlantSimulationUnavailable,
        )

        if not isinstance(payload, dict):
            return self._blocked("The handoff needs an exchange package.", missing=["package"])
        package, save_path = payload.get("package"), payload.get("save_path")
        if package is None:
            return self._blocked("The handoff needs an exchange package.", missing=["package"])

        started = time.perf_counter()
        adapter = PlantSimulationAdapter()
        try:
            adapter.connect()
        except PlantSimulationUnavailable as exc:
            # Not a failure of Fabrivium: the tool is absent on this
            # machine, which is an environment fact.
            return self._not_applicable(str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Could not reach Plant Simulation: {str(exc)[:200]}")

        try:
            result = adapter.build(package, save_path=save_path)
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"Handoff failed: {str(exc)[:200]}")
        finally:
            adapter.close()

        status = SkillStatus.SUCCESS if result.fully_verified else SkillStatus.PARTIAL
        return SkillResult(
            status=status,
            data=result,
            provenance={"verification": "read back from the saved file"},
            warnings=list(result.errors),
            unresolved_inputs=[] if result.fully_verified else ["verified_model"],
            artifacts=[result.model_path] if result.model_path else [],
            trace=[
                self._entry(
                    status,
                    f"{result.stations_verified}/{len(result.stations)} stations verified",
                    elapsed_seconds=time.perf_counter() - started,
                )
            ],
        )


# Registration

# Every first-party skill, in the order a workflow would meet them.
BUILTIN_SKILLS: tuple[type[Skill], ...] = (
    ProductUnderstandingSkill,
    RequirementsExtractionSkill,
    ProcessPlanningSkill,
    EngineeringEstimationSkill,
    FactoryConceptBuilderSkill,
    LayoutGenerationSkill,
    LayoutValidationSkill,
    FactorySimulationSkill,
    BottleneckAnalysisSkill,
    StrategyGenerationSkill,
    SensitivityAnalysisSkill,
    StationRequirementSkill,
    EquipmentDiscoverySkill,
    SiemensHandoffSkill,
)


def register_builtin_skills(registry: SkillRegistry | None = None) -> SkillRegistry:
    """Register every first-party skill."""
    target = registry or default_registry
    for skill_class in BUILTIN_SKILLS:
        skill = skill_class()
        if target.has(skill.definition.id):
            continue
        target.register(skill)
    return target
