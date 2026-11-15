"""Ingestion job queue. The API inserts rows; the GPU worker claims them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from consilium.api.schemas.ingestion import (  # pragma: allowlist secret
    IngestionCounts,
    IngestionJob,
)

JobOutcome = Literal["created", "retried", "duplicate_active", "already_ingested"]

# Partial HNSW / GIN indexes from 0002_indexes.sql. Inserts update them in place.
_SEARCH_INDEXES: tuple[str, ...] = (
    "slide_embedding_hnsw",
    "patch_embedding_hnsw",
    "report_chunk_embedding_hnsw",
    "report_search_tsv_gin",
)
_ANALYZE_SEARCH = "ANALYZE slide, patch, report, report_chunk"

_JOB_COLUMNS = """
select
    j.id, j.dataset, j.slide_path, j.case_id, j.slide_id,
    j.status, j.stage, j.stage_history, j.counts, j.error, j.attempts,
    j.created_at, j.started_at, j.finished_at,
    p.id as requester_id,
    p.name as requester_name,
    p.primary_specialty as requester_specialty,
    p.is_synthetic as requester_synthetic
from ingestion_job j
left join pathologist p on p.id = j.requested_by
"""

_LOCK_JOBS = (
    _JOB_COLUMNS
    + """
where j.dataset = %s and j.slide_path = %s
order by j.created_at desc, j.id desc
for update of j
"""
)

_READY_SLIDE = """
select
    s.id as slide_id,
    s.case_id,
    (select count(*)::int from patch p where p.slide_id = s.id) as patches,
    (select count(*)::int from report_chunk rc where rc.case_id = s.case_id) as chunks
from slide s
join path_case c on c.id = s.case_id
where s.status = 'ready'
  and c.source_dataset = %s
  and (
        s.id = %s
        or s.source_path = %s
        or right(s.source_path, char_length(%s) + 1) = '/' || %s
        or left(s.source_path, char_length(%s) + 1) = %s || '/'
      )
order by s.created_at, s.id
limit 1
"""

_READY_FROM_JOB = """
select
    s.id as slide_id,
    s.case_id,
    (select count(*)::int from patch p where p.slide_id = s.id) as patches,
    (select count(*)::int from report_chunk rc where rc.case_id = s.case_id) as chunks
from ingestion_job j
join slide s on s.id = j.slide_id
where j.dataset = %s
  and j.slide_path = %s
  and j.status = 'done'
  and s.status = 'ready'
order by j.finished_at desc nulls last, j.created_at desc
limit 1
"""

_CLAIM = """
update ingestion_job as job
set status = 'running',
    worker_id = %s,
    started_at = now(),
    error = null,
    attempts = job.attempts + 1
where job.id = (
    select id
    from ingestion_job
    where status = 'queued'
    order by created_at, id
    for update skip locked
    limit 1
)
returning id
"""

_CORPUS_COUNTS = """
select
    (select count(*)::int from path_case) as cases,
    (select count(*)::int from slide) as slides,
    (select count(*)::int from patch) as patches,
    (select count(*)::int from report_chunk) as report_chunks
"""


@dataclass(frozen=True)
class ReadySlide:
    slide_id: str
    case_id: str
    patches: int
    chunks: int


def corpus_counts(conn: Connection) -> dict[str, int]:
    """Live table counts for the ingestion screen's corpus summary."""
    row = _fetchone(conn, _CORPUS_COUNTS, ())
    if row is None:
        return {"cases": 0, "slides": 0, "patches": 0, "report_chunks": 0}
    return {
        "cases": int(row["cases"]),
        "slides": int(row["slides"]),
        "patches": int(row["patches"]),
        "report_chunks": int(row["report_chunks"]),
    }


def list_jobs(conn: Connection) -> list[IngestionJob]:
    """Recent jobs, newest first. `worker_id` is not part of the API shape."""
    rows = _fetchall(
        conn,
        _JOB_COLUMNS + " order by j.created_at desc, j.id desc",
        (),
    )
    return [_job(row) for row in rows]


def get_job(conn: Connection, job_id: UUID) -> IngestionJob | None:
    row = _fetchone(conn, _JOB_COLUMNS + " where j.id = %s", (job_id,))
    if row is None:
        return None
    return _job(row)


