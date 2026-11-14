"""Offline retrieval evaluation on held-out cases.

Research prototype. The numbers measure whether search returns related prior
cases. They are not a clinical diagnosis and not for clinical use.

Withheld reports are read from Postgres for scoring only. This module does not
register an API route and does not put report prose in the written report.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pgvector import HalfVector
from psycopg import Connection

from consilium.api.schemas.search import (  # pragma: allowlist secret
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
)
from consilium.config import get_settings, repo_root  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    MockTextEncoder,
    TextEncoders,
    build_text_encoders,
)
from consilium.search import (  # pragma: allowlist secret
    SearchError,
    configure_hnsw,
    search_patches,
    search_reports,
)
from consilium.search.common import (  # pragma: allowlist secret
    PATCH_CANDIDATE_LIMIT,
    PATCHES_PER_CASE,
    RRF_K,
    fetchall,
)

NOTICE = (
    "Research prototype. This is a retrieval evaluation of whether search returns "
    "related prior cases. It is not a measure of clinical diagnostic accuracy and "
    "it is not for clinical use."
)

# How much a signed-out prior lifts a held-out case when choosing demo cases.
# Clarity stays on a 0–1 scale; the bonus only reorders close calls.
LONGITUDINAL_WEIGHT = 0.25
SEARCH_LIMIT = 50
TOP_K = 10
AT_K = (5, 10)
RELEVANCE_KINDS = ("icd_o3_histology", "icd10_category", "specialty")
SEARCH_TYPES = ("slide", "best_patch", "mean_top_3", "reports")
_METRIC_NAMES = ("precision_at_5", "hit_rate_at_5", "precision_at_10", "hit_rate_at_10")

_HELD_OUT_SQL = """
SELECT
    c.id,
    c.patient_id,
    c.specialty,
    c.morphology,
    c.icd10,
    pat.is_synthetic_linkage,
    NULLIF(btrim(r.clinical_history), '') AS clinical_history,
    (
        SELECT count(*)::int
        FROM path_case prior
        WHERE prior.patient_id = c.patient_id
          AND prior.id <> c.id
          AND prior.status = 'signed_out'
    ) AS signed_out_priors
FROM path_case c
JOIN patient pat ON pat.id = c.patient_id
LEFT JOIN report r ON r.case_id = c.id
WHERE c.is_held_out = true
  AND c.status = 'open'
ORDER BY c.id
"""

_SLIDE_SQL = """
SELECT case_id, id, embedding
FROM slide
WHERE case_id = ANY(%(case_ids)s)
  AND status = 'ready'
  AND embedding IS NOT NULL
ORDER BY case_id, ordinal, id
"""

_CORPUS_SQL = """
SELECT
    c.id,
    c.patient_id,
    c.specialty,
    c.morphology,
    c.icd10,
    pat.is_synthetic_linkage,
    EXISTS (
        SELECT 1 FROM patch p
        WHERE p.case_id = c.id AND p.in_corpus = true
    ) AS in_slide_corpus,
    EXISTS (
        SELECT 1 FROM report_chunk ch
        WHERE ch.case_id = c.id
          AND ch.in_corpus = true
          AND ch.section <> 'clinical_history'
    ) AS in_report_corpus
FROM path_case c
JOIN patient pat ON pat.id = c.patient_id
WHERE c.status = 'signed_out'
  AND c.is_held_out = false
ORDER BY c.id
"""

_PATCH_SQL = """
SELECT
    p.id AS patch_id,
    p.case_id,
    (1 - (p.embedding <=> %(query)s::halfvec(768)))::float8 AS similarity
FROM patch p
JOIN path_case c ON c.id = p.case_id
WHERE p.in_corpus = true
  AND c.status = 'signed_out'
  AND c.is_held_out = false
  AND c.id <> %(query_case_id)s
