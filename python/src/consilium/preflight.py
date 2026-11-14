"""Read-only demo preflight.

Each check prints one line: ``PASS``, ``WARN`` or ``FAIL``, the check name, and a
short detail. The process exits non-zero when any check is ``FAIL``.

Nothing here writes to Postgres. The slide store is only written when
``--warm`` fills the local cache for ``STORAGE_BACKEND=uc_volume``.
``--ping-llm`` is the only path that calls a model.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote, urlsplit

import psycopg
from psycopg import sql

from consilium.api.store import CASE_SIGNED_BREAST  # pragma: allowlist secret
from consilium.config import Settings, StorageBackend, get_settings  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migration_status  # pragma: allowlist secret
from consilium.embed.spaces import CONCHZ_DIM, REPORT_DIM  # pragma: allowlist secret
from consilium.embed.text import (  # pragma: allowlist secret
    EmbedModelError,
    HuggingFaceTextEncoder,
    ReportTextKind,
)
from consilium.tiles.store import SlideStore, StorageError  # pragma: allowlist secret

_COUNT_TABLES = (
    "pathologist",
    "patient",
    "path_case",
    "slide",
    "patch",
    "report",
    "report_chunk",
    "concept",
)
_ENCODER_PHRASE = "tissue"
_HEATMAP_TEXT = "glandular"
_REPORT_QUERY = "adenocarcinoma"
_TILE_LEVELS = 3
_LIGHT_TIMEOUT = 30.0
_HEAVY_TIMEOUT = 180.0
_DETAIL_LIMIT = 180
_USERINFO = re.compile(r"://[^/\s@]+@")
_KEYWORD_SECRET = re.compile(r"(?i)\b(password|pwd)\s*=\s*\S+")
_SECRET_ENV = ("ANTHROPIC_API_KEY", "HF_TOKEN", "DATABRICKS_TOKEN")
_STUB_CODES = {"stub", "not_implemented"}


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True)
class EncoderProbe:
    """One text encoder. ``load`` and ``encode`` are timed separately."""

    name: str
    dim: int
    load: Callable[[], None]
    encode: Callable[[str], int]


class _SlideSource(Protocol):
    def path_for(self, key: str) -> Path: ...

    def acquire(self, key: str) -> object: ...

    def release(self, handle: object) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _HttpResult:
    status: int
    body: bytes
    content_type: str
    elapsed: float
    error: str | None = None


@dataclass(frozen=True)
class _SlideRef:
    slide_id: str
    storage_key: str
    thumb_pack_key: str | None


def run_preflight(
    case_ids: Sequence[str] | None = None,
    *,
    api_base: str | None = None,
    warm: bool = False,
    ping_llm: bool = False,
    settings: Settings | None = None,
    encoder_probes: Callable[[Settings], Sequence[EncoderProbe]] | None = None,
    slide_source_factory: Callable[[Settings], _SlideSource] | None = None,
    llm_ping: Callable[[Settings], Check] | None = None,
    http_timeout: float = _LIGHT_TIMEOUT,
    http_heavy_timeout: float = _HEAVY_TIMEOUT,
) -> int:
    """Run the static checks, then the live checks when ``api_base`` is set.

    Returns ``0`` when every check is ``PASS`` or ``WARN``, and ``1`` when any
    check is ``FAIL``. A model call happens only when ``ping_llm`` is true.
    """
    try:
        cfg = settings if settings is not None else get_settings()
    except Exception as exc:
        _emit(Check(Status.FAIL, "settings", _short(_scrub(str(exc), _env_secrets()))))
        return 1

    secrets = _secret_values(cfg)
    failed = _remember(False, _settings_check(cfg, secrets))

    slides_by_case: dict[str, list[_SlideRef]] = {}
    ids = list(case_ids or [])
    db_error, states = _migration_state(cfg, secrets)
    if db_error is not None:
        failed = _remember(failed, Check(Status.FAIL, "database", db_error))
        failed = _remember(failed, Check(Status.FAIL, "counts", db_error))
        if ids:
            for case_id in ids:
                failed = _remember(
                    failed,
                    Check(Status.FAIL, "case", f"{case_id} database unreachable"),
                )
    else:
        failed = _remember(failed, _database_check(states))
        conn = _open_readonly(cfg)
        if conn is None:
            failed = _remember(failed, Check(Status.FAIL, "counts", "database unreachable"))
            for case_id in ids:
                failed = _remember(
                    failed,
                    Check(Status.FAIL, "case", f"{case_id} database unreachable"),
                )
        else:
            try:
                failed = _remember(failed, _counts_check(conn, secrets))
                if ids:
                    source_factory = slide_source_factory or default_slide_source
                    source = source_factory(cfg)
                    try:
                        for case_id in ids:
                            case_failed, slides = _case_checks(
                                conn,
                                cfg,
                                source,
                                case_id,
                                warm,
                                secrets,
                            )
                            slides_by_case[case_id] = slides
                            failed = case_failed or failed
                    finally:
                        source.close()
            finally:
                conn.close()

    probe_factory = encoder_probes or default_encoder_probes
    for check in _encoder_checks(cfg, probe_factory, secrets):
        failed = _remember(failed, check)

    if api_base is not None and api_base.strip() != "":
        for check in _live_checks(
            api_base.strip(),
            ids,
            slides_by_case,
            secrets,
            light_timeout=http_timeout,
            heavy_timeout=http_heavy_timeout,
        ):
            failed = _remember(failed, check)

    if ping_llm:
        ping = llm_ping or _default_llm_ping
        try:
            check = ping(cfg)
        except Exception as exc:
            check = Check(Status.FAIL, "llm.ping", _short(_scrub(str(exc), secrets)))
        failed = _remember(failed, check)
    return 1 if failed else 0


def _remember(failed: bool, check: Check) -> bool:
    _emit(check)
    return failed or check.status is Status.FAIL


def default_encoder_probes(settings: Settings) -> list[EncoderProbe]:
    """CONCH-Z text tower (768-d) and bge-small (384-d). Weights load on ``load``."""
    backend = HuggingFaceTextEncoder(settings)

    def load_conch() -> None:
        # The text tower loads on first use. Time that separately from encode.
        backend._conch()

    def encode_conch(text: str) -> int:
        encoded = backend.encode_conchz([text])
        if len(encoded) != 1:
            raise EmbedModelError("CONCH-Z returned no vector")
        return len(encoded[0].values)

    def load_report() -> None:
        backend._bge()

    def encode_report(text: str) -> int:
        encoded = backend.encode_report([text], kind=ReportTextKind.QUERY)
        if len(encoded) != 1:
            raise EmbedModelError("report encoder returned no vector")
        return len(encoded[0].values)

    return [
        EncoderProbe("encoder.conchz", CONCHZ_DIM, load_conch, encode_conch),
        EncoderProbe("encoder.report", REPORT_DIM, load_report, encode_report),
    ]


def default_slide_source(settings: Settings) -> SlideStore:
    return SlideStore(settings)


def public_database_url(url: str) -> str:
    """Database target with userinfo, password keywords, query and fragment removed."""
    if "://" not in url:
        return _KEYWORD_SECRET.sub(r"\1=***", url)
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parts.port}" if parts.port else ""
    path = parts.path or ""
    # urlunsplit drops a slash when netloc is empty, so build the URL directly.
    if host or port:
        return f"{parts.scheme}://{host}{port}{path}"
    if path:
        return f"{parts.scheme}://{path}"
    return f"{parts.scheme}://"


def _settings_check(cfg: Settings, secrets: Sequence[str]) -> Check:
    database_url = public_database_url(cfg.database_url)
    for secret in secrets:
        if secret and secret in database_url:
            database_url = "postgresql://***"
            break
    detail = " ".join(
        (
            f"database_url={database_url}",
            f"storage_backend={cfg.storage_backend.value}",
            f"storage_root={cfg.storage_root}",
            f"slide_cache_dir={cfg.slide_cache_dir}",
            f"slide_cache_max_gb={format(cfg.slide_cache_max_gb, 'g')}",
            f"search_backend={cfg.search_backend.value}",
            f"llm_provider={cfg.llm_provider.value}",
            f"anthropic_model={cfg.anthropic_model}",
            f"anthropic_api_key={_secret_flag(cfg.anthropic_api_key)}",
            f"hf_token={_secret_flag(cfg.hf_token)}",
            f"databricks_host={_text_flag(cfg.databricks_host)}",
            f"databricks_token={_secret_flag(cfg.databricks_token)}",
        )
    )
    return Check(Status.PASS, "settings", _scrub(detail, secrets))


def _migration_state(
    cfg: Settings,
    secrets: Sequence[str],
) -> tuple[str | None, list[object]]:
    try:
        return None, list(migration_status(cfg.database_url))
    except Exception as exc:
        return _db_error(exc, secrets), []


def _database_check(states: Sequence[object]) -> Check:
    pending_schema = [
        state.filename
        for state in states
        if getattr(state, "kind", None) == "schema" and getattr(state, "applied_at", None) is None
    ]
    pending_index = [
        state.filename
        for state in states
        if getattr(state, "kind", None) == "index" and getattr(state, "applied_at", None) is None
    ]
    applied = [
        state.filename for state in states if getattr(state, "applied_at", None) is not None
    ]
    if pending_schema:
        detail = f"schema migration missing: {', '.join(pending_schema)}"
        if pending_index:
            detail = f"{detail}; indexes not applied: {', '.join(pending_index)}"
        return Check(Status.FAIL, "database", detail)
    if pending_index:
        return Check(
            Status.WARN,
            "database",
            f"{', '.join(pending_index)} is not applied",
        )
    if not applied:
        return Check(Status.FAIL, "database", "no migration files found")
    return Check(Status.PASS, "database", ", ".join(f"{name} applied" for name in applied))


def _counts_check(conn: psycopg.Connection, secrets: Sequence[str]) -> Check:
    try:
        parts: list[str] = []
        zero = False
        for table in _COUNT_TABLES:
            row = conn.execute(
                sql.SQL("select count(*) from {}").format(sql.Identifier(table))
            ).fetchone()
            count = int(row[0]) if row is not None else 0
            parts.append(f"{table}={count}")
            if count == 0:
                zero = True
    except Exception as exc:
        return Check(Status.FAIL, "counts", _db_error(exc, secrets))
    status = Status.FAIL if zero else Status.PASS
    return Check(status, "counts", " ".join(parts))


def _case_checks(
    conn: psycopg.Connection,
    cfg: Settings,
    source: _SlideSource,
    case_id: str,
    warm: bool,
    secrets: Sequence[str],
) -> tuple[bool, list[_SlideRef]]:
    failed = False
    try:
        row = conn.execute("select 1 from path_case where id = %s", (case_id,)).fetchone()
    except Exception as exc:
        _emit(Check(Status.FAIL, "case", f"{case_id} {_db_error(exc, secrets)}"))
        return True, []
    if row is None:
        _emit(Check(Status.FAIL, "case", f"{case_id} not in path_case"))
        return True, []
    _emit(Check(Status.PASS, "case", f"{case_id} in path_case"))
    try:
        slide_rows = conn.execute(
            """
            select id, storage_key, thumb_pack_key
            from slide
            where case_id = %s
            order by ordinal, id
            """,
            (case_id,),
        ).fetchall()
    except Exception as exc:
        _emit(Check(Status.FAIL, "slide", f"{case_id} {_db_error(exc, secrets)}"))
        return True, []
    slides = [
        _SlideRef(slide_id=str(item[0]), storage_key=str(item[1]), thumb_pack_key=item[2])
        for item in slide_rows
    ]
    if not slides:
        failed = (
            _emit(Check(Status.WARN, "slide", f"{case_id} has no slides")).status is Status.FAIL
            or failed
        )
        return failed, []
    for slide in slides:
        if _slide_file_checks(cfg, source, slide, warm, secrets):
            failed = True
    return failed, slides


def _slide_file_checks(
    cfg: Settings,
    source: _SlideSource,
    slide: _SlideRef,
    warm: bool,
    secrets: Sequence[str],
) -> bool:
    failed = False
    try:
        _resolve_key(cfg, source, slide.storage_key, warm=warm)
    except (FileNotFoundError, StorageError):
        _emit(Check(Status.FAIL, "slide", f"{slide.slide_id} file missing {slide.storage_key}"))
        failed = True
    except Exception as exc:
        _emit(
            Check(
                Status.FAIL,
                "slide",
                f"{slide.slide_id} file missing {_file_error(exc, secrets)}",
            )
        )
        failed = True
    else:
        _emit(Check(Status.PASS, "slide", f"{slide.slide_id} file {slide.storage_key}"))
        try:
            width, height = _open_slide(source, slide.storage_key)
        except Exception as exc:
            failed = True
            _emit(
                Check(
                    Status.FAIL,
                    "slide",
                    f"{slide.slide_id} opens {_file_error(exc, secrets)}",
                )
            )
        else:
            _emit(Check(Status.PASS, "slide", f"{slide.slide_id} opens {width}x{height}"))

    pack_key = slide.thumb_pack_key
    if pack_key is None or pack_key.strip() == "":
        _emit(Check(Status.FAIL, "slide", f"{slide.slide_id} pack missing"))
        return True
    try:
        pack_path = _resolve_key(cfg, source, pack_key, warm=warm)
        size = pack_path.stat().st_size
    except (FileNotFoundError, StorageError):
        _emit(Check(Status.FAIL, "slide", f"{slide.slide_id} pack missing {pack_key}"))
        return True
    except Exception as exc:
        _emit(
            Check(
                Status.FAIL,
                "slide",
                f"{slide.slide_id} pack missing {_file_error(exc, secrets)}",
            )
        )
        return True
    if size <= 0:
        _emit(Check(Status.FAIL, "slide", f"{slide.slide_id} pack empty {pack_key}"))
        return True
    _emit(Check(Status.PASS, "slide", f"{slide.slide_id} pack {pack_key} {size} bytes"))
    return failed


def _resolve_key(cfg: Settings, source: _SlideSource, key: str, *, warm: bool) -> Path:
    """Local path for a slide or pack.

    ``uc_volume`` downloads only when ``warm`` is set. Otherwise a missing
    cache file fails without touching the volume.
    """
    if cfg.storage_backend is StorageBackend.UC_VOLUME and not warm:
        path = _cache_file(cfg, key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path
    return source.path_for(key)


def _cache_file(cfg: Settings, key: str) -> Path:
    if not isinstance(key, str) or key.strip() == "" or "\x00" in key or "\\" in key:
        raise StorageError("Slide file is not available.")
    if key.startswith("/"):
        raise StorageError("Slide file is not available.")
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageError("Slide file is not available.")
    root = Path(cfg.slide_cache_dir).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise StorageError("Slide file is not available.")
    return path


def _open_slide(source: _SlideSource, key: str) -> tuple[int, int]:
    handle = source.acquire(key)
    try:
        lock = getattr(handle, "lock", None)
        slide = getattr(handle, "slide", None)
        if slide is None or not hasattr(slide, "dimensions"):
            raise StorageError("Slide file is not available.")
        if lock is None:
            width, height = slide.dimensions
        else:
            with lock:
                width, height = slide.dimensions
        return int(width), int(height)
    finally:
        source.release(handle)


def _encoder_checks(
    cfg: Settings,
    factory: Callable[[Settings], Sequence[EncoderProbe]],
    secrets: Sequence[str],
) -> list[Check]:
    # Download progress from the weight libraries is not a check line.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    try:
        probes = list(factory(cfg))
    except Exception as exc:
        detail = _short(_scrub(f"{exc.__class__.__name__}: {exc}", secrets))
        return [Check(Status.FAIL, "encoders", detail)]
    checks: list[Check] = []
    for probe in probes:
        checks.append(_one_encoder(probe, secrets))
    if not checks:
        checks.append(Check(Status.FAIL, "encoders", "no encoders were configured"))
    return checks


def _one_encoder(probe: EncoderProbe, secrets: Sequence[str]) -> Check:
    try:
        started = time.perf_counter()
        probe.load()
        load_s = time.perf_counter() - started
        started = time.perf_counter()
        dim = probe.encode(_ENCODER_PHRASE)
        encode_s = time.perf_counter() - started
    except Exception as exc:
        return Check(
            Status.FAIL,
            probe.name,
            _short(_scrub(f"{exc.__class__.__name__}: {exc}", secrets)),
        )
    if dim != probe.dim:
        return Check(Status.FAIL, probe.name, f"expected {probe.dim}-d, got {dim}")
    return Check(
        Status.PASS,
        probe.name,
        f"{probe.dim}-d load {_seconds(load_s)} encode {_seconds(encode_s)}",
    )


def _live_checks(
    api_base: str,
    case_ids: Sequence[str],
    slides_by_case: Mapping[str, Sequence[_SlideRef]],
    secrets: Sequence[str],
    *,
    light_timeout: float,
    heavy_timeout: float,
) -> list[Check]:
    checks: list[Check] = []
    base = api_base.rstrip("/")
    health = _request("GET", f"{base}/api/health", None, light_timeout, secrets)
    if health.error is not None:
        checks.append(Check(Status.FAIL, "api.health", health.error))
        return checks
    if health.status == 200 and _health_ok(health.body):
        checks.append(Check(Status.PASS, "api.health", "ok"))
    else:
        checks.append(Check(Status.FAIL, "api.health", f"HTTP {health.status}"))
        return checks

    placeholder: bool | None = None
    heatmap_slide: str | None = None
    for case_id in case_ids:
        case_result = _request(
            "GET",
            f"{base}/api/cases/{quote(case_id, safe='')}",
            None,
            light_timeout,
            secrets,
        )
        api_slide_ids = _slide_ids(case_result.body) if case_result.status == 200 else []
        if case_result.error is not None:
            checks.append(Check(Status.FAIL, "api.case", f"{case_id} {case_result.error}"))
        elif case_result.status == 200:
            checks.append(Check(Status.PASS, "api.case", f"{case_id} HTTP 200"))
        elif case_result.status == 404:
            if placeholder is None:
                placeholder = _placeholder_store(base, light_timeout, secrets)
            if placeholder:
                checks.append(
                    Check(
                        Status.WARN,
                        "api.case",
                        f"{case_id} HTTP 404; case route still serves the placeholder store",
                    )
                )
            else:
                checks.append(Check(Status.FAIL, "api.case", f"{case_id} HTTP 404"))
        else:
            checks.append(Check(Status.FAIL, "api.case", f"{case_id} HTTP {case_result.status}"))

        db_ids = [slide.slide_id for slide in slides_by_case.get(case_id, [])]
        if case_result.status == 200 and api_slide_ids:
            slide_ids = api_slide_ids
        else:
            slide_ids = db_ids or api_slide_ids
        for slide_id in slide_ids:
            if heatmap_slide is None:
                heatmap_slide = slide_id
            checks.extend(_slide_http_checks(base, slide_id, light_timeout, secrets))

    if heatmap_slide is None:
        checks.append(Check(Status.WARN, "api.heatmap", "no slide to warm; pass --case"))
    else:
        checks.append(_heatmap_check(base, heatmap_slide, heavy_timeout, secrets))
    checks.append(_report_search_check(base, heavy_timeout, secrets))
    return checks


def _placeholder_store(base: str, timeout: float, secrets: Sequence[str]) -> bool:
    """True when the known in-memory case still answers and the fixture id does not.

    ``GET /api/cases/{id}`` on this branch reads the placeholder store, whose
    ids are not the seeded ``path_case`` ids. A 404 then is a warning: the
    slide routes still warm from the database ids.
    """
    result = _request(
        "GET",
        f"{base}/api/cases/{quote(CASE_SIGNED_BREAST, safe='')}",
        None,
        timeout,
        secrets,
    )
    return result.error is None and result.status == 200


def _slide_http_checks(
    base: str,
    slide_id: str,
    timeout: float,
    secrets: Sequence[str],
) -> list[Check]:
    quoted = quote(slide_id, safe="")
    checks: list[Check] = []
    dzi = _request("GET", f"{base}/api/slides/{quoted}.dzi", None, timeout, secrets)
    if dzi.error is not None or dzi.status != 200:
        detail = dzi.error or f"HTTP {dzi.status}"
        checks.append(Check(Status.FAIL, "api.dzi", f"{slide_id} {detail}"))
        return checks
    checks.append(Check(Status.PASS, "api.dzi", f"{slide_id} HTTP 200"))

    thumb = _request(
        "GET",
        f"{base}/api/slides/{quoted}/thumbnail",
        None,
        timeout,
        secrets,
    )
    if thumb.error is not None or thumb.status != 200 or not _jpeg(thumb):
        detail = thumb.error or f"HTTP {thumb.status}"
        checks.append(Check(Status.FAIL, "api.thumbnail", f"{slide_id} {detail}"))
    else:
        checks.append(Check(Status.PASS, "api.thumbnail", f"{slide_id} HTTP 200"))

    levels = _dzi_levels(dzi.body)
    if not levels:
        checks.append(Check(Status.FAIL, "api.tiles", f"{slide_id} descriptor has no levels"))
        return checks
    failed_level: int | None = None
    failed_detail = ""
    for level in levels:
        tile = _request(
            "GET",
            f"{base}/api/slides/{quoted}_files/{level}/0_0.jpeg",
            None,
            timeout,
            secrets,
        )
        if tile.error is not None or tile.status != 200 or not _jpeg(tile):
            failed_level = level
            failed_detail = tile.error or f"HTTP {tile.status}"
            break
    if failed_level is None:
        shown = ",".join(str(level) for level in levels)
        checks.append(Check(Status.PASS, "api.tiles", f"{slide_id} levels {shown}"))
    else:
        checks.append(
            Check(Status.FAIL, "api.tiles", f"{slide_id} level {failed_level} {failed_detail}")
        )
    return checks


def _heatmap_check(base: str, slide_id: str, timeout: float, secrets: Sequence[str]) -> Check:
    quoted = quote(slide_id, safe="")
    result = _request(
        "POST",
        f"{base}/api/slides/{quoted}/heatmap",
        {"text": _HEATMAP_TEXT},
        timeout,
        secrets,
    )
    if result.error is not None:
        return Check(Status.FAIL, "api.heatmap", f"{slide_id} {result.error}")
    if result.status != 200:
        return Check(Status.FAIL, "api.heatmap", f"{slide_id} HTTP {result.status}")
    return Check(
        Status.PASS,
        "api.heatmap",
        f"{slide_id} {_HEATMAP_TEXT} {_seconds(result.elapsed)} ({_millis(result.elapsed)})",
    )


def _report_search_check(base: str, timeout: float, secrets: Sequence[str]) -> Check:
    result = _request(
        "POST",
        f"{base}/api/search/reports",
        {"text": _REPORT_QUERY},
        timeout,
        secrets,
    )
    if result.error is not None:
        return Check(Status.FAIL, "api.reports", result.error)
    if _is_stub(result.status, result.body):
        return Check(
            Status.WARN,
            "api.reports",
            f"stub HTTP {result.status}; report encoder was not warmed",
        )
    if result.status != 200:
        return Check(Status.FAIL, "api.reports", f"HTTP {result.status}")
    return Check(
        Status.PASS,
        "api.reports",
        f"{_REPORT_QUERY} {_seconds(result.elapsed)} ({_millis(result.elapsed)})",
    )


def _default_llm_ping(settings: Settings) -> Check:
    """One 5-token call. Only ``run_preflight(..., ping_llm=True)`` reaches this."""
    if settings.llm_provider.value == "databricks":
        return _ping_databricks(settings)
    return _ping_anthropic(settings)


def _ping_anthropic(settings: Settings) -> Check:
    secrets = _secret_values(settings)
    secret = settings.anthropic_api_key
    if secret is None or secret.get_secret_value().strip() == "":
        return Check(Status.FAIL, "llm.ping", "ANTHROPIC_API_KEY is not set")
    key = secret.get_secret_value()
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        client.messages.create(
            model=settings.anthropic_model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with ok."}],
        )
    except Exception as exc:
        return Check(
            Status.FAIL,
            "llm.ping",
            _short(_scrub(f"{exc.__class__.__name__}: {exc}", secrets)),
        )
    return Check(Status.PASS, "llm.ping", f"anthropic {settings.anthropic_model} max_tokens=5")


def _ping_databricks(settings: Settings) -> Check:
    """No Databricks model id is configured, so this does not call the network."""
    host = (settings.databricks_host or "").strip()
    token = settings.databricks_token
    token_set = token is not None and token.get_secret_value().strip() != ""
    if host == "" or not token_set:
        return Check(Status.FAIL, "llm.ping", "DATABRICKS_HOST or DATABRICKS_TOKEN is not set")
    return Check(
        Status.FAIL,
        "llm.ping",
        "LLM_PROVIDER=databricks has no model id configured",
    )


def _request(
    method: str,
    url: str,
    payload: Mapping[str, object] | None,
    timeout: float,
    secrets: Sequence[str],
) -> _HttpResult:
    data: bytes | None = None
    headers = {"Accept": "*/*"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = int(response.status)
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = int(exc.code)
        content_type = exc.headers.get("Content-Type", "") if exc.headers is not None else ""
    except Exception as exc:
        elapsed = time.perf_counter() - started
        detail = _short(_scrub(f"{exc.__class__.__name__}: {exc}", secrets))
        return _HttpResult(0, b"", "", elapsed, error=detail)
    elapsed = time.perf_counter() - started
    return _HttpResult(status, body, content_type, elapsed)


def _health_ok(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok"


def _slide_ids(body: bytes) -> list[str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    slides = payload.get("slides")
    if not isinstance(slides, list):
        return []
    ids: list[str] = []
    for slide in slides:
        if isinstance(slide, dict) and isinstance(slide.get("id"), str):
            ids.append(slide["id"])
    return ids


def _dzi_levels(body: bytes, handful: int = _TILE_LEVELS) -> list[int]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    size = None
    for element in root.iter():
        if element.tag.endswith("Size"):
            size = element
            break
    if size is None:
        return []
    try:
        width = int(size.attrib["Width"])
        height = int(size.attrib["Height"])
    except (KeyError, ValueError):
        return []
    count = _level_count(width, height)
    return list(range(min(handful, count)))


def _level_count(width: int, height: int) -> int:
    """Deep Zoom level count, matching OpenSlide's generator."""
    level_width = max(width, 1)
    level_height = max(height, 1)
    count = 1
    while level_width > 1 or level_height > 1:
        level_width = max(1, math.ceil(level_width / 2))
        level_height = max(1, math.ceil(level_height / 2))
        count += 1
    return count


