from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from consilium.api.schemas.common import (  # pragma: allowlist secret
    APIModel,
    CaseStatus,
    Sex,
    Specialty,
)
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret
from consilium.api.schemas.patient import PatientRef, PatientSummary  # pragma: allowlist secret
from consilium.api.schemas.slide import SlideSummary  # pragma: allowlist secret


class CaseSummary(APIModel):
    id: str
    patient: PatientRef
    specimen_label: str | None
    specialty: Specialty
    patient_age: int | None = Field(default=None, ge=0)
    patient_sex: Sex | None
    icd10: str | None
    status: CaseStatus
    assigned_to: PathologistRef
    accessioned_at: datetime
    slide_count: int = Field(ge=0)
    thumbnail_url: str | None
    conclusion_line: str | None


class CaseDetail(CaseSummary):
    slides: list[SlideSummary]
    report_status: Literal["signed", "draft", "none"]
    prior_case_count: int = Field(ge=0)


class PatientDetail(PatientSummary):
    birth_year: int | None
    cases: list[CaseSummary]
