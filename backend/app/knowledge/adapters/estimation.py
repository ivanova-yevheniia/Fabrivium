"""
Estimation knowledge — how Fabrivium produces a number nobody has measured.

CANONICAL SOURCE
----------------
``app.data.engineering_reference_data``. That module is already an explicit
knowledge base of one kind: every constant carries its meaning, unit, source
classification, rationale and applicability limits. This adapter publishes
it under the common contract; it adds no band, widens none, and drops none
of the limits.

THE CLASSIFICATION IS CARRIED, NOT TRANSLATED
---------------------------------------------
``ReferenceClass`` distinguishes a value traceable to the bundled demo
dataset from a value Fabrivium chose with its reasoning written down. Both
travel as the source's own word under the vocabulary name "ReferenceClass",
so a reader can go and look up what it means rather than trusting a mapping
this file invented.

A profile carries two bands, and they may in principle disagree about their
classification. Where they agree the item reports that class; where they do
not it reports "MIXED" and both bands' classes are in ``values``. Silently
reporting one of the two would be the more convenient lie.
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

ESTIMATION_ADAPTER_VERSION = "1.0.0"

_REFERENCE_MODULE = "app.data.engineering_reference_data"


def _band_values(band, prefix: str) -> dict[str, object]:
    return {
        f"{prefix}_low": band.low,
        f"{prefix}_high": band.high,
        f"{prefix}_unit": band.unit,
        f"{prefix}_meaning": band.meaning,
        f"{prefix}_source_class": band.source_class.value,
        f"{prefix}_rationale": band.rationale,
        f"{prefix}_applicability": band.applicability,
    }


def estimation_knowledge() -> list[EngineeringKnowledgeItem]:
    """Every documented estimation method and reference band."""
    from app.data.engineering_reference_data import (
        AUTOMATION_FACTORS,
        PROCESS_PROFILES,
        REFERENCE_DATASET_NAME,
        UNKNOWN_AUTOMATION_WIDENING,
    )

    items: list[EngineeringKnowledgeItem] = []

    for category, profile in sorted(PROCESS_PROFILES.items()):
        handling_class = profile.handling.source_class.value
        operation_class = profile.per_operation.source_class.value
        classification = (
            operation_class if handling_class == operation_class else "MIXED"
        )

        values: dict[str, object] = {
            "process_category": profile.process_category,
            "operation_noun": profile.operation_noun,
            "dataset_station_seconds": profile.dataset_station_seconds,
        }
        values.update(_band_values(profile.handling, "handling"))
        values.update(_band_values(profile.per_operation, "per_operation"))

        items.append(
            EngineeringKnowledgeItem(
                id=f"estimation.profile.{profile.process_category}",
                version=ESTIMATION_ADAPTER_VERSION,
                kind=KnowledgeKind.ESTIMATION_METHOD,
                category=KnowledgeCategory.ESTIMATION,
                domain=KnowledgeDomain.ELECTRONICS_ASSEMBLY,
                title=f"Preliminary cycle-time bands for {profile.process_category}",
                description=(
                    f"Two documented ranges for the {profile.process_category} family: the "
                    f"handling that does not repeat with the operation count, and one "
                    f"repetition of the characteristic operation "
                    f"({profile.operation_noun}). Bands rather than single figures, because "
                    f"a single figure at concept stage would be false precision — the width "
                    f"of the answer is meant to reflect the width of what is actually known."
                ),
                provenance=Provenance(
                    source_kind=SourceKind.REFERENCE_TABLE,
                    source_reference=f"{_REFERENCE_MODULE}.PROCESS_PROFILES['{category}']",
                    statement=(
                        f"A documented reference band in Fabrivium's own estimation data. "
                        f"Not an industry standard. Anchored against the '{REFERENCE_DATASET_NAME}' "
                        f"station value of {profile.dataset_station_seconds} s, which is the "
                        f"only measured figure available for this family."
                    ),
                    classification_vocabulary="ReferenceClass",
                    classification=classification,
                ),
                applicability=Applicability(
                    scope=profile.per_operation.applicability,
                    process_categories=(profile.process_category,),
                    not_valid_for=(
                        f"{profile.handling.applicability} A specific machine's datasheet "
                        f"always overrides these bands."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values=values,
                status=classification,
                tags=("estimation", "cycle-time", profile.process_category),
            )
        )

    for level, band in sorted(AUTOMATION_FACTORS.items()):
        items.append(
            EngineeringKnowledgeItem(
                id=f"estimation.automation_factor.{level.lower()}",
                version=ESTIMATION_ADAPTER_VERSION,
                kind=KnowledgeKind.ESTIMATION_METHOD,
                category=KnowledgeCategory.ESTIMATION,
                domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
                title=f"Automation factor — {level}",
                description=(
                    f"{band.meaning} Scales the PER-OPERATION part of an estimate only; "
                    f"handling is dominated by fixture and transport design rather than by "
                    f"how the operation itself is performed. Deliberately coarse — three "
                    f"steps, not a curve — because a finer scale would imply a precision "
                    f"that does not exist."
                ),
                provenance=Provenance(
                    source_kind=SourceKind.REFERENCE_TABLE,
                    source_reference=f"{_REFERENCE_MODULE}.AUTOMATION_FACTORS['{level}']",
                    statement=band.rationale,
                    classification_vocabulary="ReferenceClass",
                    classification=band.source_class.value,
                ),
                applicability=Applicability(
                    scope=band.applicability,
                    not_valid_for=(
                        "Commercial use without validation against measurement. Fabrivium "
                        "has no measured basis for these factors and does not claim one."
                    ),
                ),
                exposure=KnowledgeExposure.DERIVED_VALUE,
                values=_band_values(band, "factor") | {"automation_level": level},
                status=band.source_class.value,
                tags=("estimation", "automation"),
            )
        )

    items.append(
        EngineeringKnowledgeItem(
            id="estimation.unknown_automation_widening",
            version=ESTIMATION_ADAPTER_VERSION,
            kind=KnowledgeKind.ESTIMATION_METHOD,
            category=KnowledgeCategory.ESTIMATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="An unstated automation level widens the estimate rather than shifting it",
            description=(
                "When the engineer leaves automation unknown, Fabrivium does not pick a "
                "level. The band is stretched down to cover the automatic case while the "
                "manual case sets the top, so not knowing makes the answer less precise "
                "rather than differently precise."
            ),
            provenance=Provenance(
                source_kind=SourceKind.REFERENCE_TABLE,
                source_reference=f"{_REFERENCE_MODULE}.UNKNOWN_AUTOMATION_WIDENING",
                statement=UNKNOWN_AUTOMATION_WIDENING.rationale,
                classification_vocabulary="ReferenceClass",
                classification=UNKNOWN_AUTOMATION_WIDENING.source_class.value,
            ),
            applicability=Applicability(
                scope=UNKNOWN_AUTOMATION_WIDENING.applicability,
            ),
            exposure=KnowledgeExposure.DERIVED_VALUE,
            values=_band_values(UNKNOWN_AUTOMATION_WIDENING, "widening"),
            status=UNKNOWN_AUTOMATION_WIDENING.source_class.value,
            tags=("estimation", "automation", "uncertainty"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="estimation.composition_method",
            version=ESTIMATION_ADAPTER_VERSION,
            kind=KnowledgeKind.ESTIMATION_METHOD,
            category=KnowledgeCategory.ESTIMATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="How a preliminary cycle-time band is composed",
            description=(
                "band = handling + (operations x per-operation) x automation factor. "
                "Fabrivium composes ranges rather than recalling a number, so every figure "
                "it produces can be taken apart. The arithmetic is stated in the estimate's "
                "own basis text, and a test asserts the composed manual band still contains "
                "the one real station value available for each family."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.local_estimator.estimate",
                statement="The deterministic composition implemented in Fabrivium's estimator.",
            ),
            applicability=Applicability(
                scope=(
                    "The families that have a documented profile. Fabrivium refuses to "
                    "estimate a family it holds no bands for, and asks for information "
                    "instead of extrapolating from a family the process does not resemble."
                ),
                not_valid_for=(
                    "Producing a specification. A composed band is a preliminary "
                    "engineering assumption and is labelled as one."
                ),
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("estimation", "method", "deterministic"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="estimation.preference_order",
            version=ESTIMATION_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.ESTIMATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Order of preference when a value is not known",
            description=(
                "Derived first — arithmetic on values the concept already holds. Then a "
                "language model, which structures the engineer's own description into a "
                "range. Then the deterministic local composition. Then, if none of those "
                "apply, the request for information is stated plainly with the specific "
                "questions that would unblock it. Whichever mechanism produced a range, the "
                "VALUE is an ENGINEERING_ESTIMATE — a model is a mechanism for constructing "
                "an estimate, never the epistemic source of a number, and there is "
                "deliberately no 'AI provenance' anywhere in Fabrivium."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.services.estimation",
                statement="The resolution order implemented in Fabrivium's estimation assistant.",
                classification_vocabulary="ValueSource",
                classification="ENGINEERING_ESTIMATE",
            ),
            applicability=Applicability(
                scope="Every unknown engineering value the concept builder offers to resolve.",
                not_valid_for=(
                    "Values that are only knowable (a schedule, a budget) or only "
                    "purchasable (an equipment price). Those are asked for, never estimated."
                ),
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("estimation", "provenance", "method"),
        )
    )

    items.append(
        EngineeringKnowledgeItem(
            id="estimation.estimate_is_not_a_specification",
            version=ESTIMATION_ADAPTER_VERSION,
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.ESTIMATION,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="An estimate is never a specification, a customer fact or a manufacturer figure",
            description=(
                "An estimated range resolves to exactly one working scalar before it reaches "
                "the deterministic simulator, and the record of the range stays beside it so "
                "the question 'why 45 seconds?' can always be answered. The distinction "
                "between an estimate, a customer statement and a published figure is carried "
                "as enum members rather than as adjectives, so a user-interface label cannot "
                "blur it."
            ),
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="app.models.uncertainty",
                statement="The representation rule implemented in Fabrivium's uncertainty model.",
                classification_vocabulary="ValueSource",
                classification="ENGINEERING_ESTIMATE",
            ),
            applicability=Applicability(
                scope="Every value Fabrivium estimates during concept design.",
            ),
            exposure=KnowledgeExposure.POINTER,
            tags=("estimation", "provenance", "uncertainty"),
        )
    )

    return items
