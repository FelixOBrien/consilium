from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from consilium.api.schemas.common import APIModel  # pragma: allowlist secret
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret


class Report(APIModel):
    """Signed or draft report. The value `withheld` is never sent."""

    id: str
    case_id: str
    status: Literal["signed", "draft"]
    body: str
    clinical_history: str | None
    gross_description: str | None
    microscopic_description: str | None
    conclusion: str | None
    additional_info: str | None
    icd10: str | None
    signed_at: datetime | None
    author: PathologistRef
    is_synthetic_author: Literal[True] = Field(
        description="Author and sign-out time are synthetic."
    )


class ReportNotReported(APIModel):
    """Open case. Clinical history only; no diagnosis and no report body."""

    case_id: str
    status: Literal["none"]
    clinical_history: str | None


CaseReport = Annotated[Report | ReportNotReported, Field(discriminator="status")]
