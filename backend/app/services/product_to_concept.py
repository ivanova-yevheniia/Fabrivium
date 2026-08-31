"""Product understanding → factory concept — Phase 19."""

from __future__ import annotations

from app.models.concept import (
    ConceptStage,
    FactoryConceptDraft,
    SourcedFloat,
    SourcedInt,
    ValueSource,
)
from app.models.process_draft import ManufacturingProcessDraft
from app.models.product import ProductUnderstanding
from app.services.concept_builder import buffers_between_stages, concept_from_brief
from app.services.process_planning import draft_to_stages


# Which parsed concept field each source-stated production requirement can corroborate.
_ATTRIBUTED: tuple[tuple[str, str, str | None], ...] = (
    ("production.target_per_day", "production_target", None),
    ("production.operators", "operators_available", None),
    ("production.floor_area", "floor_width", "floor_length"),
    ("production.shifts_per_day", "shifts_per_day", None),
    ("production.hours_per_shift", "hours_per_shift", None),
)


def _agrees(value: float | int | None, stated: float | None) -> bool:
    if value is None or stated is None:
        return False
    return abs(float(value) - float(stated)) < 1e-6


def _pair_agrees(values: list[float | int | None], stated: list[float | None]) -> bool:
    """Whether one COMPOUND statement describes the values it projects onto."""
    present = [float(v) for v in values if v is not None]
    quoted = [float(q) for q in stated if q is not None]
    if len(present) != len(values) or len(quoted) != len(values):
        return False

    remaining = list(quoted)
    for value in present:
        match = next((q for q in remaining if abs(value - q) < 1e-6), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


def attribute_sources(
    draft: FactoryConceptDraft, understanding: ProductUnderstanding
) -> FactoryConceptDraft:
    """Re-label the production requirements by who actually stated them."""
    stated = {item.key: item for item in understanding.source_production_requirements}
    updates: dict[str, object] = {}

    for key, primary, secondary in _ATTRIBUTED:
        source = stated.get(key)
        fields = [name for name in (primary, secondary) if name is not None]
        values = [getattr(draft, name).value for name in fields]
        if all(value is None for value in values):
            continue

        # ONE DECISION PER REQUIREMENT, NOT ONE PER FIELD (G12).
        quoted = [source.quantity, source.quantity_secondary] if source else [None, None]
        corroborated = source is not None and (
            _pair_agrees(values, quoted[: len(fields)])
            if len(fields) > 1
            else _agrees(values[0], quoted[0])
        )

        if corroborated:
            page = f", page {source.evidence.page}" if source.evidence.page else ""
            attribution = {
                "source": ValueSource.CUSTOMER,
                "detail": f"Stated by the customer in {source.evidence.document_name}{page}",
            }
        else:
            attribution = {
                "source": ValueSource.ENGINEER,
                "detail": "Entered during engineering setup. The source document does not state it.",
            }

        for name in fields:
            current = getattr(draft, name)
            if current.value is None:
                continue
            updates[name] = current.model_copy(update=attribution)

    return draft.model_copy(update=updates) if updates else draft


class ProcessNotAcceptedError(ValueError):
    """The draft still holds operations nobody has reviewed."""


class RequirementsUnresolvedError(ValueError):
    """The source states a manufacturing requirement nothing answers."""


def concept_from_product(
    understanding: ProductUnderstanding,
    process: ManufacturingProcessDraft,
    requirements_brief: str,
    *,
    name: str | None = None,
    allow_unresolved_requirements: bool = False,
) -> FactoryConceptDraft:
    """Build a concept draft from an accepted process and a requirements brief."""
    if not process.accepted:
        raise ProcessNotAcceptedError(
            "No manufacturing operations have been accepted yet. Review the proposed process first."
        )
    if process.pending:
        pending = ", ".join(op.name for op in process.pending)
        raise ProcessNotAcceptedError(
            f"These operations are still unreviewed: {pending}. Accept or reject each one first."
        )

    if not allow_unresolved_requirements:
        # Imported here rather than at module scope: coverage reads the
        # two modules that otherwise only share a direction.
        from app.services.requirement_coverage import coverage_for

        coverage = coverage_for(understanding, process)
        if coverage.approval_blocked:
            unresolved = ", ".join(item.label for item in coverage.critical_unresolved)
            raise RequirementsUnresolvedError(
                f"The source states requirements that no operation answers: {unresolved}. "
                f"Add or link an operation, or record explicitly that they are out of scope."
            )

    # Production requirements come from the existing extractor, unchanged —
    # and are then re-attributed, because who stated a value is a different
    # question from what the value is. See `attribute_sources`.
    base = attribute_sources(
        concept_from_brief(requirements_brief, name=name or understanding.product_name),
        understanding,
    )

    stages = [
        ConceptStage(
            id=spec["id"],
            name=spec["name"],
            process_type=spec["process_type"],
            # Every simulation parameter starts UNKNOWN.
            cycle_time=SourcedFloat.unknown(),
            capacity=SourcedInt.unknown(),
            operators_required=SourcedInt.unknown(),
            width=SourcedFloat.unknown(),
            length=SourcedFloat.unknown(),
            purchase_cost=SourcedFloat.unknown(),
            # The link back to the operation the engineer reviewed.
            source_operation_id=spec["source_operation_id"],
        )
        for spec in draft_to_stages(process)
    ]

    draft = base.model_copy(
        update={
            "name": name or understanding.product_name,
            "product_name": understanding.product_name,
            "stages": stages,
        }
    )
    # Buffers follow the route, exactly as the brief path builds them.
    return draft.model_copy(update={"buffers": buffers_between_stages(draft)})


def station_context(
    understanding: ProductUnderstanding,
    process: ManufacturingProcessDraft,
    stage_id: str,
) -> dict[str, object]:
    """Product context for one stage, for Phase 18B and Phase 16."""
    specs = {spec["id"]: spec for spec in draft_to_stages(process)}
    spec = specs.get(stage_id)
    if spec is None:
        return {}

    operation = next((op for op in process.accepted if op.id == spec["source_operation_id"]), None)
    if operation is None:
        return {}

    context: dict[str, object] = {
        "product_name": understanding.product_name,
        # The reviewed operation this stage came from.
        "operation_id": operation.id,
        "operation": operation.name,
        "operation_description": operation.description,
        "why_this_station_exists": operation.basis,
    }
    if operation.repeated_operations:
        context["repeated_operations"] = operation.repeated_operations

    material = understanding.fact("material.enclosure")
    if material and material.known:
        context["material"] = material.value

    dimensions = understanding.fact("dimensions.overall")
    if dimensions and dimensions.known:
        context["product_dimensions"] = dimensions.value

    return context


def describe_for_estimator(context: dict[str, object]) -> str:
    """A one-line operation description built from product context."""
    if not context:
        return ""

    parts = [str(context.get("operation_description") or context.get("operation") or "")]
    if context.get("material"):
        parts.append(f"Material: {context['material']}.")
    if context.get("product_name"):
        parts.append(f"Product: {context['product_name']}.")
    return " ".join(p for p in parts if p).strip()