ORDER BY p.embedding <=> %(query)s::halfvec(768), p.id
LIMIT %(limit)s
"""


@dataclass(frozen=True)
class LabelledCase:
    """A case reduced to the fields retrieval metrics are allowed to see."""

    case_id: str
    patient_id: str
    specialty: str
    morphology: str | None
    icd10: str | None
    is_synthetic_linkage: bool


@dataclass(frozen=True)
class HeldOutCase:
    """One open held-out case, including withheld labels used only for scoring."""

    case_id: str
    patient_id: str
    specialty: str
    morphology: str | None
    icd10: str | None
    is_synthetic_linkage: bool
    clinical_history: str | None
    signed_out_priors: int
    slides: tuple[tuple[str, object], ...]


@dataclass(frozen=True)
class EvalResult:
    """Files written by one evaluation, plus the lines the CLI prints."""

    held_out_count: int
    slide_corpus_count: int
    winner: str
    best_patch_precision_at_5: float | None
    mean_top_3_precision_at_5: float | None
    scoring_n: int
    demo_case_ids: tuple[str, ...]
    json_path: Path
    markdown_path: Path
    summary_lines: tuple[str, ...]

    def summary(self) -> str:
        return "\n".join(self.summary_lines) + "\n"


def default_eval_dir() -> Path:
    """`<repo>/data/eval`. The `data/` tree is git-ignored."""
    return repo_root() / "data" / "eval"


def histology_code(morphology: str | None) -> str | None:
    """Four-digit ICD-O-3 histology code, the text before `/`."""
    if morphology is None:
        return None
    code = morphology.strip().split("/", 1)[0].strip()
    return code or None


def icd10_category(icd10: str | None) -> str | None:
    """Three-character ICD-10 category, for example `C50` from `C50.9`."""
    if icd10 is None:
        return None
    head = icd10.strip().upper().split(".", 1)[0]
    if len(head) < 3:
        return None
    return head[:3]


def label_value(
    *,
    morphology: str | None,
    icd10: str | None,
    specialty: str | None,
    kind: str,
) -> str | None:
    """The relevance label for one definition. Unknown kinds raise ValueError."""
    if kind == "icd_o3_histology":
        return histology_code(morphology)
    if kind == "icd10_category":
        return icd10_category(icd10)
    if kind == "specialty":
        text = (specialty or "").strip()
        return text or None
    raise ValueError(f"unknown relevance {kind}")


def case_value(case: LabelledCase | HeldOutCase, kind: str) -> str | None:
    return label_value(
        morphology=case.morphology,
        icd10=case.icd10,
        specialty=case.specialty,
        kind=kind,
    )


def precision_at_k(relevant: list[bool] | tuple[bool, ...], k: int) -> float:
    """Share of the first k hits that are relevant. Missing hits count against k."""
    if k <= 0:
        return 0.0
    return sum(1 for flag in list(relevant)[:k] if flag) / k


def hit_rate_at_k(relevant: list[bool] | tuple[bool, ...], k: int) -> float:
    """1 when any of the first k hits is relevant, otherwise 0."""
    if k <= 0:
        return 0.0
    return 1.0 if any(list(relevant)[:k]) else 0.0


def expected_precision_at_k(relevant: int, corpus: int, k: int) -> float:
    """Expected precision@k of a uniform sample without replacement.

    When the corpus is smaller than k, the unfilled slots count as not relevant,
    matching `precision_at_k`.
    """
    if k <= 0 or corpus <= 0 or relevant <= 0:
        return 0.0
    matched = min(relevant, corpus)
    drawn = min(k, corpus)
    return (drawn * (matched / corpus)) / k


def expected_hit_rate_at_k(relevant: int, corpus: int, k: int) -> float:
    """Probability a uniform sample of k contains at least one relevant case."""
    if k <= 0 or corpus <= 0 or relevant <= 0:
        return 0.0
    matched = min(relevant, corpus)
    drawn = min(k, corpus)
    total = math.comb(corpus, drawn)
    if total == 0:
        return 0.0
    missed = math.comb(corpus - matched, drawn)
    return 1.0 - missed / total


def retrieval_clarity(histology_precision_at_5: list[float] | tuple[float, ...]) -> float:
    """Mean histology precision@5 over the searches that actually ran."""
    if not histology_precision_at_5:
        return 0.0
    return sum(histology_precision_at_5) / len(histology_precision_at_5)


def demo_rank_score(clarity: float, signed_out_priors: int) -> float:
    """Clarity, plus a fixed bonus when the patient has a signed-out prior."""
    longitudinal = 1.0 if signed_out_priors > 0 else 0.0
    return clarity + LONGITUDINAL_WEIGHT * longitudinal


def fuse_case_ranks(
    rankings: list[list[str]] | tuple[list[str], ...],
    *,
    rrf_k: int = RRF_K,
) -> list[str]:
    """Reciprocal-rank fusion. One list is returned unchanged, ties break on id."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, case_id in enumerate(ranking, start=1):
            scores[case_id] = scores.get(case_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores, key=lambda case_id: (-scores[case_id], case_id))


def aggregate_patch_scores(
    similarities: dict[str, list[float]],
    *,
    top_n: int = PATCHES_PER_CASE,
) -> dict[str, tuple[float, float]]:
    """Map each case to `(best_patch, mean of up to top_n similarities)`."""
    if top_n < 1:
        raise ValueError("top_n must be positive")
    scored: dict[str, tuple[float, float]] = {}
    for case_id, values in similarities.items():
        ordered = sorted((float(value) for value in values), reverse=True)
        if not ordered:
            continue
        top = ordered[:top_n]
        scored[case_id] = (ordered[0], sum(top) / len(top))
    return scored


