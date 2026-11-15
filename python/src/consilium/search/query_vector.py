"""Shared CONCH-Z query vectors for patch search and slide heatmaps.

Q1 is a stored patch embedding. Q2 is the L2-normalised mean of the embeddings
of patches that intersect a level-0 rectangle (architecture D10). Search and
`POST /api/slides/{id}/heatmap` both call these functions, so they always
score with the same 768-d vector. Report embeddings are never read here.

Missing patches and empty regions raise the same `SearchError` values search
returns: 404 "Patch not found." and 422 "Region covers no tissue patches."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pgvector import HalfVector
from psycopg import Connection

from consilium.api.schemas.common import Region  # pragma: allowlist secret
from consilium.embed.spaces import CONCHZ_DIM, ConchzEmbedding  # pragma: allowlist secret
from consilium.search.common import SearchError, fetchall, fetchone  # pragma: allowlist secret

NO_TISSUE = "Region covers no tissue patches."


@dataclass(frozen=True)
class SeedPatch:
    """A patch that formed the query. Coordinates only — never the embedding."""

    id: int
    x: int
    y: int
    size: int


@dataclass(frozen=True)
class TissueQuery:
    """One 768-d CONCH-Z vector and the patches it was built from."""

    vector: ConchzEmbedding
    slide_id: str
    case_id: str
    seeds: tuple[SeedPatch, ...]


def patch_query_vector(conn: Connection, patch_id: int) -> TissueQuery:
    """Q1. The stored embedding of one patch, re-read as a unit vector."""
    row = fetchone(
        conn,
        """
        SELECT id, slide_id, case_id, x, y, size, embedding
        FROM patch
        WHERE id = %s
        """,
        (patch_id,),
    )
    if row is None:
        raise SearchError(404, "not_found", "Patch not found.")
    seed = _seed(row)
    return TissueQuery(
        vector=stored_conchz(row["embedding"]),
        slide_id=str(row["slide_id"]),
        case_id=str(row["case_id"]),
        seeds=(seed,),
    )


def region_query_vector(conn: Connection, region: Region) -> TissueQuery:
    """Q2. L2-normalised mean of every patch that intersects `region`."""
    rows = fetchall(
        conn,
        """
        SELECT id, case_id, x, y, size, embedding
        FROM patch
        WHERE slide_id = %(slide_id)s
          AND x < %(right)s
          AND x + size > %(x)s
          AND y < %(bottom)s
          AND y + size > %(y)s
        ORDER BY id
        """,
        {
            "slide_id": region.slide_id,
            "x": region.x,
            "y": region.y,
            "right": region.x + region.width,
            "bottom": region.y + region.height,
        },
    )
    if not rows:
        raise SearchError(422, "validation_error", NO_TISSUE)
    vectors = [_vector_floats(row["embedding"]) for row in rows]
    seeds = tuple(_seed(row) for row in rows)
    return TissueQuery(
        vector=mean_conchz(vectors),
        slide_id=region.slide_id,
        case_id=str(rows[0]["case_id"]),
        seeds=seeds,
    )


def to_halfvec(embedding: ConchzEmbedding) -> HalfVector:
    """Float16 components, the form pgvector stores and compares."""
    if embedding.dim != CONCHZ_DIM:
        raise SearchError(500, "error", "CONCH-Z query vector has the wrong dimension.")
    # pgvector accepts a list, not the tuple `to_float16` returns.
    return HalfVector(list(embedding.to_float16()))


def mean_conchz(vectors: list[list[float]]) -> ConchzEmbedding:
    """Arithmetic mean, then L2-normalise back onto the unit sphere."""
    if not vectors:
        raise SearchError(422, "validation_error", NO_TISSUE)
    total = [0.0] * CONCHZ_DIM
    for vector in vectors:
        if len(vector) != CONCHZ_DIM:
            raise SearchError(500, "error", "Patch embedding has an unexpected dimension.")
        for index, component in enumerate(vector):
            total[index] += component
    scale = 1.0 / len(vectors)
    mean = [component * scale for component in total]
    norm = sum(component * component for component in mean) ** 0.5
    if norm == 0.0:
        raise SearchError(422, "validation_error", NO_TISSUE)
    try:
        return ConchzEmbedding(values=tuple(component / norm for component in mean))
    except ValueError as exc:
        raise SearchError(422, "validation_error", NO_TISSUE) from exc


def _seed(row: dict[str, Any]) -> SeedPatch:
    return SeedPatch(
        id=int(row["id"]),
        x=int(row["x"]),
        y=int(row["y"]),
        size=int(row["size"]),
    )


def stored_conchz(value: object) -> ConchzEmbedding:
    try:
        floats = _vector_floats(value)
    except (TypeError, ValueError) as exc:
        raise SearchError(500, "error", "Stored tissue vector is unreadable.") from exc
    try:
        return ConchzEmbedding.from_halfvec(floats)
    except ValueError as exc:
        raise SearchError(500, "error", "Stored tissue vector is not a unit embedding.") from exc


def _vector_floats(value: object) -> list[float]:
    """Read a pgvector value, a text literal, or a sequence of components."""
    to_list = getattr(value, "to_list", None)
    if callable(to_list):
        raw = to_list()
    elif isinstance(value, str):
        inner = value.strip()
        if inner.startswith("[") and inner.endswith("]"):
            inner = inner[1:-1]
        raw = [] if inner == "" else inner.split(",")
    else:
        raw = list(value)  # type: ignore[arg-type]
    return [float(item) for item in raw]
