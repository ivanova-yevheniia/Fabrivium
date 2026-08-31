"""The canonical process-family vocabulary, served as a contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.data.engineering_reference_data import PROCESS_PROFILES, profile_for
from app.services.concept_builder import _STAGE_VOCABULARY
from app.services.equipment_discovery import CAPABILITY_BY_PROCESS_TYPE


class ProcessFamily(BaseModel):
    """One selectable process family and what is known about it."""

    model_config = {"frozen": True}

    # The value that travels as ``ConceptStage.process_type``.
    process_type: str = Field(..., min_length=1)

    # How the family is written on screen.
    label: str = Field(..., min_length=1)

    # The words in a brief that select this family.
    aliases: list[str] = Field(default_factory=list)

    # True when ``engineering_reference_data`` has a band for this family, i.e.
    has_reference_estimate: bool = False

    #: What "one operation" means for this family ("screw", "check",
    #: "carton step"), when there is a reference profile to say so.
    operation_noun: str | None = None

    # True when a researched equipment catalogue exists for this family.
    has_equipment_evidence: bool = False


class ProcessFamilyCatalog(BaseModel):
    """Every family, plus the totals a UI needs to describe its own limits."""

    families: list[ProcessFamily]

    # How many families have a reference band.
    families_with_reference_estimate: int
    families_with_equipment_evidence: int

    #: Reference-band coverage is anchored to one measured dataset, and any
    #: screen offering an estimate should be able to name it.
    reference_dataset_name: str


def process_family_catalog() -> ProcessFamilyCatalog:
    """Build the catalog from the tables that already define it."""
    from app.data.engineering_reference_data import REFERENCE_DATASET_NAME

    families: list[ProcessFamily] = []
    for label, process_type, aliases in _STAGE_VOCABULARY:
        profile = profile_for(process_type)
        families.append(
            ProcessFamily(
                process_type=process_type,
                label=label,
                aliases=list(aliases),
                has_reference_estimate=profile is not None,
                operation_noun=profile.operation_noun if profile is not None else None,
                has_equipment_evidence=process_type in CAPABILITY_BY_PROCESS_TYPE,
            )
        )

    return ProcessFamilyCatalog(
        families=families,
        families_with_reference_estimate=sum(1 for f in families if f.has_reference_estimate),
        families_with_equipment_evidence=sum(1 for f in families if f.has_equipment_evidence),
        reference_dataset_name=REFERENCE_DATASET_NAME,
    )


def known_process_types() -> frozenset[str]:
    """The process types a stage may carry and have anything look it up."""
    return frozenset(process_type for _, process_type, _ in _STAGE_VOCABULARY)


def unknown_process_type_note(process_type: str) -> str | None:
    """Explain, in one sentence, what an unrecognised *process_type* costs."""
    if process_type.strip().lower() in known_process_types():
        return None
    known = ", ".join(sorted(known_process_types()))
    return (
        f"'{process_type}' is not one of Fabrivium's process families, so no reference "
        f"cycle-time band, equipment search or station asset will match it. The operation "
        f"still simulates once you supply a cycle time. Known families: {known}."
    )


# Guard the composition rather than trusting it.
_ORPHANED_PROFILES = set(PROCESS_PROFILES) - {pt for _, pt, _ in _STAGE_VOCABULARY}
assert not _ORPHANED_PROFILES, (
    f"engineering_reference_data has profiles for process categories no stage can "
    f"carry: {sorted(_ORPHANED_PROFILES)}. Either add them to _STAGE_VOCABULARY or "
    f"remove the profile — an unreachable band is a band that silently never applies."
)
