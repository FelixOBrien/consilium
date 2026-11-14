"""Demo preflight: static checks, live warm-up, and secret redaction."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from pydantic import SecretStr

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.api.store import CASE_SIGNED_BREAST  # pragma: allowlist secret
from consilium.cli import main  # pragma: allowlist secret
from consilium.config import LlmProvider, Settings, StorageBackend  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.embed.spaces import CONCHZ_DIM, REPORT_DIM  # pragma: allowlist secret
from consilium.embed.text import MockTextEncoder, build_text_encoders  # pragma: allowlist secret
from consilium.preflight import (  # pragma: allowlist secret
    Check,
    EncoderProbe,
    Status,
    _ping_anthropic,
    _ping_databricks,
    public_database_url,
    run_preflight,
)

_CASE_ID = "breast-FX-B042A"
_SLIDE_ID = "breast-FX-B042A-s1"
_ANTHROPIC = "preflight-anthropic-key-9c1e"
_HF = "preflight-hf-token-9c1e"
_DATABRICKS = "preflight-databricks-token-9c1e"
_PASSWORD = "preflight-db-password-9c1e"
_USER = "preflightuser9c1e"
_JPEG = b"\xff\xd8\xff\xd9"
_DZI = b"""<?xml version="1.0" encoding="UTF-8"?>
<Image TileSize="254" Overlap="1" Format="jpeg"
       xmlns="http://schemas.microsoft.com/deepzoom/2008">
  <Size Width="2048" Height="1536"/>
