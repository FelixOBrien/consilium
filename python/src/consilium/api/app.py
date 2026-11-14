from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from consilium import __version__  # pragma: allowlist secret
from consilium.api.errors import install_error_handlers  # pragma: allowlist secret
from consilium.api.health import router as health_router  # pragma: allowlist secret
from consilium.api.openapi import customize_openapi  # pragma: allowlist secret
from consilium.api.routers import (  # pragma: allowlist secret
    annotations,
    cases,
    concepts,
    consult,
    identity,
    ingestion,
    patches,
    patients,
    search,
    slides,
)
from consilium.api.schemas.common import ErrorEnvelope  # pragma: allowlist secret
from consilium.api.store import Store  # pragma: allowlist secret
from consilium.config import Settings, get_settings  # pragma: allowlist secret
from consilium.db.connection import connection_pool  # pragma: allowlist secret
from consilium.embed.text import build_text_encoders  # pragma: allowlist secret

API_DESCRIPTION = (
    "Research prototype. Not a medical device and not for clinical use. "
    "The API retrieves precedent and cites cases; it does not diagnose."
)

_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorEnvelope, "description": "The acting pathologist cannot change this."},
    404: {"model": ErrorEnvelope, "description": "Not found."},
    422: {"model": ErrorEnvelope, "description": "Request validation failed."},
}


def create_app(settings: Settings | None = None, *, use_stub_store: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        app.state.settings = cfg
        app.state.store = Store.seed()
        if getattr(app.state, "text_encoders", None) is None:
            app.state.text_encoders = build_text_encoders(cfg)
        if use_stub_store:
            app.state.pool = None
            yield
            return
        pool = connection_pool(cfg.database_url, min_size=0, max_size=8, open=True)
        app.state.pool = pool
        try:
            yield
        finally:
            pool.close()

    app = FastAPI(
        title="Research prototype",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.use_stub_store = use_stub_store
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api")

    api = APIRouter(prefix="/api", responses=_ERROR_RESPONSES)
    for router in (
        identity.router,
        patients.router,
        cases.router,
        slides.router,
        patches.router,
        search.router,
        concepts.router,
        annotations.router,
        consult.router,
        ingestion.router,
    ):
        api.include_router(router)
    app.include_router(api)

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        app.openapi_schema = customize_openapi(schema)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


app = create_app()
