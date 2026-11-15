"""Report retrieval in the `report` space (384-d) plus keyword rank on `search_tsv`.

Q5 never reads `patch.embedding` or `slide.embedding`. Queries are encoded with
the report encoder's query instruction; chunks were embedded as passages.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pgvector import Vector
from psycopg import Connection

from consilium.api.schemas.search import (  # pragma: allowlist secret
    Passage,
    ReportSearchRequest,
    SearchResponse,
)
from consilium.embed.spaces import REPORT_DIM, ReportEmbedding  # pragma: allowlist secret
from consilium.embed.text import EmbedError, TextEncoders  # pragma: allowlist secret
from consilium.search.common import (  # pragma: allowlist secret
    PATCH_CANDIDATE_LIMIT,
    RRF_K,
    RetrievalScope,
    SearchError,
    build_case_hits,
    cap_notice,
    configure_hnsw,
    coverage,
    exact_case_ids,
    fetchall,
    filter_clauses,
    join_notice,
    keyword_highlights,
    retrieval_scope,
    section_weight,
    sql_where,
    took_ms,
)

ReportMode = Literal["hybrid", "keyword", "semantic"]


def search_reports(
    conn: Connection,
    request: ReportSearchRequest,
    encoders: TextEncoders,
) -> SearchResponse:
    """Hybrid, keyword, or semantic report search. Results are cases, one passage each."""
    started = time.perf_counter()
    text = request.text.strip()
    if text == "":
        raise SearchError(422, "validation_error", "text must not be empty")
    encoded_notice: str | None = None
    query: ReportEmbedding | None = None
    if request.mode in {"hybrid", "semantic"}:
        try:
            encoded = encoders.encode_report_query(text)
        except EmbedError as exc:
            raise SearchError(422, "validation_error", str(exc)) from exc
        query = encoded.vector
        encoded_notice = encoded.truncation_notice()
    with conn.transaction():
        configure_hnsw(conn)
        scope = retrieval_scope(
            conn,
            context_case_id=request.context_case_id,
            filters=request.filters,
        )
        return _search(
            conn,
            scope,
            text,
            request.mode,
            query,
            encoded_notice,
            request.limit,
            started,
        )


def _report_vector(embedding: ReportEmbedding) -> Vector:
    if embedding.dim != REPORT_DIM:
        raise SearchError(500, "error", "Report query vector has the wrong dimension.")
    return Vector(list(embedding.to_float32()))


def _search(
    conn: Connection,
    scope: RetrievalScope,
    text: str,
    mode: ReportMode,
    query: ReportEmbedding | None,
    notice: str | None,
    limit: int,
    started: float,
) -> SearchResponse:
    keyword_ids: list[str] = []
    semantic_rows: list[dict[str, Any]] = []
    signed = scope.status_mode(default="signed") != "open"
    if signed and mode in {"keyword", "hybrid"}:
        keyword_ids = _keyword_cases(conn, scope, text)
    if signed and mode in {"semantic", "hybrid"} and query is not None:
        semantic_rows = _semantic_chunks(conn, scope, _report_vector(query))
    semantic_ids: list[str] = []
    semantic_best: dict[str, dict[str, Any]] = {}
    for row in semantic_rows:
        case_id = str(row["case_id"])
        if case_id not in semantic_best:
            semantic_best[case_id] = row
            semantic_ids.append(case_id)
    scores: dict[str, float] = {}
    labels: dict[str, set[str]] = {}
    if mode in {"keyword", "hybrid"}:
        _rrf(keyword_ids, "keyword", scores, labels)
    if mode in {"semantic", "hybrid"}:
        _rrf(semantic_ids, "semantic", scores, labels)
    ranked = sorted(scores, key=lambda case_id: (-scores[case_id], case_id))
    exact = exact_case_ids(conn, text, scope)
    exact_set = set(exact)
    ordered: list[str] = []
    seen: set[str] = set()
    for case_id in exact:
        if case_id not in seen:
            ordered.append(case_id)
            seen.add(case_id)
    for case_id in ranked:
        if case_id not in seen:
            ordered.append(case_id)
            seen.add(case_id)
    ordered = ordered[:limit]
    raw: list[float] = []
    for index, case_id in enumerate(ordered):
        if case_id in exact_set:
            raw.append(2.0 - index * 1e-4)
        else:
            raw.append(scores.get(case_id, 0.0))
    passages = _passages(conn, ordered, text, mode, semantic_best)
    for case_id, passage in passages.items():
        if passage is None:
            continue
        if passage.highlights and mode != "semantic":
            labels.setdefault(case_id, set()).add("keyword")
    hits = build_case_hits(
        conn,
        ordered,
        context_patient_id=scope.context_patient_id,
        raw_scores=raw,
        matched_by=labels,
        patches={case_id: [] for case_id in ordered},
        patch_counts={case_id: 0 for case_id in ordered},
        passages=passages,
    )
    if mode == "keyword":
        total = len(keyword_ids)
        noun = "reports"
        capped = len(keyword_ids)
    elif mode == "semantic":
        total = len(semantic_rows)
        noun = "report chunks"
        capped = len(semantic_rows)
    else:
        total = len(semantic_rows) + len(keyword_ids)
        noun = "report chunks"
        capped = len(semantic_rows)
    return SearchResponse(
        query_kind="reports",
        hits=hits,
        total_candidates=total,
        took_ms=took_ms(started),
        notice=join_notice(notice, cap_notice(capped, PATCH_CANDIDATE_LIMIT, noun)),
    )


def _rrf(
    ranked_ids: list[str],
    label: str,
    scores: dict[str, float],
    labels: dict[str, set[str]],
) -> None:
    for rank, case_id in enumerate(ranked_ids, start=1):
        scores[case_id] = scores.get(case_id, 0.0) + 1.0 / (RRF_K + rank)
        labels.setdefault(case_id, set()).add(label)


def _keyword_cases(conn: Connection, scope: RetrievalScope, text: str) -> list[str]:
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        status_mode="signed",
    )
    clauses.extend(
        [
            "r.status = 'signed'",
            "r.search_tsv @@ websearch_to_tsquery('english', %(text)s)",
            """
            EXISTS (
                SELECT 1 FROM report_chunk ch
                WHERE ch.case_id = c.id
                  AND ch.in_corpus = true
                  AND ch.section <> 'clinical_history'
            )
            """,
        ]
    )
    params["text"] = text
    params["limit"] = PATCH_CANDIDATE_LIMIT
    rows = fetchall(
        conn,
        f"""
        SELECT c.id AS case_id
        FROM report r
        JOIN path_case c ON c.id = r.case_id
        WHERE {sql_where(clauses)}
        ORDER BY ts_rank_cd(r.search_tsv, websearch_to_tsquery('english', %(text)s)) DESC, c.id
        LIMIT %(limit)s
        """,
        params,
    )
    return [str(row["case_id"]) for row in rows]


def _semantic_chunks(
    conn: Connection,
    scope: RetrievalScope,
    query: Vector,
) -> list[dict[str, Any]]:
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        patient_column="ch.patient_id",
        specialty_column="ch.specialty",
        status_mode="signed",
    )
    clauses.extend(
        [
            "ch.in_corpus = true",
            "r.status = 'signed'",
            "ch.section <> 'clinical_history'",
        ]
    )
    params["query"] = query
    params["limit"] = PATCH_CANDIDATE_LIMIT
    return fetchall(
        conn,
        f"""
        SELECT
            ch.id,
            ch.case_id,
            ch.section,
            ch.text,
            (1 - (ch.embedding <=> %(query)s::vector(384)))::float8 AS similarity
        FROM report_chunk ch
        JOIN path_case c ON c.id = ch.case_id
        JOIN report r ON r.id = ch.report_id
        WHERE {sql_where(clauses)}
        ORDER BY ch.embedding <=> %(query)s::vector(384)
        LIMIT %(limit)s
        """,
        params,
    )


def _passages(
    conn: Connection,
    case_ids: list[str],
    text: str,
    mode: ReportMode,
    semantic_best: dict[str, dict[str, Any]],
) -> dict[str, Passage | None]:
    chunks = _corpus_chunks(conn, case_ids)
    by_case: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_case.setdefault(str(chunk["case_id"]), []).append(chunk)
    highlights: dict[int, list[tuple[int, int]]] = {}
    if mode != "semantic" and chunks:
        highlights = keyword_highlights(conn, chunks, text)
    passages: dict[str, Passage | None] = {}
    for case_id in case_ids:
        case_chunks = by_case.get(case_id, [])
        if not case_chunks:
            passages[case_id] = None
            continue
        chosen = _choose_chunk(case_id, case_chunks, mode, semantic_best, highlights)
        if chosen is None:
            passages[case_id] = None
            continue
        spans = [] if mode == "semantic" else highlights.get(int(chosen["id"]), [])
        passages[case_id] = Passage(
            section=chosen["section"],
            text=str(chosen["text"]),
            highlights=spans,
        )
    return passages


def _corpus_chunks(conn: Connection, case_ids: list[str]) -> list[dict[str, Any]]:
    if not case_ids:
        return []
    return fetchall(
        conn,
        """
        SELECT id, case_id, section, ordinal, text
        FROM report_chunk
        WHERE case_id = ANY(%s)
          AND in_corpus = true
          AND section <> 'clinical_history'
        ORDER BY case_id, ordinal
        """,
        (case_ids,),
    )


def _choose_chunk(
    case_id: str,
    chunks: list[dict[str, Any]],
    mode: ReportMode,
    semantic_best: dict[str, dict[str, Any]],
    highlights: dict[int, list[tuple[int, int]]],
) -> dict[str, Any] | None:
    semantic = semantic_best.get(case_id)
    if mode == "semantic":
        return semantic or _fallback(chunks)
    keyword = _best_keyword_chunk(chunks, highlights)
    if mode == "keyword":
        return keyword or _fallback(chunks)
    if semantic is not None and highlights.get(int(semantic["id"])):
        return semantic
    if keyword is not None:
        return keyword
    return semantic or _fallback(chunks)


def _best_keyword_chunk(
    chunks: list[dict[str, Any]],
    highlights: dict[int, list[tuple[int, int]]],
) -> dict[str, Any] | None:
    marked = [chunk for chunk in chunks if coverage(highlights.get(int(chunk["id"]), [])) > 0]
    if not marked:
        return None
    marked.sort(
        key=lambda chunk: (
            -coverage(highlights.get(int(chunk["id"]), [])),
            -section_weight(str(chunk["section"])),
            int(chunk["ordinal"]),
        )
    )
    return marked[0]


def _fallback(chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for section in (
        "conclusion",
        "microscopic_description",
        "additional_info",
        "gross_description",
        "body",
    ):
        for chunk in chunks:
            if chunk["section"] == section:
                return chunk
    return chunks[0] if chunks else None
