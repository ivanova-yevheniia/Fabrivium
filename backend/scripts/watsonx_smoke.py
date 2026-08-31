"""Minimal live watsonx.ai / Granite smoke check (FactoryMind Phase 7B §20)."""

from __future__ import annotations

import sys

from pydantic import BaseModel

from app.llm import (
    LLMProviderError,
    LLMRequest,
    RetryPolicy,
    load_dotenv_file,
    load_llm_settings,
)
from app.llm.watsonx_provider import WatsonxGraniteProvider, WatsonxSettings


class SmokeResponse(BaseModel):
    """The entire contract of the cheap probe."""

    status: str


def main() -> int:
    loaded = load_dotenv_file()
    if loaded:
        print(f"Loaded {len(loaded)} setting(s) from backend/.env (names only): {', '.join(sorted(loaded))}")

    generic = load_llm_settings()
    try:
        settings = WatsonxSettings.from_env()
    except LLMProviderError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 2

    print(f"endpoint : {settings.chat_endpoint}")
    print(f"model    : {settings.model_id}")
    print(f"project  : {settings.project_id}")
    print(f"json_mode: {settings.json_mode}")
    print(f"api key  : <present, {len(settings.api_key)} chars, never printed>")

    provider = WatsonxGraniteProvider(
        settings,
        retry_policy=RetryPolicy(max_retries=0, timeout_seconds=max(30.0, generic.timeout_seconds)),
    )

    request = LLMRequest(
        system_prompt="You return only compact JSON. No prose, no markdown fences.",
        user_prompt='Return ONLY this JSON: {"status":"ok"}',
        response_schema={"type": "object"},
        temperature=0.0,
        max_tokens=32,
        metadata={"agent": "smoke"},
    )

    try:
        result = provider.generate_structured(request, response_model=SmokeResponse)
    except LLMProviderError as exc:
        print(f"\nLIVE CALL FAILED: {type(exc).__name__}: {exc}")
        print("(In a real planning run this would have fallen back to the deterministic backend.)")
        return 1
    finally:
        provider.close()

    response = result.response
    print("\nLIVE CALL OK")
    print(f"parsed     : {result.parsed!r}")
    print(f"raw_text   : {response.raw_text!r}")
    print(f"model      : {response.model_name}")
    print(f"latency_ms : {response.latency_ms:.0f}")
    print(f"usage      : {response.usage}")
    print(f"request_id : {response.request_id}")
    print(f"attempts   : {result.attempts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
