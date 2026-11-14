from __future__ import annotations

from fastapi import APIRouter

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.pathologist import Pathologist  # pragma: allowlist secret

router = APIRouter(tags=["identity"])


@router.get("/pathologists", response_model=list[Pathologist], operation_id="list_pathologists")
def list_pathologists(_actor: Acting, store: StoreDep) -> list[Pathologist]:
    return store.list_pathologists()


@router.get("/me", response_model=Pathologist, operation_id="get_me")
def get_me(actor: Acting) -> Pathologist:
    return actor
