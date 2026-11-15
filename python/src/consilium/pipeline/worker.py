"""Pull worker for one-slide ingestion jobs.

The API only inserts `ingestion_job` rows. This process claims them, resolves
GDC metadata and the TCGA report, and runs the existing pipeline stages.
New rows land in the existing HNSW and GIN indexes; nothing is rebuilt.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from psycopg import Connection

from consilium.api.schemas.ingestion import IngestionJob  # pragma: allowlist secret
from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.db.connection import connect, resolve_database_url  # pragma: allowlist secret
from consilium.db.ingestion import (  # pragma: allowlist secret
    begin_stage,
    claim_next_job,
    find_ready_slide,
    finish_already_ready,
    finish_stage,
    mark_done,
    record_failure,
    refresh_search_indexes,
    slide_counts,
)
from consilium.embed.text import (  # pragma: allowlist secret
    TextEncoders,
    build_text_encoders,
    require_hf_token,
)
from consilium.pipeline.cohort import PROJECT_SPECIALTY  # pragma: allowlist secret
from consilium.pipeline.download import download_cohort  # pragma: allowlist secret
from consilium.pipeline.export import export_cohort  # pragma: allowlist secret
from consilium.pipeline.extract import extract_cohort, features_h5_path  # pragma: allowlist secret
from consilium.pipeline.gdc import (  # pragma: allowlist secret
    CASE_FIELDS,
    SLIDE_FIELDS,
    GdcClient,
    index_cases,
    parse_slide,
)
from consilium.pipeline.load import load_parquet  # pragma: allowlist secret
from consilium.pipeline.manifest import (  # pragma: allowlist secret
    CohortRow,
    write_cases_parquet,
    write_cohort_csv,
)
from consilium.pipeline.project import (  # pragma: allowlist secret
    LinearProjector,
    fetch_proj_contrast,
    project_cohort,
)
from consilium.pipeline.reports import ensure_reports_csv, load_reports  # pragma: allowlist secret
from consilium.pipeline.stage_reports import run_reports  # pragma: allowlist secret
from consilium.pipeline.thumbs import thumbs_cohort  # pragma: allowlist secret

STAGES: tuple[str, ...] = (
    "download",
    "segment",
    "embed",
    "project",
    "thumbnails",
    "reports",
    "load",
    "index",
)

_FILE_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_Outcome = Literal["idle", "done", "failed"]


@dataclass
class JobContext:
    """Mutable progress a stage may fill in before it returns."""

    job_id: UUID
    dataset: str
    slide_path: str
    data_root: Path
    database_url: str
    case_id: str | None = None
    slide_id: str | None = None
    patches: int | None = None
    chunks: int | None = None
    reports_csv: Path | None = None
    gpu: int = 0


class StageRunner(Protocol):
    def run(self, stage: str, ctx: JobContext) -> str: ...


class LiveStages:
    """Stages 2 to 9 for one slide, calling the bulk pipeline functions."""

    def __init__(
        self,
        *,
        gpu: int = 0,
        reports_csv: Path | None = None,
        gdc: GdcClient | None = None,
    ) -> None:
        self.gpu = gpu
        self.reports_csv = reports_csv
        self.gdc = gdc if gdc is not None else GdcClient()
        self._encoders: TextEncoders | None = None
        self._projector: LinearProjector | None = None

    def run(self, stage: str, ctx: JobContext) -> str:
        if stage == "download":
            return self._download(ctx)
        if stage == "segment":
            return self._segment(ctx)
        if stage == "embed":
            return self._embed(ctx)
        if stage == "project":
            return self._project(ctx)
        if stage == "thumbnails":
            return self._thumbnails(ctx)
        if stage == "reports":
            return self._reports(ctx)
        if stage == "load":
            return self._load(ctx)
        if stage == "index":
            return self._index(ctx)
        raise RuntimeError(f"unknown ingestion stage {stage}")

    def _download(self, ctx: JobContext) -> str:
        reports_path = ctx.reports_csv or self.reports_csv
        if reports_path is None:
            raise RuntimeError("TCGA reports path is not set")
        row = resolve_cohort_row(self.gdc, ctx.dataset, ctx.slide_path, reports_path)
        ctx.case_id = row.case_id
        ctx.slide_id = row.slide_id
        ctx.reports_csv = reports_path
        cohort_csv = ctx.data_root / "cohort" / "cohort.csv"
        write_cohort_csv(cohort_csv, [row])
        write_cases_parquet(ctx.data_root / "source" / "gdc_cases.parquet", [row])
        result = download_cohort(cohort_csv=cohort_csv, data_root=ctx.data_root, workers=1)
        _require_success(result, "download")
        return f"slide {row.slide_id} file {row.file_name}"

    def _segment(self, ctx: JobContext) -> str:
        result = extract_cohort(
            cohort_csv=_cohort_csv(ctx),
            data_root=ctx.data_root,
            gpu=ctx.gpu,
        )
        _require_success(result, "segment")
        ctx.patches = result.total_patches
        return f"segmented {result.total_patches} patches"

    def _embed(self, ctx: JobContext) -> str:
        slide_id = _require_slide(ctx)
        path = features_h5_path(ctx.data_root / "trident", slide_id)
        if not path.is_file():
            raise RuntimeError(f"features were not written for {slide_id}")
        count = ctx.patches if ctx.patches is not None else 0
        return f"embedded {count} patches"

    def _project(self, ctx: JobContext) -> str:
        result = project_cohort(
            cohort_csv=_cohort_csv(ctx),
            data_root=ctx.data_root,
            projector=self._projection(),
        )
        _require_success(result, "project")
        ctx.patches = result.total_patches
        return f"projected {result.total_patches} patches"

    def _thumbnails(self, ctx: JobContext) -> str:
        result = thumbs_cohort(cohort_csv=_cohort_csv(ctx), data_root=ctx.data_root)
        _require_success(result, "thumbnails")
        return f"thumbnails {result.total_patches} patches"

    def _reports(self, ctx: JobContext) -> str:
        reports_path = ctx.reports_csv or self.reports_csv
        if reports_path is None:
            raise RuntimeError("TCGA reports path is not set")
        result = run_reports(
            ctx.data_root,
            reports_csv=reports_path,
            roster_path=None,
            encoders=self._text_encoders(),
            encode_concepts=True,
        )
        ctx.chunks = len(result.chunks)
        if ctx.case_id is None and result.cases:
            ctx.case_id = result.cases[0].id
        return f"report chunks {ctx.chunks}"

    def _load(self, ctx: JobContext) -> str:
        exported = export_cohort(
            cohort_csv=_cohort_csv(ctx),
            data_root=ctx.data_root,
            text_encoder=self._text_encoders(),
        )
        _require_success(exported, "load")
        result = load_parquet(ctx.data_root / "export", database_url=ctx.database_url)
        _remember_counts(ctx)
        return f"loaded {result.slides_loaded} slides"

    def _index(self, ctx: JobContext) -> str:
        conn = connect(ctx.database_url)
        try:
            detail = refresh_search_indexes(conn)
            if ctx.slide_id and ctx.case_id:
                ctx.patches, ctx.chunks = slide_counts(conn, ctx.slide_id, ctx.case_id)
            conn.commit()
        finally:
            conn.close()
        return detail

    def _projection(self) -> LinearProjector:
        if self._projector is None:
            weight = fetch_proj_contrast(require_hf_token(get_settings()))
            self._projector = LinearProjector(weight, name="visual.proj_contrast")
        return self._projector

    def _text_encoders(self) -> TextEncoders:
        if self._encoders is None:
            self._encoders = build_text_encoders(get_settings())
        return self._encoders


def resolve_cohort_row(
    client: GdcClient,
    dataset: str,
    slide_path: str,
    reports_csv: Path,
) -> CohortRow:
    """Join one GDC slide and case to its TCGA report text."""
    project = dataset.strip()
    if project not in PROJECT_SPECIALTY:
        raise RuntimeError(f"unknown TCGA project {project}")
    slide_hits = client.fetch_filtered(
        "files",
        slide_lookup_filters(project, slide_path.strip()),
        SLIDE_FIELDS,
        size=5,
    )
    slides = []
    for hit in slide_hits:
        parsed, _reason = parse_slide(hit)
        if parsed is not None and parsed.project_id == project:
            slides.append(parsed)
    if not slides:
        raise RuntimeError(f"no open diagnostic slide {slide_path} in {project}")
    slide = sorted(slides, key=lambda item: (item.file_name, item.file_id))[0]
    case_hits = client.fetch_filtered(
        "cases",
        case_lookup_filters(project, slide.submitter_id),
        CASE_FIELDS,
        size=5,
    )
    clinical, _corrupt = index_cases(case_hits)
    case = clinical.get(slide.submitter_id)
    if case is None or not case.primary_diagnosis:
        raise RuntimeError(f"no primary diagnosis for {slide.submitter_id}")
    if not reports_csv.is_file():
        ensure_reports_csv(reports_csv)
    reports, _corrupt_reports = load_reports(reports_csv)
    text = reports.get(slide.submitter_id)
    if text is None or not text.strip():
        raise RuntimeError(f"no TCGA report for {slide.submitter_id}")
    specialty = PROJECT_SPECIALTY[project]
    case_id = f"{specialty}-{slide.submitter_id}"
    return CohortRow(
        case_id=case_id,
        slide_id=f"{case_id}-s1",
        gdc_file_id=slide.file_id,
        file_name=slide.file_name,
        file_size=slide.file_size,
        project_id=project,
        specialty=specialty,
        tier="demo",
        held_out=False,
        submitter_id=slide.submitter_id,
        gdc_case_id=case.gdc_case_id,
        patient_sex=case.patient_sex,
        patient_age=case.patient_age,
        primary_diagnosis=case.primary_diagnosis,
        morphology=case.morphology,
        icd10=case.icd10,
        classification_of_tumor=case.classification_of_tumor or "primary",
    )


def slide_lookup_filters(project_id: str, slide_path: str) -> dict[str, object]:
    """GDC `files` filter for one open diagnostic slide in a TCGA project."""
    field = "file_id" if _FILE_ID.match(slide_path) else "file_name"
    return {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "cases.project.project_id", "value": project_id}},
            {"op": "=", "content": {"field": field, "value": slide_path}},
            {"op": "=", "content": {"field": "data_type", "value": "Slide Image"}},
            {"op": "=", "content": {"field": "experimental_strategy", "value": "Diagnostic Slide"}},
            {"op": "=", "content": {"field": "access", "value": "open"}},
        ],
    }


def case_lookup_filters(project_id: str, submitter_id: str) -> dict[str, object]:
    return {
        "op": "and",
        "content": [
            {"op": "=", "content": {"field": "project.project_id", "value": project_id}},
            {"op": "=", "content": {"field": "submitter_id", "value": submitter_id}},
        ],
    }


def run_worker(
    *,
    once: bool = False,
    poll_interval: float = 2.0,
    worker_id: str | None = None,
    data_dir: Path | None = None,
    database_url: str | None = None,
    gpu: int = 0,
    reports_csv: Path | None = None,
    stages: StageRunner | None = None,
) -> int:
    """Poll until interrupted. `--once` claims at most one job and returns."""
    if poll_interval < 0:
        raise ValueError("poll interval must be >= 0")
    url = resolve_database_url(database_url)
    root = data_dir if data_dir is not None else repo_root() / "data"
    root.mkdir(parents=True, exist_ok=True)
    identity = (worker_id or "").strip() or f"{socket.gethostname()}-{os.getpid()}"
    if not identity:
        raise ValueError("worker_id is required")
    runner = stages if stages is not None else LiveStages(gpu=gpu, reports_csv=reports_csv)
    while True:
        try:
            outcome = _poll_once(
                url,
                identity,
                root,
                runner,
                gpu,
                reports_csv,
            )
        except Exception as exc:
            if once:
                raise
            print(f"error: {_public_message(exc)}", file=sys.stderr, flush=True)
            time.sleep(poll_interval)
            continue
        if once:
            return 1 if outcome == "failed" else 0
        if outcome == "idle":
            time.sleep(poll_interval)


def _poll_once(
    url: str,
    worker_id: str,
    data_dir: Path,
    stages: StageRunner,
    gpu: int,
    reports_csv: Path | None,
) -> _Outcome:
    conn = connect(url)
    try:
        job = claim_next_job(conn, worker_id)
        if job is None:
            conn.rollback()
            return "idle"
        conn.commit()
        print(
            f"claimed {job.id} {job.dataset} {job.slide_path} attempt {job.attempts}",
            flush=True,
        )
        failed = _run_claimed(conn, job, data_dir, stages, gpu, reports_csv, url)
        return "failed" if failed else "done"
    finally:
        conn.close()


def _run_claimed(
    conn: Connection,
    job: IngestionJob,
    data_dir: Path,
    stages: StageRunner,
    gpu: int,
    reports_csv: Path | None,
    database_url: str,
) -> bool:
    db = conn
    current = "download"
    ctx = JobContext(
        job_id=job.id,
        dataset=job.dataset,
        slide_path=job.slide_path,
        data_root=data_dir / "jobs" / str(job.id),
        database_url=database_url,
        reports_csv=reports_csv or (data_dir / "source" / "TCGA_Reports.csv"),
        gpu=gpu,
    )
    try:
        ready = find_ready_slide(db, job.dataset, job.slide_path)
        if ready is not None:
            finish_already_ready(db, job.id, ready)
            db.commit()
            print(f"job {job.id} already ready {ready.slide_id}", flush=True)
            return False
        ctx.data_root.mkdir(parents=True, exist_ok=True)
        for stage in STAGES:
            current = stage
            begin_stage(db, job.id, stage)
            db.commit()
            print(f"job {job.id} stage {stage}", flush=True)
            detail = stages.run(stage, ctx)
            finish_stage(
                db,
                job.id,
                detail,
                case_id=ctx.case_id,
                slide_id=ctx.slide_id,
                patches=ctx.patches,
                chunks=ctx.chunks,
            )
            db.commit()
        mark_done(
            db,
            job.id,
            case_id=ctx.case_id,
            slide_id=ctx.slide_id,
            patches=ctx.patches,
            chunks=ctx.chunks,
        )
        db.commit()
        print(f"job {job.id} done", flush=True)
        return False
    except Exception as exc:
        db.rollback()
        message = _public_message(exc)
        record_failure(db, job.id, current, message)
        db.commit()
        print(f"job {job.id} failed at {current}: {message}", file=sys.stderr, flush=True)
        return True


def _cohort_csv(ctx: JobContext) -> Path:
    path = ctx.data_root / "cohort" / "cohort.csv"
    if not path.is_file():
        raise RuntimeError("cohort.csv was not written; download did not finish")
    return path


def _require_slide(ctx: JobContext) -> str:
    if not ctx.slide_id:
        raise RuntimeError("slide id was not resolved")
    return ctx.slide_id


def _remember_counts(ctx: JobContext) -> None:
    if not ctx.slide_id or not ctx.case_id:
        return
    conn = connect(ctx.database_url)
    try:
        ctx.patches, ctx.chunks = slide_counts(conn, ctx.slide_id, ctx.case_id)
        conn.rollback()
    finally:
        conn.close()


def _require_success(result: object, label: str) -> None:
    failed = int(getattr(result, "failed", 0) or 0)
    if failed:
        summary = getattr(result, "summary", None)
        detail = summary() if callable(summary) else label
        raise RuntimeError(f"{label} failed: {_public_message(detail)}")


def _public_message(exc: object) -> str:
    text = " ".join(str(exc).split())
    lowered = text.lower()
    if "://" in text or "password" in lowered:
        return "ingestion failed"
    if len(text) > 500:
        return text[:500]
    return text or "ingestion failed"
