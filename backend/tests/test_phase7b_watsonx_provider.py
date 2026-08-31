"""
Phase 7B tests — WatsonxGraniteProvider (request construction, response parsing, usage
metadata, error mapping, retry semantics, secret hygiene).
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from app.llm import build_provider, load_llm_settings
from app.llm.errors import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.iam import IBMCloudIAMTokenProvider
from app.llm.models import LLMRequest, RetryPolicy
from app.llm.watsonx_provider import (
    DEFAULT_API_VERSION,
    WatsonxGraniteProvider,
    WatsonxSettings,
    _strip_code_fence,
)

API_KEY = "fake-local-api-key-value-0123456789"
BEARER = "fake-iam-bearer-token-abcdefghijklmnop"
URL = "https://eu-de.ml.cloud.example.invalid"
PROJECT_ID = "38acdfa3-0000-0000-0000-000000000000"
MODEL_ID = "ibm/granite-4-h-small"


class Widget(BaseModel):
    name: str
    count: int


def settings(**overrides) -> WatsonxSettings:
    base = dict(url=URL, project_id=PROJECT_ID, api_key=API_KEY, model_id=MODEL_ID)
    base.update(overrides)
    return WatsonxSettings(**base)


def chat_ok(content: str = '{"name":"widget","count":3}', *, finish_reason: str = "stop", usage: dict | None = None,
            response_id: str = "chatcmpl-abc123") -> dict:
    body: dict = {
        "id": response_id,
        "model_id": MODEL_ID,
        "created": 1712345678,
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def make_provider(chat_handler, *, retry_policy: RetryPolicy | None = None, **setting_overrides):
    """Build a provider whose IAM and chat transports are both mocked."""
    def iam_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": BEARER, "expires_in": 3600})

    iam_client = httpx.Client(transport=httpx.MockTransport(iam_handler))
    chat_client = httpx.Client(transport=httpx.MockTransport(chat_handler))
    cfg = settings(**setting_overrides)
    return WatsonxGraniteProvider(
        cfg,
        retry_policy=retry_policy or RetryPolicy(max_retries=0, timeout_seconds=60.0),
        client=chat_client,
        token_provider=IBMCloudIAMTokenProvider(API_KEY, client=iam_client),
    )


def request(**overrides) -> LLMRequest:
    base = dict(system_prompt="SYSTEM RULES", user_prompt="USER PAYLOAD",
                response_schema={"type": "object"}, metadata={"agent": "requirements"})
    base.update(overrides)
    return LLMRequest(**base)


# Settings


class TestSettings:
    def test_chat_endpoint_matches_the_documented_watsonx_contract(self):
        assert settings().chat_endpoint == f"{URL}/ml/v1/text/chat?version={DEFAULT_API_VERSION}"

    def test_trailing_slash_on_url_does_not_double_up(self):
        assert "//ml/v1" not in settings(url=URL + "/").chat_endpoint

    def test_from_env_reads_every_documented_variable(self):
        cfg = WatsonxSettings.from_env({
            "FACTORYMIND_WATSONX_URL": URL,
            "FACTORYMIND_WATSONX_PROJECT_ID": PROJECT_ID,
            "FACTORYMIND_WATSONX_API_KEY": API_KEY,
            "FACTORYMIND_WATSONX_MODEL_ID": MODEL_ID,
            "FACTORYMIND_WATSONX_API_VERSION": "2024-03-14",
            "FACTORYMIND_WATSONX_MAX_TOKENS": "512",
            "FACTORYMIND_WATSONX_JSON_MODE": "text",
        })
        assert (cfg.url, cfg.project_id, cfg.model_id) == (URL, PROJECT_ID, MODEL_ID)
        assert cfg.api_version == "2024-03-14"
        assert cfg.max_tokens == 512
        assert cfg.json_mode == "text"

    @pytest.mark.parametrize("missing", [
        "FACTORYMIND_WATSONX_URL", "FACTORYMIND_WATSONX_PROJECT_ID", "FACTORYMIND_WATSONX_API_KEY",
    ])
    def test_missing_required_setting_is_a_typed_auth_error(self, missing: str):
        env = {
            "FACTORYMIND_WATSONX_URL": URL,
            "FACTORYMIND_WATSONX_PROJECT_ID": PROJECT_ID,
            "FACTORYMIND_WATSONX_API_KEY": API_KEY,
        }
        del env[missing]
        with pytest.raises(LLMAuthenticationError):
            WatsonxSettings.from_env(env)

    def test_invalid_json_mode_is_rejected(self):
        with pytest.raises(LLMAuthenticationError):
            settings(json_mode="yaml_please")

    def test_repr_never_renders_the_api_key(self):
        assert API_KEY not in repr(settings())


# build_provider wiring


class TestBuildProviderWiring:
    def test_watsonx_is_now_a_supported_provider(self):
        provider = build_provider(
            load_llm_settings(env={"FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "watsonx"}),
            env={
                "FACTORYMIND_WATSONX_URL": URL,
                "FACTORYMIND_WATSONX_PROJECT_ID": PROJECT_ID,
                "FACTORYMIND_WATSONX_API_KEY": API_KEY,
            },
        )
        assert provider is not None
        assert provider.provider_name == "watsonx"
        assert provider.model_name == MODEL_ID
        provider.close()

    def test_missing_credentials_fail_loudly_rather_than_silently_disabling(self):
        with pytest.raises(LLMAuthenticationError):
            build_provider(
                load_llm_settings(env={"FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "watsonx"}),
                env={},
            )

    def test_generic_model_env_var_overrides_the_watsonx_model_id(self):
        provider = build_provider(
            load_llm_settings(env={
                "FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "watsonx",
                "FACTORYMIND_LLM_MODEL": "ibm/granite-3-8b-instruct",
            }),
            env={
                "FACTORYMIND_WATSONX_URL": URL,
                "FACTORYMIND_WATSONX_PROJECT_ID": PROJECT_ID,
                "FACTORYMIND_WATSONX_API_KEY": API_KEY,
            },
        )
        assert provider.model_name == "ibm/granite-3-8b-instruct"
        provider.close()

    def test_a_still_unimplemented_provider_fails_loudly(self):
        with pytest.raises(LLMAuthenticationError):
            build_provider(load_llm_settings(env={
                "FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "openai",
            }))


# Request construction


class TestRequestConstruction:
    def _capture(self, **kwargs) -> dict:
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["url"] = str(req.url)
            seen["headers"] = dict(req.headers)
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler, **kwargs)
        provider.generate_structured(request(), response_model=Widget)
        return seen

    def test_posts_to_the_documented_chat_endpoint_with_a_bearer_token(self):
        seen = self._capture()
        assert seen["url"] == f"{URL}/ml/v1/text/chat?version={DEFAULT_API_VERSION}"
        assert seen["headers"]["authorization"] == f"Bearer {BEARER}"
        assert seen["headers"]["content-type"] == "application/json"
        assert seen["headers"]["accept"] == "application/json"

    def test_body_carries_model_project_and_messages(self):
        body = self._capture()["body"]
        assert body["model_id"] == MODEL_ID
        assert body["project_id"] == PROJECT_ID
        assert body["messages"][0] == {"role": "system", "content": "SYSTEM RULES"}
        assert body["messages"][1]["role"] == "user"
        assert body["messages"][1]["content"] == [{"type": "text", "text": "USER PAYLOAD"}]

    def test_sampling_parameters_are_pinned_deterministic(self):
        body = self._capture()["body"]
        assert body["temperature"] == 0.0
        assert body["top_p"] == 1
        assert body["frequency_penalty"] == 0
        assert body["presence_penalty"] == 0

    def test_time_limit_is_milliseconds_and_below_the_client_timeout(self):
        body = self._capture(retry_policy=RetryPolicy(max_retries=0, timeout_seconds=60.0))["body"]
        assert body["time_limit"] == 58_000

    def test_space_id_replaces_project_id_when_configured(self):
        body = self._capture(space_id="space-123")["body"]
        assert body["space_id"] == "space-123"
        assert "project_id" not in body

    def test_object_schema_hint_enables_native_json_object_mode(self):
        body = self._capture()["body"]
        assert body["response_format"] == {"type": "json_object"}

    def test_array_schema_hint_disables_json_object_mode(self):
        """JSON-object mode biases a model toward a top-level object, but
        the planning agent's contract is a top-level ARRAY of proposals."""
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok('[{"name":"w","count":1}]'))

        provider = make_provider(handler)
        provider.generate_structured(request(response_schema={"type": "array"}), response_model=list[Widget])
        assert "response_format" not in seen["body"]

    def test_text_json_mode_sends_no_response_format_at_all(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler, json_mode="text")
        provider.generate_structured(request(), response_model=Widget)
        assert "response_format" not in seen["body"]

    def test_json_schema_mode_forwards_the_caller_schema(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler, json_mode="json_schema")
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        provider.generate_structured(request(response_schema=schema), response_model=Widget)
        assert seen["body"]["response_format"]["type"] == "json_schema"
        assert seen["body"]["response_format"]["json_schema"]["schema"] == schema
        assert seen["body"]["response_format"]["json_schema"]["name"] == "requirements"

    def test_a_contentful_schema_is_shown_to_the_model_not_merely_named(self):
        """Naming a schema is not showing it: live Granite invented its own
        field names until the actual schema was in the system message."""
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        schema = {"type": "object", "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
                  "required": ["name", "count"]}
        provider = make_provider(handler)
        provider.generate_structured(request(response_schema=schema), response_model=Widget)

        system_content = seen["body"]["messages"][0]["content"]
        assert system_content.startswith("SYSTEM RULES")
        assert "JSON object" in system_content
        assert '"count"' in system_content
        assert "do not add fields that are not in the schema" in system_content

    def test_an_array_schema_asks_for_an_array(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok('[{"name":"w","count":1}]'))

        schema = {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}
        provider = make_provider(handler)
        provider.generate_structured(request(response_schema=schema), response_model=list[Widget])
        assert "JSON array" in seen["body"]["messages"][0]["content"]

    def test_a_bare_container_hint_adds_no_useless_schema_block(self):
        """``{"type": "object"}`` tells a model nothing — don't spend tokens
        on it."""
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler)
        provider.generate_structured(request(response_schema={"type": "object"}), response_model=Widget)
        assert seen["body"]["messages"][0]["content"] == "SYSTEM RULES"

    def test_no_schema_leaves_the_system_prompt_untouched(self):
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler)
        provider.generate_structured(request(response_schema=None), response_model=Widget)
        assert seen["body"]["messages"][0]["content"] == "SYSTEM RULES"

    def test_max_tokens_comes_from_the_request_then_settings(self):
        assert self._capture()["body"]["max_tokens"] == 2000
        seen: dict = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json=chat_ok())

        provider = make_provider(handler)
        provider.generate_structured(request(max_tokens=64), response_model=Widget)
        assert seen["body"]["max_tokens"] == 64


