"""Pipeline CLI. The manifest subcommand builds the stage-1 cohort."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from consilium.config import repo_root  # pragma: allowlist secret
from consilium.pipeline.gdc import GdcClient  # pragma: allowlist secret
from consilium.pipeline.manifest import (  # pragma: allowlist secret
    ManifestResult,
    build_manifest,
    load_hit_file,
)
from consilium.pipeline.reports import ensure_reports_csv  # pragma: allowlist secret


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "manifest":
        parser.print_help()
        return 2
    try:
        result = _run_manifest(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.summary(), end="")
    return 0


def _run_manifest(args: argparse.Namespace) -> ManifestResult:
    data_root = args.data_root if args.data_root is not None else repo_root() / "data"
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
