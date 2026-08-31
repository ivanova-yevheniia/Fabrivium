"""Phase 8C — POST /simulation/playback endpoint tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


def _electronics_factory_dict() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


def _electronics_layout_dict() -> dict:
    with open(EXAMPLES_DIR / "electronics_line_layout.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestPlaybackEndpoint:
    def test_returns_trace_with_summary(self, client: TestClient):
        factory = _electronics_factory_dict()
        response = client.post(
            "/simulation/playback",
            json={"factory": factory, "product_id": factory["products"][0]["id"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["trace_version"] == 1
        assert "summary" in body
        assert body["summary"]["completed_units"] == body["system_series"][-1]["completed_units"]

    def test_layout_accepted_and_optional(self, client: TestClient):
        factory = _electronics_factory_dict()
        layout = _electronics_layout_dict()
        response = client.post(
            "/simulation/playback",
            json={"factory": factory, "product_id": factory["products"][0]["id"], "layout": layout},
        )
        assert response.status_code == 200

    def test_matches_plain_simulation_run(self, client: TestClient):
        factory = _electronics_factory_dict()
        product_id = factory["products"][0]["id"]

        plain = client.post("/simulation/run", json={"factory": factory, "product_id": product_id})
        traced = client.post("/simulation/playback", json={"factory": factory, "product_id": product_id})

        assert plain.status_code == 200
        assert traced.status_code == 200
        assert traced.json()["summary"] == plain.json()

    def test_unknown_product_id_returns_400(self, client: TestClient):
        factory = _electronics_factory_dict()
        response = client.post(
            "/simulation/playback",
            json={"factory": factory, "product_id": "does-not-exist"},
        )
        assert response.status_code == 400

    def test_structurally_invalid_factory_returns_422(self, client: TestClient):
        response = client.post(
            "/simulation/playback",
            json={"factory": {"not": "a factory"}, "product_id": "p-1"},
        )
        assert response.status_code == 422

    def test_structurally_invalid_layout_returns_422(self, client: TestClient):
        factory = _electronics_factory_dict()
        response = client.post(
            "/simulation/playback",
            json={
                "factory": factory,
                "product_id": factory["products"][0]["id"],
                "layout": {"not": "a layout"},
            },
        )
        assert response.status_code == 422

    def test_custom_trace_config_respected(self, client: TestClient):
        factory = _electronics_factory_dict()
        response = client.post(
            "/simulation/playback",
            json={
                "factory": factory,
                "product_id": factory["products"][0]["id"],
                "trace_config": {"max_tracked_units": 5, "sample_count_target": 30},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["config"]["max_tracked_units"] == 5
        assert body["tracked_unit_count"] <= 5

    def test_never_mutates_planning_history(self, client: TestClient):
        """Calling playback twice for the same input is side-effect-free —
        no session/state is created anywhere the client could observe."""
        factory = _electronics_factory_dict()
        product_id = factory["products"][0]["id"]
        first = client.post("/simulation/playback", json={"factory": factory, "product_id": product_id})
        second = client.post("/simulation/playback", json={"factory": factory, "product_id": product_id})
        assert first.json() == second.json()
