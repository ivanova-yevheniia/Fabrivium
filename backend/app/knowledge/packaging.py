"""Engineering Skills — the future packaging contract. NOT IMPLEMENTED."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.knowledge.base import EngineeringKnowledgeBase
from app.knowledge.contract import Applicability, KnowledgeDomain


class OrganizationScope(str, Enum):
    """Whose knowledge a package carries."""

    # Ships with Fabrivium and applies to every project.
    BUILT_IN = "BUILT_IN"
    # One organisation's own standards, catalogues and engineering rules.
    ORGANIZATION = "ORGANIZATION"
    # Scoped to a single project — a customer-specific requirement set.
    PROJECT = "PROJECT"


class ManifestValidationStatus(str, Enum):
    """How far a package's contents have been checked."""

    # Ships with Fabrivium; its items are the knowledge base's own.
    BUILT_IN = "BUILT_IN"
    # Authored but not checked against a knowledge base.
    DRAFT = "DRAFT"
    # Every declared knowledge item resolves in the target knowledge base.
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class EngineeringSkillManifest:
    """The declaration of one Engineering Skill package."""

    skill_id: str
    name: str
    version: str
    domain: KnowledgeDomain
    organization_scope: OrganizationScope
    description: str
    owner: str
    applicability: Applicability
    validation_status: ManifestValidationStatus

    # Qualified knowledge item ids (`id@version`). Ids, not items.
    knowledge_items: tuple[str, ...] = ()

    # Other package ids this one needs.
    dependencies: tuple[str, ...] = ()

    #: Where the package's knowledge came from, as references a reader can
    #: follow: a document, a register, an internal procedure number.
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.skill_id.strip():
            raise ValueError("An engineering skill package needs an id.")
        if not self.version.strip():
            raise ValueError(
                f"Engineering skill package '{self.skill_id}' needs a version. A package "
                f"of engineering knowledge that cannot be cited by version cannot be "
                f"referenced by a decision that used it."
            )
        if not self.name.strip():
            raise ValueError(f"Engineering skill package '{self.skill_id}' needs a name.")
        if not self.owner.strip():
            raise ValueError(
                f"Engineering skill package '{self.skill_id}' names no owner. Unowned "
                f"engineering knowledge has nobody to ask when it turns out to be wrong."
            )

    @property
    def qualified_id(self) -> str:
        return f"{self.skill_id}@{self.version}"


def validate_manifest(
    manifest: EngineeringSkillManifest, base: EngineeringKnowledgeBase
) -> list[str]:
    """Every problem with *manifest* against *base*, as readable sentences."""
    problems: list[str] = []

    for qualified in manifest.knowledge_items:
        item_id, _, version = qualified.partition("@")
        try:
            base.get(item_id, version or None)
        except KeyError:
            problems.append(
                f"Package '{manifest.qualified_id}' declares knowledge item "
                f"'{qualified}', which does not resolve in knowledge base "
                f"version {base.version}."
            )

    if manifest.dependencies:
        problems.append(
            f"Package '{manifest.qualified_id}' declares dependencies "
            f"{list(manifest.dependencies)}, and Fabrivium has no package loader to "
            f"resolve them against. Dependencies are part of the future contract only."
        )

    return problems


def builtin_manifest(base: EngineeringKnowledgeBase) -> EngineeringSkillManifest:
    """The built-in knowledge, described as a package."""
    return EngineeringSkillManifest(
        skill_id="fabrivium.builtin",
        name="Fabrivium built-in engineering knowledge",
        version=base.version,
        domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
        organization_scope=OrganizationScope.BUILT_IN,
        description=(
            "The process rules, estimation methods, equipment evidence, validation rules, "
            "layout rules and cost semantics implemented in Fabrivium today, described "
            "under the Engineering Skill packaging contract. Ships with the product; it is "
            "not loaded, and there is no mechanism to load one."
        ),
        owner="Fabrivium",
        applicability=Applicability(
            scope=(
                "Discrete manufacturing concepts Fabrivium can model. The electronics "
                "assembly reference data within it is bounded to that domain and says so "
                "on every item."
            ),
            not_valid_for=(
                "Domains Fabrivium holds no reference data for. Those produce a request "
                "for information, not an extrapolated answer."
            ),
        ),
        validation_status=ManifestValidationStatus.BUILT_IN,
        knowledge_items=tuple(item.qualified_id for item in base.all()),
        sources=(
            "app.data.engineering_reference_data",
            "app.services.process_planning",
            "app.services.equipment_catalog",
            "app.services.concept_validation",
            "app.services.constraints",
            "app.services.strategy_cost",
        ),
    )


# Package shapes the roadmap anticipates.
ROADMAP_PACKAGE_EXAMPLES: tuple[tuple[str, str], ...] = (
    (
        "ElectronicsAssemblySkill",
        "Process templates and estimation methods for electronics assembly lines.",
    ),
    (
        "LayoutPlanningSkill",
        "An organisation's own clearance, aisle and material-flow rules.",
    ),
    (
        "MedicalDeviceManufacturingSkill",
        "Domain process knowledge and the standard references that govern it.",
    ),
    (
        "CompanyStandardsSkill",
        "Internal procedure references, shift policies and engineering rules.",
    ),
    (
        "ApprovedSuppliersSkill",
        "The supplier list and commercial terms a procurement function has approved.",
    ),
)

__all__ = [
    "EngineeringSkillManifest",
    "ManifestValidationStatus",
    "OrganizationScope",
    "ROADMAP_PACKAGE_EXAMPLES",
    "builtin_manifest",
    "validate_manifest",
]
