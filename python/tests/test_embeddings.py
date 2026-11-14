from __future__ import annotations

import pytest
from pydantic import ValidationError

from consilium.embed import (  # pragma: allowlist secret
    CONCHZ_DIM,
    REPORT_DIM,
    ConchzEmbedding,
    EmbeddingSpace,
    ReportEmbedding,
    embedding_dim,
)


def _zeros(count: int) -> tuple[float, ...]:
    return tuple(0.0 for _ in range(count))


def _unit(count: int) -> tuple[float, ...]:
    return (1.0,) + tuple(0.0 for _ in range(count - 1))


def test_spaces_have_distinct_dimensions() -> None:
    assert embedding_dim(EmbeddingSpace.CONCHZ) == CONCHZ_DIM == 768
    assert embedding_dim(EmbeddingSpace.REPORT) == REPORT_DIM == 384
    assert EmbeddingSpace.CONCHZ != EmbeddingSpace.REPORT


def test_embeddings_accept_their_own_space() -> None:
    conchz = ConchzEmbedding(values=_unit(CONCHZ_DIM))
    report = ReportEmbedding(values=_unit(REPORT_DIM))
    assert conchz.space is EmbeddingSpace.CONCHZ
    assert report.space is EmbeddingSpace.REPORT
    assert conchz.dim != report.dim
    assert type(conchz) is not type(report)


def test_conchz_rejects_report_sized_vector() -> None:
    with pytest.raises(ValidationError):
        ConchzEmbedding(values=_zeros(REPORT_DIM))


def test_report_rejects_conchz_sized_vector() -> None:
    with pytest.raises(ValidationError):
        ReportEmbedding(values=_zeros(CONCHZ_DIM))


def test_space_label_cannot_be_swapped() -> None:
    with pytest.raises(ValidationError):
        ConchzEmbedding(space="report", values=_unit(CONCHZ_DIM))
    with pytest.raises(ValidationError):
        ReportEmbedding(space="conchz", values=_unit(REPORT_DIM))