# Response parsing


class TestResponseParsing:
    def test_valid_structured_response_is_parsed_and_validated(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok()))
        result = provider.generate_structured(request(), response_model=Widget)
        assert result.parsed == Widget(name="widget", count=3)
        assert result.attempts == 1

    def test_response_metadata_is_captured(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok(
            usage={"prompt_tokens": 812, "completion_tokens": 96, "total_tokens": 908},
            response_id="chatcmpl-xyz",
        )))
        response = provider.generate_structured(request(), response_model=Widget).response
        assert response.provider_name == "watsonx"
        assert response.model_name == MODEL_ID
        assert response.usage == {"prompt_tokens": 812, "completion_tokens": 96, "total_tokens": 908}
        assert response.request_id == "chatcmpl-xyz"
        assert response.latency_ms >= 0.0

    def test_absent_usage_block_is_reported_as_none_never_invented(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok()))
        assert provider.generate_structured(request(), response_model=Widget).response.usage is None

    def test_partial_usage_block_reports_only_what_ibm_actually_sent(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok(usage={"total_tokens": 42})))
        assert provider.generate_structured(request(), response_model=Widget).response.usage == {"total_tokens": 42}

    def test_markdown_fenced_json_is_normalized(self):
        fenced = '```json\n{"name":"widget","count":3}\n```'
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok(fenced)))
        assert provider.generate_structured(request(), response_model=Widget).parsed == Widget(name="widget", count=3)

    def test_prose_around_json_is_not_rescued(self):
        """Normalizing a code fence is fine; salvaging JSON out of prose is
        exactly the "almost JSON" trust Phase 7B forbids."""
        provider = make_provider(lambda req: httpx.Response(
            200, json=chat_ok('Sure! Here is the object: {"name":"widget","count":3}')))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    def test_non_json_content_is_a_malformed_response(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok("I cannot help with that.")))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    def test_valid_json_of_the_wrong_shape_is_a_malformed_response(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok('{"totally":"unrelated"}')))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    @pytest.mark.parametrize("finish_reason", ["length", "time_limit", "error", "cancelled"])
    def test_truncated_or_aborted_generation_is_never_trusted(self, finish_reason: str):
        """Even syntactically valid JSON from a truncated generation is
        rejected — a cut-off answer is not a complete answer."""
        provider = make_provider(lambda req: httpx.Response(
            200, json=chat_ok(finish_reason=finish_reason)))
        with pytest.raises(LLMMalformedResponseError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        assert finish_reason in str(exc_info.value)

    def test_empty_choices_is_a_malformed_response(self):
        provider = make_provider(lambda req: httpx.Response(200, json={"id": "x", "model_id": MODEL_ID,
                                                                       "created": 1, "choices": []}))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    def test_null_content_with_a_refusal_is_a_malformed_response(self):
        body = chat_ok()
        body["choices"][0]["message"] = {"role": "assistant", "content": None, "refusal": "I won't answer that."}
        provider = make_provider(lambda req: httpx.Response(200, json=body))
        with pytest.raises(LLMMalformedResponseError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        assert "refusal" in str(exc_info.value)

    def test_non_json_success_body_is_a_malformed_response(self):
        provider = make_provider(lambda req: httpx.Response(200, text="<html>gateway</html>"))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)


# Error mapping + retry semantics


def _error_body(code: str, message: str) -> dict:
    return {"trace": "trace-id", "errors": [{"code": code, "message": message}]}


class TestErrorMapping:
    def test_403_maps_to_authentication_error(self):
        provider = make_provider(lambda req: httpx.Response(403, json=_error_body("access_denied", "no access")))
        with pytest.raises(LLMAuthenticationError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        assert exc_info.value.retryable is False

    def test_429_maps_to_rate_limit_error(self):
        provider = make_provider(lambda req: httpx.Response(429, json=_error_body("too_many_requests", "slow down")))
        with pytest.raises(LLMRateLimitError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        assert exc_info.value.retryable is True

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_5xx_maps_to_unavailable_error(self, status: int):
        provider = make_provider(lambda req: httpx.Response(status, json=_error_body("internal", "boom")))
        with pytest.raises(LLMUnavailableError):
            provider.generate_structured(request(), response_model=Widget)

    @pytest.mark.parametrize("status", [408, 504])
    def test_gateway_timeouts_map_to_timeout_error(self, status: int):
        provider = make_provider(lambda req: httpx.Response(status, json=_error_body("timeout", "took too long")))
        with pytest.raises(LLMTimeoutError):
            provider.generate_structured(request(), response_model=Widget)

    def test_transport_timeout_maps_to_timeout_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=req)

        with pytest.raises(LLMTimeoutError):
            make_provider(handler).generate_structured(request(), response_model=Widget)

    def test_connection_failure_maps_to_unavailable_error(self):
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=req)

        with pytest.raises(LLMUnavailableError):
            make_provider(handler).generate_structured(request(), response_model=Widget)

    def test_unknown_model_id_maps_to_unsupported_capability_and_is_not_retried(self):
        """Phase 7B section 12.B: a wrong model id must be a controlled,
        non-retried failure that falls back — not a retry storm."""
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(404, json=_error_body(
                "model_not_supported", "Model 'ibm/granite-does-not-exist' is not supported"))

        provider = make_provider(handler, retry_policy=RetryPolicy(max_retries=3, timeout_seconds=60.0))
        with pytest.raises(LLMUnsupportedCapabilityError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        assert exc_info.value.retryable is False
        assert calls["n"] == 1

    def test_400_bad_request_maps_to_unsupported_capability(self):
        provider = make_provider(lambda req: httpx.Response(400, json=_error_body(
            "json_validation_error", "response_format is not supported by this model")))
        with pytest.raises(LLMUnsupportedCapabilityError):
            provider.generate_structured(request(), response_model=Widget)

    def test_credential_shaped_400_is_routed_to_authentication_error(self):
        provider = make_provider(lambda req: httpx.Response(400, json=_error_body(
            "authentication_token_invalid", "token is not valid")))
        with pytest.raises(LLMAuthenticationError):
            provider.generate_structured(request(), response_model=Widget)


class TestRetryAndTokenRefresh:
    def test_retryable_error_is_retried_up_to_the_shared_policy_bound(self):
        """Retry lives in the Phase 7A base class, not in this provider —
        this proves the real provider inherits it unchanged."""
        calls = {"n": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, json=_error_body("unavailable", "down"))

        provider = make_provider(handler, retry_policy=RetryPolicy(max_retries=2, timeout_seconds=60.0))
        with pytest.raises(LLMUnavailableError):
            provider.generate_structured(request(), response_model=Widget)
        assert calls["n"] == 3  # first attempt + 2 retries, never unbounded

    def test_malformed_response_retries_then_succeeds(self):
        responses = [chat_ok("not json at all"), chat_ok()]

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=responses.pop(0))

        provider = make_provider(handler, retry_policy=RetryPolicy(max_retries=1, timeout_seconds=60.0))
        result = provider.generate_structured(request(), response_model=Widget)
        assert result.parsed == Widget(name="widget", count=3)
        assert result.attempts == 2

    def test_expired_bearer_token_is_refreshed_and_the_call_replayed_once(self):
        """A token expiring mid-session must not push a healthy run into
        the deterministic fallback: 401 -> refresh -> replay, exactly once.
        """
        iam_calls = {"n": 0}

        def iam_handler(req: httpx.Request) -> httpx.Response:
            iam_calls["n"] += 1
            return httpx.Response(200, json={"access_token": f"bearer-{iam_calls['n']}", "expires_in": 3600})

        seen_tokens: list[str] = []

        def chat_handler(req: httpx.Request) -> httpx.Response:
            seen_tokens.append(req.headers["authorization"])
            if len(seen_tokens) == 1:
                return httpx.Response(401, json=_error_body("authentication_token_expired", "token expired"))
            return httpx.Response(200, json=chat_ok())

        provider = WatsonxGraniteProvider(
            settings(),
            retry_policy=RetryPolicy(max_retries=0, timeout_seconds=60.0),
            client=httpx.Client(transport=httpx.MockTransport(chat_handler)),
            token_provider=IBMCloudIAMTokenProvider(
                API_KEY, client=httpx.Client(transport=httpx.MockTransport(iam_handler))),
        )
        result = provider.generate_structured(request(), response_model=Widget)
        assert result.parsed == Widget(name="widget", count=3)
        assert seen_tokens == ["Bearer bearer-1", "Bearer bearer-2"]
        assert iam_calls["n"] == 2

    def test_a_persistent_401_still_fails_as_authentication_error(self):
        def chat_handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json=_error_body("authentication_token_invalid", "nope"))

        provider = make_provider(chat_handler, retry_policy=RetryPolicy(max_retries=2, timeout_seconds=60.0))
        with pytest.raises(LLMAuthenticationError):
            provider.generate_structured(request(), response_model=Widget)

    def test_iam_token_is_fetched_once_across_many_generations(self):
        iam_calls = {"n": 0}

        def iam_handler(req: httpx.Request) -> httpx.Response:
            iam_calls["n"] += 1
            return httpx.Response(200, json={"access_token": BEARER, "expires_in": 3600})

        provider = WatsonxGraniteProvider(
            settings(),
            retry_policy=RetryPolicy(max_retries=0, timeout_seconds=60.0),
            client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=chat_ok()))),
            token_provider=IBMCloudIAMTokenProvider(
                API_KEY, client=httpx.Client(transport=httpx.MockTransport(iam_handler))),
        )
        for _ in range(4):
            provider.generate_structured(request(), response_model=Widget)
        assert iam_calls["n"] == 1


