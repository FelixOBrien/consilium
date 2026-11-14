"""Patient list and longitudinal history. Open cases stay withheld inside each row."""

from __future__ import annotations

from psycopg import Connection, sql
from psycopg.rows import dict_row

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.case import PatientDetail  # pragma: allowlist secret
from consilium.api.schemas.common import Page  # pragma: allowlist secret
from consilium.api.schemas.patient import PatientSummary  # pragma: allowlist secret
from consilium.db.cases import summaries_for_patient  # pragma: allowlist secret

_FILTERED = sql.SQL(
    """
    select
        p.id,
        p.display_label,
        p.sex,
        p.is_synthetic_linkage,
        count(c.id)::int as case_count,
        (count(c.id) filter (where c.status = 'open'))::int as open_case_count,
        (count(c.id) filter (where c.status = 'signed_out'))::int as signed_out_case_count,
        max(c.accessioned_at) as latest_accessioned_at,
        (
            select coalesce(
                array_agg(distinct c2.specialty order by c2.specialty),
                '{}'::text[]
            )
            from path_case c2
            where c2.patient_id = p.id
        ) as specialties
    from patient p
    join path_case c on c.patient_id = p.id
    where (
        %s::text is null
        or position(lower(%s) in lower(p.id)) > 0
        or position(lower(%s) in lower(p.display_label)) > 0
    )
    group by p.id, p.display_label, p.sex, p.is_synthetic_linkage
    having (%s::boolean = false or count(c.id) > 1)
    """
)

_PAGE = sql.SQL(
    """
    with filtered as (
        {filtered}
    )
    select *
    from filtered f
    where (
        %s::text is null
        or (
            f.latest_accessioned_at < (
                select cur.latest_accessioned_at from filtered cur where cur.id = %s
            )
            or (
                f.latest_accessioned_at = (
                    select cur.latest_accessioned_at from filtered cur where cur.id = %s
                )
                and f.id > %s
            )
        )
    )
    order by f.latest_accessioned_at desc, f.id asc
    limit %s
    """
).format(filtered=_FILTERED)

_CURSOR_OK = sql.SQL(
    """
    with filtered as (
        {filtered}
    )
    select 1 from filtered where id = %s
    """
).format(filtered=_FILTERED)

_ONE = """
select
    p.id,
    p.display_label,
    p.sex,
    p.birth_year,
    p.is_synthetic_linkage,
    count(c.id)::int as case_count,
    (count(c.id) filter (where c.status = 'open'))::int as open_case_count,
    (count(c.id) filter (where c.status = 'signed_out'))::int as signed_out_case_count,
    max(c.accessioned_at) as latest_accessioned_at,
    (
        select coalesce(
            array_agg(distinct c2.specialty order by c2.specialty),
            '{}'::text[]
        )
        from path_case c2
        where c2.patient_id = p.id
    ) as specialties
from patient p
join path_case c on c.patient_id = p.id
where p.id = %s
group by p.id, p.display_label, p.sex, p.birth_year, p.is_synthetic_linkage
"""


def list_patients(
    conn: Connection,
    *,
    q: str | None,
    multi_case: bool,
    limit: int,
    cursor: str | None,
) -> Page[PatientSummary]:
    filters = _filter_params(q, multi_case)
    token = _cursor(cursor)
    if token is not None and _one(conn, _CURSOR_OK, (*filters, token)) is None:
        fail(422, "validation_error", "Unknown cursor.")
    params: tuple[object, ...] = (*filters, token, token, token, token, limit + 1)
    rows = _all(conn, _PAGE, params)
    items = [_summary(row) for row in rows[:limit]]
    next_cursor = items[-1].id if len(rows) > limit and items else None
    return Page(items=items, next_cursor=next_cursor)


def get_patient(conn: Connection, patient_id: str) -> PatientDetail:
    row = _one(conn, _ONE, (patient_id,))
    if row is None:
        fail(404, "not_found", "Patient not found.")
    summary = _summary(row)
    return PatientDetail(
        **summary.model_dump(),
        birth_year=row["birth_year"],  # type: ignore[arg-type]
        cases=summaries_for_patient(conn, patient_id),
    )


def _summary(row: dict[str, object]) -> PatientSummary:
    specialties = row["specialties"]
    return PatientSummary(
        id=row["id"],  # type: ignore[arg-type]
        display_label=row["display_label"],  # type: ignore[arg-type]
        sex=row["sex"],  # type: ignore[arg-type]
        case_count=row["case_count"],  # type: ignore[arg-type]
        is_synthetic_linkage=bool(row["is_synthetic_linkage"]),
        latest_accessioned_at=row["latest_accessioned_at"],  # type: ignore[arg-type]
        open_case_count=row["open_case_count"],  # type: ignore[arg-type]
        signed_out_case_count=row["signed_out_case_count"],  # type: ignore[arg-type]
        specialties=list(specialties) if isinstance(specialties, list) else [],
    )


def _filter_params(q: str | None, multi_case: bool) -> tuple[object, ...]:
    text = None if q is None or not q.strip() else q.strip()
    return (text, text, text, multi_case)


def _cursor(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        fail(422, "validation_error", "Unknown cursor.")
    return text


def _all(
    conn: Connection,
    query: sql.Composed | str,
    params: tuple[object, ...],
) -> list[dict[str, object]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _one(
    conn: Connection,
    query: sql.Composed | str,
    params: tuple[object, ...],
) -> dict[str, object] | None:
    rows = _all(conn, query, params)
    if not rows:
        return None
    return rows[0]
