"""In-memory placeholder data. Real queries replace these lookups."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID, uuid4

from consilium.api.schemas.annotation import (  # pragma: allowlist secret
    Annotation,
    AnnotationCreate,
    AnnotationUpdate,
    PointGeometry,
    RectGeometry,
    _geometry_matches,
)
from consilium.api.schemas.case import (  # pragma: allowlist secret
    CaseDetail,
    CaseSummary,
    PatientDetail,
)
from consilium.api.schemas.common import (  # pragma: allowlist secret
    CaseStatus,
    Page,
    Region,
    ReportSection,
    Sex,
    SlideStatus,
    Specialty,
)
from consilium.api.schemas.concept import (  # pragma: allowlist secret
    ENCODER_TEXT_LIMIT,
    SIMILARITY_NOTICE,
    Concept,
    HeatmapPatchScore,
    HeatmapRequest,
    HeatmapResponse,
)
from consilium.api.schemas.consult import (  # pragma: allowlist secret
    Citation,
    CitationsEvent,
    ConsultMessage,
    ConsultMessageCreate,
    ConsultStreamEvent,
    ConsultThread,
    DoneEvent,
    PathologistRank,
    RankingEvent,
    StepEvent,
    TextEvent,
    ToolTraceStep,
)
from consilium.api.schemas.ingestion import (  # pragma: allowlist secret
    IngestionCounts,
    IngestionJob,
    IngestionJobCreate,
    StageRecord,
)
from consilium.api.schemas.patch import PatchRef  # pragma: allowlist secret
from consilium.api.schemas.pathologist import (  # pragma: allowlist secret
    Pathologist,
    PathologistRef,
)
from consilium.api.schemas.patient import PatientRef, PatientSummary  # pragma: allowlist secret
from consilium.api.schemas.report import Report, ReportNotReported  # pragma: allowlist secret
from consilium.api.schemas.search import (  # pragma: allowlist secret
    CaseHit,
    Passage,
    PatchHit,
    PatchSearchRequest,
    ReportSearchRequest,
    SearchResponse,
    SimilarCases,
    SlideScopeResponse,
)
from consilium.api.schemas.search import SearchFilters as QueryFilters  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideDetail, SlideSummary  # pragma: allowlist secret

DEMO_USER_ID = "path-okafor"
OTHER_USER_ID = "path-adebayo"
PATIENT_MULTI_ID = "pt-0042"
PATIENT_SINGLE_ID = "pt-0007"
CASE_SIGNED_BREAST = "breast-TCGA-A2-0001"
CASE_OPEN_BREAST = "breast-TCGA-A2-0002"
CASE_SIGNED_THORAX = "thorax-TCGA-38-4631"
SLIDE_SIGNED_BREAST = "breast-TCGA-A2-0001-s1"
SLIDE_OPEN_BREAST = "breast-TCGA-A2-0002-s1"
SLIDE_SIGNED_THORAX = "thorax-TCGA-38-4631-s1"
PATCH_BREAST = 1001
PATCH_BREAST_OTHER = 1003
PATCH_THORAX = 1002
PATCH_OPEN = 1004
SEEDED_ANNOTATION_ID = UUID("00000000-0000-4000-8000-000000000001")
SEEDED_THREAD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
SEEDED_JOB_ID = UUID("00000000-0000-4000-8000-0000000000b1")

_CREATED = datetime(2026, 1, 1, tzinfo=UTC)


class StoreError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PatchRecord:
    id: int
    slide_id: str
    case_id: str
    x: int
    y: int
    size: int

    def as_ref(self) -> PatchRef:
        return PatchRef(
            id=self.id,
            slide_id=self.slide_id,
            case_id=self.case_id,
            x=self.x,
            y=self.y,
            size=self.size,
            thumbnail_url=f"/api/patches/{self.id}/thumbnail",
        )

    def as_hit(self, similarity: float) -> PatchHit:
        return PatchHit(
            patch_id=self.id,
            slide_id=self.slide_id,
            x=self.x,
            y=self.y,
            size=self.size,
            similarity=similarity,
            thumbnail_url=f"/api/patches/{self.id}/thumbnail",
        )


def _intersects(patch: PatchRecord, region: Region) -> bool:
    return not (
        patch.x + patch.size <= region.x
        or region.x + region.width <= patch.x
        or patch.y + patch.size <= region.y
        or region.y + region.height <= patch.y
    )


RowT = TypeVar("RowT")


def _cursor(
    rows: list[RowT],
    limit: int,
    cursor: str | None,
    key: Callable[[RowT], str],
) -> tuple[list[RowT], str | None]:
    if cursor is not None:
        ids = [key(row) for row in rows]
        if cursor not in ids:
            raise StoreError(422, "validation_error", "Unknown cursor.")
        start = ids.index(cursor) + 1
    else:
        start = 0
    chunk = rows[start : start + limit]
    next_cursor = key(chunk[-1]) if chunk and start + limit < len(rows) else None
    return chunk, next_cursor


class Store:
    def __init__(self) -> None:
        self.pathologists: dict[str, Pathologist] = {}
        self.patients: dict[str, PatientDetail] = {}
        self.cases: dict[str, CaseDetail] = {}
        self.reports: dict[str, Report | ReportNotReported] = {}
        self.slides: dict[str, SlideDetail] = {}
        self.patches: list[PatchRecord] = []
        self.concepts: list[Concept] = []
        self.annotations: dict[UUID, Annotation] = {}
        self.threads: dict[UUID, ConsultThread] = {}
        self.thread_owner: dict[UUID, str] = {}
        self.jobs: dict[UUID, IngestionJob] = {}

    @classmethod
    def seed(cls) -> Store:
        store = cls()
        okafor = _person(
            DEMO_USER_ID,
            "Dr A. Okafor",
            Specialty.BREAST,
            [Specialty.SKIN],
            demo=True,
        )
        adebayo = _person(OTHER_USER_ID, "Dr B. Adebayo", Specialty.THORAX, [], demo=False)
        nowak = _person(
            "path-nowak",
            "Dr C. Nowak",
            Specialty.COLORECTAL,
            [Specialty.GASTROINTESTINAL],
            demo=False,
        )
        singh = _person(
            "path-singh",
            "Dr D. Singh",
            Specialty.SKIN,
            [Specialty.BREAST],
            demo=False,
        )
        store.pathologists = {person.id: person for person in (okafor, adebayo, nowak, singh)}

        breast_patient = _patient_ref(PATIENT_MULTI_ID, "PT-0042", Sex.FEMALE, 2, True)
        thorax_patient = _patient_ref(PATIENT_SINGLE_ID, "PT-0007", Sex.MALE, 1, False)
        breast_slide = _slide(SLIDE_SIGNED_BREAST, CASE_SIGNED_BREAST, patch_count=2)
        open_slide = _slide(SLIDE_OPEN_BREAST, CASE_OPEN_BREAST, patch_count=1)
        thorax_slide = _slide(SLIDE_SIGNED_THORAX, CASE_SIGNED_THORAX, patch_count=1)
        store.slides = {slide.id: slide for slide in (breast_slide, open_slide, thorax_slide)}

        signed_breast = _case(
            CASE_SIGNED_BREAST,
            breast_patient,
            "Core biopsy",
            Specialty.BREAST,
            60,
            Sex.FEMALE,
            "C50.9",
            CaseStatus.SIGNED_OUT,
            okafor,
            datetime(2026, 8, 1, tzinfo=UTC),
            breast_slide,
            "Invasive carcinoma with glandular differentiation.",
            "signed",
            prior=1,
        )
        open_breast = _case(
            CASE_OPEN_BREAST,
            breast_patient,
            "Excision",
            Specialty.BREAST,
            61,
            Sex.FEMALE,
            None,
            CaseStatus.OPEN,
            okafor,
            datetime(2026, 11, 1, tzinfo=UTC),
            open_slide,
            None,
            "none",
            prior=1,
        )
        signed_thorax = _case(
            CASE_SIGNED_THORAX,
            thorax_patient,
            "Primary resection",
            Specialty.THORAX,
            58,
            Sex.MALE,
            "C34.1",
            CaseStatus.SIGNED_OUT,
            adebayo,
            datetime(2026, 10, 15, tzinfo=UTC),
            thorax_slide,
            "Adenocarcinoma, NOS.",
            "signed",
            prior=0,
        )
        store.cases = {case.id: case for case in (signed_breast, open_breast, signed_thorax)}
        store.patients = {
            PATIENT_MULTI_ID: _patient_detail(
                breast_patient,
                datetime(2026, 11, 1, tzinfo=UTC),
                1,
                1,
                [Specialty.BREAST],
                1966,
                [open_breast, signed_breast],
            ),
            PATIENT_SINGLE_ID: _patient_detail(
                thorax_patient,
                datetime(2026, 10, 15, tzinfo=UTC),
                0,
                1,
                [Specialty.THORAX],
                1968,
                [signed_thorax],
            ),
        }
        store.reports = {
            CASE_SIGNED_BREAST: _signed_report(
                signed_breast,
                "Screening mammogram. Core biopsy performed.",
                "Core fragments of firm pale tissue.",
                "Invasive carcinoma forming glands.",
                "Invasive carcinoma with glandular differentiation.",
                "Synthetic sign-out for the demo corpus.",
                datetime(2026, 8, 4, tzinfo=UTC),
            ),
            CASE_OPEN_BREAST: ReportNotReported(
                case_id=CASE_OPEN_BREAST,
                status="none",
                clinical_history="Screening imaging of the breast. Biopsy requested.",
            ),
            CASE_SIGNED_THORAX: _signed_report(
                signed_thorax,
                "Cough and a lung mass.",
                "Lobe with a firm mass.",
                "Malignant glands in a desmoplastic stroma.",
                "Adenocarcinoma, NOS.",
                None,
                datetime(2026, 10, 18, tzinfo=UTC),
            ),
        }
        store.patches = [
            PatchRecord(PATCH_BREAST, SLIDE_SIGNED_BREAST, CASE_SIGNED_BREAST, 0, 0, 512),
            PatchRecord(PATCH_BREAST_OTHER, SLIDE_SIGNED_BREAST, CASE_SIGNED_BREAST, 512, 0, 512),
            PatchRecord(PATCH_OPEN, SLIDE_OPEN_BREAST, CASE_OPEN_BREAST, 0, 0, 512),
            PatchRecord(PATCH_THORAX, SLIDE_SIGNED_THORAX, CASE_SIGNED_THORAX, 0, 0, 512),
        ]
        store.concepts = [
            Concept(
                id="necrosis",
                label="Necrosis",
                prompt="an H&E image of tumour necrosis",
                specialty=None,
            ),
            Concept(
                id="mitotic-figures",
                label="Mitotic figures",
                prompt="an H&E image of mitotic figures",
                specialty=None,
            ),
            Concept(
                id="keratinisation",
                label="Keratinisation",
                prompt="an H&E image of keratinisation",
                specialty=Specialty.SKIN,
            ),
        ]
        store.annotations[SEEDED_ANNOTATION_ID] = Annotation(
            id=SEEDED_ANNOTATION_ID,
            slide_id=SLIDE_SIGNED_BREAST,
            case_id=CASE_SIGNED_BREAST,
            author=_ref(okafor),
            can_edit=False,
            kind="rect",
            geometry=RectGeometry(x=10, y=20, width=100, height=80),
            label="margin",
            note="Region marked for a colleague.",
            created_at=datetime(2026, 8, 5, tzinfo=UTC),
            updated_at=datetime(2026, 8, 5, tzinfo=UTC),
        )
        store._seed_thread(open_breast, okafor)
        store._seed_job(adebayo)
        return store

    def demo_user(self) -> Pathologist:
        matches = [person for person in self.pathologists.values() if person.is_demo_user]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one demo pathologist")
        return matches[0]

    def list_pathologists(self) -> list[Pathologist]:
        return sorted(self.pathologists.values(), key=lambda person: person.id)

    def list_patients(
        self,
        *,
        q: str | None,
        multi_case: bool,
        limit: int,
        cursor: str | None,
    ) -> Page[PatientSummary]:
        rows = list(self.patients.values())
        if q:
            needle = q.casefold()
            rows = [
                row
                for row in rows
                if needle in row.id.casefold() or needle in row.display_label.casefold()
            ]
        if multi_case:
            rows = [row for row in rows if row.case_count > 1]
        rows.sort(key=lambda row: row.latest_accessioned_at, reverse=True)
        chunk, nxt = _cursor(rows, limit, cursor, lambda row: row.id)
        items = [
            PatientSummary.model_validate(
                row.model_dump(include=set(PatientSummary.model_fields))
            )
            for row in chunk
        ]
        return Page(items=items, next_cursor=nxt)

    def get_patient(self, patient_id: str) -> PatientDetail:
        patient = self.patients.get(patient_id)
        if patient is None:
            raise StoreError(404, "not_found", "Patient not found.")
        return patient

    def list_cases(
        self,
        *,
        actor: Pathologist,
        view: str | None,
        status: CaseStatus | None,
        specialty: Specialty | None,
        assigned_to: str | None,
        icd10: str | None,
        patient_id: str | None,
        limit: int,
        cursor: str | None,
    ) -> Page[CaseSummary]:
        rows = list(self.cases.values())
        if view == "mine":
            rows = [row for row in rows if row.assigned_to.id == actor.id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        if specialty is not None:
            rows = [row for row in rows if row.specialty == specialty]
        if assigned_to:
            rows = [row for row in rows if row.assigned_to.id == assigned_to]
        if icd10:
            rows = [row for row in rows if row.icd10 is not None and row.icd10.startswith(icd10)]
        if patient_id:
            rows = [row for row in rows if row.patient.id == patient_id]
        if view == "mine":
            rows.sort(
                key=lambda row: (row.status != CaseStatus.OPEN, -row.accessioned_at.timestamp())
            )
        else:
            rows.sort(key=lambda row: row.accessioned_at, reverse=True)
        chunk, nxt = _cursor(rows, limit, cursor, lambda row: row.id)
        return Page(items=[_summary(row) for row in chunk], next_cursor=nxt)

    def get_case(self, case_id: str) -> CaseDetail:
        return self._case(case_id)

    def get_report(self, case_id: str) -> Report | ReportNotReported:
        self._case(case_id)
        report = self.reports.get(case_id)
        if report is None:
            raise StoreError(404, "not_found", "Report not found.")
        return report

    def similar(self, case_id: str) -> SimilarCases:
        case = self._case(case_id)
        if not case.slides:
            slide_result = SearchResponse(
                query_kind="slide",
                hits=[],
                total_candidates=0,
                took_ms=4,
                notice=None,
            )
        else:
            found = self.search_patches(
                PatchSearchRequest(slide_id=case.slides[0].id, context_case_id=case_id)
            )
            if not isinstance(found, SearchResponse):
                raise StoreError(500, "error", "Slide similarity did not return cases.")
            slide_result = found
        report = self.reports[case_id]
        if isinstance(report, Report) and report.conclusion:
            text = report.conclusion
        elif isinstance(report, ReportNotReported) and report.clinical_history:
            text = report.clinical_history
        else:
            text = "clinical history"
        return SimilarCases(
            slide=slide_result,
            reports=self.search_reports(ReportSearchRequest(text=text, context_case_id=case_id)),
        )

    def get_slide(self, slide_id: str) -> SlideDetail:
        return self._slide(slide_id)

    def get_patch(self, patch_id: int) -> PatchRef:
        return self._patch(patch_id).as_ref()

    def patch_at(self, slide_id: str, x: int, y: int) -> PatchRef:
        self._slide(slide_id)
        for patch in self.patches:
            if patch.slide_id != slide_id:
                continue
            if patch.x <= x < patch.x + patch.size and patch.y <= y < patch.y + patch.size:
                return patch.as_ref()
        raise StoreError(404, "not_found", "No patch contains that point.")

    def concepts_for(self, specialty: Specialty | None) -> list[Concept]:
        if specialty is None:
            return list(self.concepts)
        return [
            concept
            for concept in self.concepts
            if concept.specialty is None or concept.specialty == specialty
        ]

    def heatmap(self, slide_id: str, body: HeatmapRequest) -> HeatmapResponse:
        self._slide(slide_id)
        concept_id: str | None = None
        if body.concept_id is not None:
            concept = next((item for item in self.concepts if item.id == body.concept_id), None)
            if concept is None:
                raise StoreError(404, "not_found", "Unknown concept.")
            phrase = concept.prompt
            concept_id = concept.id
        else:
            phrase = body.text or ""
        truncated = len(phrase) > ENCODER_TEXT_LIMIT
        if truncated:
            phrase = phrase[:ENCODER_TEXT_LIMIT]
        patches = _heatmap_patches(negative=body.negative_text is not None)
        top = sorted(patches, key=lambda item: (-item.score, item.y, item.x))[:10]
        notice = SIMILARITY_NOTICE
        if truncated:
            notice = f"{notice} The phrase was truncated to the encoder limit."
        return HeatmapResponse(
            text=phrase,
            concept_id=concept_id,
            negative_text=body.negative_text,
            notice=notice,
            truncated=truncated,
            patches=patches,
            top=top,
        )

    def search_patches(self, body: PatchSearchRequest) -> SearchResponse | SlideScopeResponse:
        selected = sum(
            value is not None
            for value in (body.patch_id, body.region, body.slide_id, body.text)
        )
        if selected != 1:
            raise StoreError(
                422,
                "validation_error",
                "Provide one of patch_id, region, slide_id or text.",
            )
        if body.text is not None and body.text.strip() == "":
            raise StoreError(422, "validation_error", "text must not be empty")
        context = self._optional_case(body.context_case_id)
        notice = _text_notice(body.text, ENCODER_TEXT_LIMIT)
        anchor: PatchRecord | None = None
        if body.patch_id is not None:
            anchor = self._patch(body.patch_id)
            kind = "patch"
            slide_id = anchor.slide_id
            exclude = {anchor.case_id}
        elif body.region is not None:
            slide = self._slide(body.region.slide_id)
            covered = [
                patch
                for patch in self.patches
                if patch.slide_id == slide.id and _intersects(patch, body.region)
            ]
            if not covered:
                raise StoreError(422, "validation_error", "Region covers no tissue patches.")
            kind = "region"
            slide_id = slide.id
            exclude = {slide.case_id}
        elif body.slide_id is not None:
            slide = self._slide(body.slide_id)
            if body.scope == "slide":
                raise StoreError(
                    422,
                    "validation_error",
                    "scope slide applies to a patch, region or text query.",
                )
            kind = "slide"
            slide_id = slide.id
            exclude = {slide.case_id}
        else:
            kind = "text_patches"
            exclude = set()
            if body.scope == "slide":
                if context is None:
                    raise StoreError(
                        422,
                        "validation_error",
                        "A text query with scope slide needs context_case_id.",
                    )
                if not context.slides:
                    raise StoreError(404, "not_found", "The context case has no slide.")
                slide_id = context.slides[0].id
            else:
                slide_id = None
        if body.scope == "slide":
            if kind not in {"patch", "region", "text_patches"} or slide_id is None:
                raise StoreError(422, "validation_error", "scope slide needs a slide.")
            return self._patches_on_slide(kind, slide_id, anchor, body, notice)
        return self._case_search(
            kind=kind,
            context=context,
            filters=body.filters,
            exclude=exclude,
            limit=body.limit,
            notice=notice,
            mode=None,
        )

    def search_reports(self, body: ReportSearchRequest) -> SearchResponse:
        context = self._optional_case(body.context_case_id)
        return self._case_search(
            kind="reports",
            context=context,
            filters=body.filters,
            exclude=set(),
            limit=body.limit,
            notice=_text_notice(body.text, 2000),
            mode=body.mode,
        )

    def list_annotations(self, slide_id: str, actor: Pathologist) -> list[Annotation]:
        self._slide(slide_id)
        rows = [row for row in self.annotations.values() if row.slide_id == slide_id]
        rows.sort(key=lambda row: row.created_at)
        return [_visible(row, actor) for row in rows]

    def create_annotation(
        self,
        slide_id: str,
        actor: Pathologist,
        body: AnnotationCreate,
    ) -> Annotation:
        slide = self._slide(slide_id)
        _bounds(slide, body.geometry)
        now = datetime.now(UTC)
        row = Annotation(
            id=uuid4(),
            slide_id=slide.id,
            case_id=slide.case_id,
            author=_ref(actor),
            can_edit=False,
            kind=body.kind,
            geometry=body.geometry,
            label=body.label,
            note=body.note,
            created_at=now,
            updated_at=now,
        )
        self.annotations[row.id] = row
        return _visible(row, actor)

    def update_annotation(
        self,
        annotation_id: UUID,
        actor: Pathologist,
        body: AnnotationUpdate,
    ) -> Annotation:
        row = self.annotations.get(annotation_id)
        if row is None:
            raise StoreError(404, "not_found", "Annotation not found.")
        if row.author.id != actor.id:
            raise StoreError(403, "forbidden", "Only the author can change this annotation.")
        geometry = row.geometry
        if body.geometry is not None:
            try:
                _geometry_matches(row.kind, body.geometry)
            except ValueError as exc:
                raise StoreError(422, "validation_error", str(exc)) from exc
            _bounds(self._slide(row.slide_id), body.geometry)
            geometry = body.geometry
        note = body.note if "note" in body.model_fields_set else row.note
        updated = row.model_copy(
            update={
                "geometry": geometry,
                "label": body.label if body.label is not None else row.label,
                "note": note,
                "updated_at": datetime.now(UTC),
            }
        )
        self.annotations[annotation_id] = updated
        return _visible(updated, actor)

    def delete_annotation(self, annotation_id: UUID, actor: Pathologist) -> None:
        row = self.annotations.get(annotation_id)
        if row is None:
            raise StoreError(404, "not_found", "Annotation not found.")
        if row.author.id != actor.id:
            raise StoreError(403, "forbidden", "Only the author can change this annotation.")
        del self.annotations[annotation_id]

    def start_thread(self, case_id: str, actor: Pathologist, new: bool) -> ConsultThread:
        self._case(case_id)
        if not new:
            existing = self._latest_thread(case_id, actor.id)
            if existing is not None:
                return existing.model_copy(deep=True)
        now = datetime.now(UTC)
        thread = ConsultThread(
            id=uuid4(),
            case_id=case_id,
            title=None,
            created_at=now,
            updated_at=now,
            messages=[],
        )
        self.threads[thread.id] = thread
        self.thread_owner[thread.id] = actor.id
        return thread.model_copy(deep=True)

    def get_thread(self, thread_id: UUID, actor: Pathologist) -> ConsultThread:
        thread = self._owned_thread(thread_id, actor.id)
        return thread.model_copy(deep=True)

    def reply(
        self,
        thread_id: UUID,
        actor: Pathologist,
        body: ConsultMessageCreate,
    ) -> list[ConsultStreamEvent]:
        thread = self._owned_thread(thread_id, actor.id)
        now = datetime.now(UTC)
        user = ConsultMessage(
            id=uuid4(),
            role="user",
            content=body.content,
            attachments=body.attachments,
            citations=None,
            ranking=None,
            tool_trace=None,
            status="complete",
            created_at=now,
        )
        precedent = self._precedent(thread.case_id)
        citation = Citation(
            case_id=precedent.id,
            slide_id=precedent.slides[0].id if precedent.slides else None,
            patch_id=None,
            quote=precedent.conclusion_line,
            case=_summary(precedent),
        )
        ranking = [
            PathologistRank(
                pathologist_id=precedent.assigned_to.id,
                name=precedent.assigned_to.name,
                specialty=precedent.assigned_to.primary_specialty,
                case_count=1,
                case_ids=[precedent.id],
            )
        ]
        trace = [
            ToolTraceStep(
                tool="search_reports",
                summary="Found 1 signed-out case.",
                duration_ms=3,
            ),
            ToolTraceStep(
                tool="rank_pathologists",
                summary="1 pathologist, counted from case ids.",
                duration_ms=2,
            ),
        ]
        content = (
            "Signed-out precedent is cited below. "
            "This prototype retrieves cases and does not diagnose the open case."
        )
        assistant = ConsultMessage(
            id=uuid4(),
            role="assistant",
            content=content,
            attachments=None,
            citations=[citation],
            ranking=ranking,
            tool_trace=trace,
            status="complete",
            created_at=now,
        )
        title = thread.title if thread.title is not None else body.content.strip()[:80]
        self.threads[thread.id] = thread.model_copy(
            update={
                "title": title,
                "updated_at": now,
                "messages": [*thread.messages, user, assistant],
            }
        )
        return [
            StepEvent(tool=trace[0].tool, summary=trace[0].summary, duration_ms=3),
            StepEvent(tool=trace[1].tool, summary=trace[1].summary, duration_ms=2),
            TextEvent(content=content),
            CitationsEvent(citations=[citation]),
            RankingEvent(ranking=ranking),
            DoneEvent(message=assistant),
        ]

    def list_jobs(self) -> list[IngestionJob]:
        return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def get_job(self, job_id: UUID) -> IngestionJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise StoreError(404, "not_found", "Ingestion job not found.")
        return job

    def create_job(self, body: IngestionJobCreate, actor: Pathologist) -> tuple[IngestionJob, bool]:
        for job in self.jobs.values():
            if (
                job.dataset == body.dataset
                and job.slide_path == body.slide_path
                and job.status in {"queued", "running"}
            ):
                return job, False
        job = IngestionJob(
            id=uuid4(),
            dataset=body.dataset,
            slide_path=body.slide_path,
            case_id=None,
            slide_id=None,
            requested_by=_ref(actor),
            status="queued",
            stage=None,
            stage_history=[],
            counts=None,
            error=None,
            attempts=0,
            created_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
        )
        self.jobs[job.id] = job
        return job, True

    def _case(self, case_id: str) -> CaseDetail:
        case = self.cases.get(case_id)
        if case is None:
            raise StoreError(404, "not_found", "Case not found.")
        return case

    def _optional_case(self, case_id: str | None) -> CaseDetail | None:
        if case_id is None:
            return None
        return self._case(case_id)

    def _slide(self, slide_id: str) -> SlideDetail:
        slide = self.slides.get(slide_id)
        if slide is None:
            raise StoreError(404, "not_found", "Slide not found.")
        return slide

    def _patch(self, patch_id: int) -> PatchRecord:
        for patch in self.patches:
            if patch.id == patch_id:
                return patch
        raise StoreError(404, "not_found", "Patch not found.")

    def _owned_thread(self, thread_id: UUID, user_id: str) -> ConsultThread:
        thread = self.threads.get(thread_id)
        if thread is None or self.thread_owner.get(thread_id) != user_id:
            raise StoreError(404, "not_found", "Consult thread not found.")
        return thread

    def _latest_thread(self, case_id: str, user_id: str) -> ConsultThread | None:
        rows = [
            thread
            for thread in self.threads.values()
            if thread.case_id == case_id and self.thread_owner.get(thread.id) == user_id
        ]
        if not rows:
            return None
        return max(rows, key=lambda thread: thread.updated_at)

    def _precedent(self, case_id: str) -> CaseDetail:
        current = self._case(case_id)
        signed = [
            case
            for case in self.cases.values()
            if case.status == CaseStatus.SIGNED_OUT and case.id != case_id
        ]
        same = [case for case in signed if case.patient.id == current.patient.id]
        pool = same or signed
        if not pool:
            raise StoreError(404, "not_found", "No signed-out precedent is available.")
        return max(pool, key=lambda case: case.accessioned_at)

    def _patches_on_slide(
        self,
        kind: str,
        slide_id: str,
        anchor: PatchRecord | None,
        body: PatchSearchRequest,
        notice: str | None,
    ) -> SlideScopeResponse:
        if body.region is not None:
            rows = [
                patch
                for patch in self.patches
                if patch.slide_id == slide_id and _intersects(patch, body.region)
            ]
        else:
            rows = [patch for patch in self.patches if patch.slide_id == slide_id]
            if anchor is not None:
                rows = [patch for patch in rows if patch.id != anchor.id]
        total = len(rows)
        limited = rows[: body.limit]
        return SlideScopeResponse(
            query_kind=kind,  # type: ignore[arg-type]
            patches=[patch.as_hit(0.8) for patch in limited],
            total_candidates=total,
            took_ms=4,
            notice=notice,
        )

    def _case_search(
        self,
        *,
        kind: str,
        context: CaseDetail | None,
        filters: QueryFilters | None,
        exclude: set[str],
        limit: int,
        notice: str | None,
        mode: str | None,
    ) -> SearchResponse:
        if context is not None:
            exclude = {*exclude, context.id}
        eligible = [
            case
            for case in self.cases.values()
            if case.id not in exclude and _allows(case, filters)
        ]
        eligible.sort(key=lambda case: case.accessioned_at, reverse=True)
        if kind == "reports":
            total = len(eligible)
        else:
            eligible_ids = {case.id for case in eligible}
            total = sum(1 for patch in self.patches if patch.case_id in eligible_ids)
        hits: list[CaseHit] = []
        for index, case in enumerate(eligible[:limit]):
            case_patches = [patch for patch in self.patches if patch.case_id == case.id]
            score = 1.0 if index == 0 else round(1 - index / max(len(eligible), 1), 4)
            if kind == "reports":
                patches: list[PatchHit] = []
                passage = _passage(case, mode or "hybrid")
                matched: list[str] = {
                    "keyword": ["keyword"],
                    "semantic": ["semantic"],
                }.get(mode or "hybrid", ["keyword", "semantic"])
            else:
                patches = [
                    patch.as_hit(0.8 - offset * 0.05)
                    for offset, patch in enumerate(case_patches[:3])
                ]
                passage = None
                matched = ["morphology"]
            hits.append(
                CaseHit(
                    case=_summary(case),
                    author=case.assigned_to,
                    same_patient=context is not None and case.patient.id == context.patient.id,
                    score=score,
                    matched_by=matched,  # type: ignore[arg-type]
                    patches=patches,
                    patch_match_count=0 if kind == "reports" else len(case_patches),
                    passage=passage,
                )
            )
        return SearchResponse(
            query_kind=kind,  # type: ignore[arg-type]
            hits=hits,
            total_candidates=total,
            took_ms=4,
            notice=notice,
        )

    def _seed_thread(self, case: CaseDetail, actor: Pathologist) -> None:
        created = datetime(2026, 11, 2, tzinfo=UTC)
        question = "Who has reported similar signed-out cases?"
        user = ConsultMessage(
            id=UUID("00000000-0000-4000-8000-0000000000a2"),
            role="user",
            content=question,
            attachments=None,
            citations=None,
            ranking=None,
            tool_trace=None,
            status="complete",
            created_at=created,
        )
        precedent = self.cases[CASE_SIGNED_BREAST]
        citation = Citation(
            case_id=precedent.id,
            slide_id=precedent.slides[0].id,
            patch_id=None,
            quote=precedent.conclusion_line,
            case=_summary(precedent),
        )
        ranking = [
            PathologistRank(
                pathologist_id=actor.id,
                name=actor.name,
                specialty=actor.primary_specialty,
                case_count=1,
                case_ids=[precedent.id],
            )
        ]
        trace = [
            ToolTraceStep(
                tool="get_patient_history",
                summary="1 signed-out prior case.",
                duration_ms=2,
            )
        ]
        assistant = ConsultMessage(
            id=UUID("00000000-0000-4000-8000-0000000000a3"),
            role="assistant",
            content=(
                "A signed-out case from this patient is cited. "
                "This is precedent, not a diagnosis of the open case."
            ),
            attachments=None,
            citations=[citation],
            ranking=ranking,
            tool_trace=trace,
            status="complete",
            created_at=created,
        )
        thread = ConsultThread(
            id=SEEDED_THREAD_ID,
            case_id=case.id,
            title=question,
            created_at=created,
            updated_at=created,
            messages=[user, assistant],
        )
        self.threads[thread.id] = thread
        self.thread_owner[thread.id] = actor.id

    def _seed_job(self, actor: Pathologist) -> None:
        started = datetime(2026, 10, 20, 9, tzinfo=UTC)
        finished = datetime(2026, 10, 20, 9, 5, tzinfo=UTC)
        self.jobs[SEEDED_JOB_ID] = IngestionJob(
            id=SEEDED_JOB_ID,
            dataset="TCGA-LUAD",
            slide_path="TCGA-38-4631-01Z-00-DX1.svs",
            case_id=CASE_SIGNED_THORAX,
            slide_id=SLIDE_SIGNED_THORAX,
            requested_by=_ref(actor),
            status="done",
            stage="index",
            stage_history=[
                StageRecord(
                    stage="index",
                    started_at=started,
                    finished_at=finished,
                    detail="Placeholder stage history.",
                )
            ],
            counts=IngestionCounts(patches=1, chunks=2),
            error=None,
            attempts=1,
            created_at=started,
            started_at=started,
            finished_at=finished,
        )


def _person(
    person_id: str,
    name: str,
    primary: Specialty,
    secondary: list[Specialty],
    *,
    demo: bool,
) -> Pathologist:
    return Pathologist(
        id=person_id,
        name=name,
        primary_specialty=primary,
        is_synthetic=True,
        role_title="Consultant Histopathologist",
        secondary_specialties=secondary,
        is_demo_user=demo,
        created_at=_CREATED,
    )


def _ref(person: Pathologist) -> PathologistRef:
    fields = set(PathologistRef.model_fields)
    return PathologistRef.model_validate(person.model_dump(include=fields))


def _patient_ref(
    patient_id: str,
    label: str,
    sex: Sex,
    case_count: int,
    synthetic: bool,
) -> PatientRef:
    return PatientRef(
        id=patient_id,
        display_label=label,
        sex=sex,
        case_count=case_count,
        is_synthetic_linkage=synthetic,
    )


def _slide(slide_id: str, case_id: str, *, patch_count: int) -> SlideDetail:
    return SlideDetail(
        id=slide_id,
        ordinal=1,
        stain="HE",
        magnification=20,
        status=SlideStatus.READY,
        thumbnail_url=f"/api/slides/{slide_id}/thumbnail",
        case_id=case_id,
        mpp=0.5,
        width=2048,
        height=2048,
        patch_size=512,
        patch_count=patch_count,
        dzi_url=f"/api/slides/{slide_id}.dzi",
    )


def _case(
    case_id: str,
    patient: PatientRef,
    specimen: str,
    specialty: Specialty,
    age: int,
    sex: Sex,
    icd10: str | None,
    status: CaseStatus,
    author: Pathologist,
    accessioned_at: datetime,
    slide: SlideDetail,
    conclusion: str | None,
    report_status: str,
    *,
    prior: int,
) -> CaseDetail:
    summary_slide = SlideSummary.model_validate(
        slide.model_dump(include=set(SlideSummary.model_fields))
    )
    return CaseDetail(
        id=case_id,
        patient=patient,
        specimen_label=specimen,
        specialty=specialty,
        patient_age=age,
        patient_sex=sex,
        icd10=icd10,
        status=status,
        assigned_to=_ref(author),
        accessioned_at=accessioned_at,
        slide_count=1,
        thumbnail_url=summary_slide.thumbnail_url,
        conclusion_line=conclusion,
        slides=[summary_slide],
        report_status=report_status,  # type: ignore[arg-type]
        prior_case_count=prior,
    )


def _patient_detail(
    ref: PatientRef,
    latest: datetime,
    open_count: int,
    signed_count: int,
    specialties: list[Specialty],
    birth_year: int,
    cases: list[CaseDetail],
) -> PatientDetail:
    ordered = sorted(cases, key=lambda case: case.accessioned_at, reverse=True)
    return PatientDetail(
        id=ref.id,
        display_label=ref.display_label,
        sex=ref.sex,
        case_count=ref.case_count,
        is_synthetic_linkage=ref.is_synthetic_linkage,
        latest_accessioned_at=latest,
        open_case_count=open_count,
        signed_out_case_count=signed_count,
        specialties=specialties,
        birth_year=birth_year,
        cases=[_summary(case) for case in ordered],
    )


def _signed_report(
    case: CaseDetail,
    clinical: str,
    gross: str,
    micro: str,
    conclusion: str,
    additional: str | None,
    signed_at: datetime,
) -> Report:
    body = "\n\n".join(
        part
        for part in (
            f"Clinical History\n{clinical}",
            f"Gross Description\n{gross}",
            f"Microscopic Description\n{micro}",
            f"Conclusion\n{conclusion}",
            f"Comment\n{additional}" if additional else "",
        )
        if part
    )
    return Report(
        id=f"{case.id}-r1",
        case_id=case.id,
        status="signed",
        body=body,
        clinical_history=clinical,
        gross_description=gross,
        microscopic_description=micro,
        conclusion=conclusion,
        additional_info=additional,
        icd10=case.icd10,
        signed_at=signed_at,
        author=case.assigned_to,
        is_synthetic_author=True,
    )


def _summary(case: CaseDetail) -> CaseSummary:
    return CaseSummary.model_validate(case.model_dump(include=set(CaseSummary.model_fields)))


def _visible(row: Annotation, actor: Pathologist) -> Annotation:
    return row.model_copy(update={"can_edit": row.author.id == actor.id})


def _bounds(slide: SlideDetail, geometry: RectGeometry | PointGeometry) -> None:
    if isinstance(geometry, RectGeometry):
        inside = (
            geometry.x >= 0
            and geometry.y >= 0
            and geometry.x + geometry.width <= slide.width
            and geometry.y + geometry.height <= slide.height
        )
    else:
        inside = 0 <= geometry.x < slide.width and 0 <= geometry.y < slide.height
    if not inside:
        raise StoreError(422, "validation_error", "Geometry is outside the slide.")


def _allows(case: CaseDetail, filters: QueryFilters | None) -> bool:
    if case.status != CaseStatus.SIGNED_OUT:
        return False
    if filters is None:
        return True
    if filters.status is not None and case.status != filters.status:
        return False
    if filters.patient_id and case.patient.id != filters.patient_id:
        return False
    if filters.specialty and case.specialty not in filters.specialty:
        return False
    if filters.icd10_prefix and not (
        case.icd10 is not None and case.icd10.startswith(filters.icd10_prefix)
    ):
        return False
    if filters.stain and not any(slide.stain == filters.stain for slide in case.slides):
        return False
    return True


def _passage(case: CaseDetail, mode: str) -> Passage:
    text = case.conclusion_line or ""
    highlights: list[tuple[int, int]] = []
    if mode != "semantic":
        word = "carcinoma"
        start = text.lower().find(word)
        if start >= 0:
            highlights.append((start, start + len(word)))
    return Passage(section=ReportSection.CONCLUSION, text=text, highlights=highlights)


def _text_notice(text: str | None, limit: int) -> str | None:
    if text is not None and len(text.strip()) > limit:
        return "Query text was truncated to the encoder limit."
    return None


def _heatmap_patches(*, negative: bool) -> list[HeatmapPatchScore]:
    if negative:
        scores = (1.0, 0.6, 0.0)
    else:
        scores = (0.0, 0.4, 1.0)
    points = ((0, 0), (512, 0), (0, 512))
    return [
        HeatmapPatchScore(x=x, y=y, size=512, score=score)
        for (x, y), score in zip(points, scores, strict=True)
    ]
