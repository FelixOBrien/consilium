"""Pydantic v2 API models. Response models omit fields the model docs never send."""

from __future__ import annotations

from consilium.api.schemas.annotation import (  # pragma: allowlist secret
    Annotation,
    AnnotationCreate,
    AnnotationUpdate,
    PointGeometry,
    RectGeometry,
)
from consilium.api.schemas.case import (  # pragma: allowlist secret
    CaseDetail,
    CaseSummary,
    PatientDetail,
)
from consilium.api.schemas.concept import (  # pragma: allowlist secret
    ENCODER_TEXT_LIMIT,
    SIMILARITY_NOTICE,
    TISSUE_SIMILARITY_NOTICE,
    Concept,
    HeatmapBBox,
    HeatmapCell,
    HeatmapCluster,
    HeatmapPatchScore,
    HeatmapRequest,
    HeatmapResponse,
)
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    Citation,
    ConsultMessage,
    ConsultMessageCreate,
    ConsultStreamEvent,
    ConsultThread,
    ConsultThreadCreate,
    PathologistRank,
    ToolTraceStep,
)
from consilium.api.schemas.ingestion import (  # pragma: allowlist secret
    IngestionJob,
    IngestionJobCreate,
)
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.api.schemas.pathologist import (  # pragma: allowlist secret
    Pathologist,
    PathologistRef,
)
from consilium.api.schemas.patient import PatientRef, PatientSummary  # pragma: allowlist secret
from consilium.api.schemas.report import (  # pragma: allowlist secret
    CaseReport,
    Report,
    ReportNotReported,
)
from consilium.api.schemas.search import (  # pragma: allowlist secret
    CaseHit,
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
    SimilarCases,
    SlideScopeResponse,
)
from consilium.api.schemas.slide import SlideDetail, SlideSummary  # pragma: allowlist secret

__all__ = [
    "ENCODER_TEXT_LIMIT",
    "SIMILARITY_NOTICE",
    "TISSUE_SIMILARITY_NOTICE",
    "Annotation",
    "AnnotationCreate",
    "AnnotationUpdate",
    "CaseDetail",
    "CaseHit",
    "CaseReport",
    "CaseSummary",
    "Citation",
    "Concept",
    "ConsultMessage",
    "ConsultMessageCreate",
    "ConsultStreamEvent",
    "ConsultThread",
    "ConsultThreadCreate",
    "HeatmapBBox",
    "HeatmapCell",
    "HeatmapCluster",
    "HeatmapPatchScore",
    "HeatmapRequest",
    "HeatmapResponse",
    "IngestionJob",
    "IngestionJobCreate",
    "PatchRef",
    "PatchSearchRequest",
    "Pathologist",
    "PathologistRank",
    "PathologistRef",
    "PatientDetail",
    "PatientRef",
    "PatientSummary",
    "PointGeometry",
    "RectGeometry",
    "Report",
    "ReportNotReported",
    "ReportSearchRequest",
    "SearchResponse",
    "SimilarCases",
    "SlideDetail",
    "SlideScopeResponse",
    "SlideSummary",
    "ToolTraceStep",
]
