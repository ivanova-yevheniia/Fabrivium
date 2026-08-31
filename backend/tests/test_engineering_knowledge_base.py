"""The Engineering Knowledge Base foundation."""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.knowledge.base import (
    EngineeringKnowledgeBase,
    KnowledgeItemNotFound,
    KnowledgeRegistrationError,
)
from app.knowledge.builtin import ADAPTERS, KNOWLEDGE_BASE_VERSION, build_knowledge_base
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
from app.knowledge.packaging import (
    ROADMAP_PACKAGE_EXAMPLES,
    EngineeringSkillManifest,
    ManifestValidationStatus,
    OrganizationScope,
    builtin_manifest,
    validate_manifest,
)
from app.knowledge.standards import (
    FORBIDDEN_CONTENT_FIELDS,
    StandardReference,
    StandardVerification,
)
from app.main import app

BACKEND = pathlib.Path(__file__).resolve().parents[1]
APP = BACKEND / "app"


@pytest.fixture(scope="module")
def base() -> EngineeringKnowledgeBase:
    return build_knowledge_base()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# 1. Provenance is preserved, on every item, without exception

def test_every_item_carries_a_source_a_reader_can_open(base):
    for item in base.all():
        assert item.provenance.source_reference.strip(), item.id
        assert item.provenance.statement.strip(), item.id


def test_every_item_states_its_own_limits(base):
    """Applicability is not decoration."""
    for item in base.all():
        assert item.applicability.scope.strip(), item.id


def test_a_classification_never_travels_without_its_vocabulary():
    """A bare trust word nobody can look up is the failure this prevents."""
    with pytest.raises(ValueError, match="vocabulary"):
        Provenance(
            source_kind=SourceKind.REFERENCE_TABLE,
            source_reference="app.data.engineering_reference_data",
            statement="A documented band.",
            classification="STATED_ASSUMPTION",
        )


def test_classifications_are_borrowed_not_minted(base):
    """The knowledge base carries the domain's own provenance words."""
    from app.models.concept import ValueSource
    from app.models.equipment_discovery import CatalogKind, EvidenceLevel, PriceStatus
    from app.data.engineering_reference_data import ReferenceClass

    vocabularies = {
        "ReferenceClass": {m.value for m in ReferenceClass} | {"MIXED"},
        "ValueSource": {m.value for m in ValueSource},
        "CatalogKind": {m.value for m in CatalogKind},
        "EvidenceLevel": {m.value for m in EvidenceLevel},
        "PriceStatus": {m.value for m in PriceStatus},
    }

    used = 0
    for item in base.all():
        vocabulary = item.provenance.classification_vocabulary
        if vocabulary is None:
            continue
        used += 1
        assert vocabulary in vocabularies, f"{item.id} names unknown vocabulary {vocabulary}"
        assert item.provenance.classification in vocabularies[vocabulary], (
            f"{item.id} classification {item.provenance.classification!r} is not a member "
            f"of {vocabulary}"
        )
    assert used > 0, "no item carried a classification at all"


def test_provenance_is_inspectable_by_id(base):
    provenance = base.provenance_of("estimation.profile.screwdriving")
    assert provenance.classification_vocabulary == "ReferenceClass"
    assert provenance.source_kind is SourceKind.REFERENCE_TABLE


# 2. Versions are explicit

def test_every_item_is_versioned(base):
    for item in base.all():
        assert item.version.strip(), item.id
        assert item.qualified_id == f"{item.id}@{item.version}"


def test_a_version_cannot_be_omitted():
    with pytest.raises(ValueError, match="needs a version"):
        EngineeringKnowledgeItem(
            id="probe",
            version="",
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Probe",
            description="Probe.",
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="probe",
                statement="Probe.",
            ),
            applicability=Applicability(scope="Probe."),
            exposure=KnowledgeExposure.POINTER,
        )


def test_the_base_itself_is_versioned(base):
    assert base.version == KNOWLEDGE_BASE_VERSION
    assert base.summary().version == KNOWLEDGE_BASE_VERSION


def test_an_exact_version_can_be_cited(base):
    item = base.all()[0]
    assert base.get(item.id, item.version) is item
    with pytest.raises(KnowledgeItemNotFound):
        base.get(item.id, "99.0.0")
    assert base.versions_of(item.id) == (item.version,)


