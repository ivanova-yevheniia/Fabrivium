"""P0 — the project workspace, and the revision model that keeps its evidence honest."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.concept import ValueSource
from app.models.project import (
    PROJECT_SCHEMA_VERSION,
    Artifact,
    ArtifactStatus,
    Channel,
    ProjectState,
    Stamp,
)
from app.services.concept_builder import concept_from_brief
from app.services.concept_example_data import apply_example_engineering_data
from app.services.input_resolution import write_input
from app.services.project_revisions import apply_revisions, describe_changes, stale_report
from app.services.project_store import ProjectNotFound, ProjectStore

BRIEF = (
    "We need a new electronics assembly line. The product goes through assembly, screwdriving, "
    "inspection and packaging. We need about 1,900 units per day. The available production area is "
    "30 by 18 meters. We have eight operators."
)


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    return ProjectStore(tmp_path / "projects")


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("FACTORYMIND_PROJECT_DIR", str(tmp_path / "api-projects"))
    return TestClient(app)


@pytest.fixture
def concept_draft() -> dict:
    return apply_example_engineering_data(concept_from_brief(BRIEF)).model_dump(mode="json")


def _process_draft(*operations) -> dict:
    return {
        "product_name": "Compact electronics controller",
        "planner": "PROCESS_PLANNING_SKILL",
        "method": "LOCAL_RULES",
        "model_name": None,
        "open_questions": [],
        "operations": list(operations),
    }


def _operation(op_id: str, name: str, **overrides) -> dict:
    operation = {
        "id": op_id,
        "process_type": "assembly",
        "name": name,
        "description": f"{name} the unit.",
        "repeated_operations": None,
        "basis": "Derived from a product fact.",
        "source_fact_keys": [],
        "evidence": [],
        "fact_status": "RULE_DERIVED",
        "confidence": "HIGH",
        "status": "ACCEPTED",
    }
    operation.update(overrides)
    return operation


def _verified(state: ProjectState, *artifacts: Artifact) -> ProjectState:
    """The same state, claiming these artifacts were just produced."""
    return state.model_copy(deep=True, update={"produced": [a.value for a in artifacts]})


# 1 / 13 — round-trip

class TestPersistence:
    def test_every_important_field_round_trips(self, store, concept_draft):
        state = ProjectState()
        state.product.name = "Compact electronics controller"
        state.product.description = "A controller in a plastic enclosure, six screws."
        state.product.understanding = {"product_name": "Compact electronics controller", "facts": []}
        state.product.understanding_model_used = False
        state.process.draft = _process_draft(_operation("op-1", "Assembly"))
        state.requirements.text = "1,900 units per day across 2 shifts of 8 hours."
        state.concept.draft = concept_draft
        state.concept.product_id = "p-controller"
        state.concept.verified_from = concept_draft
        state.results.selected_strategy_id = "s-2"
        state.results.explore_requests = ["reach 1900 a day"]
        state.layout.applied = {"baseline": {"placements": [{"machine_id": "m1", "x": 2.0, "y": 3.0, "rotation_deg": 90.0}]}}
        state.equipment.selections = {"Screwdriving": {"candidate_id": "c-1", "manufacturer": "Atlas", "model": "MicroTorque"}}
        state.stage = "VERIFIED"

        created = store.create("Controller line", state)
        reopened = store.load(created.project_id)

        assert reopened.schema_version == PROJECT_SCHEMA_VERSION
        assert reopened.name == "Controller line"
        assert reopened.created_at and reopened.updated_at
        assert reopened.state.product.name == "Compact electronics controller"
        assert reopened.state.product.description.startswith("A controller")
        assert reopened.state.process.draft["operations"][0]["name"] == "Assembly"
        assert reopened.state.requirements.text.startswith("1,900")
        assert reopened.state.concept.product_id == "p-controller"
        assert reopened.state.concept.draft == concept_draft
        assert reopened.state.results.selected_strategy_id == "s-2"
        assert reopened.state.layout.applied["baseline"]["placements"][0]["rotation_deg"] == 90.0
        assert reopened.state.equipment.selections["Screwdriving"]["model"] == "MicroTorque"
        assert reopened.state.stage == "VERIFIED"

    def test_two_projects_do_not_bleed_into_one_another(self, store):
        first_state = ProjectState()
        first_state.product.name = "Controller"
        first = store.create("Line A", first_state)

        second_state = ProjectState()
        second_state.product.name = "Sensor module"
        second = store.create("Line B", second_state)

        assert first.project_id != second.project_id
        assert store.load(first.project_id).state.product.name == "Controller"
        assert store.load(second.project_id).state.product.name == "Sensor module"

        moved = store.load(first.project_id).state
        moved.product.name = "Controller MkII"
        store.save(first.project_id, moved)

        assert store.load(second.project_id).state.product.name == "Sensor module"

    def test_a_new_manual_project_has_no_product_name(self, store):
        """Test 3 — the observed defect: a manual project arrived pre-filled
        with an example product's name, which is wrong for a real project and
        is the kind of wrong nobody notices until it is in a report."""
        created = store.create("Untitled project")
        assert created.state.product.name == ""
        assert created.state.product.description == ""
        assert created.state.product.from_example is False

    def test_listing_is_most_recently_updated_first(self, store):
        a = store.create("Line A")
        b = store.create("Line B")
        store.save(a.project_id, store.load(a.project_id).state.model_copy(update={"stage": "PRODUCT"}))

        names = [summary.name for summary in store.list_projects()]
        assert names[0] == "Line A"
        assert set(names) == {"Line A", "Line B"}
        assert {s.project_id for s in store.list_projects()} == {a.project_id, b.project_id}

    def test_an_unreadable_project_does_not_break_the_list(self, store):
        good = store.create("Line A")
        (store.root / "broken.json").write_text("{ not json", encoding="utf-8")

        summaries = store.list_projects()
        assert [s.project_id for s in summaries] == [good.project_id]

    def test_writes_are_atomic(self, store):
        """No temporary file survives a save, so a reader never sees half a
        project."""
        created = store.create("Line A")
        store.save(created.project_id, created.state)
        assert list(store.root.glob("*.tmp")) == []
        assert json.loads((store.root / f"{created.project_id}.json").read_text(encoding="utf-8"))

    def test_deleting_a_missing_project_is_reported(self, store):
        with pytest.raises(ProjectNotFound):
            store.delete("nosuchproject")


# 5 / 6 — upstream edits make downstream evidence stale

class TestUpstreamInvalidation:
    def test_changing_the_product_description_stales_the_facts_and_everything_after(self, store, concept_draft):
        state = ProjectState()
        state.product.name = "Controller"
        state.product.description = "Six screws secure the lid."
        state.product.understanding = {"facts": [{"key": "fasteners", "value": "6 screws", "status": "EXTRACTED"}]}
        state.process.draft = _process_draft(_operation("op-1", "Screwdriving"))
        state.concept.draft = concept_draft
        created = store.create("Controller line", state)

        verified = created.state.model_copy(
            update={
                "produced": [
                    Artifact.PRODUCT_FACTS.value,
                    Artifact.PROCESS_PROPOSAL.value,
                    Artifact.CONCEPT.value,
                    Artifact.SIMULATION_VERIFICATION.value,
                    Artifact.STRATEGIES.value,
                    Artifact.SELECTED_PLAN.value,
                ]
            }
        )
        document = store.save(created.project_id, verified)
        assert store.staleness(document).stale == []

        edited = document.state.model_copy(deep=True)
        edited.product.description = "Eight screws secure the lid, and a label is applied."
        after = store.save(created.project_id, edited)
        report = store.staleness(after)

        stale = {item.artifact for item in report.stale}
        assert Artifact.PRODUCT_FACTS.value in stale
        assert Artifact.PROCESS_PROPOSAL.value in stale
        assert Artifact.CONCEPT.value in stale
        assert Artifact.SIMULATION_VERIFICATION.value in stale
        assert Artifact.SELECTED_PLAN.value in stale

        facts = next(i for i in report.stale if i.artifact == Artifact.PRODUCT_FACTS.value)
        assert any("Product specification changed" in reason for reason in facts.reasons)
        assert facts.action == "Re-read the product specification"

    def test_old_facts_never_stay_silently_authoritative(self, store):
        """B6 — after a description edit, the extracted facts are STALE, and
        STALE is a state the UI is required to render differently."""
        state = ProjectState()
        state.product.description = "Six screws."
        state.product.understanding = {"facts": []}
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.PRODUCT_FACTS))

        edited = document.state.model_copy(deep=True)
        edited.product.description = "Eight screws."
        report = store.staleness(store.save(created.project_id, edited))

        assert report.status_of(Artifact.PRODUCT_FACTS) is ArtifactStatus.STALE
        assert Artifact.PRODUCT_FACTS.value not in report.current

    def test_changing_the_reviewed_process_stales_the_simulation(self, store, concept_draft):
        """Test 6."""
        state = ProjectState()
        state.process.draft = _process_draft(
            _operation("op-1", "Assembly"), _operation("op-2", "Screwdriving")
        )
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(
            created.project_id,
            _verified(created.state, Artifact.CONCEPT, Artifact.SIMULATION_VERIFICATION, Artifact.STRATEGIES),
        )
        assert store.staleness(document).stale == []

        edited = document.state.model_copy(deep=True)
        edited.process.draft["operations"].append(_operation("op-3", "Labelling"))
        report = store.staleness(store.save(created.project_id, edited))

        stale = {item.artifact for item in report.stale}
        assert Artifact.CONCEPT.value in stale
        assert Artifact.SIMULATION_VERIFICATION.value in stale
        assert Artifact.STRATEGIES.value in stale
        concept = next(i for i in report.stale if i.artifact == Artifact.CONCEPT.value)
        assert any("Operation added: Labelling" in reason for reason in concept.reasons)

    def test_reordering_operations_is_reported_as_a_reorder(self, store, concept_draft):
        state = ProjectState()
        state.process.draft = _process_draft(
            _operation("op-1", "Assembly"), _operation("op-2", "Screwdriving")
        )
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.SIMULATION_VERIFICATION, Artifact.CONCEPT))

        edited = document.state.model_copy(deep=True)
        edited.process.draft["operations"].reverse()
        report = store.staleness(store.save(created.project_id, edited))

        concept = next(i for i in report.stale if i.artifact == Artifact.CONCEPT.value)
        assert "Operation order changed." in concept.reasons

    def test_rejecting_and_restoring_an_operation_are_both_reported(self, store):
        state = ProjectState()
        state.process.draft = _process_draft(_operation("op-1", "Labelling"))
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.CONCEPT))

        rejected = document.state.model_copy(deep=True)
        rejected.process.draft["operations"][0]["status"] = "REJECTED"
        document = store.save(created.project_id, rejected)
        assert any(
            "Operation rejected: Labelling." in entry.description for entry in document.state.history
        )

        restored = document.state.model_copy(deep=True)
        restored.process.draft["operations"][0]["status"] = "ACCEPTED"
        document = store.save(created.project_id, restored)
        assert any(
            "Operation restored: Labelling." in entry.description for entry in document.state.history
        )

    def test_relinking_a_requirement_touches_coverage_but_not_the_simulation(self, store, concept_draft):
        """E7 — coverage provenance is metadata about the route, not the route."""
        state = ProjectState()
        state.process.draft = _process_draft(_operation("op-1", "Packaging"))
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(
            created.project_id,
            _verified(created.state, Artifact.REQUIREMENT_COVERAGE, Artifact.SIMULATION_VERIFICATION),
        )

        edited = document.state.model_copy(deep=True)
        edited.process.draft["operations"][0]["source_fact_keys"] = ["identification_label"]
        report = store.staleness(store.save(created.project_id, edited))

        stale = {item.artifact for item in report.stale}
        assert Artifact.REQUIREMENT_COVERAGE.value in stale
        assert Artifact.SIMULATION_VERIFICATION.value not in stale
        assert Artifact.SIMULATION_VERIFICATION.value in report.current


# 7 / 8 / 12 — engineering values and provenance

class TestEngineeringValues:
    def test_the_active_model_uses_the_latest_cycle_time(self, store):
        """Test 7 — 48 → 47 → 44."""
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = concept.stages[1]
        key = f"stage.{stage.id}.cycle_time"

        at48 = write_input(concept, key, 48, ValueSource.ENGINEER, "stopwatch")
        state = ProjectState()
        state.concept.draft = at48.model_dump(mode="json")
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.SIMULATION_VERIFICATION))

        for value in (47, 44):
            edited = document.state.model_copy(deep=True)
            edited.concept.draft = write_input(
                type(concept).model_validate(edited.concept.draft), key, value, ValueSource.ENGINEER, "re-measured"
            ).model_dump(mode="json")
            document = store.save(created.project_id, edited)

        reopened = store.load(created.project_id)
        active = type(concept).model_validate(reopened.state.concept.draft).stage_by_id(stage.id)
        assert active.cycle_time.value == 44
        assert active.cycle_time.source is ValueSource.ENGINEER

        report = store.staleness(reopened)
        simulation = next(
            i for i in report.stale if i.artifact == Artifact.SIMULATION_VERIFICATION.value
        )
        assert any("48" in reason and "44" in reason for reason in simulation.reasons) or any(
            "47" in reason and "44" in reason for reason in simulation.reasons
        )

    def test_an_engineer_override_replaces_estimate_provenance(self, store):
        """
        Test 8 — an estimated 48 s replaced by an engineer's 47 s must stop being an
        estimate.
        """
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = concept.stages[1]
        key = f"stage.{stage.id}.cycle_time"

        estimated = write_input(concept, key, 48, ValueSource.ENGINEERING_ESTIMATE, "reference bands")
        overridden = write_input(estimated, key, 47, ValueSource.ENGINEER, "measured on the pilot line")

        state = ProjectState()
        state.concept.draft = estimated.model_dump(mode="json")
        created = store.create("P", state)

        edited = store.load(created.project_id).state.model_copy(deep=True)
        edited.concept.draft = overridden.model_dump(mode="json")
        document = store.save(created.project_id, edited)

        active = type(concept).model_validate(document.state.concept.draft).stage_by_id(stage.id)
        assert active.cycle_time.value == 47
        assert active.cycle_time.source is ValueSource.ENGINEER
        assert active.cycle_time.source is not ValueSource.ENGINEERING_ESTIMATE

        assert any(
            entry.channel == Channel.SIMULATION_INPUTS.value and "48" in entry.description
            for entry in document.state.history
        )

    def test_a_commercial_change_never_invalidates_throughput(self, store):
        """Test 12 — money re-ranks plans; it moves no units."""
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = concept.stages[0]
        priced = write_input(concept, f"stage.{stage.id}.purchase_cost", 85000, ValueSource.EXTERNAL_DATA, "quote")

        state = ProjectState()
        state.concept.draft = priced.model_dump(mode="json")
        created = store.create("P", state)
        document = store.save(
            created.project_id,
            _verified(
                created.state,
                Artifact.SIMULATION_VERIFICATION,
                Artifact.STRATEGIES,
                Artifact.COMMERCIAL_COMPARISON,
            ),
        )

        edited = document.state.model_copy(deep=True)
        edited.concept.draft = write_input(
            priced, f"stage.{stage.id}.purchase_cost", 91000, ValueSource.EXTERNAL_DATA, "revised quote"
        ).model_dump(mode="json")
        report = store.staleness(store.save(created.project_id, edited))

        stale = {item.artifact for item in report.stale}
        assert Artifact.COMMERCIAL_COMPARISON.value in stale
        assert Artifact.SIMULATION_VERIFICATION.value not in stale
        assert Artifact.STRATEGIES.value not in stale
        assert Artifact.SIMULATION_VERIFICATION.value in report.current


# 10 / 11 — the two precision cases

class TestInvalidationPrecision:
    def test_moving_a_station_leaves_throughput_current(self, store, concept_draft):
        """Test 10, and the single most important assertion in this file."""
        state = ProjectState()
        state.concept.draft = concept_draft
        state.layout.applied = {
            "baseline": {"placements": [{"machine_id": "m1", "x": 2.0, "y": 3.0, "rotation_deg": 0.0}]}
        }
        created = store.create("P", state)
        document = store.save(
            created.project_id,
            _verified(
                created.state,
                Artifact.SIMULATION_VERIFICATION,
                Artifact.STRATEGIES,
                Artifact.SELECTED_PLAN,
                Artifact.LAYOUT_VALIDATION,
                Artifact.SIEMENS_HANDOFF,
            ),
        )
        assert store.staleness(document).stale == []

        moved = document.state.model_copy(deep=True)
        moved.layout.applied["baseline"]["placements"][0]["x"] = 9.5
        report = store.staleness(store.save(created.project_id, moved))

        stale = {item.artifact for item in report.stale}
        assert Artifact.LAYOUT_VALIDATION.value in stale
        assert Artifact.SIEMENS_HANDOFF.value in stale

        assert Artifact.SIMULATION_VERIFICATION.value in report.current
        assert Artifact.STRATEGIES.value in report.current
        assert Artifact.SELECTED_PLAN.value in report.current

        layout = next(i for i in report.stale if i.artifact == Artifact.LAYOUT_VALIDATION.value)
        assert any("throughput is unaffected" in reason for reason in layout.reasons)

    def test_selecting_equipment_changes_no_verified_engineering_value(self, store, concept_draft):
        """Test 11 — a candidate is equipment UNDER CONSIDERATION."""
        state = ProjectState()
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(
            created.project_id,
            _verified(created.state, Artifact.SIMULATION_VERIFICATION, Artifact.SIEMENS_HANDOFF),
        )

        chosen = document.state.model_copy(deep=True)
        chosen.equipment.selections = {
            "Screwdriving": {"candidate_id": "c-9", "manufacturer": "Atlas Copco", "model": "MicroTorque 40"}
        }
        after = store.save(created.project_id, chosen)
        report = store.staleness(after)

        assert after.state.concept.draft == concept_draft
        assert Artifact.SIMULATION_VERIFICATION.value in report.current
        assert Artifact.SIEMENS_HANDOFF.value in {i.artifact for i in report.stale}

    def test_a_layout_edit_and_a_cycle_time_edit_are_different_channels(self, store, concept_draft):
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        before = ProjectState()
        before.concept.draft = concept.model_dump(mode="json")
        before.layout.applied = {"baseline": {"placements": [{"machine_id": "m1", "x": 1.0, "y": 1.0, "rotation_deg": 0.0}]}}

        after = before.model_copy(deep=True)
        after.layout.applied["baseline"]["placements"][0]["y"] = 4.0
        channels = {channel for channel, _ in describe_changes(before, after)}
        assert channels == {Channel.LAYOUT}

        after2 = before.model_copy(deep=True)
        after2.concept.draft = write_input(
            concept, f"stage.{concept.stages[0].id}.cycle_time", 30, ValueSource.ENGINEER, "measured"
        ).model_dump(mode="json")
        channels2 = {channel for channel, _ in describe_changes(before, after2)}
        assert channels2 == {Channel.SIMULATION_INPUTS}


# 13 — reopening preserves provenance and staleness

class TestReopen:
    def test_reload_preserves_provenance_stale_state_and_selections(self, store):
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = concept.stages[1]
        overridden = write_input(
            concept, f"stage.{stage.id}.cycle_time", 44, ValueSource.ENGINEER, "measured on the pilot line"
        )

        state = ProjectState()
        state.concept.draft = concept.model_dump(mode="json")
        state.equipment.selections = {"Screwdriving": {"candidate_id": "c-1", "model": "MicroTorque"}}
        created = store.create("P", state)
        store.save(created.project_id, _verified(created.state, Artifact.SIMULATION_VERIFICATION))

        edited = store.load(created.project_id).state.model_copy(deep=True)
        edited.concept.draft = overridden.model_dump(mode="json")
        store.save(created.project_id, edited)

        reopened = store.load(created.project_id)
        report = store.staleness(reopened)

        active = type(concept).model_validate(reopened.state.concept.draft).stage_by_id(stage.id)
        assert (active.cycle_time.value, active.cycle_time.source) == (44, ValueSource.ENGINEER)
        assert active.cycle_time.detail == "measured on the pilot line"
        assert reopened.state.equipment.selections["Screwdriving"]["model"] == "MicroTorque"
        assert report.status_of(Artifact.SIMULATION_VERIFICATION) is ArtifactStatus.STALE
        assert reopened.state.history, "the change trail survives a reload"

    def test_evidence_produced_in_the_same_save_as_its_inputs_is_current(self, store, concept_draft):
        """Re-running verification AFTER an edit clears the badge — otherwise
        nothing could ever be made current again."""
        state = ProjectState()
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.SIMULATION_VERIFICATION))

        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        edited = document.state.model_copy(deep=True)
        edited.concept.draft = write_input(
            concept, f"stage.{concept.stages[0].id}.cycle_time", 31, ValueSource.ENGINEER, "measured"
        ).model_dump(mode="json")
        document = store.save(created.project_id, edited)
        assert store.staleness(document).stale

        rerun = document.state.model_copy(deep=True, update={"produced": [Artifact.SIMULATION_VERIFICATION.value]})
        document = store.save(created.project_id, rerun)
        assert store.staleness(document).stale == []
        assert Artifact.SIMULATION_VERIFICATION.value in store.staleness(document).current

    def test_a_reason_never_predates_the_stamp_it_explains(self, store):
        """
        An artifact explained with a change it was itself verified against reads as
        though a settled decision had come undone.
        """
        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        stage = concept.stages[1]
        key = f"stage.{stage.id}.cycle_time"

        state = ProjectState()
        state.concept.draft = concept.model_dump(mode="json")
        created = store.create("P", state)

        # Edit one — before anything is verified.
        first = store.load(created.project_id).state.model_copy(deep=True)
        first.concept.draft = write_input(
            concept, key, 52, ValueSource.ENGINEER, "first pass"
        ).model_dump(mode="json")
        document = store.save(created.project_id, first)

        document = store.save(
            created.project_id, _verified(document.state, Artifact.SIMULATION_VERIFICATION)
        )
        assert store.staleness(document).stale == []

        # Edit two — after.
        second = document.state.model_copy(deep=True)
        second.concept.draft = write_input(
            type(concept).model_validate(second.concept.draft),
            key,
            44,
            ValueSource.ENGINEER,
            "re-measured",
        ).model_dump(mode="json")
        report = store.staleness(store.save(created.project_id, second))

        simulation = next(
            i for i in report.stale if i.artifact == Artifact.SIMULATION_VERIFICATION.value
        )
        assert any("52" in reason and "44" in reason for reason in simulation.reasons)
        # The pre-verification edit is not offered as a reason this expired.
        assert not any("first pass" in reason for reason in simulation.reasons)
        assert not any(reason.endswith("35 \u2192 52") for reason in simulation.reasons)

    def test_a_client_cannot_mint_its_own_evidence_stamp(self, store, concept_draft):
        """The stale badge must not be something the frontend can talk its
        way out of: revisions and stamps are recomputed server-side."""
        state = ProjectState()
        state.concept.draft = concept_draft
        created = store.create("P", state)
        document = store.save(created.project_id, _verified(created.state, Artifact.SIMULATION_VERIFICATION))

        concept = apply_example_engineering_data(concept_from_brief(BRIEF))
        forged = document.state.model_copy(deep=True)
        forged.concept.draft = write_input(
            concept, f"stage.{concept.stages[0].id}.cycle_time", 31, ValueSource.ENGINEER, "measured"
        ).model_dump(mode="json")
        # A client claiming everything is current at an absurd revision.
        forged.revisions = {channel.value: 999 for channel in Channel}
        forged.evidence = {
            Artifact.SIMULATION_VERIFICATION.value: Stamp(revisions={c.value: 999 for c in Channel})
        }

        report = store.staleness(store.save(created.project_id, forged))
        assert Artifact.SIMULATION_VERIFICATION.value in {i.artifact for i in report.stale}


# The HTTP surface

class TestProjectApi:
    def test_create_list_save_reopen_delete(self, client):
        created = client.post("/projects", json={"name": "Controller line"})
        assert created.status_code == 200
        project_id = created.json()["project"]["project_id"]
        assert created.json()["project"]["state"]["product"]["name"] == ""

        listing = client.get("/projects").json()["projects"]
        assert [p["project_id"] for p in listing] == [project_id]

        state = created.json()["project"]["state"]
        state["product"]["name"] = "Compact electronics controller"
        state["product"]["description"] = "Six screws."
        state["produced"] = [Artifact.PRODUCT_FACTS.value]
        saved = client.put(f"/projects/{project_id}", json={"state": state})
        assert saved.status_code == 200
        assert saved.json()["staleness"]["current"] == [Artifact.PRODUCT_FACTS.value]

        edited = saved.json()["project"]["state"]
        edited["product"]["description"] = "Eight screws."
        after = client.put(f"/projects/{project_id}", json={"state": edited}).json()
        assert after["staleness"]["stale"][0]["artifact"] == Artifact.PRODUCT_FACTS.value
        assert after["staleness"]["stale"][0]["action"] == "Re-read the product specification"

        reopened = client.get(f"/projects/{project_id}").json()
        assert reopened["project"]["state"]["product"]["description"] == "Eight screws."
        assert reopened["staleness"]["stale"][0]["artifact"] == Artifact.PRODUCT_FACTS.value

        assert client.delete(f"/projects/{project_id}").status_code == 200
        assert client.get(f"/projects/{project_id}").status_code == 404

    def test_a_nameless_project_is_refused(self, client):
        assert client.post("/projects", json={"name": "   "}).status_code == 422

    def test_staleness_can_be_evaluated_without_saving(self, client):
        state = ProjectState()
        state.product.description = "Six screws."
        stamped = apply_revisions(None, state.model_copy(update={"produced": [Artifact.PRODUCT_FACTS.value]}))
        stamped.product.description = "Eight screws."
        # Not saved anywhere; the endpoint reads the same function the save
        # path reads, so the two cannot disagree.
        response = client.post("/projects/staleness", json=json.loads(stamped.model_dump_json()))
        assert response.status_code == 200
        assert response.json()["current"] == [Artifact.PRODUCT_FACTS.value]

    def test_stale_report_agrees_with_the_service(self, client):
        state = ProjectState()
        stamped = apply_revisions(None, state.model_copy(update={"produced": [Artifact.CONCEPT.value]}))
        assert stale_report(stamped).current == [Artifact.CONCEPT.value]
