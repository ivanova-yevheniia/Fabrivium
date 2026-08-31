"""Phase 9B — the EXACT production incident, pinned as a regression test."""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.main as main_module
from app.llm.errors import LLMAuthenticationError
from app.llm.iam import IBMCloudIAMTokenProvider
from app.llm.models import LLMRequest, RetryPolicy
from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"

API_KEY = "fake-local-api-key-value-0123456789"
BEARER = "fake-iam-bearer-token-abcdefghijklmnop"
MODEL_ID = "ibm/granite-4-h-small"
PROJECT_ID = "38acdfa3-0000-0000-0000-000000000000"
URL = "https://eu-de.ml.cloud.example.invalid"

#: IBM's verbatim response body for an exhausted watsonx token allowance,
#: copied from the live eu-de account during the Phase 9B audit.
QUOTA_BODY = {
    "errors": [
        {
            "code": "token_quota_reached",
            "message": "Request of 1 token(s) from quota was rejected",
            "more_info": "https://cloud.ibm.com/apidocs/watsonx-ai#text-chat",
        }
    ],
    "trace": "ebeec5ab40585bab417b08fd0b3282f0",
    "status_code": 403,
}


class Widget(BaseModel):
    name: str


class QuotaExhaustedWatsonx:
    """A watsonx.ai that has no tokens left."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(403, json=QUOTA_BODY)


def build_quota_blocked_provider(handler, *, max_retries: int = 0) -> WatsonxGraniteProvider:
    """
    A FULLY and CORRECTLY configured watsonx provider whose only problem is the
    account's quota — the live demo's exact state.
    """
    def iam_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": BEARER, "expires_in": 3600})

    return WatsonxGraniteProvider(
        WatsonxSettings(url=URL, project_id=PROJECT_ID, api_key=API_KEY, model_id=MODEL_ID),
        retry_policy=RetryPolicy(max_retries=max_retries, timeout_seconds=60.0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        token_provider=IBMCloudIAMTokenProvider(
            API_KEY, client=httpx.Client(transport=httpx.MockTransport(iam_handler))
        ),
    )


def a_request() -> LLMRequest:
    return LLMRequest(
        system_prompt="SYSTEM RULES",
        user_prompt="USER PAYLOAD",
        response_schema={"type": "object"},
        metadata={"agent": "requirements"},
    )


# A. Provider layer — typed mapping and no retry storm


class TestQuotaErrorMapping:
    def test_token_quota_reached_is_a_typed_non_retryable_error(self):
        """403 + ``token_quota_reached`` is a configuration-class failure:
        the next identical request will be rejected identically, so retrying
        can only burn time on an account that is already over its limit."""
        provider = build_quota_blocked_provider(QuotaExhaustedWatsonx())

        with pytest.raises(LLMAuthenticationError) as exc_info:
            provider.generate_structured(a_request(), response_model=Widget)

        assert exc_info.value.retryable is False
        assert exc_info.value.provider_name == "watsonx"
        assert exc_info.value.model_name == MODEL_ID

    def test_exactly_one_inference_request_is_made_even_with_retries_configured(self):
        """The live backend runs with FACTORYMIND_LLM_MAX_RETRIES=2."""
        handler = QuotaExhaustedWatsonx()
        provider = build_quota_blocked_provider(handler, max_retries=2)

        with pytest.raises(LLMAuthenticationError):
            provider.generate_structured(a_request(), response_model=Widget)

        assert handler.calls == 1

    def test_the_error_keeps_ibms_diagnostic_code_so_the_cause_is_identifiable(self):
        """"watsonx unavailable" is not a diagnosis."""
        provider = build_quota_blocked_provider(QuotaExhaustedWatsonx())

        with pytest.raises(LLMAuthenticationError) as exc_info:
            provider.generate_structured(a_request(), response_model=Widget)

        message = str(exc_info.value)
        assert "token_quota_reached" in message
        assert "403" in message

    def test_the_error_carries_no_credential(self):
        provider = build_quota_blocked_provider(QuotaExhaustedWatsonx())

        with pytest.raises(LLMAuthenticationError) as exc_info:
            provider.generate_structured(a_request(), response_model=Widget)

        message = str(exc_info.value)
        assert API_KEY not in message
        assert BEARER not in message

    def test_a_quota_block_is_distinguishable_from_a_rejected_api_key(self):
        """
        Both are 403/401-class, both are non-retryable — but they need completely
        different operator actions (top up the account vs.
        """
        quota = build_quota_blocked_provider(QuotaExhaustedWatsonx())

        def bad_key(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"errors": [{"code": "access_denied", "message": "no access"}]})

        denied = build_quota_blocked_provider(bad_key)

        with pytest.raises(LLMAuthenticationError) as quota_exc:
            quota.generate_structured(a_request(), response_model=Widget)
        with pytest.raises(LLMAuthenticationError) as denied_exc:
            denied.generate_structured(a_request(), response_model=Widget)

        assert "token_quota_reached" in str(quota_exc.value)
        assert "token_quota_reached" not in str(denied_exc.value)
        assert "access_denied" in str(denied_exc.value)


# B. API layer — honest fallback, never a stale IBM badge


@pytest.fixture
def example_factory_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app)


@pytest.fixture
def quota_blocked(monkeypatch: pytest.MonkeyPatch):
    """Install a quota-blocked watsonx provider exactly where ``app.main``
    resolves its process-lifetime provider."""
    handler = QuotaExhaustedWatsonx()
    monkeypatch.setattr(main_module, "_LLM_PROVIDER", build_quota_blocked_provider(handler, max_retries=2))
    return handler


THE_REQUEST = "We need 1900 units/day. Avoid buying new machines if possible."


class TestPlanningRunUnderQuotaBlock:
    def test_the_endpoint_still_succeeds(self, client, example_factory_json, quota_blocked):
        """
        The deterministic engineering system is the product; the model is an optional
        interpretation layer on top of it.
        """
        resp = client.post("/planning/run", json={
            "factory": example_factory_json,
            "product_id": "p-electronics-widget",
            "user_request": THE_REQUEST,
        })
        assert resp.status_code == 200, resp.text

    def test_provenance_admits_the_fallback_and_never_claims_granite(
        self, client, example_factory_json, quota_blocked,
    ):
        body = self._run(client, example_factory_json)
        provenance = body["provenance"]

        assert provenance["fallback_used"] is True
        assert provenance["requirements_source"] == "DETERMINISTIC"
        # The configured provider/model are still reported truthfully — the
        # account is what failed, not the configuration — but neither field
        # is ever allowed to imply the model actually ran.
        assert provenance["provider_name"] == "watsonx"
        assert provenance["model_name"] == MODEL_ID

    def test_the_kpis_are_still_produced_by_the_simulator(
        self, client, example_factory_json, quota_blocked,
    ):
        body = self._run(client, example_factory_json)
        session = body["session"]

        for simulation in (session["baseline_simulation"], session["current_simulation"]):
            assert simulation["completed_units"] >= 0
            assert simulation["target_units"] > 0
            assert "bottleneck_machine_id" in simulation["system"]

    def test_no_credential_reaches_the_api_response(
        self, client, example_factory_json, quota_blocked,
    ):
        raw = json.dumps(self._run(client, example_factory_json))
        assert API_KEY not in raw
        assert BEARER not in raw

    def test_one_failed_call_per_llm_stage_at_most_never_a_retry_storm(
        self, client, example_factory_json, quota_blocked,
    ):
        """
        A whole planning run may attempt several stages (requirements, planning,
        explanation).
        """
        self._run(client, example_factory_json)
        assert 1 <= quota_blocked.calls <= 3

    @staticmethod
    def _run(client: TestClient, factory_json: dict) -> dict:
        resp = client.post("/planning/run", json={
            "factory": factory_json,
            "product_id": "p-electronics-widget",
            "user_request": THE_REQUEST,
        })
        assert resp.status_code == 200, resp.text
        return resp.json()


class TestStrategyExploreUnderQuotaBlock:
    """The Executive View flagship path."""

    def test_the_arena_still_produces_verified_strategies(
        self, client, example_factory_json, quota_blocked,
    ):
        body = self._explore(client, example_factory_json)
        arena = body["arena"]

        assert arena["stats"]["simulations_run"] > 0
        assert len(arena["strategies"]) > 0
        for strategy in arena["strategies"]:
            assert strategy["operationally_verified"] is True

    def test_provenance_reports_the_fallback_honestly(
        self, client, example_factory_json, quota_blocked,
    ):
        provenance = self._explore(client, example_factory_json)["provenance"]

        assert provenance["fallback_used"] is True
        assert provenance["requirements_source"] == "DETERMINISTIC"
        # Strategy KPIs never came from a model in the first place, so this
        # stays DETERMINISTIC whether Granite ran or not.
        assert provenance["planning_source"] == "DETERMINISTIC"

    def test_an_unknown_cost_is_still_reported_as_unknown_not_zero(
        self, client, example_factory_json, quota_blocked,
    ):
        """The quota outage must not quietly change cost semantics: a plan
        with unpriced components stays commercially incomplete and keeps its
        information gaps."""
        arena = self._explore(client, example_factory_json)["arena"]

        incomplete = [s for s in arena["strategies"] if not s["commercially_complete"]]
        for strategy in incomplete:
            assert strategy["cost"]["information_gaps"], (
                f"{strategy['label']} is commercially incomplete but names no information gap"
            )

    def test_no_credential_reaches_the_api_response(
        self, client, example_factory_json, quota_blocked,
    ):
        raw = json.dumps(self._explore(client, example_factory_json))
        assert API_KEY not in raw
        assert BEARER not in raw

    @staticmethod
    def _explore(client: TestClient, factory_json: dict) -> dict:
        resp = client.post("/strategies/explore", json={
            "factory": factory_json,
            "product_id": "p-electronics-widget",
            "user_request": THE_REQUEST,
        })
        assert resp.status_code == 200, resp.text
        return resp.json()