def test_two_items_cannot_share_an_id_and_version():
    def probe() -> EngineeringKnowledgeItem:
        return EngineeringKnowledgeItem(
            id="probe",
            version="1.0.0",
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Probe",
            description="Probe.",
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="probe",
                statement="Probe.",
            ),
            applicability=Applicability(scope="Probe."),
            exposure=KnowledgeExposure.POINTER,
        )

    with pytest.raises(KnowledgeRegistrationError, match="share id"):
        EngineeringKnowledgeBase([probe(), probe()], version="1.0.0")


# 3. Querying is deterministic

def test_two_builds_produce_the_same_base_in_the_same_order():
    first = [i.qualified_id for i in build_knowledge_base().all()]
    second = [i.qualified_id for i in build_knowledge_base().all()]
    assert first == second
    assert len(first) == len(set(first)), "duplicate qualified ids"


def test_order_does_not_depend_on_registration_order():
    items = []
    for adapter in ADAPTERS:
        items.extend(adapter())

    forward = EngineeringKnowledgeBase(items, version="1.0.0")
    backward = EngineeringKnowledgeBase(list(reversed(items)), version="1.0.0")
    assert [i.qualified_id for i in forward] == [i.qualified_id for i in backward]


def test_every_filter_narrows_and_stays_ordered(base):
    everything = base.all()
    for category in KnowledgeCategory:
        subset = base.query(category=category)
        assert list(subset) == [i for i in everything if i.category is category]

    estimation_methods = base.query(
        category=KnowledgeCategory.ESTIMATION, kind=KnowledgeKind.ESTIMATION_METHOD
    )
    assert estimation_methods
    assert all(i.kind is KnowledgeKind.ESTIMATION_METHOD for i in estimation_methods)


def test_an_unlimited_item_answers_every_process_question(base):
    """Filtering by family must not hide the general rules from a specific
    question — an item that declares no family limit applies to all of them."""
    general = base.get("commercial.unknown_is_not_zero")
    assert general.applicability.process_categories == ()
    assert general in base.query(process_category="screwdriving")

    specific = base.get("estimation.profile.screwdriving")
    assert specific in base.query(process_category="screwdriving")
    assert specific not in base.query(process_category="packaging")


def test_a_missing_item_is_an_error_not_an_empty_answer(base):
    with pytest.raises(KnowledgeItemNotFound):
        base.get("no.such.item")


# 4. Adapters expose the canonical sources — no copy, no drift

def test_a_pointer_may_not_carry_the_value_it_points_at():
    """The structural form of the one-source-of-truth rule."""
    with pytest.raises(ValueError, match="POINTER but carries values"):
        EngineeringKnowledgeItem(
            id="probe",
            version="1.0.0",
            kind=KnowledgeKind.RULE,
            category=KnowledgeCategory.PROCESS,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Probe",
            description="Probe.",
            provenance=Provenance(
                source_kind=SourceKind.IMPLEMENTED_RULE,
                source_reference="probe",
                statement="Probe.",
            ),
            applicability=Applicability(scope="Probe."),
            exposure=KnowledgeExposure.POINTER,
            values={"cycle_time": 52.0},
        )


def test_a_derived_item_that_derived_nothing_is_refused():
    with pytest.raises(ValueError, match="derived nothing"):
        EngineeringKnowledgeItem(
            id="probe",
            version="1.0.0",
            kind=KnowledgeKind.FACT,
            category=KnowledgeCategory.LAYOUT,
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            title="Probe",
            description="Probe.",
            provenance=Provenance(
                source_kind=SourceKind.REFERENCE_TABLE,
                source_reference="probe",
                statement="Probe.",
            ),
            applicability=Applicability(scope="Probe."),
            exposure=KnowledgeExposure.DERIVED_VALUE,
        )


def test_published_values_cannot_be_mutated_through_the_item(base):
    item = base.get("layout.default_station_footprint")
    with pytest.raises(TypeError):
        item.values["width_m"] = 99.0  # type: ignore[index]


def test_process_rules_are_the_planners_own_rules(base):
    from app.services import process_planning

    published = base.query(category=KnowledgeCategory.PROCESS, tag="operation-derivation")
    assert len(published) == len(process_planning._RULES)

    by_fact = {i.values["fact_key"]: i for i in published}
    for rule in process_planning._RULES:
        item = by_fact[rule.fact_key]
        assert item.values["process_type"] == rule.process_type
        assert item.values["operation_name"] == rule.name
        assert item.values["requires_stated_action"] is rule.requires_action
        assert item.values["repeats_with_quantity"] is (
            rule.fact_key in process_planning._REPEATING
        )