def submit_job(
    conn: Connection,
    *,
    dataset: str,
    slide_path: str,
    requested_by: str | None,
) -> IngestionJob:
    """Queue a slide, or return the job S-08 should show instead of a second one.

    Active `(dataset, slide_path)` rows are unique. A concurrent insert loses
    the race and returns the winner with `duplicate_active`.
    """
    dataset = dataset.strip()
    slide_path = slide_path.strip()
    if not dataset or not slide_path:
        raise ValueError("dataset and slide_path are required")
    try:
        with conn.transaction():
            return _submit_locked(conn, dataset, slide_path, requested_by)
    except UniqueViolation:
        with conn.transaction():
            active = _first(_lock_jobs(conn, dataset, slide_path), "queued", "running")
            if active is None:
                raise
            return _job(active, outcome="duplicate_active")


def claim_next_job(conn: Connection, worker_id: str) -> IngestionJob | None:
    """Claim the oldest queued job, skipping rows locked by another worker."""
    if not worker_id.strip():
        raise ValueError("worker_id is required")
    row = _fetchone(conn, _CLAIM, (worker_id,))
    if row is None:
        return None
    job = get_job(conn, row["id"])
    if job is None:
        raise RuntimeError("claimed ingestion job disappeared")
    return job


def find_ready_slide(conn: Connection, dataset: str, slide_path: str) -> ReadySlide | None:
    """A ready slide for this project and GDC file name, file id, or slide id."""
    path = slide_path.strip()
    row = _fetchone(
        conn,
        _READY_SLIDE,
        (dataset, path, path, path, path, path, path),
    )
    if row is None:
        row = _fetchone(conn, _READY_FROM_JOB, (dataset, path))
    if row is None:
        return None
    return ReadySlide(
        slide_id=str(row["slide_id"]),
        case_id=str(row["case_id"]),
        patches=int(row["patches"]),
        chunks=int(row["chunks"]),
    )


def begin_stage(conn: Connection, job_id: UUID, stage: str) -> None:
    entry = {
        "stage": stage,
        "started_at": _now(),
        "finished_at": None,
        "detail": None,
    }
    conn.execute(
        """
        update ingestion_job
        set stage = %s,
            stage_history = stage_history || %s::jsonb
        where id = %s
        """,
        (stage, Jsonb([entry]), job_id),
    )


def finish_stage(
    conn: Connection,
    job_id: UUID,
    detail: str,
    *,
    case_id: str | None = None,
    slide_id: str | None = None,
    patches: int | None = None,
    chunks: int | None = None,
) -> None:
    history = _history(conn, job_id)
    if not history:
        raise RuntimeError("stage history is empty")
    last = history[-1]
    last["finished_at"] = _now()
    last["detail"] = _one_line(detail)
    history[-1] = last
    counts = _counts_json(patches, chunks)
    conn.execute(
        """
        update ingestion_job
        set stage_history = %s,
            case_id = coalesce(%s, case_id),
            slide_id = coalesce(%s, slide_id),
            counts = coalesce(%s, counts)
        where id = %s
        """,
        (Jsonb(history), case_id, slide_id, counts, job_id),
    )


def mark_done(
    conn: Connection,
    job_id: UUID,
    *,
    case_id: str | None,
    slide_id: str | None,
    patches: int | None,
    chunks: int | None,
) -> None:
    conn.execute(
        """
        update ingestion_job
        set status = 'done',
            stage = 'index',
            error = null,
            case_id = coalesce(%s, case_id),
            slide_id = coalesce(%s, slide_id),
            counts = coalesce(%s, counts),
            finished_at = now()
        where id = %s
        """,
        (case_id, slide_id, _counts_json(patches, chunks), job_id),
    )


def finish_already_ready(conn: Connection, job_id: UUID, ready: ReadySlide) -> None:
    """Close a claimed job without repeating pipeline work."""
    now = _now()
    entry = {
        "stage": "index",
        "started_at": now,
        "finished_at": now,
        "detail": "slide already ready; no stages repeated",
    }
    conn.execute(
        """
        update ingestion_job
        set status = 'done',
            stage = 'index',
            error = null,
            case_id = %s,
            slide_id = %s,
            counts = %s,
            stage_history = stage_history || %s::jsonb,
            finished_at = now()
        where id = %s
        """,
        (
            ready.case_id,
            ready.slide_id,
            Jsonb({"patches": ready.patches, "chunks": ready.chunks}),
            Jsonb([entry]),
            job_id,
        ),
    )


