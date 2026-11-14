from __future__ import annotations

from pydantic import Field

from consilium.api.schemas.common import APIModel  # pragma: allowlist secret


class PatchRef(APIModel):
    id: int
    slide_id: str
    case_id: str
    x: int
    y: int
    size: int = Field(gt=0)
    thumbnail_url: str