def test_a_new_process_rule_appears_without_editing_the_knowledge_base(monkeypatch):
    """The anti-drift proof: change the source, and the base follows."""
    from app.services import process_planning
    from app.knowledge.adapters.process import process_knowledge

    extra = dataclasses.replace(
        process_planning._RULES[0],
        fact_key="component.probe",
        name="Probe operation",
        process_type="probing",
    )
    monkeypatch.setattr(
        process_planning, "_RULES", process_planning._RULES + (extra,), raising=True
    )

    published = {i.values["fact_key"] for i in process_knowledge() if "fact_key" in i.values}
    assert "component.probe" in published


def test_estimation_bands_are_the_reference_tables_own_numbers(base, monkeypatch):
    from app.data import engineering_reference_data as reference
    from app.knowledge.adapters.estimation import estimation_knowledge

    for category, profile in reference.PROCESS_PROFILES.items():
        item = base.get(f"estimation.profile.{category}")
        assert item.values["per_operation_low"] == profile.per_operation.low
        assert item.values["per_operation_high"] == profile.per_operation.high
        assert item.values["handling_low"] == profile.handling.low
        assert item.values["handling_high"] == profile.handling.high
        assert item.values["dataset_station_seconds"] == profile.dataset_station_seconds
        assert item.applicability.not_valid_for.startswith(profile.handling.applicability)

    # And the same mutation proof: widen a band at the source, and the
    # published knowledge widens with it.
    widened = dataclasses.replace(
        reference.PROCESS_PROFILES["screwdriving"],
        per_operation=dataclasses.replace(
            reference.PROCESS_PROFILES["screwdriving"].per_operation, high=99.0
        ),
    )
    monkeypatch.setitem(reference.PROCESS_PROFILES, "screwdriving", widened)

    rebuilt = {i.id: i for i in estimation_knowledge()}
    assert rebuilt["estimation.profile.screwdriving"].values["per_operation_high"] == 99.0


def test_automation_factors_are_the_reference_tables_own_factors(base):
    from app.data.engineering_reference_data import AUTOMATION_FACTORS

    for level, band in AUTOMATION_FACTORS.items():
        item = base.get(f"estimation.automation_factor.{level.lower()}")
        assert item.values["factor_low"] == band.low
        assert item.values["factor_high"] == band.high
        assert item.provenance.classification == band.source_class.value


def test_validation_rules_are_read_back_from_the_real_validator(base):
    """Every gap the canonical engine can report is published, with the
    engine's own severity and the engine's own sentence."""
    from app.models.concept import ConceptStage, FactoryConceptDraft
    from app.services.concept_validation import concept_gaps

    probe = FactoryConceptDraft(
        stages=[ConceptStage(id="s", name="S", process_type="probe")]
    )
    canonical = {g.key.replace("stage.s.", "stage.*."): g for g in concept_gaps(probe)}

    published = {
        i.values["gap_key"]: i
        for i in base.query(category=KnowledgeCategory.VALIDATION)
        if "gap_key" in i.values
    }
    assert set(published) == set(canonical)

    for key, gap in canonical.items():
        item = published[key]
        assert item.values["severity"] == gap.severity.value
        assert item.values["reason"] == gap.reason
        assert item.values["blocks_simulation"] is (gap.severity.value == "REQUIRED")


def test_the_blocking_set_matches_what_the_simulator_actually_consumes(base):
    """A spot check with teeth: a price is not blocking, a cycle time is."""
    assert base.get("validation.required_input.stage_any_cycle_time").values[
        "blocks_simulation"
    ] is True
    assert base.get("validation.required_input.stage_any_purchase_cost").values[
        "blocks_simulation"
    ] is False
    assert base.get("validation.required_input.budget").values["blocks_simulation"] is False


def test_layout_defaults_are_the_converters_own_defaults(base):
    from app.services.concept_validation import (
        DEFAULT_BUFFER_CAPACITY,
        DEFAULT_STATION_CAPACITY,
        DEFAULT_STATION_LENGTH_M,
        DEFAULT_STATION_WIDTH_M,
    )

    footprint = base.get("layout.default_station_footprint")
    assert footprint.values["width_m"] == DEFAULT_STATION_WIDTH_M
    assert footprint.values["length_m"] == DEFAULT_STATION_LENGTH_M
    assert footprint.provenance.classification == "CATALOG_DEFAULT"

    assert base.get("layout.default_station_capacity").values["capacity"] == (
        DEFAULT_STATION_CAPACITY
    )
    assert base.get("layout.default_buffer_capacity").values["capacity_units"] == (
        DEFAULT_BUFFER_CAPACITY
    )


