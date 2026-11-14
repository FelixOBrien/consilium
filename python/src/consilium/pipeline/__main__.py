"""Pipeline CLI. `manifest` is stage 1. `reports` and `encode-concepts` are stage 7."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.embed import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.embed.text import EmbedError, TextEncoders  # pragma: allowlist secret
from consilium.pipeline.gdc import GdcClient  # pragma: allowlist secret
from consilium.pipeline.manifest import (  # pragma: allowlist secret
    ManifestResult,
    build_manifest,
    load_hit_file,
)
from consilium.pipeline.reports import ensure_reports_csv  # pragma: allowlist secret
from consilium.pipeline.stage_reports import (  # pragma: allowlist secret
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

    reports = subcommands.add_parser(
        "reports",
        help="Stage 7: patients, reports, authorship, chunks, and concept prompts",
    )
    _add_data_root(reports)
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
    _add_data_root(concepts)
    concepts.add_argument("--encoder", choices=("hf", "mock"), default="hf")
    return parser


def _add_data_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root. Default: <repo>/data (git-ignored).",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            result = _run_manifest(args)
            print(result.summary(), end="")
            return 0
        if args.command == "reports":
            built = _run_reports(args)
            print(built.summary(), end="")
            return 0
        if args.command == "encode-concepts":
            count = _run_encode_concepts(args)
            print(f"concepts_encoded {count}")
            return 0
    except (OSError, RuntimeError, ValueError, EmbedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


def _encoders(kind: str) -> TextEncoders:
    if kind == "mock":
        return build_text_encoders(backend=MockTextEncoder())
    return build_text_encoders(get_settings())


def _data_root(args: argparse.Namespace) -> Path:
    if args.data_root is not None:
        return args.data_root
    return repo_root() / "data"


def _run_reports(args: argparse.Namespace):
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


if __name__ == "__main__":
    raise SystemExit(main())
