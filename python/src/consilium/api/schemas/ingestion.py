from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from consilium.api.schemas.common import APIModel  # pragma: allowlist secret
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret


class StageRecord(APIModel):
    stage: Literal[
        "download",
        "segment",
        "embed",
        "project",
        "thumbnails",
        "reports",
        "load",
        "index",
    ]
    started_at: datetime
    finished_at: datetime | None
    detail: str | None = None


class IngestionCounts(APIModel):
    patches: int | None = Field(default=None, ge=0)
    chunks: int | None = Field(default=None, ge=0)


class IngestionJob(APIModel):
    id: UUID
    dataset: str
    slide_path: str
    case_id: str | None
    slide_id: str | None
    requested_by: PathologistRef | None
    status: Literal["queued", "running", "done", "failed"]
    stage: Literal[
        "download",
        "segment",
        "embed",
        "project",
        "thumbnails",
        "reports",
        "load",
        "index",
    ] | None
    stage_history: list[StageRecord]
    counts: IngestionCounts | None
    error: str | None
    attempts: int = Field(ge=0)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class IngestionJobCreate(APIModel):
    dataset: str = Field(min_length=1)
    slide_path: str = Field(min_length=1)
