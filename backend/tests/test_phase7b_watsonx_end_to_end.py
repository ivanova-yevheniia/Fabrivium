"""
Phase 7B end-to-end tests — the REAL ``WatsonxGraniteProvider`` driving the REAL ``POST
/planning/run`` endpoint, against a SIMULATED IBM watsonx.ai.
"""

from __future__ import annotations

import json
import pathlib
import re

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.llm.iam import IBMCloudIAMTokenProvider
from app.llm.models import RetryPolicy
from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent.parent / "examples"

API_KEY = "fake-local-api-key-value-0123456789"
BEARER = "fake-iam-bearer-token-abcdefghijklmnop"
MODEL_ID = "ibm/granite-4-h-small"
PROJECT_ID = "38acdfa3-0000-0000-0000-000000000000"


# A simulated Granite that answers each agent the way a good model would


def _requirements_answer() -> str:
    return json.dumps({
        "objective": "MEET_DEMAND",
        "target_units_per_day": 1900.0,
        "max_capex": 220_000.0,
        "forbidden_machine_ids": ["m-packaging"],
        "preserve_existing_layout": True,
        "confidence": 0.95,
    })


def _planning_answer(machine_id: str = "m-screwdriving") -> str:
    """A grounded proposal: it selects the deterministic optimizer's own
    ADD_PARALLEL_MACHINE candidate rather than inventing an action."""
    return json.dumps([{
        "proposal_id": f"granite-{machine_id}",
        "hypothesis": {
            "problem_summary": f"{machine_id} is the bottleneck.",
            "suspected_bottleneck_machine_id": machine_id,
            "suspected_issue_type": "INSUFFICIENT_CAPACITY",
            "evidence": [],
        },
        "scenario": {
            "id": f"granite-cand-{machine_id}", "name": "Add parallel capacity", "description": "",
            "actions": [{"action_type": "ADD_PARALLEL_MACHINE", "machine_id": machine_id}],
        },
        "expected_effects": ["Reduce the queue at the bottleneck."],
        "risks": [], "confidence": 0.8, "source": "LLM",
    }])


def _bottleneck_of(user_prompt: str) -> str:
    """Read the verified bottleneck straight out of the compact context the
    prompt carries — the same fact a real model would base its choice on."""
    match = _BOTTLENECK_RE.search(user_prompt)
    return match.group(1) if match else "m-screwdriving"


def _explanation_answer() -> str:
    """Deliberately vague-but-honest: it asserts no number and no machine
    id, so it passes the Phase 5D hallucination guard regardless of which
    path the deterministic engine actually took."""
    return json.dumps({
        "executive_summary": "FactoryMind evaluated the request and verified each step by simulation.",
        "goal_status": "See the verified iteration timeline for the outcome.",
        "recommended_changes": [], "verified_effects": [], "tradeoffs": [], "constraints_and_risks": [],
        "stop_explanation": "Planning stopped once the deterministic engine had nothing further to verify.",
        "sections": [],
    })


_BOTTLENECK_RE = re.compile(r'"bottleneck_machine_id"\s*:\s*"([^"]+)"')


class FakeWatsonx:
    """
    Routes a chat request to the right canned answer by looking at which agent's system
    prompt it carries, and records everything it saw.
    """

    def __init__(self, *, planning_answer: str | None = None, explanation_answer: str | None = None) -> None:
        self.planning_answer = planning_answer
        self.explanation_answer = explanation_answer if explanation_answer is not None else _explanation_answer()
        self.requests: list[dict] = []
        self.auth_headers: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        self.auth_headers.append(request.headers.get("authorization", ""))

        system_prompt = body["messages"][0]["content"]
        user_prompt = body["messages"][1]["content"][0]["text"]
        if "PlanningRequirements" in system_prompt:
            content = _requirements_answer()
        elif "PlanningProposal" in system_prompt:
            content = self.planning_answer if self.planning_answer is not None else _planning_answer(
                _bottleneck_of(user_prompt)
            )
        else:
            content = self.explanation_answer

        return httpx.Response(200, json={
            "id": "chatcmpl-fake", "model_id": MODEL_ID, "created": 1712345678,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020},
        })


