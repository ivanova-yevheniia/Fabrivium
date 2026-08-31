"""Phase 7B tests — IBM Cloud IAM authentication."""

from __future__ import annotations

import httpx
import pytest

from app.llm.errors import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.iam import IAM_GRANT_TYPE, IBMCloudIAMTokenProvider, _redact

API_KEY = "fake-local-api-key-value-0123456789"
IAM_URL = "https://iam.example.invalid/identity/token"


class FakeClock:
    """Injectable monotonic clock so token-expiry tests never sleep."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _provider(handler, *, clock=None, **kwargs) -> IBMCloudIAMTokenProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return IBMCloudIAMTokenProvider(
        API_KEY, iam_url=IAM_URL, client=client, clock=clock or FakeClock(), **kwargs
    )


def _ok(token: str = "iam-access-token-1", expires_in: int = 3600):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "access_token": token, "refresh_token": "not-used",
            "token_type": "Bearer", "expires_in": expires_in, "expiration": 9999999999,
        })

    return handler


# Request construction + token parsing


class TestTokenExchange:
    def test_posts_form_encoded_apikey_grant_to_iam(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            seen["content_type"] = request.headers.get("Content-Type")
            seen["accept"] = request.headers.get("Accept")
            seen["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})

        assert _provider(handler).get_token() == "t"
        assert seen["method"] == "POST"
        assert seen["url"] == IAM_URL
        assert seen["content_type"] == "application/x-www-form-urlencoded"
        assert seen["accept"] == "application/json"
        # The exact IBM grant-type URN — IAM rejects generic OAuth2 grants.
        assert f"grant_type={IAM_GRANT_TYPE.replace(':', '%3A')}" in seen["body"]
        assert "apikey=" in seen["body"]

    def test_parses_access_token_from_response(self):
        assert _provider(_ok("abc123")).get_token() == "abc123"

    def test_missing_access_token_is_typed_auth_error_not_a_keyerror(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"expires_in": 3600})

        with pytest.raises(LLMAuthenticationError):
            _provider(handler).get_token()

    def test_non_json_body_is_typed_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        with pytest.raises(LLMAuthenticationError):
            _provider(handler).get_token()

    def test_empty_api_key_rejected_at_construction(self):
        with pytest.raises(LLMAuthenticationError):
            IBMCloudIAMTokenProvider("   ")


# Caching / expiry / refresh


class TestCachingAndRefresh:
    def test_token_is_cached_not_refetched_per_call(self):
        provider = _provider(_ok())
        for _ in range(5):
            assert provider.get_token() == "iam-access-token-1"
        assert provider.token_requests == 1

    def test_refreshes_once_inside_the_expiry_margin(self):
        clock = FakeClock()
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"access_token": f"token-{calls['n']}", "expires_in": 3600})

        provider = _provider(handler, clock=clock, refresh_margin_seconds=300.0)
        assert provider.get_token() == "token-1"

        # Still comfortably valid: 3000s in, 600s of life left (> 300 margin).
        clock.advance(3000)
        assert provider.get_token() == "token-1"
        assert provider.token_requests == 1

        clock.advance(400)
        assert provider.get_token() == "token-2"
        assert provider.token_requests == 2

    def test_expiry_uses_expires_in_not_the_wall_clock_expiration_field(self):
        """A skewed/incorrect ``expiration`` timestamp must never be able
        to keep a dead token alive: expiry is derived from ``expires_in``
        against a monotonic clock."""
        clock = FakeClock()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "access_token": "short-lived", "expires_in": 60,
                # Absolute timestamp claiming it lives until the year 2286.
                "expiration": 9999999999,
            })

        provider = _provider(handler, clock=clock, refresh_margin_seconds=10.0)
        provider.get_token()
        clock.advance(55)
        provider.get_token()
        assert provider.token_requests == 2

    def test_missing_expires_in_falls_back_to_a_short_conservative_lifetime(self):
        clock = FakeClock()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "no-expiry-field"})

        provider = _provider(handler, clock=clock, refresh_margin_seconds=0.0)
        provider.get_token()
        clock.advance(299)
        provider.get_token()
        assert provider.token_requests == 1
        clock.advance(2)
        provider.get_token()
        assert provider.token_requests == 2

    def test_force_refresh_bypasses_the_cache(self):
        provider = _provider(_ok())
        provider.get_token()
        provider.get_token(force_refresh=True)
        assert provider.token_requests == 2

    def test_invalidate_forces_the_next_call_to_refetch(self):
        provider = _provider(_ok())
        provider.get_token()
        provider.invalidate()
        provider.get_token()
        assert provider.token_requests == 2

    def test_concurrent_callers_share_a_single_token_request(self):
        """FastAPI runs sync endpoints in a threadpool, so the cache must
        be safe to enter concurrently — and must not stampede IAM."""
        import threading

        barrier = threading.Barrier(8)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "shared", "expires_in": 3600})

        provider = _provider(handler)
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            token = provider.get_token()
            with lock:
                results.append(token)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == ["shared"] * 8
        assert provider.token_requests == 1


# Error mapping


class TestErrorMapping:
    @pytest.mark.parametrize("status", [400, 401, 403])
    def test_credential_rejections_map_to_authentication_error(self, status: int):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={
                "errorCode": "BXNIM0415E", "errorMessage": "Provided API key could not be found.",
            })

        with pytest.raises(LLMAuthenticationError) as exc_info:
            _provider(handler).get_token()
        assert exc_info.value.retryable is False

    def test_429_maps_to_rate_limit_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"errorMessage": "too many requests"})

        with pytest.raises(LLMRateLimitError) as exc_info:
            _provider(handler).get_token()
        assert exc_info.value.retryable is True

    def test_5xx_maps_to_unavailable_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="service unavailable")

        with pytest.raises(LLMUnavailableError):
            _provider(handler).get_token()

    def test_timeout_maps_to_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(LLMTimeoutError):
            _provider(handler).get_token()

    def test_connection_failure_maps_to_unavailable_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("dns failure", request=request)

        with pytest.raises(LLMUnavailableError):
            _provider(handler).get_token()


# Secret hygiene


class TestSecretHygiene:
    def test_api_key_never_appears_in_an_error_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # A hostile/buggy IAM echoing the key straight back at us.
            return httpx.Response(401, json={
                "errorCode": "BXNIM0415E", "errorMessage": f"bad key {API_KEY}",
            })

        with pytest.raises(LLMAuthenticationError) as exc_info:
            _provider(handler).get_token()
        assert API_KEY not in str(exc_info.value)
        assert "REDACTED" in str(exc_info.value)

    def test_api_key_never_appears_in_a_non_json_error_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text=f"upstream logged apikey={API_KEY}")

        with pytest.raises(LLMUnavailableError) as exc_info:
            _provider(handler).get_token()
        assert API_KEY not in str(exc_info.value)

    def test_repr_never_renders_the_key_or_the_token(self):
        provider = _provider(_ok("super-secret-bearer"))
        provider.get_token()
        rendered = repr(provider)
        assert API_KEY not in rendered
        assert "super-secret-bearer" not in rendered

    def test_redact_leaves_short_strings_alone_to_avoid_mangling_messages(self):
        # An 8-char minimum keeps _redact from turning innocuous words into
        # noise; real IBM Cloud API keys are far longer than that.
        assert _redact("the value is abc", "abc") == "the value is abc"
        assert _redact("the value is abcdefghij", "abcdefghij") == "the value is ***REDACTED***"