def record_failure(conn: Connection, job_id: UUID, stage: str, message: str) -> None:
    text = _one_line(message) or "ingestion failed"
    history = _history(conn, job_id)
    now = _now()
    if history and history[-1].get("stage") == stage and not history[-1].get("finished_at"):
        history[-1]["finished_at"] = now
        history[-1]["detail"] = text
    else:
        history.append(
            {
                "stage": stage,
                "started_at": now,
                "finished_at": now,
                "detail": text,
            }
        )
    conn.execute(
        """
        update ingestion_job
        set status = 'failed',
            stage = %s,
            error = %s,
            stage_history = %s,
            finished_at = now()
        where id = %s
        """,
        (stage, text, Jsonb(history), job_id),
    )


def refresh_search_indexes(conn: Connection) -> str:
    """Confirm search indexes are valid, then ANALYZE. Does not rebuild them.

    pgvector HNSW and the report GIN index incorporate new rows on insert.
    """
    rows = _fetchall(
        conn,
        """
        select c.relname
        from pg_class c
        join pg_index i on i.indexrelid = c.oid
        where c.relname = any(%s)
          and i.indisvalid
          and i.indisready
        """,
        (list(_SEARCH_INDEXES),),
    )
    found = {str(row["relname"]) for row in rows}
    missing = [name for name in _SEARCH_INDEXES if name not in found]
    if missing:
        raise RuntimeError("search indexes are not ready: " + ", ".join(missing))
    if "reindex" in _ANALYZE_SEARCH.lower():
        raise RuntimeError("index refresh must not rebuild indexes")
    conn.execute(_ANALYZE_SEARCH)
    return "indexes ready; analyzed slide, patch, report, report_chunk"


def slide_counts(conn: Connection, slide_id: str, case_id: str) -> tuple[int, int]:
    row = _fetchone(
        conn,
        """
        select
            (select count(*)::int from patch where slide_id = %s) as patches,
            (select count(*)::int from report_chunk where case_id = %s) as chunks
        """,
        (slide_id, case_id),
    )
    if row is None:
        return 0, 0
    return int(row["patches"]), int(row["chunks"])


def _submit_locked(
    conn: Connection,
    dataset: str,
    slide_path: str,
    requested_by: str | None,
) -> IngestionJob:
    rows = _lock_jobs(conn, dataset, slide_path)
    active = _first(rows, "queued", "running")
    if active is not None:
        return _job(active, outcome="duplicate_active")
    ready = find_ready_slide(conn, dataset, slide_path)
    if ready is not None:
        done = _first(rows, "done")
        if done is not None:
            return _refresh_done(conn, done["id"], ready)
        failed = _first(rows, "failed")
        if failed is not None:
            return _convert_failed_to_done(conn, failed["id"], ready)
        return _insert_done(conn, dataset, slide_path, requested_by, ready)
    latest = rows[0] if rows else None
    if latest is not None and latest["status"] == "failed":
        return _requeue(conn, latest["id"])
    return _insert_queued(conn, dataset, slide_path, requested_by)


def _refresh_done(conn: Connection, job_id: UUID, ready: ReadySlide) -> IngestionJob:
    conn.execute(
        """
        update ingestion_job
        set status = 'done',
            error = null,
            case_id = %s,
            slide_id = %s,
            counts = %s,
            finished_at = coalesce(finished_at, now())
        where id = %s
        """,
        (
            ready.case_id,
            ready.slide_id,
            Jsonb({"patches": ready.patches, "chunks": ready.chunks}),
            job_id,
        ),
    )
    return _require(conn, job_id, "already_ingested")


def _convert_failed_to_done(conn: Connection, job_id: UUID, ready: ReadySlide) -> IngestionJob:
    finish_already_ready(conn, job_id, ready)
    return _require(conn, job_id, "already_ingested")


def _insert_done(
    conn: Connection,
    dataset: str,
    slide_path: str,
    requested_by: str | None,
    ready: ReadySlide,
) -> IngestionJob:
    now = _now()
    history = [
        {
            "stage": "index",
            "started_at": now,
            "finished_at": now,
            "detail": "slide already ready; no stages repeated",
        }
    ]
    inserted = conn.execute(
        """
        insert into ingestion_job (
            dataset, slide_path, case_id, slide_id, requested_by, status, stage,
            stage_history, counts, attempts, finished_at
        ) values (
            %s, %s, %s, %s, %s, 'done', 'index',
            %s, %s, 0, now()
        )
        returning id
        """,
        (
            dataset,
            slide_path,
            ready.case_id,
            ready.slide_id,
            requested_by,
            Jsonb(history),
            Jsonb({"patches": ready.patches, "chunks": ready.chunks}),
        ),
    ).fetchone()
    if inserted is None:
        raise RuntimeError("insert of a finished ingestion job returned no id")
    return _require(conn, inserted[0], "already_ingested")


