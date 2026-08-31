"""Phase 18 — uncertainty-aware concept engineering."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import SourcedFloat, ValueSource
from app.models.uncertainty import (
    EVIDENCE_STRENGTH,
    Confidence,
    EstimateMethod,
    EstimatedRange,
    ValueRevision,
    is_upgrade,
)
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.concept_validation import concept_to_factory
from app.services.estimation import (
    AutomationLevel,
    EstimationMode,
    EstimationRequest,
    apply_estimate,
    derive_takt_seconds,
    estimate_cycle_time,
    manual_range,
)
from app.services.readiness import assess_readiness
from app.services.sensitivity import derive_cycle_time_requirement, sweep_cycle_time
from app.services.simulation import run_simulation

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)


@pytest.fixture
def draft():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


@pytest.fixture
def bare_draft():
    """A concept with no engineering values — the honest starting state."""
    return concept_from_brief(BRIEF)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def estimate() -> EstimatedRange:
    return manual_range(low=35, working=45, high=55, basis="6 fastening operations + handling allowance")


# Provenance can never be laundered

class TestProvenanceIntegrity:
    def test_an_estimate_resolves_as_an_estimate(self):
        resolved = estimate().resolve()
        assert resolved.source is ValueSource.ENGINEERING_ESTIMATE
        assert resolved.source is not ValueSource.CUSTOMER
        assert resolved.source is not ValueSource.MANUFACTURER

    def test_the_working_value_carries_the_range_it_came_from(self):
        resolved = estimate().resolve()
        assert resolved.value == 45.0
        # The provenance string must let someone reconstruct the claim.
        assert "35" in (resolved.detail or "") and "55" in (resolved.detail or "")
        assert "fastening" in (resolved.detail or "")

    def test_applying_an_estimate_does_not_relabel_customer_values(self, draft):
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        assert updated.production_target.source is ValueSource.CUSTOMER
        assert updated.operators_available.source is ValueSource.CUSTOMER

    def test_example_data_does_not_become_an_estimate(self, draft):
        # Only the touched stage changes; the others keep saying where they
        # really came from.
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        others = [s for s in updated.stages if s.id != "m-screwdriving"]
        assert all(s.cycle_time.source is ValueSource.EXAMPLE_DATA for s in others)

    def test_unknown_never_becomes_zero(self, bare_draft):
        stage = next(s for s in bare_draft.stages if s.id == "m-screwdriving")
        assert stage.cycle_time.value is None
        assert stage.cycle_time.source is ValueSource.UNKNOWN
        assert stage.cycle_time.value != 0

    def test_a_derived_value_is_calculated_not_estimated(self, draft):
        takt = derive_takt_seconds(draft)
        assert takt.source is ValueSource.CALCULATED
        assert takt.source is not ValueSource.ENGINEERING_ESTIMATE
        # 2 shifts x 8 h = 57,600 s over 1,900 units.
        assert takt.value == pytest.approx(57600 / 1900)

    def test_takt_is_unknown_while_the_schedule_is(self, bare_draft):
        assert derive_takt_seconds(bare_draft).known is False

    def test_evidence_strength_orders_the_sources(self):
        assert is_upgrade(ValueSource.UNKNOWN, ValueSource.ENGINEERING_ESTIMATE)
        assert is_upgrade(ValueSource.ENGINEERING_ESTIMATE, ValueSource.MANUFACTURER)
        assert is_upgrade(ValueSource.MANUFACTURER, ValueSource.CUSTOMER)
        # An estimate must never outrank a manufacturer figure.
        assert not is_upgrade(ValueSource.MANUFACTURER, ValueSource.ENGINEERING_ESTIMATE)
        assert EVIDENCE_STRENGTH[ValueSource.ENGINEERING_ESTIMATE] < EVIDENCE_STRENGTH[ValueSource.MANUFACTURER]

    def test_a_revision_records_what_changed_and_why(self):
        revision = ValueRevision(
            field="cycle_time",
            previous_value=45.0,
            previous_source=ValueSource.ENGINEERING_ESTIMATE,
            new_value=40.0,
            new_source=ValueSource.MANUFACTURER,
            reason="Manufacturer datasheet published a figure",
            evidence_url="https://example.test/datasheet.pdf",
        )
        assert is_upgrade(revision.previous_source, revision.new_source)

    def test_a_revision_that_changes_nothing_is_rejected(self):
        with pytest.raises(ValueError):
            ValueRevision(
                field="cycle_time",
                previous_value=45.0,
                previous_source=ValueSource.ENGINEERING_ESTIMATE,
                new_value=45.0,
                new_source=ValueSource.ENGINEERING_ESTIMATE,
                reason="no change",
            )


# The range cannot contradict itself

class TestRangeIntegrity:
    def test_an_inverted_range_is_rejected(self):
        with pytest.raises(ValueError, match="inverted"):
            EstimatedRange(
                low=55, working_value=45, high=35, unit="s",
                confidence=Confidence.MEDIUM, method=EstimateMethod.ENGINEER, basis="x",
            )

    def test_a_working_value_outside_its_range_is_rejected(self):
        # The two would be claiming different things, and the KPIs would
        # carry a number the range does not admit.
        with pytest.raises(ValueError, match="outside"):
            EstimatedRange(
                low=35, working_value=70, high=55, unit="s",
                confidence=Confidence.MEDIUM, method=EstimateMethod.ENGINEER, basis="x",
            )

    def test_a_basis_is_required(self):
        with pytest.raises(ValueError):
            EstimatedRange(
                low=35, working_value=45, high=55, unit="s",
                confidence=Confidence.MEDIUM, method=EstimateMethod.ENGINEER, basis="",
            )

    def test_sweep_points_are_the_range_deduplicated(self):
        assert estimate().sweep_points() == [35.0, 45.0, 55.0]
        flat = manual_range(low=40, working=40, high=40, basis="measured once")
        assert flat.sweep_points() == [40.0]


# The deterministic boundary

class TestDeterministicBoundary:
    def test_the_simulator_receives_exactly_the_working_value(self, draft):
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        factory, _ = concept_to_factory(updated)
        machine = next(m for m in factory.machines if m.id == "m-screwdriving")
        assert machine.cycle_time == 45.0

    def test_the_factory_model_carries_no_range(self, draft):
        # The audit's central decision: intervals never reach the trusted core.
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        factory, _ = concept_to_factory(updated)
        machine = next(m for m in factory.machines if m.id == "m-screwdriving")
        assert isinstance(machine.cycle_time, float)
        assert not hasattr(machine, "cycle_time_low")
        assert not hasattr(machine, "cycle_time_estimate")

    def test_simulation_stays_deterministic_with_an_estimate(self, draft):
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        factory, product_id = concept_to_factory(updated)
        first = run_simulation(factory, product_id)
        second = run_simulation(factory, product_id)
        assert first.completed_units == second.completed_units
        assert first.system.bottleneck_machine_id == second.system.bottleneck_machine_id


# Sensitivity uses the real simulator

class TestSensitivity:
    def test_each_point_matches_a_direct_simulation(self, draft):
        # The property that makes the sweep trustworthy: a sweep point and
        # a plain run of the concept at that value must agree exactly.
        updated = apply_estimate(draft, "m-screwdriving", estimate())
        result = sweep_cycle_time(updated, "m-screwdriving", [45.0])

        factory, product_id = concept_to_factory(updated)
        direct = run_simulation(factory, product_id)

        assert result.points[0].completed_units == float(direct.completed_units)
        assert result.points[0].bottleneck_machine_id == direct.system.bottleneck_machine_id

    def test_slower_cycles_never_produce_more(self, draft):
        result = sweep_cycle_time(draft, "m-screwdriving", [35.0, 45.0, 55.0])
        outputs = [p.completed_units for p in result.points]
        assert outputs == sorted(outputs, reverse=True)
        assert result.monotonic is True

    def test_the_run_count_is_the_number_of_distinct_values(self, draft):
        result = sweep_cycle_time(draft, "m-screwdriving", [45.0, 45.0, 55.0])
        assert result.simulations_run == 2

    def test_an_unknown_stage_is_refused(self, draft):
        with pytest.raises(ValueError, match="no stage"):
            sweep_cycle_time(draft, "m-nope", [45.0])


# Threshold derivation

class TestThresholdDerivation:
    def _target(self, draft, units: float):
        return draft.model_copy(
            update={"production_target": SourcedFloat.of(units, ValueSource.CUSTOMER, "Stated in the brief")}
        )

    def test_the_threshold_is_a_real_simulated_boundary(self, draft):
        achievable = self._target(draft, 1400)
        requirement = derive_cycle_time_requirement(achievable, "m-screwdriving", fastest=10.0, slowest=60.0)

        assert requirement.threshold is not None
        # Verified independently: at the threshold the target is met, and a
        at = sweep_cycle_time(achievable, "m-screwdriving", [requirement.threshold]).points[0]
        beyond = sweep_cycle_time(achievable, "m-screwdriving", [requirement.threshold + 1.0]).points[0]
        assert at.meets_target is True
        assert beyond.meets_target is False

    @pytest.mark.parametrize("target", [800, 1200, 1400, 1600])
    def test_the_threshold_is_never_more_permissive_than_takt(self, draft, target):
        """The simulated threshold must never exceed takt time."""
        scenario = self._target(draft, target)
        requirement = derive_cycle_time_requirement(scenario, "m-screwdriving", fastest=5.0, slowest=90.0)
        takt = derive_takt_seconds(scenario).value

        assert requirement.threshold is not None
        assert requirement.threshold <= takt + 1e-6

    def test_no_threshold_is_claimed_when_the_station_is_not_the_constraint(self, draft):
        # The golden target of 1,900 is unreachable with one station per
        # stage: Assembly limits it, so no screwdriving figure achieves it.
        requirement = derive_cycle_time_requirement(draft, "m-screwdriving", fastest=10.0, slowest=60.0)
        assert requirement.threshold is None
        assert "not what is holding the target back" in requirement.reason
        # The station that IS the constraint is named, not keyed: this text
        # is read by an engineer, and "m-assembly" is a database identifier.
        assert "Assembly" in requirement.reason
        assert "m-assembly" not in requirement.reason

    def test_no_threshold_is_claimed_when_every_value_passes(self, draft):
        easy = self._target(draft, 300)
        requirement = derive_cycle_time_requirement(easy, "m-screwdriving", fastest=10.0, slowest=60.0)
        assert requirement.threshold is None
        assert "does not constrain" in requirement.reason

    def test_the_search_is_bounded(self, draft):
        requirement = derive_cycle_time_requirement(self._target(draft, 1400), "m-screwdriving", fastest=1.0, slowest=300.0)
        assert requirement.simulations_run <= 40

    def test_the_threshold_is_calculated_provenance(self, draft):
        requirement = derive_cycle_time_requirement(self._target(draft, 1400), "m-screwdriving", fastest=10.0, slowest=60.0)
        sourced = requirement.as_sourced()
        assert sourced.source is ValueSource.CALCULATED
        assert "simulations" in (sourced.detail or "")

    def test_a_refused_threshold_yields_an_unknown_not_a_zero(self, draft):
        requirement = derive_cycle_time_requirement(draft, "m-screwdriving", fastest=10.0, slowest=60.0)
        sourced = requirement.as_sourced()
        assert sourced.value is None
        assert sourced.source is ValueSource.UNKNOWN


# Readiness

class TestReadiness:
    def test_a_bare_concept_is_not_simulation_ready(self, bare_draft):
        readiness = assess_readiness(bare_draft)
        assert readiness.simulation_ready is False
        assert readiness.verdict == "NOT YET SIMULATION READY"
        assert readiness.unknown_critical > 0

    def test_the_example_path_reaches_ready(self, draft):
        readiness = assess_readiness(draft)
        assert readiness.simulation_ready is True
        assert readiness.unknown_critical == 0

    def test_counts_distinguish_estimates_from_customer_facts(self, draft):
        before = assess_readiness(draft).counts
        after = assess_readiness(apply_estimate(draft, "m-screwdriving", estimate())).counts

        assert after.engineering_estimates == before.engineering_estimates + 1
        assert after.example_data == before.example_data - 1
        # A customer fact is never consumed to make room for an estimate.
        assert after.customer_facts == before.customer_facts

    def test_there_is_no_percentage_score(self):
        from app.services.readiness import ConceptReadiness

        assert "score" not in ConceptReadiness.model_fields
        assert "percent" not in ConceptReadiness.model_fields
        assert "completeness" not in ConceptReadiness.model_fields


# Honest degradation

class TestFallbackIsHonest:
    """Phase 18B changed what "honest" means here, and deliberately."""

    def _request(self, **overrides):
        base = dict(
            stage_id="m-screwdriving",
            stage_name="Screwdriving",
            process_category="screwdriving",
            description="Six screws into a plastic electronics enclosure",
            automation_level=AutomationLevel.ASSISTED,
            operations_per_unit=6,
        )
        base.update(overrides)
        return EstimationRequest(**base)

    def test_no_provider_falls_back_rather_than_stopping(self):
        outcome = estimate_cycle_time(self._request(), None)

        assert outcome.estimate is not None
        assert outcome.estimate.method is EstimateMethod.LOCAL_HEURISTIC
        assert outcome.fell_back is True

    def test_a_failing_provider_falls_back(self):
        from app.llm.errors import LLMUnavailableError

        class Failing:
            provider_name = "failing"
            model_name = "none"

            def generate_structured(self, *args, **kwargs):
                raise LLMUnavailableError("HTTP 403 token_quota_reached")

        outcome = estimate_cycle_time(self._request(), Failing())

        assert outcome.estimate is not None
        assert outcome.fell_back is True
        # Kept for developers, never as the headline the engineer reads.
        assert "token_quota_reached" in (outcome.provider_note or "")

    def test_the_fallback_value_is_still_only_an_estimate(self):
        # A change of mechanism must never upgrade the epistemic status of the number.
        outcome = estimate_cycle_time(self._request(), None)
        resolved = outcome.estimate.resolve()

        assert resolved.source is ValueSource.ENGINEERING_ESTIMATE
        assert resolved.source is not ValueSource.CUSTOMER
        assert resolved.source is not ValueSource.MANUFACTURER

    def test_a_working_language_model_is_used_first(self):
        class Working:
            provider_name = "watsonx"
            model_name = "granite-test"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "low_seconds": 30,
                        "working_seconds": 38,
                        "high_seconds": 50,
                        "confidence": "MEDIUM",
                        "basis": "reasoned from the description",
                    }

                return R()

        outcome = estimate_cycle_time(self._request(), Working())

        assert outcome.estimate.method is EstimateMethod.LANGUAGE_MODEL
        assert outcome.estimate.model_name == "granite-test"
        assert outcome.fell_back is False
        assert outcome.provider_note is None

    def test_a_nonsense_proposal_falls_back_instead_of_being_repaired(self):
        class Nonsense:
            provider_name = "nonsense"
            model_name = "test-model"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "low_seconds": 55.0,
                        "working_seconds": 45.0,
                        "high_seconds": 35.0,  # inverted
                        "confidence": "HIGH",
                        "basis": "nonsense",
                    }

                return R()

        outcome = estimate_cycle_time(self._request(), Nonsense())

        # The bad range is discarded, not patched into shape.
        assert outcome.estimate.method is EstimateMethod.LOCAL_HEURISTIC
        assert outcome.fell_back is True

    def test_llm_only_mode_reports_the_failure_instead_of_falling_back(self):
        from app.llm.errors import LLMTimeoutError

        class Slow:
            provider_name = "slow"
            model_name = "none"

            def generate_structured(self, *args, **kwargs):
                raise LLMTimeoutError("timed out")

        outcome = estimate_cycle_time(self._request(), Slow(), mode=EstimationMode.LLM_ONLY)

        assert outcome.estimate is None
        assert outcome.missing is not None

    def test_local_only_mode_never_calls_the_provider(self):
        class Exploding:
            provider_name = "exploding"
            model_name = "none"

            def generate_structured(self, *args, **kwargs):
                raise AssertionError("the provider must not be consulted in LOCAL_ONLY mode")

        outcome = estimate_cycle_time(self._request(), Exploding(), mode=EstimationMode.LOCAL_ONLY)

        assert outcome.estimate.method is EstimateMethod.LOCAL_HEURISTIC
        assert outcome.fell_back is False

    def test_an_unsupported_family_still_refuses(self):
        # The fallback is not a licence to answer everything: eight of the
        # twelve families the concept builder knows have no reference data.
        outcome = estimate_cycle_time(
            self._request(process_category="welding", description="Weld two brackets"), None
        )

        assert outcome.estimate is None
        assert "no engineering reference data" in outcome.missing.reason
        assert outcome.missing.questions

    def test_too_little_information_refuses_rather_than_guessing(self):
        outcome = estimate_cycle_time(
            self._request(
                description="Some work happens here",
                automation_level=AutomationLevel.UNKNOWN,
                operations_per_unit=None,
            ),
            None,
        )

        assert outcome.estimate is None
        assert outcome.missing.questions

    def test_a_contradiction_stops_estimation_entirely(self):
        outcome = estimate_cycle_time(
            self._request(
                description="Manual assembly by an operator",
                automation_level=AutomationLevel.AUTOMATIC,
            ),
            None,
        )

        assert outcome.estimate is None
        assert outcome.contradiction is not None
        assert outcome.contradiction.described_as == "MANUAL"
        assert outcome.contradiction.selected_as == "AUTOMATIC"

    def test_the_manual_path_needs_nothing_external(self):
        result = manual_range(low=30, working=38, high=50, basis="measured on a comparable line")
        assert result.method is EstimateMethod.ENGINEER
        assert result.model_name is None

    def test_the_deterministic_derivation_needs_nothing_external(self, draft):
        assert derive_takt_seconds(draft).known is True


# Equipment discovery receives the derived requirement

class TestEquipmentIntegration:
    def test_a_derived_threshold_replaces_the_stage_assumption(self, draft):
        from app.services.equipment_discovery import requirement_from_concept

        limit = SourcedFloat.of(41.1, ValueSource.CALCULATED, "Derived from 15 simulations")
        requirement = requirement_from_concept(draft, "m-screwdriving", derived_cycle_time_limit=limit)

        assert requirement.max_cycle_time_seconds.value == 41.1
        assert requirement.max_cycle_time_seconds.source is ValueSource.CALCULATED
        # The engineer must be told the bound answers a different question.
        assert "derived by simulation" in requirement.provenance

    def test_without_a_threshold_the_stage_value_is_used(self, draft):
        from app.services.equipment_discovery import requirement_from_concept

        requirement = requirement_from_concept(draft, "m-screwdriving")
        assert requirement.max_cycle_time_seconds.value == 52.0

    def test_an_unknown_threshold_does_not_replace_anything(self, draft):
        from app.services.equipment_discovery import requirement_from_concept

        requirement = requirement_from_concept(
            draft, "m-screwdriving", derived_cycle_time_limit=SourcedFloat.unknown()
        )
        assert requirement.max_cycle_time_seconds.value == 52.0

    def test_unknown_manufacturer_data_stays_unknown_against_a_derived_limit(self, draft):
        from app.services.equipment_compatibility import CheckStatus, check_compatibility
        from app.services.equipment_discovery import load_cached_candidates, requirement_from_concept

        limit = SourcedFloat.of(41.1, ValueSource.CALCULATED, "Derived from 15 simulations")
        requirement = requirement_from_concept(draft, "m-screwdriving", derived_cycle_time_limit=limit)
        candidates, _ = load_cached_candidates("screwdriving")

        for candidate in candidates:
            check = next(c for c in check_compatibility(requirement, candidate).checks if c.field == "cycle_time")
            # A stricter requirement must not turn silence into a verdict.
            assert check.status is CheckStatus.UNKNOWN
            assert check.status is not CheckStatus.FAIL
            assert check.status is not CheckStatus.PASS


# The golden path is untouched

class TestGoldenRegression:
    def test_golden_values_are_unchanged(self, draft):
        factory, product_id = concept_to_factory(draft)
        result = run_simulation(factory, product_id)

        assert result.target_units == 1900
        assert result.completed_units == 1105
        assert result.demand_gap_units == 795.0
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    def test_the_example_data_path_still_works(self, bare_draft):
        filled = apply_example_engineering_data(bare_draft)
        stage = next(s for s in filled.stages if s.id == "m-screwdriving")
        assert stage.cycle_time.value == 52.0
        assert stage.cycle_time.source is ValueSource.EXAMPLE_DATA

    def test_direct_manual_entry_still_works(self, bare_draft):
        stages = [
            s.model_copy(update={"cycle_time": SourcedFloat.of(30.0, ValueSource.CUSTOMER, "Engineer entered")})
            for s in bare_draft.stages
        ]
        manual = bare_draft.model_copy(
            update={
                "stages": stages,
                "shifts_per_day": bare_draft.shifts_per_day.of(2, ValueSource.CUSTOMER, "Engineer entered")
                if hasattr(bare_draft.shifts_per_day, "of")
                else bare_draft.shifts_per_day,
            }
        )
        stage = next(s for s in manual.stages if s.id == "m-screwdriving")
        assert stage.cycle_time.value == 30.0
        assert stage.cycle_time.source is ValueSource.CUSTOMER


# HTTP surface

class TestApi:
    def _body(self, draft, **extra):
        body = {"draft": json.loads(draft.model_dump_json())}
        body.update(extra)
        return body

    def test_readiness_reports_counts_not_a_score(self, client, draft):
        body = client.post("/concept/readiness", json=self._body(draft)).json()
        assert body["verdict"] == "SIMULATION READY"
        assert body["counts"]["customer_facts"] > 0
        assert "score" not in body
        assert body["takt_seconds"]["source"] == "CALCULATED"

    def test_estimate_falls_back_instead_of_dead_ending(self, client, draft, monkeypatch):
        monkeypatch.setattr("app.main._llm_provider", lambda: None)
        body = client.post(
            "/concept/estimate",
            json=self._body(
                draft,
                stage_id="m-screwdriving",
                description="Six screws into an enclosure",
                operations_per_unit=6,
            ),
        ).json()

        assert body["estimate"] is not None
        assert body["estimate"]["method"] == "LOCAL_HEURISTIC"
        assert body["fell_back"] is True
        # Takt is deterministic and must survive the provider being absent.
        assert body["takt_seconds"]["value"] is not None

    def test_the_process_family_comes_from_the_stage(self, client, draft, monkeypatch):
        # Typed by nobody: the heuristic picks its bands by family, and a
        # caller-supplied family could drift from the concept.
        monkeypatch.setattr("app.main._llm_provider", lambda: None)
        body = client.post(
            "/concept/estimate",
            json=self._body(
                draft,
                stage_id="m-assembly",
                description="place PCB, connect two cables and close the housing",
                automation_level="MANUAL",
            ),
        ).json()

        assert body["estimate"] is not None
        assert "assembly step" in body["estimate"]["basis"]

    def test_a_contradiction_is_reported_before_any_estimate(self, client, draft, monkeypatch):
        monkeypatch.setattr("app.main._llm_provider", lambda: None)
        body = client.post(
            "/concept/estimate",
            json=self._body(
                draft,
                stage_id="m-assembly",
                description="Manual assembly performed by an operator",
                automation_level="AUTOMATIC",
            ),
        ).json()

        assert body["estimate"] is None
        assert body["contradiction"]["described_as"] == "MANUAL"

    def test_apply_estimate_tags_the_value_as_an_estimate(self, client, draft):
        body = client.post(
            "/concept/apply-estimate",
            json=self._body(
                draft, stage_id="m-screwdriving", low=35, working_value=45, high=55,
                basis="6 fastening operations", confidence="MEDIUM",
            ),
        ).json()

        stage = next(s for s in body["draft"]["stages"] if s["id"] == "m-screwdriving")
        assert stage["cycle_time"]["value"] == 45
        assert stage["cycle_time"]["source"] == "ENGINEERING_ESTIMATE"

    def test_apply_estimate_rejects_a_contradictory_range(self, client, draft):
        response = client.post(
            "/concept/apply-estimate",
            json=self._body(draft, stage_id="m-screwdriving", low=35, working_value=70, high=55, basis="x"),
        )
        assert response.status_code == 400

    def test_sensitivity_reports_real_runs(self, client, draft):
        body = client.post(
            "/concept/sensitivity", json=self._body(draft, stage_id="m-screwdriving", values=[35, 45, 55])
        ).json()

        assert body["simulations_run"] == 3
        assert [p["value"] for p in body["points"]] == [35, 45, 55]
        assert body["monotonic"] is True

    def test_threshold_refuses_when_the_station_is_not_the_constraint(self, client, draft):
        body = client.post(
            "/concept/threshold", json=self._body(draft, stage_id="m-screwdriving", fastest=10, slowest=60)
        ).json()

        assert body["threshold"] is None
        assert body["requirement_value"]["value"] is None
        assert "holding the target back" in body["statement"]


# Audit §1 / §2 — one source of truth for the run count, and no internal
# identifiers on screen.

class TestReportedCountsAndStationNames:
    """What the search says it cost, and what it calls the station."""

    def _achievable(self, draft):
        # A target the concept can actually reach, so the bisection runs.
        return draft.model_copy(
            update={"production_target": SourcedFloat.of(1400, ValueSource.CUSTOMER, "Stated in the brief")}
        )

    def test_the_reported_count_never_exceeds_the_documented_bound(self, draft):
        from app.services import sensitivity

        result = sensitivity.derive_cycle_time_requirement(
            self._achievable(draft), "m-screwdriving", fastest=10.0, slowest=60.0
        )
        # The search really did bisect — otherwise the bound proves nothing.
        assert result.threshold is not None
        assert result.simulations_run > 6
        assert result.simulations_run <= sensitivity.MAX_SEARCH_RUNS

    def test_the_count_in_the_prose_is_the_count_in_the_field(self, draft):
        # Two statements of the same quantity must not be computed twice.
        result = derive_cycle_time_requirement(
            self._achievable(draft), "m-screwdriving", fastest=10.0, slowest=60.0
        )
        assert result.threshold is not None
        assert f"{result.simulations_run} simulations" in result.reason

    def test_a_limiting_station_is_named_not_keyed(self, draft):
        # Force the "this stage is not the constraint" branch, which is the
        # one that names the station that IS.
        result = derive_cycle_time_requirement(draft, "m-packaging", fastest=0.5, slowest=1.0)
        assert "m-" not in result.reason
        assert result.threshold is None or "m-" not in result.reason


class TestPlaybackAgreesWithTheSimulationItShows:
    """Audit §7 — the twin must not tell a different story from the KPIs."""

    def _demo(self):
        import json
        import pathlib

        from app.models.factory import Factory

        root = pathlib.Path(__file__).resolve().parents[2]
        factory = Factory.model_validate(
            json.loads((root / "examples" / "electronics_line.json").read_text(encoding="utf-8"))
        )
        return factory, factory.products[0].id

    def test_the_trace_horizon_is_the_factorys_own_operating_window(self):
        # A 24 h trace beside a two-shift result would invite exactly the
        # comparison that is not valid.
        from app.services.simulation import run_simulation_traced

        factory, product_id = self._demo()
        trace = run_simulation_traced(factory, product_id)
        expected = factory.shifts_per_day * factory.hours_per_shift * 3600
        assert trace.horizon_seconds == pytest.approx(expected)

    def test_the_final_sample_matches_the_reported_result(self):
        from app.services.simulation import run_simulation, run_simulation_traced

        factory, product_id = self._demo()
        trace = run_simulation_traced(factory, product_id)
        result = run_simulation(factory, product_id)

        last = trace.system_series[-1]
        assert last.completed_units == result.completed_units
        assert last.current_bottleneck_machine_id == result.system.bottleneck_machine_id

    def test_completed_units_never_go_backwards(self):
        from app.services.simulation import run_simulation_traced

        factory, product_id = self._demo()
        series = run_simulation_traced(factory, product_id).system_series
        assert all(a.completed_units <= b.completed_units for a, b in zip(series, series[1:]))


# The estimate contract Phase "Engineering estimate transparency".

class TestEveryProvenanceIsAccountedFor:
    def test_every_value_source_has_an_evidence_rank(self):
        """A partial ranking is not a ranking."""
        unranked = [s.value for s in ValueSource if s not in EVIDENCE_STRENGTH]
        assert unranked == [], f"ValueSource members with no evidence rank: {unranked}"

    def test_is_upgrade_answers_for_the_override_sources(self):
        assert is_upgrade(ValueSource.ENGINEERING_ESTIMATE, ValueSource.ENGINEER)
        assert is_upgrade(ValueSource.ENGINEER, ValueSource.MEASURED)
        # An estimate never outranks a person's decision or an observation.
        assert not is_upgrade(ValueSource.ENGINEER, ValueSource.ENGINEERING_ESTIMATE)
        assert not is_upgrade(ValueSource.MEASURED, ValueSource.ENGINEERING_ESTIMATE)

    def test_a_persons_sources_tie_rather_than_outranking_each_other(self):
        """No scale can order CUSTOMER, ENGINEER and DOCUMENT in the abstract."""
        pairs = (
            (ValueSource.CUSTOMER, ValueSource.ENGINEER),
            (ValueSource.ENGINEER, ValueSource.DOCUMENT),
        )
        for a, b in pairs:
            assert not is_upgrade(a, b)
            assert not is_upgrade(b, a)

    def test_readiness_counts_every_value_exactly_once(self, draft):
        from app.services.readiness import _all_values

        counts = assess_readiness(draft).counts
        assert counts.total == len(_all_values(draft))

    def test_an_engineer_override_is_counted_as_an_engineer_decision(self, draft):
        """The bucket that did not exist, for the source an override makes."""
        from app.services.input_resolution import write_input
        from app.services.readiness import _all_values

        before = assess_readiness(draft).counts
        overridden = write_input(
            draft, "stage.m-screwdriving.cycle_time", 41.0, ValueSource.ENGINEER, "Pilot cell stopwatch"
        )
        after = assess_readiness(overridden).counts

        assert after.engineer_decisions == before.engineer_decisions + 1
        assert after.total == len(_all_values(overridden))


class TestEngineerOverrideRetiresTheEstimate:
    @pytest.fixture
    def estimated(self, draft):
        """A concept whose screwdriving cycle time IS an estimate."""
        return apply_estimate(draft, "m-screwdriving", estimate())

    def _stage(self, concept):
        return concept.stage_by_id("m-screwdriving")

    def test_the_estimate_survives_while_it_still_describes_the_value(self, estimated):
        stage = self._stage(estimated)
        assert stage.cycle_time.value == 45.0
        assert stage.cycle_time_estimate is not None
        assert stage.cycle_time_estimate.working_value == 45.0

    def test_an_override_drops_the_range_it_replaced(self, estimated):
        from app.services.input_resolution import write_input

        after = write_input(
            estimated, "stage.m-screwdriving.cycle_time", 40.0, ValueSource.ENGINEER, "Pilot cell"
        )
        stage = self._stage(after)

        assert stage.cycle_time.value == 40.0
        assert stage.cycle_time.source is ValueSource.ENGINEER
        # The whole point: nothing downstream can still read 35-55 s as the
        # basis of 40 s, or sweep it as this concept's plausible range.
        assert stage.cycle_time_estimate is None

    def test_retyping_the_same_number_as_an_engineer_also_retires_it(self, estimated):
        """Same digits, different authorship."""
        from app.services.input_resolution import write_input

        after = write_input(
            estimated,
            "stage.m-screwdriving.cycle_time",
            45.0,
            ValueSource.ENGINEER,
            "Confirmed on the pilot cell",
        )
        stage = self._stage(after)

        assert stage.cycle_time.source is ValueSource.ENGINEER
        assert stage.cycle_time_estimate is None

    def test_clearing_the_value_also_clears_the_estimate(self, estimated):
        from app.services.input_resolution import write_input

        after = write_input(estimated, "stage.m-screwdriving.cycle_time", None, ValueSource.ENGINEER, None)
        stage = self._stage(after)

        assert stage.cycle_time.value is None
        assert stage.cycle_time.source is ValueSource.UNKNOWN
        assert stage.cycle_time_estimate is None

    def test_the_override_is_recorded_so_it_can_be_explained(self, estimated):
        from app.services.input_resolution import write_input

        after = write_input(
            estimated, "stage.m-screwdriving.cycle_time", 40.0, ValueSource.ENGINEER, "Pilot cell stopwatch"
        )
        revisions = self._stage(after).revisions

        assert len(revisions) == 1
        revision = revisions[-1]
        assert revision.field == "cycle_time"
        assert revision.previous_value == 45.0
        assert revision.previous_source is ValueSource.ENGINEERING_ESTIMATE
        assert revision.new_value == 40.0
        assert revision.new_source is ValueSource.ENGINEER
        assert "45" in revision.reason and "Pilot cell stopwatch" in revision.reason

    def test_writing_a_different_field_leaves_the_estimate_alone(self, estimated):
        """Only the cycle time's own estimate answers for the cycle time."""
        from app.services.input_resolution import write_input

        after = write_input(
            estimated, "stage.m-screwdriving.operators_required", 2, ValueSource.ENGINEER, "Two-handed"
        )
        assert self._stage(after).cycle_time_estimate is not None

    def test_rewriting_the_identical_value_records_no_revision(self, estimated):
        """A restore is not a revision."""
        from app.services.input_resolution import write_input

        stage = self._stage(estimated)
        after = write_input(
            estimated,
            "stage.m-screwdriving.cycle_time",
            stage.cycle_time.value,
            stage.cycle_time.source,
            stage.cycle_time.detail,
        )
        assert self._stage(after).revisions == []
        assert self._stage(after).cycle_time_estimate is not None

    def test_a_rerun_uses_the_engineer_value_not_the_estimate(self, estimated):
        """The contract's last clause: the simulator runs what the engineer said."""
        from app.services.concept_validation import concept_to_factory
        from app.services.input_resolution import write_input

        after = write_input(
            estimated, "stage.m-screwdriving.cycle_time", 40.0, ValueSource.ENGINEER, "Pilot cell"
        )
        factory, _ = concept_to_factory(after)
        machine = next(m for m in factory.machines if m.id == "m-screwdriving")

        assert machine.cycle_time == 40.0

    def test_the_resolution_plan_stops_offering_the_retired_basis(self, estimated):
        """UI contract: the info panel must never justify a number with
        another number's reasoning."""
        from app.services.input_resolution import resolution_plan, write_input

        key = "stage.m-screwdriving.cycle_time"
        row = next(i for i in resolution_plan(estimated).inputs if i.key == key)
        assert row.estimate is not None
        assert row.superseded is None

        after = write_input(estimated, key, 40.0, ValueSource.ENGINEER, "Pilot cell")
        row = next(i for i in resolution_plan(after).inputs if i.key == key)

        assert row.estimate is None
        assert row.superseded is not None and "45" in row.superseded


