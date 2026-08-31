"""Phase 16 — equipment discovery."""

from __future__ import annotations

import json
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import SourcedFloat, SourcedInt, ValueSource
from app.models.equipment_discovery import (
    EquipmentCandidate,
    EquipmentCapability,
    EquipmentSource,
    MatchClaim,
    PriceStatus,
    PublishedSpec,
    SourceType,
)
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.equipment_compatibility import CheckStatus, check_compatibility
from app.services.equipment_discovery import (
    UnknownStationError,
    adopt_parameters,
    load_cached_candidates,
    proposed_parameter_changes,
    requirement_from_concept,
    select_candidate,
    source_backed_only,
)

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators. We would prefer not to buy unnecessary equipment."
)


@pytest.fixture
def draft():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


@pytest.fixture
def requirement(draft):
    return requirement_from_concept(draft, "m-screwdriving")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def source() -> EquipmentSource:
    return EquipmentSource(
        source_id="s1",
        url="https://example-manufacturer.test/product",
        source_type=SourceType.MANUFACTURER_DATASHEET,
        title="Test datasheet",
        retrieved_at=date(2026, 8, 21),
    )


def candidate(**overrides) -> EquipmentCandidate:
    base = dict(
        candidate_id="test-1",
        manufacturer="Test Manufacturer",
        model="TM-1",
        category="Fixtured screwdriving system",
        # Declared, not inferred from the category text above.
        provides=[EquipmentCapability.SCREW_FASTENING],
        product_scope="Screwdriving unit",
        sources=[source()],
    )
    base.update(overrides)
    return EquipmentCandidate(**base)


# The requirement comes from the concept

class TestRequirementDerivation:
    def test_cycle_time_comes_from_the_concept_stage(self, draft, requirement):
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        assert requirement.max_cycle_time_seconds.value == stage.cycle_time.value
        # The golden demo's 52 s, arrived at without this module knowing it.
        assert requirement.max_cycle_time_seconds.value == 52.0

    def test_changing_the_concept_changes_the_requirement(self, draft):
        # The property that makes derivation worth doing: no second source
        # of truth to forget to update.
        stages = [
            s.model_copy(update={"cycle_time": SourcedFloat.of(30.0, ValueSource.CUSTOMER, "Customer")})
            if s.id == "m-screwdriving"
            else s
            for s in draft.stages
        ]
        edited = draft.model_copy(update={"stages": stages})
        assert requirement_from_concept(edited, "m-screwdriving").max_cycle_time_seconds.value == 30.0

    def test_envelope_and_budget_come_from_the_station_not_the_project(self, draft, requirement):
        assert requirement.max_width_m.value == 2.5
        assert requirement.max_length_m.value == 2.0
        # The station's own planned cost, not the €500,000 project budget —
        # otherwise the shortlist would be judged against the wrong ceiling.
        assert requirement.budget_limit.value == 85000.0
        assert requirement.budget_limit.value != draft.budget.value

    def test_provenance_names_the_real_source(self, requirement):
        assert "example dataset" in requirement.provenance.lower()

    def test_an_unset_bound_stays_unknown_rather_than_zero(self):
        bare = concept_from_brief(BRIEF)  # no engineering data applied
        req = requirement_from_concept(bare, "m-screwdriving")
        assert req.max_cycle_time_seconds.known is False
        assert req.max_cycle_time_seconds.value is None
        assert req.known_bounds == 0

    def test_no_interface_is_invented_from_the_process_type(self, requirement):
        # "It is a screwdriving station so it needs PROFINET" is a guess,
        # and a guessed requirement would produce a FAIL that removes a
        # valid option from an engineer's shortlist.
        assert requirement.required_interfaces == []

    def test_an_unknown_station_is_refused(self, draft):
        with pytest.raises(UnknownStationError) as exc:
            requirement_from_concept(draft, "m-does-not-exist")
        assert "m-does-not-exist" in str(exc.value)


# Candidates and their sources

