"""OpenAPI export. No database connection is required."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MESSAGES_PATH = "/api/consult/threads/{thread_id}/messages"


def canonical_openapi(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def customize_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """Document the consult reply as SSE and use the shared error envelope."""
    message = schema.get("paths", {}).get(MESSAGES_PATH, {}).get("post")
    if isinstance(message, dict):
        response = message.setdefault("responses", {}).setdefault("200", {})
        content = response.get("content", {})
        json_schema = content.get("application/json")
        if json_schema is not None:
            content.pop("application/json", None)
            content["text/event-stream"] = json_schema
            response["content"] = content
            response["description"] = (
                "Server-sent events named step, text, citations, ranking, done and error. "
                "Each data payload is one consult event. The answer cites precedent and "
                "does not diagnose the open case."
            )
    error_schema = {
        "description": "Error.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    }
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            if "422" in responses:
                responses["422"] = {
                    **error_schema,
                    "description": "Request validation failed.",
                }
    _drop_unreferenced(schema, "HTTPValidationError")
    _drop_unreferenced(schema, "ValidationError")
    return schema


def _drop_unreferenced(schema: dict[str, Any], name: str) -> None:
    components = schema.get("components", {}).get("schemas", {})
    if name not in components:
        return
    blob = json.dumps({key: value for key, value in schema.items() if key != "components"})
    if f"#/components/schemas/{name}" not in blob:
        components.pop(name, None)


def export_openapi(path: Path) -> None:
    from consilium.api.app import create_app  # pragma: allowlist secret

    schema = create_app().openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_openapi(schema), encoding="utf-8")
