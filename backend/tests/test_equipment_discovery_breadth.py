"""Equipment discovery breadth — capability matching, evidence, catalogues."""

from __future__ import annotations

import json
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import ConceptStage, SourcedFloat, SourcedInt
from app.models.equipment_discovery import (
    CatalogKind,
    EquipmentCandidate,
    EquipmentCapability,
    EquipmentSource,
    EvidenceLevel,
    MatchClaim,
    PriceStatus,
    PublishedSpec,
    SourceType,
)
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.equipment_catalog import (
    APPROVED_SUPPLIERS,
    CatalogDescriptor,
    CatalogQuery,
    EquipmentCatalog,
    EquipmentCatalogRegistry,
    JsonFileCatalog,
    UnavailableCatalog,
    default_registry,
)
from app.services.equipment_compatibility import (
    CheckStatus,
    CompatibilityCheck,
    check_compatibility,
)
from app.services.equipment_discovery import (
    CAPABILITY_BY_PROCESS_TYPE,
    CAPABILITY_STATEMENTS,
    capability_for,
    load_cached_candidates,
    requirement_from_concept,
    search_catalogs,
)

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection, labelling and packaging. We need about 1,900 units per day. The available "
    "production area is 30 by 18 meters. We have eight operators."
)


@pytest.fixture
def draft():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def source(source_id: str = "s1", kind: SourceType = SourceType.MANUFACTURER_DATASHEET) -> EquipmentSource:
    return EquipmentSource(
        source_id=source_id,
        url="https://example-manufacturer.test/product",
        source_type=kind,
        title="Test datasheet",
        retrieved_at=date(2026, 8, 23),
    )


def candidate(**overrides) -> EquipmentCandidate:
    base = dict(
        candidate_id="test-1",
        manufacturer="Test Manufacturer",
        model="TM-1",
        category="Test equipment",
        provides=[EquipmentCapability.SCREW_FASTENING],
        product_scope="Test unit",
        sources=[source()],
    )
    base.update(overrides)
    return EquipmentCandidate(**base)


def _check(req, cand, field):
    report = check_compatibility(req, cand)
    return next(c for c in report.checks if c.field == field)


# 1. The requirement names a CAPABILITY, and matching uses it

class TestCapabilityMatching:
    def test_the_requirement_carries_what_the_station_must_do(self, draft):
        req = requirement_from_concept(draft, "m-inspection")
        assert req.required_capability is EquipmentCapability.VISUAL_INSPECTION
        # And it says so in words an engineer could send to a vendor.
        assert "image" in req.capability_statement.lower()

    def test_a_station_we_have_not_researched_has_no_capability(self, draft):
        req = requirement_from_concept(draft, "m-assembly")
        assert req.required_capability is None
        assert req.capability_statement == ""

    def test_a_candidate_is_matched_on_its_declaration_not_its_name(self, draft):
        """The defect this whole layer exists to prevent."""
        req = requirement_from_concept(draft, "m-screwdriving")
        impostor = candidate(
            candidate_id="impostor",
            manufacturer="Screwdriving Systems GmbH",
            model="Automatic Screwdriving Station 9000",
            category="Screwdriving system",
            provides=[EquipmentCapability.VISUAL_INSPECTION],
        )
        check = _check(req, impostor, "capability")
        assert check.status is CheckStatus.FAIL
        assert "does not declare" in check.reason

    def test_a_record_that_declares_nothing_matches_nothing(self, draft):
        req = requirement_from_concept(draft, "m-screwdriving")
        silent = candidate(candidate_id="silent", provides=[])
        assert _check(req, silent, "capability").status is CheckStatus.FAIL

    def test_capability_lookup_is_exact_not_substring(self):
        # "screwdriving" resolves; a sentence containing it does not.
        assert capability_for("screwdriving") is EquipmentCapability.SCREW_FASTENING
        assert capability_for("  Screwdriving ") is EquipmentCapability.SCREW_FASTENING
        assert capability_for("manual screwdriving and deburring") is None

    def test_every_mapped_capability_has_a_catalogue(self):
        """No process type may claim to have been searched with no data."""
        registry = default_registry()
        for capability in set(CAPABILITY_BY_PROCESS_TYPE.values()):
            found = registry.search(capability)
            assert found.candidates, f"{capability} is mapped but no catalogue holds records for it"

    def test_every_capability_has_a_statement(self):
        assert set(CAPABILITY_STATEMENTS) == set(EquipmentCapability)
        for capability, statement in CAPABILITY_STATEMENTS.items():
            assert statement and capability.value not in statement