def test_cost_semantics_are_the_costing_modules_own_table(base):
    from app.services import strategy_cost

    published = {
        i.values["action_type"]: i
        for i in base.query(category=KnowledgeCategory.COMMERCIAL)
        if "action_type" in i.values
    }
    assert set(published) == set(strategy_cost._ACTION_COST_RULES)

    for action, (category, gap_type, description) in strategy_cost._ACTION_COST_RULES.items():
        item = published[action]
        assert item.values["cost_category"] == category.value
        assert item.values["information_gap_type"] == gap_type.value
        assert item.values["what_is_unknown"] == description


def test_equipment_evidence_comes_through_the_catalogue_loader(base):
    """Records are read through the registry, never out of the JSON files."""
    from app.models.equipment_discovery import EquipmentCapability
    from app.services.equipment_catalog import default_registry

    registry = default_registry()
    canonical = {}
    for capability in EquipmentCapability:
        for candidate in registry.search(capability).candidates:
            canonical[candidate.candidate_id] = candidate

    published = {
        i.values["candidate_id"]: i
        for i in base.query(kind=KnowledgeKind.EQUIPMENT_EVIDENCE)
    }
    assert set(published) == set(canonical)

    for candidate_id, candidate in canonical.items():
        item = published[candidate_id]
        assert item.values["manufacturer"] == candidate.manufacturer
        assert item.values["model"] == candidate.model
        assert item.values["catalog_id"] == candidate.catalog_id
        assert item.provenance.classification == candidate.catalog_kind.value
        assert item.values["price_status"] == candidate.price_status.value


def test_a_source_that_could_not_answer_is_published_as_such(base):
    """"We could not consult this source" is a result, not an empty list."""
    live = base.get("equipment.catalog.live-manufacturer-web")
    assert live.values["available"] is False
    assert live.status == "NOT_CONNECTED"
    assert live.values["unavailable_reason"]
    assert "nothing suitable exists" in live.applicability.not_valid_for


def test_a_catalogue_reports_its_oldest_verification_date(base):
    """A catalogue is only as fresh as its least recently checked file."""
    from app.models.equipment_discovery import EquipmentCapability
    from app.services.equipment_catalog import default_registry

    registry = default_registry()
    seen: dict[str, list] = {}
    for capability in EquipmentCapability:
        for response in registry.search(capability).responses:
            if response.verified_on is not None:
                seen.setdefault(response.descriptor.catalog_id, []).append(
                    response.verified_on
                )

    assert seen, "no catalogue reported a verification date"
    tested_a_disagreement = False
    for catalog_id, dates in seen.items():
        published = base.get(f"equipment.catalog.{catalog_id}").provenance.verified_on
        assert published == min(dates), catalog_id
        if len(set(dates)) > 1:
            assert published != max(dates)
            tested_a_disagreement = True

    assert tested_a_disagreement, (
        "every catalogue answered with one date, so this test proved nothing. The "
        "researched catalogue's files are checked on different days; if that stops "
        "being true the rule needs a different fixture."
    )


def test_an_unknown_price_is_never_published_as_zero(base):
    for item in base.query(kind=KnowledgeKind.EQUIPMENT_EVIDENCE):
        assert item.values["price_status"] in {"PUBLISHED", "QUOTE_REQUIRED", "UNKNOWN"}
        assert "price" not in item.values, (
            f"{item.id} publishes a price. Prices belong to the equipment record, and "
            f"copying one here creates a second commercial figure."
        )


# 5. Standards references cannot be mistaken for content or for compliance

def test_a_standard_reference_has_no_field_that_could_hold_its_content():
    fields = {f.name for f in dataclasses.fields(StandardReference)}
    collision = fields & FORBIDDEN_CONTENT_FIELDS
    assert not collision, (
        f"StandardReference gained {sorted(collision)}. A reference that can hold the "
        f"standard's text is a reproduction of a copyrighted document."
    )


def test_a_standard_reference_never_claims_content_or_compliance(base):
    for reference in base.standard_references():
        assert reference.content_available is False
        assert reference.establishes_compliance is False
        assert "no content" in reference.disclosure
        assert "no assessment of compliance" in reference.disclosure


