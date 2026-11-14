from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from consilium.api.schemas.common import APIModel, Specialty  # pragma: allowlist secret


class PathologistRef(APIModel):
    """Pathologist embedded in cases, reports and annotations."""

    id: str
    name: str
    primary_specialty: Specialty
    is_synthetic: bool = Field(description="Roster identities are synthetic, not real people.")

    @field_validator("is_synthetic")
    @classmethod
    def must_be_synthetic(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("pathologist identities are synthetic")
        return value


class Pathologist(PathologistRef):
    role_title: str
    secondary_specialties: list[Specialty]
    is_demo_user: bool
    created_at: datetime
