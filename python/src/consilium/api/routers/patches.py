from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Request, Response
from psycopg import Connection

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.placeholders import PLACEHOLDER_JPEG  # pragma: allowlist secret
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.db.slides import get_patch as fetch_patch  # pragma: allowlist secret
from consilium.db.slides import patch_ref  # pragma: allowlist secret
from consilium.tiles.dzi import TILE_CACHE_CONTROL, pack_jpeg  # pragma: allowlist secret
from consilium.tiles.store import SlideStore, StorageError  # pragma: allowlist secret

router = APIRouter(tags=["patches"])


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


@router.get("/patches/{patch_id}", response_model=PatchRef, operation_id="get_patch")
def get_patch(patch_id: int, request: Request, _actor: Acting, store: StoreDep) -> PatchRef:
    if request.app.state.use_stub_store:
        return store.get_patch(patch_id)
    with _connection(request) as conn:
        row = fetch_patch(conn, patch_id)
    if row is None:
        fail(404, "not_found", "Patch not found.")
    return patch_ref(row)


@router.get(
    "/patches/{patch_id}/thumbnail",
    operation_id="get_patch_thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "Patch thumbnail."}},
)
def get_patch_thumbnail(
    patch_id: int, request: Request, _actor: Acting, store: StoreDep
) -> Response:
    if request.app.state.use_stub_store:
        store.get_patch(patch_id)
        return Response(content=PLACEHOLDER_JPEG, media_type="image/jpeg")
    with _connection(request) as conn:
        row = fetch_patch(conn, patch_id)
    if row is None:
        fail(404, "not_found", "Patch not found.")
    if row.slide_status != "ready" or not row.thumb_pack_key:
        fail(409, "not_ready", f"Slide status is {row.slide_status}.")
    try:
        payload = pack_jpeg(
            _slide_store(request),
            row.thumb_pack_key,
            row.thumb_offset,
            row.thumb_length,
        )
    except StorageError as exc:
        fail(exc.status_code, exc.code, exc.message)
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": TILE_CACHE_CONTROL},
    )