class TestCandidateData:
    def test_every_bundled_candidate_cites_a_document(self):
        candidates, _ = load_cached_candidates("screwdriving")
        assert candidates
        for c in candidates:
            assert c.source_backed
            for s in c.sources:
                assert s.url.startswith("https://")
                assert s.retrieved_at

    def test_a_candidate_without_a_source_is_dropped(self):
        real = candidate()
        unsourced = candidate(candidate_id="no-source", sources=[])
        kept = source_backed_only([real, unsourced])
        assert [c.candidate_id for c in kept] == ["test-1"]

    def test_the_cache_records_when_it_was_verified(self):
        _, verified_on = load_cached_candidates("screwdriving")
        assert verified_on == date(2026, 8, 21)

    def test_an_unresearched_category_returns_nothing_rather_than_guessing(self):
        candidates, verified_on = load_cached_candidates("welding")
        assert candidates == []
        assert verified_on is None

    def test_unknown_price_is_not_zero(self):
        candidates, _ = load_cached_candidates("screwdriving")
        for c in candidates:
            if c.price_status is not PriceStatus.PUBLISHED:
                # The whole failure mode this guards: a missing price
                # rendering as "€0" and reading as free.
                assert c.price.value is None
                assert c.price.published is False

    def test_quote_required_is_kept_distinct_from_unknown(self):
        candidates, _ = load_cached_candidates("screwdriving")
        # Every researched manufacturer quotes rather than publishing — a
        # fact about this market, and different from "we failed to find it".
        assert all(c.price_status is PriceStatus.QUOTE_REQUIRED for c in candidates)

    def test_manufacturer_documents_outrank_distributors(self):
        multi = candidate(
            sources=[
                EquipmentSource(
                    source_id="d",
                    url="https://distributor.test/x",
                    source_type=SourceType.DISTRIBUTOR_PAGE,
                    title="Distributor",
                    retrieved_at=date(2026, 8, 21),
                ),
                source(),
            ]
        )
        assert multi.primary_source.source_type is SourceType.MANUFACTURER_DATASHEET

    def test_completeness_is_a_count_not_a_score(self):
        c = candidate(width_mm=PublishedSpec.of(27.0, "mm", "s1"))
        assert c.completeness.published == 1
        assert c.completeness.considered == 8


# Compatibility arithmetic

