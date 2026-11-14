from __future__ import annotations

from fastapi import APIRouter, Response

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.placeholders import PLACEHOLDER_JPEG  # pragma: allowlist secret
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret

router = APIRouter(tags=["patches"])


@router.get("/patches/{patch_id}", response_model=PatchRef, operation_id="get_patch")
def get_patch(patch_id: int, _actor: Acting, store: StoreDep) -> PatchRef:
    return store.get_patch(patch_id)


@router.get(
    "/patches/{patch_id}/thumbnail",
    operation_id="get_patch_thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}, "description": "Patch thumbnail."}},
)
def get_patch_thumbnail(patch_id: int, _actor: Acting, store: StoreDep) -> Response:
    store.get_patch(patch_id)
    return Response(content=PLACEHOLDER_JPEG, media_type="image/jpeg")