def select_hits(
    ranked: list[str] | tuple[str, ...],
    *,
    corpus_ids: set[str],
    synthetic_same_patient: set[str],
) -> tuple[list[str], list[str]]:
    """Drop unknown ids and synthetic same-patient links, preserving rank.

    The excluded ids are returned in the order they were encountered so a caller
    can see which longitudinal priors were removed before top-k.
    """
    kept: list[str] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for case_id in ranked:
        if case_id in seen or case_id not in corpus_ids:
            continue
        seen.add(case_id)
        if case_id in synthetic_same_patient:
            excluded.append(case_id)
            continue
        kept.append(case_id)
    return kept, excluded


def run_evaluate(
    *,
    out_dir: Path | None = None,
    encoder: str = "hf",
    database_url: str | None = None,
    encoders: TextEncoders | None = None,
) -> EvalResult:
    """Score held-out cases and write `report.md` and `report.json`."""
    if encoder not in {"hf", "mock"}:
        raise ValueError("encoder must be hf or mock")
    directory = out_dir if out_dir is not None else default_eval_dir()
    conn = connect(database_url)
    try:
        payload = _evaluate(conn, encoder=encoder, encoders=encoders)
    finally:
        conn.close()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    json_path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    lines = _summary_lines(payload, json_path, markdown_path)
    return EvalResult(
        held_out_count=int(payload["held_out_count"]),
        slide_corpus_count=int(payload["slide_corpus_count"]),
        winner=str(payload["scoring_comparison"]["winner"]),
        best_patch_precision_at_5=payload["scoring_comparison"]["best_patch_precision_at_5"],
        mean_top_3_precision_at_5=payload["scoring_comparison"]["mean_top_3_precision_at_5"],
        scoring_n=int(payload["scoring_comparison"]["n"]),
        demo_case_ids=tuple(str(item["case_id"]) for item in payload["demo_candidates"]),
        json_path=json_path,
        markdown_path=markdown_path,
        summary_lines=lines,
    )


def _evaluate(
    conn: Connection,
    *,
    encoder: str,
    encoders: TextEncoders | None,
) -> dict[str, Any]:
    with conn.transaction():
        held = _load_held_out(conn)
        slide_pool, report_pool = _load_corpus(conn)
    active = _resolve_encoders(
        encoder,
        encoders,
        needed=any(case.clinical_history for case in held),
    )
    slide_index = _index(slide_pool)
    report_index = _index(report_pool)
    case_rows: list[dict[str, Any]] = []
    for case in held:
        case_rows.append(
            _evaluate_case(
                conn,
                case,
                slide_index=slide_index,
                report_index=report_index,
                encoders=active,
            )
        )
    metrics = _headline_metrics(held, case_rows, slide_pool, report_pool)
    comparison = _comparison(metrics)
    ranked_cases = _with_demo_scores(case_rows)
    payload: dict[str, Any] = {
        "notice": NOTICE,
        "generated_at": datetime.now(UTC).isoformat(),
        "encoder": encoder,
        "held_out_count": len(held),
        "slide_corpus_count": len(slide_pool),
        "report_corpus_count": len(report_pool),
        "method": _method(),
        "metrics": metrics,
        "scoring_comparison": comparison,
        "demo_candidates": ranked_cases[:5],
        "cases": ranked_cases,
    }
    # Demo candidates are a short view of the same rows. Drop the bulky searches
    # from that list; the per-case section keeps the retrieved ids.
    payload["demo_candidates"] = [_demo_view(row) for row in ranked_cases[:5]]
    return payload


def _method() -> dict[str, Any]:
    return {
        "slide": (
            "Q3 via search_patches on every ready slide, fused by reciprocal rank. "
            "Synthetic same-patient links are removed before top-5 and top-10."
        ),
        "patch_scores": (
            "Nearest in-corpus patches to each query slide vector, pooled across the "
            "case's slides. best_patch is the max similarity. mean_top_3 is the mean "
            "of up to three. This is the F-05 case-score question."
        ),
        "reports": (
            "Q5 via search_reports (hybrid) on clinical_history when that field is "
            "non-empty. The text is read from Postgres and is not written to the report."
        ),
        "exclusion": (
            "A hit is dropped when patient.is_synthetic_linkage is true and the hit "
            "shares patient_id with the held-out case."
        ),
        "baseline": (
            "For each held-out case and relevance label, the expected precision and "
            "hit rate of a uniform draw from the eligible signed-out in_corpus pool. "
            "The headline baseline is the mean of those expectations. N is the number "
            "of held-out cases in the row."
        ),
        "demo_rank": (
            "clarity + 0.25 when the patient has a signed-out prior. clarity is the "
            "mean histology precision@5 of slide similarity and report search, "
            "omitting a search that did not run."
        ),
        "search_limit": SEARCH_LIMIT,
        "patch_candidate_limit": PATCH_CANDIDATE_LIMIT,
        "patches_in_mean": PATCHES_PER_CASE,
    }


