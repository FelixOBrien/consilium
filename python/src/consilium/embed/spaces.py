from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

# Two embedding spaces. Never compare a vector from one with a vector from the other.
CONCHZ_DIM = 768
REPORT_DIM = 384


class EmbeddingSpace(StrEnum):
    CONCHZ = "conchz"
    REPORT = "report"


class ConchzEmbedding(BaseModel):
    """768-d CONCH-Z vector for patches, slides, and image-query text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    space: Literal[EmbeddingSpace.CONCHZ] = EmbeddingSpace.CONCHZ
    dim: Literal[768] = CONCHZ_DIM
    values: tuple[float, ...]

    @model_validator(mode="after")
    def check_length(self) -> Self:
        if len(self.values) != CONCHZ_DIM:
            raise ValueError(f"conchz embeddings have {CONCHZ_DIM} dimensions")
        return self


class ReportEmbedding(BaseModel):
    """384-d report-space vector for report chunks and report-query text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    space: Literal[EmbeddingSpace.REPORT] = EmbeddingSpace.REPORT
    dim: Literal[384] = REPORT_DIM
    values: tuple[float, ...]

    @model_validator(mode="after")
    def check_length(self) -> Self:
        if len(self.values) != REPORT_DIM:
            raise ValueError(f"report embeddings have {REPORT_DIM} dimensions")
        return self


def embedding_dim(space: EmbeddingSpace) -> int:
    if space is EmbeddingSpace.CONCHZ:
        return CONCHZ_DIM
    if space is EmbeddingSpace.REPORT:
        return REPORT_DIM
    raise TypeError(f"unknown embedding space: {space}")