</Image>
"""
_SECRETS = (_ANTHROPIC, _HF, _DATABRICKS, _PASSWORD)


def _probes(settings: Settings) -> list[EncoderProbe]:
    del settings
    return [
        EncoderProbe("encoder.conchz", CONCHZ_DIM, lambda: None, lambda text: CONCHZ_DIM),
        EncoderProbe("encoder.report", REPORT_DIM, lambda: None, lambda text: REPORT_DIM),
    ]


def _lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.strip()]


def _status(lines: list[str], name: str) -> list[str]:
    prefix = ("PASS ", "WARN ", "FAIL ")
    return [line for line in lines if line.startswith(prefix) and f" {name} " in f" {line} "]


def _seeded(url: str, root: Path) -> Settings:
    migrate(url)
    seed(url, root)
    return Settings(
        database_url=url,
        storage_backend=StorageBackend.LOCAL,
        storage_root=root,
        slide_cache_dir=root / "cache",
        slide_cache_max_gb=1,
    )


def _run(
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
    argv_cases: list[str] | None = None,
    **kwargs: object,
) -> tuple[int, str, str]:
    code = run_preflight(
        argv_cases,
        settings=settings,
        encoder_probes=kwargs.pop("encoder_probes", _probes),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._reply()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.posts.append((self.path, body))  # type: ignore[attr-defined]
        self._reply()

    def _reply(self) -> None:
        status, payload, content_type = self.server.router(self.path, self.command)  # type: ignore[attr-defined]
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def _http(
    router: Callable[[str, str], tuple[int, bytes | str, str]],
) -> Iterator[tuple[str, list[tuple[str, bytes]]]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.router = router  # type: ignore[attr-defined]
    server.posts = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}", server.posts  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _down_settings() -> Settings:
    return Settings(
        database_url=f"postgresql://{_USER}:{_PASSWORD}@127.0.0.1:1/none",
        anthropic_api_key=SecretStr(_ANTHROPIC),
        hf_token=SecretStr(_HF),
        databricks_token=SecretStr(_DATABRICKS),
        databricks_host="https://example.cloud.databricks.com",
    )


def test_public_database_url_strips_userinfo() -> None:
    name = "consilium"  # pragma: allowlist secret
    url = f"postgresql://{_USER}:{_PASSWORD}@localhost:5432/{name}?sslmode=require"
    public = public_database_url(url)
    assert public == f"postgresql://localhost:5432/{name}"
    socket_url = f"postgresql://{_USER}:{_PASSWORD}@/{name}?host=/var/run/postgresql"
    assert public_database_url(socket_url) == f"postgresql:///{name}"
    assert _PASSWORD not in public
    assert _USER not in public
    keyword = public_database_url(f"host=localhost password={_PASSWORD} dbname={name}")
    assert _PASSWORD not in keyword
    assert "password=***" in keyword


def test_secrets_never_appear(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def leak(settings: Settings) -> list[EncoderProbe]:
        token = settings.hf_token.get_secret_value() if settings.hf_token else ""
        password = urlsplit(settings.database_url).password or ""

        def boom() -> None:
            raise RuntimeError(f"load failed token={token} password={password} key={_ANTHROPIC}")

        return [
            EncoderProbe("encoder.conchz", CONCHZ_DIM, boom, lambda text: CONCHZ_DIM),
            EncoderProbe("encoder.report", REPORT_DIM, lambda: None, lambda text: REPORT_DIM),
        ]

    def ping(settings: Settings) -> Check:
        raise AssertionError(settings.anthropic_api_key)

    http_open = "consilium.preflight.urllib.request.urlopen"  # pragma: allowlist secret
    monkeypatch.setattr(http_open, _forbid_http)
    monkeypatch.setattr("anthropic.Anthropic", _forbid_anthropic)
    code, out, err = _run(
        capsys,
        _down_settings(),
        ["breast-FX-B042C"],
        encoder_probes=leak,
        llm_ping=ping,
    )
    combined = out + err
    for secret in _SECRETS:
        assert secret not in combined
    assert _USER not in out
    settings_line = next(line for line in _lines(out) if line.startswith("PASS settings "))
    assert "anthropic_api_key=set" in settings_line
    assert "hf_token=set" in settings_line
    assert "databricks_token=set" in settings_line
    assert "databricks_host=set" in settings_line
    assert "example.cloud.databricks.com" not in combined
    assert "database_url=postgresql://127.0.0.1:1/none" in settings_line
    assert "@" not in settings_line.split("storage_backend=", 1)[0]
    assert code == 1
    assert "FAIL encoder.conchz" in out
    assert "PASS encoder.report" in out


def test_database_down_fails(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(capsys, _down_settings(), [_CASE_ID])
    assert code == 1
    assert err == ""
    assert any(line.startswith("FAIL database ") for line in _lines(out))
    assert any(line.startswith("FAIL counts ") for line in _lines(out))
    assert any(line.startswith(f"FAIL case {_CASE_ID} ") for line in _lines(out))
    for secret in _SECRETS:
        assert secret not in out
        assert secret not in err


def test_missing_schema_fails(empty_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(database_url=empty_database)
    code, out, _err = _run(capsys, settings)
    assert code == 1
    assert "FAIL database " in out
    assert "0001_init.sql" in out
    assert "FAIL counts " in out


def test_pending_indexes_warn(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    migrate(empty_database, include_indexes=False)
    seed(empty_database, tmp_path)
    settings = Settings(
        database_url=empty_database,
        storage_root=tmp_path,
        slide_cache_dir=tmp_path / "cache",
    )
    code, out, err = _run(capsys, settings)
    assert err == ""
    assert code == 0
    assert "WARN database " in out
    assert "0002_indexes.sql is not applied" in out
    assert "PASS counts " in out
    assert "pathologist=0" not in out


def test_zero_counts_fail(empty_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    migrate(empty_database)
    settings = Settings(database_url=empty_database)
    code, out, _err = _run(capsys, settings)
    assert code == 1
    assert "PASS database " in out
    assert "FAIL counts " in out
    assert "pathologist=0" in out
    assert "concept=0" in out


def test_seeded_case_passes(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _seeded(empty_database, tmp_path)
    before = _snapshot(empty_database)
    code, out, err = _run(capsys, settings, [_CASE_ID])
    assert err == ""
    assert code == 0
    assert _snapshot(empty_database) == before
    text = " ".join(_lines(out))
    assert f"PASS case {_CASE_ID} in path_case" in out
    assert f"PASS slide {_SLIDE_ID} file " in out
    assert f"PASS slide {_SLIDE_ID} opens " in out
    assert f"PASS slide {_SLIDE_ID} pack " in out
    assert "bytes" in out
    assert f"PASS encoder.conchz {CONCHZ_DIM}-d load " in text
    assert f"PASS encoder.report {REPORT_DIM}-d load " in text
    assert "api." not in out


def test_missing_case_and_slide_file(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _seeded(empty_database, tmp_path)
    code, out, _err = _run(capsys, settings, ["missing-case"])
    assert code == 1
    assert "FAIL case missing-case not in path_case" in out

    with connect(empty_database) as conn:
        key = conn.execute(
            "select storage_key from slide where id = %s",
            (_SLIDE_ID,),
        ).fetchone()[0]
    slide_path = tmp_path / key
    slide_path.unlink()
    code, out, _err = _run(capsys, settings, [_CASE_ID])
    assert code == 1
    assert f"FAIL slide {_SLIDE_ID} file missing {key}" in out
    assert not slide_path.exists()


def test_empty_pack_fails(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _seeded(empty_database, tmp_path)
    with connect(empty_database) as conn:
        pack_key = conn.execute(
            "select thumb_pack_key from slide where id = %s",
            (_SLIDE_ID,),
        ).fetchone()[0]
    pack = tmp_path / pack_key
    pack.write_bytes(b"")
    code, out, _err = _run(capsys, settings, [_CASE_ID])
    assert code == 1
    assert f"FAIL slide {_SLIDE_ID} pack empty {pack_key}" in out


def test_preflight_does_not_call_http_or_llm(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_open = "consilium.preflight.urllib.request.urlopen"  # pragma: allowlist secret
    monkeypatch.setattr(http_open, _forbid_http)
    monkeypatch.setattr("anthropic.Anthropic", _forbid_anthropic)
    code, out, _err = _run(capsys, _down_settings())
    assert code == 1
    assert "api." not in out
    assert "llm.ping" not in out


def test_ping_llm_is_opt_in(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def ping(settings: Settings) -> Check:
        calls.append("called")
        return Check(Status.PASS, "llm.ping", f"anthropic {settings.anthropic_model} max_tokens=5")

    monkeypatch.setattr("anthropic.Anthropic", _forbid_anthropic)
    code, out, _err = _run(capsys, _down_settings(), ping_llm=True, llm_ping=ping)
    assert calls == ["called"]
    assert code == 1
    assert "PASS llm.ping anthropic " in out
    assert "max_tokens=5" in out


def test_anthropic_ping_reports_and_scrubs(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class _Messages:
        def create(self, **kwargs: object) -> dict[str, str]:
            seen["kwargs"] = kwargs
            if seen.get("fail"):
                raise RuntimeError(f"rejected {_ANTHROPIC}")
            return {"id": "msg"}

    class _Client:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == _ANTHROPIC
            self.messages = _Messages()

    monkeypatch.setattr("anthropic.Anthropic", _Client)
    settings = Settings(anthropic_api_key=SecretStr(_ANTHROPIC))
    passed = _ping_anthropic(settings)
    assert passed.status is Status.PASS
    assert passed.detail.endswith("max_tokens=5")
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["max_tokens"] == 5

    seen["fail"] = True
    failed = _ping_anthropic(settings)
    assert failed.status is Status.FAIL
    assert _ANTHROPIC not in failed.detail
    assert "RuntimeError" in failed.detail


def test_databricks_ping_does_not_call_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    http_open = "consilium.preflight.urllib.request.urlopen"  # pragma: allowlist secret
    monkeypatch.setattr(http_open, _forbid_http)
    missing = _ping_databricks(
        Settings(llm_provider=LlmProvider.DATABRICKS, databricks_host="https://example.invalid")
    )
    assert missing.status is Status.FAIL
    assert "not set" in missing.detail
    refused = _ping_databricks(
        Settings(
            llm_provider=LlmProvider.DATABRICKS,
            databricks_host="https://example.invalid",
            databricks_token=SecretStr(_DATABRICKS),
        )
    )
    assert refused.status is Status.FAIL
    assert "no model id" in refused.detail
    assert _DATABRICKS not in refused.detail


def test_cli_help_and_default_encoder_factory(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["preflight", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--case" in help_text
    assert "--api" in help_text
    assert "--warm" in help_text
    assert "--ping-llm" in help_text

    called = {"yes": False}

    def factory(settings: Settings) -> list[EncoderProbe]:
        called["yes"] = True
        return _probes(settings)

    probes = "consilium.preflight.default_encoder_probes"  # pragma: allowlist secret
    monkeypatch.setattr(probes, factory)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://{_USER}:{_PASSWORD}@127.0.0.1:1/none")
    code = main(["preflight"])
    captured = capsys.readouterr()
    assert called["yes"] is True
    assert code == 1
    assert _PASSWORD not in captured.out
    assert _PASSWORD not in captured.err


def test_warm_fetches_only_for_uc_volume(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _seeded(empty_database, tmp_path)
    cold = _Recorder(tmp_path / "cold")
    settings = Settings(
        database_url=empty_database,
        storage_backend=StorageBackend.UC_VOLUME,
        storage_root=Path("/Volumes/cohort"),
        slide_cache_dir=tmp_path / "empty-cache",
        slide_cache_max_gb=1,
    )
    code, out, _err = _run(
        capsys,
        settings,
        [_CASE_ID],
        warm=False,
        slide_source_factory=lambda _settings: cold,
    )
    assert code == 1
    assert cold.keys == []
    assert f"FAIL slide {_SLIDE_ID} file missing " in out

    warm = _Recorder(tmp_path / "warm")
    code, out, _err = _run(
        capsys,
        settings,
        [_CASE_ID],
        warm=True,
        slide_source_factory=lambda _settings: warm,
    )
    assert code == 0
    assert warm.closed is True
    assert "slides/fixture-he-rose.svs" in warm.keys
    assert f"thumbs/{_SLIDE_ID}.pack" in warm.keys
    assert f"PASS slide {_SLIDE_ID} opens 8x8" in out


def test_api_stub_warns_and_missing_server_fails(capsys: pytest.CaptureFixture[str]) -> None:
    def router(path: str, method: str) -> tuple[int, bytes | str, str]:
        del method
        if path == "/api/health":
            return 200, '{"status":"ok"}', "application/json"
        if path == f"/api/cases/{_CASE_ID}":
            return (
                404,
                '{"error":{"code":"not_found","message":"Case not found."}}',
                "application/json",
            )
        if path == f"/api/cases/{CASE_SIGNED_BREAST}":
            return 200, '{"id":"placeholder","slides":[]}', "application/json"
        if path == "/api/search/reports":
            return 501, '{"error":{"code":"stub","message":"not implemented"}}', "application/json"
        return 404, "{}", "application/json"

    with _http(router) as (base, posts):
        code, out, _err = _run(capsys, _down_settings(), [_CASE_ID], api_base=base)
    assert code == 1
    assert "PASS api.health ok" in out
    warning = (
        f"WARN api.case {_CASE_ID} HTTP 404; "
        "case route still serves the placeholder store"
    )
    assert warning in out
    assert "WARN api.reports stub HTTP 501; report encoder was not warmed" in out
    assert "WARN api.heatmap no slide to warm; pass --case" in out
    assert json.loads(posts[0][1]) == {"text": "adenocarcinoma"}

    code, out, _err = _run(capsys, _down_settings(), api_base="http://127.0.0.1:1")
    assert code == 1
    assert "FAIL api.health " in out


def test_api_case_404_without_placeholder_fails(capsys: pytest.CaptureFixture[str]) -> None:
    def router(path: str, method: str) -> tuple[int, bytes | str, str]:
        del method
        if path == "/api/health":
            return 200, '{"status":"ok"}', "application/json"
        return (
            404,
            '{"error":{"code":"not_found","message":"Case not found."}}',
            "application/json",
        )

    with _http(router) as (base, _posts):
        _code, out, _err = _run(capsys, _down_settings(), [_CASE_ID], api_base=base)
    assert f"FAIL api.case {_CASE_ID} HTTP 404" in out
    assert "placeholder" not in out


def test_api_pass_and_stub_payload(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _seeded(empty_database, tmp_path)

    def ok(path: str, method: str) -> tuple[int, bytes | str, str]:
        if path == "/api/health":
            return 200, '{"status":"ok"}', "application/json"
        if path == f"/api/cases/{_CASE_ID}":
            body = json.dumps({"id": _CASE_ID, "slides": [{"id": _SLIDE_ID}]})
            return 200, body, "application/json"
        if path == f"/api/slides/{_SLIDE_ID}.dzi":
            return 200, _DZI, "application/xml"
        if path == f"/api/slides/{_SLIDE_ID}/thumbnail":
            return 200, _JPEG, "image/jpeg"
        if path.startswith(f"/api/slides/{_SLIDE_ID}_files/") and path.endswith("/0_0.jpeg"):
            return 200, _JPEG, "image/jpeg"
        if method == "POST" and path == f"/api/slides/{_SLIDE_ID}/heatmap":
            return 200, '{"patches":[]}', "application/json"
        if method == "POST" and path == "/api/search/reports":
            body = '{"query_kind":"reports","hits":[],"total_candidates":0,"took_ms":12}'
            return 200, body, "application/json"
        return 500, "unexpected", "text/plain"

    before = _snapshot(empty_database)
    with _http(ok) as (base, posts):
        code, out, err = _run(capsys, settings, [_CASE_ID], api_base=base)
    assert err == ""
    assert code == 0
    assert _snapshot(empty_database) == before
    assert f"PASS api.case {_CASE_ID} HTTP 200" in out
    assert f"PASS api.dzi {_SLIDE_ID} HTTP 200" in out
    assert f"PASS api.thumbnail {_SLIDE_ID} HTTP 200" in out
    assert f"PASS api.tiles {_SLIDE_ID} levels 0,1,2" in out
    assert f"PASS api.heatmap {_SLIDE_ID} glandular " in out
    assert "PASS api.reports adenocarcinoma " in out
    bodies = [json.loads(body) for _path, body in posts]
    assert {"text": "glandular"} in bodies
    assert {"text": "adenocarcinoma"} in bodies

    def stub(path: str, method: str) -> tuple[int, bytes | str, str]:
        if path == "/api/search/reports":
            return 200, '{"stub": true}', "application/json"
        return ok(path, method)

    with _http(stub) as (base, _posts):
        code, out, _err = _run(capsys, settings, [_CASE_ID], api_base=base)
    assert code == 0
    assert "WARN api.reports stub HTTP 200; report encoder was not warmed" in out


def test_live_server_on_fixture_data(
    empty_database: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _seeded(empty_database, tmp_path)
    app = create_app(settings, use_stub_store=False)
    app.state.text_encoders = build_text_encoders(backend=MockTextEncoder())
    with _uvicorn(app) as base:
        code, out, err = _run(capsys, settings, [_CASE_ID], api_base=base, http_timeout=30)
    assert "Traceback" not in err
    assert "PASS api.health ok" in out
    assert f"PASS api.case {_CASE_ID} HTTP 200" in out
    assert f"PASS api.dzi {_SLIDE_ID} HTTP 200" in out
    assert f"PASS api.thumbnail {_SLIDE_ID} HTTP 200" in out
    assert f"PASS api.tiles {_SLIDE_ID} levels 0,1,2" in out
    assert f"PASS api.heatmap {_SLIDE_ID} glandular " in out
    assert "PASS api.reports adenocarcinoma " in out
    assert code == 0


class _Recorder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.keys: list[str] = []
        self.closed = False

    def path_for(self, key: str) -> Path:
        self.keys.append(key)
        path = self.root / "blob"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"pack-bytes")
        return path

    def acquire(self, key: str) -> object:
        self.keys.append(f"open:{key}")
        return SimpleNamespace(lock=threading.Lock(), slide=SimpleNamespace(dimensions=(8, 8)))

    def release(self, handle: object) -> None:
        del handle

    def close(self) -> None:
        self.closed = True


def _snapshot(url: str) -> tuple[tuple[str, ...], dict[str, int]]:
    tables = (
        "pathologist",
        "patient",
        "path_case",
        "slide",
        "patch",
        "report",
        "report_chunk",
        "concept",
    )
    with connect(url, register=False) as conn:
        migrations = conn.execute(
            "select filename from schema_migration order by filename"
        ).fetchall()
        counts = {
            table: int(conn.execute(f"select count(*) from {table}").fetchone()[0])
            for table in tables
        }
    return tuple(row[0] for row in migrations), counts


@contextmanager
def _uvicorn(app: object) -> Iterator[str]:
    import socket

    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("API server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _forbid_http(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("preflight made an HTTP call")


def _forbid_anthropic(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("preflight constructed an Anthropic client")
