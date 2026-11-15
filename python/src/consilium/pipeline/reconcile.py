"""Compare parquet, Delta gold, and Postgres row counts.

Gold is optional. When ``--subset-from`` is set, Postgres is expected to match
the subset and gold is expected to match the full parquet. A mismatch is a
non-zero pipeline exit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq
from psycopg import sql

from consilium.db.connection import connect, resolve_database_url  # pragma: allowlist secret
from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ReconcileResult:
    """One row per pipeline table, plus the tables that disagreed."""

    counts: dict[str, dict[str, int | None]]
    mismatched: tuple[str, ...]
    subset: bool

    @property
    def failed(self) -> int:
        return len(self.mismatched)

    def summary(self) -> str:
        headers = ["table", "parquet", "gold", "postgres"]
        if self.subset:
            headers.append("subset")
        cells = [
            f"{header:<16}" if index == 0 else f"{header:>12}"
            for index, header in enumerate(headers)
        ]
        lines = [" ".join(cells)]
        for table in PIPELINE_TABLES:
            row = self.counts[table]
            cells = [
                f"{table:<16}",
                f"{_cell(row.get('parquet')):>12}",
                f"{_cell(row.get('gold')):>12}",
                f"{_cell(row.get('postgres')):>12}",
            ]
            if self.subset:
                cells.append(f"{_cell(row.get('subset')):>12}")
            lines.append(" ".join(cells))
        if self.mismatched:
            lines.extend(f"mismatch {name}" for name in self.mismatched)
        else:
            lines.append("mismatch none")
        return "\n".join(lines) + "\n"


def reconcile(
    export_dir: Path,
    *,
    subset_dir: Path | None = None,
    database_url: str | None = None,
    gold_counts: Mapping[str, int] | None = None,
    postgres_counts: Mapping[str, int] | None = None,
    connect_postgres: bool = True,
) -> ReconcileResult:
    """Build the side-by-side counts. Postgres is read unless counts are passed."""
    parquet_counts = count_parquet(export_dir)
    subset_counts = count_parquet(subset_dir) if subset_dir is not None else None
    if postgres_counts is None and connect_postgres:
        url = database_url if database_url is not None else resolve_database_url(None)
        postgres_counts = count_postgres(url)
    if gold_counts is not None:
        missing = [table for table in PIPELINE_TABLES if table not in gold_counts]
        if missing:
            raise ValueError(f"gold counts are missing tables: {', '.join(missing)}")

    expected_postgres = subset_counts if subset_counts is not None else parquet_counts
    mismatched: list[str] = []
    rows: dict[str, dict[str, int | None]] = {}
    for table in PIPELINE_TABLES:
        gold = None if gold_counts is None else int(gold_counts[table])
        postgres = None if postgres_counts is None else int(postgres_counts[table])
        subset_value = None if subset_counts is None else int(subset_counts[table])
        rows[table] = {
            "parquet": int(parquet_counts[table]),
            "gold": gold,
            "postgres": postgres,
            "subset": subset_value,
        }
        if postgres is not None and postgres != int(expected_postgres[table]):
            mismatched.append(table)
        elif gold is not None and gold != int(parquet_counts[table]) and table not in mismatched:
            mismatched.append(table)
    return ReconcileResult(
        counts=rows,
        mismatched=tuple(mismatched),
        subset=subset_counts is not None,
    )


def count_parquet(export_dir: Path) -> dict[str, int]:
    """Row counts from parquet metadata. Embeddings are not read."""
    directory = Path(export_dir)
    if not directory.is_dir():
        raise ValueError(f"export directory not found: {directory}")
    counts: dict[str, int] = {}
    for table in PIPELINE_TABLES:
        path = directory / PARQUET_FILES[table]
        if not path.is_file():
            raise ValueError(f"export directory is missing parquet files: {path.name}")
        metadata = pq.ParquetFile(path).metadata
        counts[table] = 0 if metadata is None else int(metadata.num_rows)
    return counts


def count_postgres(database_url: str) -> dict[str, int]:
    """Row counts from the eight pipeline tables."""
    counts: dict[str, int] = {}
    conn = connect(database_url)
    try:
        for table in PIPELINE_TABLES:
            row = conn.execute(
                sql.SQL("select count(*) from {}").format(sql.Identifier(table))
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
    finally:
        conn.close()
    return counts


def fetch_gold_counts(
    client: object,
    *,
    warehouse_id: str,
    catalog: str,
    schema: str,
) -> dict[str, int]:
    """Count ``gold_<model>`` tables through the Databricks SQL statement API."""
    catalog_name = _identifier(catalog, "catalog")
    schema_name = _identifier(schema, "schema")
    execution = getattr(client, "statement_execution", None)
    if execution is None or not hasattr(execution, "execute_statement"):
        raise RuntimeError("Databricks SQL is not configured")
    counts: dict[str, int] = {}
    for table in PIPELINE_TABLES:
        statement = f"select count(*) from {catalog_name}.{schema_name}.gold_{table}"
        response = execution.execute_statement(
            statement=statement,
            warehouse_id=warehouse_id,
            wait_timeout="50s",
        )
        _reject_failed(response)
        counts[table] = _count_cell(response)
    return counts


def _identifier(value: str, label: str) -> str:
    if not _IDENT.match(value or ""):
        raise ValueError(f"{label} is not a catalog identifier")
    return value


def _count_cell(response: object) -> int:
    result = getattr(response, "result", None)
    data = getattr(result, "data_array", None) if result is not None else None
    if data is None and isinstance(response, dict):
        nested = response.get("result", response)
        if isinstance(nested, dict):
            data = nested.get("data_array") or nested.get("data")
    if not data or not data[0] or data[0][0] is None:
        raise RuntimeError("gold count query returned no row")
    return int(data[0][0])


def _reject_failed(response: object) -> None:
    status = getattr(response, "status", None)
    state = getattr(status, "state", None)
    if state is None and isinstance(response, dict):
        state = (response.get("status") or {}).get("state")
    if str(state or "").upper() == "FAILED":
        raise RuntimeError("gold count query failed")


def _cell(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)
