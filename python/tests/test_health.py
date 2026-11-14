from __future__ import annotations

from fastapi.testclient import TestClient

from consilium.api.app import API_DESCRIPTION, create_app  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret


def test_health_and_lifespan() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert isinstance(client.app.state.settings, Settings)
        assert client.app.state.settings.search_backend.value == "pgvector"

    assert "not for clinical use" in API_DESCRIPTION
    assert "not for clinical use" in app.description


def test_openapi_lists_health() -> None:
    schema = create_app().openapi()
    assert "/api/health" in schema["paths"]
    assert "get" in schema["paths"]["/api/health"]


def test_unknown_route() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/missing")
        assert response.status_code == 404