# 2. The existing category still behaves, and the two new ones behave too

class TestThreeCategories:
    def test_the_existing_category_is_unchanged(self, draft):
        """Phase 16's flagship station keeps its data and its 52 s bound."""
        req = requirement_from_concept(draft, "m-screwdriving")
        assert req.max_cycle_time_seconds.value == 52.0
        candidates, verified_on = load_cached_candidates("screwdriving")
        assert {c.candidate_id for c in candidates} == {
            "weber-ser-30",
            "kolver-kds-nt120ca",
            "kolver-kbl30fr-ca",
            "deprag-dcam",
        }
        assert verified_on == date(2026, 8, 21)

    def test_new_category_one_visual_inspection(self, draft):
        req = requirement_from_concept(draft, "m-inspection")
        found = search_catalogs(req)
        ids = {c.candidate_id for c in found.candidates}
        assert "omron-fhv7x-m032-c" in ids
        assert "sick-inspectorp65x-v2d652p" in ids
        for cand in found.candidates:
            assert cand.provides_capability(EquipmentCapability.VISUAL_INSPECTION)

    def test_new_category_two_label_application(self, draft):
        req = requirement_from_concept(draft, "m-labelling")
        assert req.required_capability is EquipmentCapability.LABEL_APPLICATION
        found = search_catalogs(req)
        ids = {c.candidate_id for c in found.candidates}
        assert {"herma-500", "weber-legi-air-4050e", "videojet-9560-tamp"} <= ids

    def test_no_vision_candidate_claims_a_cycle_time(self, draft):
        """A frame rate is not an inspection cycle time."""
        candidates, _ = load_cached_candidates("inspection")
        assert candidates
        for cand in candidates:
            assert cand.cycle_time_seconds.published is False

    def test_a_derived_cycle_time_says_it_was_derived(self):
        candidates, _ = load_cached_candidates("labelling")
        videojet = next(c for c in candidates if c.candidate_id == "videojet-9560-tamp")
        spec = videojet.cycle_time_seconds
        assert spec.value == 1.0
        assert spec.evidence is EvidenceLevel.SOURCE_DERIVED
        # The arithmetic is written down, so an engineer can redo it.
        assert "60 packs per minute" in spec.basis
        assert spec.evidence is not EvidenceLevel.KNOWN_SPECIFICATION


# 3. The evidence model

