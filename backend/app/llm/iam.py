"""IBM Cloud IAM authentication for Fabrivium Phase 7B."""

from __future__ import annotations

import threading
import time
from typing import Callable

import httpx

from app.llm.errors import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

#: IBM Cloud's public IAM token endpoint (global — there is no per-region
#: IAM host; the *region* only applies to the watsonx.ai data-plane URL).
DEFAULT_IAM_URL = "https://iam.cloud.ibm.com/identity/token"

# IBM Cloud IAM's API-key grant type.
IAM_GRANT_TYPE = "urn:ibm:params:oauth:grant-type:apikey"

#: Refresh this many seconds BEFORE the token actually expires, so a
#: request that starts just under the wire cannot be issued with a token
#: that dies mid-flight. IAM tokens live 3600s, so 300s is ~8% of the
#: lifetime — generous enough for a slow request, small enough that we
#: still get ~55 minutes of use out of every token.
DEFAULT_REFRESH_MARGIN_SECONDS = 300.0

_REDACTED = "***REDACTED***"


def _redact(text: str, *secrets: str) -> str:
    """Remove *secrets* (and anything shaped like a Bearer token) from *text*."""
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 8:
            cleaned = cleaned.replace(secret, _REDACTED)
    return cleaned


class IBMCloudIAMTokenProvider:
    """Caching IBM Cloud IAM access-token provider."""

    def __init__(
        self,
        api_key: str,
        *,
        iam_url: str = DEFAULT_IAM_URL,
        timeout_seconds: float = 30.0,
        refresh_margin_seconds: float = DEFAULT_REFRESH_MARGIN_SECONDS,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMAuthenticationError(
                "No IBM Cloud API key configured. Set FACTORYMIND_WATSONX_API_KEY in the "
                "backend's local .env (never commit it) to enable the watsonx provider."
            )
        self._api_key = api_key.strip()
        self._iam_url = iam_url
        self._timeout_seconds = timeout_seconds
        self._refresh_margin_seconds = refresh_margin_seconds
        self._clock = clock

        self._client = client
        self._owns_client = client is None

        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        #: Number of actual HTTP token exchanges performed — observability
        #: only (asserted by tests proving the cache really is used).
        self.token_requests = 0

    # Public API

    def get_token(self, *, force_refresh: bool = False) -> str:
        """
        Return a valid Bearer access token, minting a new one only if there is no cached
        token, it is inside the refresh margin, or *force_refresh* is set (used by the
        watsonx provider when IBM rejects a token as expired mid-flight).
        """
        with self._lock:
            if not force_refresh and self._token is not None and not self._is_expiring():
                return self._token
            self._token, self._expires_at = self._fetch_token()
            return self._token

    def redact(self, text: str) -> str:
        """
        Scrub BOTH secrets this object owns — the API key and the currently cached
        access token — out of *text*.
        """
        with self._lock:
            token = self._token
        return _redact(text, self._api_key, token or "")

    def invalidate(self) -> None:
        """Drop the cached token so the next ``get_token`` mints a fresh one."""
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def close(self) -> None:
        """Close the owned HTTP client, if any."""
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        # Deliberately never renders the api key or the cached token.
        return f"<IBMCloudIAMTokenProvider iam_url={self._iam_url!r} cached={self._token is not None}>"

    # Internals

    def _is_expiring(self) -> bool:
        return self._clock() >= (self._expires_at - self._refresh_margin_seconds)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout_seconds)
        return self._client

    def _fetch_token(self) -> tuple[str, float]:
        """Perform ONE IAM token exchange. Caller holds ``self._lock``."""
        started = self._clock()
        try:
            response = self._http().post(
                self._iam_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"grant_type": IAM_GRANT_TYPE, "apikey": self._api_key},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"IBM Cloud IAM token request timed out after {self._timeout_seconds}s.",
                provider_name="watsonx", cause=exc,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMUnavailableError(
                f"Could not reach IBM Cloud IAM ({type(exc).__name__}).",
                provider_name="watsonx", cause=exc,
            ) from exc

        self.token_requests += 1
        self._raise_for_status(response)

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMAuthenticationError(
                "IBM Cloud IAM returned a non-JSON body for a token request.",
                provider_name="watsonx", cause=exc,
            ) from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise LLMAuthenticationError(
                "IBM Cloud IAM returned a token response with no usable 'access_token' field.",
                provider_name="watsonx",
            )

        # Prefer the relative ``expires_in`` over the absolute
        # ``expiration``: it is immune to local clock skew (see module
        # docstring). Fall back to a conservative 5 minutes if IAM ever
        # omits it, so a missing field can only ever make us refresh MORE
        # often, never trust a token for too long.
        expires_in = payload.get("expires_in")
        lifetime = float(expires_in) if isinstance(expires_in, (int, float)) and expires_in > 0 else 300.0
        return token, started + lifetime

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return

        detail = self._error_detail(response)

        if status in (400, 401, 403):
            # IAM uses 400 (BXNIM0415E "Provided API key could not be
            # found") for a bad/deleted key just as often as 401 — all
            # three mean "these credentials cannot work", never retry.
            raise LLMAuthenticationError(
                f"IBM Cloud IAM rejected the configured API key (HTTP {status}): {detail}",
                provider_name="watsonx",
            )
        if status == 429:
            raise LLMRateLimitError(
                f"IBM Cloud IAM rate-limited the token request (HTTP 429): {detail}",
                provider_name="watsonx",
            )
        raise LLMUnavailableError(
            f"IBM Cloud IAM token request failed (HTTP {status}): {detail}",
            provider_name="watsonx",
        )

    def _error_detail(self, response: httpx.Response) -> str:
        """Build a short, SECRET-FREE description of an IAM error."""
        try:
            body = response.json()
        except ValueError:
            return _redact(response.text[:200], self._api_key)

        if isinstance(body, dict):
            code = body.get("errorCode") or body.get("code") or ""
            message = body.get("errorMessage") or body.get("message") or ""
            if code or message:
                return _redact(f"{code} {message}".strip()[:300], self._api_key)
        return _redact(str(body)[:200], self._api_key)
