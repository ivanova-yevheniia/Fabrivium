"""Phase 15C — the handoff endpoint."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.integrations.plant_simulation.adapter import PlantSimulationAdapter, PlantSimulationUnavailable
from app.main import app
from tests.test_plant_simulation_adapter import FakePlantSim

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def factory_payload() -> dict:
    return json.loads((EXAMPLES / "electronics_line.json").read_text(encoding="utf-8"))


def layout_payload() -> dict:
    return json.loads((EXAMPLES / "electronics_line_layout.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_export_dir(tmp_path, monkeypatch):
    """Keep stub .spp files out of the directory that holds real deliverables."""
    monkeypatch.setenv("FACTORYMIND_EXPORT_DIR", str(tmp_path / "exports"))
    return tmp_path


@pytest.fixture
def use_fake(monkeypatch):
    """Point the endpoint at a fake Plant Simulation."""

    def install(**fake_kwargs):
        fake = FakePlantSim(**fake_kwargs)

        class PatchedAdapter(PlantSimulationAdapter):
            def __init__(self, dispatch=None):
                super().__init__(dispatch=lambda _prog_id: fake)

        monkeypatch.setattr(
            "app.integrations.plant_simulation.PlantSimulationAdapter", PatchedAdapter
        )
        return fake

    return install


def post(client: TestClient, **overrides):
    body = {"factory": factory_payload(), "product_id": None, "layout": layout_payload()}
    body["product_id"] = body["factory"]["products"][0]["id"]
    body.update(overrides)
    return client.post("/handoff/plant-simulation", json=body)


# The success path

class TestCompleteHandoff:
    def test_a_verified_handoff_reports_complete(self, client, use_fake):
        use_fake()
        body = post(client).json()

        assert body["status"] == "COMPLETE"
        assert body["stations_verified"] == body["stations_created"] > 0
        assert body["connections_verified"] == body["connections_created"] > 0
        assert body["errors"] == []

    def test_counts_are_read_back_counts_not_attempt_counts(self, client, use_fake):
        # Guards the one claim the competition rests on: the numbers shown in
        # the UI come from reading the model, so they cannot be inflated by a
        use_fake()
        body = post(client).json()
        assert body["cycle_times_verified"] == body["stations_created"]

    def test_the_model_is_saved_and_the_path_is_returned(self, client, use_fake):
        use_fake()
        body = post(client).json()
        assert body["model_path"] and body["model_path"].endswith(".spp")

    def test_renamed_stations_are_reported_rather_than_hidden(self, client, use_fake):
        # Plant Simulation names are identifiers, so "Assembly Station"
        # becomes Assembly_Station. An engineer opening the model must be
        # able to reconcile it with the concept they signed off.
        use_fake()
        body = post(client).json()
        assert any("Assembly_Station" in w for w in body["warnings"])

    def test_a_run_is_not_performed_unless_asked(self, client, use_fake):
        use_fake()
        assert post(client).json()["simulated_units"] is None


# The input really is the caller's session

class TestInputComesFromTheRequest:
    def test_cycle_times_transferred_are_the_ones_in_the_request(self, client, use_fake):
        fake = use_fake()
        payload = factory_payload()
        # A value that exists in no fixture, so it can only have arrived via the request
        # body.
        payload["products"][0]["route"][0]["cycle_time"] = 41.5
        target_id = payload["products"][0]["route"][0]["machine_id"]
        for machine in payload["machines"]:
            if machine["id"] == target_id:
                machine["cycle_time"] = 41.5

        post(client, factory=payload)

        written = {obj.get("ProcTime") for obj in fake.objects.values()}
        assert 41.5 in written

    def test_station_names_transferred_are_the_ones_in_the_request(self, client, use_fake):
        fake = use_fake()
        payload = factory_payload()
        payload["machines"][0]["name"] = "Bespoke Cell"

        post(client, factory=payload)

        assert any("Bespoke_Cell" in name for name in fake.objects)

    def test_an_unknown_product_is_a_client_error(self, client):
        response = post(client, product_id="p-does-not-exist")
        assert response.status_code == 400
        assert "p-does-not-exist" in response.json()["detail"]

    def test_a_malformed_factory_is_rejected_before_any_com_call(self, client):
        # No adapter is patched in, so reaching COM would either fail loudly
        # or touch the real product. A 422 proves validation came first.
        response = post(client, factory={"name": "broken"})
        assert response.status_code == 422


# Failure is never dressed up as success

class TestFailureIsExplicit:
    def test_plant_simulation_missing_is_reported_as_unavailable(self, client, monkeypatch):
        class Refusing(PlantSimulationAdapter):
            def connect(self, visible: bool = False) -> None:
                raise PlantSimulationUnavailable("Plant Simulation is not installed on this machine.")

        monkeypatch.setattr("app.integrations.plant_simulation.PlantSimulationAdapter", Refusing)
        body = post(client).json()

        assert body["status"] == "UNAVAILABLE"
        assert body["stations_verified"] == 0
        assert "not installed" in body["errors"][0]

    @pytest.mark.parametrize("failure", ["create", "connect", "verify_cycle", "verify_link"])
    def test_no_failure_mode_can_produce_complete(self, client, use_fake, failure):
        use_fake(fail_on=failure)
        body = post(client).json()

        assert body["status"] == "INCOMPLETE"
        assert body["status"] != "COMPLETE"

    def test_an_unverified_cycle_time_blocks_completion(self, client, use_fake):
        # The decisive case: every write "succeeded", but the model does not
        # contain what was sent.
        use_fake(fail_on="verify_cycle")
        body = post(client).json()

        assert body["status"] == "INCOMPLETE"
        assert body["cycle_times_verified"] == 0
        assert body["stations_created"] > 0

    def test_a_partial_model_reports_which_half_failed(self, client, use_fake):
        use_fake(fail_on="verify_link")
        body = post(client).json()

        assert body["status"] == "INCOMPLETE"
        assert body["stations_verified"] > 0  # stations did transfer
        assert body["connections_verified"] == 0  # flow did not
        assert body["connections_created"] > 0

    def test_an_unknown_localisation_stops_rather_than_guesses(self, client, use_fake):
        use_fake(locale="klingon")
        body = post(client).json()

        assert body["status"] == "INCOMPLETE"
        assert body["errors"]


class TestTheFileIsTheDeliverable:
    """Audit §12/§13 — the endpoint reports on the FILE, not the session."""

    def test_a_good_handoff_reports_the_round_trip(self, client, use_fake):
        use_fake()
        body = post(client).json()

        assert body["status"] == "COMPLETE"
        assert body["saved_model_verified"] is True
        assert body["saved_stations_verified"] == body["stations_verified"]
        assert body["saved_connections_verified"] == body["connections_verified"]
        assert body["model_bytes"] > 100_000
        assert body["export_directory"]

    def test_a_save_that_loses_a_station_is_reported_incomplete(self, client, use_fake):
        use_fake(fail_on="save_drops_a_station")
        body = post(client).json()

        # The session was fine — that is exactly what makes this dangerous.
        assert body["stations_verified"] == body["stations_created"]
        assert body["saved_model_verified"] is False
        assert body["status"] == "INCOMPLETE"
        assert any("does not match" in e for e in body["errors"])

    def test_a_save_that_writes_nothing_is_reported_incomplete(self, client, use_fake):
        use_fake(fail_on="save_produces_nothing")
        body = post(client).json()

        assert body["status"] == "INCOMPLETE"
        assert body["model_path"] is None
        # Never a pass. An unattempted round trip is not a passed one.
        assert body["saved_model_verified"] is None
        assert any("no file exists" in e for e in body["errors"])

    def test_the_export_never_lands_in_a_temporary_directory(self, monkeypatch):
        # §10 — the .spp is the deliverable an engineer takes away, and the operating
        # system may delete anything in Temp without warning.
        import tempfile

        from app.main import _export_destination

        monkeypatch.delenv("FACTORYMIND_EXPORT_DIR", raising=False)
        destination = _export_destination("Electronics Assembly Line")

        # Compared against the PROJECT ROOT, not against the machine's temp path.
        import app.main

        project_root = pathlib.Path(app.main.__file__).resolve().parents[2]
        assert pathlib.Path(destination).is_relative_to(project_root)
        assert pathlib.Path(destination).parent.name == "siemens"

        # And it is genuinely NOT the OS temp area — checked by asking where
        # the OS would have put it, rather than by substring-matching a path
        # that may legitimately contain the temp directory.
        assert pathlib.Path(destination).parent != pathlib.Path(tempfile.gettempdir())
        assert destination.lower().endswith("exports\siemens\electronics_assembly_line.spp") or (
            "exports" in destination.lower() and "siemens" in destination.lower()
        )

    def test_the_export_directory_can_be_redirected(self, monkeypatch, tmp_path):
        # The override exists so tests never write stub .spp files into the
        # directory that holds real deliverables.
        from app.main import _export_destination

        monkeypatch.setenv("FACTORYMIND_EXPORT_DIR", str(tmp_path / "elsewhere"))
        destination = _export_destination("Electronics Assembly Line")
        assert str(tmp_path) in destination