class TestOverrideOverTheApi:
    """The same contract, through the wire, on a draft that has been JSON."""

    def _estimated(self):
        return apply_estimate(
            apply_example_engineering_data(concept_from_brief(BRIEF)), "m-screwdriving", estimate()
        )

    def test_resolve_input_retires_the_estimate_and_says_so(self, client):
        draft = json.loads(self._estimated().model_dump_json())

        response = client.post(
            "/concept/resolve-input",
            json={
                "draft": draft,
                "key": "stage.m-screwdriving.cycle_time",
                "value": 40.0,
                "source": "ENGINEER",
                "detail": "Pilot cell stopwatch",
            },
        )
        assert response.status_code == 200
        stage = next(s for s in response.json()["draft"]["stages"] if s["id"] == "m-screwdriving")

        assert stage["cycle_time"]["value"] == 40.0
        assert stage["cycle_time"]["source"] == "ENGINEER"
        assert stage["cycle_time_estimate"] is None
        assert stage["revisions"][-1]["previous_value"] == 45.0

    def test_the_plan_carries_the_estimate_contract_for_an_estimated_value(self, client):
        draft = json.loads(self._estimated().model_dump_json())

        response = client.post("/concept/resolution-plan", json={"draft": draft})
        assert response.status_code == 200
        row = next(
            i for i in response.json()["inputs"] if i["key"] == "stage.m-screwdriving.cycle_time"
        )

        # Every field the contract requires, inspectable without a second
        # request: value, unit, method, basis, range, confidence.
        assert row["estimate"]["working_value"] == 45.0
        assert row["estimate"]["low"] == 35.0
        assert row["estimate"]["high"] == 55.0
        assert row["estimate"]["unit"] == "s"
        assert row["estimate"]["method"] == "ENGINEER"
        assert row["estimate"]["confidence"] in ("HIGH", "MEDIUM", "LOW")
        assert row["estimate"]["basis"]
        assert row["superseded"] is None

    def test_the_sweep_refuses_a_retired_range_rather_than_using_it(self, client):
        """/concept/sensitivity with no values used to sweep the dead estimate."""
        from app.services.input_resolution import write_input

        overridden = write_input(
            self._estimated(), "stage.m-screwdriving.cycle_time", 40.0, ValueSource.ENGINEER, "Pilot cell"
        )
        response = client.post(
            "/concept/sensitivity",
            json={"draft": json.loads(overridden.model_dump_json()), "stage_id": "m-screwdriving"},
        )

        assert response.status_code == 400
        assert "estimated range" in response.json()["detail"]
