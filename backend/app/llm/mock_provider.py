"""MockLLMProvider for Fabrivium Phase 7A."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Literal

from app.llm.errors import LLMProviderError, LLMTimeoutError, LLMUnavailableError
from app.llm.models import LLMRequest, LLMResponse
from app.llm.provider import LLMProvider

OutcomeKind = Literal["ok", "malformed", "timeout", "failure"]


@dataclass(frozen=True)
class MockOutcome:
    """One scripted response for a single ``MockLLMProvider`` call."""

    kind: OutcomeKind
    payload: dict | list | None = None
    raw_text: str | None = None
    error: LLMProviderError | None = None

    @classmethod
    def ok(cls, payload: dict | list) -> "MockOutcome":
        """A. Valid structured response."""
        return cls(kind="ok", payload=payload)

    @classmethod
    def malformed(cls, raw_text: str = "not json {") -> "MockOutcome":
        """B."""
        return cls(kind="malformed", raw_text=raw_text)

    @classmethod
    def timeout(cls) -> "MockOutcome":
        """C. Timeout."""
        return cls(kind="timeout")

    @classmethod
    def failure(cls, error: LLMProviderError | None = None) -> "MockOutcome":
        """D. Provider failure (network/unavailable by default)."""
        return cls(kind="failure", error=error)


class MockLLMProvider(LLMProvider):
    """Scripted, network-free ``LLMProvider`` for tests and demos."""

    def __init__(
        self,
        outcomes: list[MockOutcome] | None = None,
        *,
        default_factory: Callable[[LLMRequest], dict | list] | None = None,
        provider_name: str = "mock",
        model_name: str = "mock-echo-v1",
        retry_policy=None,
    ) -> None:
        super().__init__(retry_policy=retry_policy)
        self._outcomes: list[MockOutcome] = list(outcomes or [])
        self._default_factory = default_factory
        self._provider_name = provider_name
        self._model_name = model_name
        self.calls: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def _next_outcome(self, request: LLMRequest) -> MockOutcome:
        if self._outcomes:
            outcome = self._outcomes.pop(0)
            self._last_outcome = outcome
            return outcome
        if self._default_factory is not None:
            return MockOutcome.ok(self._default_factory(request))
        if hasattr(self, "_last_outcome"):
            return self._last_outcome
        raise AssertionError(
            "MockLLMProvider called with no outcomes queued and no default_factory set — "
            "construct it with outcomes=[...] or default_factory=..."
        )

    def _generate_raw(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        outcome = self._next_outcome(request)

        if outcome.kind == "timeout":
            raise LLMTimeoutError(
                f"Mock provider simulated a timeout after {self._retry_policy.timeout_seconds}s.",
                provider_name=self._provider_name, model_name=self._model_name,
            )
        if outcome.kind == "failure":
            error = outcome.error or LLMUnavailableError(
                "Mock provider simulated an unavailable/network failure.",
                provider_name=self._provider_name, model_name=self._model_name,
            )
            raise error
        if outcome.kind == "malformed":
            # Returned as a normal (transport-successful) response — the
            # malformed-ness is discovered by generate_structured's own
            # JSON-parse/validation step, exactly like a real provider
            # that transports fine but emits bad content.
            return LLMResponse(
                raw_text=outcome.raw_text or "not json {",
                parsed=None,
                provider_name=self._provider_name,
                model_name=self._model_name,
                latency_ms=1.0,
            )
        # kind == "ok"
        return LLMResponse(
            raw_text=json.dumps(outcome.payload),
            parsed=outcome.payload,
            provider_name=self._provider_name,
            model_name=self._model_name,
            latency_ms=1.0,
        )
