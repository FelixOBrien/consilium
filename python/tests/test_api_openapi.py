"""The committed OpenAPI document is the frontend contract."""

from __future__ import annotations

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.openapi import canonical_openapi  # pragma: allowlist secret
from consilium.config import repo_root  # pragma: allowlist secret

CLIENT_SCHEMA = repo_root() / "typescript" / "apps" / "web" / "src" / "lib" / "api" / "openapi.json"


def test_committed_openapi_matches_the_models() -> None:
    assert CLIENT_SCHEMA.is_file(), "Run `bun run gen:api` from typescript/ and commit the client."
    live = canonical_openapi(create_app().openapi())
    assert CLIENT_SCHEMA.read_text(encoding="utf-8") == live


def test_acting_user_header_is_documented() -> None:
    operation = create_app().openapi()["paths"]["/api/me"]["get"]
    headers = [param for param in operation["parameters"] if param["in"] == "header"]
    assert headers[0]["name"] == "X-User-Id"
    assert headers[0]["required"] is False


def test_consult_messages_are_server_sent_events() -> None:
    operation = create_app().openapi()["paths"]["/api/consult/threads/{thread_id}/messages"]["post"]
    content = operation["responses"]["200"]["content"]
    assert "text/event-stream" in content
    assert "application/json" not in content
