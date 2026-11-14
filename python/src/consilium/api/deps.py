from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import Depends, Header, Request
from psycopg import Connection
from psycopg_pool import ConnectionPool

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.pathologist import Pathologist  # pragma: allowlist secret
from consilium.api.store import Store  # pragma: allowlist secret
from consilium.config import Settings, get_settings  # pragma: allowlist secret


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def get_pool(request: Request) -> ConnectionPool:
    pool = getattr(request.app.state, "pool", None)
    if not isinstance(pool, ConnectionPool):
        fail(500, "error", "Database pool is not open.")
    return pool


def get_db(request: Request) -> Iterator[Connection]:
    """Checkout one pooled connection for the request.

    Stub mode has no pool. Contract tests still resolve this dependency, so
    yield without connecting and let the handler return the in-memory store.
    """
    if getattr(request.app.state, "use_stub_store", False):
        yield cast(Connection, None)
        return
    with get_pool(request).connection() as conn:
        yield conn


def get_acting_pathologist(
    request: Request,
    x_user_id: Annotated[
        str | None,
        Header(
            alias="X-User-Id",
            description="Acting pathologist id. Omit to act as the demo user.",
        ),
    ] = None,
) -> Pathologist:
    """Resolve the acting pathologist. Missing header uses the demo user (F-01.7)."""
    raw = (x_user_id or "").strip()
    if getattr(request.app.state, "use_stub_store", False):
        store = get_store(request)
        if not raw:
            return store.demo_user()
        found = store.pathologists.get(raw)
        if found is None:
            fail(404, "unknown_user", "No pathologist matches X-User-Id.")
        return found

    with get_pool(request).connection() as conn:
        if not raw:
            row = conn.execute(
                """
                select id, name, role_title, primary_specialty, secondary_specialties,
                       is_demo_user, is_synthetic, created_at
                from pathologist
                where is_demo_user = true
                order by id
                limit 1
                """
            ).fetchone()
            if row is None:
                fail(404, "unknown_user", "No demo pathologist is seeded.")
            return _pathologist(row)
        row = conn.execute(
            """
            select id, name, role_title, primary_specialty, secondary_specialties,
                   is_demo_user, is_synthetic, created_at
            from pathologist
            where id = %s
            """,
            (raw,),
        ).fetchone()
        if row is None:
            fail(404, "unknown_user", "No pathologist matches X-User-Id.")
        return _pathologist(row)


def _pathologist(row: tuple[object, ...]) -> Pathologist:
    specialties = row[4]
    secondary = list(specialties) if isinstance(specialties, (list, tuple)) else []
    return Pathologist.model_validate(
        {
            "id": row[0],
            "name": row[1],
            "role_title": row[2],
            "primary_specialty": row[3],
            "secondary_specialties": secondary,
            "is_demo_user": row[5],
            "is_synthetic": row[6],
            "created_at": row[7],
        }
    )


StoreDep = Annotated[Store, Depends(get_store)]
Acting = Annotated[Pathologist, Depends(get_acting_pathologist)]
DbConn = Annotated[Connection, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
