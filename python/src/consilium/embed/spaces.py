"""Two embedding spaces. A vector from one is never compared with a vector from the other."""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Self, overload

from pydantic import BaseModel, ConfigDict, model_validator

# Stored widths. `conchz` is pgvector `halfvec(768)`; `report` is `vector(384)`.
CONCHZ_DIM = 768
REPORT_DIM = 384

# Float32 encoders land well inside 1e-3. Float16 rounding of a unit vector can
# drift by about 1e-2, so halfvec reads use the wider tolerance and are
# re-normalised back to float32.
UNIT_NORM_ATOL = 1e-3
HALFVEC_NORM_ATOL = 2e-2


class EmbeddingSpace(StrEnum):
    CONCHZ = "conchz"
    REPORT = "report"


def _l2_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def _as_float16(value: float) -> float:
    """Round one component to IEEE binary16 and back to float64."""
    return struct.unpack("<e", struct.pack("<e", value))[0]


def _validate_unit(values: tuple[float, ...], dim: int, space: str) -> tuple[float, ...]:
    if len(values) != dim:
        raise ValueError(f"{space} embeddings have {dim} dimensions")
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{space} embeddings must be finite")
    norm = _l2_norm(values)
    if abs(norm - 1.0) > UNIT_NORM_ATOL:
        raise ValueError(f"{space} embeddings must be L2-normalised (norm {norm:.6f})")
    return values


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _from_halfvec(values: Sequence[float], dim: int, space: str) -> tuple[float, ...]:
    rounded = tuple(_as_float16(float(value)) for value in values)
    if len(rounded) != dim:
        raise ValueError(f"{space} embeddings have {dim} dimensions")
    if any(not math.isfinite(value) for value in rounded):
        raise ValueError(f"{space} embeddings must be finite")
    norm = _l2_norm(rounded)
    if norm == 0.0 or abs(norm - 1.0) > HALFVEC_NORM_ATOL:
        raise ValueError(f"{space} halfvec must be L2-normalised (norm {norm:.6f})")
    return tuple(value / norm for value in rounded)


class ConchzEmbedding(BaseModel):
    """768-d L2-normalised vector in the CONCH-Z image-text space.

    Patches, slides, concepts and image-query text share this space. It is not
    interchangeable with `ReportEmbedding`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    space: Literal[EmbeddingSpace.CONCHZ] = EmbeddingSpace.CONCHZ
    dim: Literal[768] = CONCHZ_DIM
    values: tuple[float, ...]

    @model_validator(mode="after")
    def check_unit(self) -> Self:
        _validate_unit(self.values, CONCHZ_DIM, "conchz")
        return self

    @classmethod
    def from_halfvec(cls, values: Sequence[float]) -> Self:
        """Read a `halfvec(768)` value and restore a float32 unit vector."""
        return cls(values=_from_halfvec(values, CONCHZ_DIM, "conchz"))

    def to_float32(self) -> tuple[float, ...]:
        return self.values

    def to_float16(self) -> tuple[float, ...]:
        """Components rounded to float16, the form stored in `halfvec(768)`."""
        return tuple(_as_float16(value) for value in self.values)

    def cosine(self, other: Self) -> float:
        if type(other) is not ConchzEmbedding:
            raise TypeError(
                f"cannot compare ConchzEmbedding with {type(other).__name__}"
            )
        return _dot(self.values, other.values)


class ReportEmbedding(BaseModel):
    """384-d L2-normalised vector in the report-text space.

    Report chunks and report-query text share this space. It is not
    interchangeable with `ConchzEmbedding`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    space: Literal[EmbeddingSpace.REPORT] = EmbeddingSpace.REPORT
    dim: Literal[384] = REPORT_DIM
    values: tuple[float, ...]

    @model_validator(mode="after")
    def check_unit(self) -> Self:
        _validate_unit(self.values, REPORT_DIM, "report")
        return self

    @classmethod
    def from_halfvec(cls, values: Sequence[float]) -> Self:
        """Read a float16 report vector and restore a float32 unit vector.

        Report chunks are stored as `vector(384)` (float32). This constructor
        accepts a float16 rounding of that vector so the two dtypes stay explicit.
        """
        return cls(values=_from_halfvec(values, REPORT_DIM, "report"))

    def to_float32(self) -> tuple[float, ...]:
        return self.values

    def to_float16(self) -> tuple[float, ...]:
        return tuple(_as_float16(value) for value in self.values)

    def cosine(self, other: Self) -> float:
        if type(other) is not ReportEmbedding:
            raise TypeError(
                f"cannot compare ReportEmbedding with {type(other).__name__}"
            )
        return _dot(self.values, other.values)


# Names callers use when they want the vector rather than the encoder result.
ConchZVector = ConchzEmbedding
ImageTextVector = ConchzEmbedding
ReportVector = ReportEmbedding


def embedding_dim(space: EmbeddingSpace) -> int:
    if space is EmbeddingSpace.CONCHZ:
        return CONCHZ_DIM
    if space is EmbeddingSpace.REPORT:
        return REPORT_DIM
    raise TypeError(f"unknown embedding space: {space}")


@overload
def cosine_similarity(left: ConchzEmbedding, right: ConchzEmbedding) -> float: ...


@overload
def cosine_similarity(left: ReportEmbedding, right: ReportEmbedding) -> float: ...


def cosine_similarity(
    left: ConchzEmbedding | ReportEmbedding,
    right: ConchzEmbedding | ReportEmbedding,
) -> float:
    """Cosine of two vectors from the same space.

    Mixing `conchz` and `report` is a type error for the checker and a
    `TypeError` at runtime.
    """
    if type(left) is not type(right):
        raise TypeError(
            "cannot compare embedding spaces "
            f"{type(left).__name__} ({left.space}) and {type(right).__name__} ({right.space})"
        )
    return _dot(left.values, right.values)
