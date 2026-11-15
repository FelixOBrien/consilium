"""Consult threads, messages, and the SQL pathologist ranking.

Counts come from this query, not from model prose. Open and held-out cases
never enter the ranking. Token columns and tool inputs stay in the table and
are omitted from the API shape.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Json

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    Citation,
    ConsultMessage,
    ConsultThread,
    MessageAttachments,
    PathologistRank,
    ToolTraceStep,
)
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret
from consilium.search.common import (  # pragma: allowlist secret
    case_summary,
    fetchall,
    fetchone,
    load_summaries,
)

_TITLE_LIMIT = 80

_RANK_SQL = """
SELECT
    p.id AS pathologist_id,
    p.name,
    p.primary_specialty AS specialty,
    p.is_synthetic,
    COUNT(DISTINCT c.id)::int AS case_count,
    ARRAY_AGG(DISTINCT c.id ORDER BY c.id) AS case_ids,
    BOOL_OR(
        EXISTS (
            SELECT 1
            FROM path_case earlier
            JOIN report earlier_report
                ON earlier_report.case_id = earlier.id
               AND earlier_report.status = 'signed'
            WHERE earlier.patient_id = %(patient_id)s
              AND earlier.status = 'signed_out'
              AND earlier.is_held_out = false
              AND earlier.id <> %(thread_case_id)s
              AND earlier_report.author_id = p.id
        )
    ) AS reported_same_patient
FROM path_case c
JOIN report r ON r.case_id = c.id AND r.status = 'signed'
JOIN pathologist p ON p.id = r.author_id
WHERE c.id = ANY(%(case_ids)s)
  AND c.status = 'signed_out'
  AND c.is_held_out = false
  AND c.id <> %(thread_case_id)s
  AND EXISTS (
      SELECT 1
      FROM report_chunk chunk
      WHERE chunk.case_id = c.id
        AND chunk.in_corpus = true
  )
GROUP BY p.id, p.name, p.primary_specialty, p.is_synthetic
ORDER BY COUNT(DISTINCT c.id) DESC, p.id ASC
"""

_PRECEDENT_SQL = """
SELECT c.id, c.patient_id
FROM path_case c
JOIN report r ON r.case_id = c.id AND r.status = 'signed'
WHERE c.id = ANY(%(case_ids)s)
  AND c.status = 'signed_out'
  AND c.is_held_out = false
  AND c.id <> %(thread_case_id)s
  AND EXISTS (
      SELECT 1
      FROM report_chunk chunk
      WHERE chunk.case_id = c.id
        AND chunk.in_corpus = true
  )
ORDER BY c.accessioned_at ASC, c.id ASC
"""


def create_or_resume_thread(
    conn: Connection,
    *,
    case_id: str,
    user_id: str,
    new: bool,
) -> ConsultThread:
    case = fetchone(conn, "SELECT id FROM path_case WHERE id = %s", (case_id,))
    if case is None:
        fail(404, "not_found", "Case not found.")
    if not new:
        existing = fetchone(
            conn,
            """
            SELECT id
            FROM consult_thread
            WHERE case_id = %s AND user_id = %s
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (case_id, user_id),
        )
        if existing is not None:
            return _hydrate(conn, existing["id"], user_id)
    created = fetchone(
        conn,
        """
        INSERT INTO consult_thread (case_id, user_id)
        VALUES (%s, %s)
        RETURNING id
        """,
        (case_id, user_id),
    )
    if created is None:
        fail(500, "error", "Consult thread was not created.")
    return _hydrate(conn, created["id"], user_id)


def get_thread(conn: Connection, thread_id: UUID, user_id: str) -> ConsultThread:
    return _hydrate(conn, thread_id, user_id)