def test_no_verification_status_means_compliant():
    words = {m.value.upper() for m in StandardVerification}
    for forbidden in ("COMPLIANT", "CERTIFIED", "APPROVED", "MEETS", "CONFORMS"):
        assert not any(forbidden in w for w in words), (
            f"StandardVerification gained a member containing {forbidden!r}. Compliance "
            f"is a judgement a person makes, and no enum member may imply Fabrivium made it."
        )


def test_this_build_only_ever_says_a_source_mentioned_a_standard(base):
    references = base.standard_references()
    assert references, "the bundled catalogue cites a standard; it should be published"
    assert all(
        r.verification is StandardVerification.MENTIONED_IN_SOURCE for r in references
    )
    assert base.summary().claims_standards_compliance is False


def test_the_published_standard_reference_is_one_a_real_record_cites(base):
    """Extracted from the record, not authored here."""
    from app.models.equipment_discovery import EquipmentCapability
    from app.services.equipment_catalog import default_registry

    text = " ".join(
        (candidate.description or "") + " " + " ".join(candidate.caveats)
        for capability in EquipmentCapability
        for candidate in default_registry().search(capability).candidates
    )
    for reference in base.standard_references():
        assert reference.identifier in text, (
            f"{reference.identifier} is not cited by any bundled equipment record. "
            f"Fabrivium must not accumulate standard references nobody wrote down."
        )
        assert reference.cited_by.strip()


def test_a_standard_reference_must_name_who_cites_it():
    with pytest.raises(ValueError, match="names no citing source"):
        StandardReference(
            identifier="ISO 9001",
            cited_by="",
            verification=StandardVerification.MENTIONED_IN_SOURCE,
        )


def test_only_a_standard_reference_item_carries_a_standard(base):
    for item in base.all():
        assert (item.kind is KnowledgeKind.STANDARD_REFERENCE) == (
            item.standard is not None
        ), item.id


# 6. Skill manifests are versioned, and there is no loader

def test_a_manifest_without_a_version_is_refused():
    with pytest.raises(ValueError, match="needs a version"):
        EngineeringSkillManifest(
            skill_id="probe",
            name="Probe",
            version="",
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            organization_scope=OrganizationScope.ORGANIZATION,
            description="Probe.",
            owner="Probe Ltd",
            applicability=Applicability(scope="Probe."),
            validation_status=ManifestValidationStatus.DRAFT,
        )


def test_a_manifest_without_an_owner_is_refused():
    with pytest.raises(ValueError, match="names no owner"):
        EngineeringSkillManifest(
            skill_id="probe",
            name="Probe",
            version="1.0.0",
            domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
            organization_scope=OrganizationScope.ORGANIZATION,
            description="Probe.",
            owner="",
            applicability=Applicability(scope="Probe."),
            validation_status=ManifestValidationStatus.DRAFT,
        )


def test_the_builtin_manifest_is_derived_from_the_base_and_cannot_overclaim(base):
    manifest = builtin_manifest(base)
    assert manifest.version == base.version
    assert manifest.validation_status is ManifestValidationStatus.BUILT_IN
    assert set(manifest.knowledge_items) == {i.qualified_id for i in base.all()}
    assert validate_manifest(manifest, base) == []


def test_a_manifest_declaring_knowledge_the_product_lacks_does_not_validate(base):
    manifest = EngineeringSkillManifest(
        skill_id="acme.medical",
        name="Acme medical device manufacturing",
        version="0.1.0",
        domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
        organization_scope=OrganizationScope.ORGANIZATION,
        description="A hypothetical company package.",
        owner="Acme",
        applicability=Applicability(scope="Acme's medical device lines."),
        validation_status=ManifestValidationStatus.DRAFT,
        knowledge_items=("estimation.profile.cleanroom_assembly@1.0.0",),
    )
    problems = validate_manifest(manifest, base)
    assert len(problems) == 1
    assert "does not resolve" in problems[0]


def test_dependencies_are_declared_but_explicitly_unsupported(base):
    manifest = EngineeringSkillManifest(
        skill_id="acme.layout",
        name="Acme layout planning",
        version="0.1.0",
        domain=KnowledgeDomain.DISCRETE_MANUFACTURING,
        organization_scope=OrganizationScope.ORGANIZATION,
        description="A hypothetical company package.",
        owner="Acme",
        applicability=Applicability(scope="Acme's plants."),
        validation_status=ManifestValidationStatus.DRAFT,
        dependencies=("acme.standards@1.0.0",),
    )
    problems = validate_manifest(manifest, base)
    assert any("no package loader" in p for p in problems)