def _jpeg(result: _HttpResult) -> bool:
    if result.body.startswith(b"\xff\xd8"):
        return True
    return "image/jpeg" in result.content_type.lower()


def _is_stub(status: int, body: bytes) -> bool:
    if status == 501:
        return True
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        text = body.decode("utf-8", errors="replace").lower()
        return status >= 400 and "stub" in text
    if not isinstance(payload, dict):
        return False
    if payload.get("stub") is True:
        return True
    error = payload.get("error")
    if isinstance(error, dict):
        code = str(error.get("code", "")).lower()
        message = str(error.get("message", "")).lower()
        if code in _STUB_CODES or "stub" in message or "not implemented" in message:
            return True
    for key in ("status", "code", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.lower() in _STUB_CODES:
            return True
    return False


def _open_readonly(cfg: Settings) -> psycopg.Connection | None:
    try:
        conn = connect(_with_timeout(cfg.database_url), register=False)
    except psycopg.Error:
        return None
    conn.autocommit = True
    try:
        conn.execute("set default_transaction_read_only = on")
    except psycopg.Error:
        pass
    return conn


def _with_timeout(url: str) -> str:
    if "connect_timeout" in url:
        return url
    if "://" in url:
        join = "&" if "?" in url else "?"
        return f"{url}{join}connect_timeout=5"
    return f"{url} connect_timeout=5"


def _text_flag(value: str | None) -> str:
    """Hostnames are not printed. The architecture table marks the host as secret."""
    if value is None or value.strip() == "":
        return "not set"
    return "set"


def _secret_flag(secret: object) -> str:
    if secret is None:
        return "not set"
    getter = getattr(secret, "get_secret_value", None)
    if not callable(getter):
        return "not set"
    value = getter()
    if not isinstance(value, str) or value.strip() == "":
        return "not set"
    return "set"


def _secret_values(cfg: Settings) -> list[str]:
    values = _env_secrets()
    host = (cfg.databricks_host or "").strip()
    if host:
        values.append(host)
    for secret in (cfg.anthropic_api_key, cfg.hf_token, cfg.databricks_token):
        if secret is None:
            continue
        raw = secret.get_secret_value()
        if raw.strip() != "":
            values.append(raw)
    password = _password(cfg.database_url)
    if password:
        values.append(password)
        decoded = unquote(password)
        if decoded != password:
            values.append(decoded)
    # Longest first so a shorter secret that is a prefix is not left behind.
    unique = [value for value in dict.fromkeys(values) if value]
    unique.sort(key=len, reverse=True)
    return unique


def _env_secrets() -> list[str]:
    values: list[str] = []
    for name in (*_SECRET_ENV, "DATABRICKS_HOST"):
        raw = os.environ.get(name, "")
        if raw.strip() != "":
            values.append(raw)
    password = _password(os.environ.get("DATABASE_URL", ""))
    if password:
        values.append(password)
    return values


def _password(url: str) -> str | None:
    if url.strip() == "":
        return None
    if "://" in url:
        password = urlsplit(url).password
        if password:
            return unquote(password)
        return None
    match = re.search(r"(?i)\b(?:password|pwd)\s*=\s*(\S+)", url)
    if match is None:
        return None
    return match.group(1)


def _scrub(text: str, secrets: Sequence[str]) -> str:
    cleaned = text
    for secret in secrets:
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "***")
    cleaned = _USERINFO.sub("://", cleaned)
    cleaned = _KEYWORD_SECRET.sub(r"\1=***", cleaned)
    return " ".join(cleaned.split())


def _db_error(exc: BaseException, secrets: Sequence[str]) -> str:
    message = _scrub(f"{exc.__class__.__name__}: {exc}", secrets)
    lowered = message.lower()
    if "://" in message or "password" in lowered:
        return exc.__class__.__name__
    return _short(message)


def _file_error(exc: BaseException, secrets: Sequence[str]) -> str:
    if isinstance(exc, StorageError):
        return _short(exc.message)
    if isinstance(exc, FileNotFoundError):
        return "not in the local cache" if exc.filename is None else "not found"
    return _db_error(exc, secrets)


def _seconds(value: float) -> str:
    return f"{value:.3f}s"


def _millis(value: float) -> str:
    return f"{max(0, int(round(value * 1000)))}ms"


def _short(text: str, limit: int = _DETAIL_LIMIT) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _emit(check: Check) -> Check:
    print(f"{check.status.value} {check.name} {check.detail}")
    return check
