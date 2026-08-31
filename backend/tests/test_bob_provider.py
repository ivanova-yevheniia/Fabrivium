"""The IBM Bob provider: what it sends, what it accepts, and what it never leaks."""

from __future__ import annotations

import json

import httpx
import pytest

from app.llm.bob_provider import DEFAULT_BASE_URL, BobProvider, BobSettings
from app.llm.errors import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.models import LLMRequest, RetryPolicy

KEY = "bob-secret-key-do-not-leak"

ENV = {
    "BOB_API_KEY": KEY,
    "FACTORYMIND_BOB_MODEL": "some/model",
}


def settings(**overrides) -> BobSettings:
    return BobSettings(api_key=KEY, model="some/model", **overrides)


def provider(handler, **overrides) -> BobProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BobProvider(settings(**overrides), client=client, retry_policy=RetryPolicy(max_retries=0))


def completion(content: str, **body) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "cmpl-1",
        "model": "some/model",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        **body,
    })


REQUEST = LLMRequest(system_prompt="Extract requirements.", user_prompt="We need 500 a day.")


# Settings


def test_reads_ibms_own_env_var_so_a_bob_cli_machine_needs_nothing_added():
    assert BobSettings.from_env(ENV).api_key == KEY


def test_a_fabrivium_specific_key_overrides_the_shared_one():
    env = {**ENV, "FACTORYMIND_BOB_API_KEY": "fabrivium-key"}
    assert BobSettings.from_env(env).api_key == "fabrivium-key"


def test_a_missing_key_is_a_typed_error_naming_the_required_scope():
    """A key with the wrong scope authenticates and then cannot infer, so
    the scope is worth saying before the first call, not after it."""
    with pytest.raises(LLMAuthenticationError) as exc:
        BobSettings.from_env({"FACTORYMIND_BOB_MODEL": "m"})
    assert "Inference" in str(exc.value)


def test_no_model_is_defaulted():
    """Bob's catalogue is account-specific."""
    with pytest.raises(LLMAuthenticationError) as exc:
        BobSettings.from_env({"BOB_API_KEY": KEY})
    assert "bob_smoke" in str(exc.value)


def test_the_endpoint_is_the_resolved_contract():
    resolved = BobSettings.from_env(ENV)
    assert resolved.base_url == DEFAULT_BASE_URL
    assert resolved.chat_endpoint == f"{DEFAULT_BASE_URL}/chat/completions"
    assert resolved.model_info_endpoint == f"{DEFAULT_BASE_URL}/model/info"


def test_the_auth_scheme_is_configurable_because_it_is_single_sourced():
    assert BobSettings.from_env(ENV).auth_scheme == "Apikey"
    assert BobSettings.from_env({**ENV, "FACTORYMIND_BOB_AUTH_SCHEME": "Bearer"}).auth_scheme == "Bearer"


def test_an_unknown_auth_scheme_fails_rather_than_being_sent():
    with pytest.raises(LLMAuthenticationError):
        BobSettings.from_env({**ENV, "FACTORYMIND_BOB_AUTH_SCHEME": "Basic"})


def test_repr_never_renders_the_key():
    assert KEY not in repr(BobSettings.from_env(ENV))
    assert "<redacted>" in repr(BobSettings.from_env(ENV))


# The request


def test_sends_an_openai_shaped_chat_completion_with_the_apikey_scheme():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return completion('{"ok": true}')

    provider(handler).generate_structured(REQUEST)

    assert seen["url"] == f"{DEFAULT_BASE_URL}/chat/completions"
    assert seen["auth"] == f"Apikey {KEY}"
    assert seen["body"]["model"] == "some/model"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert seen["body"]["temperature"] == 0.0
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_json_mode_can_be_turned_off_for_a_model_that_rejects_the_parameter():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return completion('{"ok": true}')

    provider(handler, json_mode=False).generate_structured(REQUEST)
    assert "response_format" not in seen["body"]


def test_routing_headers_are_sent_only_when_configured():
    """An empty string is a real (invalid) value to some gateways, so an
    unset team id must be absent rather than blank."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        return completion('{"ok": true}')

    provider(handler).generate_structured(REQUEST)
    assert "x-bob-team-id" not in seen["headers"]

    provider(handler, team_id="team-9").generate_structured(REQUEST)
    assert seen["headers"]["x-bob-team-id"] == "team-9"


def test_the_target_schema_travels_in_the_system_message():
    """A model that has never seen Fabrivium's field names invents its own,
    so naming a schema is not the same as showing it."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return completion('{"ok": true}')

    schema = {"type": "object", "properties": {"target_units_per_day": {"type": "number"}}}
    provider(handler).generate_structured(
        LLMRequest(system_prompt="Extract.", user_prompt="500 a day.", response_schema=schema)
    )
    assert "target_units_per_day" in seen["body"]["messages"][0]["content"]


# The response


def test_returns_validated_content_and_the_usage_the_account_was_billed_for():
    result = provider(lambda r: completion('{"target": 500}')).generate_structured(REQUEST)
    assert result.parsed == {"target": 500}
    assert result.response.usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert result.response.request_id == "cmpl-1"
    assert result.response.provider_name == "bob"


