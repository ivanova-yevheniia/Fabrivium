"""JSON-Schema preparation for LLM prompts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def compact_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Derive a compact JSON Schema for *model*."""
    schema = model.model_json_schema()
    schema.pop("description", None)
    for definition in (schema.get("$defs") or {}).values():
        if isinstance(definition, dict):
            definition.pop("description", None)
    return _strip_titles(schema)


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_titles(value) for key, value in node.items() if key != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node
