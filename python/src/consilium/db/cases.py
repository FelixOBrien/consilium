"""Case and report queries. Open cases never leave the database with a diagnosis."""

from __future__ import annotations

from typing import Literal

from psycopg import Connection, sql
from psycopg.rows import dict_row

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.case import CaseDetail, CaseSummary  # pragma: allowlist secret
from consilium.api.schemas.common import Page  # pragma: allowlist secret
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret
from consilium.api.schemas.patient import PatientRef  # pragma: allowlist secret
from consilium.api.schemas.report import Report, ReportNotReported  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideSummary  # pragma: allowlist secret

# Shared projection. Diagnosis columns are null unless the case is signed out,
# so an open row cannot carry primary_diagnosis or conclusion into Python.
_SUMMARY = sql.SQL(
    """
    select
        c.id,
        c.specimen_label,
        c.specialty,
        c.patient_age,
        c.patient_sex,
        case when c.status = 'signed_out' then c.icd10 else null end as icd10,
        c.status,
        c.accessioned_at,
        case when c.status = 'signed_out' then r.conclusion else null end as conclusion,
        case
            when c.status = 'signed_out' then c.primary_diagnosis
            else null
        end as primary_diagnosis,
        (select count(*)::int from slide s where s.case_id = c.id) as slide_count,
        (
            select s.id
            from slide s
            where s.case_id = c.id
            order by s.ordinal asc, s.id asc
            limit 1
        ) as first_slide_id,
        p.id as patient_id,
        p.display_label,
        p.sex as patient_record_sex,
        p.is_synthetic_linkage,
        (
            select count(*)::int from path_case pc where pc.patient_id = p.id
        ) as case_count,
        a.id as assignee_id,
        a.name as assignee_name,
        a.primary_specialty as assignee_specialty,
        a.is_synthetic as assignee_synthetic
    from path_case c
    join patient p on p.id = c.patient_id
    join pathologist a on a.id = c.assigned_to
    left join report r on r.case_id = c.id
    """
)

_FILTERS = sql.SQL(
    """
    (%s::text is null or c.status = %s)
    and (%s::text is null or c.specialty = %s)
    and (%s::text is null or c.assigned_to = %s)
    and (%s::text is null or c.patient_id = %s)
    and (
        %s::text is null
        or (
            c.status = 'signed_out'
            and c.icd10 is not null
            and c.icd10 like %s escape '\\'
        )
    )
    and (%s::boolean = false or c.assigned_to = %s)
    """
)

_PAGE = sql.SQL(
    """
    with filtered as (
        {summary}
        where {filters}
    ),
    ranked as (
        select
            f.*,
            case
                when %s then case when f.status = 'open' then 0 else 1 end
                else 0
            end as open_rank
        from filtered f
    )
    select *
    from ranked r
    where (
        %s::text is null
        or (
            r.open_rank > (select cur.open_rank from ranked cur where cur.id = %s)
            or (
                r.open_rank = (select cur.open_rank from ranked cur where cur.id = %s)
                and (
                    r.accessioned_at < (
                        select cur.accessioned_at from ranked cur where cur.id = %s
                    )
                    or (
                        r.accessioned_at = (
                            select cur.accessioned_at from ranked cur where cur.id = %s
                        )
                        and r.id > %s
                    )
                )
            )
        )
    )
    order by r.open_rank asc, r.accessioned_at desc, r.id asc
    limit %s
    """
).format(summary=_SUMMARY, filters=_FILTERS)

_CURSOR_OK = sql.SQL(
    """
    select 1
    from path_case c
    where {filters}
      and c.id = %s
    """
).format(filters=_FILTERS)

_BY_ID = sql.SQL("{summary} where c.id = %s").format(summary=_SUMMARY)

_FOR_PATIENT = sql.SQL(
    """
    {summary}
    where c.patient_id = %s
    order by c.accessioned_at desc, c.id asc
    """
).format(summary=_SUMMARY)

_SLIDES = """
select id, ordinal, stain, magnification, status
from slide
where case_id = %s
order by ordinal asc, id asc
"""

_REPORT_STATUS = "select status from report where case_id = %s"

