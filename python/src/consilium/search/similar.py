"""Shortcut for Q3 on a case's primary slide and Q5 on its visible report text.

An open case contributes only `clinical_history`. Withheld conclusion, body,
microscopic description, diagnosis and ICD-10 are not selected.
"""

from __future__ import annotations

import time

from psycopg import Connection

from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
    SimilarCases,
)
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.search.common import (  # pragma: allowlist secret
    SearchError,
    configure_hnsw,
    fetchone,
    took_ms,
)
from consilium.search.patches import search_patches  # pragma: allowlist secret
from consilium.search.reports import search_reports  # pragma: allowlist secret


def case_precedent_text(conn: Connection, case_id: str) -> str | None:
    """Text Q5 may use for this case. Open cases yield clinical history only."""
    case = fetchone(conn, "SELECT status FROM path_case WHERE id = %s", (case_id,))
    if case is None:
        raise SearchError(404, "not_found", "Case not found.")
    if case["status"] == "open":
        row = fetchone(
            conn,
            "SELECT clinical_history FROM report WHERE case_id = %s",
            (case_id,),
        )
        history = None if row is None else row["clinical_history"]
        if history is None or str(history).strip() == "":
            return None
        return str(history)
    row = fetchone(
        conn,
        """
        SELECT conclusion, clinical_history
        FROM report
        WHERE case_id = %s AND status = 'signed'
        """,
        (case_id,),
    )
    if row is None:
        return None
    conclusion = row["conclusion"]
    if conclusion is not None and str(conclusion).strip() != "":
        return str(conclusion)
    history = row["clinical_history"]
    if history is None or str(history).strip() == "":
        return None
    return str(history)


def similar_cases(conn: Connection, case_id: str, encoders: TextEncoders) -> SimilarCases:
    """Q3 on the first ready slide, and Q5 on the conclusion or clinical history."""
    started = time.perf_counter()
    with conn.transaction():
        configure_hnsw(conn)
        text = case_precedent_text(conn, case_id)
        slide_id = _primary_slide_id(conn, case_id)
    if slide_id is None:
        slide = SearchResponse(
            query_kind="slide",
            hits=[],
            total_candidates=0,
            took_ms=took_ms(started),
            notice="This case has no ready slide.",
        )
    else:
        found = search_patches(
            conn,
            PatchSearchRequest(slide_id=slide_id, context_case_id=case_id),
            encoders,
        )
        if not isinstance(found, SearchResponse):
            raise SearchError(500, "error", "Slide similarity did not return cases.")
        slide = found
    if text is None:
        reports = SearchResponse(
            query_kind="reports",
            hits=[],
            total_candidates=0,
            took_ms=0,
            notice="No report text is available to search.",
        )
    else:
        reports = search_reports(
            conn,
            ReportSearchRequest(text=text, context_case_id=case_id, mode="hybrid"),
            encoders,
        )
    return SimilarCases(slide=slide, reports=reports)


def _primary_slide_id(conn: Connection, case_id: str) -> str | None:
    row = fetchone(
        conn,
        """
        SELECT id
        FROM slide
        WHERE case_id = %s AND status = 'ready' AND embedding IS NOT NULL
        ORDER BY ordinal
        LIMIT 1
        """,
        (case_id,),
    )
    if row is None:
        return None
    return str(row["id"])
