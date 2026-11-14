"""The API serves the SvelteKit build without swallowing /api."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings, repo_root  # pragma: allowlist secret

_SHELL = "<!doctype html><title>Consilium</title><p>spa-shell</p>\n"  # pragma: allowlist secret
_SECRET = "VOLUME-SECRET-TOKEN\n"


def _build(tmp_path: Path) -> Path:
    build = tmp_path / "web"
    (build / "_app" / "immutable" / "chunks").mkdir(parents=True)
    (build / "index.html").write_text(_SHELL, encoding="utf-8")
    (build / "_app" / "immutable" / "chunks" / "app.js").write_text(
        "console.log('consilium');\n",  # pragma: allowlist secret
        encoding="utf-8",
    )
    (build / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
        encoding="utf-8",
    )
    # A file that must never win over the real API route.
    (build / "api").mkdir()
    (build / "api" / "health").write_text("not-the-api\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text(_SECRET, encoding="utf-8")
    (build / "leak.txt").symlink_to(tmp_path / "secret.txt")
    return build


@pytest.fixture
def spa(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(web_build_dir=_build(tmp_path)), use_stub_store=True)
    with TestClient(app) as client:
        yield client


def test_api_health_beats_a_static_file_of_the_same_path(spa: TestClient) -> None:
    response = spa.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "not-the-api" not in response.text


def test_unknown_api_path_is_json_not_the_spa(spa: TestClient) -> None:
    response = spa.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"
    assert "spa-shell" not in response.text
    assert "<html" not in response.text.lower()


def test_static_assets_keep_their_media_type(spa: TestClient) -> None:
    script = spa.get("/_app/immutable/chunks/app.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "console.log" in script.text

    icon = spa.get("/favicon.svg")
    assert icon.status_code == 200
    assert icon.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in icon.text


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/cases/breast-FX-001",
        "/cases/foo",
        "/patients/PT-001",
        "/patients/PT-01",
        "/search",
        "/ingest",
        "/compare",
    ],
)
def test_client_routes_serve_index_html(spa: TestClient, path: str) -> None:
    response = spa.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == _SHELL


def test_search_query_string_still_serves_the_shell(spa: TestClient) -> None:
    response = spa.get("/search", params={"q": "adenocarcinoma"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == _SHELL


def test_head_on_a_client_route(spa: TestClient) -> None:
    response = spa.head("/cases/breast-FX-001")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_post_to_a_client_route_is_not_html(spa: TestClient) -> None:
    # The shell is GET and HEAD only, so another method is rejected as JSON.
    response = spa.post("/cases/foo")
    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")
    assert "spa-shell" not in response.text


def test_encoded_parent_segments_are_rejected(spa: TestClient) -> None:
    response = spa.get("/_app/%2e%2e/%2e%2e/secret.txt")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert _SECRET not in response.text
    assert "spa-shell" not in response.text


def test_symlink_outside_the_build_is_rejected(spa: TestClient) -> None:
    response = spa.get("/leak.txt")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert _SECRET not in response.text


def test_raw_parent_path_is_rejected(tmp_path: Path) -> None:
    app = create_app(Settings(web_build_dir=_build(tmp_path)), use_stub_store=True)
    status, headers, body = _raw_get(app, "/../secret.txt")
    assert status == 404
    content_type = _header(headers, b"content-type")
    assert content_type.startswith(b"application/json")
    assert _SECRET.encode() not in body
    assert b"spa-shell" not in body


def test_missing_build_does_not_crash_and_leaves_root_alone(tmp_path: Path) -> None:
    app = create_app(Settings(web_build_dir=tmp_path / "absent"), use_stub_store=True)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        root = client.get("/")
        assert root.status_code == 404
        assert root.headers["content-type"].startswith("application/json")
        missing = client.get("/api/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"


def test_relative_web_build_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _build(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = create_app(Settings(web_build_dir=Path("web")), use_stub_store=True)
    with TestClient(app) as client:
        response = client.get("/patients/PT-001")
        assert response.status_code == 200
        assert response.text == _SHELL


def test_openapi_stays_on_api_paths(tmp_path: Path) -> None:
    app = create_app(Settings(web_build_dir=_build(tmp_path)), use_stub_store=True)
    paths = app.openapi()["paths"]
    assert "/api/health" in paths
    assert "/" not in paths
    assert not any("full_path" in path for path in paths)
    assert all(path.startswith("/api/") for path in paths)


def test_app_yaml_references_resources_not_secrets() -> None:
    text = (repo_root() / "python" / "databricks" / "app.yaml").read_text(encoding="utf-8")
    for forbidden in ("sk-ant-", "hf_", "dapi", "postgresql://", "BEGIN ", "AKIA"):
        assert forbidden not in text
    for required in (
        "uvicorn",
        "consilium.api.app:create_app",  # pragma: allowlist secret
        "--factory",
        "0.0.0.0",
        "${DATABRICKS_APP_PORT:-8000}",
        "STORAGE_BACKEND",
        "uc_volume",
        "SEARCH_BACKEND",
        "pgvector",
        "LLM_PROVIDER",
        "anthropic",
        "SLIDE_CACHE_DIR",
        "/tmp/consilium-slides",  # pragma: allowlist secret
        "SLIDE_CACHE_MAX_GB",
        'value: "4"',
        "WEB_BUILD_DIR",
        "static_web",
        "HF_HOME",
        "/tmp/consilium-hf",  # pragma: allowlist secret
        "valueFrom: volume",
        "DATABRICKS_VOLUME_ROOT",
        "STORAGE_ROOT",
        "valueFrom: database-url",
        "valueFrom: anthropic-api-key",
        "valueFrom: hf-token",
        "valueFrom: postgres",
        "/api/health",
    ):
        assert required in text


def _raw_get(app: object, path: str) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("test", 80),
        "root_path": "",
    }

    async def run() -> None:
        await app(scope, receive, send)  # type: ignore[operator]

    asyncio.run(run())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        bytes(message["body"])  # type: ignore[arg-type]
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), list(start["headers"]), body  # type: ignore[arg-type]


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes:
    for key, value in headers:
        if key.lower() == name:
            return value
    return b""