_PRIOR_COUNT = """
select count(*)::int as prior_case_count
from path_case
where patient_id = %s and id <> %s
"""

_REPORT = """
select
    c.status as case_status,
    r.id as report_id,
    r.status as report_status,
    r.body,
    r.clinical_history,
    r.gross_description,
    r.microscopic_description,
    r.conclusion,
    r.additional_info,
    case when c.status = 'signed_out' then r.icd10 else null end as icd10,
    r.signed_at,
    a.id as author_id,
    a.name as author_name,
    a.primary_specialty as author_specialty,
    a.is_synthetic as author_synthetic
from path_case c
left join report r on r.case_id = c.id
left join pathologist a on a.id = r.author_id
where c.id = %s
"""


def list_cases(
    conn: Connection,
    *,
    actor_id: str,
    view: str | None,
    status: str | None,
    specialty: str | None,
    assigned_to: str | None,
    icd10: str | None,
    patient_id: str | None,
    limit: int,
    cursor: str | None,
) -> Page[CaseSummary]:
    """Newest first. Omitted `view` is My cases (F-01.4): the actor's cases, open first."""
    mine = view != "all"
    filters = _filter_params(
        status=status,
        specialty=specialty,
        assigned_to=assigned_to,
        patient_id=patient_id,
        icd10=icd10,
        mine=mine,
        actor_id=actor_id,
    )
    token = _cursor(cursor)
    if token is not None and _one(conn, _CURSOR_OK, (*filters, token)) is None:
        fail(422, "validation_error", "Unknown cursor.")
    params: tuple[object, ...] = (
        *filters,
        mine,
        token,
        token,
        token,
        token,
        token,
        token,
        limit + 1,
    )
    rows = _all(conn, _PAGE, params)
    summaries = [_summary(row) for row in rows[:limit]]
    next_cursor = summaries[-1].id if len(rows) > limit and summaries else None
    return Page(items=summaries, next_cursor=next_cursor)


def summaries_for_patient(conn: Connection, patient_id: str) -> list[CaseSummary]:
    rows = _all(conn, _FOR_PATIENT, (patient_id,))
    return [_summary(row) for row in rows]


def get_case(conn: Connection, case_id: str) -> CaseDetail:
    row = _one(conn, _BY_ID, (case_id,))
    if row is None:
        fail(404, "not_found", "Case not found.")
    summary = _summary(row)
    status_row = _one(conn, _REPORT_STATUS, (case_id,))
    stored = None if status_row is None else status_row["status"]
    return CaseDetail(
        **summary.model_dump(),
        slides=_slides(conn, case_id),
        report_status=_visible_report_status(summary.status, stored),
        prior_case_count=_prior_count(conn, summary.patient.id, case_id),
    )


def get_report(conn: Connection, case_id: str) -> Report | ReportNotReported:
    row = _one(conn, _REPORT, (case_id,))
    if row is None:
        fail(404, "not_found", "Case not found.")
    case_status = row["case_status"]
    report_status = row["report_status"]
    if case_status == "open" or report_status in (None, "withheld"):
        if case_status != "open" and report_status is None:
            fail(404, "not_found", "Report not found.")
        return ReportNotReported(
            case_id=case_id,
            status="none",
            clinical_history=_text_or_none(row["clinical_history"]),
        )
    if report_status not in ("signed", "draft"):
        fail(404, "not_found", "Report not found.")
    return Report(
        id=row["report_id"],
        case_id=case_id,
        status=report_status,
        body=row["body"],
        clinical_history=_text_or_none(row["clinical_history"]),
        gross_description=_text_or_none(row["gross_description"]),
        microscopic_description=_text_or_none(row["microscopic_description"]),
        conclusion=_text_or_none(row["conclusion"]),
        additional_info=_text_or_none(row["additional_info"]),
        icd10=_text_or_none(row["icd10"]),
        signed_at=row["signed_at"],
        author=PathologistRef(
            id=row["author_id"],
            name=row["author_name"],
            primary_specialty=row["author_specialty"],
            is_synthetic=row["author_synthetic"],
        ),
        is_synthetic_author=True,
    )


