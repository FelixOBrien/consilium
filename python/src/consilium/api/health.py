from __future__ import annotations

from typing import Literal

import psycopg
from fastapi import APIRouter, Request
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from consilium.db.ingestion import corpus_counts  # pragma: allowlist secret

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Liveness plus the corpus counts the ingestion screen summarises."""

    status: Literal["ok"]
    cases: int | None = Field(default=None, ge=0)
    slides: int | None = Field(default=None, ge=0)
    patches: int | None = Field(default=None, ge=0)
    report_chunks: int | None = Field(default=None, ge=0)


@router.get(
    "/health",
    response_model=HealthResponse,
    response_model_exclude_none=True,
    operation_id="get_health",
)
def health(request: Request) -> HealthResponse:
    counts = _corpus_counts(request)
    if counts is None:
        return HealthResponse(status="ok")
    return HealthResponse(status="ok", **counts)


def _corpus_counts(request: Request) -> dict[str, int] | None:
    """Table counts when Postgres is open. Missing or unreachable DB omits them."""
    if getattr(request.app.state, "use_stub_store", False):
        return None
    pool = getattr(request.app.state, "pool", None)
    if not isinstance(pool, ConnectionPool):
        return None
    try:
        with pool.connection() as conn:
            return corpus_counts(conn)
    except psycopg.Error:
        return None
