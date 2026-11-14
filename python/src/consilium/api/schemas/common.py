from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    """Request and response models. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class Specialty(StrEnum):
    BREAST = "breast"
    THORAX = "thorax"
    COLORECTAL = "colorectal"
    GASTROINTESTINAL = "gastrointestinal"
    HEMATOLOGIC = "hematologic"
    SKIN = "skin"


class CaseStatus(StrEnum):
    OPEN = "open"
    SIGNED_OUT = "signed_out"


class SlideStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Sex(StrEnum):
    FEMALE = "F"
    MALE = "M"


class ReportSection(StrEnum):
    CLINICAL_HISTORY = "clinical_history"
    GROSS_DESCRIPTION = "gross_description"
    MICROSCOPIC_DESCRIPTION = "microscopic_description"
    CONCLUSION = "conclusion"
    ADDITIONAL_INFO = "additional_info"
    BODY = "body"


class FieldError(APIModel):
    loc: list[str]
    message: str


class ErrorBody(APIModel):
    code: str
    message: str
    fields: list[FieldError] | None = None


class ErrorEnvelope(APIModel):
    """Standard error body for 4xx responses."""

    error: ErrorBody


class Page(APIModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Region(APIModel):
    """Level-0 pixel rectangle, including the slide it belongs to."""

    slide_id: str = Field(min_length=1)
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
