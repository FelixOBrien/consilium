from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence

import pytest
from pydantic import SecretStr

from consilium.config import Settings  # pragma: allowlist secret
from consilium.embed import (  # pragma: allowlist secret
    CONCHZ_DIM,
    CONCHZ_MAX_TOKENS,
    REPORT_DIM,
    REPORT_MAX_TOKENS,
    ConchzTextEncoding,
    EmbedConfigError,
    EmbeddingSpace,
    EmbedModelError,
    MockTextEncoder,
    ReportTextKind,
    TextEncoders,
    build_text_encoders,
    cosine_similarity,
    report_model_input,
)
from consilium.embed.text import EncodedText, HuggingFaceTextEncoder  # pragma: allowlist secret


class CountingBackend:
    def __init__(self) -> None:
        self.conch: list[list[str]] = []
        self.reports: list[tuple[ReportTextKind, list[str]]] = []

    def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
        batch = list(texts)
        self.conch.append(batch)
        return MockTextEncoder().encode_conchz(batch)

    def encode_report(
        self, texts: Sequence[str], *, kind: ReportTextKind
    ) -> list[EncodedText]:
        batch = list(texts)
        self.reports.append((kind, batch))
        return MockTextEncoder().encode_report(batch, kind=kind)


def _encoders(cache_size: int = 32) -> tuple[TextEncoders, CountingBackend]:
    backend = CountingBackend()
    return build_text_encoders(backend=backend, cache_size=cache_size), backend


def test_query_prefix_is_the_bge_instruction() -> None:
    assert report_model_input("cribriform glands", ReportTextKind.QUERY) == (
        "Represent this sentence for searching relevant passages: cribriform glands"
    )
    assert report_model_input("cribriform glands", ReportTextKind.PASSAGE) == "cribriform glands"


def test_mock_shapes_norms_and_query_passage_split() -> None:
    encoders, _backend = _encoders()
    image = encoders.encode_image_text("cribriform glands")
    query = encoders.encode_report_query("cribriform glands")
    passage = encoders.encode_report_passages(["cribriform glands"])[0]
    assert isinstance(image, ConchzTextEncoding)
    assert image.vector.dim == CONCHZ_DIM == len(image.vector.values)
    assert image.vector.space is EmbeddingSpace.CONCHZ
    assert query.vector.dim == REPORT_DIM == len(query.vector.values)
    assert query.kind is ReportTextKind.QUERY
    assert passage.kind is ReportTextKind.PASSAGE
    assert query.vector.values != passage.vector.values
    assert image.vector.values != tuple(query.vector.values) + tuple(query.vector.values)
    with pytest.raises(TypeError):
        cosine_similarity(image.vector, query.vector)
    again = encoders.encode_image_text("cribriform glands")
    assert again.vector.values == image.vector.values


def test_empty_and_whitespace_text_is_rejected() -> None:
    encoders, backend = _encoders()
    for text in ("", " ", "\n\t"):
        with pytest.raises(ValueError, match="empty"):
            encoders.encode_image_text(text)
        with pytest.raises(ValueError, match="empty"):
            encoders.encode_report_query(text)
        with pytest.raises(ValueError, match="empty"):
            encoders.encode_report_passages([text])
    with pytest.raises(ValueError, match="empty"):
        encoders.encode_image_texts(["glands", " "])
    assert backend.conch == []
    assert backend.reports == []


def test_non_strings_and_empty_batches() -> None:
    encoders, backend = _encoders()
    with pytest.raises(TypeError):
        encoders.encode_image_texts("cribriform glands")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        encoders.encode_report_passages(["ok", 3])  # type: ignore[list-item]
    assert encoders.encode_image_texts([]) == []
    assert encoders.encode_report_queries([]) == []
    assert encoders.encode_report_passages([]) == []
    assert backend.conch == []


def test_truncation_is_reported() -> None:
    encoders, _backend = _encoders()
    short = encoders.encode_image_text(" ".join(["gland"] * 125))
    long = encoders.encode_image_text(" ".join(["gland"] * 126))
    assert short.token_count == CONCHZ_MAX_TOKENS
    assert short.truncated is False
    assert short.truncation_notice() is None
    assert long.truncated is True
    assert long.token_count > CONCHZ_MAX_TOKENS
    notice = long.truncation_notice()
    assert notice is not None
    assert str(CONCHZ_MAX_TOKENS) in notice

    passage = encoders.encode_report_passages([" ".join(["cell"] * 600)])[0]
    assert passage.truncated is True
    assert passage.token_count > REPORT_MAX_TOKENS
    report_notice = passage.truncation_notice()
    assert report_notice is not None
    assert str(REPORT_MAX_TOKENS) in report_notice
    assert encoders.encode_report_query("short note").truncated is False


def test_batch_order_and_partial_cache() -> None:
    encoders, backend = _encoders()
    first = encoders.encode_report_passages(["alpha", "beta", "alpha"])
    assert first[0].vector == first[2].vector
    assert first[0].vector != first[1].vector
    encoders.encode_report_query("alpha")
    backend.reports.clear()
    queries = encoders.encode_report_queries(["alpha", "beta", "alpha"])
    assert queries[0].vector == queries[2].vector
    assert queries[0].kind is ReportTextKind.QUERY
    assert backend.reports == [(ReportTextKind.QUERY, ["beta"])]


