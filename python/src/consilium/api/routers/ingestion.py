from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from consilium.api.deps import Acting, StoreDep  # pragma: allowlist secret
from consilium.api.schemas.ingestion import (  # pragma: allowlist secret
    IngestionJob,
    IngestionJobCreate,
)

router = APIRouter(tags=["ingestion"])


@router.get(
    "/ingestion/jobs",
    response_model=list[IngestionJob],
    operation_id="list_ingestion_jobs",
)
def list_ingestion_jobs(_actor: Acting, store: StoreDep) -> list[IngestionJob]:
    return store.list_jobs()


@router.post(
    "/ingestion/jobs",
    response_model=IngestionJob,
    status_code=201,
    operation_id="create_ingestion_job",
    responses={
        200: {
            "model": IngestionJob,
            "description": "An active job already exists for this dataset and slide path.",
        }
    },
)
def create_ingestion_job(
    body: IngestionJobCreate,
    actor: Acting,
    store: StoreDep,
    response: Response,
) -> IngestionJob:
    job, created = store.create_job(body, actor)
    if not created:
        response.status_code = 200
    return job


@router.get(
    "/ingestion/jobs/{job_id}",
    response_model=IngestionJob,
    operation_id="get_ingestion_job",
)
def get_ingestion_job(job_id: UUID, _actor: Acting, store: StoreDep) -> IngestionJob:
    return store.get_job(job_id)
