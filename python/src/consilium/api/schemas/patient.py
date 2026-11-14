from __future__ import annotations

from datetime import datetime

from pydantic import Field

from consilium.api.schemas.common import APIModel, Sex, Specialty  # pragma: allowlist secret


class PatientRef(APIModel):
    id: str
    display_label: str
    sex: Sex | None
    case_count: int = Field(ge=0)
    is_synthetic_linkage: bool = Field(
        description="True when longitudinal history links more than one TCGA donor."
    )


class PatientSummary(PatientRef):
    latest_accessioned_at: datetime
    open_case_count: int = Field(ge=0)
    signed_out_case_count: int = Field(ge=0)
    specialties: list[Specialty]