class TestEvidence:
    def test_an_unpublished_value_is_unknown_whatever_the_file_says(self):
        # A record cannot upgrade an empty value by labelling it.
        spec = PublishedSpec(evidence=EvidenceLevel.KNOWN_SPECIFICATION)
        assert spec.evidence is EvidenceLevel.UNKNOWN
        assert spec.published is False

    def test_a_derived_value_without_its_derivation_is_refused(self):
        with pytest.raises(ValueError, match="basis"):
            PublishedSpec(value=1.0, unit="s", evidence=EvidenceLevel.SOURCE_DERIVED)

    def test_an_estimate_may_not_cite_a_manufacturer_document(self):
        estimate = PublishedSpec.estimated(12.0, "s", "assumed from a comparable station")
        assert estimate.source_id is None
        assert estimate.traceable is False

    def test_derived_and_published_are_both_traceable_but_not_equal(self):
        published = PublishedSpec.of(1.0, "s", "s1")
        derived = PublishedSpec.derived(1.0, "s", "s1", "60 / 60 packs per minute")
        assert published.traceable and derived.traceable
        assert published.evidence is not derived.evidence

    def test_the_evidence_counts_add_up(self):
        cand = candidate(
            width_mm=PublishedSpec.of(90.0, "mm", "s1"),
            cycle_time_seconds=PublishedSpec.derived(1.0, "s", "s1", "60 / 60 per minute"),
            price_status=PriceStatus.QUOTE_REQUIRED,
        )
        summary = cand.evidence_summary
        total = (
            summary.known_specification
            + summary.source_derived
            + summary.estimated
            + summary.unknown
            + summary.quote_required
        )
        assert total == len(cand.comparable_specs)
        assert summary.quote_required == 1
        assert summary.traceable == 2

    def test_provenance_survives_the_whole_round_trip(self, client, draft):
        """Field-level provenance from the JSON file to the HTTP response."""
        body = client.post(
            "/equipment/discover",
            json={"draft": draft.model_dump(mode="json"), "station_id": "m-labelling"},
        ).json()
        weber = next(
            a for a in body["assessments"] if a["candidate"]["candidate_id"] == "weber-legi-air-4050e"
        )
        cand = weber["candidate"]
        cycle = cand["cycle_time_seconds"]
        assert cycle["evidence"] == "SOURCE_DERIVED"
        assert "240 labels/min" in cycle["basis"]
        # The source id on the value resolves to a document in the same record.
        cited = {s["source_id"]: s for s in cand["sources"]}
        assert cycle["source_id"] in cited
        assert cited[cycle["source_id"]]["url"].startswith("https://")
        assert cited[cycle["source_id"]]["retrieved_at"] == "2026-08-23"


# 4. Price semantics

class TestPrice:
    def test_a_missing_price_is_never_zero_in_any_catalogue(self):
        registry = default_registry()
        for capability in EquipmentCapability:
            for cand in registry.search(capability).candidates:
                if cand.price_status is PriceStatus.PUBLISHED:
                    continue
                assert cand.price.value is None, f"{cand.candidate_id} has a price without publishing one"
                assert cand.price.evidence is EvidenceLevel.UNKNOWN

    def test_quote_required_is_a_real_answer_not_a_gap(self, draft):
        """Against a station that HAS a budget: the reason names the market."""
        req = requirement_from_concept(draft, "m-screwdriving")
        assert req.budget_limit.known
        weber = next(
            c for c in search_catalogs(req).candidates if c.candidate_id == "weber-ser-30"
        )
        check = _check(req, weber, "budget")
        assert check.status is CheckStatus.UNKNOWN
        assert check.candidate_text == "Quote required"
        assert "quotation" in check.reason

    def test_quote_required_is_shown_even_with_no_budget_to_check_against(self, draft):
        """The price status is a fact about the supplier, not about us."""
        req = requirement_from_concept(draft, "m-labelling")
        assert req.budget_limit.known is False
        herma = next(
            c for c in search_catalogs(req).candidates if c.candidate_id == "herma-500"
        )
        check = _check(req, herma, "budget")
        assert check.status is CheckStatus.UNKNOWN
        assert check.candidate_text == "Quote required"
        assert "No budget is recorded" in check.reason

    def test_a_legitimate_zero_is_kept_and_explained(self, draft):
        """The one €0 in the system: a machine the customer already owns."""
        req = requirement_from_concept(draft, "m-inspection")
        owned = next(
            c
            for c in search_catalogs(req).candidates
            if c.catalog_kind is CatalogKind.INTERNAL_ASSET_POOL
        )
        assert owned.price_status is PriceStatus.PUBLISHED
        assert owned.price.value == 0.0
        assert owned.price.evidence is EvidenceLevel.KNOWN_SPECIFICATION
        # And the zero says what it excludes, so nobody reads it as free.
        assert any("already owned" in c for c in owned.caveats)
        assert any("requalification" in c for c in owned.caveats)

    def test_a_published_price_over_budget_still_fails(self, draft):
        req = requirement_from_concept(draft, "m-screwdriving")
        assert req.budget_limit.known
        expensive = candidate(
            price=PublishedSpec.of(float(req.budget_limit.value) + 1.0, "EUR", "s1"),
            price_status=PriceStatus.PUBLISHED,
        )
        assert _check(req, expensive, "budget").status is CheckStatus.FAIL


