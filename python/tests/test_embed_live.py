"""Live CPU checks for CONCH-Z and bge-small.

Skipped unless the HF integration environment flag is set. CONCH-Z also needs HF_TOKEN.
The token is captured at import, before the test fixture clears the environment,
and is never written into an assertion message.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from consilium.config import Settings  # pragma: allowlist secret
from consilium.embed import (  # pragma: allowlist secret
    CONCHZ_DIM,
    CONCHZ_MAX_TOKENS,
    REPORT_DIM,
    build_text_encoders,
    cosine_similarity,
)
from consilium.embed.text import ReportTextKind  # pragma: allowlist secret

pytestmark = pytest.mark.integration

_SAVED_HF_TOKEN = os.environ.get("HF_TOKEN")
_METRICS_PATH = Path("/tmp/sko-258-live-metrics.txt")


def _rss_mb() -> float:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS missing")


def _maxrss_mb() -> float:
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _norm(values: tuple[float, ...]) -> float:
    return math.sqrt(sum(value * value for value in values))


def test_live_cpu_encoders() -> None:
    if os.environ.get("CONSILIUM_RUN_HF_INTEGRATION") != "1":  # pragma: allowlist secret
        pytest.skip("HF integration flag is unset")
    if not _SAVED_HF_TOKEN:
        pytest.skip("HF_TOKEN is absent")

    token = _SAVED_HF_TOKEN
    settings = Settings(hf_token=SecretStr(token))
    encoders = build_text_encoders(settings)
    lines: list[str] = []

    def record(name: str, value: float) -> None:
        lines.append(f"{name}={value:.4f}")

    try:
        rss_before = _rss_mb()
        record("rss_before_mb", rss_before)

        started = time.perf_counter()
        bge_cold = encoders.encode_report_query("cribriform glands")
        record("bge_cold_s", time.perf_counter() - started)
        record("rss_after_bge_mb", _rss_mb())

        started = time.perf_counter()
        bge_warm = encoders.encode_report_query("adenocarcinoma")
        record("bge_warm_s", time.perf_counter() - started)

        started = time.perf_counter()
        bge_cached = encoders.encode_report_query("cribriform glands")
        record("bge_cached_s", time.perf_counter() - started)

        started = time.perf_counter()
        conch_cold = encoders.encode_image_text("cribriform glands")
        record("conch_cold_s", time.perf_counter() - started)
        record("rss_after_conch_mb", _rss_mb())

        started = time.perf_counter()
        conch_warm = encoders.encode_image_text("adenocarcinoma")
        record("conch_warm_s", time.perf_counter() - started)

        started = time.perf_counter()
        conch_cached = encoders.encode_image_text("cribriform glands")
        record("conch_cached_s", time.perf_counter() - started)

        stroma = encoders.encode_image_text("normal stroma")
        passage = encoders.encode_report_passages(["cribriform glands"])[0]
        batched = encoders.encode_image_texts(
            ["cribriform glands", "adenocarcinoma", "normal stroma"]
        )
        long_text = encoders.encode_image_text(" ".join(["glandular"] * 400))
        record("maxrss_mb", _maxrss_mb())
    except Exception as exc:
        message = str(exc).replace(token, "***")
        raise AssertionError(message) from None

    assert bge_cached.vector.values == bge_cold.vector.values
    assert conch_cached.vector.values == conch_cold.vector.values
    assert len(bge_cold.vector.values) == REPORT_DIM
    assert len(conch_cold.vector.values) == CONCHZ_DIM
    assert abs(_norm(bge_cold.vector.values) - 1.0) < 1e-3
    assert abs(_norm(conch_cold.vector.values) - 1.0) < 1e-3
    assert bge_cold.kind is ReportTextKind.QUERY
    assert passage.kind is ReportTextKind.PASSAGE
    assert bge_cold.vector.values != passage.vector.values
    assert bge_cold.truncated is False
    assert conch_cold.truncated is False
    assert conch_cold.token_count <= CONCHZ_MAX_TOKENS
    assert long_text.truncated is True
    assert long_text.token_count > CONCHZ_MAX_TOKENS
    assert long_text.truncation_notice() is not None
    assert len(batched) == 3
    assert [item.vector for item in batched] == [
        conch_cold.vector,
        conch_warm.vector,
        stroma.vector,
    ]

    conch_adeno = cosine_similarity(conch_cold.vector, conch_warm.vector)
    conch_stroma = cosine_similarity(conch_cold.vector, stroma.vector)
    bge_adeno = cosine_similarity(bge_cold.vector, bge_warm.vector)
    record("conch_cos_adeno", conch_adeno)
    record("conch_cos_stroma", conch_stroma)
    record("bge_cos_adeno", bge_adeno)
    text = "\n".join(lines) + "\n"
    _METRICS_PATH.write_text(text, encoding="utf-8")
    print(text)
    assert conch_adeno > conch_stroma
    assert bge_warm.token_count > 0
    # Warm encode is a forward pass, not a weight load. The issue asks for
    # well under a second once the model is loaded.
    warm_line = next(line for line in lines if line.startswith("conch_warm_s="))
    bge_warm_line = next(line for line in lines if line.startswith("bge_warm_s="))
    assert float(warm_line.split("=", 1)[1]) < 1.0
    assert float(bge_warm_line.split("=", 1)[1]) < 1.0
