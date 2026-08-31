"""Typed LLM provider-layer errors for Fabrivium Phase 7A."""

from __future__ import annotations


class LLMProviderError(Exception):
    """Base class for every typed provider-layer failure."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_name = provider_name
        self.model_name = model_name
        self.cause = cause


class LLMTimeoutError(LLMProviderError):
    """The provider did not respond within the configured timeout.
    Plausibly transient — retryable."""

    retryable = True


class LLMRateLimitError(LLMProviderError):
    """The provider rejected the call due to rate limiting. Plausibly
    transient — retryable."""

    retryable = True


class LLMUnavailableError(LLMProviderError):
    """Network/provider-side outage (connection refused, 5xx, DNS failure, ...)."""

    retryable = True


class LLMAuthenticationError(LLMProviderError):
    """
    Invalid/missing credentials or a configuration that can never succeed as-is (e.g.
    """

    retryable = False


class LLMMalformedResponseError(LLMProviderError):
    """
    The provider returned a response that is not valid JSON, or that fails validation
    against the requested ``response_model``.
    """

    retryable = True


class LLMUnsupportedCapabilityError(LLMProviderError):
    """The requested capability (e.g."""

    retryable = False