# 5. Insufficient specification, no candidate, multiple candidates, mismatch

class TestOutcomes:
    def test_insufficient_specification_stays_unverified(self, draft):
        """A record with an identity and nothing else."""
        req = requirement_from_concept(draft, "m-inspection")
        owned = next(
            c
            for c in search_catalogs(req).candidates
            if c.catalog_kind is CatalogKind.INTERNAL_ASSET_POOL
        )
        report = check_compatibility(req, owned)
        assert report.claim is MatchClaim.CANDIDATE
        assert report.unverified
        for check in report.unverified:
            assert check.reason, f"{check.field} is UNKNOWN with no reason given"
        assert any("no dimensions" in c for c in owned.caveats)

    def test_no_candidate_is_distinguished_from_no_data(self, client, draft):
        body = client.post(
            "/equipment/discover",
            json={"draft": draft.model_dump(mode="json"), "station_id": "m-packaging"},
        ).json()
        assert body["assessments"] == []
        assert body["capability"] is None
        assert "not a statement about the market" in body["note"]

    def test_multiple_candidates_come_back_with_their_sources_kept_apart(self, client, draft):
        body = client.post(
            "/equipment/discover",
            json={"draft": draft.model_dump(mode="json"), "station_id": "m-labelling"},
        ).json()
        assert len(body["assessments"]) >= 4
        kinds = {a["catalog_kind"] for a in body["assessments"]}
        # Two genuinely different KINDS of source in one shortlist, each
        # candidate still naming which one it came from.
        assert {"RESEARCHED_MANUFACTURER", "APPROVED_SUPPLIER"} <= kinds
        for assessment in body["assessments"]:
            assert assessment["candidate"]["catalog_id"]
            assert assessment["candidate"]["sources"]

    def test_a_constraint_mismatch_blocks_regardless_of_what_passed(self, draft):
        req = requirement_from_concept(draft, "m-screwdriving")
        oversized = candidate(
            width_mm=PublishedSpec.of(50.0, "mm", "s1"),
            length_mm=PublishedSpec.of(99_000.0, "mm", "s1"),
        )
        report = check_compatibility(req, oversized)
        assert report.pass_count >= 2
        assert report.claim is MatchClaim.CONSTRAINT_MISMATCH
        assert "Constraint mismatch" in report.claim_text


# 6. The cycle budget is per operation, not per unit

class TestRepeatCount:
    def test_a_repeat_count_divides_the_station_budget(self, draft):
        """52 s and four screws is 13 s a screw, not 52."""
        req = requirement_from_concept(
            draft,
            "m-screwdriving",
            station_context={"repeated_operations": 4, "operation": "Screw fastening"},
        )
        assert req.operations_per_unit.value == 4
        too_slow = candidate(cycle_time_seconds=PublishedSpec.of(20.0, "s", "s1"))
        check = _check(req, too_slow, "cycle_time")
        assert check.status is CheckStatus.FAIL
        assert "13 s" in check.requirement_text

        fast_enough = candidate(cycle_time_seconds=PublishedSpec.of(12.0, "s", "s1"))
        assert _check(req, fast_enough, "cycle_time").status is CheckStatus.PASS

    def test_no_repeat_count_means_no_division_and_no_assumption(self, draft):
        req = requirement_from_concept(draft, "m-screwdriving")
        assert req.operations_per_unit.known is False
        check = _check(req, candidate(cycle_time_seconds=PublishedSpec.of(20.0, "s", "s1")), "cycle_time")
        # Compared against the station's own 52 s, and the text says so.
        assert check.status is CheckStatus.PASS
        assert check.requirement_text == "≤ 52 s"

    def test_the_product_dimensions_are_quoted_not_parsed(self, draft):
        req = requirement_from_concept(
            draft,
            "m-inspection",
            station_context={"product_dimensions": "180 × 120 × 65 mm"},
        )
        assert req.part_dimensions_text == "180 × 120 × 65 mm"
        assert req.part_dimensions_provenance

    def test_payload_is_never_invented(self, draft):
        req = requirement_from_concept(draft, "m-inspection")
        assert req.max_payload_kg.known is False
        check = _check(req, candidate(provides=[EquipmentCapability.VISUAL_INSPECTION]), "payload")
        assert check.status is CheckStatus.UNKNOWN
        assert "how heavy" in check.reason


