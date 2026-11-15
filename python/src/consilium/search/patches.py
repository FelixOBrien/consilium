"""Patch and slide retrieval in the `conchz` space (768-d halfvec).

Q1 uses a stored patch vector, Q2 the L2-normalised mean of intersecting patches,
Q3 the stored slide vector, and Q4 a CONCH-Z text encoding. None of these queries
read `report_chunk.embedding`.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from pgvector import HalfVector
from psycopg import Connection

from consilium.api.schemas.common import Region  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchHit,
    PatchSearchRequest,
    SearchResponse,
    SlideScopeResponse,
)
from consilium.embed.spaces import CONCHZ_DIM, ConchzEmbedding  # pragma: allowlist secret
from consilium.embed.text import EmbedError, TextEncoders  # pragma: allowlist secret
from consilium.search.common import (  # pragma: allowlist secret
    PATCH_CANDIDATE_LIMIT,
    PATCHES_PER_CASE,
    RetrievalScope,
    SearchError,
    build_case_hits,
    cap_notice,
    clamp_similarity,
    configure_hnsw,
    exact_case_ids,
    fetchall,
    fetchone,
    filter_clauses,
    join_notice,
    retrieval_scope,
    sql_where,
    took_ms,
)

_NO_TISSUE = "Region covers no tissue patches."


def search_patches(
    conn: Connection,
    request: PatchSearchRequest,
    encoders: TextEncoders,
) -> SearchResponse | SlideScopeResponse:
    """Run Q1–Q4. `scope='slide'` returns patches on one slide; otherwise cases."""
    started = time.perf_counter()
    kind = _query_kind(request)
    notice = _encode_notice(request, encoders) if kind == "text_patches" else None
    with conn.transaction():
        configure_hnsw(conn)
        if request.scope == "slide":
            return _search_slide(conn, request, encoders, kind, notice, started)
        return _search_corpus(conn, request, encoders, kind, notice, started)


def _query_kind(request: PatchSearchRequest) -> str:
    selected = [
        name
        for name, value in (
            ("patch", request.patch_id),
            ("region", request.region),
            ("slide", request.slide_id),
            ("text_patches", request.text),
        )
        if value is not None
    ]
    if len(selected) != 1:
        raise SearchError(
            422,
            "validation_error",
            "Provide one of patch_id, region, slide_id or text.",
        )
    if request.text is not None and request.text.strip() == "":
        raise SearchError(422, "validation_error", "text must not be empty")
    kind = selected[0]
    if kind == "slide" and request.scope == "slide":
        raise SearchError(
            422,
            "validation_error",
            "scope slide applies to a patch, region or text query.",
        )
    if kind == "text_patches" and request.scope == "slide" and request.context_case_id is None:
        raise SearchError(
            422,
            "validation_error",
            "A text query with scope slide needs context_case_id.",
        )
    return kind


def _encode_notice(request: PatchSearchRequest, encoders: TextEncoders) -> str | None:
    if request.text is None:
        return None
    try:
        encoded = encoders.encode_image_text(request.text.strip())
    except EmbedError as exc:
        raise SearchError(422, "validation_error", str(exc)) from exc
    return encoded.truncation_notice()


def _conchz_query(encoders: TextEncoders, text: str) -> ConchzEmbedding:
    try:
        return encoders.encode_image_text(text.strip()).vector
    except EmbedError as exc:
        raise SearchError(422, "validation_error", str(exc)) from exc


def _halfvec(embedding: ConchzEmbedding) -> HalfVector:
    if embedding.dim != CONCHZ_DIM:
        raise SearchError(500, "error", "CONCH-Z query vector has the wrong dimension.")
    # pgvector accepts a list, not the tuple `to_float16` returns.
    return HalfVector(list(embedding.to_float16()))


def _stored_conchz(value: object) -> ConchzEmbedding:
    try:
        floats = _vector_floats(value)
    except (TypeError, ValueError) as exc:
        raise SearchError(500, "error", "Stored tissue vector is unreadable.") from exc
    try:
        return ConchzEmbedding.from_halfvec(floats)
    except ValueError as exc:
        raise SearchError(500, "error", "Stored tissue vector is not a unit embedding.") from exc


def _vector_floats(value: object) -> list[float]:
    """Read a pgvector value, a text literal, or a sequence of components."""
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        raw = to_list()
    elif isinstance(value, str):
        inner = value.strip()
        if inner.startswith("[") and inner.endswith("]"):
            inner = inner[1:-1]
        raw = [] if inner == "" else inner.split(",")
    else:
        raw = list(value)  # type: ignore[arg-type]
    return [float(item) for item in raw]


def _search_slide(
    conn: Connection,
    request: PatchSearchRequest,
    encoders: TextEncoders,
    kind: str,
    notice: str | None,
    started: float,
) -> SlideScopeResponse:
    # Slide scope looks at the open slide, which is the context case. Do not
    # apply the corpus exclusion or the query would drop every patch on it.
    scope = replace(
        retrieval_scope(conn, context_case_id=request.context_case_id, filters=request.filters),
        exclude_case_ids=(),
    )
    slide_id, query, exclude_ids = _slide_query(conn, request, encoders, kind)
    rows = _slide_patch_rows(
        conn,
        slide_id=slide_id,
        query=_halfvec(query),
        exclude_ids=exclude_ids,
        scope=scope,
        limit=request.limit,
    )
    total = int(rows[0]["total"]) if rows else 0
    patches = [_patch_hit(row) for row in rows]
    return SlideScopeResponse(
        query_kind=kind,  # type: ignore[arg-type]
        patches=patches,
        total_candidates=total,
        took_ms=took_ms(started),
        notice=notice,
    )


def _slide_query(
    conn: Connection,
    request: PatchSearchRequest,
    encoders: TextEncoders,
    kind: str,
) -> tuple[str, ConchzEmbedding, list[int]]:
    if kind == "patch":
        row = _patch_row(conn, request.patch_id)
        return str(row["slide_id"]), _stored_conchz(row["embedding"]), [int(row["id"])]
    if kind == "region":
        region = request.region
        assert region is not None
        _require_slide(conn, region.slide_id)
        vectors, ids = _region_vectors(conn, region)
        return region.slide_id, _mean_conchz(vectors), ids
    row = fetchone(
        conn,
        """
        SELECT s.id
        FROM path_case c
        JOIN slide s ON s.case_id = c.id
        WHERE c.id = %s AND s.status = 'ready' AND s.embedding IS NOT NULL
        ORDER BY s.ordinal
        LIMIT 1
        """,
        (request.context_case_id,),
    )
    if row is None:
        raise SearchError(404, "not_found", "The context case has no slide.")
    assert request.text is not None
    return str(row["id"]), _conchz_query(encoders, request.text), []


def _search_corpus(
    conn: Connection,
    request: PatchSearchRequest,
    encoders: TextEncoders,
    kind: str,
    notice: str | None,
    started: float,
) -> SearchResponse:
    query, query_case_id = _corpus_vector(conn, request, encoders, kind)
    scope = retrieval_scope(
        conn,
        context_case_id=request.context_case_id,
        filters=request.filters,
        extra_exclude=[query_case_id] if query_case_id else (),
    )
    exact: list[str] = []
    if kind == "text_patches" and request.text is not None:
        exact = exact_case_ids(conn, request.text, scope)
    if kind == "slide":
        return _cases_by_slide(conn, scope, query, notice, request.limit, started)
    return _cases_by_patches(
        conn,
        scope,
        query,
        kind,
        exact,
        notice,
        request.limit,
        started,
    )


def _corpus_vector(
    conn: Connection,
    request: PatchSearchRequest,
    encoders: TextEncoders,
    kind: str,
) -> tuple[ConchzEmbedding, str | None]:
    if kind == "patch":
        row = _patch_row(conn, request.patch_id)
        return _stored_conchz(row["embedding"]), str(row["case_id"])
    if kind == "region":
        region = request.region
        assert region is not None
        slide = _require_slide(conn, region.slide_id)
        vectors, _ids = _region_vectors(conn, region)
        return _mean_conchz(vectors), str(slide["case_id"])
    if kind == "slide":
        slide = _require_slide(conn, request.slide_id or "")
        if slide["embedding"] is None:
            raise SearchError(422, "validation_error", "Slide has no tissue embedding.")
        return _stored_conchz(slide["embedding"]), str(slide["case_id"])
    assert request.text is not None
    return _conchz_query(encoders, request.text), None


def _patch_row(conn: Connection, patch_id: int | None) -> dict[str, Any]:
    row = fetchone(
        conn,
        "SELECT id, slide_id, case_id, embedding FROM patch WHERE id = %s",
        (patch_id,),
    )
    if row is None:
        raise SearchError(404, "not_found", "Patch not found.")
    return row


def _require_slide(conn: Connection, slide_id: str) -> dict[str, Any]:
    row = fetchone(
        conn,
        "SELECT id, case_id, embedding, status FROM slide WHERE id = %s",
        (slide_id,),
    )
    if row is None:
        raise SearchError(404, "not_found", "Slide not found.")
    return row


def _region_vectors(conn: Connection, region: Region) -> tuple[list[list[float]], list[int]]:
    rows = fetchall(
        conn,
        """
        SELECT id, embedding
        FROM patch
        WHERE slide_id = %(slide_id)s
          AND x < %(right)s
          AND x + size > %(x)s
          AND y < %(bottom)s
          AND y + size > %(y)s
        ORDER BY id
        """,
        {
            "slide_id": region.slide_id,
            "x": region.x,
            "y": region.y,
            "right": region.x + region.width,
            "bottom": region.y + region.height,
        },
    )
    if not rows:
        raise SearchError(422, "validation_error", _NO_TISSUE)
    vectors: list[list[float]] = []
    ids: list[int] = []
    for row in rows:
        vectors.append(_vector_floats(row["embedding"]))
        ids.append(int(row["id"]))
    return vectors, ids


def _mean_conchz(vectors: list[list[float]]) -> ConchzEmbedding:
    if not vectors:
        raise SearchError(422, "validation_error", _NO_TISSUE)
    total = [0.0] * CONCHZ_DIM
    for vector in vectors:
        if len(vector) != CONCHZ_DIM:
            raise SearchError(500, "error", "Patch embedding has an unexpected dimension.")
        for index, component in enumerate(vector):
            total[index] += component
    scale = 1.0 / len(vectors)
    mean = [component * scale for component in total]
    norm = sum(component * component for component in mean) ** 0.5
    if norm == 0.0:
        raise SearchError(422, "validation_error", _NO_TISSUE)
    try:
        return ConchzEmbedding(values=tuple(component / norm for component in mean))
    except ValueError as exc:
        raise SearchError(422, "validation_error", _NO_TISSUE) from exc


def _cases_by_patches(
    conn: Connection,
    scope: RetrievalScope,
    query: ConchzEmbedding,
    kind: str,
    exact: list[str],
    notice: str | None,
    limit: int,
    started: float,
) -> SearchResponse:
    # Open cases are not in the corpus. Status `open` is an exact-id lookup only.
    rows: list[dict[str, Any]] = []
    if scope.status_mode(default="signed") != "open":
        rows = _nearest_patches(conn, scope, _halfvec(query))
    grouped = _group_patches(rows)
    exact_set = set(exact)
    ordered: list[str] = []
    seen: set[str] = set()
    for case_id in exact:
        if case_id not in seen:
            ordered.append(case_id)
            seen.add(case_id)
    for case_id, _patches, _count, _best in grouped:
        if case_id not in seen:
            ordered.append(case_id)
            seen.add(case_id)
    ordered = ordered[:limit]
    best = {case_id: score for case_id, _patches, _count, score in grouped}
    counts = {case_id: count for case_id, _patches, count, _score in grouped}
    patch_hits = {
        case_id: [_patch_hit(row) for row in patches[:PATCHES_PER_CASE]]
        for case_id, patches, _count, _score in grouped
    }
    missing = [case_id for case_id in ordered if case_id not in patch_hits]
    if missing and scope.status_mode(default="signed") != "open":
        extra = _top_patches_for_cases(conn, missing, _halfvec(query))
        for case_id, patches, count in extra:
            patch_hits[case_id] = patches
            counts[case_id] = count
    raw: list[float] = []
    matched: dict[str, set[str]] = {}
    for index, case_id in enumerate(ordered):
        if case_id in exact_set:
            raw.append(2.0 - index * 1e-4)
        else:
            raw.append(best.get(case_id, 0.0))
        if case_id in best or patch_hits.get(case_id):
            matched[case_id] = {"morphology"}
        else:
            matched[case_id] = set()
    hits = build_case_hits(
        conn,
        ordered,
        context_patient_id=scope.context_patient_id,
        raw_scores=raw,
        matched_by=matched,
        patches=patch_hits,
        patch_counts=counts,
        passages={case_id: None for case_id in ordered},
    )
    return SearchResponse(
        query_kind=kind,  # type: ignore[arg-type]
        hits=hits,
        total_candidates=len(rows),
        took_ms=took_ms(started),
        notice=join_notice(notice, cap_notice(len(rows), PATCH_CANDIDATE_LIMIT, "patches")),
    )


def _nearest_patches(
    conn: Connection,
    scope: RetrievalScope,
    query: HalfVector,
) -> list[dict[str, Any]]:
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        patient_column="p.patient_id",
        specialty_column="p.specialty",
        stain_column="s.stain",
        status_mode="signed",
    )
    clauses.insert(0, "p.in_corpus = true")
    params["query"] = query
    params["limit"] = PATCH_CANDIDATE_LIMIT
    return fetchall(
        conn,
        f"""
        SELECT
            p.id AS patch_id,
            p.slide_id,
            p.case_id,
            p.x,
            p.y,
            p.size,
            (1 - (p.embedding <=> %(query)s::halfvec(768)))::float8 AS similarity
        FROM patch p
        JOIN path_case c ON c.id = p.case_id
        JOIN slide s ON s.id = p.slide_id
        WHERE {sql_where(clauses)}
        ORDER BY p.embedding <=> %(query)s::halfvec(768)
        LIMIT %(limit)s
        """,
        params,
    )


def _group_patches(
    rows: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]], int, float]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row["case_id"]), []).append(row)
    ranked: list[tuple[float, str, list[dict[str, Any]]]] = []
    for case_id, patches in buckets.items():
        patches.sort(key=lambda item: (-float(item["similarity"]), int(item["patch_id"])))
        ranked.append((float(patches[0]["similarity"]), case_id, patches))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        (case_id, patches, len(patches), best) for best, case_id, patches in ranked
    ]


def _top_patches_for_cases(
    conn: Connection,
    case_ids: list[str],
    query: HalfVector,
) -> list[tuple[str, list[PatchHit], int]]:
    rows = fetchall(
        conn,
        """
        SELECT case_id, patch_id, slide_id, x, y, size, similarity, match_count
        FROM (
            SELECT
                p.case_id,
                p.id AS patch_id,
                p.slide_id,
                p.x,
                p.y,
                p.size,
                (1 - (p.embedding <=> %(query)s::halfvec(768)))::float8 AS similarity,
                row_number() OVER (
                    PARTITION BY p.case_id
                    ORDER BY p.embedding <=> %(query)s::halfvec(768), p.id
                ) AS rn,
                count(*) OVER (PARTITION BY p.case_id) AS match_count
            FROM patch p
            WHERE p.case_id = ANY(%(case_ids)s)
              AND p.in_corpus = true
        ) ranked
        WHERE rn <= %(per_case)s
        """,
        {"query": query, "case_ids": case_ids, "per_case": PATCHES_PER_CASE},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for row in rows:
        case_id = str(row["case_id"])
        grouped.setdefault(case_id, []).append(row)
        counts[case_id] = int(row["match_count"])
    return [
        (case_id, [_patch_hit(row) for row in grouped[case_id]], counts[case_id])
        for case_id in case_ids
        if case_id in grouped
    ]


def _cases_by_slide(
    conn: Connection,
    scope: RetrievalScope,
    query: ConchzEmbedding,
    notice: str | None,
    limit: int,
    started: float,
) -> SearchResponse:
    rows: list[dict[str, Any]] = []
    if scope.status_mode(default="signed") != "open":
        rows = _nearest_slides(conn, scope, _halfvec(query))
    best: dict[str, float] = {}
    order: list[str] = []
    for row in rows:
        case_id = str(row["case_id"])
        similarity = float(row["similarity"])
        if case_id not in best:
            best[case_id] = similarity
            order.append(case_id)
        elif similarity > best[case_id]:
            best[case_id] = similarity
    order.sort(key=lambda case_id: (-best[case_id], case_id))
    ordered = order[:limit]
    extra = _top_patches_for_cases(conn, ordered, _halfvec(query)) if ordered else []
    patch_hits = {case_id: patches for case_id, patches, _count in extra}
    counts = {case_id: count for case_id, _patches, count in extra}
    hits = build_case_hits(
        conn,
        ordered,
        context_patient_id=scope.context_patient_id,
        raw_scores=[best[case_id] for case_id in ordered],
        matched_by={case_id: {"morphology"} for case_id in ordered},
        patches=patch_hits,
        patch_counts=counts,
        passages={case_id: None for case_id in ordered},
    )
    return SearchResponse(
        query_kind="slide",
        hits=hits,
        total_candidates=len(rows),
        took_ms=took_ms(started),
        notice=join_notice(notice, cap_notice(len(rows), PATCH_CANDIDATE_LIMIT, "slides")),
    )


def _nearest_slides(
    conn: Connection,
    scope: RetrievalScope,
    query: HalfVector,
) -> list[dict[str, Any]]:
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        stain_column="s.stain",
        status_mode="signed",
    )
    clauses.insert(0, "s.status = 'ready'")
    clauses.insert(1, "s.embedding IS NOT NULL")
    params["query"] = query
    params["limit"] = PATCH_CANDIDATE_LIMIT
    return fetchall(
        conn,
        f"""
        SELECT
            s.id AS slide_id,
            s.case_id,
            (1 - (s.embedding <=> %(query)s::halfvec(768)))::float8 AS similarity
        FROM slide s
        JOIN path_case c ON c.id = s.case_id
        WHERE {sql_where(clauses)}
          AND EXISTS (
              SELECT 1 FROM patch p
              WHERE p.case_id = c.id AND p.in_corpus = true
          )
        ORDER BY s.embedding <=> %(query)s::halfvec(768)
        LIMIT %(limit)s
        """,
        params,
    )


def _slide_patch_rows(
    conn: Connection,
    *,
    slide_id: str,
    query: HalfVector,
    exclude_ids: list[int],
    scope: RetrievalScope,
    limit: int,
) -> list[dict[str, Any]]:
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        patient_column="p.patient_id",
        specialty_column="p.specialty",
        stain_column="s.stain",
        status_mode=scope.status_mode(default="any"),
    )
    clauses.insert(0, "p.slide_id = %(slide_id)s")
    params["slide_id"] = slide_id
    params["query"] = query
    params["limit"] = limit
    if exclude_ids:
        clauses.append("p.id <> ALL(%(exclude_ids)s)")
        params["exclude_ids"] = exclude_ids
    return fetchall(
        conn,
        f"""
        SELECT patch_id, slide_id, x, y, size, similarity, total
        FROM (
            SELECT
                p.id AS patch_id,
                p.slide_id,
                p.x,
                p.y,
                p.size,
                (1 - (p.embedding <=> %(query)s::halfvec(768)))::float8 AS similarity,
                count(*) OVER () AS total
            FROM patch p
            JOIN path_case c ON c.id = p.case_id
            JOIN slide s ON s.id = p.slide_id
            WHERE {sql_where(clauses)}
        ) ranked
        ORDER BY similarity DESC, patch_id
        LIMIT %(limit)s
        """,
        params,
    )


def _patch_hit(row: dict[str, Any]) -> PatchHit:
    patch_id = int(row["patch_id"])
    return PatchHit(
        patch_id=patch_id,
        slide_id=str(row["slide_id"]),
        x=int(row["x"]),
        y=int(row["y"]),
        size=int(row["size"]),
        similarity=clamp_similarity(float(row["similarity"])),
        thumbnail_url=f"/api/patches/{patch_id}/thumbnail",
    )
