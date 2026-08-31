"""Phase 7A tests — generic LLM provider foundation."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.llm import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMRequest,
    LLMTimeoutError,
    LLMUnavailableError,
    MockLLMProvider,
    MockOutcome,
    RetryPolicy,
    build_provider,
    load_llm_settings,
)


class Widget(BaseModel):
    name: str
    count: int


def request() -> LLMRequest:
    return LLMRequest(system_prompt="s", user_prompt="u")


# 1-6: PROVIDER


class TestProvider:
    def test_1_valid_structured_output(self):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({"name": "widget", "count": 3})])
        result = provider.generate_structured(request(), response_model=Widget)
        assert result.parsed == Widget(name="widget", count=3)
        assert result.attempts == 1
        assert result.response.provider_name == "mock"

    def test_2_malformed_output_raises_typed_error(self):
        provider = MockLLMProvider(outcomes=[MockOutcome.malformed("not json {")], retry_policy=RetryPolicy(max_retries=0))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    def test_2b_valid_json_wrong_shape_also_raises_malformed(self):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok({"totally": "unrelated"})], retry_policy=RetryPolicy(max_retries=0))
        with pytest.raises(LLMMalformedResponseError):
            provider.generate_structured(request(), response_model=Widget)

    def test_3_timeout_is_typed_and_retryable(self):
        assert LLMTimeoutError.retryable is True
        provider = MockLLMProvider(outcomes=[MockOutcome.timeout()], retry_policy=RetryPolicy(max_retries=0))
        with pytest.raises(LLMTimeoutError):
            provider.generate_structured(request(), response_model=Widget)

    def test_4_transient_failure_then_successful_retry(self):
        provider = MockLLMProvider(
            outcomes=[MockOutcome.failure(LLMUnavailableError("blip")), MockOutcome.ok({"name": "ok", "count": 1})],
            retry_policy=RetryPolicy(max_retries=2),
        )
        result = provider.generate_structured(request(), response_model=Widget)
        assert result.parsed == Widget(name="ok", count=1)
        assert result.attempts == 2
        assert len(provider.calls) == 2

    def test_5_retry_exhaustion_raises_after_max_retries(self):
        provider = MockLLMProvider(
            outcomes=[MockOutcome.timeout(), MockOutcome.timeout(), MockOutcome.timeout()],
            retry_policy=RetryPolicy(max_retries=2),
        )
        with pytest.raises(LLMTimeoutError):
            provider.generate_structured(request(), response_model=Widget)
        assert len(provider.calls) == 3  # 1 initial + 2 retries, never more

    def test_6_authentication_failure_never_retried(self):
        provider = MockLLMProvider(
            outcomes=[MockOutcome.failure(LLMAuthenticationError("bad key")), MockOutcome.ok({"name": "x", "count": 1})],
            retry_policy=RetryPolicy(max_retries=5),
        )
        with pytest.raises(LLMAuthenticationError):
            provider.generate_structured(request(), response_model=Widget)
        assert len(provider.calls) == 1  # never retried, despite max_retries=5


# Retry policy / config sanity (supporting coverage, not in the numbered list
# but directly exercises Phase 7A section 5/11's explicit requirements)


class TestRetryPolicyAndConfig:
    def test_retry_policy_rejects_negative_max_retries(self):
        with pytest.raises(ValueError):
            RetryPolicy(max_retries=-1)

    def test_retry_policy_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            RetryPolicy(timeout_seconds=0)

    def test_default_settings_disabled_with_no_env(self):
        settings = load_llm_settings(env={})
        assert settings.enabled is False
        assert build_provider(settings) is None

    def test_enabled_mock_provider_constructs(self):
        settings = load_llm_settings(env={"FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "mock"})
        provider = build_provider(settings)
        assert provider is not None
        assert provider.provider_name == "mock"

    def test_unsupported_provider_fails_loudly_not_silently(self):
        # "watsonx" was the example here in Phase 7A, when it was the
        # canonical NOT-YET-IMPLEMENTED provider. Phase 7B implements it
        # for real (see test_phase7b_watsonx_provider.py), so the
        # fails-loudly guarantee is now demonstrated with a provider that
        # genuinely does not exist.
        settings = load_llm_settings(env={"FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "openai"})
        with pytest.raises(LLMAuthenticationError):
            build_provider(settings)

    def test_env_vars_drive_timeout_and_retries(self):
        settings = load_llm_settings(env={
            "FACTORYMIND_LLM_ENABLED": "true", "FACTORYMIND_LLM_PROVIDER": "mock",
            "FACTORYMIND_LLM_TIMEOUT_SECONDS": "5", "FACTORYMIND_LLM_MAX_RETRIES": "0",
        })
        assert settings.timeout_seconds == 5.0
        assert settings.max_retries == 0

    def test_no_outcomes_and_no_default_factory_raises_assertion_not_network_call(self):
        provider = MockLLMProvider()
        with pytest.raises(AssertionError):
            provider.generate_structured(request(), response_model=Widget)

    def test_default_factory_used_once_outcomes_exhausted(self):
        provider = MockLLMProvider(
            outcomes=[MockOutcome.ok({"name": "first", "count": 1})],
            default_factory=lambda req: {"name": "computed", "count": 2},
        )
        first = provider.generate_structured(request(), response_model=Widget)
        second = provider.generate_structured(request(), response_model=Widget)
        assert first.parsed.name == "first"
        assert second.parsed.name == "computed"

    def test_generate_structured_with_response_model_none_returns_raw_json(self):
        provider = MockLLMProvider(outcomes=[MockOutcome.ok([{"a": 1}, {"b": 2}])])
        result = provider.generate_structured(request(), response_model=None)
        assert result.parsed == [{"a": 1}, {"b": 2}]
