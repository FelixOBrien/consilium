from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from consilium.api.deps import Acting, StoreDep, read_connection  # pragma: allowlist secret
from consilium.api.schemas.case import CaseDetail, CaseSummary  # pragma: allowlist secret
from consilium.api.schemas.common import CaseStatus, Page, Specialty  # pragma: allowlist secret
from consilium.api.schemas.report import CaseReport  # pragma: allowlist secret
from consilium.api.schemas.search import SimilarCases  # pragma: allowlist secret
from consilium.db.cases import get_case as get_case_row  # pragma: allowlist secret
from consilium.db.cases import get_report as get_report_row  # pragma: allowlist secret
from consilium.db.cases import list_cases as list_case_rows  # pragma: allowlist secret

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=Page[CaseSummary], operation_id="list_cases")
def list_cases(
    request: Request,
    actor: Acting,
    store: StoreDep,
    view: Annotated[Literal["mine", "all"] | None, Query()] = None,
    status: Annotated[CaseStatus | None, Query()] = None,
    specialty: Annotated[Specialty | None, Query()] = None,
    assigned_to: Annotated[str | None, Query()] = None,
    icd10: Annotated[str | None, Query(description="ICD-10 prefix.")] = None,
    patient_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> Page[CaseSummary]:
    if request.app.state.use_stub_store:
        return store.list_cases(
            actor=actor,
            view=view,
            status=status,
            specialty=specialty,
            assigned_to=assigned_to,
            icd10=icd10,
            patient_id=patient_id,
            limit=limit,
            cursor=cursor,
        )
    with read_connection(request) as conn:
        return list_case_rows(
            conn,
            actor_id=actor.id,
            view=view,
            status=None if status is None else status.value,
            specialty=None if specialty is None else specialty.value,
            assigned_to=assigned_to,
            icd10=icd10,
            patient_id=patient_id,
            limit=limit,
            cursor=cursor,
        )


@router.get("/cases/{case_id}", response_model=CaseDetail, operation_id="get_case")
def get_case(case_id: str, request: Request, _actor: Acting, store: StoreDep) -> CaseDetail:
    if request.app.state.use_stub_store:
        return store.get_case(case_id)
    with read_connection(request) as conn:
        return get_case_row(conn, case_id)


@router.get("/cases/{case_id}/report", response_model=CaseReport, operation_id="get_case_report")
def get_case_report(case_id: str, request: Request, _actor: Acting, store: StoreDep) -> CaseReport:
    if request.app.state.use_stub_store:
        return store.get_report(case_id)
    with read_connection(request) as conn:
        return get_report_row(conn, case_id)


@router.get(
    "/cases/{case_id}/similar",
    response_model=SimilarCases,
    operation_id="get_similar_cases",
)
def get_similar_cases(case_id: str, _actor: Acting, store: StoreDep) -> SimilarCases:
    return store.similar(case_id)
