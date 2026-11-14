"""Pipeline CLI: one subcommand per ingestion stage, plus ``run``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.embed import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    EmbedError,
    TextEncoders,
    require_hf_token,
)
from consilium.pipeline.download import DownloadResult, download_cohort  # pragma: allowlist secret
from consilium.pipeline.evaluate import EvalResult, run_evaluate  # pragma: allowlist secret
from consilium.pipeline.export import ExportResult, export_cohort  # pragma: allowlist secret
from consilium.pipeline.extract import (  # pragma: allowlist secret
    SEGMENTERS,
    ExtractResult,
    extract_cohort,
)
from consilium.pipeline.gdc import GdcClient  # pragma: allowlist secret
from consilium.pipeline.load import LoadResult, load_parquet  # pragma: allowlist secret
from consilium.pipeline.manifest import (  # pragma: allowlist secret
    ManifestResult,
    build_manifest,
    load_hit_file,
)
from consilium.pipeline.project import (  # pragma: allowlist secret
    LinearProjector,
    ProjectResult,
    fetch_proj_contrast,
    project_cohort,
)
from consilium.pipeline.reports import ensure_reports_csv  # pragma: allowlist secret
from consilium.pipeline.run import RunResult, run_pipeline  # pragma: allowlist secret
from consilium.pipeline.stage_reports import (  # pragma: allowlist secret
    Stage7Result,
    encode_concept_parquet,
    run_reports,
)
from consilium.pipeline.thumbs import (  # pragma: allowlist secret
    AlignmentResult,
    ThumbsResult,
    thumbs_cohort,
    verify_alignment,
)

_Result = (
    ManifestResult
    | DownloadResult
    | ExtractResult
    | ProjectResult
    | ThumbsResult
    | ExportResult
    | AlignmentResult
    | Stage7Result
    | LoadResult
    | RunResult
    | EvalResult
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="consilium.pipeline",  # pragma: allowlist secret
        description=(
            "Ingestion tooling. Research prototype. "
            "Not a medical device and not for clinical use."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    manifest = subcommands.add_parser(
        "manifest",
        help="Build the stage-1 cohort manifest from GDC and TCGA-Reports",
    )
    manifest.add_argument("--tier", required=True, choices=("smoke", "demo", "stretch"))
    manifest.add_argument("--max-slide-gb", type=float, default=1.0)
    manifest.add_argument("--seed", type=int, default=0)
    manifest.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Output root. Default: <repo>/data (git-ignored).",
    )
    manifest.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="TCGA_Reports.csv. Downloaded into data/source when omitted and absent.",
    )
    manifest.add_argument(
        "--slides-json",
        type=Path,
        default=None,
        help="Offline GDC files payload. Requires --cases-json.",
    )
    manifest.add_argument(
        "--cases-json",
        type=Path,
        default=None,
        help="Offline GDC cases payload. Requires --slides-json.",
    )
    _add_download_parser(subcommands)
    _add_extract_parser(subcommands)
    _add_reports_parser(subcommands)
    _add_project_parser(subcommands)
    _add_thumbs_parser(subcommands)
    _add_export_parser(subcommands)
    _add_alignment_parser(subcommands)
    _add_load_parser(subcommands)
    _add_run_parser(subcommands)
    _add_evaluate_parser(subcommands)
    return parser


def _add_download_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    download = subcommands.add_parser(
        "download",
        help="Download manifest slides from the GDC to data/slides/{slide_id}.svs",
    )
    download.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root. Default: <repo>/data (git-ignored).",
    )
    download.add_argument(
        "--cohort",
        type=Path,
        default=None,
        help="Cohort CSV. Default: <data-root>/cohort/cohort.csv.",
    )
    download.add_argument("--workers", type=int, default=4, help="Concurrent downloads.")
    download.add_argument(
        "--verify-md5",
        action="store_true",
        help="Hash existing .svs files before skipping them. Fresh downloads always check MD5.",
    )
    download.add_argument("--retries", type=int, default=5)
    download.add_argument("--timeout", type=float, default=300.0)
    download.add_argument(
        "--gdc-base-url",
        default=None,
        help="GDC API origin. Default: https://api.gdc.cancer.gov.",
    )


def _add_extract_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    extract = subcommands.add_parser(
        "extract",
        help="Read SVS headers and run TRIDENT conch_v15 features into data/trident/",
    )
    extract.add_argument("--data-root", type=Path, default=None)
    extract.add_argument("--cohort", type=Path, default=None)
    extract.add_argument(
        "--gpu",
        type=int,
        default=0,
        help="GPU index passed to TRIDENT as --gpus. Use -1 for CPU.",
    )
    extract.add_argument("--segmenter", default="hest", choices=SEGMENTERS)
    extract.add_argument(
        "--trident",
        default="trident",
        help="TRIDENT executable. Default: trident on PATH.",
    )


def _add_reports_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    reports = subcommands.add_parser(
        "reports",
        help="Stage 7: patients, reports, authorship, chunks, and concept prompts",
    )
    reports.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root. Default: <repo>/data (git-ignored).",
    )
    reports.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="TCGA_Reports.csv. Downloaded into data/source when omitted and absent.",
    )
    reports.add_argument(
        "--roster",
        type=Path,
        default=None,
        help="Synthetic roster JSON. Built-in roster is used when no shared file is present.",
    )
    reports.add_argument(
        "--encode-concepts",
        action="store_true",
        help="Also encode concept prompts with the CONCH-Z text tower (needs HF_TOKEN).",
    )
    reports.add_argument("--encoder", choices=("hf", "mock"), default="hf")

    concepts = subcommands.add_parser(
        "encode-concepts",
        help="Fill concept.parquet embeddings with the CONCH-Z text tower",
    )
    concepts.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root. Default: <repo>/data (git-ignored).",
    )
    concepts.add_argument("--encoder", choices=("hf", "mock"), default="hf")


def _add_project_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    project = subcommands.add_parser(
        "project",
        help="Project conch_v15 features with CONCH-Z visual.proj_contrast",
    )
    project.add_argument("--data-root", type=Path, default=None)
    project.add_argument("--cohort", type=Path, default=None)


def _add_thumbs_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    thumbs = subcommands.add_parser(
        "thumbs",
        help="Write data/thumbs/{slide_id}.pack and per-patch JPEG offsets",
    )
    thumbs.add_argument("--data-root", type=Path, default=None)
    thumbs.add_argument("--cohort", type=Path, default=None)
    thumbs.add_argument("--thumb-side", type=int, default=224)
    thumbs.add_argument("--jpeg-quality", type=int, default=80)


def _add_export_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    export = subcommands.add_parser(
        "export",
        help="Write slide.parquet and patch.parquet, and refresh concept.parquet",
    )
    export.add_argument("--data-root", type=Path, default=None)
    export.add_argument("--cohort", type=Path, default=None)
    export.add_argument(
        "--concepts",
        type=Path,
        default=None,
        help="Concept catalog JSON. Default: the list shipped with the pipeline.",
    )


def _add_alignment_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    check = subcommands.add_parser(
        "verify-alignment",
        help="Save top thumbnails for two contrasting prompts on one slide",
    )
    check.add_argument("--slide-id", required=True)
    check.add_argument("--prompt", default="tumour cells")
    check.add_argument("--contrast", default="adipose tissue")
    check.add_argument("--top-k", type=int, default=8)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--data-root", type=Path, default=None)


def _add_load_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    load = subcommands.add_parser(
        "load",
        help="COPY parquet into Postgres, then build HNSW and GIN indexes",
    )
    load.add_argument(
        "--from",
        dest="export_dir",
        type=Path,
        required=True,
        help="Directory of pipeline parquet files, usually data/export.",
    )
    load.add_argument(
        "--replace-fixtures",
        action="store_true",
        help="Remove seeded fixture cases before loading. Other cases stay.",
    )


def _add_evaluate_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    evaluate = subcommands.add_parser(
        "evaluate",
        help="Score held-out retrieval. Research prototype, not for clinical use.",
        description=(
            "Score held-out retrieval against withheld labels read from Postgres. "
            "Research prototype, not for clinical use."
        ),
    )
    evaluate.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory for report.md and report.json. Default: <repo>/data/eval.",
    )
    evaluate.add_argument(
        "--encoder",
        choices=("hf", "mock"),
        default="hf",
        help="Text encoder for report search. mock does not download weights.",
    )


def _add_run_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    run = subcommands.add_parser(
        "run",
        help="Run manifest, download, extract, reports, project, thumbs, export, and load",
    )
    run.add_argument("--tier", required=True, choices=("smoke", "demo", "stretch"))
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--gpu", type=int, default=0, help="GPU index for TRIDENT. Use -1 for CPU.")
    run.add_argument("--workers", type=int, default=4, help="Concurrent slide downloads.")
    run.add_argument(
        "--max-slide-gb",
        type=float,
        default=1.0,
        help="Manifest size cap in decimal gigabytes.",
    )
    run.add_argument("--data-root", type=Path, default=None)
    run.add_argument(
        "--replace-fixtures",
        action="store_true",
        help="Remove seeded fixture cases before the load stage.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: _Result | int
        if args.command == "manifest":
            result = _run_manifest(args)
        elif args.command == "download":
            result = _run_download(args)
        elif args.command == "extract":
            result = _run_extract(args)
        elif args.command == "reports":
            result = _run_reports(args)
        elif args.command == "encode-concepts":
            count = _run_encode_concepts(args)
            print(f"concepts_encoded {count}")
            return 0
        elif args.command == "project":
            result = _run_project(args)
        elif args.command == "thumbs":
            result = _run_thumbs(args)
        elif args.command == "export":
            result = _run_export(args)
        elif args.command == "verify-alignment":
            result = _run_alignment(args)
        elif args.command == "load":
            result = load_parquet(args.export_dir, replace_fixtures=args.replace_fixtures)
        elif args.command == "evaluate":
            result = run_evaluate(out_dir=args.out_dir, encoder=args.encoder)
        elif args.command == "run":
            result = run_pipeline(
                tier=args.tier,
                seed=args.seed,
                gpu=args.gpu,
                workers=args.workers,
                replace_fixtures=args.replace_fixtures,
                data_root=args.data_root,
                max_slide_gb=args.max_slide_gb,
            )
        else:
            parser.print_help()
            return 2
    except (OSError, RuntimeError, ValueError, EmbedError, psycopg.Error) as exc:
        print(f"error: {_public_error(exc)}", file=sys.stderr)
        return 1
    text = result.summary()
    print(text, end="" if text.endswith("\n") else "\n")
    if getattr(result, "failed", 0):
        return 1
    return 0


def _encoders(kind: str) -> TextEncoders:
    if kind == "mock":
        return build_text_encoders(backend=MockTextEncoder())
    return build_text_encoders(get_settings())


def _run_manifest(args: argparse.Namespace) -> ManifestResult:
    data_root = _data_root(args)
    if (args.slides_json is None) != (args.cases_json is None):
        raise ValueError("pass both --slides-json and --cases-json, or neither to query the GDC")
    reports_path = args.reports
    if reports_path is None:
        reports_path = data_root / "source" / "TCGA_Reports.csv"
        ensure_reports_csv(reports_path)
    elif not reports_path.is_file():
        raise ValueError(f"reports file not found: {reports_path}")
    if args.slides_json is None:
        client = GdcClient()
        slides = client.fetch_slides()
        cases = client.fetch_cases()
    else:
        slides = load_hit_file(args.slides_json)
        cases = load_hit_file(args.cases_json)
    return build_manifest(
        tier=args.tier,
        seed=args.seed,
        max_slide_gb=args.max_slide_gb,
        slides=slides,
        cases=cases,
        reports_csv=reports_path,
        data_root=data_root,
    )


def _data_root(args: argparse.Namespace) -> Path:
    return args.data_root if args.data_root is not None else repo_root() / "data"


def _cohort_path(args: argparse.Namespace, data_root: Path) -> Path:
    if args.cohort is not None:
        return args.cohort
    return data_root / "cohort" / "cohort.csv"


def _run_download(args: argparse.Namespace) -> DownloadResult:
    data_root = _data_root(args)
    cohort_csv = _cohort_path(args, data_root)
    if args.gdc_base_url:
        return download_cohort(
            cohort_csv=cohort_csv,
            data_root=data_root,
            workers=args.workers,
            verify_md5=args.verify_md5,
            retries=args.retries,
            timeout=args.timeout,
            base_url=args.gdc_base_url,
        )
    return download_cohort(
        cohort_csv=cohort_csv,
        data_root=data_root,
        workers=args.workers,
        verify_md5=args.verify_md5,
        retries=args.retries,
        timeout=args.timeout,
    )


def _run_reports(args: argparse.Namespace) -> Stage7Result:
    data_root = _data_root(args)
    reports_path = args.reports
    if reports_path is None:
        reports_path = data_root / "source" / "TCGA_Reports.csv"
        ensure_reports_csv(reports_path)
    elif not reports_path.is_file():
        raise ValueError(f"reports file not found: {reports_path}")
    return run_reports(
        data_root,
        reports_csv=reports_path,
        roster_path=args.roster,
        encoders=_encoders(args.encoder),
        encode_concepts=args.encode_concepts,
    )


def _run_encode_concepts(args: argparse.Namespace) -> int:
    data_root = _data_root(args)
    path = data_root / "export" / "concept.parquet"
    return encode_concept_parquet(path, _encoders(args.encoder))


def _run_project(args: argparse.Namespace) -> ProjectResult:
    data_root = _data_root(args)
    weight = fetch_proj_contrast(require_hf_token(get_settings()))
    projector = LinearProjector(weight, name="visual.proj_contrast")
    return project_cohort(
        cohort_csv=_cohort_path(args, data_root),
        data_root=data_root,
        projector=projector,
    )


def _run_thumbs(args: argparse.Namespace) -> ThumbsResult:
    data_root = _data_root(args)
    return thumbs_cohort(
        cohort_csv=_cohort_path(args, data_root),
        data_root=data_root,
        thumb_side=args.thumb_side,
        jpeg_quality=args.jpeg_quality,
    )


def _run_export(args: argparse.Namespace) -> ExportResult:
    data_root = _data_root(args)
    return export_cohort(
        cohort_csv=_cohort_path(args, data_root),
        data_root=data_root,
        concepts_path=args.concepts,
    )


def _run_alignment(args: argparse.Namespace) -> AlignmentResult:
    return verify_alignment(
        data_root=_data_root(args),
        slide_id=args.slide_id,
        output_dir=args.output,
        prompt=args.prompt,
        contrast=args.contrast,
        top_k=args.top_k,
    )


def _run_extract(args: argparse.Namespace) -> ExtractResult:
    data_root = _data_root(args)
    return extract_cohort(
        cohort_csv=_cohort_path(args, data_root),
        data_root=data_root,
        gpu=args.gpu,
        segmenter=args.segmenter,
        trident_executable=args.trident,
    )


def _public_error(exc: BaseException) -> str:
    message = str(exc)
    lowered = message.lower()
    if "://" in message or "password" in lowered:
        return exc.__class__.__name__
    return message


if __name__ == "__main__":
    raise SystemExit(main())
