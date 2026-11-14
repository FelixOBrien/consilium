from __future__ import annotations

from fastapi import APIRouter

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
    SlideScopeResponse,
)

router = APIRouter(tags=["search"])


@router.post(
    "/search/patches",
    response_model=SearchResponse | SlideScopeResponse,
    operation_id="search_patches",
)
def search_patches(
    body: PatchSearchRequest,
    _actor: Acting,
    store: StoreDep,
) -> SearchResponse | SlideScopeResponse:
    return store.search_patches(body)


@router.post(
    "/search/reports",
    response_model=SearchResponse,
    operation_id="search_reports",
)
def search_reports(body: ReportSearchRequest, _actor: Acting, store: StoreDep) -> SearchResponse:
    return store.search_reports(body)
