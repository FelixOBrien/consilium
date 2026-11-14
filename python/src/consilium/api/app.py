from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from consilium.api.health import router as health_router  # pragma: allowlist secret
from consilium.config import get_settings  # pragma: allowlist secret

API_DESCRIPTION = (
    "Research prototype. Not a medical device and not for clinical use. "
    "The API retrieves precedent and cites cases; it does not diagnose."
)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = get_settings()
        yield

    title = "Consilium"  # pragma: allowlist secret
    app = FastAPI(title=title, description=API_DESCRIPTION, lifespan=lifespan)
    app.include_router(health_router, prefix="/api")
    return app


app = create_app()
