"""Pipeline CLI: manifest, slide download, TRIDENT extract, and stage-7 reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.embed import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.embed.text import EmbedError, TextEncoders  # pragma: allowlist secret
from consilium.pipeline.download import DownloadResult, download_cohort  # pragma: allowlist secret
from consilium.pipeline.extract import (  # pragma: allowlist secret
    SEGMENTERS,
    ExtractResult,
    extract_cohort,
)
from consilium.pipeline.gdc import GdcClient  # pragma: allowlist secret
from consilium.pipeline.manifest import (  # pragma: allowlist secret
    ManifestResult,
    build_manifest,
    load_hit_file,
)
from consilium.pipeline.reports import ensure_reports_csv  # pragma: allowlist secret
from consilium.pipeline.stage_reports import (  # pragma: allowlist secret
    Stage7Result,
    encode_concept_parquet,
    run_reports,
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
    _add_encode_concepts_parser(subcommands)
    return parser


def _add_data_root(parser: argparse.ArgumentParser, *, help_text: str) -> None:
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help=help_text,
    )


def _add_download_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    download = subcommands.add_parser(
        "download",
        help="Download manifest slides from the GDC to data/slides/{slide_id}.svs",
    )
    _add_data_root(download, help_text="Data root. Default: <repo>/data (git-ignored).")
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
    _add_data_root(reports, help_text="Data root. Default: <repo>/data (git-ignored).")
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


def _add_encode_concepts_parser(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    concepts = subcommands.add_parser(
        "encode-concepts",
        help="Fill concept.parquet embeddings with the CONCH-Z text tower",
    )
    _add_data_root(concepts, help_text="Data root. Default: <repo>/data (git-ignored).")
    concepts.add_argument("--encoder", choices=("hf", "mock"), default="hf")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            result: ManifestResult | DownloadResult | ExtractResult | Stage7Result = _run_manifest(
                args
            )
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
        else:
            parser.print_help()
            return 2
    except (OSError, RuntimeError, ValueError, EmbedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.summary(), end="")
    if getattr(result, "failed", 0):
        return 1
    return 0


def _encoders(kind: str) -> TextEncoders:
    if kind == "mock":
        return build_text_encoders(backend=MockTextEncoder())
    return build_text_encoders(get_settings())


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


def _run_extract(args: argparse.Namespace) -> ExtractResult:
    data_root = _data_root(args)
    return extract_cohort(
        cohort_csv=_cohort_path(args, data_root),
        data_root=data_root,
        gpu=args.gpu,
        segmenter=args.segmenter,
        trident_executable=args.trident,
    )


if __name__ == "__main__":
    raise SystemExit(main())
