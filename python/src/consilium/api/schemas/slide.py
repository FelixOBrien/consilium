from __future__ import annotations

from pydantic import Field

from consilium.api.schemas.common import APIModel, SlideStatus  # pragma: allowlist secret


class SlideSummary(APIModel):
    id: str
    ordinal: int = Field(ge=1)
    stain: str
    magnification: float = Field(gt=0)
    status: SlideStatus
    thumbnail_url: str


class SlideDetail(SlideSummary):
    case_id: str
    mpp: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    patch_size: int = Field(gt=0)
    patch_count: int = Field(ge=0)
    dzi_url: str
