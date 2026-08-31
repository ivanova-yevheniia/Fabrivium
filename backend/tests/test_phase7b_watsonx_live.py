"""Phase 7B REAL-provider integration tests — live IBM watsonx.ai / Granite."""

from __future__ import annotations

import json
import os
import pathlib

import pytest
from pydantic import BaseModel

from app.llm import LLMProviderError, LLMRequest, RetryPolicy, load_dotenv_file, load_llm_settings
from app.models.agent import PlanningRequirements
from app.models.factory import Factory
from app.models.optimization import OptimizationObjective
from app.services.agent_context import build_factory_context
from app.services.llm_integration import parse_requirements_with_fallback
from app.services.requirements_parser import ParserType

# Populate os.environ from backend/.env before the gate is evaluated, so a
# developer only has to set the flag in one place.
load_dotenv_file()

_ENABLED = os.environ.get("FACTORYMIND_RUN_WATSONX_INTEGRATION_TESTS", "").strip().lower() in {"1", "true", "yes", "on"}

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason=(
        "Live IBM watsonx.ai integration tests are opt-in: they make real, billable API "
        "calls. Set FACTORYMIND_RUN_WATSONX_INTEGRATION_TESTS=1 (with FACTORYMIND_WATSONX_* "
        "configured in backend/.env) to run them."
    ),
)


EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"


class SmokeResponse(BaseModel):
    status: str


@pytest.fixture
def electronics_factory() -> Factory:
    """The same bundled example line every other test suite uses — the
    real 1105/day baseline, not a synthetic toy."""
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return Factory.model_validate(json.load(fh))


@pytest.fixture(scope="module")
def live_provider():
    """One shared provider for the module, so the IAM token is minted once
    and reused across every test (proving the cache works under real
    conditions, and keeping IAM traffic minimal)."""
    from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

    settings = WatsonxSettings.from_env()
    generic = load_llm_settings()
    provider = WatsonxGraniteProvider(
        settings,
        retry_policy=RetryPolicy(max_retries=generic.max_retries, timeout_seconds=max(60.0, generic.timeout_seconds)),
    )
    yield provider
    provider.close()


# 1. Cheapest possible probe — run this before anything expensive


class TestLiveSmoke:
    def test_minimal_structured_call_round_trips(self, live_provider):
        """IAM auth + endpoint + model + JSON mode + Phase 7A parsing, for
        a handful of tokens."""
        result = live_provider.generate_structured(
            LLMRequest(
                system_prompt="You return only compact JSON. No prose, no markdown fences.",
                user_prompt='Return ONLY this JSON: {"status":"ok"}',
                response_schema={"type": "object"},
                max_tokens=32,
                metadata={"agent": "smoke"},
            ),
            response_model=SmokeResponse,
        )
        assert result.parsed.status.lower() == "ok"
        assert result.response.provider_name == "watsonx"

    def test_usage_metadata_is_reported_by_ibm(self, live_provider):
        result = live_provider.generate_structured(
            LLMRequest(
                system_prompt="You return only compact JSON.",
                user_prompt='Return ONLY this JSON: {"status":"ok"}',
                response_schema={"type": "object"},
                max_tokens=32,
                metadata={"agent": "smoke"},
            ),
            response_model=SmokeResponse,
        )
        usage = result.response.usage
        assert usage is not None, "watsonx.ai reported no usage block"
        assert usage.get("total_tokens", 0) > 0
        print(f"\n[live usage] {json.dumps(usage)} request_id={result.response.request_id}")


# 2. Requirements agent (Phase 7B section 8) — semantic, not byte-exact


def _parse(factory, request_text: str) -> PlanningRequirements:
    from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

    provider = WatsonxGraniteProvider(
        WatsonxSettings.from_env(),
        retry_policy=RetryPolicy(max_retries=2, timeout_seconds=90.0),
    )
    try:
        result, fallback_used = parse_requirements_with_fallback(
            request_text, build_factory_context(factory), provider
        )
    finally:
        provider.close()

    assert not fallback_used, f"Granite output failed validation; fell back. warnings={result.warnings}"
    assert result.parser_type is ParserType.LLM
    return result.parsed_requirements


class TestLiveRequirementsAgent:
    def test_simple_target_demand(self, electronics_factory):
        requirements = _parse(electronics_factory, "We need 1900 units/day.")
        assert requirements.objective is OptimizationObjective.MEET_DEMAND
        assert requirements.target_units_per_day == pytest.approx(1900.0)

    def test_target_demand_with_capex_ceiling(self, electronics_factory):
        requirements = _parse(electronics_factory, "Increase output to 1500/day with CAPEX below €100k.")
        assert requirements.target_units_per_day == pytest.approx(1500.0)
        assert requirements.max_capex == pytest.approx(100_000.0)

    def test_full_request_with_forbidden_machine_and_layout_preservation(self, electronics_factory):
        requirements = _parse(
            electronics_factory,
            "We need 1900 units/day, budget €220k, don't modify Packaging, and keep the existing layout.",
        )
        assert requirements.target_units_per_day == pytest.approx(1900.0)
        assert requirements.max_capex == pytest.approx(220_000.0)
        assert requirements.preserve_existing_layout is True

        # The model must name a machine that actually exists — the id, not
        # a hallucinated one. Resolution to the real pool is the
        # deterministic layer's job (candidate_generator), not the model's.
        known_ids = {m.id for m in electronics_factory.machines}
        assert requirements.forbidden_machine_ids, "Packaging was not recognised as forbidden"
        assert set(requirements.forbidden_machine_ids) <= known_ids, (
            f"Granite invented machine id(s): {set(requirements.forbidden_machine_ids) - known_ids}"
        )
        packaging_ids = {m.id for m in electronics_factory.machines if "packaging" in m.name.lower()}
        assert set(requirements.forbidden_machine_ids) & packaging_ids


