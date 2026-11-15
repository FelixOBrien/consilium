from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response

from consilium.api.deps import Acting, StoreDep, read_connection  # pragma: allowlist secret
from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.ingestion import (  # pragma: allowlist secret
    IngestionJob,
    IngestionJobCreate,
)
from consilium.db.ingestion import get_job, list_jobs, submit_job  # pragma: allowlist secret

router = APIRouter(tags=["ingestion"])


@router.get(
    "/ingestion/jobs",
    response_model=list[IngestionJob],
    operation_id="list_ingestion_jobs",
)
def list_ingestion_jobs(request: Request, _actor: Acting, store: StoreDep) -> list[IngestionJob]:
    if request.app.state.use_stub_store:
        return store.list_jobs()
    with read_connection(request) as conn:
        return list_jobs(conn)


@router.post(
    "/ingestion/jobs",
    response_model=IngestionJob,
    status_code=201,
    operation_id="create_ingestion_job",
    responses={
        200: {
            "model": IngestionJob,
            "description": (
                "No new queued job. The body is the active job (duplicate_active), "
                "the failed job returned to the queue (retried), or a finished job "
                "for a slide that is already ready (already_ingested)."
            ),
        }
    },
)
def create_ingestion_job(
    body: IngestionJobCreate,
    request: Request,
    actor: Acting,
    store: StoreDep,
    response: Response,
) -> IngestionJob:
    if request.app.state.use_stub_store:
        job, created = store.create_job(body, actor)
        if not created:
            response.status_code = 200
        return job
    with request.app.state.pool.connection() as conn:
        job = submit_job(
            conn,
            dataset=body.dataset,
            slide_path=body.slide_path,
            requested_by=actor.id,
        )
    if job.outcome != "created":
        response.status_code = 200
    return job


@router.get(
    "/ingestion/jobs/{job_id}",
    response_model=IngestionJob,
    operation_id="get_ingestion_job",
)
def get_ingestion_job(
    job_id: UUID,
    request: Request,
    _actor: Acting,
    store: StoreDep,
) -> IngestionJob:
    if request.app.state.use_stub_store:
        return store.get_job(job_id)
    with read_connection(request) as conn:
        job = get_job(conn, job_id)
    if job is None:
        fail(404, "not_found", "Ingestion job not found.")
    return job