# 7. No false automation claim

class TestClaimCeiling:
    def test_there_is_no_claim_stronger_than_potentially_suitable(self):
        forbidden = {"COMPATIBLE", "VALIDATED", "GUARANTEED", "SUITABLE", "APPROVED"}
        assert {m.value for m in MatchClaim} & forbidden == set()

    def test_a_fully_matched_candidate_is_still_only_potentially_suitable(self, draft):
        """Everything the concept states passes — and the wording still hedges."""
        req = requirement_from_concept(draft, "m-screwdriving")
        perfect = candidate(
            cycle_time_seconds=PublishedSpec.of(10.0, "s", "s1"),
            capacity=PublishedSpec.of(10.0, "", "s1"),
            operators_required=PublishedSpec.of(0.0, "", "s1"),
            width_mm=PublishedSpec.of(100.0, "mm", "s1"),
            length_mm=PublishedSpec.of(100.0, "mm", "s1"),
            price=PublishedSpec.of(1.0, "EUR", "s1"),
            price_status=PriceStatus.PUBLISHED,
        )
        # The payload check is UNKNOWN, which is itself the point: a concept
        # cannot establish a payload, so the claim stays CANDIDATE.
        report = check_compatibility(req, perfect)
        assert report.claim is MatchClaim.CANDIDATE

        # With the payload row removed from the comparison there is nothing
        # left unchecked, and the ceiling is still POTENTIALLY_SUITABLE.
        without_payload = report.model_copy(
            update={"checks": [c for c in report.checks if c.field != "payload"]}
        )
        assert without_payload.claim is MatchClaim.POTENTIALLY_SUITABLE
        assert "not a compatibility statement" in without_payload.claim_text

    def test_the_claim_sentence_reads_as_english(self, draft):
        """Found by looking at the rendered panel, not by a test."""
        req = requirement_from_concept(draft, "m-screwdriving")
        one = check_compatibility(req, candidate())
        assert "1 requirement matched" in one.claim_text
        assert "(s)" not in one.claim_text

        two = one.model_copy(
            update={
                "checks": [
                    *one.checks,
                    CompatibilityCheck(
                        field="extra",
                        label="Extra",
                        status=CheckStatus.PASS,
                        requirement_text="x",
                        candidate_text="y",
                    ),
                ]
            }
        )
        assert "2 requirements matched" in two.claim_text

    def test_the_ui_facing_text_never_uses_the_forbidden_words(self, draft):
        req = requirement_from_concept(draft, "m-labelling")
        for cand in search_catalogs(req).candidates:
            report = check_compatibility(req, cand)
            text = " ".join(
                [report.claim_text, report.summary()]
                + [f"{c.label} {c.requirement_text} {c.candidate_text} {c.reason}" for c in report.checks]
            ).lower()
            for word in ("is compatible", "validated", "guaranteed suitable", "certified for"):
                assert word not in text, f"{cand.candidate_id} claims '{word}'"

    def test_an_unverified_requirement_is_never_folded_into_the_matches(self, draft):
        req = requirement_from_concept(draft, "m-inspection")
        for cand in search_catalogs(req).candidates:
            report = check_compatibility(req, cand)
            assert set(report.matched).isdisjoint(report.unverified)
            assert len(report.matched) + len(report.unverified) + len(report.mismatched) == len(
                report.checks
            )


# 8. Extensibility — a fourth catalogue changes nothing else

