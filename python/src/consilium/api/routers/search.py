from __future__ import annotations

from fastapi import APIRouter, Request

from consilium.api.deps import Acting, DbConn, StoreDep  # pragma: allowlist secret
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
    SlideScopeResponse,
)
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.search import SearchError  # pragma: allowlist secret
from consilium.search import search_patches as run_patch_search  # pragma: allowlist secret
from consilium.search import search_reports as run_report_search  # pragma: allowlist secret

router = APIRouter(tags=["search"])


def _encoders(request: Request) -> TextEncoders:
    encoders = getattr(request.app.state, "text_encoders", None)
    if isinstance(encoders, TextEncoders):
        return encoders
    fail(500, "error", "Text encoder is not configured.")


@router.post(
    "/search/patches",
    response_model=SearchResponse | SlideScopeResponse,
    operation_id="search_patches",
)
def search_patches(
    body: PatchSearchRequest,
    request: Request,
    _actor: Acting,
    store: StoreDep,
    db: DbConn,
) -> SearchResponse | SlideScopeResponse:
    if request.app.state.use_stub_store:
        return store.search_patches(body)
    try:
        return run_patch_search(db, body, _encoders(request))
    except SearchError as exc:
        fail(exc.status_code, exc.code, exc.message)


@router.post(
    "/search/reports",
    response_model=SearchResponse,
    operation_id="search_reports",
)
def search_reports(
    body: ReportSearchRequest,
    request: Request,
    _actor: Acting,
    store: StoreDep,
    db: DbConn,
) -> SearchResponse:
    if request.app.state.use_stub_store:
        return store.search_reports(body)
    try:
        return run_report_search(db, body, _encoders(request))
    except SearchError as exc:
        fail(exc.status_code, exc.code, exc.message)