def insert_user_message(
    conn: Connection,
    *,
    thread_id: UUID,
    content: str,
    attachments: MessageAttachments | None,
) -> UUID:
    row = fetchone(
        conn,
        """
        INSERT INTO consult_message (
            thread_id, role, content, attachments, status, created_at
        )
        VALUES (%s, 'user', %s, %s, 'complete', clock_timestamp())
        RETURNING id
        """,
        (
            thread_id,
            content,
            Json(attachments.model_dump(mode="json")) if attachments is not None else None,
        ),
    )
    if row is None:
        fail(500, "error", "Consult message was not stored.")
    title = content.strip()[:_TITLE_LIMIT]
    conn.execute(
        """
        UPDATE consult_thread
        SET title = COALESCE(title, %s),
            updated_at = now()
        WHERE id = %s
        """,
        (title, thread_id),
    )
    return row["id"]


def insert_streaming_assistant_message(conn: Connection, *, thread_id: UUID) -> UUID:
    row = fetchone(
        conn,
        """
        INSERT INTO consult_message (thread_id, role, content, status, created_at)
        VALUES (%s, 'assistant', '', 'streaming', clock_timestamp())
        RETURNING id
        """,
        (thread_id,),
    )
    if row is None:
        fail(500, "error", "Consult message was not stored.")
    conn.execute(
        "UPDATE consult_thread SET updated_at = now() WHERE id = %s",
        (thread_id,),
    )
    return row["id"]


def finalize_assistant_message(
    conn: Connection,
    *,
    message_id: UUID,
    content: str,
    citations: list[dict[str, object]] | None,
    ranking: list[PathologistRank] | None,
    tool_trace: list[dict[str, object]] | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    status: str,
) -> None:
    ranking_json = None
    if ranking is not None:
        ranking_json = [item.model_dump(mode="json") for item in ranking]
    conn.execute(
        """
        UPDATE consult_message
        SET content = %s,
            citations = %s,
            ranking = %s,
            tool_trace = %s,
            model = %s,
            input_tokens = %s,
            output_tokens = %s,
            status = %s
        WHERE id = %s AND role = 'assistant'
        """,
        (
            content,
            Json(citations) if citations is not None else None,
            Json(ranking_json) if ranking_json is not None else None,
            Json(tool_trace) if tool_trace is not None else None,
            model,
            input_tokens,
            output_tokens,
            status,
            message_id,
        ),
    )
    conn.execute(
        """
        UPDATE consult_thread
        SET updated_at = now()
        WHERE id = (SELECT thread_id FROM consult_message WHERE id = %s)
        """,
        (message_id,),
    )


def rank_pathologists_sql(
    conn: Connection,
    *,
    case_ids: list[str],
    thread_case_id: str,
    patient_id: str,
) -> list[dict[str, Any]]:
    """One aggregation. `case_count` is the number of distinct signed-out cases."""
    if not case_ids:
        return []
    rows = fetchall(
        conn,
        _RANK_SQL,
        {
            "case_ids": list(case_ids),
            "thread_case_id": thread_case_id,
            "patient_id": patient_id,
        },
    )
    ranked: list[dict[str, Any]] = []
    for row in rows:
        ids = [str(item) for item in row["case_ids"]]
        count = len(ids)
        rank = PathologistRank(
            pathologist_id=str(row["pathologist_id"]),
            name=str(row["name"]),
            specialty=row["specialty"],
            case_count=count,
            case_ids=ids,
        )
        ranked.append(
            {
                "rank": rank,
                "is_synthetic": True,
                "reported_same_patient": bool(row["reported_same_patient"]),
            }
        )
    return ranked


def precedent_cases(
    conn: Connection,
    *,
    case_ids: list[str],
    thread_case_id: str,
) -> list[dict[str, Any]]:
    """Signed-out in-corpus cases other than the thread case. Drops the rest."""
    if not case_ids:
        return []
    return fetchall(
        conn,
        _PRECEDENT_SQL,
        {"case_ids": list(case_ids), "thread_case_id": thread_case_id},
    )