class TestExtensibility:
    def test_the_shipped_registry_covers_three_kinds_plus_an_external_source(self):
        kinds = {d.kind for d in default_registry().descriptors}
        assert kinds == {
            CatalogKind.INTERNAL_ASSET_POOL,
            CatalogKind.APPROVED_SUPPLIER,
            CatalogKind.RESEARCHED_MANUFACTURER,
            CatalogKind.EXTERNAL_SOURCE,
        }

    def test_an_unavailable_source_says_so_instead_of_returning_nothing(self, client, draft):
        body = client.post(
            "/equipment/discover",
            json={"draft": draft.model_dump(mode="json"), "station_id": "m-screwdriving"},
        ).json()
        external = next(c for c in body["catalogs"] if c["kind"] == "EXTERNAL_SOURCE")
        assert external["available"] is False
        assert external["unavailable_reason"]
        assert external["candidate_count"] == 0
        # And it is not silently counted among the sources that answered.
        assert all(a["catalog_kind"] != "EXTERNAL_SOURCE" for a in body["assessments"])

    def test_a_new_catalog_needs_no_core_change(self, draft):
        """A third party's source, implemented against the protocol alone."""

        class PartnerCatalog:
            """Two members. That is the whole interface."""

            descriptor = CatalogDescriptor(
                catalog_id="partner-plm",
                kind=CatalogKind.EXTERNAL_SOURCE,
                display_name="Partner PLM export",
                trust_statement="A partner company's own equipment master data.",
            )

            def search(self, query: CatalogQuery):
                from app.services.equipment_catalog import CatalogResponse

                if query.capability is not EquipmentCapability.SCREW_FASTENING:
                    return CatalogResponse(descriptor=self.descriptor, candidates=[])
                return CatalogResponse(
                    descriptor=self.descriptor,
                    candidates=[
                        candidate(
                            candidate_id="partner-unit-1",
                            catalog_id=self.descriptor.catalog_id,
                            catalog_kind=self.descriptor.kind,
                            cycle_time_seconds=PublishedSpec.of(8.0, "s", "s1"),
                        )
                    ],
                    verified_on=date(2026, 8, 23),
                )

        partner = PartnerCatalog()
        assert isinstance(partner, EquipmentCatalog)

        registry = EquipmentCatalogRegistry((*_shipped(), partner))
        req = requirement_from_concept(draft, "m-screwdriving")
        found = search_catalogs(req, registry=registry)

        assert "partner-unit-1" in {c.candidate_id for c in found.candidates}
        # And it is checked by exactly the same arithmetic as everything else.
        partner_candidate = next(c for c in found.candidates if c.candidate_id == "partner-unit-1")
        assert _check(req, partner_candidate, "cycle_time").status is CheckStatus.PASS

    def test_a_catalog_cannot_promote_its_own_records(self, tmp_path, monkeypatch):
        """A file registered as an approved-supplier list stays one."""
        payload = {
            "verified_on": "2026-08-23",
            "candidates": [
                {
                    "candidate_id": "self-promoting",
                    "manufacturer": "X",
                    "model": "Y",
                    "category": "Z",
                    "provides": ["SCREW_FASTENING"],
                    "product_scope": "unit",
                    "catalog_kind": "RESEARCHED_MANUFACTURER",
                    "sources": ["s"],
                }
            ],
            "sources": [
                {
                    "source_id": "s",
                    "url": "internal://x/y",
                    "source_type": "APPROVED_SUPPLIER_LIST",
                    "title": "t",
                    "retrieved_at": "2026-08-23",
                }
            ],
        }
        path = tmp_path / "supplier.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr("app.services.equipment_catalog._DATA_DIR", tmp_path)

        catalog = JsonFileCatalog(APPROVED_SUPPLIERS, ("supplier.json",))
        found = catalog.search(CatalogQuery(capability=EquipmentCapability.SCREW_FASTENING))
        assert found.candidates[0].catalog_kind is CatalogKind.APPROVED_SUPPLIER

    def test_a_missing_catalogue_file_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.services.equipment_catalog._DATA_DIR", tmp_path)
        catalog = JsonFileCatalog(APPROVED_SUPPLIERS, ("absent.json",))
        found = catalog.search(CatalogQuery(capability=EquipmentCapability.SCREW_FASTENING))
        assert found.available is False
        assert "missing from this build" in found.unavailable_reason

    def test_the_shortlist_is_only_as_fresh_as_its_oldest_entry(self, draft):
        req = requirement_from_concept(draft, "m-screwdriving")
        found = search_catalogs(req)
        answered = [r.verified_on for r in found.consulted if r.verified_on is not None]
        assert found.verified_on == min(answered)

    def test_catalogues_do_not_reach_into_planning_or_simulation(self):
        """The property that makes the abstraction safe to extend."""
        text = pathlib.Path("app/services/equipment_catalog.py").read_text(encoding="utf-8")
        for forbidden in (
            "app.services.simulation",
            "app.services.layout",
            "app.services.optimization",
            "app.models.factory",
            "requests",
            "httpx",
            "urllib",
            "socket",
        ):
            assert forbidden not in text, f"the catalogue layer must not reach into {forbidden}"


