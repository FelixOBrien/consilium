"""CPU text encoders for the two embedding spaces.

The default backend loads weights on first use. Tests pass `MockTextEncoder`
(or any `TextEncoderBackend`) so the suite never downloads gated weights.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from consilium.config import Settings, get_settings  # pragma: allowlist secret
from consilium.embed.spaces import (  # pragma: allowlist secret
    CONCHZ_DIM,
    REPORT_DIM,
    ConchzEmbedding,
    ReportEmbedding,
)

# CONCH-Z tokenizer max length is context_length - 1 (the last slot is the CLS
# token). The model card calls this a 127-token prompt limit.
CONCHZ_MAX_TOKENS = 127
# BAAI/bge-small-en-v1.5 `model_max_length`.
REPORT_MAX_TOKENS = 512
# Model card query prefix, including the trailing space. Passages do not use it.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
DEFAULT_QUERY_CACHE_SIZE = 256


class EmbedError(Exception):
    """Base error for text encoding."""


class EmbedConfigError(EmbedError):
    """Raised when settings cannot load a gated model."""


class EmbedDependencyError(EmbedError):
    """Raised when the CPU encoder libraries are not installed."""


class EmbedModelError(EmbedError):
    """Raised when a loaded model fails or returns an unusable vector."""


class ReportTextKind(StrEnum):
    QUERY = "query"
    PASSAGE = "passage"


def report_model_input(text: str, kind: ReportTextKind) -> str:
    """Text the report encoder actually embeds.

    Queries take the bge instruction prefix. Passages (report chunks) do not.
    """
    if kind is ReportTextKind.QUERY:
        return BGE_QUERY_INSTRUCTION + text
    return text


@dataclass(frozen=True)
class EncodedText:
    """One backend result, before it is wrapped in a space-specific type."""

    values: tuple[float, ...]
    truncated: bool
    token_count: int


class ConchzTextEncoding(BaseModel):
    """A CONCH-Z text encoding. `truncated` tells the caller the 127-token cap applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: ConchzEmbedding
    truncated: bool
    token_count: int

    def truncation_notice(self) -> str | None:
        if not self.truncated:
            return None
        return (
            f"Text was truncated to {CONCHZ_MAX_TOKENS} tokens (CONCH-Z context limit)."
        )


