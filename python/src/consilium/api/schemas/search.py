from __future__ import annotations

from typing import Literal

from pydantic import Field

from consilium.api.schemas.case import CaseSummary  # pragma: allowlist secret
from consilium.api.schemas.common import (  # pragma: allowlist secret
    APIModel,
    CaseStatus,
    Region,
    ReportSection,
    Specialty,
)
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret


class SearchFilters(APIModel):
    patient_id: str | None = None
    specialty: list[Specialty] | None = None
    icd10_prefix: str | None = None
    stain: str | None = None
    status: CaseStatus | None = None


class PatchSearchRequest(APIModel):
    """One of patch_id, region, slide_id or text."""

    patch_id: int | None = Field(default=None, ge=1)
    region: Region | None = None
    slide_id: str | None = None
    text: str | None = None
    context_case_id: str | None = None
    scope: Literal["corpus", "slide"] = "corpus"
    filters: SearchFilters | None = None
    limit: int = Field(default=20, ge=1, le=50)


class ReportSearchRequest(APIModel):
    text: str = Field(min_length=1)
    mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    context_case_id: str | None = None
    filters: SearchFilters | None = None
    limit: int = Field(default=20, ge=1, le=50)


class PatchHit(APIModel):
    patch_id: int
    slide_id: str
    x: int
    y: int
    size: int = Field(gt=0)
    similarity: float = Field(ge=-1, le=1)
    thumbnail_url: str


class Passage(APIModel):
    section: ReportSection
    text: str
    highlights: list[tuple[int, int]]


class CaseHit(APIModel):
    case: CaseSummary
    author: PathologistRef
    same_patient: bool
    score: float = Field(
        ge=0,
        le=1,
        description="Relative score within this response. Not a probability or a diagnosis.",
    )
    matched_by: list[Literal["morphology", "keyword", "semantic"]]
    patches: list[PatchHit]
    patch_match_count: int = Field(ge=0)
    passage: Passage | None


class SearchResponse(APIModel):
    query_kind: Literal["patch", "region", "slide", "text_patches", "reports"]
    hits: list[CaseHit]
    total_candidates: int = Field(ge=0)
    took_ms: int = Field(ge=0)
    notice: str | None = None


class SlideScopeResponse(APIModel):
    """Scope `slide` returns patches on one slide, not cases."""

    query_kind: Literal["patch", "region", "text_patches"]
    patches: list[PatchHit]
    total_candidates: int = Field(ge=0)
    took_ms: int = Field(ge=0)
    notice: str | None = None


class SimilarCases(APIModel):
    """Q3 on the case's first slide, and Q5 on its report or clinical history."""

    slide: SearchResponse
    reports: SearchResponse