def test_reports_the_model_that_answered_not_the_one_asked_for():
    """Provenance must name what actually answered; an account may alias."""
    def handler(request: httpx.Request) -> httpx.Response:
        return completion('{"ok": true}', model="some/model-v2-actual")

    result = provider(handler).generate_structured(REQUEST)
    assert result.response.model_name == "some/model-v2-actual"


def test_a_fenced_response_is_normalised_not_rescued():
    result = provider(lambda r: completion('```json\n{"target": 500}\n```')).generate_structured(REQUEST)
    assert result.parsed == {"target": 500}


def test_truncated_output_is_rejected_even_though_it_parses():
    """`length` means fields are missing, and missing fields in valid JSON
    is the failure mode that would otherwise pass silently."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "x", "model": "some/model",
            "choices": [{"finish_reason": "length", "message": {"content": '{"target": 500}'}}],
        })

    with pytest.raises(LLMMalformedResponseError) as exc:
        provider(handler).generate_structured(REQUEST)
    assert "truncated" in str(exc.value)


def test_a_refusal_becomes_a_malformed_response_rather_than_a_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "x", "model": "some/model",
            "choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "I cannot."}}],
        })

    with pytest.raises(LLMMalformedResponseError) as exc:
        provider(handler).generate_structured(REQUEST)
    assert "refusal" in str(exc.value)


def test_prose_instead_of_json_fails_closed():
    with pytest.raises(LLMMalformedResponseError):
        provider(lambda r: completion("Sure! Here is what I found.")).generate_structured(REQUEST)


@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": "not-a-list"},
    {},
])
def test_a_response_without_a_usable_choice_is_malformed(body):
    with pytest.raises(LLMMalformedResponseError):
        provider(lambda r: httpx.Response(200, json=body)).generate_structured(REQUEST)


# Errors


@pytest.mark.parametrize("status,expected", [
    (401, LLMAuthenticationError),
    (403, LLMAuthenticationError),
    (429, LLMRateLimitError),
    (408, LLMTimeoutError),
    (504, LLMTimeoutError),
    (500, LLMUnavailableError),
    (503, LLMUnavailableError),
    (400, LLMUnsupportedCapabilityError),
    (404, LLMUnsupportedCapabilityError),
    (422, LLMUnsupportedCapabilityError),
])
def test_http_status_maps_onto_the_existing_taxonomy(status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "nope"}})

    with pytest.raises(expected):
        provider(handler).generate_structured(REQUEST)


def test_a_403_names_the_scope_because_that_is_the_likely_cause():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "forbidden"}})

    with pytest.raises(LLMAuthenticationError) as exc:
        provider(handler).generate_structured(REQUEST)
    assert "Inference" in str(exc.value)


def test_auth_failure_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMAuthenticationError):
        BobProvider(settings(), client=client, retry_policy=RetryPolicy(max_retries=3)).generate_structured(REQUEST)
    assert calls["n"] == 1, "a bad key fails identically on every retry"


def test_a_transient_failure_is_retried_and_bounded():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": {"message": "down"}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailableError):
        BobProvider(settings(), client=client, retry_policy=RetryPolicy(max_retries=2)).generate_structured(REQUEST)
    assert calls["n"] == 3, "one attempt plus two retries, never unbounded"


def test_a_timeout_is_typed_not_a_raw_httpx_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(LLMTimeoutError):
        provider(handler).generate_structured(REQUEST)


def test_an_unreachable_host_is_typed():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMUnavailableError):
        provider(handler).generate_structured(REQUEST)


# The key never leaves


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
def test_an_error_body_that_echoes_the_key_is_redacted(status):
    """A gateway echoing a request header into its error response is not
    hypothetical, and an exception message is the one place a secret
    reliably reaches a log."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"rejected token {KEY}"}})

    with pytest.raises(Exception) as exc:
        provider(handler).generate_structured(REQUEST)
    assert KEY not in str(exc.value)
    assert "<redacted>" in str(exc.value)


def test_a_non_json_error_body_is_also_redacted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"upstream said {KEY} is bad")

    with pytest.raises(Exception) as exc:
        provider(handler).generate_structured(REQUEST)
    assert KEY not in str(exc.value)


def test_the_provider_repr_never_renders_the_key():
    assert KEY not in repr(provider(lambda r: completion("{}")))


# Wiring


def test_build_provider_constructs_bob_from_settings():
    from app.llm import build_provider
    from app.llm.config import load_llm_settings

    env = {**ENV, "FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "bob"}
    built = build_provider(load_llm_settings(env), env)
    assert built is not None
    assert built.provider_name == "bob"
    assert built.model_name == "some/model"


def test_the_generic_model_override_reaches_bob():
    from app.llm import build_provider
    from app.llm.config import load_llm_settings

    env = {
        **ENV,
        "FACTORYMIND_LLM_ENABLED": "true",
        "FACTORYMIND_LLM_PROVIDER": "bob",
        "FACTORYMIND_LLM_MODEL": "override/model",
    }
    assert build_provider(load_llm_settings(env), env).model_name == "override/model"


def test_bob_is_disabled_like_every_other_provider_when_llm_is_off():
    from app.llm import build_provider
    from app.llm.config import load_llm_settings

    env = {**ENV, "FACTORYMIND_LLM_ENABLED": "false", "FACTORYMIND_LLM_PROVIDER": "bob"}
    assert build_provider(load_llm_settings(env), env) is None
