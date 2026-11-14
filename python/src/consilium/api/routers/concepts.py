from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from consilium.api.deps import Acting, DbConn, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.common import Specialty  # pragma: allowlist secret
from consilium.api.schemas.concept import Concept  # pragma: allowlist secret
from consilium.db.concepts import concepts_for  # pragma: allowlist secret

router = APIRouter(tags=["heatmaps"])


@router.get("/concepts", response_model=list[Concept], operation_id="list_concepts")
def list_concepts(
    request: Request,
    _actor: Acting,
    store: StoreDep,
    db: DbConn,
    specialty: Annotated[
        Specialty | None,
        Query(description="That specialty plus general concepts. Omit for the full list."),
    ] = None,
) -> list[Concept]:
    if request.app.state.use_stub_store:
        return store.concepts_for(specialty)
    return concepts_for(db, None if specialty is None else specialty.value)
