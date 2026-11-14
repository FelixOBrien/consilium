from __future__ import annotations

import importlib

import pytest

MODULES = [
    "consilium",  # pragma: allowlist secret
    "consilium.config",  # pragma: allowlist secret
    "consilium.cli",  # pragma: allowlist secret
    "consilium.api",  # pragma: allowlist secret
    "consilium.api.app",  # pragma: allowlist secret
    "consilium.api.health",  # pragma: allowlist secret
    "consilium.db",  # pragma: allowlist secret
    "consilium.search",  # pragma: allowlist secret
    "consilium.embed",  # pragma: allowlist secret
    "consilium.embed.spaces",  # pragma: allowlist secret
    "consilium.tiles",  # pragma: allowlist secret
    "consilium.agent",  # pragma: allowlist secret
    "consilium.pipeline",  # pragma: allowlist secret
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


def test_api_dependencies_import() -> None:
    import anthropic
    import fastapi
    import pgvector
    import psycopg
    import pydantic
    import pydantic_settings
    import uvicorn

    modules = (
        anthropic,
        fastapi,
        pgvector,
        psycopg,
        pydantic,
        pydantic_settings,
        uvicorn,
    )
    assert all(module.__name__ for module in modules)