def expand_citation_summaries(
    conn: Connection,
    records: list[dict[str, object]] | None,
) -> list[Citation] | None:
    """Attach a safe `CaseSummary`. Unknown ids are dropped."""
    if records is None:
        return None
    ids = [str(item["case_id"]) for item in records if item.get("case_id")]
    summaries = load_summaries(conn, ids)
    citations: list[Citation] = []
    for item in records:
        case_id = str(item.get("case_id") or "")
        row = summaries.get(case_id)
        if row is None or str(row["status"]) != "signed_out":
            continue
        patch_id = item.get("patch_id")
        citations.append(
            Citation(
                case_id=case_id,
                slide_id=_optional_str(item.get("slide_id")),
                patch_id=int(patch_id) if isinstance(patch_id, int) else None,
                quote=_optional_str(item.get("quote")),
                case=case_summary(row),
            )
        )
    return citations


def thread_case_context(conn: Connection, thread_id: UUID) -> dict[str, Any]:
    row = fetchone(
        conn,
        """
        SELECT
            t.case_id,
            t.user_id,
            c.patient_id,
            (
                SELECT count(*)::int
                FROM path_case other
                WHERE other.patient_id = c.patient_id
            ) AS case_count
        FROM consult_thread t
        JOIN path_case c ON c.id = t.case_id
        WHERE t.id = %s
        """,
        (thread_id,),
    )
    if row is None:
        fail(404, "not_found", "Consult thread not found.")
    return row


def _hydrate(conn: Connection, thread_id: UUID, user_id: str) -> ConsultThread:
    row = fetchone(
        conn,
        """
        SELECT id, case_id, user_id, title, created_at, updated_at
        FROM consult_thread
        WHERE id = %s
        """,
        (thread_id,),
    )
    if row is None:
        fail(404, "not_found", "Consult thread not found.")
    if str(row["user_id"]) != user_id:
        fail(403, "forbidden", "This consult thread belongs to another pathologist.")
    messages = fetchall(
        conn,
        """
        SELECT
            id, role, content, attachments, citations, ranking, tool_trace,
            status, created_at
        FROM consult_message
        WHERE thread_id = %s
        ORDER BY created_at ASC, id ASC
        """,
        (thread_id,),
    )
    return ConsultThread(
        id=row["id"],
        case_id=str(row["case_id"]),
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=[_message(conn, item) for item in messages],
    )


def _message(conn: Connection, row: dict[str, Any]) -> ConsultMessage:
    attachments = row["attachments"]
    parsed_attachments = (
        MessageAttachments.model_validate(attachments) if isinstance(attachments, dict) else None
    )
    citations = None
    if row["role"] == "assistant":
        raw = row["citations"]
        citations = expand_citation_summaries(conn, raw if isinstance(raw, list) else None)
    ranking = _ranking(row["ranking"])
    return ConsultMessage(
        id=row["id"],
        role=row["role"],
        content=str(row["content"]),
        attachments=parsed_attachments,
        citations=citations,
        ranking=ranking,
        tool_trace=_trace(row["tool_trace"]),
        status=row["status"],
        created_at=row["created_at"],
    )


def _ranking(raw: object) -> list[PathologistRank] | None:
    if not isinstance(raw, list):
        return None
    return [PathologistRank.model_validate(item) for item in raw]


def _trace(raw: object) -> list[ToolTraceStep] | None:
    if not isinstance(raw, list):
        return None
    steps: list[ToolTraceStep] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        steps.append(
            ToolTraceStep(
                tool=str(item.get("tool") or ""),
                summary=str(item.get("summary") or ""),
                duration_ms=int(item.get("duration_ms") or 0),
            )
        )
    return steps


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def author_ref(row: dict[str, Any]) -> PathologistRef | None:
    if row.get("author_id") is None:
        return None
    return PathologistRef(
        id=str(row["author_id"]),
        name=str(row["author_name"]),
        primary_specialty=row["author_specialty"],
        is_synthetic=True,
    )
