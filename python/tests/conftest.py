from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from consilium.config import Settings  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


def _with_dbname(url: str, dbname: str) -> str:
    info = conninfo_to_dict(url)
    info["dbname"] = dbname
    return make_conninfo(**{key: value for key, value in info.items() if value is not None})


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Admin URL captured before tests clear the process environment."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("DATABASE_URL must be set so migration tests run in CI")
        pytest.skip("DATABASE_URL is not set; migration tests need Postgres with pgvector")
    return url


@pytest.fixture
def empty_database(postgres_url: str) -> Iterator[str]:
    """A new empty database on the configured Postgres server."""
    name = f"sko255_{uuid4().hex[:16]}"
    admin = _with_dbname(postgres_url, "postgres")
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    except psycopg.Error as exc:
        pytest.fail(f"could not create a test database ({exc.__class__.__name__})")
    url = _with_dbname(postgres_url, name)
    try:
        yield url
    finally:
        try:
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(
                    "select pg_terminate_backend(pid) from pg_stat_activity "
                    "where datname = %s and pid <> pg_backend_pid()",
                    (name,),
                )
                conn.execute(sql.SQL("drop database if exists {}").format(sql.Identifier(name)))
        except psycopg.Error:
            pass
