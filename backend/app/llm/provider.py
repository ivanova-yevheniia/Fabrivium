"""Generic LLM provider contract for Fabrivium Phase 7A."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.llm.errors import LLMMalformedResponseError, LLMProviderError
from app.llm.models import LLMInvocationResult, LLMRequest, LLMResponse, RetryPolicy

T = TypeVar("T")


class LLMProvider(ABC):
    """Common interface for every LLM transport backend."""

    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self._retry_policy = retry_policy or RetryPolicy()

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable machine-readable name, e.g. 'mock', 'watsonx'."""
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The concrete model identifier in use, e.g. 'mock-echo-v1'."""
        raise NotImplementedError

    @abstractmethod
    def _generate_raw(self, request: LLMRequest) -> LLMResponse:
        """Provider-specific transport call."""
        raise NotImplementedError

    def generate_structured(
        self,
        request: LLMRequest,
        response_model: type[T] | None = None,
    ) -> LLMInvocationResult:
        """
        Call ``_generate_raw`` with bounded retry (Phase 7A section 5), then
        parse/validate the result.
        """
        last_error: LLMProviderError | None = None
        attempts_made = 0

        for attempt in range(self._retry_policy.max_retries + 1):
            attempts_made = attempt + 1
            try:
                raw = self._generate_raw(request)
            except LLMProviderError as exc:
                last_error = exc
                if exc.retryable and attempt < self._retry_policy.max_retries:
                    continue
                raise

            try:
                data = raw.parsed if raw.parsed is not None else json.loads(raw.raw_text)
                parsed = _validate(data, response_model)
            except (ValidationError, ValueError, TypeError) as exc:
                last_error = LLMMalformedResponseError(
                    f"Structured output failed validation"
                    f"{f' against {response_model!r}' if response_model is not None else ''}: {exc}",
                    provider_name=self.provider_name,
                    model_name=self.model_name,
                )
                if attempt < self._retry_policy.max_retries:
                    continue
                raise last_error from exc
            else:
                return LLMInvocationResult(parsed=parsed, response=raw, attempts=attempts_made)

        # Unreachable in practice (every loop iteration either returns or
        # raises), but keeps this function's control flow explicit rather
        # than relying on the loop's last statement.
        assert last_error is not None
        raise last_error


def _validate(data: Any, response_model: type[T] | None) -> Any:
    if response_model is None:
        return data
    if isinstance(response_model, type) and issubclass(response_model, BaseModel):
        return response_model.model_validate(data)
    return TypeAdapter(response_model).validate_python(data)
