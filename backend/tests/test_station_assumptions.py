"""Phase 18B — the Station Assumption Assistant."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.llm.errors import LLMAuthenticationError
from app.main import app
from app.models.concept import ValueSource
from app.models.uncertainty import EstimateMethod, StationAssumptionProposal
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.concept_validation import concept_to_factory
from app.services.estimation import (
    LOCAL_HEURISTIC_METHOD_LABEL,
    AutomationLevel,
    EstimationRequest,
    apply_station_assumptions,
    propose_station_assumptions,
)
from app.services.local_estimator import propose_capacity, propose_operators
from app.services.simulation import run_simulation

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)

ASSEMBLY = (
    "Manual assembly of a small electronics enclosure: place PCB into housing, "
    "connect two cables and close the enclosure."
)
SCREWDRIVING = (
    "Manually fasten six screws into a small plastic electronics enclosure using an electric screwdriver."
)


@pytest.fixture
def draft():
    return concept_from_brief(BRIEF)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class Quota:
    """The account's real state: watsonx maps quota exhaustion to an auth error."""

    provider_name = "watsonx"
    model_name = "granite"

    def generate_structured(self, *args, **kwargs):
        raise LLMAuthenticationError("HTTP 403 token_quota_reached")


def request_for(stage_id, name, category, description, level="MANUAL", ops=1):
    return EstimationRequest(
        stage_id=stage_id, stage_name=name, process_category=category,
        description=description, automation_level=AutomationLevel(level), operations_per_unit=ops,
    )


# One description, three parameters

class TestMultiParameterProposal:
    def test_all_three_parameters_come_back_together(self):
        outcome = propose_station_assumptions(
            request_for("m-assembly", "Assembly", "assembly", ASSEMBLY), Quota()
        )
        proposal = outcome.proposal

        assert proposal.proposed_fields == ["cycle_time", "capacity", "operators"]
        assert proposal.cycle_time.working_value == 28.5
        assert proposal.capacity.working_value == 1
        assert proposal.operators.working_value == 1

    def test_each_parameter_carries_its_own_basis(self):
        proposal = propose_station_assumptions(
            request_for("m-assembly", "Assembly", "assembly", ASSEMBLY), Quota()
        ).proposal

        # Three different claims resting on three different things.
        bases = {proposal.cycle_time.basis, proposal.capacity.basis, proposal.operators.basis}
        assert len(bases) == 3
        assert "handling" in proposal.cycle_time.basis
        assert "one unit at a time" in proposal.capacity.basis
        assert "one person" in proposal.operators.basis

    def test_a_declined_field_falls_through_to_the_deterministic_reading(self):
        class Partial:
            provider_name, model_name = "watsonx", "granite-test"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "low_seconds": 20, "working_seconds": 26, "high_seconds": 34,
                        "confidence": "MEDIUM", "basis": "model reasoning",
                        "capacity": None, "capacity_basis": None,
                        "operators": 2, "operators_basis": "two people at this bench",
                    }

                return R()

        proposal = propose_station_assumptions(
            request_for("m-assembly", "Assembly", "assembly", ASSEMBLY), Partial()
        ).proposal

        # The model answered for two of three; the third is not left empty
        # and is not attributed to the model.
        assert proposal.cycle_time.method is EstimateMethod.LANGUAGE_MODEL
        assert proposal.operators.method is EstimateMethod.LANGUAGE_MODEL
        assert proposal.operators.working_value == 2
        assert proposal.capacity.method is EstimateMethod.LOCAL_HEURISTIC

    def test_an_unusable_model_figure_is_discarded_not_repaired(self):
        class Bad:
            provider_name, model_name = "watsonx", "granite-test"

            def generate_structured(self, *args, **kwargs):
                class R:
                    parsed = {
                        "low_seconds": 20, "working_seconds": 26, "high_seconds": 34,
                        "confidence": "MEDIUM", "basis": "ok",
                        "capacity": 0, "operators": -3,  # neither is a usable count
                    }

                return R()

        proposal = propose_station_assumptions(
            request_for("m-assembly", "Assembly", "assembly", ASSEMBLY), Bad()
        ).proposal

        assert proposal.capacity.method is EstimateMethod.LOCAL_HEURISTIC
        assert proposal.operators.method is EstimateMethod.LOCAL_HEURISTIC


# The workforce distinction (§3)

