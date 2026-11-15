"""Shared retrieval helpers. Patch vectors stay in `conchz`; report vectors stay in `report`."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from psycopg import Connection
from psycopg.rows import dict_row

from consilium.api.schemas.case import CaseSummary  # pragma: allowlist secret
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret
from consilium.api.schemas.patient import PatientRef  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    CaseHit,
    Passage,
    PatchHit,
    SearchFilters,
)

# pgvector 0.8 filtered HNSW. `relaxed_order` keeps scanning until LIMIT is filled
# under selective predicates (patient, specialty, ICD-10, stain) instead of
# returning a short list from the first ef_search candidates. ef_search is the
# candidate-list size of each iteration; the server default is 40.
HNSW_ITERATIVE_SCAN = "relaxed_order"
HNSW_EF_SEARCH = 100
PATCH_CANDIDATE_LIMIT = 200
RRF_K = 60
PATCHES_PER_CASE = 3

MatchKind = Literal["morphology", "keyword", "semantic"]
StatusMode = Literal["signed", "open", "any"]

_SECTION_WEIGHT = {
    "conclusion": 5,
    "microscopic_description": 4,
    "additional_info": 3,
    "gross_description": 2,
    "body": 1,
    "clinical_history": 0,
}


class SearchError(Exception):
    """A search the caller can turn into an HTTP error. The agent tools catch it too."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def configure_hnsw(conn: Connection) -> None:
    """Enable filtered HNSW inside the current transaction.

    `SET LOCAL` lasts until commit, so every vector query in the transaction
    uses iterative scan. Requires pgvector 0.8 (`relaxed_order` is one of
    `off`, `relaxed_order`, `strict_order` on 0.8.7).
    """
    conn.execute(f"SET LOCAL hnsw.iterative_scan = '{HNSW_ITERATIVE_SCAN}'")
    conn.execute(f"SET LOCAL hnsw.ef_search = {int(HNSW_EF_SEARCH)}")


def took_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def join_notice(*parts: str | None) -> str | None:
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return text or None


def cap_notice(count: int, limit: int, noun: str) -> str | None:
    if count >= limit:
        return f"Search stopped after the nearest {limit} {noun}."
    return None


def relative_scores(raw: list[float]) -> list[float]:
    """Scale a page so the best hit is 1. The value is not a probability."""
    if not raw:
        return []
    top = max(raw)
    if top > 0:
        scores = [min(1.0, max(0.0, value / top)) for value in raw]
    else:
        scores = [1.0 if value == top else 0.0 for value in raw]
    best = max(range(len(raw)), key=lambda index: (raw[index], -index))
    scores[best] = 1.0
    return scores


def match_list(kinds: set[str]) -> list[MatchKind]:
    order: tuple[MatchKind, ...] = ("morphology", "keyword", "semantic")
    return [kind for kind in order if kind in kinds]