def _resolve_encoders(
    encoder: str,
    encoders: TextEncoders | None,
    *,
    needed: bool,
) -> TextEncoders | None:
    if not needed:
        return None
    if encoders is not None:
        return encoders
    if encoder == "mock":
        return build_text_encoders(backend=MockTextEncoder())
    return build_text_encoders(get_settings())


def _load_held_out(conn: Connection) -> list[HeldOutCase]:
    rows = fetchall(conn, _HELD_OUT_SQL)
    case_ids = [str(row["id"]) for row in rows]
    slides = _load_slides(conn, case_ids)
    loaded: list[HeldOutCase] = []
    for row in rows:
        history = row["clinical_history"]
        case_id = str(row["id"])
        loaded.append(
            HeldOutCase(
                case_id=case_id,
                patient_id=str(row["patient_id"]),
                specialty=str(row["specialty"]),
                morphology=None if row["morphology"] is None else str(row["morphology"]),
                icd10=None if row["icd10"] is None else str(row["icd10"]),
                is_synthetic_linkage=bool(row["is_synthetic_linkage"]),
                clinical_history=None if history is None else str(history),
                signed_out_priors=int(row["signed_out_priors"]),
                slides=tuple(slides.get(case_id, ())),
            )
        )
    return loaded


def _load_slides(
    conn: Connection,
    case_ids: list[str],
) -> dict[str, list[tuple[str, object]]]:
    if not case_ids:
        return {}
    rows = fetchall(conn, _SLIDE_SQL, {"case_ids": case_ids})
    grouped: dict[str, list[tuple[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append((str(row["id"]), row["embedding"]))
    return grouped


def _load_corpus(conn: Connection) -> tuple[list[LabelledCase], list[LabelledCase]]:
    slide_pool: list[LabelledCase] = []
    report_pool: list[LabelledCase] = []
    for row in fetchall(conn, _CORPUS_SQL):
        case = LabelledCase(
            case_id=str(row["id"]),
            patient_id=str(row["patient_id"]),
            specialty=str(row["specialty"]),
            morphology=None if row["morphology"] is None else str(row["morphology"]),
            icd10=None if row["icd10"] is None else str(row["icd10"]),
            is_synthetic_linkage=bool(row["is_synthetic_linkage"]),
        )
        if row["in_slide_corpus"]:
            slide_pool.append(case)
        if row["in_report_corpus"]:
            report_pool.append(case)
    return slide_pool, report_pool


def _index(cases: list[LabelledCase]) -> dict[str, LabelledCase]:
    return {case.case_id: case for case in cases}


def _synthetic_ids(labels: dict[str, LabelledCase], patient_id: str) -> set[str]:
    return {
        case.case_id
        for case in labels.values()
        if case.is_synthetic_linkage and case.patient_id == patient_id
    }


def _evaluate_case(
    conn: Connection,
    case: HeldOutCase,
    *,
    slide_index: dict[str, LabelledCase],
    report_index: dict[str, LabelledCase],
    encoders: TextEncoders | None,
) -> dict[str, Any]:
    searches: dict[str, Any] = {
        "slide": None,
        "best_patch": None,
        "mean_top_3": None,
        "reports": None,
    }
    if case.slides:
        rankings = [
            _slide_ranking(conn, case.case_id, slide_id) for slide_id, _embedding in case.slides
        ]
        searches["slide"] = _pack(
            fuse_case_ranks(rankings),
            case,
            slide_index,
        )
        similarities = _patch_similarities(conn, case)
        scores = aggregate_patch_scores(similarities)
        searches["best_patch"] = _pack(
            _rank_scores({case_id: pair[0] for case_id, pair in scores.items()}),
            case,
            slide_index,
        )
        searches["mean_top_3"] = _pack(
            _rank_scores({case_id: pair[1] for case_id, pair in scores.items()}),
            case,
            slide_index,
        )
    if case.clinical_history is not None and encoders is not None:
        searches["reports"] = _pack(
            _report_ranking(conn, case, encoders),
            case,
            report_index,
        )
    return {
        "case_id": case.case_id,
        "patient_id": case.patient_id,
        "synthetic_linkage": case.is_synthetic_linkage,
        "signed_out_priors": case.signed_out_priors,
        "has_clinical_history": case.clinical_history is not None,
        "histology": case_value(case, "icd_o3_histology"),
        "icd10_category": case_value(case, "icd10_category"),
        "specialty": case_value(case, "specialty"),
        "searches": searches,
    }


def _pack(
    ranked: list[str],
    case: HeldOutCase,
    labels: dict[str, LabelledCase],
) -> dict[str, Any]:
    kept, excluded = select_hits(
        ranked,
        corpus_ids=set(labels),
        synthetic_same_patient=_synthetic_ids(labels, case.patient_id),
    )
    top10 = kept[:TOP_K]
    block: dict[str, Any] = {
        "top5": top10[:5],
        "top10": top10,
        "excluded_synthetic": excluded,
    }
    for name in _METRIC_NAMES:
        block[name] = {}
    for kind in RELEVANCE_KINDS:
        expected = case_value(case, kind)
        if expected is None:
            flags = None
        else:
            flags = [case_value(labels[case_id], kind) == expected for case_id in top10]
        block["precision_at_5"][kind] = None if flags is None else precision_at_k(flags, 5)
        block["hit_rate_at_5"][kind] = None if flags is None else hit_rate_at_k(flags, 5)
        block["precision_at_10"][kind] = None if flags is None else precision_at_k(flags, 10)
        block["hit_rate_at_10"][kind] = None if flags is None else hit_rate_at_k(flags, 10)
    return block


def _slide_ranking(conn: Connection, case_id: str, slide_id: str) -> list[str]:
    try:
        found = search_patches(
            conn,
            PatchSearchRequest(slide_id=slide_id, context_case_id=case_id, limit=SEARCH_LIMIT),
            _unused_encoders(),
        )
    except SearchError as exc:
        raise RuntimeError(exc.message) from exc
    if not isinstance(found, SearchResponse):
        raise RuntimeError("Slide similarity did not return cases.")
    return [hit.case.id for hit in found.hits]


def _report_ranking(conn: Connection, case: HeldOutCase, encoders: TextEncoders) -> list[str]:
    history = case.clinical_history
    if history is None:
        return []
    try:
        found = search_reports(
            conn,
            ReportSearchRequest(
                text=history,
                context_case_id=case.case_id,
                mode="hybrid",
                limit=SEARCH_LIMIT,
            ),
            encoders,
        )
    except SearchError as exc:
        raise RuntimeError(exc.message) from exc
    return [hit.case.id for hit in found.hits]


def _patch_similarities(conn: Connection, case: HeldOutCase) -> dict[str, list[float]]:
    rows: list[dict[str, Any]] = []
    with conn.transaction():
        configure_hnsw(conn)
        for _slide_id, embedding in case.slides:
            rows.extend(
                fetchall(
                    conn,
                    _PATCH_SQL,
                    {
                        "query": _halfvector(embedding),
                        "query_case_id": case.case_id,
                        "limit": PATCH_CANDIDATE_LIMIT,
                    },
                )
            )
    return _merge_patches(rows)


def _merge_patches(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    best: dict[int, tuple[str, float]] = {}
    for row in rows:
        similarity = float(row["similarity"])
        if not math.isfinite(similarity):
            similarity = -1.0
        patch_id = int(row["patch_id"])
        case_id = str(row["case_id"])
        current = best.get(patch_id)
        if current is None or similarity > current[1]:
            best[patch_id] = (case_id, similarity)
    grouped: dict[str, list[float]] = {}
    for case_id, similarity in best.values():
        grouped.setdefault(case_id, []).append(similarity)
    return grouped


def _halfvector(value: object) -> HalfVector:
    if isinstance(value, HalfVector):
        return value
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
    return HalfVector([float(item) for item in raw])


def _rank_scores(scores: dict[str, float]) -> list[str]:
    return sorted(scores, key=lambda case_id: (-scores[case_id], case_id))


def _unused_encoders() -> TextEncoders:
    """Q3 reads a stored slide vector. The text encoder is not called."""
    return build_text_encoders(backend=MockTextEncoder())


def _headline_metrics(
    held: list[HeldOutCase],
    case_rows: list[dict[str, Any]],
    slide_pool: list[LabelledCase],
    report_pool: list[LabelledCase],
) -> list[dict[str, Any]]:
    rows_by_id = {str(row["case_id"]): row for row in case_rows}
    metrics: list[dict[str, Any]] = []
    for search_type in SEARCH_TYPES:
        pool = report_pool if search_type == "reports" else slide_pool
        for kind in RELEVANCE_KINDS:
            used: list[HeldOutCase] = []
            collected: dict[str, list[float]] = {name: [] for name in _METRIC_NAMES}
            for case in held:
                block = rows_by_id[case.case_id]["searches"][search_type]
                if block is None:
                    continue
                if block["precision_at_5"][kind] is None:
                    continue
                used.append(case)
                for name in _METRIC_NAMES:
                    collected[name].append(float(block[name][kind]))
            n = len(used)
            baselines = {
                5: _baseline(used, pool, kind, 5) if n else None,
                10: _baseline(used, pool, kind, 10) if n else None,
            }
            metrics.append(
                {
                    "search_type": search_type,
                    "relevance": kind,
                    "n": n,
                    "precision_at_5": _mean(collected["precision_at_5"]),
                    "hit_rate_at_5": _mean(collected["hit_rate_at_5"]),
                    "precision_at_10": _mean(collected["precision_at_10"]),
                    "hit_rate_at_10": _mean(collected["hit_rate_at_10"]),
                    "baseline_precision_at_5": None if n == 0 else baselines[5][0],
                    "baseline_hit_rate_at_5": None if n == 0 else baselines[5][1],
                    "baseline_precision_at_10": None if n == 0 else baselines[10][0],
                    "baseline_hit_rate_at_10": None if n == 0 else baselines[10][1],
                }
            )
    return metrics


def _baseline(
    queries: list[HeldOutCase],
    pool: list[LabelledCase],
    kind: str,
    k: int,
) -> tuple[float, float]:
    precision = 0.0
    hit_rate = 0.0
    for query in queries:
        label = case_value(query, kind)
        eligible = [
            case
            for case in pool
            if not (case.is_synthetic_linkage and case.patient_id == query.patient_id)
        ]
        relevant = sum(1 for case in eligible if case_value(case, kind) == label)
        precision += expected_precision_at_k(relevant, len(eligible), k)
        hit_rate += expected_hit_rate_at_k(relevant, len(eligible), k)
    size = len(queries)
    return precision / size, hit_rate / size


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _comparison(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    best = _find_metric(metrics, "best_patch", "icd_o3_histology")
    mean = _find_metric(metrics, "mean_top_3", "icd_o3_histology")
    best_p5 = None if best is None else best["precision_at_5"]
    mean_p5 = None if mean is None else mean["precision_at_5"]
    n = 0 if best is None else int(best["n"])
    if best_p5 is None or mean_p5 is None:
        winner = "tie"
    elif best_p5 > mean_p5 + 1e-12:
        winner = "best_patch"
    elif mean_p5 > best_p5 + 1e-12:
        winner = "mean_top_3"
    else:
        winner = "tie"
    return {
        "question": (
            "Whether a case score should be its best patch similarity or the mean "
            "of its top three (F-05)."
        ),
        "criterion": "mean precision@5 on the 4-digit ICD-O-3 histology code",
        "winner": winner,
        "n": n,
        "best_patch_precision_at_5": best_p5,
        "mean_top_3_precision_at_5": mean_p5,
    }


def _find_metric(
    metrics: list[dict[str, Any]],
    search_type: str,
    kind: str,
) -> dict[str, Any] | None:
    for metric in metrics:
        if metric["search_type"] == search_type and metric["relevance"] == kind:
            return metric
    return None


def _with_demo_scores(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in case_rows:
        parts: list[float] = []
        for search_type in ("slide", "reports"):
            block = row["searches"][search_type]
            if block is None:
                continue
            value = block["precision_at_5"]["icd_o3_histology"]
            if value is not None:
                parts.append(float(value))
        clarity = retrieval_clarity(parts)
        rank_score = demo_rank_score(clarity, int(row["signed_out_priors"]))
        updated = dict(row)
        updated["clarity"] = clarity
        updated["rank_score"] = rank_score
        scored.append(updated)
    scored.sort(key=lambda row: (-float(row["rank_score"]), -float(row["clarity"]), row["case_id"]))
    return scored


def _demo_view(row: dict[str, Any]) -> dict[str, Any]:
    slide = row["searches"]["slide"]
    reports = row["searches"]["reports"]
    return {
        "case_id": row["case_id"],
        "rank_score": row["rank_score"],
        "clarity": row["clarity"],
        "signed_out_priors": row["signed_out_priors"],
        "synthetic_linkage": row["synthetic_linkage"],
        "histology": row["histology"],
        "icd10_category": row["icd10_category"],
        "specialty": row["specialty"],
        "slide_top5": [] if slide is None else list(slide["top5"]),
        "report_top5": [] if reports is None else list(reports["top5"]),
    }


def _summary_lines(
    payload: dict[str, Any],
    json_path: Path,
    markdown_path: Path,
) -> tuple[str, ...]:
    lines = [
        "Retrieval evaluation. Research prototype, not clinical diagnostic accuracy.",
        f"held_out {payload['held_out_count']}",
        f"slide_corpus {payload['slide_corpus_count']}",
    ]
    for metric in payload["metrics"]:
        if metric["relevance"] != "icd_o3_histology":
            continue
        lines.append(
            f"{metric['search_type']} histology "
            f"P@5 {_fmt(metric['precision_at_5'])} "
            f"HR@5 {_fmt(metric['hit_rate_at_5'])} "
            f"P@10 {_fmt(metric['precision_at_10'])} "
            f"HR@10 {_fmt(metric['hit_rate_at_10'])} "
            f"n={metric['n']} "
            f"baseline_P@5 {_fmt(metric['baseline_precision_at_5'])} "
            f"baseline_HR@5 {_fmt(metric['baseline_hit_rate_at_5'])}"
        )
    comparison = payload["scoring_comparison"]
    lines.append(
        f"scoring {comparison['winner']} "
        f"best_patch_P@5 {_fmt(comparison['best_patch_precision_at_5'])} "
        f"mean_top_3_P@5 {_fmt(comparison['mean_top_3_precision_at_5'])} "
        f"n={comparison['n']}"
    )
    demo_ids = [str(item["case_id"]) for item in payload["demo_candidates"]]
    if demo_ids:
        lines.append("demo " + ", ".join(demo_ids))
    lines.append(f"wrote {json_path}")
    lines.append(f"wrote {markdown_path}")
    return tuple(lines)


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        payload["notice"],
        "",
        f"Encoder: `{payload['encoder']}`. "
        f"Held-out open cases: **{payload['held_out_count']}**. "
        f"Signed-out slide corpus (`in_corpus` patches): **{payload['slide_corpus_count']}**. "
        f"Signed-out report corpus (`in_corpus` chunks): **{payload['report_corpus_count']}**.",
        "",
        "Synthetic longitudinal links (`patient.is_synthetic_linkage` and the same "
        "patient) are removed before top-5 and top-10 so that pairing does not "
        "inflate corpus retrieval. N beside each number is the count of held-out "
        "cases in that row. Primary relevance is the 4-digit ICD-O-3 histology "
        "code. ICD-10 category and specialty are secondary, because one organ "
        "often shares a site code across histologies.",
        "",
        "## Headline",
        "",
        _metric_table(payload["metrics"]),
        "",
        "## Case scoring: best patch vs mean of top 3",
        "",
        _comparison_prose(payload["scoring_comparison"]),
        "",
        _comparison_table(payload["metrics"]),
        "",
        "## Demo candidates",
        "",
        "Up to five open cases, best first. Rank is retrieval clarity plus a bonus "
        "when a signed-out prior is on the same patient. A synthetic link is labelled "
        "as synthetic. These are cases where retrieved precedent is easiest to show, "
        "not cases with a recommended diagnosis.",
        "",
        _demo_lines(payload["demo_candidates"]),
        "",
        "## Per-case results",
        "",
        "Sorted best first. Retrieved ids are corpus cases after synthetic same-patient "
        "links were removed.",
        "",
    ]
    if not payload["cases"]:
        lines.append("No held-out open cases were in the database.")
        lines.append("")
    for row in payload["cases"]:
        lines.extend(_case_lines(row))
    return "\n".join(lines)


def _metric_table(metrics: list[dict[str, Any]]) -> str:
    header = (
        "| Search | Relevance | N | P@5 | HR@5 | P@10 | HR@10 "
        "| Baseline P@5 | Baseline HR@5 | Baseline P@10 | Baseline HR@10 |"
    )
    rule = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    body = [_metric_row(metric) for metric in metrics]
    return "\n".join([header, rule, *body])


def _metric_row(metric: dict[str, Any]) -> str:
    cells = [
        str(metric["search_type"]),
        str(metric["relevance"]),
        str(metric["n"]),
        _fmt(metric["precision_at_5"]),
        _fmt(metric["hit_rate_at_5"]),
        _fmt(metric["precision_at_10"]),
        _fmt(metric["hit_rate_at_10"]),
        _fmt(metric["baseline_precision_at_5"]),
        _fmt(metric["baseline_hit_rate_at_5"]),
        _fmt(metric["baseline_precision_at_10"]),
        _fmt(metric["baseline_hit_rate_at_10"]),
    ]
    return "| " + " | ".join(cells) + " |"


def _comparison_prose(comparison: dict[str, Any]) -> str:
    n = comparison["n"]
    best = _fmt(comparison["best_patch_precision_at_5"])
    mean = _fmt(comparison["mean_top_3_precision_at_5"])
    winner = comparison["winner"]
    if n == 0:
        return (
            "F-05 asks whether a case score should be its best patch or the mean of "
            "its top three. This run had no held-out slide to compare (N=0)."
        )
    if winner == "tie":
        decision = f"The two strategies tie on that number ({best}, N={n})."
    else:
        decision = (
            f"On this cohort, `{winner}` is higher "
            f"(best_patch {best} vs mean_top_3 {mean}, N={n})."
        )
    return (
        "F-05 asks whether a case score should be its best patch or the mean of its "
        "top three. The comparison uses 4-digit ICD-O-3 precision@5. " + decision
    )


def _comparison_table(metrics: list[dict[str, Any]]) -> str:
    header = "| Strategy | N | Histology P@5 | Histology HR@5 | Histology P@10 | Histology HR@10 |"
    rule = "| --- | ---: | ---: | ---: | ---: | ---: |"
    rows = []
    for search_type in ("best_patch", "mean_top_3"):
        metric = _find_metric(metrics, search_type, "icd_o3_histology")
        if metric is None:
            continue
        rows.append(
            f"| {search_type} | {metric['n']} | {_fmt(metric['precision_at_5'])} "
            f"| {_fmt(metric['hit_rate_at_5'])} | {_fmt(metric['precision_at_10'])} "
            f"| {_fmt(metric['hit_rate_at_10'])} |"
        )
    return "\n".join([header, rule, *rows])


def _demo_lines(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No held-out case was available."
    lines = []
    for index, row in enumerate(candidates, start=1):
        linkage = "synthetic linkage" if row["synthetic_linkage"] else "not a synthetic link"
        priors = int(row["signed_out_priors"])
        prior_text = f"{priors} signed-out prior" + ("" if priors == 1 else "s")
        lines.append(
            f"{index}. `{row['case_id']}` — rank {_fmt(row['rank_score'])}, "
            f"clarity {_fmt(row['clarity'])}, histology `{row['histology']}`, "
            f"{prior_text} ({linkage}). "
            f"Slide top-5: {_id_list(row['slide_top5'])}."
        )
    return "\n".join(lines)


def _case_lines(row: dict[str, Any]) -> list[str]:
    linkage = "synthetic linkage" if row["synthetic_linkage"] else "not a synthetic link"
    lines = [
        f"### `{row['case_id']}`",
        "",
        f"Rank {_fmt(row['rank_score'])}, clarity {_fmt(row['clarity'])}. "
        f"Histology `{row['histology']}`, ICD-10 `{row['icd10_category']}`, "
        f"specialty `{row['specialty']}`. "
        f"Signed-out priors: {row['signed_out_priors']} ({linkage}). "
        f"Clinical history used for report search: "
        f"{'yes' if row['has_clinical_history'] else 'no'}.",
        "",
    ]
    labels = {
        "slide": "Slide similarity (Q3)",
        "best_patch": "Best patch",
        "mean_top_3": "Mean of top 3",
        "reports": "Report search (Q5)",
    }
    for search_type in SEARCH_TYPES:
        block = row["searches"][search_type]
        title = labels[search_type]
        if block is None:
            lines.append(f"- {title}: not run.")
            continue
        lines.append(
            f"- {title}: top-5 {_id_list(block['top5'])}; "
            f"top-10 {_id_list(block['top10'])}; "
            f"excluded synthetic {_id_list(block['excluded_synthetic'])}. "
            f"Histology P@5 {_fmt(block['precision_at_5']['icd_o3_histology'])}, "
            f"HR@5 {_fmt(block['hit_rate_at_5']['icd_o3_histology'])}, "
            f"P@10 {_fmt(block['precision_at_10']['icd_o3_histology'])}, "
            f"HR@10 {_fmt(block['hit_rate_at_10']['icd_o3_histology'])}. "
            f"ICD-10 P@5 {_fmt(block['precision_at_5']['icd10_category'])}. "
            f"Specialty P@5 {_fmt(block['precision_at_5']['specialty'])}."
        )
    lines.append("")
    return lines


def _id_list(case_ids: list[str]) -> str:
    if not case_ids:
        return "(none)"
    return ", ".join(f"`{case_id}`" for case_id in case_ids)


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.3f}"
