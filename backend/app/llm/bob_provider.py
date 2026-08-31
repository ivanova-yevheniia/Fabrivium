"""IBM Bob as a runtime language provider."""

from __future__ import annotations

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
from app.llm.models import LLMRequest, LLMResponse, RetryPolicy
from app.llm.provider import LLMProvider
from app.llm.watsonx_provider import (
    _INCOMPLETE_FINISH_REASONS,
    _extract_usage,
    _strip_code_fence,
    _system_content,
)

#: Bob's inference base, as published by the integration package and
#: corroborated by IBM's own ``/inference/v1/model/info`` reference.
#: Overridable, because ``us-east`` is a region and a deployment elsewhere
#: will not be on this host.
DEFAULT_BASE_URL = "https://api.us-east.bob.ibm.com/inference/v1"

# The default authorization scheme.
DEFAULT_AUTH_SCHEME = "Apikey"

# No model id is defaulted.
_NO_DEFAULT_MODEL = ""

_AUTH_SCHEMES = frozenset({"Apikey", "Bearer"})


# Settings


@dataclass(frozen=True)
class BobSettings:
    """Bob-specific configuration, read by Bob's own construction code."""

    api_key: str
    model: str
    base_url: str = DEFAULT_BASE_URL
    auth_scheme: str = DEFAULT_AUTH_SCHEME
    max_tokens: int = 2000
    # Non-secret routing metadata some deployments require.
    team_id: str | None = None
    instance_id: str | None = None
    # Ask for a JSON object back.
    json_mode: bool = True

    def __post_init__(self) -> None:
        if self.auth_scheme not in _AUTH_SCHEMES:
            raise LLMAuthenticationError(
                f"FACTORYMIND_BOB_AUTH_SCHEME={self.auth_scheme!r} is not one of "
                f"{sorted(_AUTH_SCHEMES)}. Bob uses 'Apikey' for an API key and "
                f"'Bearer' for an SSO-issued token."
            )

    @property
    def chat_endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def model_info_endpoint(self) -> str:
        """Bob's model catalogue."""
        return f"{self.base_url.rstrip('/')}/model/info"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BobSettings":
        """Build settings from the environment."""
        source = env if env is not None else os.environ

        api_key = (
            source.get("FACTORYMIND_BOB_API_KEY") or source.get("BOB_API_KEY") or ""
        ).strip()
        if not api_key:
            raise LLMAuthenticationError(
                "No Bob API key. Set BOB_API_KEY (or FACTORYMIND_BOB_API_KEY) in the "
                "backend's local .env — never commit it. The key must have been created "
                "in the Bob portal with its Scope set to 'Inference'; a key with any "
                "other scope authenticates and then cannot infer."
            )

        model = (source.get("FACTORYMIND_BOB_MODEL") or _NO_DEFAULT_MODEL).strip()
        if not model:
            raise LLMAuthenticationError(
                "FACTORYMIND_BOB_MODEL is not set and has no default. Bob's model "
                "catalogue is account-specific — run `python -m scripts.bob_smoke` to "
                "list the models this account can actually reach, then name one. "
                "Defaulting to a guessed model id would fail confusingly on an account "
                "that does not have it."
            )

        raw_max_tokens = (source.get("FACTORYMIND_BOB_MAX_TOKENS") or "").strip()
        try:
            max_tokens = int(raw_max_tokens) if raw_max_tokens else 2000
        except ValueError as exc:
            raise LLMAuthenticationError(
                f"FACTORYMIND_BOB_MAX_TOKENS={raw_max_tokens!r} is not an integer."
            ) from exc

        json_mode = (source.get("FACTORYMIND_BOB_JSON_MODE") or "true").strip().lower()

        return cls(
            api_key=api_key,
            model=model,
            base_url=(source.get("FACTORYMIND_BOB_BASE_URL") or DEFAULT_BASE_URL).strip(),
            auth_scheme=(source.get("FACTORYMIND_BOB_AUTH_SCHEME") or DEFAULT_AUTH_SCHEME).strip(),
            max_tokens=max_tokens,
            team_id=(source.get("FACTORYMIND_BOB_TEAM_ID") or "").strip() or None,
            instance_id=(source.get("FACTORYMIND_BOB_INSTANCE_ID") or "").strip() or None,
            json_mode=json_mode not in ("0", "false", "no", "off"),
        )

    def redact(self, text: str) -> str:
        """Remove the API key from *text*."""
        if not self.api_key:
            return text
        return text.replace(self.api_key, "<redacted>")

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        # Never renders api_key.
        return (
            f"BobSettings(base_url={self.base_url!r}, model={self.model!r}, "
            f"auth_scheme={self.auth_scheme!r}, team_id={self.team_id!r}, "
            f"json_mode={self.json_mode!r}, api_key=<redacted>)"
        )


# Provider


