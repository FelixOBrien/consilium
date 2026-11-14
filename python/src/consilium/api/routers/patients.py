from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.case import PatientDetail  # pragma: allowlist secret
from consilium.api.schemas.common import Page  # pragma: allowlist secret
from consilium.api.schemas.patient import PatientSummary  # pragma: allowlist secret

router = APIRouter(tags=["patients"])


@router.get("/patients", response_model=Page[PatientSummary], operation_id="list_patients")
def list_patients(
    _actor: Acting,
    store: StoreDep,
    q: Annotated[str | None, Query(description="Match patient id or display label.")] = None,
    multi_case: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[PatientSummary]:
    return store.list_patients(q=q, multi_case=multi_case, limit=limit, cursor=cursor)


@router.get("/patients/{patient_id}", response_model=PatientDetail, operation_id="get_patient")
def get_patient(patient_id: str, _actor: Acting, store: StoreDep) -> PatientDetail:
    return store.get_patient(patient_id)