def build_provider(chat_handler, *, max_retries: int = 0) -> WatsonxGraniteProvider:
    def iam_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": BEARER, "expires_in": 3600})

    return WatsonxGraniteProvider(
        WatsonxSettings(url="https://eu-de.ml.cloud.example.invalid", project_id=PROJECT_ID,
                        api_key=API_KEY, model_id=MODEL_ID),
        retry_policy=RetryPolicy(max_retries=max_retries, timeout_seconds=60.0),
        client=httpx.Client(transport=httpx.MockTransport(chat_handler)),
        token_provider=IBMCloudIAMTokenProvider(
            API_KEY, client=httpx.Client(transport=httpx.MockTransport(iam_handler))),
    )


@pytest.fixture
def example_factory_json() -> dict:
    with open(EXAMPLES_DIR / "electronics_line.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main_module.app)


@pytest.fixture
def with_provider(monkeypatch: pytest.MonkeyPatch):
    """Install a watsonx provider as the app's process-lifetime provider,
    exactly where ``app.main`` resolves it."""
    def install(provider) -> None:
        monkeypatch.setattr(main_module, "_LLM_PROVIDER", provider)

    return install


THE_REQUEST = "We need 1900 units/day, budget €220k, don't modify Packaging, and keep the existing layout."


def run_plan(client: TestClient, factory_json: dict, user_request: str = THE_REQUEST) -> dict:
    resp = client.post("/planning/run", json={
        "factory": factory_json,
        "product_id": "p-electronics-widget",
        "user_request": user_request,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# A. Valid credentials + Granite available -> provenance = LLM


class TestHappyPath:
    def test_provenance_reports_watsonx_and_granite(self, client, example_factory_json, with_provider):
        fake = FakeWatsonx()
        with_provider(build_provider(fake))
        body = run_plan(client, example_factory_json)

        provenance = body["provenance"]
        assert provenance["requirements_source"] == "LLM"
        assert provenance["planning_source"] == "LLM"
        assert provenance["explanation_source"] == "LLM"
        assert provenance["fallback_used"] is False
        assert provenance["provider_name"] == "watsonx"
        assert provenance["model_name"] == MODEL_ID

    def test_requirements_are_the_ones_the_model_returned(self, client, example_factory_json, with_provider):
        with_provider(build_provider(FakeWatsonx()))
        requirements = run_plan(client, example_factory_json)["parse_result"]["parsed_requirements"]
        assert requirements["target_units_per_day"] == 1900.0
        assert requirements["max_capex"] == 220_000.0
        assert requirements["forbidden_machine_ids"] == ["m-packaging"]
        assert requirements["preserve_existing_layout"] is True

    def test_every_request_carried_a_bearer_token_and_the_documented_payload(
        self, client, example_factory_json, with_provider,
    ):
        fake = FakeWatsonx()
        with_provider(build_provider(fake))
        run_plan(client, example_factory_json)

        assert fake.requests, "the provider never called watsonx"
        assert all(header == f"Bearer {BEARER}" for header in fake.auth_headers)
        for body in fake.requests:
            assert body["model_id"] == MODEL_ID
            assert body["project_id"] == PROJECT_ID
            assert body["temperature"] == 0.0
            assert body["messages"][0]["role"] == "system"

    def test_engineering_results_remain_deterministic_not_model_authored(
        self, client, example_factory_json, with_provider,
    ):
        """Every number in the session comes from the simulator, not the model."""
        with_provider(build_provider(FakeWatsonx()))
        body = run_plan(client, example_factory_json)
        session = body["session"]

        from app.models.factory import Factory
        from app.services.simulation import run_simulation

        replayed = run_simulation(Factory.model_validate(session["current_factory"]), "p-electronics-widget")
        final = session["final_snapshot"]["simulation"]

        assert replayed.completed_units == final["completed_units"]
        assert replayed.demand_gap_units == final["demand_gap_units"]
        assert replayed.demand_met == final["demand_met"]
        assert replayed.system.bottleneck_machine_id == final["system"]["bottleneck_machine_id"]
        assert replayed.operator_kpi.utilization == pytest.approx(final["operator_kpi"]["utilization"])

    def test_a_machine_only_model_hits_the_workforce_wall(
        self, client, example_factory_json, with_provider,
    ):
        """
        Phase 8A, and a genuinely useful thing to pin: a model that only knows how to
        buy equipment cannot solve a staffing problem.
        """
        with_provider(build_provider(FakeWatsonx()))
        session = run_plan(client, example_factory_json)["session"]

        accepted = [it for it in session["iterations"] if it["accepted"]]
        assert len(accepted) == 1
        assert accepted[0]["selected_proposal"]["scenario"]["actions"][0]["machine_id"] == "m-screwdriving"
        assert session["goal_reached"] is False
        assert session["cumulative_known_capex"] == 85_000.0
        # The rejected purchase is recorded, not silently dropped.
        assert any(
            not it["accepted"] and it["selected_proposal"] is not None
            for it in session["iterations"]
        )

    def test_every_step_is_verified_and_the_forbidden_machine_is_never_touched(
        self, client, example_factory_json, with_provider,
    ):
        """
        Every accepted step carries its own verified simulation, and the user's lock
        holds no matter what the model proposed.
        """
        with_provider(build_provider(FakeWatsonx()))
        session = run_plan(client, example_factory_json)["session"]

        accepted = [it for it in session["iterations"] if it["accepted"]]
        assert accepted
        for iteration in accepted:
            assert iteration["scenario_result"] is not None
            assert iteration["state_after"] is not None
            assert iteration["state_after"]["simulation"]["completed_units"] >= 0

        # The forbidden machine was never touched, whatever the model said.
        assert "m-packaging" not in json.dumps([it["selected_proposal"] for it in accepted])

    def test_a_model_that_repeats_itself_is_stopped_honestly(
        self, client, example_factory_json, with_provider,
    ):
        """
        A model that proposes the same intervention every iteration must not loop
        forever, and must never be reported as having reached a goal it did not reach.
        """
        with_provider(build_provider(FakeWatsonx(planning_answer=_planning_answer("m-screwdriving"))))
        session = run_plan(client, example_factory_json)["session"]

        assert session["stop_reason"] == "REPEATED_PROPOSAL"
        assert session["goal_reached"] is False
        assert len(session["iterations"]) < 5  # bounded, never a loop

    def test_no_credential_appears_anywhere_in_the_api_response(
        self, client, example_factory_json, with_provider,
    ):
        with_provider(build_provider(FakeWatsonx()))
        resp = client.post("/planning/run", json={
            "factory": example_factory_json, "product_id": "p-electronics-widget", "user_request": THE_REQUEST,
        })
        payload = resp.text
        assert API_KEY not in payload
        assert BEARER not in payload
        assert "Bearer" not in payload
        assert "FACTORYMIND_WATSONX_API_KEY" not in payload
        # The endpoint URL and project id are backend-only too.
        assert "ml.cloud" not in payload


# B-E. Failure modes (Phase 7B section 12) — FactoryMind stays operational


class TestFailureModesStayOperational:
    def _assert_still_usable(self, body: dict) -> None:
        """Whatever went wrong upstream, the deterministic product still
        answered: a session with a real stop reason and a real explanation."""
        assert body["session"]["stop_reason"]
        assert body["explanation"]["executive_summary"]
        assert body["parse_result"]["parsed_requirements"]["objective"]

    def test_b_wrong_model_id_falls_back_without_breaking_anything(
        self, client, example_factory_json, with_provider,
    ):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"trace": "t", "errors": [
                {"code": "model_not_supported", "message": "Model 'ibm/nope' is not supported"}]})

        with_provider(build_provider(handler))
        body = run_plan(client, example_factory_json)

        assert body["provenance"]["fallback_used"] is True
        assert body["provenance"]["requirements_source"] == "DETERMINISTIC"
        assert body["provenance"]["explanation_source"] == "DETERMINISTIC"
        # Identity is still reported honestly: a model WAS configured, it
        # just could not be used.
        assert body["provenance"]["model_name"] == MODEL_ID
        self._assert_still_usable(body)

    def test_c_timeout_falls_back(self, client, example_factory_json, with_provider):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with_provider(build_provider(handler))
        body = run_plan(client, example_factory_json)
        assert body["provenance"]["fallback_used"] is True
        assert body["provenance"]["requirements_source"] == "DETERMINISTIC"
        self._assert_still_usable(body)

    def test_d_malformed_response_falls_back(self, client, example_factory_json, with_provider):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "id": "x", "model_id": MODEL_ID, "created": 1,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "Sure! Here you go: <not json>"}}],
            })

        with_provider(build_provider(handler, max_retries=1))
        body = run_plan(client, example_factory_json)
        assert body["provenance"]["fallback_used"] is True
        self._assert_still_usable(body)

    def test_e_hallucinated_proposal_is_rejected_never_executed(
        self, client, example_factory_json, with_provider,
    ):
        """A proposal naming a machine that does not exist must be rejected
        by the existing validator — the run continues on deterministic
        proposals, and the fabricated machine never appears in a scenario."""
        fake = FakeWatsonx(planning_answer=_planning_answer("m-does-not-exist"))
        with_provider(build_provider(fake))
        body = run_plan(client, example_factory_json)

        session = body["session"]
        rejected_reasons = [
            reason
            for iteration in session["iterations"]
            for rejection in iteration["planning_agent_result"]["rejected_proposals"]
            for reason in rejection["reasons"]
        ]
        assert any("unknown machine_id" in reason for reason in rejected_reasons)
        assert "m-does-not-exist" not in json.dumps(session["iterations"] and [
            it["selected_proposal"] for it in session["iterations"] if it.get("selected_proposal")
        ])
        self._assert_still_usable(body)

    def test_e2_ungrounded_proposal_is_rejected_by_optimizer_grounding(
        self, client, example_factory_json, with_provider,
    ):
        """A real machine, but an intervention the optimizer never
        generated and the user never asked for: still rejected."""
        fake = FakeWatsonx(planning_answer=json.dumps([{
            "proposal_id": "granite-ungrounded",
            "hypothesis": {"problem_summary": "guess", "suspected_issue_type": "UNKNOWN", "evidence": []},
            "scenario": {"id": "s", "name": "n", "description": "", "actions": [
                {"action_type": "CHANGE_MACHINE_CYCLE_TIME", "machine_id": "m-assembly", "cycle_time": 0.01}]},
            "expected_effects": [], "risks": [], "confidence": 0.99, "source": "LLM",
        }]))
        with_provider(build_provider(fake))
        body = run_plan(client, example_factory_json)

        rejected_reasons = [
            reason
            for iteration in body["session"]["iterations"]
            for rejection in iteration["planning_agent_result"]["rejected_proposals"]
            for reason in rejection["reasons"]
        ]
        assert any("optimizer_grounded" in reason for reason in rejected_reasons)
        self._assert_still_usable(body)

    def test_f_hallucinated_explanation_is_rejected_and_replaced(
        self, client, example_factory_json, with_provider,
    ):
        fake = FakeWatsonx(explanation_answer=json.dumps({
            "executive_summary": "We reached 5000 units/day for only €12 using machine m-teleporter.",
            "goal_status": "Goal reached.", "recommended_changes": [], "verified_effects": [],
            "tradeoffs": [], "constraints_and_risks": [], "stop_explanation": "Done.", "sections": [],
        }))
        with_provider(build_provider(fake))
        body = run_plan(client, example_factory_json)

        assert body["provenance"]["explanation_source"] == "DETERMINISTIC"
        assert body["provenance"]["fallback_used"] is True
        assert "m-teleporter" not in json.dumps(body["explanation"])
        assert "5000" not in json.dumps(body["explanation"])

    def test_service_outage_falls_back(self, client, example_factory_json, with_provider):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        with_provider(build_provider(handler))
        body = run_plan(client, example_factory_json)
        assert body["provenance"]["fallback_used"] is True
        self._assert_still_usable(body)

    def test_a_misconfigured_provider_never_takes_the_api_down(self, monkeypatch):
        """Phase 7B: a bad LLM setting must degrade to deterministic-only,
        not prevent the app from serving at all."""
        monkeypatch.setenv("FACTORYMIND_LLM_ENABLED", "true")
        monkeypatch.setenv("FACTORYMIND_LLM_PROVIDER", "watsonx")
        monkeypatch.delenv("FACTORYMIND_WATSONX_API_KEY", raising=False)
        monkeypatch.delenv("FACTORYMIND_WATSONX_URL", raising=False)
        monkeypatch.delenv("FACTORYMIND_WATSONX_PROJECT_ID", raising=False)

        assert main_module._build_llm_provider() is None


