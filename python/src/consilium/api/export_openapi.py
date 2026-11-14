"""Write the OpenAPI document. No database is required."""

from __future__ import annotations

import argparse
from pathlib import Path

from consilium.api.openapi import export_openapi  # pragma: allowlist secret


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write the Consilium OpenAPI document. "  # pragma: allowlist secret
            "Research prototype. Not for clinical use. No database is required."
        )
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    export_openapi(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
