from __future__ import annotations

from fastapi import APIRouter, Request

from consilium.api.deps import Acting, StoreDep, read_connection  # pragma: allowlist secret
from consilium.api.schemas.pathologist import Pathologist  # pragma: allowlist secret
from consilium.db.pathologists import (  # pragma: allowlist secret
    list_pathologists as list_pathologist_rows,  # pragma: allowlist secret
)

router = APIRouter(tags=["identity"])


@router.get("/pathologists", response_model=list[Pathologist], operation_id="list_pathologists")
def list_pathologists(
    request: Request,
    _actor: Acting,
    store: StoreDep,
) -> list[Pathologist]:
    if request.app.state.use_stub_store:
        return store.list_pathologists()
    with read_connection(request) as conn:
        return list_pathologist_rows(conn)


@router.get("/me", response_model=Pathologist, operation_id="get_me")
def get_me(actor: Acting) -> Pathologist:
    return actor
