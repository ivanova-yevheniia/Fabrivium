"""P0 — re-estimating, and the line between a proposal and a decision."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import SourcedFloat, ValueSource
from app.models.uncertainty import Confidence, EstimatedRange, EstimateMethod
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.estimation import (
    PROTECTED_SOURCES,
    AutomationLevel,
    EstimationMode,
    EstimationRequest,
    propose_station_assumptions,
    protected_values,
)
from app.services.input_resolution import write_input

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def concept():
    return apply_example_engineering_data(concept_from_brief(BRIEF))


@pytest.fixture
def screwdriving(concept):
    stage = next(s for s in concept.stages if "screw" in s.process_type.lower())
    return stage


def _propose(stage, **overrides):
    fields = {
        "stage_id": stage.id,
        "stage_name": stage.name,
        "process_category": stage.process_type,
        "description": "six screws into a plastic electronics enclosure",
        "automation_level": AutomationLevel.MANUAL,
        "operations_per_unit": 6,
    }
    fields.update(overrides)
    return propose_station_assumptions(
        EstimationRequest(**fields), None, mode=EstimationMode.LOCAL_ONLY
    )


# 9 — a changed input produces a changed estimate

class TestReEstimation:
    def test_changing_the_repetition_count_changes_the_estimate(self, screwdriving):
        six = _propose(screwdriving, operations_per_unit=6)
        two = _propose(screwdriving, operations_per_unit=2)

        assert six.proposal and two.proposal
        assert six.proposal.cycle_time.working_value != two.proposal.cycle_time.working_value

    def test_changing_the_automation_level_changes_the_estimate(self, screwdriving):
        manual = _propose(
            screwdriving,
            description="six screws driven by hand",
            automation_level=AutomationLevel.MANUAL,
        )
        automatic = _propose(
            screwdriving,
            description="six screws driven by an automatic screwdriving cell",
            automation_level=AutomationLevel.AUTOMATIC,
        )

        assert manual.proposal and automatic.proposal
        assert (
            automatic.proposal.cycle_time.working_value
            != manual.proposal.cycle_time.working_value
        )

    def test_the_estimate_is_a_function_of_its_inputs_not_of_the_station_id(self, screwdriving):
        """
        The same station, asked two different questions, must get two different answers.
        """
        first = _propose(screwdriving, operations_per_unit=6)
        again = _propose(screwdriving, operations_per_unit=6)
        different = _propose(screwdriving, operations_per_unit=12)

        assert first.proposal.cycle_time.working_value == again.proposal.cycle_time.working_value
        assert first.proposal.cycle_time.working_value != different.proposal.cycle_time.working_value

    def test_the_basis_states_the_arithmetic_that_produced_it(self, screwdriving):
        """A recomputed number is only worth having if it can be argued with."""
        outcome = _propose(screwdriving, operations_per_unit=6)
        assert outcome.proposal.cycle_time.basis
        assert outcome.proposal.cycle_time.method is EstimateMethod.LOCAL_HEURISTIC

    def test_the_endpoint_recomputes_rather_than_returning_the_stored_value(
        self, client, concept, screwdriving
    ):
        """The stage already holds a cycle time from the demo dataset."""
        stored = screwdriving.cycle_time.value
        body = {
            "draft": concept.model_dump(mode="json"),
            "stage_id": screwdriving.id,
            "description": "twelve screws into a steel enclosure, by hand",
            "automation_level": "MANUAL",
            "operations_per_unit": 12,
            "mode": "LOCAL_ONLY",
        }
        first = client.post("/concept/estimate", json=body).json()

        body["operations_per_unit"] = 2
        body["description"] = "two screws into a plastic enclosure, by hand"
        second = client.post("/concept/estimate", json=body).json()

        assert first["proposal"]["cycle_time"]["working_value"] != stored
        assert (
            first["proposal"]["cycle_time"]["working_value"]
            != second["proposal"]["cycle_time"]["working_value"]
        )


# D3 / D4 / D6 — override semantics

class TestOverrideSemantics:
    def test_an_engineer_value_can_be_replaced_again_and_again(self, concept, screwdriving):
        """D3 — 48 estimated, 47 engineer, 44 engineer."""
        key = f"stage.{screwdriving.id}.cycle_time"
        estimated = write_input(concept, key, 48, ValueSource.ENGINEERING_ESTIMATE, "reference bands")
        assert estimated.stage_by_id(screwdriving.id).cycle_time.source is ValueSource.ENGINEERING_ESTIMATE

        first = write_input(estimated, key, 47, ValueSource.ENGINEER, "stopwatch on the pilot line")
        assert first.stage_by_id(screwdriving.id).cycle_time.value == 47
        assert first.stage_by_id(screwdriving.id).cycle_time.source is ValueSource.ENGINEER

        second = write_input(first, key, 44, ValueSource.ENGINEER, "re-measured")
        assert second.stage_by_id(screwdriving.id).cycle_time.value == 44
        assert second.stage_by_id(screwdriving.id).cycle_time.source is ValueSource.ENGINEER

    def test_an_override_retires_the_range_that_justified_the_old_number(self, concept, screwdriving):
        """The ⓘ panel must never explain 44 with the reasoning behind 48."""
        key = f"stage.{screwdriving.id}.cycle_time"
        estimated = write_input(concept, key, 48, ValueSource.ENGINEERING_ESTIMATE, "reference bands")
        overridden = write_input(estimated, key, 44, ValueSource.ENGINEER, "measured")

        assert overridden.stage_by_id(screwdriving.id).cycle_time_estimate is None

    def test_the_revision_log_names_what_was_actually_replaced(self, concept, screwdriving):
        """
        D5 — "what is active now, where did it come from, and what did it replace?"
        """
        from app.services.input_resolution import _superseded_estimate_reason

        stage = screwdriving.model_copy(
            update={"cycle_time": SourcedFloat.of(44, ValueSource.ENGINEER, "stopwatch")}
        )
        reason = _superseded_estimate_reason(
            stage, SourcedFloat.of(39, ValueSource.ENGINEER, "re-measured on the pilot line")
        )

        assert "44" in reason
        assert "engineer-entered value" in reason
        assert "engineering estimate" not in reason
        assert "re-measured on the pilot line" in reason

    def test_replacing_an_estimate_still_says_estimate_and_quotes_its_band(
        self, concept, screwdriving
    ):
        """The distinction only means something if it cuts both ways — and the
        plausible band is quoted only where one genuinely exists."""
        from app.services.estimation import apply_estimate
        from app.services.input_resolution import _superseded_estimate_reason

        outcome = _propose(screwdriving)
        applied = apply_estimate(concept, screwdriving.id, outcome.proposal.cycle_time)
        stage = applied.stage_by_id(screwdriving.id)
        assert stage.cycle_time.source is ValueSource.ENGINEERING_ESTIMATE

        reason = _superseded_estimate_reason(
            stage, SourcedFloat.of(44, ValueSource.ENGINEER, "stopwatch")
        )
        assert "engineering estimate" in reason
        assert " s)" in reason, "the band belongs to the estimate, so it is quoted here"

    def test_an_override_over_an_estimate_leaves_a_revision(self, concept, screwdriving):
        """The trail exists at all, through the real write path."""
        from app.services.estimation import apply_estimate

        outcome = _propose(screwdriving)
        applied = apply_estimate(concept, screwdriving.id, outcome.proposal.cycle_time)
        overridden = write_input(
            applied,
            f"stage.{screwdriving.id}.cycle_time",
            44,
            ValueSource.ENGINEER,
            "stopwatch on the pilot line",
        )

        revisions = overridden.stage_by_id(screwdriving.id).revisions
        assert len(revisions) == 1
        assert revisions[0].previous_source is ValueSource.ENGINEERING_ESTIMATE
        assert revisions[0].new_value == 44
        assert revisions[0].new_source is ValueSource.ENGINEER

    def test_an_engineer_number_is_never_relabelled_as_an_estimate(self, concept, screwdriving):
        """D4 — the whole point of the source enum."""
        key = f"stage.{screwdriving.id}.cycle_time"
        overridden = write_input(concept, key, 44, ValueSource.ENGINEER, "measured")
        source = overridden.stage_by_id(screwdriving.id).cycle_time.source

        assert source is ValueSource.ENGINEER
        assert source is not ValueSource.ENGINEERING_ESTIMATE
        assert source is not ValueSource.CUSTOMER

    def test_protected_values_names_what_would_be_lost(self, concept, screwdriving):
        key = f"stage.{screwdriving.id}.cycle_time"
        overridden = write_input(concept, key, 44, ValueSource.ENGINEER, "measured")

        protected = protected_values(overridden, screwdriving.id, ["cycle_time"])
        assert [item.field for item in protected] == ["cycle_time"]
        assert protected[0].value == 44
        assert protected[0].source == "ENGINEER"
        assert "44" in protected[0].describe()

    def test_an_estimate_is_not_protected_from_being_re_estimated(self, concept, screwdriving):
        """Re-estimating over a previous ESTIMATE needs no ceremony — that is
        the ordinary refinement loop, and asking for confirmation every time
        would train people to click through it."""
        key = f"stage.{screwdriving.id}.cycle_time"
        estimated = write_input(concept, key, 48, ValueSource.ENGINEERING_ESTIMATE, "bands")
        assert protected_values(estimated, screwdriving.id, ["cycle_time"]) == []

    def test_the_protected_set_is_exactly_the_non_estimate_sources(self):
        assert PROTECTED_SOURCES == {
            ValueSource.ENGINEER,
            ValueSource.MEASURED,
            ValueSource.DOCUMENT,
            ValueSource.CUSTOMER,
            ValueSource.MANUFACTURER,
        }
        assert ValueSource.ENGINEERING_ESTIMATE not in PROTECTED_SOURCES
        assert ValueSource.EXAMPLE_DATA not in PROTECTED_SOURCES


class TestOverrideApi:
    """D6 over HTTP: the proposal is always available; replacing is a choice."""

    def _estimate_body(self, draft, stage_id, **overrides):
        body = {
            "draft": draft.model_dump(mode="json"),
            "stage_id": stage_id,
            "low": 40.0,
            "working_value": 45.0,
            "high": 52.0,
            "basis": "reference bands",
            "confidence": "MEDIUM",
            "method": "LOCAL_HEURISTIC",
        }
        body.update(overrides)
        return body

    def test_applying_over_an_engineer_value_is_refused_by_default(
        self, client, concept, screwdriving
    ):
        overridden = write_input(
            concept, f"stage.{screwdriving.id}.cycle_time", 44, ValueSource.ENGINEER, "measured"
        )
        response = client.post(
            "/concept/apply-estimate", json=self._estimate_body(overridden, screwdriving.id)
        )

        assert response.status_code == 409
        # Structured, and INSIDE `detail`: the frontend's API client unwraps
        # `body.detail` on every non-2xx response, so a payload sitting
        # beside it never reaches the panel that has to act on it.
        detail = response.json()["detail"]
        assert detail["conflict"] == "PROTECTED_VALUE"
        assert detail["protected"][0]["value"] == 44
        assert detail["protected"][0]["source"] == "ENGINEER"
        assert "Confirm the replacement" in detail["message"]

    def test_applying_over_an_engineer_value_succeeds_once_confirmed(
        self, client, concept, screwdriving
    ):
        overridden = write_input(
            concept, f"stage.{screwdriving.id}.cycle_time", 44, ValueSource.ENGINEER, "measured"
        )
        response = client.post(
            "/concept/apply-estimate",
            json=self._estimate_body(overridden, screwdriving.id, replace_existing=True),
        )

        assert response.status_code == 200
        stage = next(
            s for s in response.json()["draft"]["stages"] if s["id"] == screwdriving.id
        )
        assert stage["cycle_time"]["value"] == 45.0
        assert stage["cycle_time"]["source"] == "ENGINEERING_ESTIMATE"

    def test_applying_over_an_estimate_needs_no_confirmation(self, client, concept, screwdriving):
        estimated = write_input(
            concept,
            f"stage.{screwdriving.id}.cycle_time",
            48,
            ValueSource.ENGINEERING_ESTIMATE,
            "bands",
        )
        response = client.post(
            "/concept/apply-estimate", json=self._estimate_body(estimated, screwdriving.id)
        )
        assert response.status_code == 200

    def test_accepting_station_assumptions_respects_the_same_rule(
        self, client, concept, screwdriving
    ):
        overridden = write_input(
            concept, f"stage.{screwdriving.id}.cycle_time", 44, ValueSource.ENGINEER, "measured"
        )
        outcome = _propose(screwdriving)
        assert outcome.proposal is not None

        body = {
            "draft": overridden.model_dump(mode="json"),
            "proposal": outcome.proposal.model_dump(mode="json"),
            "accepted_fields": ["cycle_time"],
        }
        assert client.post("/concept/accept-assumptions", json=body).status_code == 409

        body["replace_existing"] = True
        confirmed = client.post("/concept/accept-assumptions", json=body)
        assert confirmed.status_code == 200
        assert confirmed.json()["applied"] == ["cycle_time"]

    def test_a_field_the_engineer_did_not_accept_is_not_protected_against(
        self, client, concept, screwdriving
    ):
        """The guard is about what would actually be written, not about the
        station as a whole — accepting only the operator count must not be
        blocked by an engineer-entered cycle time it never touches."""
        overridden = write_input(
            concept, f"stage.{screwdriving.id}.cycle_time", 44, ValueSource.ENGINEER, "measured"
        )
        assert protected_values(overridden, screwdriving.id, ["operators"]) == []

    def test_an_estimate_proposal_is_still_returned_for_a_protected_station(
        self, client, concept, screwdriving
    ):
        """D6 — 'present the new proposed range, but require explicit acceptance'."""
        overridden = write_input(
            concept, f"stage.{screwdriving.id}.cycle_time", 44, ValueSource.ENGINEER, "measured"
        )
        response = client.post(
            "/concept/estimate",
            json={
                "draft": overridden.model_dump(mode="json"),
                "stage_id": screwdriving.id,
                "description": "six screws into a plastic electronics enclosure",
                "automation_level": "MANUAL",
                "operations_per_unit": 6,
                "mode": "LOCAL_ONLY",
            },
        )
        assert response.status_code == 200
        assert response.json()["proposal"]["cycle_time"]["working_value"] > 0


class TestEstimateRangeIntegrity:
    def test_an_inverted_range_is_refused_rather_than_repaired(self, client, concept, screwdriving):
        response = client.post(
            "/concept/apply-estimate",
            json={
                "draft": concept.model_dump(mode="json"),
                "stage_id": screwdriving.id,
                "low": 60.0,
                "working_value": 45.0,
                "high": 50.0,
                "basis": "typo",
                "replace_existing": True,
            },
        )
        assert response.status_code == 400

    def test_the_range_model_still_rejects_a_working_value_outside_its_bounds(self):
        with pytest.raises(ValueError):
            EstimatedRange(
                low=10,
                working_value=99,
                high=20,
                unit="s",
                confidence=Confidence.MEDIUM,
                method=EstimateMethod.ENGINEER,
                basis="out of bounds",
            )
