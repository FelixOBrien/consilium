"""Eight consult tools. Thin wrappers over search and SQL.

Precedent tools never return the thread case, an open case, or a withheld
report. Passages are cut to 400 characters and thumbnails are dropped.
`rank_pathologists` does not count in Python: it returns the SQL aggregation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from psycopg import Connection
from pydantic import ValidationError

from consilium.agent.postcheck import AllowedCase, Allowlist  # pragma: allowlist secret
from consilium.api.schemas.common import Region  # pragma: allowlist secret
from consilium.api.schemas.report import Report  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    CaseHit,
    Passage,
    PatchSearchRequest,
    ReportSearchRequest,
    SearchFilters,
    SearchResponse,
)
from consilium.db.cases import get_case, get_report  # pragma: allowlist secret
from consilium.db.consult import (  # pragma: allowlist secret
    author_ref,
    precedent_cases,
    rank_pathologists_sql,
)
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.search import SearchError, search_patches, search_reports  # pragma: allowlist secret
from consilium.search.common import fetchall, fetchone  # pragma: allowlist secret

PASSAGE_LIMIT = 400
HIT_LIMIT = 8
_REPORT_BODY_LIMIT = 6000

_HISTORY_SQL = """
SELECT
    c.id,
    c.patient_id,
    c.status,
    c.specimen_label,
    c.specialty,
    c.accessioned_at,
    CASE WHEN c.status = 'signed_out' THEN c.icd10 ELSE NULL END AS icd10,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN r.signed_at
        ELSE NULL
    END AS signed_at,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN r.conclusion
        ELSE NULL
    END AS conclusion,
    CASE
        WHEN c.status = 'open' THEN r.clinical_history
        ELSE NULL
    END AS open_clinical_history,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN auth.id
        ELSE NULL
    END AS author_id,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN auth.name
        ELSE NULL
    END AS author_name,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN auth.primary_specialty
        ELSE NULL
    END AS author_specialty,
    CASE
        WHEN c.status = 'signed_out' AND r.status = 'signed' THEN auth.is_synthetic
        ELSE NULL
    END AS author_synthetic
FROM path_case c
LEFT JOIN report r ON r.case_id = c.id
LEFT JOIN pathologist auth ON auth.id = r.author_id
WHERE c.patient_id = %(patient_id)s
  AND c.id <> %(thread_case_id)s
