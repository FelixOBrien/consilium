from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from consilium.api.schemas.case import CaseSummary  # pragma: allowlist secret
from consilium.api.schemas.common import APIModel, Region, Specialty  # pragma: allowlist secret


class MessageAttachments(APIModel):
    region: Region | None = None
    case_ids: list[str] | None = None


class Citation(APIModel):
    case_id: str
    slide_id: str | None = None
    patch_id: int | None = None
    quote: str | None = None
    case: CaseSummary


class PathologistRank(APIModel):
    """Counts come from retrieval results, not from model prose."""

    pathologist_id: str
    name: str
    specialty: Specialty
    case_count: int = Field(ge=0)
    case_ids: list[str]

    @model_validator(mode="after")
    def count_matches_ids(self) -> Self:
        if self.case_count != len(self.case_ids):
            raise ValueError("case_count must equal the number of case_ids")
        return self


class ToolTraceStep(APIModel):
    """Tool name, summary and duration. Tool inputs are never sent."""

    tool: str
    summary: str
    duration_ms: int = Field(ge=0)


class ConsultMessage(APIModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    attachments: MessageAttachments | None
    citations: list[Citation] | None
    ranking: list[PathologistRank] | None
    tool_trace: list[ToolTraceStep] | None
    status: Literal["complete", "streaming", "error"]
    created_at: datetime


class ConsultThread(APIModel):
    id: UUID
    case_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[ConsultMessage]


class ConsultThreadCreate(APIModel):
    new: bool = False


class ConsultMessageCreate(APIModel):
    content: str = Field(min_length=1)
    attachments: MessageAttachments | None = None


class StepEvent(APIModel):
    type: Literal["step"] = "step"
    tool: str
    summary: str
    duration_ms: int = Field(ge=0)


class TextEvent(APIModel):
    type: Literal["text"] = "text"
    content: str


class CitationsEvent(APIModel):
    type: Literal["citations"] = "citations"
    citations: list[Citation]


class RankingEvent(APIModel):
    type: Literal["ranking"] = "ranking"
    ranking: list[PathologistRank]


class DoneEvent(APIModel):
    type: Literal["done"] = "done"
    message: ConsultMessage


class ErrorEvent(APIModel):
    type: Literal["error"] = "error"
    message: str


ConsultStreamEvent = Annotated[
    StepEvent | TextEvent | CitationsEvent | RankingEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]
