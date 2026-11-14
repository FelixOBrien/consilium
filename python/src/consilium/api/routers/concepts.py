from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.common import Specialty  # pragma: allowlist secret
from consilium.api.schemas.concept import Concept  # pragma: allowlist secret

router = APIRouter(tags=["heatmaps"])


@router.get("/concepts", response_model=list[Concept], operation_id="list_concepts")
def list_concepts(
    _actor: Acting,
    store: StoreDep,
    specialty: Annotated[
        Specialty | None,
        Query(description="That specialty plus general concepts. Omit for the full list."),
    ] = None,
) -> list[Concept]:
    return store.concepts_for(specialty)
