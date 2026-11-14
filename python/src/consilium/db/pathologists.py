"""Pathologist queries. The roster is synthetic; flags stay on every row."""

from __future__ import annotations

from psycopg import Connection, sql
from psycopg.rows import dict_row

from consilium.api.schemas.pathologist import Pathologist  # pragma: allowlist secret

_COLUMNS = sql.SQL(
    "id, name, role_title, primary_specialty, secondary_specialties, "
    "is_demo_user, is_synthetic, created_at"
)

_LIST = sql.SQL("select {} from pathologist order by id").format(_COLUMNS)

_BY_ID = sql.SQL("select {} from pathologist where id = %s").format(_COLUMNS)

_DEMO = sql.SQL(
    "select {} from pathologist where is_demo_user = true order by id limit 1"
).format(_COLUMNS)


def list_pathologists(conn: Connection) -> list[Pathologist]:
    return [_person(row) for row in _fetch(conn, _LIST, ())]


def get_pathologist(conn: Connection, pathologist_id: str) -> Pathologist | None:
    rows = _fetch(conn, _BY_ID, (pathologist_id,))
    if not rows:
        return None
    return _person(rows[0])


def get_demo_pathologist(conn: Connection) -> Pathologist | None:
    rows = _fetch(conn, _DEMO, ())
    if not rows:
        return None
    return _person(rows[0])


def _fetch(
    conn: Connection,
    query: sql.Composed,
    params: tuple[object, ...],
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _person(row: dict[str, object]) -> Pathologist:
    secondaries = row["secondary_specialties"]
    return Pathologist(
        id=row["id"],  # type: ignore[arg-type]
        name=row["name"],  # type: ignore[arg-type]
        role_title=row["role_title"],  # type: ignore[arg-type]
        primary_specialty=row["primary_specialty"],  # type: ignore[arg-type]
        secondary_specialties=list(secondaries) if isinstance(secondaries, list) else [],
        is_demo_user=bool(row["is_demo_user"]),
        is_synthetic=bool(row["is_synthetic"]),
        created_at=row["created_at"],  # type: ignore[arg-type]
    )
