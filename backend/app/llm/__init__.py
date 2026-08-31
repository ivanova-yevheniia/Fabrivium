"""Fabrivium Phase 7A/7B — generic runtime LLM provider foundation."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from app.llm.config import (
    DEFAULT_DOTENV_PATH,
    LLMSettings,
    SUPPORTED_PROVIDERS,
    load_dotenv_file,
    load_llm_settings,
)
from app.llm.errors import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.mock_provider import MockLLMProvider, MockOutcome
from app.llm.models import LLMInvocationRecord, LLMInvocationResult, LLMRequest, LLMResponse, RetryPolicy
from app.llm.provider import LLMProvider

__all__ = [
    "DEFAULT_DOTENV_PATH",
    "IBMCloudIAMTokenProvider",
    "LLMAuthenticationError",
    "LLMInvocationRecord",
    "LLMInvocationResult",
    "LLMMalformedResponseError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMRequest",
    "LLMResponse",
    "LLMSettings",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "LLMUnsupportedCapabilityError",
    "MockLLMProvider",
    "MockOutcome",
    "RetryPolicy",
    "SUPPORTED_PROVIDERS",
    "WatsonxGraniteProvider",
    "WatsonxSettings",
    "build_provider",
    "load_dotenv_file",
    "load_llm_settings",
]


def __getattr__(name: str):
    """Lazily expose the Phase 7B watsonx names at package level without
    importing the real transport module (and its ``httpx`` client) for
    every consumer of the Phase 7A mock path."""
    if name in ("WatsonxGraniteProvider", "WatsonxSettings"):
        from app.llm import watsonx_provider

        return getattr(watsonx_provider, name)
    if name == "IBMCloudIAMTokenProvider":
        from app.llm.iam import IBMCloudIAMTokenProvider

        return IBMCloudIAMTokenProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def build_provider(settings: LLMSettings, env: Mapping[str, str] | None = None) -> LLMProvider | None:
    """
    Construct the ``LLMProvider`` described by *settings*, or ``None`` if LLM mode is
    disabled — the single place that decides "is there a provider at all" for callers
    like ``app.main`` (Phase 7A section 11).
    """
    if not settings.enabled:
        return None

    if settings.provider == "watsonx":
        # Imported lazily so the Phase 7A mock/deterministic paths never
        # pay for (or depend on) the real provider's transport module.
        from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings

        watsonx_settings = WatsonxSettings.from_env(env)
        if settings.model:
            # FACTORYMIND_LLM_MODEL, if set, overrides the watsonx-specific
            # model id — one generic knob that works across providers.
            watsonx_settings = replace(watsonx_settings, model_id=settings.model)
        return WatsonxGraniteProvider(
            watsonx_settings,
            retry_policy=RetryPolicy(max_retries=settings.max_retries, timeout_seconds=settings.timeout_seconds),
        )

    if settings.provider == "bob":
        # Lazily imported for the same reason watsonx is: the mock and
        # deterministic paths never pay for a transport module.
        from app.llm.bob_provider import BobProvider, BobSettings

        bob_settings = BobSettings.from_env(env)
        if settings.model:
            # FACTORYMIND_LLM_MODEL, if set, overrides the Bob-specific
            # model id — one generic knob that works across providers.
            bob_settings = replace(bob_settings, model=settings.model)
        return BobProvider(
            bob_settings,
            retry_policy=RetryPolicy(max_retries=settings.max_retries, timeout_seconds=settings.timeout_seconds),
        )

    if settings.provider == "mock":
        retry_policy = RetryPolicy(max_retries=settings.max_retries, timeout_seconds=settings.timeout_seconds)

        def _no_scripted_response(_request) -> dict:
            # The zero-config mock has no real language understanding — it
            # exists for SCRIPTED tests/demos (construct your own
            # MockLLMProvider(outcomes=[...]) for those), not to guess at
            # arbitrary user text. Raising a typed, retryable-false error
            # here (rather than the bare AssertionError a raw unconfigured
            # MockLLMProvider() gives — see mock_provider.py — which is
            # reserved for catching a genuinely-misused test double) means
            # every real request safely, honestly falls back to the
            # deterministic backend instead of crashing the endpoint —
            # itself a legitimate, demonstrable "provider unavailable"
            # scenario (Phase 7A section 18's failure-mode demo).
            raise LLMUnsupportedCapabilityError(
                "The built-in zero-config mock provider has no scripted response for this "
                "call — it cannot interpret arbitrary language. Falling back to the "
                "deterministic backend.",
                provider_name="mock", model_name=settings.model or "mock-echo-v1",
            )

        return MockLLMProvider(
            model_name=settings.model or "mock-echo-v1",
            retry_policy=retry_policy,
            default_factory=_no_scripted_response,
        )

    raise LLMAuthenticationError(
        f"FACTORYMIND_LLM_PROVIDER={settings.provider!r} is not a provider Fabrivium implements "
        f"(supported: {sorted(SUPPORTED_PROVIDERS)}). Set FACTORYMIND_LLM_ENABLED=false to run "
        f"without an LLM, or FACTORYMIND_LLM_PROVIDER=mock for the built-in test/demo provider."
    )