def _shipped() -> tuple:
    """The bundled catalogues, as a tuple a test can extend."""
    from app.services.equipment_catalog import (
        APPROVED_SUPPLIERS as approved,
        INTERNAL_POOL,
        LIVE_WEB,
        RESEARCHED,
    )

    return (
        JsonFileCatalog(INTERNAL_POOL, ("internal_asset_pool.json",)),
        JsonFileCatalog(approved, ("approved_supplier_catalog.json",)),
        JsonFileCatalog(
            RESEARCHED,
            (
                "screwdriving_candidates.json",
                "visual_inspection_candidates.json",
                "label_application_candidates.json",
            ),
        ),
        UnavailableCatalog(LIVE_WEB, "not connected"),
    )


# 9. The skill runtime path

def test_the_equipment_skill_actually_runs():
    """It returned FAILED for every input before the breadth phase."""
    from app.skills.builtin import EquipmentDiscoverySkill
    from app.skills.contract import SkillContext, SkillStatus

    draft = apply_example_engineering_data(concept_from_brief(BRIEF))
    requirement = requirement_from_concept(draft, "m-screwdriving")
    result = EquipmentDiscoverySkill().execute({"requirement": requirement}, SkillContext())

    assert result.status is not SkillStatus.FAILED
    assert result.data, "the skill produced no reports"
    assert result.evidence, "the skill produced no evidence"
    # Every price needs a quotation, so the honest status is PARTIAL.
    assert result.status is SkillStatus.PARTIAL


# 10. Nothing here can move a simulation number

def test_a_new_category_cannot_change_what_the_simulator_reads():
    """Selecting labelling equipment leaves the concept's physics alone."""
    from app.services.equipment_discovery import proposed_parameter_changes, select_candidate

    draft = apply_example_engineering_data(concept_from_brief(BRIEF))
    req = requirement_from_concept(draft, "m-labelling")
    stage = next(s for s in draft.stages if s.id == "m-labelling")
    before = (stage.cycle_time, stage.capacity, stage.operators_required)

    cand = next(c for c in search_catalogs(req).candidates if c.candidate_id == "herma-500")
    selection = select_candidate(req, cand)
    assert selection.adopted_parameters == []

    changes = proposed_parameter_changes(req, cand, stage)
    # A proposal is offered for review; nothing was applied.
    assert (stage.cycle_time, stage.capacity, stage.operators_required) == before
    for change in changes:
        assert change.proposed_source_url


def test_a_stage_with_no_engineering_values_still_derives_a_capability():
    """Capability comes from the process type, not from the physics."""
    bare = ConceptStage(
        id="m-labelling",
        name="Labelling",
        process_type="labelling",
        cycle_time=SourcedFloat.unknown(),
        capacity=SourcedInt.unknown(),
        operators_required=SourcedInt.unknown(),
    )
    draft = concept_from_brief(BRIEF).model_copy(update={"stages": [bare]})
    req = requirement_from_concept(draft, "m-labelling")
    assert req.required_capability is EquipmentCapability.LABEL_APPLICATION
    assert req.known_bounds == 0
    # Every check is UNKNOWN except the capability itself, and nothing was
    # defaulted to make a comparison possible.
    report = check_compatibility(req, candidate(provides=[EquipmentCapability.LABEL_APPLICATION]))
    assert report.claim is MatchClaim.CANDIDATE
    assert report.pass_count == 1