class TestWorkforceDistinction:
    def test_the_factory_workforce_never_becomes_a_station_demand(self, draft):
        # The brief says eight operators are AVAILABLE.
        assert draft.operators_available.value == 8

        for stage_id, name, category, text in (
            ("m-assembly", "Assembly", "assembly", ASSEMBLY),
            ("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING),
        ):
            proposal = propose_station_assumptions(
                request_for(stage_id, name, category, text, ops=6), Quota()
            ).proposal
            assert proposal.operators.working_value != 8
            assert proposal.operators.working_value == 1

    def test_a_line_of_estimated_stations_stays_simulatable(self, draft):
        # The consequence the distinction protects: had every station
        # claimed the whole pool, run_simulation would refuse the concept.
        filled = apply_example_engineering_data(draft)
        for stage in filled.stages:
            proposal = propose_station_assumptions(
                request_for(stage.id, stage.name, stage.process_type, f"Manual {stage.name.lower()} of one unit"),
                Quota(),
            ).proposal
            filled, _ = apply_station_assumptions(filled, proposal, ["capacity", "operators"])

        factory, product_id = concept_to_factory(filled)
        total_demand = sum(m.operators_required for m in factory.machines)
        assert total_demand <= factory.operators_available
        run_simulation(factory, product_id)  # must not raise

    def test_a_stated_station_count_is_read_from_the_description(self):
        proposal = propose_station_assumptions(
            request_for(
                "m-assembly", "Assembly", "assembly",
                "Manual assembly where two operators work together on one enclosure",
            ),
            Quota(),
        ).proposal
        assert proposal.operators.working_value == 2


# Capacity has real semantics (§4)

class TestCapacitySemantics:
    def test_parallel_fixtures_give_a_capacity_above_one(self):
        result = propose_capacity(
            process_category="assembly",
            description="Automatic cell places the PCB using two parallel fixtures simultaneously",
            automation_level="AUTOMATIC",
        )
        assert result is not None
        assert result.working_value == 2

    def test_a_batch_process_is_unknown_rather_than_a_number(self):
        # The simulator models a station as N concurrent single-unit servers.
        result = propose_capacity(
            process_category="curing",
            description="Batch oven cures a tray of 20 units for ten minutes",
            automation_level="AUTOMATIC",
        )
        assert result is None

    def test_an_automatic_station_without_detail_is_unknown(self):
        assert propose_capacity(
            process_category="assembly",
            description="The cell assembles the unit",
            automation_level="AUTOMATIC",
        ) is None

    def test_capacity_is_never_defaulted_to_one_by_the_estimator(self):
        # `concept_to_factory` defaults an absent capacity to 1 and documents that.
        assert propose_capacity(
            process_category="assembly", description="", automation_level="UNKNOWN"
        ) is None

    def test_an_automatic_station_leaves_operator_demand_unknown(self):
        # Somebody usually still loads it, and the description does not say
        # whether that is inside this station's cycle.
        assert propose_operators(description="The cell runs the operation", automation_level="AUTOMATIC") is None


# Repeated operations (§6)

class TestRepeatedOperations:
    def test_the_station_cycle_is_not_multiplied_wholesale(self):
        one = propose_station_assumptions(
            request_for("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING, ops=1), Quota()
        ).proposal
        six = propose_station_assumptions(
            request_for("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING, ops=6), Quota()
        ).proposal

        # Handling happens once, not six times, so six screws cost far less
        # than six whole stations.
        assert six.cycle_time.working_value < 6 * one.cycle_time.working_value
        assert six.cycle_time.working_value > one.cycle_time.working_value

    def test_the_basis_shows_the_decomposition(self):
        proposal = propose_station_assumptions(
            request_for("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING, ops=6), Quota()
        ).proposal

        basis = proposal.cycle_time.basis
        assert "handling" in basis
        assert "6 ×" in basis
        assert "per screw" in basis

    def test_repeats_do_not_change_capacity_or_operators(self):
        # Fastening six screws instead of one does not put a second unit in
        # the station or a second person beside it.
        one = propose_station_assumptions(
            request_for("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING, ops=1), Quota()
        ).proposal
        six = propose_station_assumptions(
            request_for("m-screwdriving", "Screwdriving", "screwdriving", SCREWDRIVING, ops=6), Quota()
        ).proposal

        assert one.capacity.working_value == six.capacity.working_value
        assert one.operators.working_value == six.operators.working_value


# Acceptance

class TestAcceptance:
    def _proposal(self):
        return propose_station_assumptions(
            request_for("m-assembly", "Assembly", "assembly", ASSEMBLY), Quota()
        ).proposal

    def test_accepting_all_writes_all_three(self, draft):
        updated, applied = apply_station_assumptions(
            draft, self._proposal(), ["cycle_time", "capacity", "operators"]
        )
        stage = next(s for s in updated.stages if s.id == "m-assembly")

        assert applied == ["cycle_time", "capacity", "operators"]
        assert stage.cycle_time.value == 28.5
        assert stage.capacity.value == 1
        assert stage.operators_required.value == 1

    def test_every_written_value_is_labelled_an_estimate(self, draft):
        updated, _ = apply_station_assumptions(
            draft, self._proposal(), ["cycle_time", "capacity", "operators"]
        )
        stage = next(s for s in updated.stages if s.id == "m-assembly")

        for value in (stage.cycle_time, stage.capacity, stage.operators_required):
            assert value.source is ValueSource.ENGINEERING_ESTIMATE
            assert value.source is not ValueSource.CUSTOMER

    def test_accepting_some_leaves_the_rest_unknown(self, draft):
        updated, applied = apply_station_assumptions(draft, self._proposal(), ["cycle_time"])
        stage = next(s for s in updated.stages if s.id == "m-assembly")

        assert applied == ["cycle_time"]
        assert stage.capacity.value is None
        assert stage.capacity.source is ValueSource.UNKNOWN
        assert stage.operators_required.value is None

    def test_accepting_nothing_changes_nothing(self, draft):
        updated, applied = apply_station_assumptions(draft, self._proposal(), [])
        assert applied == []
        assert updated == draft

    def test_the_detail_carries_the_method_and_basis(self, draft):
        updated, _ = apply_station_assumptions(draft, self._proposal(), ["capacity"])
        stage = next(s for s in updated.stages if s.id == "m-assembly")

        # The ⓘ affordance reads this, so it must say where the number came from and
        # what it rests on.
        assert LOCAL_HEURISTIC_METHOD_LABEL in stage.capacity.detail
        assert "one unit at a time" in stage.capacity.detail

    def test_a_field_that_was_never_proposed_is_not_invented(self, draft):
        bare = StationAssumptionProposal(stage_id="m-assembly", stage_name="Assembly")
        updated, applied = apply_station_assumptions(
            bare and draft, bare, ["cycle_time", "capacity", "operators"]
        )
        assert applied == []


# HTTP surface

class TestApi:
    def _draft(self, client):
        return client.post("/concept/from-brief", json={"brief": BRIEF, "name": None}).json()["draft"]

    def test_estimate_returns_the_whole_station(self, client):
        draft = self._draft(client)
        body = client.post(
            "/concept/estimate",
            json={
                "draft": draft, "stage_id": "m-assembly", "description": ASSEMBLY,
                "automation_level": "MANUAL", "operations_per_unit": 1,
            },
        ).json()

        assert body["proposal"]["cycle_time"]["working_value"] == 28.5
        assert body["proposal"]["capacity"]["working_value"] == 1
        assert body["proposal"]["operators"]["working_value"] == 1
        # The cycle-time-only field stays for anything already reading it.
        assert body["estimate"]["working_value"] == 28.5

    def test_accepting_writes_every_named_field(self, client):
        draft = self._draft(client)
        proposal = client.post(
            "/concept/estimate",
            json={"draft": draft, "stage_id": "m-assembly", "description": ASSEMBLY,
                  "automation_level": "MANUAL", "operations_per_unit": 1},
        ).json()["proposal"]

        body = client.post(
            "/concept/accept-assumptions",
            json={"draft": draft, "proposal": proposal,
                  "accepted_fields": ["cycle_time", "capacity", "operators"]},
        ).json()

        stage = next(s for s in body["draft"]["stages"] if s["id"] == "m-assembly")
        assert body["applied"] == ["cycle_time", "capacity", "operators"]
        assert stage["capacity"]["source"] == "ENGINEERING_ESTIMATE"
        # And the factory pool is untouched by a station-level acceptance.
        assert body["draft"]["operators_available"]["value"] == 8

    def test_an_unknown_stage_is_refused(self, client):
        draft = self._draft(client)
        proposal = {"stage_id": "m-nope", "stage_name": "Nope"}
        response = client.post(
            "/concept/accept-assumptions",
            json={"draft": draft, "proposal": proposal, "accepted_fields": []},
        )
        assert response.status_code == 400


# Regression (§13)

class TestRegression:
    def test_known_values_produce_unchanged_results(self):
        filled = apply_example_engineering_data(concept_from_brief(BRIEF))
        factory, product_id = concept_to_factory(filled)
        result = run_simulation(factory, product_id)

        assert result.target_units == 1900
        assert result.completed_units == 1105
        assert result.demand_gap_units == 795.0
        assert result.system.bottleneck_machine_id == "m-screwdriving"

    def test_the_example_data_path_is_untouched(self):
        filled = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = next(s for s in filled.stages if s.id == "m-screwdriving")
        assert stage.cycle_time.value == 52.0
        assert stage.cycle_time.source is ValueSource.EXAMPLE_DATA
