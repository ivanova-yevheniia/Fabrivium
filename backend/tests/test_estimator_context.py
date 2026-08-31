"""G10/G11 — the estimator does not start from a blank form."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.process_draft import ManufacturingProcessDraft
from app.models.product import ProductUnderstanding
from app.services.concept_builder import concept_from_brief
from app.services.estimation import (
    AutomationLevel,
    EstimationRequest,
    apply_station_assumptions,
    propose_station_assumptions,
)
from app.services.input_adapters import ingest_text
from app.services.process_editing import link_to_requirements
from app.services.process_planning import plan_process
from app.services.product_intelligence import understand_product
from app.services.product_to_concept import concept_from_product, station_context
from app.services.requirement_coverage import coverage_for
from tests.test_product_understanding import REFERENCE, REQUIREMENTS


@pytest.fixture
def understanding() -> ProductUnderstanding:
    return understand_product(
        ingest_text(REFERENCE.read_text(encoding="utf-8"), name="reference.txt"),
        None,
        product_name="Compact electronics controller",
    ).understanding


@pytest.fixture
def accepted_process(understanding) -> ManufacturingProcessDraft:
    """A route an engineer has finished reviewing — see the Phase 19 suite."""
    draft = plan_process(understanding)
    draft = draft.model_copy(update={"operations": [op.accept() for op in draft.operations]})
    unresolved = [item.fact_key for item in coverage_for(understanding, draft).unresolved]
    if unresolved:
        target = next(op for op in draft.operations if op.process_type == "assembly")
        draft = link_to_requirements(draft, target.id, unresolved)
    return draft


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# The link: a station knows which reviewed operation it is

class TestTheStationKnowsItsOperation:
    def test_every_stage_links_back_to_the_operation_it_was_built_from(
        self, understanding, accepted_process
    ):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        by_id = {op.id: op for op in accepted_process.accepted}

        # One stage per reviewed operation, each naming its own — the link,
        # not a name match and not an index.
        assert [s.source_operation_id for s in draft.stages] == [op.id for op in accepted_process.accepted]
        for stage in draft.stages:
            assert by_id[stage.source_operation_id].name == stage.name

    def test_the_repeat_count_is_reachable_through_the_link(
        self, understanding, accepted_process
    ):
        """The whole of G11, at the level the frontend consumes it."""
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        by_id = {op.id: op for op in accepted_process.accepted}

        repeats = {
            stage.id: by_id[stage.source_operation_id].repeated_operations
            for stage in draft.stages
        }

        # The fixture's route states a count for at least one station, and
        # the count read through the link is the reviewed one — whichever
        # operation happens to carry it.
        stated = {stage_id: count for stage_id, count in repeats.items() if count is not None}
        assert stated, "the reviewed route states no repeat count at all"
        for stage_id, count in stated.items():
            operation = by_id[
                next(s for s in draft.stages if s.id == stage_id).source_operation_id
            ]
            assert operation.repeated_operations == count

    def test_an_edited_repeat_count_is_seen_through_the_same_link(
        self, understanding, accepted_process
    ):
        """6 → 4 on the route, with no concept rebuild."""
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        stage = next(
            s
            for s in draft.stages
            if next(
                op for op in accepted_process.accepted if op.id == s.source_operation_id
            ).repeated_operations
        )
        operation = next(op for op in accepted_process.accepted if op.id == stage.source_operation_id)
        before = operation.repeated_operations

        edited = accepted_process.model_copy(
            update={
                "operations": [
                    op.model_copy(update={"repeated_operations": before - 2})
                    if op.id == operation.id
                    else op
                    for op in accepted_process.operations
                ]
            }
        )

        found = next(op for op in edited.accepted if op.id == stage.source_operation_id)
        assert found.repeated_operations == before - 2

    def test_a_concept_built_from_a_brief_links_to_nothing(self):
        # There is no reviewed operation behind a hand-built route, and the
        # station says so rather than pointing at something plausible.
        draft = concept_from_brief(
            "An assembly line with assembly, screwdriving, inspection and packaging."
        )
        assert draft.stages
        assert all(stage.source_operation_id is None for stage in draft.stages)

    def test_the_station_context_names_the_operation_id(self, understanding, accepted_process):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        stage = draft.stages[0]
        context = station_context(understanding, accepted_process, stage.id)

        assert context["operation_id"] == stage.source_operation_id


# The estimate records what it was composed under

def _propose(stage_name: str, category: str, description: str, repeats: int | None):
    return propose_station_assumptions(
        EstimationRequest(
            stage_id="s1",
            stage_name=stage_name,
            process_category=category,
            description=description,
            automation_level=AutomationLevel.MANUAL,
            operations_per_unit=repeats,
        ),
        None,
    )


class TestTheEstimateUsesAndRecordsTheCount:
    def test_the_propagated_count_changes_the_number(self):
        """G11's reason for existing, stated as arithmetic."""
        one = _propose("Screw fastening", "screwdriving", "Screw fastening.", 1)
        six = _propose("Screw fastening", "screwdriving", "Screw fastening.", 6)

        assert one.proposal and six.proposal
        assert six.proposal.cycle_time.working_value > one.proposal.cycle_time.working_value

    def test_the_range_records_the_count_it_used(self):
        outcome = _propose("Screw fastening", "screwdriving", "Screw fastening.", 6)
        assert outcome.proposal.cycle_time.operations_per_unit == 6

    def test_a_count_read_from_the_description_is_recorded_too(self):
        # The engineer left the field blank and the description carried it.
        outcome = _propose(
            "Screw fastening", "screwdriving", "Six screws into the enclosure.", None
        )
        assert outcome.proposal.cycle_time.operations_per_unit == 6

    def test_accepting_keeps_the_assumption_on_the_station(
        self, understanding, accepted_process
    ):
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        stage = draft.stages[0]
        outcome = propose_station_assumptions(
            EstimationRequest(
                stage_id=stage.id,
                stage_name=stage.name,
                process_category=stage.process_type,
                description=f"{stage.name}.",
                automation_level=AutomationLevel.MANUAL,
                operations_per_unit=6,
            ),
            None,
        )
        applied, _ = apply_station_assumptions(draft, outcome.proposal, ["cycle_time"])

        written = next(s for s in applied.stages if s.id == stage.id)
        assert written.cycle_time_estimate.operations_per_unit == 6

    def test_the_assumption_survives_the_wire_and_a_reload(
        self, client, understanding, accepted_process
    ):
        """Provenance is only worth anything if it comes back."""
        draft = concept_from_product(understanding, accepted_process, REQUIREMENTS)
        stage = draft.stages[0]

        estimate = client.post(
            "/concept/estimate",
            json={
                "draft": draft.model_dump(mode="json"),
                "stage_id": stage.id,
                "description": f"{stage.name}.",
                "automation_level": "MANUAL",
                "operations_per_unit": 6,
                "mode": "LOCAL_ONLY",
            },
        )
        assert estimate.status_code == 200
        proposal = estimate.json()["proposal"]
        assert proposal["cycle_time"]["operations_per_unit"] == 6

        accepted = client.post(
            "/concept/accept-assumptions",
            json={
                "draft": draft.model_dump(mode="json"),
                "proposal": proposal,
                "accepted_fields": ["cycle_time"],
            },
        )
        assert accepted.status_code == 200

        stored = accepted.json()["draft"]["stages"][0]
        assert stored["cycle_time_estimate"]["operations_per_unit"] == 6
        assert stored["source_operation_id"] == stage.source_operation_id

        # And it parses back into the model the next session would load.
        from app.models.concept import FactoryConceptDraft

        # `cycle_time_estimate` is typed loosely on the stage to keep the
        # models layer acyclic, so a reloaded one is the same mapping the
        # frontend reads — and that is the shape which has to carry the
        # assumption, because it is what a reopened project holds.
        reloaded = FactoryConceptDraft.model_validate(accepted.json()["draft"])
        assert reloaded.stages[0].cycle_time_estimate["operations_per_unit"] == 6
        assert reloaded.stages[0].source_operation_id == stage.source_operation_id

    def test_a_directly_entered_value_records_no_assumption(self):
        # An engineer who types 47 seconds has not estimated six of anything,
        # and a repeat count on that range would be an invention. It stays
        # None, which is what keeps the staleness rule from firing on values
        # no route change can invalidate.
        from app.services.estimation import manual_range

        typed = manual_range(low=40, working=47, high=55, basis="Measured on a comparable line.")
        assert typed.operations_per_unit is None