# Secret hygiene


class TestSecretHygiene:
    def test_api_key_and_bearer_never_leak_into_an_error_message(self):
        """Even an IBM error body that echoed both credentials straight
        back at us must not be able to put either into a traceback."""
        provider = make_provider(lambda req: httpx.Response(400, json=_error_body(
            "bad_request", f"received apikey={API_KEY} and Bearer {BEARER}")))
        with pytest.raises(LLMUnsupportedCapabilityError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        rendered = str(exc_info.value)
        assert API_KEY not in rendered
        assert BEARER not in rendered
        assert rendered.count("REDACTED") == 2

    def test_credentials_are_scrubbed_from_a_non_json_error_body_too(self):
        provider = make_provider(lambda req: httpx.Response(
            502, text=f"proxy log: authorization=Bearer {BEARER} apikey={API_KEY}"))
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.generate_structured(request(), response_model=Widget)
        rendered = str(exc_info.value)
        assert API_KEY not in rendered
        assert BEARER not in rendered

    def test_repr_never_renders_credentials(self):
        provider = make_provider(lambda req: httpx.Response(200, json=chat_ok()))
        assert API_KEY not in repr(provider)
        assert BEARER not in repr(provider)


# Fence stripping


class TestStripCodeFence:
    @pytest.mark.parametrize("raw,expected", [
        ('{"a":1}', '{"a":1}'),
        ('  {"a":1}  ', '{"a":1}'),
        ('```json\n{"a":1}\n```', '{"a":1}'),
        ('```\n{"a":1}\n```', '{"a":1}'),
        ('```json\n[{"a":1}]\n```', '[{"a":1}]'),
        # Unknown language tag: left alone rather than guessed at.
        ('```python\nprint(1)\n```', '```python\nprint(1)\n```'),
        # No closing fence: still de-fenced, then fails JSON parsing above.
        ('```json\n{"a":1}', '{"a":1}'),
    ])
    def test_fence_normalization(self, raw: str, expected: str):
        assert _strip_code_fence(raw) == expected
