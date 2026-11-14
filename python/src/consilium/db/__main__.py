"""Load fixture data with `python -m <package>.db seed`."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m consilium.db",  # pragma: allowlist secret
        description=(
            "Database commands. Research prototype. Not a medical device and not for clinical use."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("seed", help="Load idempotent synthetic fixture data")
    args = parser.parse_args(argv)
    if args.command == "seed":
        from consilium.db.seed import run_seed_command  # pragma: allowlist secret

        return run_seed_command()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
