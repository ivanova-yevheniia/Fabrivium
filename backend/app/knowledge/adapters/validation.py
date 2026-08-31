"""
Validation knowledge — what must be known before something may run, and what
fails closed.

CANONICAL SOURCE
----------------
``app.services.concept_validation.concept_gaps``. The knowledge is not a
table anybody could read; it is a decision the function makes per value.
So the adapter ASKS the function: it builds an empty probe concept with one
empty probe stage and reads back every gap the canonical rule engine
reports, with the severity and the reason the engine itself gives.

WHY A PROBE RATHER THAN A LIST
------------------------------
A hand-written list of "the required inputs" is the copy this whole layer
exists to avoid — and it is the copy most likely to drift, because the
required set has already changed once in this product's history. Running the
real engine means a value that becomes blocking appears here as blocking on
the next build, with the engine's own sentence explaining why.

The probe is discarded immediately. It is never simulated, never converted,
never persisted, and nothing downstream sees it.

STAGE KEYS ARE GENERALISED
--------------------------
The engine emits stage gaps as ``stage.<stage-id>.cycle_time``. The probe's
stage id is an artefact of the probe, so it is replaced by ``stage.*`` and
the real key shape is kept in ``values`` — a knowledge item about "every
stage needs a cycle time" must not appear to be about one stage.
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

VALIDATION_ADAPTER_VERSION = "1.0.0"

#: The probe stage's id. Chosen so that a key built from it is obviously not
#: a real stage if one ever escapes into a report.
_PROBE_STAGE_ID = "knowledge-probe-stage"

_VALIDATION_MODULE = "app.services.concept_validation"


def _generalise(key: str) -> tuple[str, bool]:
    """(`stage.*.cycle_time`, True) for a stage gap; (key, False) otherwise."""
    prefix = f"stage.{_PROBE_STAGE_ID}."
    if key.startswith(prefix):
        return f"stage.*.{key[len(prefix):]}", True
    return key, False


def validation_knowledge() -> list[EngineeringKnowledgeItem]:
    """Every input requirement the concept validator enforces, plus the
    fail-closed rules that are procedures rather than tables."""
    from app.integrations.plant_simulation.adapter import TierStatus, VerificationTier
    from app.models.concept import ConceptStage, FactoryConceptDraft
    from app.services.concept_validation import GapSeverity, concept_gaps

    probe = FactoryConceptDraft(
        name="Knowledge base probe",
        stages=[
            ConceptStage(
                id=_PROBE_STAGE_ID,
                name="Probe stage",
                process_type="probe",
            )
        ],
    )

    items: list[EngineeringKnowledgeItem] = []

    for gap in concept_gaps(probe):
        key, per_stage = _generalise(gap.key)
        blocking = gap.severity is GapSeverity.REQUIRED

        items.append(
            EngineeringKnowledgeItem(
                id=f"validation.required_input.{key.replace('.', '_').replace('*', 'any')}",
                version=VALIDATION_ADAPTER_VERSION,
                kind=KnowledgeKind.VALIDATION_RULE,
                category=KnowledgeCategory.VALIDATION,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=(
                    f"{gap.label.replace('Probe stage ', '').strip().capitalize()} — "
                    f"{'blocks simulation' if blocking else 'does not block simulation'}"
                ),
                description=(
                    f"{gap.reason} "
                    + (
                        "Simulation cannot run until this value is supplied, and it is "
                        "never defaulted."
                        if blocking
                        else "Reported when missing, but the simulator does not read it, so "
                        "it does not block. Blocking on a value the physics ignores would "
                        "be theatre."
                    )
                ),
                provenance=Provenance(
                    source_kind=SourceKind.IMPLEMENTED_RULE,
                    source_reference=f"{_VALIDATION_MODULE}.concept_gaps",
                    statement=(
                        "Read back from Fabrivium's own concept validator, which decides "
                        "whether a gap blocks by whether the deterministic simulator "
                        "actually consumes the value."
                    ),
                ),
                applicability=Applicability(
                    scope=(
                        "Every stage of every concept."
                        if per_stage
                        else "Every factory concept before it may be simulated."
                    ),
                    not_valid_for=(
                        "Ranking how important a value is commercially. Whether an input "
                        "blocks is a fact about the simulator, not a judgement about "
                        "the project."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values={
                    "gap_key": key,
                    "severity": gap.severity.value,
                    "blocks_simulation": blocking,
                    "reason": gap.reason,
                    "per_stage": per_stage,
                },
                status=gap.severity.value,
                tags=(
                    "validation",
                    "required-input" if blocking else "optional-input",
                ),
            )
        )

    items.append(
        EngineeringKnowledgeItem(
            id="validation.simulation_readiness",
            version=VALIDATION_ADAPTER_VERSION,
            kind=KnowledgeKind.VALIDATION_RULE,
            category=KnowledgeCategory.VALIDATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="A concept is simulation-ready exactly when no required gap remains",
            description=(
                "There is deliberately no readiness percentage. A score would have to "
                "weight a missing cycle time against a missing budget, and no defensible "
                "weighting exists. Readiness is a verdict plus the list of what is still "
                "blocking it, and the composition of a concept is reported as counts by "
                "provenance — figures an engineer can point at and check."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference=f"{_VALIDATION_MODULE}.validate_concept",
                statement="The readiness verdict implemented in Fabrivium's concept validator.",
            ),
            applicability=Applicability(
                scope="Every factory concept.",
                not_valid_for="Judging whether the concept is a good design.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("validation", "readiness", "fail-closed"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="validation.route_integrity",
            version=VALIDATION_ADAPTER_VERSION,
            kind=KnowledgeKind.VALIDATION_RULE,
            category=KnowledgeCategory.VALIDATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="A product route is validated against the factory before any simulation runs",
            description=(
                "Route integrity is checked before any discrete-event work begins: every "
                "step must resolve to machines that exist and can serve it. The check is a "
                "pure function of the factory and the product, and a route that does not "
                "validate is refused rather than simulated with substitutions."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.route_validator.validate_route",
                statement="The pre-simulation check implemented in Fabrivium's route validator.",
            ),
            applicability=Applicability(
                scope="Every simulation run.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("validation", "simulation", "fail-closed"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="validation.handoff_verification_tiers",
            version=VALIDATION_ADAPTER_VERSION,
            kind=KnowledgeKind.VALIDATION_RULE,
            category=KnowledgeCategory.VALIDATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="A Siemens handoff is verified in four independent tiers, never one boolean",
            description=(
                "STRUCTURE (the right objects exist and hold the right values), LAYOUT "
                "(they sit in distinct, non-overlapping, readable places), FLOW (Source "
                "reaches Drain through every one of them) and RUNTIME (a unit was actually "
                "put through and came out). They fail independently: a green STRUCTURE says "
                "nothing about LAYOUT. A tier that was not attempted is NOT_RUN — never "
                "VERIFIED, and never quietly folded into the others."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.integrations.plant_simulation.adapter.VerificationTier",
                statement=(
                    "The verification model implemented in Fabrivium's Plant Simulation "
                    "handoff adapter."
                ),
            ),
            applicability=Applicability(
                scope="Every generated Siemens Plant Simulation model.",
                not_valid_for=(
                    "Claiming the model is engineering-correct. The tiers verify that what "
                    "was written is what was read back, not that the design is right."
                ),
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values={
                "tiers": [t.value for t in VerificationTier],
                "tier_statuses": [s.value for s in TierStatus],
            },
            tags=("validation", "handoff", "fail-closed"),
        )
    )

    return items
