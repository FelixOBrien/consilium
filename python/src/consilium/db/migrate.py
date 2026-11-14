"""Idempotent SQL migrations.

Schema files run in a transaction per file and are recorded in `schema_migration`.
Index files (HNSW and GIN) can run separately, after a bulk load.

`SEARCH_BACKEND=pgvector` applies those indexes. `SEARCH_BACKEND=lakebase` is a
marked branch and raises: Lakebase Search index types are not created here.
This runner also refuses `LAKEBASE_DATABASE_URL` and Databricks hosts. Loading
Lakebase is SKO-280.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import psycopg
from psycopg import sql

from consilium.config import SearchBackend, get_settings, python_root  # pragma: allowlist secret
from consilium.db.connection import connect, resolve_database_url  # pragma: allowlist secret

MigrationKind = Literal["schema", "index"]

_TRACKING_TABLE = "schema_migration"
_TRACKING_SQL = """
create table if not exists schema_migration (
    filename text primary key,
    checksum text not null,
    applied_at timestamptz not null default now()
)
"""


class LakebaseMigrationRefused(RuntimeError):
    """The target database is Lakebase. SKO-255 does not migrate it."""


class LakebaseIndexesNotImplemented(RuntimeError):
    """`SEARCH_BACKEND=lakebase` index types are intentionally not created."""


@dataclass(frozen=True)
class MigrationFile:
    filename: str
    path: Path
    kind: MigrationKind
    checksum: str


@dataclass(frozen=True)
class MigrationState:
    filename: str
    kind: MigrationKind
    checksum: str
    applied_at: datetime | None
    applied_checksum: str | None


def migrations_dir() -> Path:
    return python_root() / "sql" / "migrations"


def migration_kind(path: Path) -> MigrationKind:
    """Index migrations are the files whose names contain ``index``."""
    if "index" in path.stem:
        return "index"
    return "schema"


def list_migrations(directory: Path | None = None) -> list[MigrationFile]:
    root = directory or migrations_dir()
    files = sorted(path for path in root.glob("*.sql") if path.is_file())
    return [
        MigrationFile(
            filename=path.name,
            path=path,
            kind=migration_kind(path),
            checksum=_checksum(path),
        )
        for path in files
    ]


def migrate(
    database_url: str | None = None,
    *,
    search_backend: SearchBackend | None = None,
    include_schema: bool = True,
    include_indexes: bool = True,
) -> list[str]:
    """Apply pending migrations. Returns the filenames applied on this call."""
    if not include_schema and not include_indexes:
        raise ValueError("migrate() needs include_schema, include_indexes, or both")

    url = database_url if database_url is not None else _configured_database_url()
    _refuse_lakebase_target(url)
    backend = search_backend if search_backend is not None else get_settings().search_backend
    if include_indexes and backend is SearchBackend.LAKEBASE and not include_schema:
        # No schema work to do first. Refuse before opening a connection.
        _raise_lakebase_indexes()

    selected = [
        item
        for item in list_migrations()
        if (item.kind == "schema" and include_schema)
        or (item.kind == "index" and include_indexes and backend is SearchBackend.PGVECTOR)
    ]

    applied: list[str] = []
    # The extension does not exist on a fresh database, so vector adapters
    # are registered by later connections, after 0001_init.sql creates it.
    conn = connect(url, register=False)
    try:
        # Autocommit so each file's transaction() commits on its own. A later
        # failure then leaves the earlier files recorded.
        conn.autocommit = True
        with conn.transaction():
            conn.execute(_TRACKING_SQL)
        recorded = _recorded(conn)
        for item in selected:
            previous = recorded.get(item.filename)
            if previous is not None:
                if previous != item.checksum:
                    raise RuntimeError(
                        f"{item.filename} changed after it was applied; migrations are immutable"
                    )
                continue
            _apply_file(conn, item)
            applied.append(item.filename)
    finally:
        conn.close()
    if include_indexes and backend is SearchBackend.LAKEBASE:
        # Schema is committed. Lakebase Search indexes are a separate, unimplemented path.
        _raise_lakebase_indexes()
    return applied


def migration_status(database_url: str | None = None) -> list[MigrationState]:
    """Report each migration file as applied or pending. Does not write."""
    url = database_url if database_url is not None else _configured_database_url()
    _refuse_lakebase_target(url)
    files = list_migrations()
    conn = connect(url, register=False)
    try:
        conn.autocommit = True
        recorded = _recorded_with_time(conn)
    finally:
        conn.close()
    states: list[MigrationState] = []
    for item in files:
        applied_at, applied_checksum = recorded.get(item.filename, (None, None))
        if applied_checksum is not None and applied_checksum != item.checksum:
            raise RuntimeError(
                f"{item.filename} changed after it was applied; migrations are immutable"
            )
        states.append(
            MigrationState(
                filename=item.filename,
                kind=item.kind,
                checksum=item.checksum,
                applied_at=applied_at,
                applied_checksum=applied_checksum,
            )
        )
    return states


def run_db_command(args: object) -> int:
    """CLI handler for `consilium db`."""  # pragma: allowlist secret
    command = getattr(args, "db_command", None)
    try:
        if command == "status":
            for state in migration_status():
                mark = "applied" if state.applied_at is not None else "pending"
                print(f"{state.filename} {mark}")
            return 0
        if command == "migrate":
            schema_only = bool(getattr(args, "schema_only", False))
            indexes_only = bool(getattr(args, "indexes_only", False))
            applied = migrate(
                include_schema=not indexes_only,
                include_indexes=not schema_only,
            )
            if not applied:
                print("up to date")
            else:
                for filename in applied:
                    print(f"applied {filename}")
            return 0
        if command == "seed":
            from consilium.db.seed import run_seed_command  # pragma: allowlist secret

            return run_seed_command()
    except (LakebaseMigrationRefused, LakebaseIndexesNotImplemented, RuntimeError) as exc:
        print(_public_error(exc), file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(_public_error(exc), file=sys.stderr)
        return 1
    print("usage: consilium db {status,migrate,seed}", file=sys.stderr)  # pragma: allowlist secret
    return 2


def split_sql(script: str) -> list[str]:
    """Split a SQL script into statements. Strings, comments and dollar quotes stay intact."""
    statements: list[str] = []
    current: list[str] = []
    i = 0
    length = len(script)
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar: str | None = None

    while i < length:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < length else ""

        if in_line_comment:
            current.append(ch)
            i += 1
            if ch == "\n":
                in_line_comment = False
            continue
        if in_block_comment:
            current.append(ch)
            if ch == "*" and nxt == "/":
                current.append(nxt)
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue
        if dollar is not None:
            if script.startswith(dollar, i):
                current.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            current.append(ch)
            i += 1
            continue
        if in_single:
            current.append(ch)
            if ch == "'" and nxt == "'":
                current.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            current.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            current.append("--")
            i += 2
            in_line_comment = True
            continue
        if ch == "/" and nxt == "*":
            current.append("/*")
            i += 2
            in_block_comment = True
            continue
        if ch == "'":
            in_single = True
            current.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            current.append(ch)
            i += 1
            continue
        if ch == "$":
            tag = _dollar_tag(script, i)
            if tag is not None:
                dollar = tag
                current.append(tag)
                i += len(tag)
                continue
        if ch == ";":
            statement = "".join(current).strip()
            if _has_sql(statement):
                statements.append(statement)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1

    tail = "".join(current).strip()
    if _has_sql(tail):
        statements.append(tail)
    return statements


def _configured_database_url() -> str:
    return resolve_database_url(None)


def _refuse_lakebase_target(url: str) -> None:
    configured = os.environ.get("LAKEBASE_DATABASE_URL", "").strip()
    if configured and configured == url:
        raise LakebaseMigrationRefused(
            "Refusing to migrate LAKEBASE_DATABASE_URL. SKO-280 loads Lakebase."
        )
    host = (urlparse(url).hostname or "").lower()
    if "databricks" in host or "lakebase" in host:
        raise LakebaseMigrationRefused(
            "Refusing to migrate a Databricks Lakebase host. SKO-280 loads Lakebase."
        )


def _raise_lakebase_indexes() -> None:
    raise LakebaseIndexesNotImplemented(
        "SEARCH_BACKEND=lakebase index types (lakebase_ann, lakebase_bm25) are not "
        "implemented. Keep SEARCH_BACKEND=pgvector for HNSW and GIN."
    )


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded(conn: psycopg.Connection) -> dict[str, str]:
    if not _tracking_exists(conn):
        return {}
    rows = conn.execute(
        sql.SQL("select filename, checksum from {}").format(sql.Identifier(_TRACKING_TABLE))
    ).fetchall()
    return {filename: checksum for filename, checksum in rows}


def _recorded_with_time(conn: psycopg.Connection) -> dict[str, tuple[datetime, str]]:
    if not _tracking_exists(conn):
        return {}
    rows = conn.execute(
        sql.SQL("select filename, applied_at, checksum from {}").format(
            sql.Identifier(_TRACKING_TABLE)
        )
    ).fetchall()
    return {filename: (applied_at, checksum) for filename, applied_at, checksum in rows}


def _tracking_exists(conn: psycopg.Connection) -> bool:
    row = conn.execute(
        """
        select exists (
            select 1
            from information_schema.tables
            where table_schema = 'public' and table_name = %s
        )
        """,
        (_TRACKING_TABLE,),
    ).fetchone()
    return bool(row and row[0])


def _apply_file(conn: psycopg.Connection, item: MigrationFile) -> None:
    script = item.path.read_text(encoding="utf-8")
    with conn.transaction():
        for statement in split_sql(script):
            conn.execute(statement)
        conn.execute(
            sql.SQL("insert into {} (filename, checksum) values (%s, %s)").format(
                sql.Identifier(_TRACKING_TABLE)
            ),
            (item.filename, item.checksum),
        )


def _dollar_tag(script: str, start: int) -> str | None:
    if script[start] != "$":
        return None
    end = start + 1
    while end < len(script) and (script[end].isalnum() or script[end] == "_"):
        end += 1
    if end < len(script) and script[end] == "$":
        return script[start : end + 1]
    return None


def _has_sql(statement: str) -> bool:
    return bool(_strip_comments(statement).strip())


def _strip_comments(statement: str) -> str:
    kept: list[str] = []
    i = 0
    length = len(statement)
    in_single = False
    in_double = False
    dollar: str | None = None
    while i < length:
        ch = statement[i]
        nxt = statement[i + 1] if i + 1 < length else ""
        if dollar is not None:
            if statement.startswith(dollar, i):
                kept.append(dollar)
                i += len(dollar)
                dollar = None
                continue
            kept.append(ch)
            i += 1
            continue
        if in_single:
            kept.append(ch)
            if ch == "'" and nxt == "'":
                kept.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            kept.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            i += 2
            while i < length and statement[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < length and not (statement[i] == "*" and statement[i + 1] == "/"):
                i += 1
            i = min(i + 2, length)
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "$":
            tag = _dollar_tag(statement, i)
            if tag is not None:
                dollar = tag
                kept.append(tag)
                i += len(tag)
                continue
        kept.append(ch)
        i += 1
    return "".join(kept)


def _public_error(exc: BaseException) -> str:
    message = str(exc)
    lowered = message.lower()
    if "://" in message or "password" in lowered or "lakebase_database_url" in lowered:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"
