from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. `serve` runs the API. Ingestion stages are not implemented here."""
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

    pipeline = subcommands.add_parser(
        "pipeline",
        help="Offline ingestion entrypoint (stages are not implemented yet)",
        description=(
            "Ingestion stages ship with the pipeline work. "
            "This command does not download slides, embed tissue, or write to the database."
        ),
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
    if args.command == "pipeline":
        pipeline.print_help()
        return 0
    parser.print_help()
    return 0
