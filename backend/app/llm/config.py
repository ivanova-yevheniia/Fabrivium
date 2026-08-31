"""LLM provider configuration for Fabrivium Phase 7A / 7B."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Mapping, MutableMapping

_TRUTHY = {"1", "true", "yes", "on"}


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class LLMSettings:
    """
    Resolved LLM configuration for one process — never mutated after construction; a
    caller that wants different settings builds a new one (e.g.
    """

    enabled: bool
    provider: str
    model: str | None
    timeout_seconds: float
    max_retries: int


#: The concrete providers that actually exist:
#:
#:   "mock"     network-free, key-free; scripted, for tests and local dev
#:   "watsonx"  IBM watsonx.ai / Granite
#:   "bob"      IBM Bob, over its OpenAI-compatible inference API
#:
#: Listed explicitly (rather than silently accepting any string) so an
#: unimplemented FACTORYMIND_LLM_PROVIDER value fails fast and clearly
#: instead of silently behaving like "disabled" — see build_provider in
#: app.llm.__init__.
SUPPORTED_PROVIDERS = frozenset({"mock", "watsonx", "bob"})

#: Default location of the local, never-committed secrets file:
#: ``backend/.env`` (this file lives at backend/app/llm/config.py).
DEFAULT_DOTENV_PATH = pathlib.Path(__file__).resolve().parents[2] / ".env"


def load_dotenv_file(
    path: pathlib.Path | None = None,
    *,
    target: MutableMapping[str, str] | None = None,
) -> list[str]:
    """
    Load ``KEY=value`` lines from *path* (default ``backend/.env``) into *target*
    (default ``os.environ``), and return the names of the keys it actually set.
    """
    dotenv_path = path or DEFAULT_DOTENV_PATH
    sink: MutableMapping[str, str] = target if target is not None else os.environ

    try:
        raw = dotenv_path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []

    loaded: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()

        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        if key in sink:
            continue
        sink[key] = value
        loaded.append(key)

    return loaded


def load_llm_settings(env: Mapping[str, str] | None = None) -> LLMSettings:
    """Read ``FACTORYMIND_LLM_*`` environment variables into an ``LLMSettings``."""
    source = env if env is not None else os.environ

    return LLMSettings(
        enabled=_read_bool(source.get("FACTORYMIND_LLM_ENABLED"), default=False),
        provider=(source.get("FACTORYMIND_LLM_PROVIDER") or "mock").strip().lower(),
        model=(source.get("FACTORYMIND_LLM_MODEL") or None),
        timeout_seconds=float(source.get("FACTORYMIND_LLM_TIMEOUT_SECONDS") or 30.0),
        max_retries=int(source.get("FACTORYMIND_LLM_MAX_RETRIES") or 2),
    )