class ReportTextEncoding(BaseModel):
    """A report-space encoding of a query or a passage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: ReportEmbedding
    truncated: bool
    token_count: int
    kind: ReportTextKind

    def truncation_notice(self) -> str | None:
        if not self.truncated:
            return None
        return (
            f"Text was truncated to {REPORT_MAX_TOKENS} tokens (bge-small context limit)."
        )


class TextEncoderBackend(Protocol):
    def encode_conchz(self, texts: Sequence[str]) -> Sequence[EncodedText]: ...

    def encode_report(
        self, texts: Sequence[str], *, kind: ReportTextKind
    ) -> Sequence[EncodedText]: ...


def _unit_vector(key: str, dim: int) -> tuple[float, ...]:
    raw: list[float] = []
    counter = 0
    while len(raw) < dim:
        digest = hashlib.sha256(f"{key}\0{counter}".encode()).digest()
        counter += 1
        for offset in range(0, len(digest), 4):
            chunk = digest[offset : offset + 4]
            if len(chunk) < 4:
                break
            raw.append(int.from_bytes(chunk, "little") / 4294967295 * 2 - 1)
    values = raw[:dim]
    norm = math.sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values)


def _mock_tokens(text: str) -> int:
    """Whitespace pieces plus two special tokens, a stand-in for the real tokenizer."""
    return len(text.split()) + 2


class MockTextEncoder:
    """Deterministic encoder for tests and offline runs. No weights and no network."""

    def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
        encoded: list[EncodedText] = []
        for text in texts:
            count = _mock_tokens(text)
            encoded.append(
                EncodedText(
                    values=_unit_vector(f"conchz\0{text}", CONCHZ_DIM),
                    truncated=count > CONCHZ_MAX_TOKENS,
                    token_count=count,
                )
            )
        return encoded

    def encode_report(
        self, texts: Sequence[str], *, kind: ReportTextKind
    ) -> list[EncodedText]:
        encoded: list[EncodedText] = []
        for text in texts:
            model_text = report_model_input(text, kind)
            count = _mock_tokens(model_text)
            encoded.append(
                EncodedText(
                    values=_unit_vector(f"report\0{kind.value}\0{model_text}", REPORT_DIM),
                    truncated=count > REPORT_MAX_TOKENS,
                    token_count=count,
                )
            )
        return encoded


def require_hf_token(settings: Settings) -> str:
    """Return the gated-download token without logging it."""
    secret = settings.hf_token
    if secret is None or secret.get_secret_value().strip() == "":
        raise EmbedConfigError(
            "HF_TOKEN is not set. CONCH-Z weights are gated and were not downloaded."
        )
    return secret.get_secret_value()


def scrub_secret(message: str, secret: str | None) -> str:
    if secret and secret in message:
        return message.replace(secret, "***")
    return message


class HuggingFaceTextEncoder:
    """Lazy, thread-safe CPU encoders for CONCH-Z text and bge-small.

    Weights load on the first encode of that space. CONCH-Z loads the text tower
    only; the vision tower is not needed for query-time text.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        chunk_size: int = 8,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        self._settings = settings if settings is not None else get_settings()
        self._chunk_size = chunk_size
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._conch_model: object | None = None
        self._bge_model: object | None = None

    def encode_conchz(self, texts: Sequence[str]) -> list[EncodedText]:
        try:
            model = self._conch()
            with self._infer_lock:
                return self._run_chunks(model, texts)
        except EmbedError:
            raise
        except Exception as exc:
            raise self._failed("CONCH-Z text encoder", exc) from None

    def encode_report(
        self, texts: Sequence[str], *, kind: ReportTextKind
    ) -> list[EncodedText]:
        try:
            model = self._bge()
            prepared = [report_model_input(text, kind) for text in texts]
            with self._infer_lock:
                return self._run_chunks(model, prepared)
        except EmbedError:
            raise
        except Exception as exc:
            raise self._failed("report encoder", exc) from None

    def _conch(self) -> object:
        model = self._conch_model
        if model is None:
            with self._load_lock:
                model = self._conch_model
                if model is None:
                    model = self._load_conch()
                    self._conch_model = model
        return model

    def _bge(self) -> object:
        model = self._bge_model
        if model is None:
            with self._load_lock:
                model = self._bge_model
                if model is None:
                    model = self._load_bge()
                    self._bge_model = model
        return model

    def _load_conch(self) -> object:
        token = require_hf_token(self._settings)
        from consilium.embed import hf  # pragma: allowlist secret

        return hf.load_conchz_text_tower(token)

    def _load_bge(self) -> object:
        token = _optional_token(self._settings)
        from consilium.embed import hf  # pragma: allowlist secret

        return hf.load_bge_encoder(token)

    def _run_chunks(self, model: object, texts: Sequence[str]) -> list[EncodedText]:
        encode = getattr(model, "encode", None)
        if not callable(encode):
            raise EmbedModelError("encoder backend has no encode method")
        output: list[EncodedText] = []
        for start in range(0, len(texts), self._chunk_size):
            piece = list(texts[start : start + self._chunk_size])
            output.extend(encode(piece))
        return output

    def _failed(self, label: str, exc: Exception) -> EmbedModelError:
        secret = _optional_token(self._settings)
        detail = scrub_secret(str(exc), secret)
        return EmbedModelError(f"{label} failed: {detail}")


def _optional_token(settings: Settings) -> str | None:
    secret: SecretStr | None = settings.hf_token
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    if value == "":
        return None
    return secret.get_secret_value()


EncodingT = TypeVar("EncodingT", ConchzTextEncoding, ReportTextEncoding)