def test_query_cache_is_lru_and_passages_are_not_cached() -> None:
    encoders, backend = _encoders(cache_size=2)
    encoders.encode_image_text("a")
    encoders.encode_image_text("b")
    encoders.encode_image_text("c")
    encoders.encode_image_text("c")
    encoders.encode_image_text("a")
    assert backend.conch == [["a"], ["b"], ["c"], ["a"]]

    encoders.encode_report_passages(["same"])
    encoders.encode_report_passages(["same"])
    assert [batch for _kind, batch in backend.reports] == [["same"], ["same"]]


def test_disabled_cache_still_returns_vectors() -> None:
    encoders, backend = _encoders(cache_size=0)
    first = encoders.encode_image_text("a")
    second = encoders.encode_image_text("a")
    assert first.vector == second.vector
    assert backend.conch == [["a"], ["a"]]


def test_warmup_fills_the_query_cache() -> None:
    encoders, backend = _encoders()
    thread = encoders.schedule_warmup()
    assert thread.daemon is True
    assert thread.name == "embed-warmup"
    thread.join(timeout=2)
    assert thread.is_alive() is False
    conch_calls = len(backend.conch)
    report_calls = len(backend.reports)
    encoders.encode_image_text("tissue")
    encoders.encode_report_query("tissue")
    assert len(backend.conch) == conch_calls
    assert len(backend.reports) == report_calls


def test_concurrent_mock_encodes() -> None:
    encoders = build_text_encoders(backend=MockTextEncoder(), cache_size=8)
    errors: list[BaseException] = []

    def run(index: int) -> None:
        try:
            image = encoders.encode_image_text(f"phrase {index % 3}")
            report = encoders.encode_report_query(f"phrase {index % 3}")
            assert len(image.vector.values) == CONCHZ_DIM
            assert len(report.vector.values) == REPORT_DIM
        except BaseException as exc:  # noqa: BLE001 — collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert errors == []


def test_bad_backend_vector_is_rejected() -> None:
    class BadBackend:
        def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
            return [EncodedText(values=(0.0, 1.0), truncated=False, token_count=1)]

        def encode_report(
            self, texts: Sequence[str], *, kind: ReportTextKind
        ) -> list[EncodedText]:
            return [
                EncodedText(
                    values=tuple(0.0 for _ in range(3)),
                    truncated=False,
                    token_count=1,
                )
            ]

    encoders = build_text_encoders(backend=BadBackend())
    with pytest.raises(EmbedModelError, match="768"):
        encoders.encode_image_text("glands")
    with pytest.raises(EmbedModelError, match="384"):
        encoders.encode_report_passages(["glands"])


def test_backend_length_mismatch_is_rejected() -> None:
    class ShortBackend:
        def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
            return []

        def encode_report(
            self, texts: Sequence[str], *, kind: ReportTextKind
        ) -> list[EncodedText]:
            return []

    encoders = build_text_encoders(backend=ShortBackend())
    with pytest.raises(EmbedModelError):
        encoders.encode_image_texts(["one", "two"])


def test_missing_token_fails_before_download() -> None:
    encoder = HuggingFaceTextEncoder(Settings(hf_token=None))
    with pytest.raises(EmbedConfigError, match="HF_TOKEN"):
        encoder.encode_conchz(["glands"])


def test_model_errors_do_not_echo_the_token(caplog: pytest.LogCaptureFixture) -> None:
    token = "hf-secret-token-xyz"

    class Boom(HuggingFaceTextEncoder):
        def _load_conch(self) -> object:
            raise RuntimeError(f"unauthorized {token}")

    encoder = Boom(Settings(hf_token=SecretStr(token)))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(EmbedModelError) as caught:
            encoder.encode_conchz(["glands"])
    assert token not in str(caught.value)
    assert token not in caplog.text
    assert caught.value.__cause__ is None


def test_huggingface_chunks_and_loads_once() -> None:
    class Slow(HuggingFaceTextEncoder):
        def __init__(self) -> None:
            super().__init__(Settings(hf_token=None), chunk_size=2)
            self.loads = 0
            self.batches: list[list[str]] = []
            self.release = threading.Event()

        def _load_conch(self) -> Slow:
            self.loads += 1
            if self.loads == 1:
                assert self.release.wait(timeout=2)
            return self

        def encode(self, texts: Sequence[str]) -> list[EncodedText]:
            batch = list(texts)
            self.batches.append(batch)
            return MockTextEncoder().encode_conchz(batch)

    encoder = Slow()
    errors: list[BaseException] = []

    def call() -> None:
        try:
            encoder.encode_conchz(["one", "two", "three"])
        except BaseException as exc:  # noqa: BLE001 — collected for the assertion
            errors.append(exc)

    first = threading.Thread(target=call)
    second = threading.Thread(target=call)
    first.start()
    for _ in range(50):
        if encoder.loads == 1:
            break
        time.sleep(0.01)
    assert encoder.loads == 1
    second.start()
    time.sleep(0.05)
    assert encoder.loads == 1
    encoder.release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert errors == []
    assert encoder.loads == 1
    assert encoder.batches == [
        ["one", "two"],
        ["three"],
        ["one", "two"],
        ["three"],
    ]


def test_cache_and_chunk_size_must_be_valid() -> None:
    with pytest.raises(ValueError):
        TextEncoders(MockTextEncoder(), cache_size=-1)
    with pytest.raises(ValueError):
        HuggingFaceTextEncoder(chunk_size=0)
