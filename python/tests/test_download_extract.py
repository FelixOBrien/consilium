"""Download streaming, SVS header parsing, and the TRIDENT extract wrapper."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import h5py
import numpy as np
import pyarrow.parquet as pq
import pytest

from consilium.pipeline.__main__ import main  # pragma: allowlist secret
from consilium.pipeline.download import download_cohort, read_cohort_csv  # pragma: allowlist secret
from consilium.pipeline.extract import (  # pragma: allowlist secret
    CONCH_V15_DIM,
    build_trident_command,
    coords_h5_path,
    extract_cohort,
    fallback_mpp,
    features_h5_path,
    geometry_from_properties,
    level0_patch_px,
    trident_magnification,
    validate_features,
)

COLUMNS = (
    "case_id",
    "slide_id",
    "gdc_file_id",
    "file_name",
    "file_size",
    "project_id",
    "specialty",
    "tier",
    "held_out",
)


class _Store:
    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {}
        self.md5: dict[str, str] = {}
        self.meta_size: dict[str, int] = {}
        self.data_hits: dict[str, int] = {}
        self.meta_hits: dict[str, int] = {}
        self.fail_remaining: dict[str, int] = {}
        self.status: dict[str, int] = {}
        self.hold_id: str | None = None
        self.started = threading.Event()
        self.hold = threading.Event()
        self.lock = threading.Lock()

    def add(
        self,
        file_id: str,
        body: bytes,
        *,
        md5: str | None = None,
        meta_size: int | None = None,
        fail: int = 0,
        status: int | None = None,
    ) -> None:
        self.bodies[file_id] = body
        self.md5[file_id] = md5 if md5 is not None else hashlib.md5(body).hexdigest()
        self.meta_size[file_id] = len(body) if meta_size is None else meta_size
        self.fail_remaining[file_id] = fail
        if status is not None:
            self.status[file_id] = status


def _handler(store: _Store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 2:
                self._send(404, b"missing", "text/plain")
                return
            kind, file_id = parts
            if kind == "files":
                self._meta(file_id)
            elif kind == "data":
                self._data(file_id)
            else:
                self._send(404, b"missing", "text/plain")

        def _meta(self, file_id: str) -> None:
            with store.lock:
                store.meta_hits[file_id] = store.meta_hits.get(file_id, 0) + 1
                payload = {
                    "data": {
                        "md5sum": store.md5[file_id],
                        "file_size": store.meta_size[file_id],
                    }
                }
            self._send(200, json.dumps(payload).encode(), "application/json")

        def _data(self, file_id: str) -> None:
            with store.lock:
                store.data_hits[file_id] = store.data_hits.get(file_id, 0) + 1
                remaining = store.fail_remaining.get(file_id, 0)
                if remaining > 0:
                    store.fail_remaining[file_id] = remaining - 1
                    self._send(503, b"busy", "text/plain")
                    return
                status = store.status.get(file_id)
                body = store.bodies[file_id]
            if status is not None:
                self._send(status, b"no", "text/plain")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if file_id == store.hold_id:
                self.wfile.write(body[:1])
                self.wfile.flush()
                store.started.set()
                if not store.hold.wait(5):
                    return
                self.wfile.write(body[1:])
            else:
                self.wfile.write(body)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class _Server:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(store))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        host, port = self._httpd.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def _cohort(path: Path, rows: list[dict[str, object]]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(COLUMNS)
    if any("md5sum" in row for row in rows):
        fields.append("md5sum")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fields})


def _row(slide_id: str, file_id: str, size: int, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "case_id": f"case-{slide_id}",
        "slide_id": slide_id,
        "gdc_file_id": file_id,
        "file_name": f"{slide_id}.svs",
        "file_size": size,
        "project_id": "TCGA-BRCA",
        "specialty": "breast",
        "tier": "smoke",
        "held_out": "false",
    }
    row.update(extra)
    return row


def _clock(start: float, end: float):
    values = iter((start, end))

    def clock() -> float:
        return next(values)

    return clock


class _Headers:
    def __init__(self, table: Mapping[str, tuple[int, int, dict[str, str]] | Exception]) -> None:
        self.table = table

    def read(self, path: Path) -> tuple[int, int, Mapping[str, str]]:
        item = self.table[path.name]
        if isinstance(item, Exception):
            raise item
        width, height, properties = item
        return width, height, properties


def _write_pair(
    job_dir: Path,
    slide_id: str,
    *,
    count: int = 4,
    dim: int = CONCH_V15_DIM,
    level0: int = 1024,
    encoder: str = "conch_v15",
    features: bool = True,
) -> None:
    coords_path = coords_h5_path(job_dir, slide_id)
    coords_path.parent.mkdir(parents=True, exist_ok=True)
    coords = np.arange(count * 2, dtype=np.int64).reshape(count, 2)
    with h5py.File(coords_path, "w") as handle:
        dataset = handle.create_dataset("coords", data=coords)
        dataset.attrs["patch_size"] = 512
        dataset.attrs["patch_size_level0"] = level0
        dataset.attrs["target_magnification"] = 20
        dataset.attrs["overlap"] = 0
        dataset.attrs["level0_magnification"] = 40
    if not features:
        return
    features_path = features_h5_path(job_dir, slide_id)
    features_path.parent.mkdir(parents=True, exist_ok=True)
    values = np.zeros((count, dim), dtype=np.float32)
    with h5py.File(features_path, "w") as handle:
        dataset = handle.create_dataset("features", data=values)
        dataset.attrs["encoder"] = encoder
        dataset.attrs["name"] = slide_id
        handle.create_dataset("coords", data=coords)


def test_concurrent_download_verifies_md5_and_renames_part(tmp_path: Path) -> None:
    store = _Store()
    bodies = {f"id-{index}": f"slide-{index}-bytes".encode() * 20 for index in range(4)}
    for file_id, body in bodies.items():
        store.add(file_id, body)
    server = _Server(store)
    try:
        cohort = tmp_path / "cohort.csv"
        _cohort(
            cohort,
            [
                _row(f"slide-{index}", f"id-{index}", len(bodies[f"id-{index}"]))
                for index in range(4)
            ],
        )
        result = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=4,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
            clock=_clock(0.0, 8.0),
        )
    finally:
        server.close()
    assert result.attempted == 4
    assert result.succeeded == 4
    assert result.skipped == 0
    assert result.failed == 0
    assert result.seconds_per_slide == pytest.approx(2.0)
    assert result.projected_demo_slides == 200
    assert result.projected_demo_seconds == pytest.approx(400.0)
    for index, body in enumerate(bodies.values()):
        path = tmp_path / "slides" / f"slide-{index}.svs"
        assert path.read_bytes() == body
        assert not path.with_suffix(".svs.part").exists()
        assert hashlib.md5(body).hexdigest() == result.slides[index].md5
    report = json.loads((tmp_path / "trident" / "download_report.json").read_text())
    assert report["succeeded"] == 4
    assert "seconds_per_slide 2.000" in result.summary()
    assert "projected_demo_seconds 400.000" in result.summary()


def test_partial_file_is_visible_before_atomic_rename(tmp_path: Path) -> None:
    body = b"abcdefghij"
    store = _Store()
    store.add("held", body)
    store.hold_id = "held"
    server = _Server(store)
    destination = tmp_path / "slides" / "held.svs"
    partial = tmp_path / "slides" / "held.svs.part"
    holder: dict[str, object] = {}

    def run() -> None:
        holder["result"] = download_cohort(
            cohort_csv=_write_held(tmp_path, len(body)),
            data_root=tmp_path,
            workers=1,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
        )

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert store.started.wait(5)
        seen = False
        deadline = time.time() + 5
        while time.time() < deadline:
            if partial.exists() and not destination.exists():
                seen = True
                break
            time.sleep(0.01)
        assert seen
    finally:
        store.hold.set()
        worker.join(10)
        server.close()
    assert not worker.is_alive()
    result = holder["result"]
    assert result.succeeded == 1
    assert destination.read_bytes() == body
    assert not partial.exists()


def _write_held(root: Path, size: int) -> Path:
    path = root / "cohort.csv"
    _cohort(path, [_row("held", "held", size)])
    return path


def test_md5_and_size_mismatches_are_rejected(tmp_path: Path) -> None:
    good = b"good-slide"
    store = _Store()
    store.add("bad-md5", b"xxxx-slide", md5=hashlib.md5(good).hexdigest())
    store.add("too-big", b"0123456789", meta_size=4)
    store.add("ok", b"ok-slide")
    server = _Server(store)
    try:
        cohort = tmp_path / "cohort.csv"
        _cohort(
            cohort,
            [
                _row("bad-md5", "bad-md5", len(b"xxxx-slide")),
                _row("too-big", "too-big", 4),
                _row("ok", "ok", len(b"ok-slide")),
            ],
        )
        result = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=3,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
        )
    finally:
        server.close()
    by_id = {slide.slide_id: slide for slide in result.slides}
    assert by_id["bad-md5"].status == "failed"
    assert "md5" in (by_id["bad-md5"].error or "")
    assert by_id["too-big"].status == "failed"
    assert "manifest size" in (by_id["too-big"].error or "")
    assert by_id["ok"].status == "downloaded"
    assert result.succeeded == 1
    assert result.failed == 2
    assert not (tmp_path / "slides" / "bad-md5.svs").exists()
    assert not (tmp_path / "slides" / "too-big.svs").exists()
    assert not (tmp_path / "slides" / "bad-md5.svs.part").exists()
    assert "failure bad-md5" in result.summary()


def test_second_download_is_a_size_noop_unless_verify_md5(tmp_path: Path) -> None:
    body = b"already-there"
    store = _Store()
    store.add("once", body)
    server = _Server(store)
    try:
        cohort = tmp_path / "cohort.csv"
        _cohort(cohort, [_row("once", "once", len(body))])
        first = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=1,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
        )
        hits_after_first = store.data_hits["once"]
        second = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=1,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
            clock=_clock(5.0, 5.0),
        )
        assert store.data_hits["once"] == hits_after_first
        assert second.skipped == 1
        assert second.succeeded == 0
        assert second.seconds_per_slide is None
        assert "seconds_per_slide n/a" in second.summary()
        corrupt = tmp_path / "slides" / "once.svs"
        corrupt.write_bytes(b"x" * len(body))
        ignored = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=1,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
        )
        assert ignored.skipped == 1
        assert store.data_hits["once"] == hits_after_first
        checked = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=1,
            verify_md5=True,
            base_url=server.base_url,
            sleeper=lambda _delay: None,
        )
    finally:
        server.close()
    assert first.succeeded == 1
    assert checked.succeeded == 1
    assert (tmp_path / "slides" / "once.svs").read_bytes() == body


def test_retry_then_continue_after_a_permanent_failure(tmp_path: Path) -> None:
    body = b"retry-me"
    store = _Store()
    store.add("flaky", body, fail=2)
    store.add("missing", b"nope", status=404)
    sleeps: list[float] = []
    server = _Server(store)
    try:
        cohort = tmp_path / "cohort.csv"
        _cohort(
            cohort,
            [_row("flaky", "flaky", len(body)), _row("missing", "missing", 4)],
        )
        result = download_cohort(
            cohort_csv=cohort,
            data_root=tmp_path,
            workers=2,
            retries=4,
            base_url=server.base_url,
            sleeper=sleeps.append,
        )
    finally:
        server.close()
    by_id = {slide.slide_id: slide for slide in result.slides}
    assert by_id["flaky"].status == "downloaded"
    assert by_id["flaky"].attempts == 3
    assert sleeps == [0.5, 1.0]
    assert by_id["missing"].status == "failed"
    assert "HTTP 404" in (by_id["missing"].error or "")
    assert result.succeeded == 1
    assert result.failed == 1
    assert (tmp_path / "slides" / "flaky.svs").read_bytes() == body


def test_cli_download_reports_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = b"cli-slide"
    store = _Store()
    store.add("cli", body)
    store.add("gone", b"zz", status=404)
    server = _Server(store)
    try:
        cohort = tmp_path / "cohort.csv"
        _cohort(
            cohort,
            [_row("cli", "cli", len(body)), _row("gone", "gone", 2)],
        )
        code = main(
            [
                "download",
                "--data-root",
                str(tmp_path),
                "--cohort",
                str(cohort),
                "--workers",
                "2",
                "--gdc-base-url",
                server.base_url,
            ]
        )
    finally:
        server.close()
    captured = capsys.readouterr()
    assert code == 1
    assert "succeeded 1" in captured.out
    assert "failed 1" in captured.out
    assert "failure gone" in captured.out
    assert (tmp_path / "slides" / "cli.svs").read_bytes() == body


def test_cohort_rejects_duplicate_and_unsafe_ids(tmp_path: Path) -> None:
    path = tmp_path / "cohort.csv"
    _cohort(path, [_row("a", "a", 1), _row("a", "b", 1)])
    with pytest.raises(ValueError, match="duplicate"):
        read_cohort_csv(path)
    _cohort(path, [_row("../a", "a", 1)])
    with pytest.raises(ValueError, match="unsafe"):
        read_cohort_csv(path)


def test_header_mpp_and_magnification_fallbacks() -> None:
    both = geometry_from_properties(
        "s",
        "c",
        1000,
        800,
        {"openslide.mpp-x": "0.2524", "aperio.MPP": "0.9", "openslide.objective-power": "40"},
    )
    assert both.mpp == pytest.approx(0.2524)
    assert both.mpp_source == "openslide.mpp-x"
    assert both.magnification == pytest.approx(40)
    assert both.trident_magnification == 40
    assert both.patch_size_level0 == 1024
    assert both.error is None

    aperio = geometry_from_properties(
        "s",
        "c",
        100,
        80,
        {"aperio.MPP": "0.5015", "aperio.AppMag": "20"},
    )
    assert aperio.mpp_source == "aperio.MPP"
    assert aperio.magnification_source == "aperio.AppMag"
    assert aperio.trident_magnification == 20
    assert aperio.patch_size_level0 == 512

    fallback = geometry_from_properties("s", "c", 100, 80, {"aperio.AppMag": "40"})
    assert fallback.mpp == pytest.approx(0.25)
    assert fallback.mpp_source == "magnification_fallback"
    assert fallback.patch_size_level0 == 1024

    from_mpp = geometry_from_properties("s", "c", 100, 80, {"openslide.mpp-x": "0.5015"})
    assert from_mpp.magnification == pytest.approx(20)
    assert from_mpp.magnification_source == "mpp"
    assert from_mpp.patch_size_level0 == 512

    missing = geometry_from_properties("s", "c", 100, 80, {})
    assert missing.error is not None
    assert "microns-per-pixel" in missing.error
    assert missing.patch_size_level0 is None

    blank = geometry_from_properties("s", "c", 0, 10, {"openslide.mpp-x": "0.5"})
    assert blank.error is not None
    assert "dimensions" in blank.error
    assert level0_patch_px(40) == 1024
    assert level0_patch_px(20) == 512
    assert trident_magnification(0.5015) == 20
    assert fallback_mpp(40) == pytest.approx(0.25)
    assert fallback_mpp(20) == pytest.approx(0.5)


def test_trident_command_uses_upstream_flags() -> None:
    command = build_trident_command(
        wsi_dir=Path("/data/slides"),
        job_dir=Path("/data/trident"),
        custom_list=Path("/data/trident/custom_list_of_wsis.csv"),
        gpu=0,
        segmenter="hest",
    )
    assert command == [
        "trident",
        "batch",
        "--",
        "--task",
        "all",
        "--wsi_dir",
        "/data/slides",
        "--job_dir",
        "/data/trident",
        "--custom_list_of_wsis",
        "/data/trident/custom_list_of_wsis.csv",
        "--wsi_ext",
        ".svs",
        "--reader_type",
        "openslide",
        "--segmenter",
        "hest",
        "--mag",
        "20",
        "--patch_size",
        "512",
        "--overlap",
        "0",
        "--patch_encoder",
        "conch_v15",
        "--skip_errors",
        "--clear_dead_locks",
        "--gpus",
        "0",
    ]


def test_h5_validation_and_idempotent_skip(tmp_path: Path) -> None:
    _touch_slide(tmp_path, "ready")
    _write_pair(tmp_path / "trident", "ready", count=3, level0=1024)
    calls: list[list[str]] = []
    cohort = tmp_path / "cohort.csv"
    _cohort(cohort, [_row("ready", "file-ready", 10)])
    result = extract_cohort(
        cohort_csv=cohort,
        data_root=tmp_path,
        header_source=_Headers({"ready.svs": (4000, 3000, _forty())}),
        runner=lambda command: calls.append(list(command)) or 0,
        clock=_clock(0.0, 3.0),
    )
    assert calls == []
    assert result.skipped == 1
    assert result.succeeded == 0
    assert result.failed == 0
    assert result.total_patches == 3
    assert result.command is None
    assert result.seconds_per_slide is None
    assert "total_patches 3" in result.summary()
    count, error = validate_features(
        tmp_path / "trident", "ready", expected_level0=1024
    )
    assert error is None
    assert count == 3
    _write_pair(tmp_path / "trident", "ready", dim=4)
    count, error = validate_features(tmp_path / "trident", "ready", expected_level0=1024)
    assert count is None
    assert error is not None
    assert "768" in error


def test_extract_invokes_trident_and_projects_demo_time(tmp_path: Path) -> None:
    _touch_slide(tmp_path, "one")
    _touch_slide(tmp_path, "two")
    cohort = tmp_path / "cohort.csv"
    _cohort(cohort, [_row("one", "f1", 10), _row("two", "f2", 10)])
    calls: list[list[str]] = []

    def runner(command: list[str]) -> int:
        calls.append(list(command))
        _write_pair(tmp_path / "trident", "one", count=5, level0=1024)
        return 7

    result = extract_cohort(
        cohort_csv=cohort,
        data_root=tmp_path,
        header_source=_Headers(
            {
                "one.svs": (8000, 6000, _forty()),
                "two.svs": (8000, 6000, {"aperio.AppMag": "40"}),
            }
        ),
        runner=runner,
        clock=_clock(10.0, 18.0),
    )
    assert len(calls) == 1
    assert "--patch_encoder" in calls[0]
    assert calls[0][calls[0].index("--patch_encoder") + 1] == "conch_v15"
    assert calls[0][calls[0].index("--mag") + 1] == "20"
    assert calls[0][calls[0].index("--patch_size") + 1] == "512"
    assert "--skip_errors" in calls[0]
    custom = (tmp_path / "trident" / "custom_list_of_wsis.csv").read_text()
    assert "one.svs,0.25" in custom
    assert "two.svs,0.25" in custom
    by_id = {slide.slide_id: slide for slide in result.slides}
    assert by_id["one"].status == "extracted"
    assert by_id["one"].patch_count == 5
    assert by_id["two"].status == "failed"
    assert "trident exit 7" in (by_id["two"].error or "")
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.total_patches == 5
    assert result.seconds_per_slide == pytest.approx(8.0)
    assert result.projected_demo_seconds == pytest.approx(1600.0)
    table = pq.read_table(tmp_path / "trident" / "slide_headers.parquet")
    assert table.column("patch_size_level0").to_pylist() == [1024, 1024]
    assert table.column("mpp_source").to_pylist()[1] == "magnification_fallback"
    report = json.loads((tmp_path / "trident" / "extract_report.json").read_text())
    assert report["total_patches"] == 5
    assert report["command"][0] == "trident"


def test_extract_keeps_valid_coords_and_records_unreadable_slides(tmp_path: Path) -> None:
    _touch_slide(tmp_path, "coords-only")
    _touch_slide(tmp_path, "broken")
    _write_pair(tmp_path / "trident", "coords-only", count=2, level0=512, features=False)
    coords = coords_h5_path(tmp_path / "trident", "coords-only")
    stamp = coords.stat().st_mtime_ns
    cohort = tmp_path / "cohort.csv"
    _cohort(
        cohort,
        [
            _row("coords-only", "c1", 10),
            _row("broken", "c2", 10),
            _row("absent", "c3", 10),
        ],
    )

    def runner(command: list[str]) -> int:
        assert coords.stat().st_mtime_ns == stamp
        features_path = features_h5_path(tmp_path / "trident", "coords-only")
        features_path.parent.mkdir(parents=True, exist_ok=True)
        values = np.zeros((2, CONCH_V15_DIM), dtype=np.float32)
        saved = np.arange(4, dtype=np.int64).reshape(2, 2)
        with h5py.File(features_path, "w") as handle:
            dataset = handle.create_dataset("features", data=values)
            dataset.attrs["encoder"] = "conch_v15"
            handle.create_dataset("coords", data=saved)
        return 0

    result = extract_cohort(
        cohort_csv=cohort,
        data_root=tmp_path,
        header_source=_Headers(
            {
                "coords-only.svs": (100, 80, {"openslide.mpp-x": "0.5015", "aperio.AppMag": "20"}),
                "broken.svs": RuntimeError("not an svs"),
            }
        ),
        runner=runner,
    )
    by_id = {slide.slide_id: slide for slide in result.slides}
    assert by_id["coords-only"].status == "extracted"
    assert by_id["coords-only"].patch_count == 2
    assert coords.stat().st_mtime_ns == stamp
    assert by_id["broken"].status == "failed"
    assert "unreadable" in (by_id["broken"].error or "")
    assert by_id["absent"].status == "failed"
    assert "missing" in (by_id["absent"].error or "")
    assert result.succeeded == 1
    assert result.failed == 2


def test_invalid_h5_is_rebuilt_on_the_next_run(tmp_path: Path) -> None:
    _touch_slide(tmp_path, "again")
    _write_pair(tmp_path / "trident", "again", dim=8, level0=1024)
    cohort = tmp_path / "cohort.csv"
    _cohort(cohort, [_row("again", "f", 10)])
    calls = {"n": 0}

    def runner(command: list[str]) -> int:
        calls["n"] += 1
        _write_pair(tmp_path / "trident", "again", count=6, level0=1024)
        return 0

    result = extract_cohort(
        cohort_csv=cohort,
        data_root=tmp_path,
        header_source=_Headers({"again.svs": (10, 10, _forty())}),
        runner=runner,
    )
    assert calls["n"] == 1
    assert result.succeeded == 1
    assert result.slides[0].patch_count == 6
    second = extract_cohort(
        cohort_csv=cohort,
        data_root=tmp_path,
        header_source=_Headers({"again.svs": (10, 10, _forty())}),
        runner=runner,
    )
    assert calls["n"] == 1
    assert second.skipped == 1
    assert second.succeeded == 0


def test_pipeline_help_lists_download_and_extract() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "consilium.pipeline", "--help"],  # pragma: allowlist secret
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    output = " ".join(result.stdout.split())
    assert "manifest" in output
    assert "download" in output
    assert "extract" in output
    assert "not for clinical use" in output


def _touch_slide(root: Path, slide_id: str) -> None:
    path = root / "slides" / f"{slide_id}.svs"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"svs")


def _forty() -> dict[str, str]:
    return {"openslide.mpp-x": "0.25", "openslide.objective-power": "40", "aperio.MPP": "0.25"}
