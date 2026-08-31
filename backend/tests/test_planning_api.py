"""FastAPI endpoint tests for FactoryMind Phase 6A/6B backend wiring."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def example_factory_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)



class TestExampleFactoryEndpoint:
    def test_returns_valid_factory(self, client: TestClient, example_factory_json: dict):
        resp = client.get("/factory/example")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == example_factory_json["name"]
        assert {m["id"] for m in body["machines"]} == {m["id"] for m in example_factory_json["machines"]}

    def test_matches_bundled_example_file_exactly(self, client: TestClient, example_factory_json: dict):
        from app.models.factory import Factory

        resp = client.get("/factory/example")
        served = Factory.model_validate(resp.json())
        expected = Factory.model_validate(example_factory_json)
        assert served.model_dump() == expected.model_dump()



class TestExampleLayoutEndpoint:
    def test_returns_a_valid_layout(self, client: TestClient, example_factory_json: dict):
        from app.models.factory import Factory
        from app.services.constraints import validate_layout
        from app.models.layout import FactoryLayout

        resp = client.get("/factory/example/layout")
        assert resp.status_code == 200
        factory = Factory.model_validate(example_factory_json)
        layout = FactoryLayout.model_validate(resp.json())
        result = validate_layout(factory, layout, "p-electronics-widget")
        assert result.valid is True
        assert result.error_count == 0

    def test_has_an_aisle_and_a_reserved_zone(self, client: TestClient):
        body = client.get("/factory/example/layout").json()
        assert len(body["aisle_zones"]) >= 1
        assert len(body["reserved_zones"]) >= 1

    def test_every_factory_machine_is_placed(self, client: TestClient):
        body = client.get("/factory/example/layout").json()
        placed_ids = {p["machine_id"] for p in body["placements"]}
        assert placed_ids == {"m-assembly", "m-screwdriving", "m-inspection", "m-packaging"}


# POST /planning/run

class TestPlanningRunEndpoint:
    def test_demonstration_a_one_step_goal_reached(self, client: TestClient, example_factory_json: dict):
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1200 units per day.",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["session"]["stop_reason"] == "GOAL_REACHED"
        assert body["session"]["goal_reached"] is True
        assert len(body["session"]["iterations"]) == 1
        assert body["parse_result"]["parsed_requirements"]["target_units_per_day"] == 1200.0

    def test_demonstration_b_multi_step_goal_reached(self, client: TestClient, example_factory_json: dict):
        """
        Phase 8A: three steps, not two — relieve Screwdriving, hire the staff the next
        machine needs, then buy it.
        """
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1900 units per day.",
        })
        body = resp.json()
        assert body["session"]["goal_reached"] is True
        assert len(body["session"]["iterations"]) == 3
        assert "Assembly" in body["explanation"]["executive_summary"]

    def test_budget_stop_reflected_in_response(self, client: TestClient, example_factory_json: dict):
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1200 units per day with CAPEX below €80,000.",
        })
        body = resp.json()
        assert body["session"]["stop_reason"] == "BUDGET_EXHAUSTED"
        assert body["session"]["goal_reached"] is False
        assert body["explanation"]["stop_explanation"]

    def test_forbidden_machine_reflected_in_response(self, client: TestClient, example_factory_json: dict):
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1200 units per day. Do not modify Screwdriving.",
        })
        body = resp.json()
        assert body["parse_result"]["parsed_requirements"]["forbidden_machine_ids"] == ["m-screwdriving"]

        # PHASE 8A CHANGE.
        assert body["session"]["goal_reached"] is True
        session = body["session"]
        for iteration in session["iterations"]:
            proposal = iteration.get("selected_proposal")
            if proposal is None:
                continue
            for action in proposal["scenario"]["actions"]:
                assert action.get("machine_id") != "m-screwdriving"
        assert not any(
            m.get("parallel_of_machine_id") == "m-screwdriving"
            for m in session["current_factory"]["machines"]
        )

    def test_unknown_product_id_returns_400(self, client: TestClient, example_factory_json: dict):
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-does-not-exist",
            "user_request": "We need 1200 units per day.",
        })
        assert resp.status_code == 400

    def test_malformed_factory_returns_422(self, client: TestClient):
        resp = client.post("/planning/run", json={
            "factory": {"not": "a valid factory"},
            "product_id": "p-electronics-widget",
            "user_request": "We need 1200 units per day.",
        })
        assert resp.status_code == 422

    def test_max_capex_override_applies_when_parser_finds_none(self, client: TestClient, example_factory_json: dict):
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1200 units per day.",
            "max_capex": 80_000.0,
        })
        body = resp.json()
        # parse_result reflects what was ACTUALLY parsed from the text
        # (nothing — no budget phrase was present); the override only
        # affects the requirements actually run through the orchestrator.
        assert body["parse_result"]["parsed_requirements"]["max_capex"] is None
        assert body["session"]["stop_reason"] == "BUDGET_EXHAUSTED"

    def test_original_factory_unaffected_by_response(self, client: TestClient, example_factory_json: dict):
        before = json.dumps(example_factory_json, sort_keys=True)
        client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": "We need 1900 units per day.",
        })
        assert json.dumps(example_factory_json, sort_keys=True) == before


# CORS (required for the Vite dev server)

class TestCORS:
    def test_cors_headers_present_for_browser_origin(self, client: TestClient):
        resp = client.get("/health", headers={"origin": "http://localhost:5173"})
        assert resp.headers.get("access-control-allow-origin") == "*"
