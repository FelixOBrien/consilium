from __future__ import annotations

from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from consilium.config import get_settings  # pragma: allowlist secret


def resolve_database_url(explicit: str | None = None) -> str:
    """Return an explicit URL, or the configured `DATABASE_URL` when omitted."""
    if explicit is not None:
        return explicit
    return get_settings().database_url


def connect(url: str | None = None, *, register: bool = True) -> Connection:
    """Open one connection and, by default, register pgvector types on it.

    Registration needs the `vector` extension. Pass `register=False` while
    applying migrations that create the extension. The caller closes the
    connection. Closing rolls back a transaction that is still open.
    """
    conn = Connection.connect(resolve_database_url(url))
    if register:
        register_vector(conn)
    return conn


def _configure(conn: Connection) -> None:
    register_vector(conn)


def connection_pool(
    url: str | None = None,
    *,
    min_size: int = 0,
    max_size: int = 4,
    **kwargs: Any,
) -> ConnectionPool:
    """Pool of connections with `pgvector.psycopg.register_vector` applied.

    The pool stays closed until the caller opens it (`with pool` or `pool.open()`),
    unless `open=True` is passed through.
    """
    return ConnectionPool(
        conninfo=resolve_database_url(url),
        min_size=min_size,
        max_size=max_size,
        configure=_configure,
        kwargs={"autocommit": False},
        **kwargs,
    )