# The suite must never make a real, billable call (Phase 7B section 18)


class TestNoAccidentalLiveCalls:
    def test_the_app_under_test_has_no_live_provider_even_with_credentials_present(self):
        """
        Regression guard for a real defect: once a genuine IBM API key landed in
        backend/.env, ``app.main`` began resolving a LIVE watsonx provider at import
        time — which would have made every pre-existing ``/planning/run`` endpoint test
        (none of which know an LLM exists) start issuing billable requests to IBM.
        """
        assert main_module._llm_provider() is None

    def test_a_planning_run_makes_no_outbound_connection(self, client, example_factory_json, monkeypatch):
        """
        Behavioral proof, not a config assertion: block every OUTBOUND socket connection
        and run the real endpoint end to end.
        """
        import socket

        real_connect = socket.socket.connect

        def _guarded_connect(self, address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) and address else ""
            if host not in ("127.0.0.1", "::1", "localhost", ""):
                raise AssertionError(
                    f"The default test suite must never open an outbound connection (attempted {host!r})."
                )
            return real_connect(self, address, *args, **kwargs)

        monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
        body = run_plan(client, example_factory_json, "We need 1200 units per day.")
        assert body["session"]["stop_reason"]
        assert body["provenance"]["provider_name"] is None


# Token usage observability (Phase 7B section 13)