ORDER BY c.accessioned_at ASC, c.id ASC
"""

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_case_context",
        "description": (
            "Describe the case under discussion: patient (including case_count), "
            "specialty, age, sex, specimen, clinical history and slides. "
            "The report is included only when this case is itself signed out. "
            "This case is never precedent and must not be cited."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_patient_history",
        "description": (
            "Chronological other cases for a patient (oldest first). "
            "Signed-out cases include the conclusion excerpt and the synthetic "
            "reporting pathologist and may be cited (same_patient true when it is "
            "this patient). Open cases return metadata and clinical_history only "
            "and are not precedent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {
                    "type": "string",
                    "description": "Defaults to the open case's patient.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_patient_cases",
        "description": (
            "Search signed-out in-corpus cases of one patient. "
            "mode 'reports' needs text. mode 'patches' needs text or a slide_id/region."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["reports", "patches"]},
                "text": {"type": "string"},
                "patient_id": {"type": "string"},
                "slide_id": {"type": "string"},
                "region": {"type": "object"},
                "filters": {"type": "object"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_similar_cases_by_morphology",
        "description": (
            "Tissue similarity (Q2 region or Q3 slide) against signed-out cases "
            "other than the open case. Omit slide_id and region to use the open "
            "case's primary slide."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string"},
                "region": {"type": "object"},
                "filters": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_patches_by_text",
        "description": "Cases whose patches match a morphology description (Q4).",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "filters": {"type": "object"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_reports",
        "description": "Signed-out cases whose reports match the text (Q5), with a passage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "filters": {"type": "object"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_report",
        "description": (
            "Full signed-out report and its synthetic author. "
            "Refuses the open case, an open case, and a withheld report."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "rank_pathologists",
        "description": (
            "SQL aggregation over the given case ids. Returns each synthetic author, "
            "specialty, case_count (the length of case_ids), the case ids, and "
            "reported_same_patient when they reported an earlier case of this patient. "
            "Open, held-out and the thread case are ignored. Use this for every count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["case_ids"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class ToolContext:
    conn: Connection
    encoders: TextEncoders
    thread_case_id: str
    patient_id: str
    allowlist: Allowlist


@dataclass
class ToolOutcome:
    summary: str
    payload: dict[str, Any]
    result_count: int


def execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> ToolOutcome:
    try:
        if name == "get_case_context":
            return _case_context(ctx)
        if name == "get_patient_history":
            return _patient_history(ctx, arguments)
        if name == "search_patient_cases":
            return _search_patient(ctx, arguments)
        if name == "search_similar_cases_by_morphology":
            return _search_morphology(ctx, arguments)
        if name == "search_patches_by_text":
            return _search_patches_text(ctx, arguments)
        if name == "search_reports":
            return _search_reports(ctx, arguments)
        if name == "get_report":
            return _read_report(ctx, arguments)
        if name == "rank_pathologists":
            return _rank(ctx, arguments)
    except SearchError as exc:
        return ToolOutcome(exc.message, {"error": exc.code, "message": exc.message}, 0)
    except HTTPException as exc:
        return ToolOutcome("Tool failed.", {"error": "tool_failed", "status": exc.status_code}, 0)
    except ValidationError:
        return ToolOutcome("Tool input was not valid.", {"error": "validation_error"}, 0)
    return ToolOutcome("Unknown tool.", {"error": "unknown_tool", "tool": name}, 0)


def outcome_json(outcome: ToolOutcome) -> str:
    return json.dumps(outcome.payload, separators=(",", ":"), default=_json_default)


def _case_context(ctx: ToolContext) -> ToolOutcome:
    """The open case. Never added to the citation allowlist."""
    detail = get_case(ctx.conn, ctx.thread_case_id)
    history = fetchone(
        ctx.conn,
        "SELECT clinical_history FROM report WHERE case_id = %s",
        (ctx.thread_case_id,),
    )
    clinical = None if history is None else history["clinical_history"]
    payload: dict[str, Any] = {
        "precedent": False,
        "citable": False,
        "case_id": detail.id,
        "patient": detail.patient.model_dump(mode="json"),
        "specialty": detail.specialty.value,
        "patient_age": detail.patient_age,
        "patient_sex": None if detail.patient_sex is None else detail.patient_sex.value,
        "specimen_label": detail.specimen_label,
        "status": detail.status.value,
        "clinical_history": clinical,
        "slides": [
            {
                "id": slide.id,
                "ordinal": slide.ordinal,
                "stain": slide.stain,
                "magnification": slide.magnification,
                "status": slide.status.value,
            }
            for slide in detail.slides
        ],
        "report": None,
    }
    if detail.status.value == "signed_out" and detail.report_status == "signed":
        report = get_report(ctx.conn, ctx.thread_case_id)
        if isinstance(report, Report):
            payload["report"] = _report_payload(report)
    return ToolOutcome(
        "Loaded the open case. It is not precedent.",
        payload,
        0,
    )


def _patient_history(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    requested = arguments.get("patient_id")
    patient_id = ctx.patient_id
    if isinstance(requested, str) and requested.strip():
        patient_id = requested.strip()
    exists = fetchone(ctx.conn, "SELECT id FROM patient WHERE id = %s", (patient_id,))
    if exists is None:
        return ToolOutcome(
            "Patient not found.",
            {"error": "not_found", "patient_id": patient_id},
            0,
        )
    rows = fetchall(
        ctx.conn,
        _HISTORY_SQL,
        {"patient_id": patient_id, "thread_case_id": ctx.thread_case_id},
    )
    cases: list[dict[str, Any]] = []
    signed = 0
    for row in rows:
        same = str(row["patient_id"]) == ctx.patient_id
        if str(row["status"]) == "signed_out":
            signed += 1
            excerpt = _clip(row["conclusion"])
            author = author_ref(row)
            entry = {
                "case_id": str(row["id"]),
                "status": "signed_out",
                "citable": True,
                "same_patient": same,
                "specimen_label": row["specimen_label"],
                "specialty": row["specialty"],
                "accessioned_at": row["accessioned_at"],
                "signed_at": row["signed_at"],
                "icd10": row["icd10"],
                "conclusion_line": _first_line(row["conclusion"]),
                "report_excerpt": excerpt,
                "pathologist": None
                if author is None
                else {
                    "id": author.id,
                    "name": author.name,
                    "specialty": author.primary_specialty.value,
                    "is_synthetic": True,
                },
            }
            ctx.allowlist.add(
                AllowedCase(
                    case_id=str(row["id"]),
                    patient_id=str(row["patient_id"]),
                    same_patient=same,
                    quote=excerpt,
                )
            )
            cases.append(entry)
            continue
        cases.append(
            {
                "case_id": str(row["id"]),
                "status": "open",
                "citable": False,
                "same_patient": same,
                "specimen_label": row["specimen_label"],
                "specialty": row["specialty"],
                "accessioned_at": row["accessioned_at"],
                "clinical_history": row["open_clinical_history"],
            }
        )
    summary = f"Found {len(cases)} other cases, {signed} signed out."
    return ToolOutcome(
        summary,
        {"patient_id": patient_id, "case_count": len(cases), "cases": cases},
        signed,
    )


def _search_patient(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    mode = arguments.get("mode")
    if mode not in {"reports", "patches"}:
        return ToolOutcome("mode must be reports or patches.", {"error": "validation_error"}, 0)
    requested = arguments.get("patient_id")
    patient_id = (
        requested.strip() if isinstance(requested, str) and requested.strip() else ctx.patient_id
    )
    filters = _filters(arguments.get("filters"), patient_id=patient_id)
    if mode == "reports":
        text = arguments.get("text")
        if not isinstance(text, str) or not text.strip():
            return ToolOutcome("reports search needs text.", {"error": "validation_error"}, 0)
        response = search_reports(
            ctx.conn,
            ReportSearchRequest(
                text=text.strip(),
                context_case_id=ctx.thread_case_id,
                filters=filters,
                limit=HIT_LIMIT,
            ),
            ctx.encoders,
        )
        return _from_search(ctx, response)
    region = _region(arguments.get("region"))
    slide_id = arguments.get("slide_id") if isinstance(arguments.get("slide_id"), str) else None
    text = arguments.get("text") if isinstance(arguments.get("text"), str) else None
    request = _patch_request(
        ctx,
        text=text,
        slide_id=slide_id,
        region=region,
        filters=filters,
    )
    if isinstance(request, ToolOutcome):
        return request
    found = search_patches(ctx.conn, request, ctx.encoders)
    if not isinstance(found, SearchResponse):
        return ToolOutcome("Patch search did not return cases.", {"error": "tool_failed"}, 0)
    return _from_search(ctx, found)


def _search_morphology(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    region = _region(arguments.get("region"))
    slide_id = arguments.get("slide_id") if isinstance(arguments.get("slide_id"), str) else None
    if region is None and slide_id is None:
        slide_id = _primary_slide(ctx)
        if slide_id is None:
            return ToolOutcome(
                "This case has no ready slide.",
                {"query_kind": "slide", "hit_count": 0, "hits": [], "notice": "No ready slide."},
                0,
            )
    found = search_patches(
        ctx.conn,
        _must_patch(
            ctx,
            text=None,
            slide_id=None if region is not None else slide_id,
            region=region,
            filters=_filters(arguments.get("filters")),
        ),
        ctx.encoders,
    )
    if not isinstance(found, SearchResponse):
        return ToolOutcome("Morphology search did not return cases.", {"error": "tool_failed"}, 0)
    return _from_search(ctx, found)


def _search_patches_text(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        return ToolOutcome("text is required.", {"error": "validation_error"}, 0)
    filters = _filters(arguments.get("filters"))
    found = search_patches(
        ctx.conn,
        _must_patch(ctx, text=text.strip(), slide_id=None, region=None, filters=filters),
        ctx.encoders,
    )
    if not isinstance(found, SearchResponse):
        return ToolOutcome("Text search did not return cases.", {"error": "tool_failed"}, 0)
    return _from_search(ctx, found)


def _search_reports(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    text = arguments.get("text")
    if not isinstance(text, str) or not text.strip():
        return ToolOutcome("text is required.", {"error": "validation_error"}, 0)
    response = search_reports(
        ctx.conn,
        ReportSearchRequest(
            text=text.strip(),
            context_case_id=ctx.thread_case_id,
            filters=_filters(arguments.get("filters")),
            limit=HIT_LIMIT,
        ),
        ctx.encoders,
    )
    return _from_search(ctx, response)


def _read_report(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    case_id = arguments.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        return ToolOutcome("case_id is required.", {"error": "validation_error"}, 0)
    case_id = case_id.strip()
    if case_id == ctx.thread_case_id:
        return ToolOutcome(
            "Refused: the open case is not precedent.",
            {"error": "not_precedent", "reason": "The open case is not precedent."},
            0,
        )
    rows = precedent_cases(ctx.conn, case_ids=[case_id], thread_case_id=ctx.thread_case_id)
    if not rows:
        return ToolOutcome(
            "Refused: not signed-out precedent.",
            {
                "error": "not_precedent",
                "reason": "Only a signed-out report from another case can be read.",
            },
            0,
        )
    report = get_report(ctx.conn, case_id)
    if not isinstance(report, Report):
        return ToolOutcome(
            "Refused: not signed-out precedent.",
            {"error": "not_precedent", "reason": "Report is not signed."},
            0,
        )
    payload = _report_payload(report)
    quote = _clip(report.conclusion) or _clip(report.body)
    ctx.allowlist.add(
        AllowedCase(
            case_id=case_id,
            patient_id=str(rows[0]["patient_id"]),
            same_patient=str(rows[0]["patient_id"]) == ctx.patient_id,
            quote=quote,
        )
    )
    payload["same_patient"] = str(rows[0]["patient_id"]) == ctx.patient_id
    payload["is_synthetic_author"] = True
    return ToolOutcome("Loaded one signed-out report.", payload, 1)


def _rank(ctx: ToolContext, arguments: dict[str, Any]) -> ToolOutcome:
    raw_ids = arguments.get("case_ids")
    if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
        return ToolOutcome("case_ids must be a list of strings.", {"error": "validation_error"}, 0)
    ranked = rank_pathologists_sql(
        ctx.conn,
        case_ids=[item.strip() for item in raw_ids if item.strip()],
        thread_case_id=ctx.thread_case_id,
        patient_id=ctx.patient_id,
    )
    returned: list[str] = []
    payload_rows: list[dict[str, Any]] = []
    for item in ranked:
        rank = item["rank"]
        returned.extend(rank.case_ids)
        payload_rows.append(
            {
                **rank.model_dump(mode="json"),
                "is_synthetic": True,
                "reported_same_patient": item["reported_same_patient"],
            }
        )
    for row in precedent_cases(ctx.conn, case_ids=returned, thread_case_id=ctx.thread_case_id):
        ctx.allowlist.add(
            AllowedCase(
                case_id=str(row["id"]),
                patient_id=str(row["patient_id"]),
                same_patient=str(row["patient_id"]) == ctx.patient_id,
            )
        )
    same = sum(1 for item in ranked if item["reported_same_patient"])
    summary = f"Ranked {len(ranked)} pathologists from SQL."
    if same:
        summary = f"{summary} {same} also reported an earlier case of this patient."
    return ToolOutcome(summary, {"ranking": payload_rows}, len(ranked))


def _from_search(ctx: ToolContext, response: SearchResponse) -> ToolOutcome:
    hits: list[dict[str, Any]] = []
    for hit in response.hits:
        if hit.case.id == ctx.thread_case_id or hit.case.status.value != "signed_out":
            continue
        _remember_hit(ctx, hit)
        hits.append(_trim_hit(hit))
        if len(hits) >= HIT_LIMIT:
            break
    notice = response.notice
    if len(response.hits) > len(hits):
        extra = "Some hits were withheld because they are not signed-out precedent."
        notice = f"{notice} {extra}".strip() if notice else extra
    summary = f"Found {len(hits)} signed-out cases."
    return ToolOutcome(
        summary,
        {
            "query_kind": response.query_kind,
            "hit_count": len(hits),
            "total_candidates": response.total_candidates,
            "notice": notice,
            "hits": hits,
        },
        len(hits),
    )


def _remember_hit(ctx: ToolContext, hit: CaseHit) -> None:
    patch = hit.patches[0] if hit.patches else None
    quote = None
    if hit.passage is not None and hit.passage.text:
        quote = hit.passage.text[:PASSAGE_LIMIT]
    elif hit.case.conclusion_line:
        quote = hit.case.conclusion_line[:PASSAGE_LIMIT]
    ctx.allowlist.add(
        AllowedCase(
            case_id=hit.case.id,
            patient_id=hit.case.patient.id,
            same_patient=hit.case.patient.id == ctx.patient_id,
            slide_id=None if patch is None else patch.slide_id,
            patch_id=None if patch is None else patch.patch_id,
            quote=quote,
        )
    )


def _trim_hit(hit: CaseHit) -> dict[str, Any]:
    return {
        "case_id": hit.case.id,
        "same_patient": hit.same_patient,
        "score": hit.score,
        "matched_by": list(hit.matched_by),
        "specialty": hit.case.specialty.value,
        "specimen_label": hit.case.specimen_label,
        "icd10": hit.case.icd10,
        "conclusion_line": _clip(hit.case.conclusion_line),
        "author": {
            "id": hit.author.id,
            "name": hit.author.name,
            "specialty": hit.author.primary_specialty.value,
            "is_synthetic": True,
        },
        "patches": [
            {
                "patch_id": patch.patch_id,
                "slide_id": patch.slide_id,
                "x": patch.x,
                "y": patch.y,
                "size": patch.size,
                "similarity": patch.similarity,
            }
            for patch in hit.patches
        ],
        "passage": _trim_passage(hit.passage),
    }


def _trim_passage(passage: Passage | None) -> dict[str, Any] | None:
    if passage is None:
        return None
    text = passage.text[:PASSAGE_LIMIT]
    highlights = [
        [start, min(end, len(text))]
        for start, end in passage.highlights
        if start < len(text) and min(end, len(text)) > start
    ]
    return {"section": passage.section.value, "text": text, "highlights": highlights}


def _report_payload(report: Report) -> dict[str, Any]:
    body = report.body
    truncated = len(body) > _REPORT_BODY_LIMIT
    return {
        "case_id": report.case_id,
        "status": report.status,
        "clinical_history": report.clinical_history,
        "gross_description": report.gross_description,
        "microscopic_description": report.microscopic_description,
        "conclusion": report.conclusion,
        "additional_info": report.additional_info,
        "icd10": report.icd10,
        "signed_at": report.signed_at,
        "body": body[:_REPORT_BODY_LIMIT],
        "body_truncated": truncated,
        "author": {
            "id": report.author.id,
            "name": report.author.name,
            "specialty": report.author.primary_specialty.value,
            "is_synthetic": True,
        },
    }


def _filters(raw: object, *, patient_id: str | None = None) -> SearchFilters | None:
    data = dict(raw) if isinstance(raw, dict) else {}
    data.pop("status", None)
    if patient_id is not None:
        data["patient_id"] = patient_id
    if not data:
        return None
    return SearchFilters.model_validate(data)


def _region(raw: object) -> Region | None:
    if not isinstance(raw, dict):
        return None
    return Region.model_validate(raw)


def _patch_request(
    ctx: ToolContext,
    *,
    text: str | None,
    slide_id: str | None,
    region: Region | None,
    filters: SearchFilters | None,
) -> PatchSearchRequest | ToolOutcome:
    chosen = [value for value in (text, slide_id, region) if value]
    if len(chosen) != 1:
        return ToolOutcome(
            "Provide one of text, slide_id or region.",
            {"error": "validation_error"},
            0,
        )
    return _must_patch(ctx, text=text, slide_id=slide_id, region=region, filters=filters)


def _must_patch(
    ctx: ToolContext,
    *,
    text: str | None,
    slide_id: str | None,
    region: Region | None,
    filters: SearchFilters | None,
) -> PatchSearchRequest:
    return PatchSearchRequest(
        text=text,
        slide_id=slide_id,
        region=region,
        context_case_id=ctx.thread_case_id,
        filters=filters,
        limit=HIT_LIMIT,
    )


def _primary_slide(ctx: ToolContext) -> str | None:
    row = fetchone(
        ctx.conn,
        """
        SELECT id
        FROM slide
        WHERE case_id = %s AND status = 'ready'
        ORDER BY ordinal ASC, id ASC
        LIMIT 1
        """,
        (ctx.thread_case_id,),
    )
    if row is None:
        return None
    return str(row["id"])


def _clip(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:PASSAGE_LIMIT]


def _first_line(value: object) -> str | None:
    text = _clip(value)
    if text is None:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:PASSAGE_LIMIT]
    return None


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot encode {type(value).__name__}")