class TestCompatibility:
    def test_a_published_compatible_spec_passes(self, requirement):
        c = candidate(cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1"))
        check = _check(requirement, c, "cycle_time")
        assert check.status is CheckStatus.PASS
        assert "45" in check.candidate_text

    def test_a_published_incompatible_spec_fails(self, requirement):
        c = candidate(cycle_time_seconds=PublishedSpec.of(70.0, "s", "s1"))
        check = _check(requirement, c, "cycle_time")
        assert check.status is CheckStatus.FAIL
        assert check.reason

    def test_the_boundary_value_passes(self, requirement):
        # 52 s against a 52 s station keeps up exactly; calling it a failure
        # would reject equipment that meets the requirement.
        c = candidate(cycle_time_seconds=PublishedSpec.of(52.0, "s", "s1"))
        assert _check(requirement, c, "cycle_time").status is CheckStatus.PASS

    def test_a_missing_spec_is_unknown_never_pass(self, requirement):
        check = _check(requirement, candidate(), "cycle_time")
        assert check.status is CheckStatus.UNKNOWN
        assert check.status is not CheckStatus.PASS
        # The reason must say WHY nothing could be compared, not just
        # "unknown" — and it must name WHICH source failed to publish it,
        # because that is where the engineer has to go to ask.
        assert "does not publish" in check.reason.lower()
        assert "manufacturer" in check.reason.lower()

    def test_unknown_never_counts_toward_the_pass_total(self, requirement):
        report = check_compatibility(requirement, candidate())
        # The candidate publishes no specification at all, so the ONLY thing
        # that can pass is the capability it declares. Every field check is
        # UNKNOWN, and none of them was rounded up into the pass total.
        assert [c.field for c in report.checks if c.status is CheckStatus.PASS] == ["capability"]
        assert report.fail_count == 0
        assert report.unknown_count == len(report.checks) - 1

    def test_counts_are_transparent_and_add_up(self, requirement):
        report = check_compatibility(requirement, candidate())
        assert report.pass_count + report.fail_count + report.unknown_count == len(report.checks)
        assert report.summary() == (
            f"{report.pass_count} matched · {report.fail_count} mismatched · "
            f"{report.unknown_count} not verified"
        )

    def test_millimetres_are_converted_before_comparison(self, requirement):
        # 221 mm against a 2.0 m envelope. Comparing the raw numbers would
        c = candidate(length_mm=PublishedSpec.of(221.0, "mm", "s1"))
        assert _check(requirement, c, "footprint_length").status is CheckStatus.PASS

    def test_an_oversized_device_fails_on_footprint(self, requirement):
        c = candidate(length_mm=PublishedSpec.of(4000.0, "mm", "s1"))
        check = _check(requirement, c, "footprint_length")
        assert check.status is CheckStatus.FAIL

    def test_a_published_price_over_budget_fails(self, requirement):
        c = candidate(
            price=PublishedSpec.of(120000.0, "EUR", "s1"),
            price_status=PriceStatus.PUBLISHED,
        )
        assert _check(requirement, c, "budget").status is CheckStatus.FAIL

    def test_quote_required_is_unknown_and_says_so(self, requirement):
        check = _check(requirement, candidate(price_status=PriceStatus.QUOTE_REQUIRED), "budget")
        assert check.status is CheckStatus.UNKNOWN
        assert "quot" in check.candidate_text.lower()

    def test_an_unbounded_requirement_is_not_checked(self):
        bare = requirement_from_concept(concept_from_brief(BRIEF), "m-screwdriving")
        check = _check(bare, candidate(cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1")), "cycle_time")
        # The concept states no limit, so a 45 s machine cannot be said to
        # meet it — there is nothing to meet.
        assert check.status is CheckStatus.UNKNOWN

    def test_any_failure_blocks_regardless_of_passes(self, requirement):
        c = candidate(
            length_mm=PublishedSpec.of(50.0, "mm", "s1"),
            width_mm=PublishedSpec.of(50.0, "mm", "s1"),
            cycle_time_seconds=PublishedSpec.of(90.0, "s", "s1"),
        )
        report = check_compatibility(requirement, c)
        # Capability plus both footprint axes pass; the cycle time does not.
        assert report.pass_count == 3
        assert report.blocked is True
        # And the claim follows the failure, not the passes.
        assert report.claim is MatchClaim.CONSTRAINT_MISMATCH

    def test_the_report_is_not_stored_on_the_candidate(self, requirement):
        c = candidate()
        check_compatibility(requirement, c)
        # A verdict welded to the data would outlive the requirement that
        # produced it and mislead the next station that considers it.
        assert not hasattr(c, "compatibility")
        assert not hasattr(c, "status")

    def test_the_real_dataset_produces_only_derivable_verdicts(self, requirement):
        candidates, _ = load_cached_candidates("screwdriving")
        for c in candidates:
            report = check_compatibility(requirement, c)
            for check in report.checks:
                if check.status is CheckStatus.PASS:
                    # Every PASS must trace to a published number.
                    assert check.candidate_text != "Not published"


def _check(req, cand, field):
    report = check_compatibility(req, cand)
    return next(c for c in report.checks if c.field == field)


# Selection must not move engineering values

class TestSelectionSemantics:
    def test_selecting_does_not_change_simulation_parameters(self, draft, requirement):
        stage_before = next(s for s in draft.stages if s.id == "m-screwdriving")
        candidates, _ = load_cached_candidates("screwdriving")

        select_candidate(requirement, candidates[0])

        stage_after = next(s for s in draft.stages if s.id == "m-screwdriving")
        assert stage_after.cycle_time == stage_before.cycle_time
        assert stage_after.capacity == stage_before.capacity
        assert stage_after.operators_required == stage_before.operators_required

    def test_a_selection_records_its_source(self, requirement):
        candidates, _ = load_cached_candidates("screwdriving")
        selection = select_candidate(requirement, candidates[0])
        assert selection.source_url and selection.source_url.startswith("https://")
        assert selection.adopted_parameters == []

    def test_nothing_is_proposed_when_the_manufacturer_publishes_nothing(self, draft, requirement):
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        candidates, _ = load_cached_candidates("screwdriving")
        deprag = next(c for c in candidates if c.candidate_id == "deprag-dcam")
        assert proposed_parameter_changes(requirement, deprag, stage) == []

    def test_a_cycle_time_proposal_is_flagged_as_affecting_simulation(self, draft, requirement):
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        c = candidate(cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1"))
        change = next(ch for ch in proposed_parameter_changes(requirement, c, stage) if ch.field == "cycle_time")
        assert change.current_value == 52.0
        assert change.proposed_value == 45.0
        assert change.affects_simulation is True

    def test_a_device_envelope_is_never_offered_as_a_station_footprint(self, draft, requirement):
        # Found in live QA: the panel offered "replace 2.5 m with 0.027 m" for a Kolver
        # spindle.
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        c = candidate(
            width_mm=PublishedSpec.of(27.0, "mm", "s1"),
            length_mm=PublishedSpec.of(221.0, "mm", "s1"),
        )
        fields = [ch.field for ch in proposed_parameter_changes(requirement, c, stage)]
        assert "width" not in fields
        assert "length" not in fields

    def test_the_dimensions_are_still_used_for_the_fit_check(self, requirement):
        # Removing the adoption path must not remove the legitimate use.
        c = candidate(length_mm=PublishedSpec.of(221.0, "mm", "s1"))
        assert _check(requirement, c, "footprint_length").status is CheckStatus.PASS

    def test_adoption_without_approval_changes_nothing(self, draft, requirement):
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        c = candidate(cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1"))
        changes = proposed_parameter_changes(requirement, c, stage)

        updated, applied = adopt_parameters(stage, changes, approved_fields=[])

        assert applied == []
        assert updated.cycle_time.value == 52.0

    def test_only_the_approved_field_is_adopted(self, draft, requirement):
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        c = candidate(
            cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1"),
            operators_required=PublishedSpec.of(1.0, "", "s1"),
        )
        changes = proposed_parameter_changes(requirement, c, stage)

        updated, applied = adopt_parameters(stage, changes, approved_fields=["cycle_time"])

        assert [a.field for a in applied] == ["cycle_time"]
        assert updated.cycle_time.value == 45.0
        assert updated.operators_required.value == 2  # untouched

    def test_an_adopted_value_is_the_manufacturers_and_says_so(self, draft, requirement):
        """A published figure is MANUFACTURER, not CUSTOMER."""
        stage = next(s for s in draft.stages if s.id == "m-screwdriving")
        c = candidate(cycle_time_seconds=PublishedSpec.of(45.0, "s", "s1"))
        changes = proposed_parameter_changes(requirement, c, stage)

        updated, _ = adopt_parameters(stage, changes, approved_fields=["cycle_time"])

        assert updated.cycle_time.source is ValueSource.MANUFACTURER
        assert updated.cycle_time.source is not ValueSource.EXAMPLE_DATA
        assert "example-manufacturer" in (updated.cycle_time.detail or "")


# The HTTP surface

class TestDiscoveryApi:
    def _body(self, draft, **extra):
        body = {"draft": json.loads(draft.model_dump_json()), "station_id": "m-screwdriving"}
        body.update(extra)
        return body

    def test_discover_returns_requirement_and_candidates(self, client, draft):
        body = client.post("/equipment/discover", json=self._body(draft)).json()

        assert body["requirement"]["max_cycle_time_seconds"]["value"] == 52.0
        assert len(body["assessments"]) == 4
        assert body["freshness"] == "CACHED"
        assert body["verified_on"] == "2026-08-21"

    def test_every_returned_candidate_exposes_provenance(self, client, draft):
        body = client.post("/equipment/discover", json=self._body(draft)).json()
        for assessment in body["assessments"]:
            assert assessment["candidate"]["sources"]
            assert assessment["candidate"]["sources"][0]["url"].startswith("https://")

    def test_counts_are_reported_not_a_single_score(self, client, draft):
        body = client.post("/equipment/discover", json=self._body(draft)).json()
        first = body["assessments"][0]
        assert {"pass_count", "fail_count", "unknown_count"} <= set(first)
        assert "score" not in first
        assert "rating" not in first

    def test_an_unresearched_station_says_so(self, client, draft):
        body = client.post("/equipment/discover", json=self._body(draft, station_id="m-assembly")).json()
        assert body["assessments"] == []
        # The note has to distinguish "we have not researched this" from
        # "the market has nothing", and it names which of the two it is.
        assert body["capability"] is None
        assert "no researched equipment capability" in body["note"]
        assert "not a statement about the market" in body["note"]

    def test_an_unknown_station_is_a_client_error(self, client, draft):
        response = client.post("/equipment/discover", json=self._body(draft, station_id="m-nope"))
        assert response.status_code == 400

    def test_select_returns_proposals_but_applies_nothing(self, client, draft):
        body = client.post(
            "/equipment/select", json=self._body(draft, candidate_id="kolver-kds-nt120ca")
        ).json()

        assert body["selection"]["model"].startswith("KDS-NT120CA")
        # No researched manufacturer publishes a cycle time, so there is
        # nothing here that could rewrite the concept's physics.
        assert body["affects_simulation"] is False

    def test_adopt_with_no_approved_fields_returns_the_draft_unchanged(self, client, draft):
        body = client.post(
            "/equipment/adopt", json=self._body(draft, candidate_id="kolver-kds-nt120ca", approved_fields=[])
        ).json()

        assert body["applied"] == []
        assert body["requires_reverification"] is False
        stage = next(s for s in body["draft"]["stages"] if s["id"] == "m-screwdriving")
        assert stage["cycle_time"]["value"] == 52.0

    def test_selecting_an_unknown_candidate_is_404(self, client, draft):
        response = client.post("/equipment/select", json=self._body(draft, candidate_id="nope"))
        assert response.status_code == 404


# The Siemens handoff keeps working, and can carry the selection

class TestSiemensHandoffRelation:
    def test_selected_equipment_travels_in_the_exchange_package(self):
        from app.integrations.plant_simulation import exchange_from_factory
        from app.models.factory import Factory
        from app.models.layout import FactoryLayout

        examples = pathlib.Path(__file__).resolve().parents[2] / "examples"
        factory = Factory.model_validate(json.loads((examples / "electronics_line.json").read_text(encoding="utf-8")))
        layout = FactoryLayout.model_validate(
            json.loads((examples / "electronics_line_layout.json").read_text(encoding="utf-8"))
        )

        package = exchange_from_factory(
            factory,
            factory.products[0].id,
            layout=layout,
            equipment_selections={
                "m-screwdriving": {
                    "manufacturer": "Kolver S.r.l.",
                    "model": "KDS-NT120CA",
                    "source_url": "https://kolver.com/upl/EN_Catalog_CA.pdf",
                }
            },
        )

        station = next(s for s in package.stations if s.id == "m-screwdriving")
        assert station.selected_manufacturer == "Kolver S.r.l."
        assert station.selected_source_url.startswith("https://")
        # Metadata only — the process values are untouched.
        assert station.cycle_time_seconds == 52.0

    def test_selection_metadata_does_not_change_station_physics(self):
        from app.integrations.plant_simulation import exchange_from_factory
        from app.models.factory import Factory

        examples = pathlib.Path(__file__).resolve().parents[2] / "examples"
        factory = Factory.model_validate(json.loads((examples / "electronics_line.json").read_text(encoding="utf-8")))

        without = exchange_from_factory(factory, factory.products[0].id)
        with_selection = exchange_from_factory(
            factory,
            factory.products[0].id,
            equipment_selections={"m-screwdriving": {"manufacturer": "X", "model": "Y"}},
        )

        for a, b in zip(without.stations, with_selection.stations):
            assert a.cycle_time_seconds == b.cycle_time_seconds
            assert a.capacity == b.capacity
            assert a.operators_required == b.operators_required

    def test_the_no_equipment_assumption_is_dropped_once_something_is_selected(self):
        from app.integrations.plant_simulation import exchange_from_factory
        from app.models.factory import Factory

        examples = pathlib.Path(__file__).resolve().parents[2] / "examples"
        factory = Factory.model_validate(json.loads((examples / "electronics_line.json").read_text(encoding="utf-8")))

        package = exchange_from_factory(
            factory,
            factory.products[0].id,
            equipment_selections={"m-screwdriving": {"manufacturer": "Kolver S.r.l.", "model": "KDS-NT120CA"}},
        )

        blanket = "Stations are generic process requirements — no specific equipment has been selected."
        assert blanket not in package.open_assumptions
        # It still says so for the stations where it remains true.
        assert any("No specific equipment has been selected for:" in a for a in package.open_assumptions)


# Offline behaviour

def test_the_cached_dataset_needs_no_network():
    """The competition demo must not depend on a conference network."""
    # Both files, deliberately: the breadth phase moved the actual loading
    # into ``equipment_catalog``, so checking only this module would have
    # left the guard passing while guarding nothing.
    for module in (
        "app/services/equipment_discovery.py",
        "app/services/equipment_catalog.py",
    ):
        source_text = pathlib.Path(module).read_text(encoding="utf-8")
        for forbidden in ("requests", "httpx", "urllib", "socket", "aiohttp"):
            assert forbidden not in source_text, (
                f"{forbidden} in {module} would make discovery depend on the network"
            )


class TestProvenanceIsWrittenInWords:
    """Audit §20 — an enum name is not a phrase."""

    def test_every_value_source_has_a_human_phrase(self):
        from app.models.concept import ConceptStage
        from app.services.equipment_discovery import _describe_provenance

        for source in ValueSource:
            if source is ValueSource.UNKNOWN:
                continue  # an unknown value is not "known", so it never lists
            stage = ConceptStage(
                id="m-x",
                name="Screwdriving",
                process_type="screwdriving",
                cycle_time=SourcedFloat.of(48.0, source, "for this test"),
            )
            sentence = _describe_provenance(stage)
            assert source.value not in sentence, f"{source.value} leaked into: {sentence}"
            assert sentence.endswith(".")

    def test_a_stage_with_no_values_says_so_plainly(self):
        from app.models.concept import ConceptStage
        from app.services.equipment_discovery import _describe_provenance

        stage = ConceptStage(id="m-x", name="Screwdriving", process_type="screwdriving")
        assert "no engineering values yet" in _describe_provenance(stage)
