from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool

from consilium.config import get_settings  # pragma: allowlist secret

_SSL_KEEP = frozenset({"require", "verify-ca", "verify-full"})


def resolve_database_url(explicit: str | None = None) -> str:
    """Return an explicit URL, or the configured `DATABASE_URL` when omitted."""
    if explicit is not None:
        return explicit
    return get_settings().database_url


def is_lakebase_url(url: str) -> bool:
    """True for Databricks Lakebase and Neon endpoints, which require TLS."""
    host = (urlparse(url).hostname or "").lower()
    if host == "":
        try:
            host = str(conninfo_to_dict(url).get("host") or "").lower()
        except Exception:
            return False
    return "databricks" in host or "lakebase" in host or host.endswith("neon.tech")


def prepare_database_url(url: str) -> str:
    """Add ``sslmode=require`` for Lakebase. Local URLs are unchanged."""
    if not is_lakebase_url(url):
        return url
    try:
        info = conninfo_to_dict(url)
    except Exception:
        return url
    mode = str(info.get("sslmode") or "").lower()
    if mode in _SSL_KEEP:
        return url
    info["sslmode"] = "require"
    cleaned = {key: value for key, value in info.items() if value is not None}
    return make_conninfo(**cleaned)


def connect(url: str | None = None, *, register: bool = True) -> Connection:
    """Open one connection and, by default, register pgvector types on it.

    Registration needs the `vector` extension. Pass `register=False` while
    applying migrations that create the extension. The caller closes the
    connection. Closing rolls back a transaction that is still open.
    Lakebase hosts are opened with ``sslmode=require``.
    """
    conn = Connection.connect(prepare_database_url(resolve_database_url(url)))
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
        conninfo=prepare_database_url(resolve_database_url(url)),
        min_size=min_size,
        max_size=max_size,
        configure=_configure,
        kwargs={"autocommit": False},
        **kwargs,
    )
