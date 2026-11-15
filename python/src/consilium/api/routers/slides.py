from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from psycopg import Connection

from consilium.api.deps import Acting, DbConn, StoreDep  # pragma: allowlist secret
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.placeholders import PLACEHOLDER_JPEG, dzi_document  # pragma: allowlist secret
from consilium.api.schemas.concept import (  # pragma: allowlist secret
    HeatmapRequest,
    HeatmapResponse,
)
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideDetail  # pragma: allowlist secret
from consilium.db.concepts import heatmap_for  # pragma: allowlist secret
from consilium.db.slides import find_patch_at, patch_ref, slide_detail  # pragma: allowlist secret
from consilium.db.slides import get_slide as fetch_slide  # pragma: allowlist secret
from consilium.tiles.dzi import (  # pragma: allowlist secret
    TILE_CACHE_CONTROL,
    TileOutOfRange,
    descriptor,
    slide_thumbnail,
    tile_jpeg,
)
from consilium.tiles.store import SlideStore, StorageError  # pragma: allowlist secret

router = APIRouter(tags=["slides"])


def _jpeg() -> Response:
    return Response(content=PLACEHOLDER_JPEG, media_type="image/jpeg")


@contextmanager
def _connection(request: Request) -> Iterator[Connection]:
    pool = request.app.state.pool
    if pool is None:
        fail(500, "error", "Database pool is not configured.")
    with pool.connection() as conn:
        yield conn


def _slide_store(request: Request) -> SlideStore:
    store = getattr(request.app.state, "slide_store", None)
    if store is None:
        fail(500, "error", "Slide store is not configured.")
    return store


def _require_ready(status: str) -> None:
    if status != "ready":
        fail(409, "not_ready", f"Slide status is {status}.")


def _storage_error(exc: StorageError) -> None:
    fail(exc.status_code, exc.code, exc.message)


@router.get(
    "/slides/{slide_id}.dzi",
    operation_id="get_slide_dzi",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}, "description": "Deep Zoom descriptor."}},
)
def get_slide_dzi(slide_id: str, request: Request, _actor: Acting, store: StoreDep) -> Response:
    # Sync handler: FastAPI runs it on a worker thread, off the event loop.
    if request.app.state.use_stub_store:
        slide = store.get_slide(slide_id)
        xml = dzi_document(slide.width, slide.height)
        return Response(content=xml, media_type="application/xml")
    with _connection(request) as conn:
        row = fetch_slide(conn, slide_id)
    if row is None:
        fail(404, "not_found", "Slide not found.")
    _require_ready(row.status)
    try:
        xml = descriptor(_slide_store(request), row.storage_key)
    except StorageError as exc:
        _storage_error(exc)
    return Response(content=xml, media_type="application/xml")


@router.get(
    "/slides/{slide_id}_files/{level}/{col}_{row}.jpeg",
    operation_id="get_slide_tile",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "Deep Zoom tile."}},
)
def get_slide_tile(
    slide_id: str,
    level: Annotated[int, Path(ge=0)],
    col: Annotated[int, Path(ge=0)],
    row: Annotated[int, Path(ge=0)],
    request: Request,
    _actor: Acting,
    store: StoreDep,
) -> Response:
    if request.app.state.use_stub_store:
        del level, col, row
        store.get_slide(slide_id)
        return _jpeg()
    with _connection(request) as conn:
        slide = fetch_slide(conn, slide_id)
    if slide is None:
        fail(404, "not_found", "Slide not found.")
    _require_ready(slide.status)
    try:
        payload = tile_jpeg(_slide_store(request), slide.storage_key, level, col, row)
    except TileOutOfRange:
        fail(404, "not_found", "Tile is outside the slide.")
    except StorageError as exc:
        _storage_error(exc)
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": TILE_CACHE_CONTROL},
    )


@router.get("/slides/{slide_id}", response_model=SlideDetail, operation_id="get_slide")
def get_slide(slide_id: str, request: Request, _actor: Acting, store: StoreDep) -> SlideDetail:
    if request.app.state.use_stub_store:
        return store.get_slide(slide_id)
    with _connection(request) as conn:
        row = fetch_slide(conn, slide_id)
    if row is None:
        fail(404, "not_found", "Slide not found.")
    return slide_detail(row)


@router.get(
    "/slides/{slide_id}/thumbnail",
    operation_id="get_slide_thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "Whole-slide thumbnail."}},
)
def get_slide_thumbnail(
    slide_id: str, request: Request, _actor: Acting, store: StoreDep
) -> Response:
    if request.app.state.use_stub_store:
        store.get_slide(slide_id)
        return _jpeg()
    with _connection(request) as conn:
        row = fetch_slide(conn, slide_id)
    if row is None:
        fail(404, "not_found", "Slide not found.")
    _require_ready(row.status)
    try:
        payload = slide_thumbnail(_slide_store(request), row.storage_key)
    except StorageError as exc:
        _storage_error(exc)
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": TILE_CACHE_CONTROL},
    )


@router.get(
    "/slides/{slide_id}/patches/at",
    response_model=PatchRef,
    operation_id="get_patch_at",
)
def get_patch_at(
    slide_id: str,
    x: Annotated[int, Query()],
    y: Annotated[int, Query()],
    request: Request,
    _actor: Acting,
    store: StoreDep,
) -> PatchRef:
    if request.app.state.use_stub_store:
        return store.patch_at(slide_id, x, y)
    with _connection(request) as conn:
        slide = fetch_slide(conn, slide_id)
        if slide is None:
            fail(404, "not_found", "Slide not found.")
        found = find_patch_at(conn, slide_id, x, y)
    if found is None:
        fail(404, "not_found", "No patch contains that point.")
    return patch_ref(found)


@router.post(
    "/slides/{slide_id}/heatmap",
    response_model=HeatmapResponse,
    operation_id="create_slide_heatmap",
)
def create_slide_heatmap(
    slide_id: str,
    body: HeatmapRequest,
    request: Request,
    _actor: Acting,
    store: StoreDep,
    db: DbConn,
) -> HeatmapResponse:
    """Score one slide from a report word, a concept, or selected tissue."""
    if request.app.state.use_stub_store:
        return store.heatmap(slide_id, body)
    encoders = getattr(request.app.state, "text_encoders", None)
    if encoders is None and (body.text is not None or body.concept_id is not None):
        fail(500, "error", "Text encoder is not configured.")
    return heatmap_for(db, encoders, slide_id, body)
