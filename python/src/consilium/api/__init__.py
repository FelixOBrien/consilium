"""API package.

`app` is loaded lazily. Importing a schema must not import the routers, because
the routers call the search package and the search package imports those schemas.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name in {"app", "create_app"}:
        from consilium.api.app import app, create_app  # pragma: allowlist secret

        globals()["app"] = app
        globals()["create_app"] = create_app
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