class BobProvider(LLMProvider):
    """IBM Bob, over its OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        settings: BobSettings,
        *,
        retry_policy: RetryPolicy | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(retry_policy)
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    @property
    def provider_name(self) -> str:
        return "bob"

    @property
    def model_name(self) -> str:
        return self._settings.model

    def _generate_raw(self, request: LLMRequest) -> LLMResponse:
        """One Bob chat completion."""
        body = self._build_payload(request)
        started = time.monotonic()
        response = self._post(body)
        latency_ms = (time.monotonic() - started) * 1000.0

        if response.status_code >= 400:
            raise self._map_error(response)
        return self._parse_response(response, latency_ms=latency_ms)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<BobProvider model={self._settings.model!r} base_url={self._settings.base_url!r}>"

    # Transport

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._retry_policy.timeout_seconds)
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"{self._settings.auth_scheme} {self._settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Routing metadata, sent only when a deployment supplied it.
        if self._settings.team_id:
            headers["X-Bob-Team-Id"] = self._settings.team_id
        if self._settings.instance_id:
            headers["X-Bob-Instance-Id"] = self._settings.instance_id
        return headers

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._http().post(
                self._settings.chat_endpoint,
                headers=self._headers(),
                json=body,
                timeout=self._retry_policy.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"IBM Bob did not respond within {self._retry_policy.timeout_seconds}s.",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Could not reach IBM Bob ({type(exc).__name__}).",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc

    # Request construction

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Translate the generic ``LLMRequest`` into an OpenAI-shaped body."""
        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": _system_content(request)},
                {"role": "user", "content": request.user_prompt},
            ],
            # Determinism first: the same request should give the same
            # answer wherever a model allows it.
            "temperature": request.temperature,
            "max_tokens": request.max_tokens or self._settings.max_tokens,
        }
        if self._settings.json_mode:
            # OpenAI-compatible JSON mode.
            payload["response_format"] = {"type": "json_object"}
        return payload

    # Response

    def _parse_response(self, response: httpx.Response, *, latency_ms: float) -> LLMResponse:
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMMalformedResponseError(
                "IBM Bob returned a non-JSON body for a successful chat request.",
                provider_name=self.provider_name, model_name=self.model_name, cause=exc,
            ) from exc

        if not isinstance(body, dict):
            raise LLMMalformedResponseError(
                f"IBM Bob returned a {type(body).__name__} where a chat-completion object "
                f"was expected.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMMalformedResponseError(
                "IBM Bob's chat response contained no usable 'choices' entry.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if isinstance(finish_reason, str) and finish_reason in _INCOMPLETE_FINISH_REASONS:
            # Truncated output can still parse as JSON while being missing
            # half its fields, so it is rejected on the finish reason rather
            # than on whether it happens to parse.
            raise LLMMalformedResponseError(
                f"IBM Bob stopped generating early (finish_reason={finish_reason!r}); the "
                f"output is truncated and cannot be trusted as structured data.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            refusal = message.get("refusal") if isinstance(message, dict) else None
            detail = f" (model refusal: {str(refusal)[:200]})" if refusal else ""
            raise LLMMalformedResponseError(
                f"IBM Bob's chat response carried no assistant text content{detail}.",
                provider_name=self.provider_name, model_name=self.model_name,
            )

        return LLMResponse(
            raw_text=_strip_code_fence(content),
            # None on purpose: the base class owns JSON parsing and
            # validation, and setting this would bypass its one tested path.
            parsed=None,
            provider_name=self.provider_name,
            # Report the model Bob says it used, which may differ from the
            # one asked for if the account aliases it. Provenance must name
            # what answered, not what was requested.
            model_name=str(body.get("model") or self.model_name),
            latency_ms=latency_ms,
            usage=_extract_usage(body.get("usage")),
            request_id=str(body["id"]) if isinstance(body.get("id"), str) else None,
        )

    def _map_error(self, response: httpx.Response) -> LLMProviderError:
        """Map a Bob HTTP error onto the existing error taxonomy."""
        status = response.status_code
        detail = self._error_detail(response)
        message = f"IBM Bob chat request failed (HTTP {status}): {detail}"

        if status in (401, 403):
            # Includes the specific case worth naming: a valid key whose
            # scope is not Inference authenticates and is then refused.
            return LLMAuthenticationError(
                f"{message} If the key is valid, check that its Scope is 'Inference'.",
                provider_name=self.provider_name, model_name=self.model_name,
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
            # An unknown model, an unsupported parameter, a malformed request.
            return LLMUnsupportedCapabilityError(
                message, provider_name=self.provider_name, model_name=self.model_name,
            )
        return LLMUnavailableError(
            message, provider_name=self.provider_name, model_name=self.model_name,
        )

    def _error_detail(self, response: httpx.Response) -> str:
        """A short, redacted description of an error body."""
        try:
            body = response.json()
        except ValueError:
            return self._settings.redact(response.text[:300]) or "(empty body)"

        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and error.get("message"):
                return self._settings.redact(str(error["message"])[:300])
            if body.get("message"):
                return self._settings.redact(str(body["message"])[:300])
        return self._settings.redact(str(body)[:300])
