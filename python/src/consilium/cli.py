from __future__ import annotations

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. `serve` runs the API. `pipeline` runs offline ingestion."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "pipeline":
        from consilium.pipeline.__main__ import main as pipeline_main  # pragma: allowlist secret

        return pipeline_main(args_list[1:])
    parser = argparse.ArgumentParser(
        prog="consilium",  # pragma: allowlist secret
        description=(
            "Consilium API and tooling. "  # pragma: allowlist secret
            "Research prototype. Not a medical device and not for clinical use."
        ),
    )
    subcommands = parser.add_subparsers(dest="command")

    serve = subcommands.add_parser("serve", help="Run the API with uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    subcommands.add_parser(
        "pipeline",
        help="Offline ingestion: manifest through load",
    )

    db = subcommands.add_parser("db", help="Apply or inspect database migrations")
    db_commands = db.add_subparsers(dest="db_command", required=True)
    db_commands.add_parser("status", help="Show which migration files are applied")
    migrate_cmd = db_commands.add_parser(
        "migrate",
        help="Apply pending migrations. Index migrations can run separately",
    )
    mode = migrate_cmd.add_mutually_exclusive_group()
    mode.add_argument(
        "--schema-only",
        action="store_true",
        help="Apply table migrations and skip HNSW and GIN indexes",
    )
    mode.add_argument(
        "--indexes-only",
        action="store_true",
        help="Apply HNSW and GIN index migrations only",
    )

    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(
            "consilium.api.app:app",  # pragma: allowlist secret
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0
    if args.command == "db":
        from consilium.db.migrate import run_db_command  # pragma: allowlist secret

        return run_db_command(args)
    parser.print_help()
    return 0