class TestUsageObservability:
    def test_token_counts_reach_the_audit_record(self, example_factory_json):
        from app.llm.models import LLMInvocationRecord
        from app.services.agent_context import build_factory_context
        from app.services.llm_integration import parse_requirements_with_fallback
        from app.models.factory import Factory

        records: list[LLMInvocationRecord] = []
        provider = build_provider(FakeWatsonx())
        factory = Factory.model_validate(example_factory_json)

        parse_requirements_with_fallback(
            THE_REQUEST, build_factory_context(factory), provider, on_invocation=records.append,
        )

        assert len(records) == 1
        record = records[0]
        assert record.provider_name == "watsonx"
        assert record.model_name == MODEL_ID
        assert (record.prompt_tokens, record.completion_tokens, record.total_tokens) == (900, 120, 1020)
        assert record.request_id == "chatcmpl-fake"

    def test_a_provider_reporting_no_usage_invents_nothing(self, example_factory_json):
        from app.llm.mock_provider import MockLLMProvider, MockOutcome
        from app.llm.models import LLMInvocationRecord
        from app.services.agent_context import build_factory_context
        from app.services.llm_integration import parse_requirements_with_fallback
        from app.models.factory import Factory

        records: list[LLMInvocationRecord] = []
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({"objective": "MEET_DEMAND"})])
        factory = Factory.model_validate(example_factory_json)

        parse_requirements_with_fallback(
            "anything", build_factory_context(factory), provider, on_invocation=records.append,
        )
        assert records[0].total_tokens is None
        assert records[0].prompt_tokens is None
