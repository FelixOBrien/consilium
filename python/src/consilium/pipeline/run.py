"""Run every ingestion stage in order.

``reports`` runs before ``export`` so the export can read synthetic
``patient_id`` and ``in_corpus`` from ``path_case.parquet`` and can refresh
``concept.parquet`` without dropping the stage-7 concept rows. Concept
embeddings are encoded in ``reports`` and written again by ``export``, so the
file that ``load`` reads has a non-null 768-d vector on every concept.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    TextEncoders,
    build_text_encoders,
    require_hf_token,
)
from consilium.pipeline.download import DownloadResult, download_cohort  # pragma: allowlist secret
from consilium.pipeline.export import ExportResult, export_cohort  # pragma: allowlist secret
from consilium.pipeline.extract import ExtractResult, extract_cohort  # pragma: allowlist secret
from consilium.pipeline.gdc import GdcClient  # pragma: allowlist secret
from consilium.pipeline.load import LoadResult, load_parquet  # pragma: allowlist secret
from consilium.pipeline.manifest import ManifestResult, build_manifest  # pragma: allowlist secret
from consilium.pipeline.project import (  # pragma: allowlist secret
    LinearProjector,
    ProjectResult,
    fetch_proj_contrast,
    project_cohort,
)
from consilium.pipeline.reports import ensure_reports_csv  # pragma: allowlist secret
from consilium.pipeline.stage_reports import Stage7Result, run_reports  # pragma: allowlist secret
from consilium.pipeline.thumbs import ThumbsResult, thumbs_cohort  # pragma: allowlist secret

StageResult = (
    ManifestResult
    | DownloadResult
    | ExtractResult
    | Stage7Result
    | ProjectResult
    | ThumbsResult
    | ExportResult
    | LoadResult
)


@dataclass(frozen=True)
class RunResult:
    """Summaries from each stage, in the order they ran."""

    tier: str
    failed: int
    parts: tuple[str, ...]

    def summary(self) -> str:
        return "".join(self.parts)


def run_pipeline(
    *,
    tier: str,
    seed: int = 0,
    gpu: int = 0,
    workers: int = 4,
    replace_fixtures: bool = False,
    data_root: Path | None = None,
    max_slide_gb: float = 1.0,
    reports_csv: Path | None = None,
    database_url: str | None = None,
    encoders: TextEncoders | None = None,
) -> RunResult:
    """Manifest, download, extract, reports, project, thumbs, export, load."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    root = data_root if data_root is not None else repo_root() / "data"
    shared = _EncoderCache(encoders)
    failed = 0
    parts: list[str] = []
    failed += _capture(
        parts,
        "manifest",
        run_manifest_stage(
            root,
            tier=tier,
            seed=seed,
            max_slide_gb=max_slide_gb,
            reports_csv=reports_csv,
        ),
    )
    failed += _capture(parts, "download", run_download_stage(root, workers=workers))
    failed += _capture(parts, "extract", run_extract_stage(root, gpu=gpu))
    failed += _capture(
        parts,
        "reports",
        run_reports_stage(root, reports_csv=reports_csv, encoders=shared.get),
    )
    failed += _capture(parts, "project", run_project_stage(root))
    failed += _capture(parts, "thumbs", run_thumbs_stage(root))
    failed += _capture(parts, "export", run_export_stage(root, encoders=shared.get))
    failed += _capture(
        parts,
        "load",
        run_load_stage(root, database_url=database_url, replace_fixtures=replace_fixtures),
    )
    return RunResult(tier=tier, failed=failed, parts=tuple(parts))


class _EncoderCache:
    def __init__(self, explicit: TextEncoders | None) -> None:
        self._explicit = explicit
        self._built: TextEncoders | None = None

    def get(self) -> TextEncoders:
        if self._explicit is not None:
            return self._explicit
        if self._built is None:
            self._built = build_text_encoders(get_settings())
        return self._built


def run_manifest_stage(
    data_root: Path,
    *,
    tier: str,
    seed: int,
    max_slide_gb: float,
    reports_csv: Path | None,
) -> ManifestResult:
    reports_path = reports_csv
    if reports_path is None:
        reports_path = data_root / "source" / "TCGA_Reports.csv"
        ensure_reports_csv(reports_path)
    elif not reports_path.is_file():
        raise ValueError(f"reports file not found: {reports_path}")
    client = GdcClient()
    return build_manifest(
        tier=tier,
        seed=seed,
        max_slide_gb=max_slide_gb,
        slides=client.fetch_slides(),
        cases=client.fetch_cases(),
        reports_csv=reports_path,
        data_root=data_root,
    )


def run_download_stage(data_root: Path, *, workers: int) -> DownloadResult:
    return download_cohort(
        cohort_csv=data_root / "cohort" / "cohort.csv",
        data_root=data_root,
        workers=workers,
    )


def run_extract_stage(data_root: Path, *, gpu: int) -> ExtractResult:
    return extract_cohort(
        cohort_csv=data_root / "cohort" / "cohort.csv",
        data_root=data_root,
        gpu=gpu,
    )


def run_reports_stage(
    data_root: Path,
    *,
    reports_csv: Path | None,
    encoders: Callable[[], TextEncoders],
) -> Stage7Result:
    """Stage 7. Concept prompts are encoded here, before export refreshes them."""
    reports_path = reports_csv or (data_root / "source" / "TCGA_Reports.csv")
    if not reports_path.is_file():
        ensure_reports_csv(reports_path)
    return run_reports(
        data_root,
        reports_csv=reports_path,
        roster_path=None,
        encoders=encoders(),
        encode_concepts=True,
    )


def run_project_stage(data_root: Path) -> ProjectResult:
    weight = fetch_proj_contrast(require_hf_token(get_settings()))
    projector = LinearProjector(weight, name="visual.proj_contrast")
    return project_cohort(
        cohort_csv=data_root / "cohort" / "cohort.csv",
        data_root=data_root,
        projector=projector,
    )


def run_thumbs_stage(data_root: Path) -> ThumbsResult:
    return thumbs_cohort(
        cohort_csv=data_root / "cohort" / "cohort.csv",
        data_root=data_root,
    )


def run_export_stage(
    data_root: Path,
    *,
    encoders: Callable[[], TextEncoders],
) -> ExportResult:
    """Stage 8. Reads ``path_case.parquet`` and keeps every stage-7 concept row."""
    return export_cohort(
        cohort_csv=data_root / "cohort" / "cohort.csv",
        data_root=data_root,
        text_encoder=encoders(),
    )


def run_load_stage(
    data_root: Path,
    *,
    database_url: str | None,
    replace_fixtures: bool,
) -> LoadResult:
    return load_parquet(
        data_root / "export",
        database_url=database_url,
        replace_fixtures=replace_fixtures,
    )


def _capture(parts: list[str], name: str, result: StageResult) -> int:
    text = result.summary()
    if not text.endswith("\n"):
        text += "\n"
    parts.append(f"stage {name}\n{text}")
    return int(getattr(result, "failed", 0) or 0)
