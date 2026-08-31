"""Generic LLM request/response/audit models for Fabrivium Phase 7A."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

# Request / response


class LLMRequest(BaseModel):
    """One structured-generation request."""

    model_config = {"frozen": True}

    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any] | None = Field(
        None, description="JSON-schema hint for the target structure, if the provider can use one (e.g. function-calling/schema-constrained decoding)."
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0)
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Caller-supplied context for observability only (e.g. {'agent': 'requirements'}) — never sent to a real provider as part of the prompt.",
    )


class LLMResponse(BaseModel):
    """One raw provider response, BEFORE ``response_model`` validation."""

    model_config = {"frozen": True}

    raw_text: str
    parsed: Any | None = None
    provider_name: str
    model_name: str
    latency_ms: float = Field(..., ge=0.0)
    usage: dict[str, int] | None = Field(None, description="e.g. {'prompt_tokens': .., 'completion_tokens': ..} — omitted if the provider doesn't report it.")
    request_id: str | None = None


# Retry policy


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded, deterministic retry policy (Phase 7A section 5)."""

    max_retries: int = 2
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")


# Invocation result / audit record (Phase 7A section 12)


@dataclass(frozen=True)
class LLMInvocationResult:
    """
    Result of one successful ``generate_structured`` call — the parsed/ validated value
    plus enough metadata for an audit record.
    """

    parsed: Any
    response: LLMResponse
    attempts: int


class LLMInvocationRecord(BaseModel):
    """
    One audit-log entry for a single ``generate_structured`` call (Phase 7A section 12).
    """

    model_config = {"frozen": True}

    agent: str = Field(..., description="Which agent invoked the provider, e.g. 'requirements' | 'planning' | 'explanation'.")
    provider_name: str
    model_name: str
    success: bool
    attempts: int = Field(..., ge=0)
    latency_ms: float = Field(..., ge=0.0)
    fallback_used: bool
    validation_passed: bool | None = Field(
        None, description="None when not applicable (e.g. the call failed before any structured-output validation was attempted)."
    )
    error_type: str | None = Field(None, description="The failing app.llm.errors class name, if any — never a raw provider exception message.")

    # Phase 7B cost observability A real provider (IBM watsonx.ai) bills per token, so
    # consumption is worth recording.
    prompt_tokens: int | None = Field(None, ge=0)
    completion_tokens: int | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, ge=0)
    request_id: str | None = Field(
        None, description="The provider's own request/completion id, for correlating with provider-side logs."
    )