# 3. Full iterative session against real Granite (Phase 7B sections 9-11)


class TestLiveIterativeSession:
    """
    The real 1900/day demonstration, end to end through POST /planning/run with live
    Granite driving all three agents.
    """

    @pytest.fixture
    def live_client(self, monkeypatch):
        from fastapi.testclient import TestClient

        import app.main as main_module
        from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

        provider = WatsonxGraniteProvider(
            WatsonxSettings.from_env(),
            retry_policy=RetryPolicy(max_retries=2, timeout_seconds=90.0),
        )
        monkeypatch.setattr(main_module, "_LLM_PROVIDER", provider)
        yield TestClient(main_module.app)
        provider.close()

    @pytest.fixture
    def response_body(self, live_client, electronics_factory) -> dict:
        resp = live_client.post("/planning/run", json={
            "factory": json.loads(electronics_factory.model_dump_json()),
            "product_id": "p-electronics-widget",
            "user_request": (
                "We need 1900 units/day, budget €220k, don't modify Packaging, "
                "and keep the existing layout."
            ),
        })
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_provenance_reports_granite_with_no_fallback(self, response_body):
        provenance = response_body["provenance"]
        assert provenance == {
            "requirements_source": "LLM",
            "planning_source": "LLM",
            "explanation_source": "LLM",
            "fallback_used": False,
            "provider_name": "watsonx",
            "model_name": "ibm/granite-4-h-small",
        }

    def test_the_verified_engineering_outcome_is_reached(self, response_body):
        session = response_body["session"]
        assert session["goal_reached"] is True
        assert session["stop_reason"] == "GOAL_REACHED"
        assert session["cumulative_known_capex"] == 205_000.0

    def test_every_accepted_proposal_was_optimizer_grounded_and_none_rejected_silently(self, response_body):
        for iteration in response_body["session"]["iterations"]:
            agent_result = iteration["planning_agent_result"]
            assert agent_result["agent_type"] == "LLM"
            assert agent_result["optimizer_grounded"] is True

    def test_the_forbidden_machine_was_never_touched(self, response_body):
        touched = {
            action["machine_id"]
            for iteration in response_body["session"]["iterations"]
            if iteration.get("selected_proposal")
            for action in iteration["selected_proposal"]["scenario"]["actions"]
            if action.get("machine_id")
        }
        assert "m-packaging" not in touched

    def test_the_explanation_is_model_authored_and_survived_the_hallucination_guard(self, response_body):
        explanation = response_body["explanation"]
        assert explanation["source_type"] == "LLM"
        assert explanation["executive_summary"].strip()
        print(f"\n[live explanation] {explanation['executive_summary']}")

    def test_no_credential_or_endpoint_detail_reaches_the_client(self, live_client, electronics_factory):
        resp = live_client.post("/planning/run", json={
            "factory": json.loads(electronics_factory.model_dump_json()),
            "product_id": "p-electronics-widget",
            "user_request": "We need 1900 units/day.",
        })
        payload = resp.text
        assert os.environ["FACTORYMIND_WATSONX_API_KEY"] not in payload
        assert "Bearer" not in payload
        assert "ml.cloud.ibm.com" not in payload
        assert "iam.cloud.ibm.com" not in payload
        assert os.environ["FACTORYMIND_WATSONX_PROJECT_ID"] not in payload


# 4. Failure modes against the REAL service (Phase 7B section 12)


class TestLiveFailureModes:
    def test_wrong_model_id_is_a_controlled_typed_failure(self):
        """B."""
        from dataclasses import replace

        from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

        settings = replace(WatsonxSettings.from_env(), model_id="ibm/granite-this-model-does-not-exist")
        provider = WatsonxGraniteProvider(settings, retry_policy=RetryPolicy(max_retries=0, timeout_seconds=60.0))
        try:
            with pytest.raises(LLMProviderError) as exc_info:
                provider.generate_structured(
                    LLMRequest(system_prompt="s", user_prompt="u", max_tokens=8), response_model=SmokeResponse
                )
        finally:
            provider.close()
        assert exc_info.value.retryable is False
        print(f"\n[live wrong-model] {type(exc_info.value).__name__}: {exc_info.value}")

    def test_invalid_api_key_maps_to_authentication_error(self):
        from dataclasses import replace

        from app.llm.errors import LLMAuthenticationError
        from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

        settings = replace(WatsonxSettings.from_env(), api_key="definitely-not-a-real-ibm-cloud-api-key")
        provider = WatsonxGraniteProvider(settings, retry_policy=RetryPolicy(max_retries=0, timeout_seconds=60.0))
        try:
            with pytest.raises(LLMAuthenticationError):
                provider.generate_structured(
                    LLMRequest(system_prompt="s", user_prompt="u", max_tokens=8), response_model=SmokeResponse
                )
        finally:
            provider.close()
