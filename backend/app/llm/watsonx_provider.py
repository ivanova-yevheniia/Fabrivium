"""IBM watsonx.ai / Granite provider for Fabrivium """

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from app.llm.errors import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    LLMUnsupportedCapabilityError,
)
from app.llm.iam import DEFAULT_IAM_URL, IBMCloudIAMTokenProvider
from app.llm.models import LLMRequest, LLMResponse, RetryPolicy
from app.llm.provider import LLMProvider

# watsonx.ai's date-based API version.
DEFAULT_API_VERSION = "2023-10-25"

DEFAULT_MODEL_ID = "ibm/granite-4-h-small"
DEFAULT_MAX_TOKENS = 2000

#: Finish reasons that mean the returned text is TRUNCATED or aborted, so
#: whatever JSON it contains cannot be trusted even if it happens to
#: parse. Treated as a malformed response (retryable, bounded) rather than
#: silently used.
_INCOMPLETE_FINISH_REASONS = frozenset({"length", "time_limit", "error", "cancelled"})

_JSON_MODES = frozenset({"text", "json_object", "json_schema"})


# Settings


@dataclass(frozen=True)
class WatsonxSettings:
    """watsonx-specific configuration."""

    url: str
    project_id: str
    api_key: str
    model_id: str = DEFAULT_MODEL_ID
    api_version: str = DEFAULT_API_VERSION
    iam_url: str = DEFAULT_IAM_URL
    max_tokens: int = DEFAULT_MAX_TOKENS
    # "json_object" (default), "json_schema", or "text" (no JSON mode).
    json_mode: str = "json_object"
    space_id: str | None = None

    def __post_init__(self) -> None:
        if self.json_mode not in _JSON_MODES:
            raise LLMAuthenticationError(
                f"FACTORYMIND_WATSONX_JSON_MODE={self.json_mode!r} is not one of "
                f"{sorted(_JSON_MODES)}."
            )

    @property
    def chat_endpoint(self) -> str:
        return f"{self.url.rstrip('/')}/ml/v1/text/chat?version={self.api_version}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "WatsonxSettings":
        """Build settings from ``FACTORYMIND_WATSONX_*`` environment variables."""
        source = env if env is not None else os.environ

        def _required(name: str) -> str:
            value = (source.get(name) or "").strip()
            if not value:
                raise LLMAuthenticationError(
                    f"{name} is not set. The watsonx provider needs FACTORYMIND_WATSONX_URL, "
                    f"FACTORYMIND_WATSONX_PROJECT_ID and FACTORYMIND_WATSONX_API_KEY (put the "
                    f"API key in the backend's local .env — never commit it)."
                )
            return value

        raw_max_tokens = (source.get("FACTORYMIND_WATSONX_MAX_TOKENS") or "").strip()
        try:
            max_tokens = int(raw_max_tokens) if raw_max_tokens else DEFAULT_MAX_TOKENS
        except ValueError as exc:
            raise LLMAuthenticationError(
                f"FACTORYMIND_WATSONX_MAX_TOKENS={raw_max_tokens!r} is not an integer."
            ) from exc

        return cls(
            url=_required("FACTORYMIND_WATSONX_URL"),
            project_id=_required("FACTORYMIND_WATSONX_PROJECT_ID"),
            api_key=_required("FACTORYMIND_WATSONX_API_KEY"),
            model_id=(source.get("FACTORYMIND_WATSONX_MODEL_ID") or DEFAULT_MODEL_ID).strip(),
            api_version=(source.get("FACTORYMIND_WATSONX_API_VERSION") or DEFAULT_API_VERSION).strip(),
            iam_url=(source.get("FACTORYMIND_WATSONX_IAM_URL") or DEFAULT_IAM_URL).strip(),
            max_tokens=max_tokens,
            json_mode=(source.get("FACTORYMIND_WATSONX_JSON_MODE") or "json_object").strip().lower(),
            space_id=(source.get("FACTORYMIND_WATSONX_SPACE_ID") or None),
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        # Never renders api_key.
        return (
            f"WatsonxSettings(url={self.url!r}, project_id={self.project_id!r}, "
            f"model_id={self.model_id!r}, api_version={self.api_version!r}, "
            f"json_mode={self.json_mode!r}, api_key=<redacted>)"
        )


# Provider


class WatsonxGraniteProvider(LLMProvider):
    """Real IBM watsonx.ai chat provider (Granite family by default)."""

    def __init__(
        self,
        settings: WatsonxSettings,
        *,
        retry_policy: RetryPolicy | None = None,
        client: httpx.Client | None = None,
        token_provider: IBMCloudIAMTokenProvider | None = None,
    ) -> None:
        super().__init__(retry_policy=retry_policy)
        self._settings = settings
        self._client = client
        self._owns_client = client is None
        self._token_provider = token_provider or IBMCloudIAMTokenProvider(
            settings.api_key,
            iam_url=settings.iam_url,
            timeout_seconds=self._retry_policy.timeout_seconds,
            client=client,
        )

    # LLMProvider contract

    @property
    def provider_name(self) -> str:
        return "watsonx"

    @property
    def model_name(self) -> str:
        return self._settings.model_id

    def _generate_raw(self, request: LLMRequest) -> LLMResponse:
        """One watsonx.ai chat completion."""
        body = self._build_payload(request)
        started = time.monotonic()

        response = self._post(body, token=self._token_provider.get_token())
        if response.status_code == 401:
            self._token_provider.invalidate()
            response = self._post(body, token=self._token_provider.get_token(force_refresh=True))

        latency_ms = (time.monotonic() - started) * 1000.0

        if response.status_code >= 400:
            raise self._map_error(response)

        return self._parse_response(response, latency_ms=latency_ms)

    def close(self) -> None:
        """Release the owned HTTP client and IAM client, if any."""
        self._token_provider.close()
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<WatsonxGraniteProvider model={self._settings.model_id!r} url={self._settings.url!r}>"

    # Request construction

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._retry_policy.timeout_seconds)
        return self._client

    def _post(self, body: dict[str, Any], *, token: str) -> httpx.Response:
        try:
            return self._http().post(
                self._settings.chat_endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=body,
                timeout=self._retry_policy.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"watsonx.ai did not respond within {self._retry_policy.timeout_seconds}s.",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Could not reach watsonx.ai ({type(exc).__name__}).",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Translate the generic ``LLMRequest`` into watsonx.ai's chat payload."""
        settings = self._settings

        payload: dict[str, Any] = {
            "model_id": settings.model_id,
            "messages": [
                {"role": "system", "content": _system_content(request)},
                {"role": "user", "content": [{"type": "text", "text": request.user_prompt}]},
            ],
            "max_tokens": request.max_tokens or settings.max_tokens,
            "temperature": request.temperature,
            "top_p": 1,
            "frequency_penalty": 0,
            "presence_penalty": 0,
            # Server-side generation budget, in MILLISECONDS.
            "time_limit": max(1000, int((self._retry_policy.timeout_seconds - 2.0) * 1000)),
        }

        # A watsonx.ai request is scoped by EITHER a project or a
        # deployment space, never both.
        if settings.space_id:
            payload["space_id"] = settings.space_id
        else:
            payload["project_id"] = settings.project_id

        response_format = self._response_format(request)
        if response_format is not None:
            payload["response_format"] = response_format

        return payload

    def _response_format(self, request: LLMRequest) -> dict[str, Any] | None:
        """Pick watsonx.ai's native JSON mode for this request."""
        mode = self._settings.json_mode
        if mode == "text":
            return None

        schema = request.response_schema
        if isinstance(schema, dict) and schema.get("type") == "array":
            return None

        if mode == "json_schema" and isinstance(schema, dict):
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": str(request.metadata.get("agent", "factorymind_response")),
                    "schema": schema,
                    "strict": False,
                },
            }

        return {"type": "json_object"}

    # Response handling

    def _parse_response(self, response: httpx.Response, *, latency_ms: float) -> LLMResponse:
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMMalformedResponseError(
                "watsonx.ai returned a non-JSON body for a successful chat request.",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc

        if not isinstance(body, dict):
            raise LLMMalformedResponseError(
                f"watsonx.ai returned a {type(body).__name__} where a chat-completion object was expected.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMMalformedResponseError(
                "watsonx.ai chat response contained no usable 'choices' entry.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason in _INCOMPLETE_FINISH_REASONS:
            raise LLMMalformedResponseError(
                f"watsonx.ai stopped generating early (finish_reason={finish_reason!r}); the "
                f"output is truncated and cannot be trusted as structured data.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        # The chat API types ``content`` as a nullable string, but a model
        # that refuses returns ``refusal`` instead — surface that as a
        # malformed (retryable, then falls back) response rather than
        # crashing on None.
        if not isinstance(content, str) or not content.strip():
            refusal = message.get("refusal") if isinstance(message, dict) else None
            detail = f" (model refusal: {str(refusal)[:200]})" if refusal else ""
            raise LLMMalformedResponseError(
                f"watsonx.ai chat response carried no assistant text content{detail}.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        return LLMResponse(
            raw_text=_strip_code_fence(content),
            # Deliberately None: the Phase 7A base class owns JSON parsing
            # and validation. Setting ``parsed`` here would bypass its
            # single, uniformly-tested code path.
            parsed=None,
            provider_name=self.provider_name,
            model_name=str(body.get("model_id") or self.model_name),
            latency_ms=latency_ms,
            usage=_extract_usage(body.get("usage")),
            request_id=str(body["id"]) if isinstance(body.get("id"), str) else None,
        )

    def _map_error(self, response: httpx.Response) -> LLMProviderError:
        """Map an IBM HTTP error onto the Phase 7A error taxonomy."""
        status = response.status_code
        code, detail = self._error_detail(response)
        where = f"watsonx.ai chat request failed (HTTP {status}"
        where += f", code={code!r})" if code else ")"
        message = f"{where}: {detail}"

        if status in (401, 403):
            return LLMAuthenticationError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        if status == 429:
            return LLMRateLimitError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        if status in (408, 504):
            return LLMTimeoutError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        if status >= 500:
            return LLMUnavailableError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        if status in (400, 404, 422):
            # A rejected model id, an unknown project, an unsupported parameter (e.g.
            if code and any(token in code.lower() for token in ("auth", "token", "credential")):
                return LLMAuthenticationError(
                    message, provider_name=self.provider_name, model_name=self.model_name,
                )
            return LLMUnsupportedCapabilityError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        return LLMUnavailableError(
            message, provider_name=self.provider_name, model_name=self.model_name,
        )

    def _error_detail(self, response: httpx.Response) -> tuple[str, str]:
        """Extract ``(code, message)`` from IBM's ``ApiErrorResponse`` body."""
        scrub = self._token_provider.redact
        try:
            body = response.json()
        except ValueError:
            return "", scrub(response.text[:300])

        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                first = errors[0]
                code = str(first.get("code") or "")
                message = str(first.get("message") or "")
                return code, scrub(message[:300] or "(no message)")
            if body.get("message"):
                return str(body.get("code") or ""), scrub(str(body["message"])[:300])
        return "", scrub(str(body)[:300])


# Helpers


def _is_contentful_schema(schema: Any) -> bool:
    """
    True when *schema* actually describes a structure, rather than just naming a
    container type.
    """
    return isinstance(schema, dict) and bool(schema.get("properties") or schema.get("items"))


def _system_content(request: LLMRequest) -> str:
    """
    Build the system message: the caller's own prompt, plus the target JSON Schema when
    one was supplied.
    """
    schema = request.response_schema
    if not _is_contentful_schema(schema):
        return request.system_prompt

    is_array = schema.get("type") == "array"
    shape = "JSON array" if is_array else "JSON object"
    return (
        f"{request.system_prompt}\n\n"
        f"Return a single {shape} that conforms to this JSON Schema. Use exactly these "
        f"field names — do not rename them, do not add fields that are not in the schema, "
        f"and omit any optional field you are not confident about rather than guessing.\n"
        f"{json.dumps(schema, separators=(',', ':'))}"
    )


def _extract_usage(usage: Any) -> dict[str, int] | None:
    """
    Normalize watsonx.ai's ``usage`` block into ``LLMResponse.usage`` (Phase 7B section
    13 — cost observability).
    """
    if not isinstance(usage, dict):
        return None
    extracted = {
        key: int(usage[key])
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(usage.get(key), (int, float))
    }
    return extracted or None


def _strip_code_fence(text: str) -> str:
    """Strip a surrounding markdown code fence, if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    without_open = stripped[3:]
    newline = without_open.find("\n")
    if newline == -1:
        return stripped
    # Drop an optional language tag ("json") on the opening fence line.
    if without_open[:newline].strip().lower() not in ("", "json"):
        return stripped

    inner = without_open[newline + 1:]
    closing = inner.rfind("```")
    return (inner[:closing] if closing != -1 else inner).strip()
