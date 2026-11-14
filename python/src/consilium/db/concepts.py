"""Concept list and on-demand slide heatmaps.

Heatmaps are one exact scan of `patch` filtered by `slide_id`. The btree behind
that filter is the unique index `patch_slide_position_unique` on
`(slide_id, x, y)` (patch.md). The statements have no `ORDER BY embedding <=>`
and no `LIMIT`, so they do not use the HNSW index `patch_embedding_hnsw`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pgvector import HalfVector
from psycopg import Connection

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.concept import (  # pragma: allowlist secret
    SIMILARITY_NOTICE,
    Concept,
    HeatmapPatchScore,
    HeatmapRequest,
    HeatmapResponse,
)
from consilium.embed.text import (  # pragma: allowlist secret
    CONCHZ_MAX_TOKENS,
    ConchzTextEncoding,
    EmbedError,
    TextEncoders,
)

# Cosine similarity is `1 - cosine_distance`. pgvector's `<=>` is that distance.
_POSITIVE_SIMILARITY = "(1 - (embedding <=> %s::halfvec(768)))"

POSITIVE_HEATMAP_SQL = f"""
select x, y, size,
       {_POSITIVE_SIMILARITY} as raw_score
from patch
where slide_id = %s
"""

CONTRAST_HEATMAP_SQL = f"""
select x, y, size,
       {_POSITIVE_SIMILARITY} - (1 - (embedding <=> %s::halfvec(768))) as raw_score
from patch
where slide_id = %s
"""

_LIST_SQL = """
select id, label, prompt, specialty
from concept
where (
    %s::text is null
    or specialty is null
    or specialty = %s
)
order by ordinal asc, id asc
"""

_CONCEPT_SQL = """
select id, prompt, embedding, negative_embedding
from concept
where id = %s
"""

_SLIDE_SQL = "select 1 from slide where id = %s"


@dataclass(frozen=True)
class StoredConcept:
    """Embeddings stay on the server. Callers never put them on a response."""

    id: str
    prompt: str
    embedding: HalfVector | None
    negative_embedding: HalfVector | None


def concepts_for(conn: Connection, specialty: str | None) -> list[Concept]:
    """Concepts for one specialty plus general ones, or every concept.

    `specialty is None` returns the full list. A value returns rows whose
    specialty matches plus rows with a null specialty (general concepts).
    Display order is `ordinal`, then `id`. Embeddings are not selected.
    """
    rows = conn.execute(_LIST_SQL, (specialty, specialty)).fetchall()
    return [
        Concept(id=row[0], label=row[1], prompt=row[2], specialty=row[3])
        for row in rows
    ]


def heatmap_for(
    conn: Connection,
    encoders: TextEncoders,
    slide_id: str,
    body: HeatmapRequest,
) -> HeatmapResponse:
    """Score every patch on one slide and min-max normalise to 0–1.

    A `concept_id` reads the stored `conchz` embedding and does not encode the
    positive phrase. `negative_text` replaces a stored negative embedding and
    is the only text encoded in that case. Free `text` is encoded with the
    CONCH-Z text tower, along with `negative_text` when it is present.
    """
    if conn.execute(_SLIDE_SQL, (slide_id,)).fetchone() is None:
        fail(404, "not_found", "Slide not found.")

    truncated = False
    concept_id: str | None = None
    negative: HalfVector | None = None

    if body.concept_id is not None:
        concept = _load_concept(conn, body.concept_id)
        if concept is None:
            fail(404, "not_found", "Unknown concept.")
        if concept.embedding is None:
            fail(422, "validation_error", "Concept has no stored embedding.")
        positive = concept.embedding
        phrase = concept.prompt
        concept_id = concept.id
        if body.negative_text is not None:
            encoded = _encode(encoders, [body.negative_text])
            negative = _half(encoded[0].vector.to_float16())
            truncated = encoded[0].truncated
        else:
            negative = concept.negative_embedding
    else:
        phrases = [body.text or ""]
        if body.negative_text is not None:
            phrases.append(body.negative_text)
        encoded = _encode(encoders, phrases)
        positive = _half(encoded[0].vector.to_float16())
        phrase = body.text or ""
        truncated = encoded[0].truncated
        if body.negative_text is not None:
            negative = _half(encoded[1].vector.to_float16())
            truncated = truncated or encoded[1].truncated

    patches = _score_slide(conn, slide_id, positive, negative)
    top = sorted(patches, key=lambda item: (-item.score, item.y, item.x))[:10]
    return HeatmapResponse(
        text=phrase,
        concept_id=concept_id,
        negative_text=body.negative_text,
        notice=_notice(truncated),
        truncated=truncated,
        patches=patches,
        top=top,
    )


def normalise_scores(raw: Sequence[float]) -> list[float]:
    """Min-max to ``[0.0, 1.0]``. Empty and flat slides stay defined.

    A slide with no patches returns an empty list. A slide whose raw scores
    are all equal returns zeros, so a zero span never divides.
    """
    if not raw:
        return []
    lo = min(raw)
    hi = max(raw)
    if hi == lo:
        return [0.0 for _ in raw]
    span = hi - lo
    scaled: list[float] = []
    for value in raw:
        if value == lo:
            scaled.append(0.0)
        elif value == hi:
            scaled.append(1.0)
        else:
            score = (value - lo) / span
            if score <= 0.0:
                scaled.append(0.0)
            elif score >= 1.0:
                scaled.append(1.0)
            else:
                scaled.append(score)
    return scaled


def _score_slide(
    conn: Connection,
    slide_id: str,
    positive: HalfVector,
    negative: HalfVector | None,
) -> list[HeatmapPatchScore]:
    if negative is None:
        rows = conn.execute(POSITIVE_HEATMAP_SQL, (positive, slide_id)).fetchall()
    else:
        rows = conn.execute(
            CONTRAST_HEATMAP_SQL,
            (positive, negative, slide_id),
        ).fetchall()
    scores = normalise_scores([float(row[3]) for row in rows])
    patches = [
        HeatmapPatchScore(x=int(row[0]), y=int(row[1]), size=int(row[2]), score=score)
        for row, score in zip(rows, scores, strict=True)
    ]
    patches.sort(key=lambda item: (item.y, item.x))
    return patches


def _load_concept(conn: Connection, concept_id: str) -> StoredConcept | None:
    row = conn.execute(_CONCEPT_SQL, (concept_id,)).fetchone()
    if row is None:
        return None
    return StoredConcept(
        id=row[0],
        prompt=row[1],
        embedding=None if row[2] is None else _half(row[2]),
        negative_embedding=None if row[3] is None else _half(row[3]),
    )


def _encode(encoders: TextEncoders, phrases: Sequence[str]) -> list[ConchzTextEncoding]:
    try:
        return encoders.encode_image_texts(phrases)
    except EmbedError:
        fail(500, "error", "Text encoder failed.")


def _notice(truncated: bool) -> str:
    if not truncated:
        return SIMILARITY_NOTICE
    return (
        f"{SIMILARITY_NOTICE} "
        f"Text was truncated to {CONCHZ_MAX_TOKENS} tokens (CONCH-Z context limit)."
    )


def _half(values: HalfVector | Sequence[float]) -> HalfVector:
    if isinstance(values, HalfVector):
        return values
    return HalfVector([float(value) for value in values])