def test_no_status_word_implies_certification():
    words = {m.value.upper() for m in ManifestValidationStatus}
    assert not any(
        forbidden in w
        for w in words
        for forbidden in ("CERTIFIED", "APPROVED", "COMPLIANT")
    )


def test_engineering_skills_are_a_contract_with_no_loader():
    """No install, load, merge or override path exists."""
    source = (APP / "knowledge" / "packaging.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for forbidden in ("load", "install", "merge", "apply", "register", "activate"):
        assert not any(forbidden in name for name in functions), (
            f"app.knowledge.packaging gained a '{forbidden}' function. Engineering "
            f"Skills are a roadmap contract; shipping a loader makes them a feature."
        )

    assert len(ROADMAP_PACKAGE_EXAMPLES) >= 3
    assert all(
        isinstance(name, str) and isinstance(note, str)
        for name, note in ROADMAP_PACKAGE_EXAMPLES
    )


# 7. Production behaviour is unchanged — structurally, not by assertion

def test_no_engineering_module_imports_the_knowledge_base():
    """The knowledge base changes what Fabrivium can SAY, never what it DOES."""
    allowed = {APP / "main.py"}
    offenders: list[str] = []

    for path in sorted(APP.rglob("*.py")):
        if "knowledge" in path.relative_to(APP).parts or path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        if "app.knowledge" in source:
            offenders.append(str(path.relative_to(BACKEND)))

    assert not offenders, (
        f"These modules import the knowledge base: {offenders}. It is a read-only "
        f"description of Fabrivium's engineering knowledge and must never be on a "
        f"path that computes an engineering answer."
    )


def test_the_knowledge_api_is_read_only():
    paths = {
        route.path: getattr(route, "methods", set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/knowledge")
    }
    assert paths, "the knowledge endpoints should be registered"
    for path, methods in paths.items():
        assert methods <= {"GET", "HEAD"}, f"{path} accepts {methods}"


def test_building_the_base_leaves_the_canonical_sources_untouched():
    """Reading must not write."""
    from app.data import engineering_reference_data as reference
    from app.services import process_planning, strategy_cost

    before = (
        dict(reference.PROCESS_PROFILES),
        dict(reference.AUTOMATION_FACTORS),
        tuple(process_planning._RULES),
        dict(strategy_cost._ACTION_COST_RULES),
    )
    build_knowledge_base()
    after = (
        dict(reference.PROCESS_PROFILES),
        dict(reference.AUTOMATION_FACTORS),
        tuple(process_planning._RULES),
        dict(strategy_cost._ACTION_COST_RULES),
    )
    assert before == after


# 8. The read-only inspection endpoints

def test_the_knowledge_endpoint_reports_the_whole_base(client, base):
    payload = client.get("/knowledge").json()
    assert payload["version"] == base.version
    assert payload["items"] == len(base.all())
    assert len(payload["knowledge"]) == len(base.all())
    assert {c["category"] for c in payload["categories"]} == {
        i.category.value for i in base.all()
    }


def test_the_endpoint_never_reports_a_compliance_claim(client):
    payload = client.get("/knowledge").json()
    assert payload["claims_standards_compliance"] is False
    for item in payload["knowledge"]:
        if item["standard"] is not None:
            assert item["standard"]["content_available"] is False
            assert item["standard"]["establishes_compliance"] is False


def test_the_endpoint_presents_engineering_skills_as_not_implemented(client):
    package = client.get("/knowledge").json()["builtin_package"]
    assert package["implemented"] is False
    assert "roadmap" in package["note"].lower()


def test_a_filtered_view_cannot_be_mistaken_for_the_whole_base(client, base):
    payload = client.get("/knowledge", params={"category": "ESTIMATION"}).json()
    assert len(payload["knowledge"]) == len(
        base.query(category=KnowledgeCategory.ESTIMATION)
    )
    assert payload["items"] == len(base.all())


def test_one_item_can_be_inspected_with_its_provenance(client):
    payload = client.get("/knowledge/estimation.profile.screwdriving").json()
    assert payload["qualified_id"] == "estimation.profile.screwdriving@1.0.0"
    assert payload["classification_vocabulary"] == "ReferenceClass"
    assert payload["source_reference"].startswith("app.data.engineering_reference_data")
    assert payload["exposure"] == "DERIVED_VALUE"
    assert payload["not_valid_for"]


def test_an_unknown_item_and_an_unknown_category_fail_visibly(client):
    assert client.get("/knowledge/no.such.item").status_code == 404
    assert client.get("/knowledge", params={"category": "BOGUS"}).status_code == 400