def _filter_params(
    *,
    status: str | None,
    specialty: str | None,
    assigned_to: str | None,
    patient_id: str | None,
    icd10: str | None,
    mine: bool,
    actor_id: str,
) -> tuple[object, ...]:
    prefix = _blank(icd10)
    like = _like_prefix(prefix) if prefix is not None else ""
    status_text = _blank(status)
    specialty_text = _blank(specialty)
    assignee = _blank(assigned_to)
    patient = _blank(patient_id)
    return (
        status_text,
        status_text,
        specialty_text,
        specialty_text,
        assignee,
        assignee,
        patient,
        patient,
        prefix,
        like,
        mine,
        actor_id,
    )


def _summary(row: dict[str, object]) -> CaseSummary:
    slide_id = row["first_slide_id"]
    thumbnail = f"/api/slides/{slide_id}/thumbnail" if isinstance(slide_id, str) else None
    return CaseSummary(
        id=row["id"],  # type: ignore[arg-type]
        patient=PatientRef(
            id=row["patient_id"],  # type: ignore[arg-type]
            display_label=row["display_label"],  # type: ignore[arg-type]
            sex=row["patient_record_sex"],  # type: ignore[arg-type]
            case_count=row["case_count"],  # type: ignore[arg-type]
            is_synthetic_linkage=bool(row["is_synthetic_linkage"]),
        ),
        specimen_label=_text_or_none(row["specimen_label"]),
        specialty=row["specialty"],  # type: ignore[arg-type]
        patient_age=row["patient_age"],  # type: ignore[arg-type]
        patient_sex=row["patient_sex"],  # type: ignore[arg-type]
        icd10=_text_or_none(row["icd10"]),
        status=row["status"],  # type: ignore[arg-type]
        assigned_to=PathologistRef(
            id=row["assignee_id"],  # type: ignore[arg-type]
            name=row["assignee_name"],  # type: ignore[arg-type]
            primary_specialty=row["assignee_specialty"],  # type: ignore[arg-type]
            is_synthetic=bool(row["assignee_synthetic"]),
        ),
        accessioned_at=row["accessioned_at"],  # type: ignore[arg-type]
        slide_count=row["slide_count"],  # type: ignore[arg-type]
        thumbnail_url=thumbnail,
        conclusion_line=_conclusion_line(
            str(row["status"]),
            _text_or_none(row["conclusion"]),
            _text_or_none(row["primary_diagnosis"]),
        ),
    )


def _conclusion_line(
    status: str,
    conclusion: str | None,
    primary_diagnosis: str | None,
) -> str | None:
    """First non-empty conclusion line, else the stored diagnosis. Open cases stay null."""
    if status != "signed_out":
        return None
    if conclusion:
        for line in conclusion.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    if primary_diagnosis:
        stripped = primary_diagnosis.strip()
        if stripped:
            return stripped
    return None


def _slides(conn: Connection, case_id: str) -> list[SlideSummary]:
    slides: list[SlideSummary] = []
    for row in _all(conn, _SLIDES, (case_id,)):
        slide_id = row["id"]
        slides.append(
            SlideSummary(
                id=slide_id,  # type: ignore[arg-type]
                ordinal=row["ordinal"],  # type: ignore[arg-type]
                stain=row["stain"],  # type: ignore[arg-type]
                magnification=float(row["magnification"]),  # type: ignore[arg-type]
                status=row["status"],  # type: ignore[arg-type]
                thumbnail_url=f"/api/slides/{slide_id}/thumbnail",
            )
        )
    return slides


def _prior_count(conn: Connection, patient_id: str, case_id: str) -> int:
    row = _one(conn, _PRIOR_COUNT, (patient_id, case_id))
    if row is None:
        return 0
    return int(row["prior_case_count"])


def _visible_report_status(
    case_status: object,
    stored: object,
) -> Literal["signed", "draft", "none"]:
    """The value `withheld` is never sent. An open case is `none`."""
    if str(case_status) == "open":
        return "none"
    if stored == "signed":
        return "signed"
    if stored == "draft":
        return "draft"
    return "none"


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _text_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value


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