class TextEncoders:
    """Encode image-query text and report text, with an LRU cache of queries."""

    def __init__(
        self,
        backend: TextEncoderBackend,
        *,
        cache_size: int = DEFAULT_QUERY_CACHE_SIZE,
    ) -> None:
        if cache_size < 0:
            raise ValueError("cache_size must be >= 0")
        self._backend = backend
        self._cache_size = cache_size
        self._cache: OrderedDict[tuple[str, ...], ConchzTextEncoding | ReportTextEncoding] = (
            OrderedDict()
        )
        self._cache_lock = threading.Lock()

    def encode_image_text(self, text: str) -> ConchzTextEncoding:
        return self.encode_image_texts((text,))[0]

    def encode_image_texts(self, texts: Sequence[str]) -> list[ConchzTextEncoding]:
        batch = _strings(texts)
        if not batch:
            return []
        keys = [("conchz", text) for text in batch]

        def fetch(indexes: Sequence[int]) -> list[ConchzTextEncoding]:
            encoded = list(self._backend.encode_conchz([batch[index] for index in indexes]))
            _check_batch(encoded, len(indexes), "CONCH-Z")
            return [_wrap_conch(item) for item in encoded]

        return self._encode_cached(keys, fetch, ConchzTextEncoding)

    def encode_report_query(self, text: str) -> ReportTextEncoding:
        return self.encode_report_queries((text,))[0]

    def encode_report_queries(self, texts: Sequence[str]) -> list[ReportTextEncoding]:
        batch = _strings(texts)
        if not batch:
            return []
        keys = [("report", ReportTextKind.QUERY.value, text) for text in batch]

        def fetch(indexes: Sequence[int]) -> list[ReportTextEncoding]:
            encoded = list(
                self._backend.encode_report(
                    [batch[index] for index in indexes],
                    kind=ReportTextKind.QUERY,
                )
            )
            _check_batch(encoded, len(indexes), "report")
            return [_wrap_report(item, ReportTextKind.QUERY) for item in encoded]

        return self._encode_cached(keys, fetch, ReportTextEncoding)

    def encode_report_passages(self, texts: Sequence[str]) -> list[ReportTextEncoding]:
        """Embed report chunks. Passages are not cached and do not take the query prefix."""
        batch = _strings(texts)
        if not batch:
            return []
        encoded = list(self._backend.encode_report(batch, kind=ReportTextKind.PASSAGE))
        _check_batch(encoded, len(batch), "report")
        return [_wrap_report(item, ReportTextKind.PASSAGE) for item in encoded]

    def warmup(self) -> None:
        """Load both encoders and encode one short phrase in each space."""
        self.encode_image_text("tissue")
        self.encode_report_query("tissue")

    def schedule_warmup(self) -> threading.Thread:
        """Start `warmup` on a daemon thread for API startup."""
        thread = threading.Thread(
            target=self.warmup,
            name="embed-warmup",
            daemon=True,
        )
        thread.start()
        return thread

    def _encode_cached(
        self,
        keys: Sequence[tuple[str, ...]],
        fetch: Callable[[Sequence[int]], Sequence[EncodingT]],
        result_type: type[EncodingT],
    ) -> list[EncodingT]:
        results: list[EncodingT | None] = [None] * len(keys)
        missing: list[int] = []
        with self._cache_lock:
            for index, key in enumerate(keys):
                hit = self._cache.get(key)
                if isinstance(hit, result_type):
                    self._cache.move_to_end(key)
                    results[index] = hit
                else:
                    missing.append(index)
        if missing:
            unique: list[int] = []
            seen: set[tuple[str, ...]] = set()
            for index in missing:
                key = keys[index]
                if key not in seen:
                    seen.add(key)
                    unique.append(index)
            wrapped = list(fetch(unique))
            if len(wrapped) != len(unique):
                raise EmbedModelError("encoder returned a different number of vectors than texts")
            by_key = {
                keys[index]: value for index, value in zip(unique, wrapped, strict=True)
            }
            with self._cache_lock:
                for index in missing:
                    value = by_key[keys[index]]
                    results[index] = value
                    self._remember(keys[index], value)
        encoded: list[EncodingT] = []
        for value in results:
            if not isinstance(value, result_type):
                raise EmbedModelError("encoder dropped a text")
            encoded.append(value)
        return encoded

    def _remember(
        self,
        key: tuple[str, ...],
        value: ConchzTextEncoding | ReportTextEncoding,
    ) -> None:
        if self._cache_size <= 0:
            return
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def build_text_encoders(
    settings: Settings | None = None,
    *,
    backend: TextEncoderBackend | None = None,
    cache_size: int = DEFAULT_QUERY_CACHE_SIZE,
) -> TextEncoders:
    """Build the query-time encoders.

    Pass `backend=MockTextEncoder()` in tests. The default loads Hugging Face
    weights on CPU, using `settings.hf_token` for the gated CONCH-Z download.
    """
    if backend is None:
        backend = HuggingFaceTextEncoder(settings)
    return TextEncoders(backend, cache_size=cache_size)


def _strings(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, str) or not isinstance(texts, Sequence):
        raise TypeError("texts must be a sequence of strings")
    batch = list(texts)
    for text in batch:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if text.strip() == "":
            raise ValueError("text is empty")
    return batch


def _check_batch(encoded: Sequence[EncodedText], expected: int, label: str) -> None:
    if len(encoded) != expected:
        raise EmbedModelError(
            f"{label} encoder returned {len(encoded)} vectors for {expected} texts"
        )


def _wrap_conch(item: EncodedText) -> ConchzTextEncoding:
    try:
        vector = ConchzEmbedding(values=item.values)
    except ValidationError as exc:
        raise EmbedModelError(
            "CONCH-Z returned a vector that is not a unit 768-d embedding"
        ) from exc
    return ConchzTextEncoding(
        vector=vector,
        truncated=item.truncated,
        token_count=item.token_count,
    )


def _wrap_report(item: EncodedText, kind: ReportTextKind) -> ReportTextEncoding:
    try:
        vector = ReportEmbedding(values=item.values)
    except ValidationError as exc:
        raise EmbedModelError(
            "bge-small returned a vector that is not a unit 384-d embedding"
        ) from exc
    return ReportTextEncoding(
        vector=vector,
        truncated=item.truncated,
        token_count=item.token_count,
        kind=kind,
    )
