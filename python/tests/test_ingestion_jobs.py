"""Single-slide ingestion jobs against Postgres. Pipeline stages are scripted."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pgvector import HalfVector, Vector
from psycopg.types.json import Jsonb

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.ingestion import (  # pragma: allowlist secret
    claim_next_job,
    corpus_counts,
    refresh_search_indexes,
)
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.pipeline.__main__ import build_parser  # pragma: allowlist secret
from consilium.pipeline.worker import (  # pragma: allowlist secret
    STAGES,
    JobContext,
    case_lookup_filters,
    run_worker,
    slide_lookup_filters,
)
from consilium.seed_data import DEMO_USER_ID  # pragma: allowlist secret

READY_CASE = "breast-FX-B042A"
READY_SLIDE = "breast-FX-B042A-s1"
READY_PATH = "fixture/fixture-he-rose.svs"
FILE_ID = "11111111-2222-4333-8444-555555555555"
FILE_NAME = "TCGA-B0-0001-01Z-00-DX1.svs"
NEW_CASE = "breast-SKO273"
NEW_SLIDE = "breast-SKO273-s1"


@pytest.fixture
def api(empty_database: str, tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    app = create_app(Settings(database_url=empty_database))
    with TestClient(app) as client:
        yield client, empty_database


def test_health_reports_live_corpus_counts(api: tuple[TestClient, str]) -> None:
    client, url = api
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    with _connection(url) as conn:
        expected = corpus_counts(conn)
    assert body["cases"] == expected["cases"] > 0
    assert body["slides"] == expected["slides"] > 0
    assert body["patches"] == expected["patches"] > 0
    assert body["report_chunks"] == expected["report_chunks"] > 0


def test_active_index_prevents_duplicate_queued_jobs(api: tuple[TestClient, str]) -> None:
    _url = api[1]
    with _connection(_url) as conn:
        row = conn.execute(
            "select indexdef from pg_indexes where indexname = 'ingestion_job_active_slide'"
        ).fetchone()
    assert row is not None
    definition = str(row[0])
    assert "UNIQUE" in definition.upper() or "unique" in definition
    assert "queued" in definition
    assert "running" in definition


def test_create_lists_and_hides_worker_id(api: tuple[TestClient, str]) -> None:
    client, _url = api
    created = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-LUSC", "slide_path": "new-lusc.svs"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["outcome"] == "created"
    assert body["status"] == "queued"
    assert body["stage"] is None
    assert body["stage_history"] == []
    assert body["attempts"] == 0
    assert body["requested_by"]["id"] == DEMO_USER_ID
    assert body["requested_by"]["is_synthetic"] is True
    assert "worker_id" not in body

    listed = client.get("/api/ingestion/jobs")
    assert listed.status_code == 200
    jobs = listed.json()
    assert jobs[0]["id"] == body["id"]
    assert jobs == sorted(jobs, key=lambda job: (job["created_at"], job["id"]), reverse=True)
    assert "worker_id" not in listed.text

    one = client.get(f"/api/ingestion/jobs/{body['id']}")
    assert one.status_code == 200
    assert one.json()["outcome"] is None
    assert one.json()["slide_path"] == "new-lusc.svs"

    missing = client.get("/api/ingestion/jobs/00000000-0000-4000-8000-000000009999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    blank = client.post("/api/ingestion/jobs", json={"dataset": "TCGA-LUSC", "slide_path": "  "})
    assert blank.status_code == 422


def test_duplicate_active_job_returns_the_existing_row(api: tuple[TestClient, str]) -> None:
    client, url = api
    first = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-COAD", "slide_path": "dup.svs"},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-COAD", "slide_path": "dup.svs"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["outcome"] == "duplicate_active"
    with _connection(url) as conn:
        conn.execute(
            "update ingestion_job set status = 'running', worker_id = 'other' where id = %s",
            (first.json()["id"],),
        )
        conn.commit()
    running = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-COAD", "slide_path": "dup.svs"},
    )
    assert running.status_code == 200
    assert running.json()["id"] == first.json()["id"]
    assert running.json()["outcome"] == "duplicate_active"
    assert running.json()["status"] == "running"
    with _connection(url) as conn:
        count = conn.execute(
            """
            select count(*) from ingestion_job
            where dataset = 'TCGA-COAD' and slide_path = 'dup.svs'
            """
        ).fetchone()
    assert count is not None
    assert count[0] == 1


def test_retry_failed_job_keeps_history_and_attempts(api: tuple[TestClient, str]) -> None:
    client, url = api
    history = [
        {
            "stage": "download",
            "started_at": "2026-11-01T10:00:00+00:00",
            "finished_at": "2026-11-01T10:01:00+00:00",
            "detail": "downloaded",
        },
        {
            "stage": "embed",
            "started_at": "2026-11-01T10:02:00+00:00",
            "finished_at": "2026-11-01T10:03:00+00:00",
            "detail": "encoder failed",
        },
    ]
    with _connection(url) as conn:
        row = conn.execute(
            """
            insert into ingestion_job (
                dataset, slide_path, requested_by, status, stage, stage_history,
                counts, error, attempts, worker_id, started_at, finished_at
            ) values (
                'TCGA-STAD', 'retry.svs', %s, 'failed', 'embed', %s,
                %s, 'encoder failed', 2, 'gpu-1', now(), now()
            )
            returning id
            """,
            (DEMO_USER_ID, Jsonb(history), Jsonb({"patches": 3, "chunks": None})),
        ).fetchone()
        conn.commit()
    assert row is not None
    job_id = str(row[0])
    retried = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-STAD", "slide_path": "retry.svs"},
    )
    assert retried.status_code == 200
    body = retried.json()
    assert body["id"] == job_id
    assert body["outcome"] == "retried"
    assert body["status"] == "queued"
    assert body["stage"] is None
    assert body["error"] is None
    assert body["started_at"] is None
    assert body["finished_at"] is None
    assert body["attempts"] == 2
    assert body["counts"]["patches"] == 3
    assert [item["stage"] for item in body["stage_history"]] == ["download", "embed"]
    assert body["stage_history"][1]["detail"] == "encoder failed"
    with _connection(url) as conn:
        stored = conn.execute(
            "select worker_id, stage, error from ingestion_job where id = %s",
            (job_id,),
        ).fetchone()
    assert stored == (None, None, None)


def test_already_ready_slide_finishes_without_a_new_queue_entry(
    api: tuple[TestClient, str],
) -> None:
    client, url = api
    by_path = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": READY_PATH},
    )
    assert by_path.status_code == 200
    path_body = by_path.json()
    assert path_body["outcome"] == "already_ingested"
    assert path_body["status"] == "done"
    assert path_body["case_id"] == READY_CASE
    assert path_body["slide_id"] == READY_SLIDE
    with _connection(url) as conn:
        counts = conn.execute(
            """
            select
                (select count(*)::int from patch where slide_id = %s),
                (select count(*)::int from report_chunk where case_id = %s)
            """,
            (READY_SLIDE, READY_CASE),
        ).fetchone()
    assert counts is not None
    assert path_body["counts"] == {"patches": counts[0], "chunks": counts[1]}
    assert counts[0] > 0 and counts[1] > 0
    again = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": READY_PATH},
    )
    assert again.status_code == 200
    assert again.json()["id"] == path_body["id"]

    by_slide = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": READY_SLIDE},
    )
    assert by_slide.status_code == 200
    assert by_slide.json()["outcome"] == "already_ingested"
    assert by_slide.json()["slide_id"] == READY_SLIDE
    assert by_slide.json()["case_id"] == READY_CASE

    _insert_named_ready_slide(url)
    by_id = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": FILE_ID},
    )
    assert by_id.status_code == 200
    assert by_id.json()["outcome"] == "already_ingested"
    assert by_id.json()["status"] == "done"
    assert by_id.json()["slide_id"] == f"{READY_CASE}-s2"
    assert by_id.json()["counts"]["patches"] == 1
    by_name = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": FILE_NAME},
    )
    assert by_name.status_code == 200
    assert by_name.json()["outcome"] == "already_ingested"
    assert by_name.json()["slide_id"] == f"{READY_CASE}-s2"
    assert by_name.json()["id"] != by_id.json()["id"]


def test_failed_job_for_a_ready_slide_finishes_instead_of_retrying(
    api: tuple[TestClient, str],
) -> None:
    client, url = api
    with _connection(url) as conn:
        row = conn.execute(
            """
            insert into ingestion_job (
                dataset, slide_path, requested_by, status, stage, stage_history,
                error, attempts, finished_at
            ) values (
                'TCGA-BRCA', %s, %s, 'failed', 'download',
                %s, 'stale failure', 1, now()
            )
            returning id
            """,
            (
                READY_SLIDE,
                DEMO_USER_ID,
                Jsonb(
                    [
                        {
                            "stage": "download",
                            "started_at": "2026-11-02T00:00:00+00:00",
                            "finished_at": "2026-11-02T00:01:00+00:00",
                            "detail": "stale failure",
                        }
                    ]
                ),
            ),
        ).fetchone()
        conn.commit()
    assert row is not None
    finished = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": READY_SLIDE},
    )
    assert finished.status_code == 200
    body = finished.json()
    assert body["id"] == str(row[0])
    assert body["outcome"] == "already_ingested"
    assert body["status"] == "done"
    assert body["error"] is None
    assert body["case_id"] == READY_CASE
    assert body["slide_id"] == READY_SLIDE
    assert body["attempts"] == 1
    assert body["stage_history"][0]["detail"] == "stale failure"
    assert body["stage_history"][-1]["detail"] == "slide already ready; no stages repeated"


def test_skip_locked_claim_takes_distinct_oldest_jobs(api: tuple[TestClient, str]) -> None:
    _client, url = api
    _park_queue(url)
    older = datetime(2026, 11, 1, tzinfo=UTC)
    newer = datetime(2026, 11, 2, tzinfo=UTC)
    with _connection(url) as conn:
        first_id = _insert_queued(conn, "older.svs", older)
        second_id = _insert_queued(conn, "newer.svs", newer)
        conn.commit()
    conn_a = connect(url)
    conn_b = connect(url)
    try:
        conn_b.execute("set statement_timeout = '2s'")
        claimed_a = claim_next_job(conn_a, "worker-a")
        claimed_b = claim_next_job(conn_b, "worker-b")
        assert claimed_a is not None and claimed_b is not None
        assert claimed_a.id == first_id
        assert claimed_b.id == second_id
        assert claimed_a.attempts == 1
        assert claimed_b.attempts == 1
        conn_a.commit()
        conn_b.commit()
    finally:
        conn_a.close()
        conn_b.close()
    with _connection(url) as conn:
        stored = conn.execute(
            """
            select worker_id, status, error is null
            from ingestion_job where id = %s
            """,
            (first_id,),
        ).fetchone()
        none = claim_next_job(conn, "worker-c")
        conn.rollback()
    assert stored == ("worker-a", "running", True)
    assert none is None


def test_uncommitted_claim_is_skipped_then_returns_to_the_queue(
    api: tuple[TestClient, str],
) -> None:
    _client, url = api
    _park_queue(url)
    with _connection(url) as conn:
        job_id = _insert_queued(conn, "locked.svs", datetime(2026, 11, 3, tzinfo=UTC))
        conn.commit()
    holder = connect(url)
    try:
        held = claim_next_job(holder, "holder")
        assert held is not None and held.id == job_id
        other = connect(url)
        try:
            other.execute("set statement_timeout = '2s'")
            assert claim_next_job(other, "other") is None
            other.rollback()
        finally:
            other.close()
        holder.rollback()
    finally:
        holder.close()
    with _connection(url) as conn:
        reclaimed = claim_next_job(conn, "closer")
        assert reclaimed is not None
        assert reclaimed.id == job_id
        assert reclaimed.attempts == 1
        assert reclaimed.status == "running"
        conn.rollback()


def test_worker_records_each_stage_and_new_patch_is_searchable(
    api: tuple[TestClient, str],
) -> None:
    client, url = api
    _park_queue(url)
    created = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-BRCA", "slide_path": "sko273-new.svs"},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    before = _index_filenode(url)
    script = _Script()

    def load(ctx: JobContext) -> None:
        _insert_searchable_slide(url, ctx.case_id or NEW_CASE, ctx.slide_id or NEW_SLIDE)

    def index(ctx: JobContext) -> str:
        with _connection(url) as conn:
            detail = refresh_search_indexes(conn)
            conn.commit()
        ctx.patches, ctx.chunks = 1, 1
        return detail

    script.on_load = load
    script.on_index = index
    code = run_worker(
        once=True,
        database_url=url,
        data_dir=Path("/tmp/sko273-unused"),
        stages=script,
    )
    assert code == 0
    assert script.calls == list(STAGES)
    assert _index_filenode(url) == before

    done = client.get(f"/api/ingestion/jobs/{job_id}")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "done"
    assert body["stage"] == "index"
    assert body["error"] is None
    assert body["case_id"] == NEW_CASE
    assert body["slide_id"] == NEW_SLIDE
    assert body["counts"] == {"patches": 1, "chunks": 1}
    assert body["attempts"] == 1
    history = body["stage_history"]
    assert [item["stage"] for item in history] == list(STAGES)
    assert all(item["started_at"] and item["finished_at"] for item in history)
    assert history[-1]["detail"].startswith("indexes ready")
    assert "reindex" not in history[-1]["detail"].lower()

    query = HalfVector([1.0, *([0.0] * 767)])
    with _connection(url) as conn:
        nearest = conn.execute(
            """
            select slide_id
            from patch
            where in_corpus
            order by embedding <=> %s
            limit 1
            """,
            (query,),
        ).fetchone()
    assert nearest is not None
    assert nearest[0] == NEW_SLIDE


def test_worker_records_failure_and_retry_then_succeeds(api: tuple[TestClient, str]) -> None:
    client, url = api
    _park_queue(url)
    created = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-ESCA", "slide_path": "fails-once.svs"},
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    failing = _Script(fail_at="project")
    assert run_worker(once=True, database_url=url, stages=failing) == 1
    assert failing.calls == ["download", "segment", "embed", "project"]
    failed = client.get(f"/api/ingestion/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert failed["stage"] == "project"
    assert "project exploded" in failed["error"]
    assert failed["attempts"] == 1
    assert [item["stage"] for item in failed["stage_history"]] == [
        "download",
        "segment",
        "embed",
        "project",
    ]
    assert failed["stage_history"][-1]["finished_at"] is not None
    assert "exploded" in failed["stage_history"][-1]["detail"]

    retried = client.post(
        "/api/ingestion/jobs",
        json={"dataset": "TCGA-ESCA", "slide_path": "fails-once.svs"},
    )
    assert retried.status_code == 200
    assert retried.json()["outcome"] == "retried"
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 1
    assert len(retried.json()["stage_history"]) == 4

    succeeding = _Script()
    assert run_worker(once=True, database_url=url, stages=succeeding) == 0
    done = client.get(f"/api/ingestion/jobs/{job_id}").json()
    assert done["status"] == "done"
    assert done["error"] is None
    assert done["attempts"] == 2
    assert [item["stage"] for item in done["stage_history"][:4]] == [
        "download",
        "segment",
        "embed",
        "project",
    ]
    assert [item["stage"] for item in done["stage_history"][4:]] == list(STAGES)
    assert done["counts"]["patches"] == 4
    assert done["counts"]["chunks"] == 2


def test_worker_marks_an_already_ready_queue_row_done(api: tuple[TestClient, str]) -> None:
    client, url = api
    _park_queue(url)
    with _connection(url) as conn:
        job_id = _insert_queued(conn, READY_PATH, datetime(2026, 11, 14, tzinfo=UTC), "TCGA-BRCA")
        conn.commit()
    script = _Script(fail_at="download")
    assert run_worker(once=True, database_url=url, stages=script) == 0
    assert script.calls == []
    body = client.get(f"/api/ingestion/jobs/{job_id}").json()
    assert body["status"] == "done"
    assert body["case_id"] == READY_CASE
    assert body["slide_id"] == READY_SLIDE
    assert body["counts"]["patches"] > 0
    assert body["stage_history"][-1]["detail"] == "slide already ready; no stages repeated"


def test_worker_command_and_gdc_lookup_filters() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["worker", "--once", "--poll-interval", "0.5", "--worker-id", "box", "--gpu", "-1"]
    )
    assert args.command == "worker"
    assert args.once is True
    assert args.poll_interval == 0.5
    assert args.worker_id == "box"
    assert args.gpu == -1
    assert args.data_dir is None

    by_name = slide_lookup_filters("TCGA-BRCA", FILE_NAME)
    assert _filter_field(by_name) == "file_name"
    by_id = slide_lookup_filters("TCGA-BRCA", FILE_ID)
    assert _filter_field(by_id) == "file_id"
    case_filters = case_lookup_filters("TCGA-BRCA", "TCGA-B0-0001")
    fields = {item["content"]["field"] for item in case_filters["content"]}  # type: ignore[index]
    assert fields == {"project.project_id", "submitter_id"}


class _Script:
    def __init__(self, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[str] = []
        self.on_load: object = None
        self.on_index: object = None

    def run(self, stage: str, ctx: JobContext) -> str:
        self.calls.append(stage)
        if stage == self.fail_at:
            raise RuntimeError(f"stage {stage} exploded")
        if stage == "download":
            ctx.case_id = NEW_CASE
            ctx.slide_id = NEW_SLIDE
        if stage == "embed":
            ctx.patches = 4
        if stage == "reports":
            ctx.chunks = 2
        if stage == "project":
            _assert_progress(ctx)
        if stage == "load" and callable(self.on_load):
            self.on_load(ctx)
        if stage == "index" and callable(self.on_index):
            return str(self.on_index(ctx))
        return f"{stage} ok"


def _assert_progress(ctx: JobContext) -> None:
    from consilium.db.ingestion import get_job  # pragma: allowlist secret

    with _connection(ctx.database_url) as conn:
        job = get_job(conn, ctx.job_id)
    assert job is not None
    assert job.stage == "project"
    assert job.stage_history[-1].stage == "project"
    assert job.stage_history[-1].finished_at is None
    assert job.case_id == NEW_CASE
    assert job.slide_id == NEW_SLIDE
    if len(job.stage_history) == 4:
        assert [item.stage for item in job.stage_history] == [
            "download",
            "segment",
            "embed",
            "project",
        ]
        assert job.counts is not None
        assert job.counts.patches == 4


def _park_queue(url: str) -> None:
    with _connection(url) as conn:
        conn.execute("delete from ingestion_job where status = 'queued'")
        conn.commit()


def _insert_queued(
    conn: object,
    slide_path: str,
    created_at: datetime,
    dataset: str = "TCGA-SKCM",
) -> UUID:
    row = conn.execute(  # type: ignore[attr-defined]
        """
        insert into ingestion_job (
            dataset, slide_path, requested_by, status, stage_history, attempts, created_at
        ) values (%s, %s, %s, 'queued', '[]'::jsonb, 0, %s)
        returning id
        """,
        (dataset, slide_path, DEMO_USER_ID, created_at),
    ).fetchone()
    assert row is not None
    return row[0]


def _insert_named_ready_slide(url: str) -> None:
    vector = HalfVector([0.0, 1.0, *([0.0] * 766)])
    source = f"{FILE_ID}/{FILE_NAME}"
    with _connection(url) as conn:
        conn.execute(
            """
            insert into slide (
                id, case_id, ordinal, stain, magnification, mpp, width, height,
                patch_size, patch_count, storage_key, thumb_pack_key, source_path,
                embedding, status
            )
            select %s, case_id, 2, stain, magnification, mpp, width, height,
                   patch_size, 1, storage_key, thumb_pack_key, %s, embedding, status
            from slide where id = %s
            """,
            (f"{READY_CASE}-s2", source, READY_SLIDE),
        )
        conn.execute(
            """
            insert into patch (
                slide_id, case_id, patient_id, specialty, x, y, size, embedding,
                in_corpus, thumb_offset, thumb_length
            )
            select %s, case_id, patient_id, specialty, x, y, size, %s,
                   in_corpus, thumb_offset, thumb_length
            from patch where slide_id = %s
            order by id
            limit 1
            """,
            (f"{READY_CASE}-s2", vector, READY_SLIDE),
        )
        conn.commit()


def _insert_searchable_slide(url: str, case_id: str, slide_id: str) -> None:
    patch_vector = HalfVector([1.0, *([0.0] * 767)])
    chunk_vector = Vector([1.0, *([0.0] * 383)])
    with _connection(url) as conn:
        conn.execute(
            """
            insert into path_case (
                id, patient_id, specimen_label, source_dataset, source_case_id, specialty,
                patient_age, patient_sex, primary_diagnosis, morphology, icd10, status,
                assigned_to, accessioned_at, is_held_out, cohort_tier
            ) values (
                %s, 'pt-0042', 'biopsy', 'TCGA-BRCA', 'SKO273', 'breast',
                60, 'F', 'Invasive carcinoma of no special type', '8500/3', 'C50.9',
                'signed_out', %s, now(), false, 'demo'
            )
            """,
            (case_id, DEMO_USER_ID),
        )
        conn.execute(
            """
            insert into report (
                id, case_id, author_id, status, body, conclusion, signed_at
            ) values (%s, %s, %s, 'signed', %s, %s, now())
            """,
            (
                f"{case_id}-r1",
                case_id,
                DEMO_USER_ID,
                "Synthetic ingestion test report. Not a clinical diagnosis.",
                "Synthetic fixture interpretation.",
            ),
        )
        conn.execute(
            """
            insert into report_chunk (
                report_id, case_id, patient_id, specialty, section, ordinal, text,
                embedding, in_corpus
            ) values (%s, %s, 'pt-0042', 'breast', 'conclusion', 0, %s, %s, true)
            """,
            (
                f"{case_id}-r1",
                case_id,
                "Synthetic fixture interpretation.",
                chunk_vector,
            ),
        )
        conn.execute(
            """
            insert into slide (
                id, case_id, ordinal, stain, magnification, mpp, width, height,
                patch_size, patch_count, storage_key, thumb_pack_key, source_path,
                embedding, status
            ) values (
                %s, %s, 1, 'HE', 20, 0.5, 1024, 1024,
                512, 1, %s, %s, 'sko273/new.svs', %s, 'ready'
            )
            """,
            (
                slide_id,
                case_id,
                f"slides/{slide_id}.svs",
                f"thumbs/{slide_id}.pack",
                patch_vector,
            ),
        )
        conn.execute(
            """
            insert into patch (
                slide_id, case_id, patient_id, specialty, x, y, size, embedding,
                in_corpus, thumb_offset, thumb_length
            ) values (
                %s, %s, 'pt-0042', 'breast', 0, 0, 512, %s, true, 0, 128
            )
            """,
            (slide_id, case_id, patch_vector),
        )
        conn.commit()


def _index_filenode(url: str) -> int:
    with _connection(url) as conn:
        row = conn.execute(
            "select relfilenode from pg_class where relname = 'patch_embedding_hnsw'"
        ).fetchone()
    assert row is not None
    assert int(row[0]) > 0
    return int(row[0])


def _filter_field(filters: dict[str, object]) -> str:
    content = filters["content"]
    assert isinstance(content, list)
    for item in content:
        assert isinstance(item, dict)
        inner = item["content"]
        assert isinstance(inner, dict)
        if inner["field"] in {"file_id", "file_name"}:
            return str(inner["field"])
    raise AssertionError(filters)


class _connection:
    """Commit-or-rollback connection that always closes."""

    def __init__(self, url: str) -> None:
        self._conn = connect(url)

    def __enter__(self) -> object:
        return self._conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is None:
                return
            self._conn.rollback()
        finally:
            self._conn.close()
