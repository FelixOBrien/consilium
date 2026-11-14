from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from consilium.embed import (  # pragma: allowlist secret
    CONCHZ_DIM,
    REPORT_DIM,
    ConchzEmbedding,
    ConchZVector,
    EmbeddingSpace,
    ImageTextVector,
    ReportEmbedding,
    ReportVector,
    cosine_similarity,
    embedding_dim,
)


def _unit(count: int, index: int = 0) -> tuple[float, ...]:
    values = [0.0] * count
    values[index] = 1.0
    return tuple(values)


def _spread(count: int) -> tuple[float, ...]:
    raw = [float((index * 17) % 100 + 1) for index in range(count)]
    norm = math.sqrt(sum(value * value for value in raw))
    return tuple(value / norm for value in raw)


def test_aliases_are_the_space_types() -> None:
    assert ConchZVector is ConchzEmbedding
    assert ImageTextVector is ConchzEmbedding
    assert ReportVector is ReportEmbedding
    assert embedding_dim(EmbeddingSpace.CONCHZ) == CONCHZ_DIM
    assert embedding_dim(EmbeddingSpace.REPORT) == REPORT_DIM


def test_unit_vectors_round_trip_float32() -> None:
    vector = ConchzEmbedding(values=_spread(CONCHZ_DIM))
    assert vector.to_float32() == vector.values
    assert abs(math.sqrt(sum(value * value for value in vector.values)) - 1.0) < 1e-9


def test_halfvec_round_trip_stays_in_space() -> None:
    original = ConchzEmbedding(values=_spread(CONCHZ_DIM))
    restored = ConchzEmbedding.from_halfvec(original.to_float16())
    assert restored.space is EmbeddingSpace.CONCHZ
    assert len(restored.to_float16()) == CONCHZ_DIM
    assert cosine_similarity(original, restored) > 0.999

    report = ReportEmbedding(values=_spread(REPORT_DIM))
    report_restored = ReportEmbedding.from_halfvec(report.to_float16())
    assert cosine_similarity(report, report_restored) > 0.999


def test_one_hot_halfvec_is_exact() -> None:
    original = ReportEmbedding(values=_unit(REPORT_DIM))
    assert original.to_float16() == original.values
    assert ReportEmbedding.from_halfvec(original.to_float16()) == original


def test_non_unit_and_non_finite_vectors_are_rejected() -> None:
    skewed = list(_unit(CONCHZ_DIM))
    skewed[0] = 2.0
    with pytest.raises(ValidationError):
        ConchzEmbedding(values=tuple(skewed))
    skewed[1] = float("nan")
    with pytest.raises(ValidationError):
        ConchzEmbedding(values=tuple(skewed))
    skewed[1] = float("inf")
    with pytest.raises(ValidationError):
        ConchzEmbedding(values=tuple(skewed))
    with pytest.raises(ValueError):
        ConchzEmbedding.from_halfvec(_unit(REPORT_DIM))
    with pytest.raises(ValueError):
        ReportEmbedding.from_halfvec(tuple(0.0 for _ in range(REPORT_DIM)))


def test_cosine_rejects_the_other_space() -> None:
    conchz = ConchzEmbedding(values=_unit(CONCHZ_DIM))
    report = ReportEmbedding(values=_unit(REPORT_DIM))
    orthogonal = ConchzEmbedding(values=_unit(CONCHZ_DIM, index=1))
    assert conchz.cosine(conchz) == 1.0
    assert cosine_similarity(conchz, orthogonal) == 0.0
    with pytest.raises(TypeError):
        cosine_similarity(conchz, report)
    with pytest.raises(TypeError):
        conchz.cosine(report)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        report.cosine(conchz)  # type: ignore[arg-type]


def test_unknown_space_is_rejected() -> None:
    with pytest.raises(TypeError):
        embedding_dim("conchz")  # type: ignore[arg-type]
