from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.placeholders import PLACEHOLDER_JPEG, dzi_document  # pragma: allowlist secret
from consilium.api.schemas.concept import (  # pragma: allowlist secret
    HeatmapRequest,
    HeatmapResponse,
)
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideDetail  # pragma: allowlist secret

router = APIRouter(tags=["slides"])


def _jpeg() -> Response:
    return Response(content=PLACEHOLDER_JPEG, media_type="image/jpeg")


@router.get(
    "/slides/{slide_id}.dzi",
    operation_id="get_slide_dzi",
    response_class=Response,
    responses={200: {"content": {"application/xml": {}}, "description": "Deep Zoom descriptor."}},
)
def get_slide_dzi(slide_id: str, _actor: Acting, store: StoreDep) -> Response:
    slide = store.get_slide(slide_id)
    xml = dzi_document(slide.width, slide.height)
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
    _actor: Acting,
    store: StoreDep,
) -> Response:
    del level, col, row
    store.get_slide(slide_id)
    return _jpeg()


@router.get("/slides/{slide_id}", response_model=SlideDetail, operation_id="get_slide")
def get_slide(slide_id: str, _actor: Acting, store: StoreDep) -> SlideDetail:
    return store.get_slide(slide_id)


@router.get(
    "/slides/{slide_id}/thumbnail",
    operation_id="get_slide_thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "Whole-slide thumbnail."}},
)
def get_slide_thumbnail(slide_id: str, _actor: Acting, store: StoreDep) -> Response:
    store.get_slide(slide_id)
    return _jpeg()


@router.get(
    "/slides/{slide_id}/patches/at",
    response_model=PatchRef,
    operation_id="get_patch_at",
)
def get_patch_at(
    slide_id: str,
    x: Annotated[int, Query()],
    y: Annotated[int, Query()],
    _actor: Acting,
    store: StoreDep,
) -> PatchRef:
    return store.patch_at(slide_id, x, y)


@router.post(
    "/slides/{slide_id}/heatmap",
    response_model=HeatmapResponse,
    operation_id="create_slide_heatmap",
)
def create_slide_heatmap(
    slide_id: str,
    body: HeatmapRequest,
    _actor: Acting,
    store: StoreDep,
) -> HeatmapResponse:
    """Score patches against a report word (`text`) or an optional concept."""
    return store.heatmap(slide_id, body)
