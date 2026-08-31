"""Live IBM Bob smoke check — the one thing this repository cannot do for you."""

from __future__ import annotations

import sys

import httpx
from pydantic import BaseModel

from app.llm import (
    LLMProviderError,
    LLMRequest,
    RetryPolicy,
    load_dotenv_file,
    load_llm_settings,
)
from app.llm.bob_provider import BobProvider, BobSettings


class SmokeResponse(BaseModel):
    """The entire contract of the cheap probe."""

    status: str


def list_models(settings: BobSettings, timeout: float) -> list[str]:
    """Ask Bob what this account can reach."""
    try:
        response = httpx.get(
            settings.model_info_endpoint,
            headers={
                "Authorization": f"{settings.auth_scheme} {settings.api_key}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        print(f"  model catalogue: unreachable ({type(exc).__name__})")
        return []

    if response.status_code >= 400:
        print(f"  model catalogue: HTTP {response.status_code} — {settings.redact(response.text[:200])}")
        return []

    try:
        body = response.json()
    except ValueError:
        print("  model catalogue: non-JSON response")
        return []

    # The published shape is `{"data": [{"model_name": ..., "exposed": ...}]}`.
    entries = body.get("data") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        print("  model catalogue: unexpected shape, skipping")
        return []

    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("exposed") is False:
            continue
        name = entry.get("model_name") or entry.get("id") or entry.get("model")
        if isinstance(name, str):
            names.append(name)
    return names


def main() -> int:
    loaded = load_dotenv_file()
    print(f"loaded {len(loaded)} key(s) from backend/.env: {sorted(loaded)}")

    generic = load_llm_settings()
    try:
        settings = BobSettings.from_env()
    except LLMProviderError as exc:
        print(f"\nNOT CONFIGURED: {exc}")
        return 2

    print(f"\nendpoint : {settings.chat_endpoint}")
    print(f"model    : {settings.model}")
    print(f"scheme   : {settings.auth_scheme}")
    print(f"team id  : {settings.team_id or '(not set)'}")

    print("\nmodels this account can reach:")
    names = list_models(settings, generic.timeout_seconds)
    for name in names:
        marker = "  <- configured" if name == settings.model else ""
        print(f"  - {name}{marker}")
    if names and settings.model not in names:
        print(
            f"\n  NOTE: FACTORYMIND_BOB_MODEL={settings.model!r} is not in the list above. "
            f"The chat probe will still be attempted, but a 404 here means the model id."
        )
    if not names:
        print("  (none listed — the catalogue was unavailable, not necessarily empty)")

    provider = BobProvider(
        settings,
        retry_policy=RetryPolicy(
            max_retries=generic.max_retries, timeout_seconds=generic.timeout_seconds
        ),
    )

    print("\nchat probe...")
    try:
        result = provider.generate_structured(
            LLMRequest(
                system_prompt='Reply with exactly {"status": "ok"} and nothing else.',
                user_prompt="ping",
                response_schema=SmokeResponse.model_json_schema(),
                max_tokens=32,
            ),
            response_model=SmokeResponse,
        )
    except LLMProviderError as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        print(f"  retryable: {exc.retryable}")
        print(
            "\n  This is what a real planning run would have seen. It would have fallen "
            "back to the deterministic backend and said so in its provenance."
        )
        return 1
    finally:
        provider.close()

    response = result.response
    print(f"  OK: {result.parsed.status}")
    print(f"  model answered : {response.model_name}")
    print(f"  latency        : {response.latency_ms:.0f} ms")
    print(f"  attempts       : {result.attempts}")
    print(f"  usage          : {response.usage or '(not reported)'}")
    print(f"  request id     : {response.request_id or '(not reported)'}")
    print("\nLIVE BOB SMOKE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