def _requeue(conn: Connection, job_id: UUID) -> IngestionJob:
    updated = conn.execute(
        """
        update ingestion_job
        set status = 'queued',
            stage = null,
            error = null,
            started_at = null,
            finished_at = null,
            worker_id = null
        where id = %s and status = 'failed'
        returning id
        """,
        (job_id,),
    ).fetchone()
    if updated is None:
        raise RuntimeError("failed ingestion job could not be queued again")
    return _require(conn, job_id, "retried")


def _insert_queued(
    conn: Connection,
    dataset: str,
    slide_path: str,
    requested_by: str | None,
) -> IngestionJob:
    inserted = conn.execute(
        """
        insert into ingestion_job (
            dataset, slide_path, requested_by, status, stage, stage_history, attempts
        ) values (%s, %s, %s, 'queued', null, '[]'::jsonb, 0)
        returning id
        """,
        (dataset, slide_path, requested_by),
    ).fetchone()
    if inserted is None:
        raise RuntimeError("insert of a queued ingestion job returned no id")
    return _require(conn, inserted[0], "created")


def _require(conn: Connection, job_id: UUID, outcome: JobOutcome) -> IngestionJob:
    job = get_job(conn, job_id)
    if job is None:
        raise RuntimeError("ingestion job disappeared")
    return job.model_copy(update={"outcome": outcome})


def _lock_jobs(conn: Connection, dataset: str, slide_path: str) -> list[dict[str, object]]:
    return _fetchall(conn, _LOCK_JOBS, (dataset, slide_path))


def _first(
    rows: list[dict[str, object]],
    *statuses: str,
) -> dict[str, object] | None:
    allowed = set(statuses)
    for row in rows:
        if row["status"] in allowed:
            return row
    return None


def _history(conn: Connection, job_id: UUID) -> list[dict[str, object]]:
    row = _fetchone(conn, "select stage_history from ingestion_job where id = %s", (job_id,))
    if row is None:
        raise RuntimeError("ingestion job disappeared")
    raw = row["stage_history"] or []
    if not isinstance(raw, list):
        raise RuntimeError("stage_history is not a list")
    return [dict(item) for item in raw if isinstance(item, dict)]


def _counts_json(patches: int | None, chunks: int | None) -> Jsonb | None:
    if patches is None and chunks is None:
        return None
    return Jsonb({"patches": patches, "chunks": chunks})


def _job(row: dict[str, object], *, outcome: JobOutcome | None = None) -> IngestionJob:
    raw_counts = row["counts"]
    counts: IngestionCounts | None
    if isinstance(raw_counts, dict):
        counts = IngestionCounts.model_validate(
            {"patches": raw_counts.get("patches"), "chunks": raw_counts.get("chunks")}
        )
    else:
        counts = None
    requested: dict[str, object] | None = None
    if row["requester_id"] is not None:
        requested = {
            "id": row["requester_id"],
            "name": row["requester_name"],
            "primary_specialty": row["requester_specialty"],
            "is_synthetic": bool(row["requester_synthetic"]),
        }
    history = row["stage_history"] if isinstance(row["stage_history"], list) else []
    return IngestionJob.model_validate(
        {
            "id": row["id"],
            "dataset": row["dataset"],
            "slide_path": row["slide_path"],
            "case_id": row["case_id"],
            "slide_id": row["slide_id"],
            "requested_by": requested,
            "status": row["status"],
            "stage": row["stage"],
            "stage_history": history,
            "counts": counts,
            "error": row["error"],
            "attempts": row["attempts"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "outcome": outcome,
        }
    )


def _fetchone(
    conn: Connection,
    query: str,
    params: tuple[object, ...],
) -> dict[str, object] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    return row


def _fetchall(
    conn: Connection,
    query: str,
    params: tuple[object, ...],
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _one_line(message: str) -> str:
    text = " ".join(message.split())
    lowered = text.lower()
    if "://" in text or "password" in lowered:
        return "ingestion failed"
    if len(text) > 500:
        return text[:500]
    return text