def clamp_similarity(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(-1.0, min(1.0, float(value)))


def like_prefix(value: str) -> str:
    """Escape a user prefix for `ILIKE ... ESCAPE '!'`."""
    escaped = value.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return f"{escaped}%"


def fetchall(
    conn: Connection,
    query: str,
    params: Mapping[str, Any] | Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]


def fetchone(
    conn: Connection,
    query: str,
    params: Mapping[str, Any] | Sequence[Any] | None = None,
) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


@dataclass(frozen=True)
class RetrievalScope:
    """Corpus rules and filters. Evidence search (a context case) is signed-out only."""

    evidence: bool
    context_case_id: str | None
    context_patient_id: str | None
    patient_id: str | None
    specialties: tuple[str, ...] | None
    icd10_like: str | None
    stain: str | None
    status: str | None
    exclude_case_ids: tuple[str, ...]

    def status_mode(self, *, default: StatusMode) -> StatusMode:
        """Evidence search ignores `filters.status` and keeps the caller's default."""
        if self.evidence:
            return default
        if self.status == "open":
            return "open"
        if self.status == "signed_out":
            return "signed"
        return default


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def retrieval_scope(
    conn: Connection,
    *,
    context_case_id: str | None,
    filters: SearchFilters | None,
    extra_exclude: Sequence[str] = (),
) -> RetrievalScope:
    context_patient: str | None = None
    if context_case_id is not None:
        row = fetchone(
            conn,
            "SELECT id, patient_id FROM path_case WHERE id = %s",
            (context_case_id,),
        )
        if row is None:
            raise SearchError(404, "not_found", "Case not found.")
        context_patient = str(row["patient_id"])
    exclude: list[str] = []
    if context_case_id is not None:
        exclude.append(context_case_id)
    for case_id in extra_exclude:
        if case_id not in exclude:
            exclude.append(case_id)
    chosen = filters or SearchFilters()
    specialties = tuple(item.value for item in chosen.specialty) if chosen.specialty else None
    prefix = _text(chosen.icd10_prefix)
    status = chosen.status.value if chosen.status is not None else None
    return RetrievalScope(
        evidence=context_case_id is not None,
        context_case_id=context_case_id,
        context_patient_id=context_patient,
        patient_id=_text(chosen.patient_id),
        specialties=specialties or None,
        icd10_like=like_prefix(prefix) if prefix else None,
        stain=_text(chosen.stain),
        status=status,
        exclude_case_ids=tuple(exclude),
    )


def filter_clauses(
    scope: RetrievalScope,
    *,
    case_alias: str,
    patient_column: str | None = None,
    specialty_column: str | None = None,
    stain_column: str | None = None,
    status_mode: StatusMode,
) -> tuple[list[str], dict[str, Any]]:
    """Predicates that belong in the same SQL statement as the vector distance.

    `patient_column` / `specialty_column` point at the denormalised patch or
    chunk columns so a filtered HNSW scan does not wait on a later join.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if scope.exclude_case_ids:
        clauses.append(f"{case_alias}.id <> ALL(%(exclude_case_ids)s)")
        params["exclude_case_ids"] = list(scope.exclude_case_ids)
    if scope.patient_id:
        column = patient_column or f"{case_alias}.patient_id"
        clauses.append(f"{column} = %(patient_id)s")
        params["patient_id"] = scope.patient_id
    if scope.specialties:
        column = specialty_column or f"{case_alias}.specialty"
        clauses.append(f"{column} = ANY(%(specialties)s)")
        params["specialties"] = list(scope.specialties)
    if scope.icd10_like:
        # Open cases keep ICD-10 for evaluation only. A prefix never matches them.
        clauses.append(
            f"({case_alias}.status = 'signed_out' AND {case_alias}.icd10 ILIKE "
            "%(icd10_like)s ESCAPE '!')"
        )
        params["icd10_like"] = scope.icd10_like
    if scope.stain:
        if stain_column:
            clauses.append(f"{stain_column} = %(stain)s")
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM slide stain_slide "
                f"WHERE stain_slide.case_id = {case_alias}.id "
                "AND stain_slide.stain = %(stain)s)"
            )
        params["stain"] = scope.stain
    if status_mode == "signed":
        clauses.append(f"{case_alias}.status = 'signed_out'")
    elif status_mode == "open":
        clauses.append(f"{case_alias}.status = 'open'")
    return clauses, params


def sql_where(clauses: Sequence[str]) -> str:
    if not clauses:
        return "TRUE"
    return " AND ".join(clauses)


_SUMMARY_SQL = """
SELECT
    c.id,
    c.patient_id,
    p.display_label,
    p.sex,
    p.is_synthetic_linkage,
    (SELECT count(*)::int FROM path_case pc WHERE pc.patient_id = c.patient_id) AS case_count,
    c.specimen_label,
    c.specialty,
    c.patient_age,
    c.patient_sex,
    CASE WHEN c.status = 'signed_out' THEN c.icd10 ELSE NULL END AS icd10,
    c.status,
    c.accessioned_at,
    a.id AS assignee_id,
    a.name AS assignee_name,
    a.primary_specialty AS assignee_specialty,
    a.is_synthetic AS assignee_synthetic,
    (SELECT count(*)::int FROM slide s WHERE s.case_id = c.id) AS slide_count,
    (
        SELECT '/api/slides/' || s.id || '/thumbnail'
        FROM slide s
        WHERE s.case_id = c.id
        ORDER BY s.ordinal
        LIMIT 1
    ) AS thumbnail_url,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed'
        THEN NULLIF(split_part(coalesce(r.conclusion, ''), E'\\n', 1), '')
        ELSE NULL
    END AS conclusion_line,
    CASE WHEN r.status = 'signed' THEN auth.id ELSE a.id END AS author_id,
    CASE WHEN r.status = 'signed' THEN auth.name ELSE a.name END AS author_name,
    CASE
        WHEN r.status = 'signed' THEN auth.primary_specialty
        ELSE a.primary_specialty
    END AS author_specialty,
    CASE
        WHEN r.status = 'signed' THEN auth.is_synthetic
        ELSE a.is_synthetic
    END AS author_synthetic
FROM path_case c
JOIN patient p ON p.id = c.patient_id
JOIN pathologist a ON a.id = c.assigned_to
LEFT JOIN report r ON r.case_id = c.id
LEFT JOIN pathologist auth ON auth.id = r.author_id
WHERE c.id = ANY(%(ids)s)
"""


def load_summaries(conn: Connection, case_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not case_ids:
        return {}
    rows = fetchall(conn, _SUMMARY_SQL, {"ids": list(case_ids)})
    return {str(row["id"]): row for row in rows}


def _ref(row: dict[str, Any], prefix: str) -> PathologistRef:
    return PathologistRef(
        id=str(row[f"{prefix}_id"]),
        name=str(row[f"{prefix}_name"]),
        primary_specialty=row[f"{prefix}_specialty"],
        is_synthetic=bool(row[f"{prefix}_synthetic"]),
    )


def case_summary(row: dict[str, Any]) -> CaseSummary:
    """Case card safe for an open case: no ICD-10 and no conclusion line."""
    return CaseSummary(
        id=str(row["id"]),
        patient=PatientRef(
            id=str(row["patient_id"]),
            display_label=str(row["display_label"]),
            sex=row["sex"],
            case_count=int(row["case_count"]),
            is_synthetic_linkage=bool(row["is_synthetic_linkage"]),
        ),
        specimen_label=row["specimen_label"],
        specialty=row["specialty"],
        patient_age=row["patient_age"],
        patient_sex=row["patient_sex"],
        icd10=row["icd10"],
        status=row["status"],
        assigned_to=_ref(row, "assignee"),
        accessioned_at=row["accessioned_at"],
        slide_count=int(row["slide_count"]),
        thumbnail_url=row["thumbnail_url"],
        conclusion_line=row["conclusion_line"],
    )


def build_case_hits(
    conn: Connection,
    ordered_ids: Sequence[str],
    *,
    context_patient_id: str | None,
    raw_scores: Sequence[float],
    matched_by: Mapping[str, set[str]],
    patches: Mapping[str, list[PatchHit]],
    patch_counts: Mapping[str, int],
    passages: Mapping[str, Passage | None],
) -> list[CaseHit]:
    if len(ordered_ids) != len(raw_scores):
        raise SearchError(500, "error", "Search scores were not aligned with cases.")
    summaries = load_summaries(conn, ordered_ids)
    scores = relative_scores([float(value) for value in raw_scores])
    hits: list[CaseHit] = []
    for index, case_id in enumerate(ordered_ids):
        row = summaries.get(case_id)
        if row is None:
            raise SearchError(500, "error", "A search hit case is missing.")
        hits.append(
            CaseHit(
                case=case_summary(row),
                author=_ref(row, "author"),
                same_patient=bool(context_patient_id)
                and str(row["patient_id"]) == context_patient_id,
                score=scores[index],
                matched_by=match_list(matched_by.get(case_id, set())),
                patches=list(patches.get(case_id, [])),
                patch_match_count=int(patch_counts.get(case_id, 0)),
                passage=passages.get(case_id),
            )
        )
    return hits


def exact_case_ids(conn: Connection, text: str, scope: RetrievalScope) -> list[str]:
    """F-02.3: a case id, patient id / display label, or ICD-10 code comes first.

    ICD-10 matches signed-out cases only, so a held-out code is not confirmed.
    An open case is returned only in global search, and only without report text.
    """
    needle = text.strip()
    if needle == "":
        return []
    case_row = fetchone(
        conn,
        "SELECT id FROM path_case WHERE lower(id) = lower(%s)",
        (needle,),
    )
    if case_row is not None:
        return _filter_exact(conn, [str(case_row["id"])], scope, allow_open=True)
    patients = fetchall(
        conn,
        """
        SELECT id FROM patient
        WHERE lower(id) = lower(%s) OR lower(display_label) = lower(%s)
        """,
        (needle, needle),
    )
    if patients:
        owned = fetchall(
            conn,
            """
            SELECT id FROM path_case
            WHERE patient_id = ANY(%s)
            ORDER BY accessioned_at DESC, id
            """,
            ([str(row["id"]) for row in patients],),
        )
        return _filter_exact(conn, [str(row["id"]) for row in owned], scope, allow_open=True)
    coded = fetchall(
        conn,
        """
        SELECT id FROM path_case
        WHERE status = 'signed_out'
          AND icd10 IS NOT NULL
          AND lower(icd10) = lower(%s)
        ORDER BY accessioned_at DESC, id
        """,
        (needle,),
    )
    return _filter_exact(conn, [str(row["id"]) for row in coded], scope, allow_open=False)


def _filter_exact(
    conn: Connection,
    candidates: Sequence[str],
    scope: RetrievalScope,
    *,
    allow_open: bool,
) -> list[str]:
    if not candidates:
        return []
    if scope.status == "open" and not allow_open:
        return []
    clauses, params = filter_clauses(
        scope,
        case_alias="c",
        status_mode="any",
    )
    # filter_clauses adds exclusion, patient, specialty, icd10 and stain, but
    # status_mode "any" leaves status to the rule below.
    if scope.evidence or scope.status == "signed_out" or not allow_open:
        clauses.append("c.status = 'signed_out'")
    elif scope.status == "open":
        clauses.append("c.status = 'open'")
    params["ids"] = list(candidates)
    rows = fetchall(
        conn,
        f"""
        SELECT c.id
        FROM path_case c
        WHERE c.id = ANY(%(ids)s)
          AND {sql_where(clauses)}
        ORDER BY c.accessioned_at DESC, c.id
        """,
        params,
    )
    return [str(row["id"]) for row in rows]


def section_weight(section: str) -> int:
    return _SECTION_WEIGHT.get(section, 0)


def keyword_highlights(
    conn: Connection,
    chunks: Sequence[Mapping[str, Any]],
    query: str,
) -> dict[int, list[tuple[int, int]]]:
    """Character offsets of keyword matches inside each chunk. Empty for stop-words."""
    if not chunks or query.strip() == "":
        return {}
    ids = [int(chunk["id"]) for chunk in chunks]
    texts = {int(chunk["id"]): str(chunk["text"]) for chunk in chunks}
    rows = fetchall(
        conn,
        """
        SELECT ch.id AS chunk_id,
               dbg.alias,
               dbg.token,
               dbg.token_ord,
               to_tsvector('english', dbg.token)
                   @@ websearch_to_tsquery('english', %(query)s) AS hit
        FROM report_chunk ch
        CROSS JOIN LATERAL ts_debug('english', ch.text)
            WITH ORDINALITY AS dbg(
                alias, description, token, dictionaries, dictionary, lexemes, token_ord
            )
        WHERE ch.id = ANY(%(ids)s)
        ORDER BY ch.id, dbg.token_ord
        """,
        {"ids": ids, "query": query},
    )
    grouped: dict[int, list[tuple[str, bool]]] = {chunk_id: [] for chunk_id in ids}
    for row in rows:
        # `ts_debug` emits a hyphenated word and then its parts. The parts
        # repeat text already consumed by the compound token.
        if str(row["alias"]).endswith("part"):
            continue
        grouped[int(row["chunk_id"])].append((str(row["token"]), bool(row["hit"])))
    return {
        chunk_id: _offsets(texts[chunk_id], tokens) for chunk_id, tokens in grouped.items()
    }


def _offsets(text: str, tokens: Sequence[tuple[str, bool]]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for token, hit in tokens:
        if text.startswith(token, cursor):
            start = cursor
        else:
            start = text.find(token, cursor)
            if start < 0 or any(char.isalnum() for char in text[cursor:start]):
                continue
        end = start + len(token)
        cursor = end
        if hit and end > start:
            ranges.append((start, end))
    return ranges


def coverage(ranges: Sequence[tuple[int, int]]) -> int:
    return sum(end - start for start, end in ranges)
