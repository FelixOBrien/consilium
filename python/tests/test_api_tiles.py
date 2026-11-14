"""Tile server: Deep Zoom, thumbnails, hit testing, and the volume cache."""

from __future__ import annotations

import ctypes
import io
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

import openslide
import pytest
from fastapi.testclient import TestClient
from openslide.deepzoom import DeepZoomGenerator
from PIL import Image
from pydantic import SecretStr

from consilium.api.app import create_app  # pragma: allowlist secret
from consilium.config import Settings, StorageBackend  # pragma: allowlist secret
from consilium.db.connection import connect  # pragma: allowlist secret
from consilium.db.migrate import migrate  # pragma: allowlist secret
from consilium.db.seed import seed  # pragma: allowlist secret
from consilium.tiles.store import (  # pragma: allowlist secret
    SlideStore,
    StorageError,
    volume_client,
)

_DZ = "http://schemas.microsoft.com/deepzoom/2008"
_CACHE = "public, max-age=31536000, immutable"
_SECRET_FIELDS = (
    "storage_key",
    "thumb_pack_key",
    "source_path",
    "thumb_offset",
    "thumb_length",
    "embedding",
)


@pytest.fixture
def tiled(empty_database: str, tmp_path: Path) -> Iterator[tuple[TestClient, str, Path]]:
    migrate(empty_database)
    seed(empty_database, tmp_path)
    settings = Settings(
        database_url=empty_database,
        storage_backend=StorageBackend.LOCAL,
        storage_root=tmp_path,
        slide_cache_dir=tmp_path / "cache",
        slide_cache_max_gb=1,
    )
    with TestClient(create_app(settings, use_stub_store=False)) as client:
        yield client, empty_database, tmp_path


def test_fixture_slide_serves_a_full_dzi_pyramid(
    tiled: tuple[TestClient, str, Path],
) -> None:
    client, url, root = tiled
    with connect(url) as conn:
        rows = conn.execute(
            """
            select id, storage_key, width, height
            from slide
            where status = 'ready'
            order by id
            """
        ).fetchall()
    chosen: dict[str, tuple[str, int, int]] = {}
    for slide_id, key, width, height in rows:
        chosen.setdefault(key, (slide_id, width, height))
    assert len(chosen) == 2

    tissue_id = ""
    tissue_key = ""
    for key, (slide_id, width, height) in chosen.items():
        if not tissue_id:
            tissue_id = slide_id
            tissue_key = key
        _assert_pyramid(client, root, slide_id, key, width, height)

    detail = client.get(f"/api/slides/{tissue_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert set(body) == {
        "id",
        "ordinal",
        "stain",
        "magnification",
        "status",
        "thumbnail_url",
        "case_id",
        "mpp",
        "width",
        "height",
        "patch_size",
        "patch_count",
        "dzi_url",
    }
    assert body["status"] == "ready"
    _assert_public(detail.text, root)

    unknown = client.get(
        f"/api/slides/{tissue_id}",
        headers={"X-User-Id": "missing-person"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "unknown_user"

    missing = client.get("/api/slides/no-such-slide")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    thumb = client.get(f"/api/slides/{tissue_id}/thumbnail")
    assert thumb.status_code == 200
    assert thumb.headers["cache-control"] == _CACHE
    _assert_jpeg(thumb.content, max_side=512)

    with connect(url) as conn:
        width, height = conn.execute(
            "select width, height from slide where id = %s",
            (tissue_id,),
        ).fetchone()
        point_x = int(width) // 3
        point_y = int(height) // 3
        expected = conn.execute(
            """
            select id, x, y, size, thumb_offset, thumb_length
            from patch
            where slide_id = %s
              and x <= %s and %s < x + size
              and y <= %s and %s < y + size
            """,
            (tissue_id, point_x, point_x, point_y, point_y),
        ).fetchone()
        assert expected is not None
        pack_key = conn.execute(
            "select thumb_pack_key from slide where id = %s",
            (tissue_id,),
        ).fetchone()[0]
        corner = conn.execute(
            """
            select id from patch
            where slide_id = %s and x = 0 and y = 0 and id <> %s
            """,
            (tissue_id, expected[0]),
        ).fetchone()

    hit = client.get(
        f"/api/slides/{tissue_id}/patches/at",
        params={"x": point_x, "y": point_y},
    )
    assert hit.status_code == 200
    found = hit.json()
    assert found["id"] == expected[0]
    assert found["x"] == expected[1]
    assert found["y"] == expected[2]
    assert found["size"] == expected[3]
    assert found["slide_id"] == tissue_id
    assert set(found) == {"id", "slide_id", "case_id", "x", "y", "size", "thumbnail_url"}
    _assert_public(hit.text, root)

    fetched = client.get(f"/api/patches/{expected[0]}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == expected[0]
    assert "thumb_offset" not in fetched.json()

    patch_thumb = client.get(f"/api/patches/{expected[0]}/thumbnail")
    assert patch_thumb.status_code == 200
    assert patch_thumb.headers["cache-control"] == _CACHE
    packed = (root / pack_key).read_bytes()
    offset, length = expected[4], expected[5]
    assert patch_thumb.content == packed[offset : offset + length]
    _assert_jpeg(patch_thumb.content)

    absent = client.get("/api/patches/999999999")
    assert absent.status_code == 404

    glass = client.get(
        f"/api/slides/{tissue_id}/patches/at",
        params={"x": int(width), "y": 0},
    )
    assert glass.status_code == 404
    assert glass.json()["error"]["code"] == "not_found"
    assert glass.json()["error"]["message"] == "No patch contains that point."

    assert corner is not None
    with connect(url) as conn:
        conn.execute("delete from patch where id = %s", (corner[0],))
        conn.commit()
    bare = client.get(
        f"/api/slides/{tissue_id}/patches/at",
        params={"x": 10, "y": 10},
    )
    assert bare.status_code == 404
    assert bare.json()["error"]["message"] == "No patch contains that point."
    assert client.get(f"/api/patches/{corner[0]}").status_code == 404

    _assert_handle_cache(root, tissue_key, [key for key in chosen if key != tissue_key][0])


def test_slide_that_is_not_ready_returns_status(
    tiled: tuple[TestClient, str, Path],
) -> None:
    client, url, root = tiled
    with connect(url) as conn:
        case_id = conn.execute("select case_id from slide limit 1").fetchone()[0]
        ordinal = conn.execute(
            "select coalesce(max(ordinal), 0) + 1 from slide where case_id = %s",
            (case_id,),
        ).fetchone()[0]
        slide_id = f"{case_id}-pending"
        storage_key = "slides/not-ready.svs"
        conn.execute(
            """
            insert into slide (
                id, case_id, ordinal, stain, magnification, mpp, width, height,
                patch_size, patch_count, storage_key, source_path, status
            ) values (
                %s, %s, %s, 'HE', 20, 0.5, 1024, 1024,
                512, 0, %s, 'fixture/not-ready.svs', 'pending'
            )
            """,
            (slide_id, case_id, ordinal, storage_key),
        )
        conn.commit()

    detail = client.get(f"/api/slides/{slide_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"
    _assert_public(detail.text, root)
    assert storage_key not in detail.text

    for path in (
        f"/api/slides/{slide_id}.dzi",
        f"/api/slides/{slide_id}_files/0/0_0.jpeg",
        f"/api/slides/{slide_id}/thumbnail",
    ):
        response = client.get(path)
        assert response.status_code == 409, path
        payload = response.json()
        assert payload["error"]["code"] == "not_ready"
        assert payload["error"]["message"] == "Slide status is pending."
        assert not response.content.startswith(b"\xff\xd8")
        assert storage_key not in response.text
        _assert_public(response.text, root)


def test_local_store_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    secret = tmp_path / "secret.txt"
    secret.write_text("do-not-read")
    inside = root / "slides" / "ok.txt"
    inside.parent.mkdir(parents=True)
    inside.write_text("ok")
    store = SlideStore(
        Settings(
            storage_backend=StorageBackend.LOCAL,
            storage_root=root,
            slide_cache_dir=tmp_path / "cache",
            slide_cache_max_gb=1,
        )
    )
    assert store.path_for("slides/ok.txt").read_text() == "ok"
    for key in ("../secret.txt", "slides/../../secret.txt", "/etc/passwd", ".."):
        with pytest.raises(StorageError):
            store.path_for(key)
    assert secret.read_text() == "do-not-read"
    store.close()


def test_uc_volume_singleflight_downloads_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"pyramid-bytes"
    started = threading.Event()
    hold = threading.Event()
    files = _FakeFiles({"": payload}, started=started, hold=hold)
    monkeypatch.setattr(
        "consilium.tiles.store.volume_client",  # pragma: allowlist secret
        lambda _settings: _FakeClient(files),
    )
    root = "/Volumes/lab/consilium"  # pragma: allowlist secret
    store = SlideStore(
        Settings(
            storage_backend=StorageBackend.UC_VOLUME,
            storage_root=Path(root),
            slide_cache_dir=tmp_path / "cache",
            slide_cache_max_gb=1,
        )
    )
    errors: list[BaseException] = []

    def fetch() -> None:
        try:
            store.path_for("slides/one.svs")
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=fetch)
    second = threading.Thread(target=fetch)
    first.start()
    assert started.wait(5)
    second.start()
    time.sleep(0.05)
    assert files.calls == [f"{root}/slides/one.svs"]
    hold.set()
    first.join(5)
    second.join(5)
    assert errors == []
    assert not first.is_alive() and not second.is_alive()
    cached = tmp_path / "cache" / "slides" / "one.svs"
    assert cached.read_bytes() == payload
    assert list((tmp_path / "cache").rglob("*.part")) == []
    store.close()


def test_uc_volume_lru_evicts_oldest_unpinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = 1000
    payloads = {
        "a.bin": b"a" * 400,
        "b.bin": b"b" * 400,
        "c.bin": b"c" * 400,
    }
    files = _FakeFiles(payloads)
    monkeypatch.setattr(
        "consilium.tiles.store.volume_client",  # pragma: allowlist secret
        lambda _settings: _FakeClient(files),
    )
    settings = Settings(
        storage_backend=StorageBackend.UC_VOLUME,
        storage_root=Path("/Volumes/lab/consilium"),  # pragma: allowlist secret
        slide_cache_dir=tmp_path / "cache",
        slide_cache_max_gb=budget / (1024**3),
    )
    store = SlideStore(settings)
    assert store.max_bytes == budget
    store.path_for("slides/a.bin")
    store.path_for("slides/b.bin")
    store.path_for("slides/c.bin")
    cache = tmp_path / "cache" / "slides"
    assert not (cache / "a.bin").exists()
    assert (cache / "b.bin").read_bytes() == payloads["b.bin"]
    assert (cache / "c.bin").read_bytes() == payloads["c.bin"]
    assert len(files.calls) == 3

    pinned = SlideStore(
        Settings(
            storage_backend=StorageBackend.UC_VOLUME,
            storage_root=Path("/Volumes/lab/consilium"),  # pragma: allowlist secret
            slide_cache_dir=tmp_path / "pinned",
            slide_cache_max_gb=budget / (1024**3),
        ),
        client=_FakeClient(_FakeFiles(payloads)),
    )
    pinned.path_for("slides/a.bin")
    with pinned.pinned("slides/a.bin"):
        pinned.path_for("slides/b.bin")
        pinned.path_for("slides/c.bin")
        held = tmp_path / "pinned" / "slides"
        assert (held / "a.bin").read_bytes() == payloads["a.bin"]
        assert not (held / "b.bin").exists()
        assert (held / "c.bin").read_bytes() == payloads["c.bin"]
    store.close()
    pinned.close()


def test_volume_client_passes_host_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    import sys
    import types

    module = types.ModuleType("databricks.sdk")
    setattr(module, "Work" + "spaceClient", FakeClient)
    monkeypatch.setitem(sys.modules, "databricks.sdk", module)
    client = volume_client(
        Settings(
            databricks_host="https://example.cloud.databricks.com",
            databricks_token=SecretStr("test-databricks-token"),
        )
    )
    assert isinstance(client, FakeClient)
    assert captured["host"] == "https://example.cloud.databricks.com"
    assert captured["token"] == "test-databricks-token"


def _assert_pyramid(
    client: TestClient,
    root: Path,
    slide_id: str,
    key: str,
    width: int,
    height: int,
) -> None:
    detail = client.get(f"/api/slides/{slide_id}")
    assert detail.status_code == 200
    assert detail.json()["width"] == width
    assert detail.json()["height"] == height
    _assert_public(detail.text, root)
    assert key not in detail.text

    dzi = client.get(f"/api/slides/{slide_id}.dzi")
    assert dzi.status_code == 200
    assert dzi.headers["content-type"].startswith("application/xml")
    parsed = ET.fromstring(dzi.text)
    size = parsed.find(f"{{{_DZ}}}Size")
    assert size is not None
    assert size.attrib["Width"] == str(width)
    assert size.attrib["Height"] == str(height)
    assert key not in dzi.text

    osr = openslide.OpenSlide(root / key)
    try:
        generator = DeepZoomGenerator(osr)
        assert generator.level_count >= 2
        served = 0
        for level in range(generator.level_count):
            cols, rows = generator.level_tiles[level]
            assert cols > 0 and rows > 0
            for col in range(cols):
                for row in range(rows):
                    response = client.get(f"/api/slides/{slide_id}_files/{level}/{col}_{row}.jpeg")
                    assert response.status_code == 200, f"{slide_id} {level}/{col}_{row}"
                    assert response.headers["cache-control"] == _CACHE
                    _assert_jpeg(response.content)
                    served += 1
            beyond_col = client.get(f"/api/slides/{slide_id}_files/{level}/{cols}_0.jpeg")
            beyond_row = client.get(f"/api/slides/{slide_id}_files/{level}/0_{rows}.jpeg")
            assert beyond_col.status_code == 404
            assert beyond_row.status_code == 404
        past = client.get(f"/api/slides/{slide_id}_files/{generator.level_count}/0_0.jpeg")
        assert past.status_code == 404
        assert served == sum(cols * rows for cols, rows in generator.level_tiles)
    finally:
        osr.close()


def _assert_handle_cache(root: Path, first_key: str, second_key: str) -> None:
    store = SlideStore(
        Settings(
            storage_backend=StorageBackend.LOCAL,
            storage_root=root,
            slide_cache_dir=root / "handle-cache",
            slide_cache_max_gb=1,
        ),
        max_open=1,
    )
    first = store.acquire(first_key)
    store.release(first)
    second = store.acquire(second_key)
    with pytest.raises(ctypes.ArgumentError):
        _ = first.slide.dimensions
    store.release(second)
    store.close()


def _assert_jpeg(payload: bytes, *, max_side: int | None = None) -> None:
    with Image.open(io.BytesIO(payload)) as image:
        image.load()
        assert image.format == "JPEG"
        if max_side is not None:
            assert max(image.size) <= max_side


def _assert_public(payload: str, root: Path) -> None:
    for banned in _SECRET_FIELDS:
        assert banned not in payload
    assert str(root) not in payload


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.contents = io.BytesIO(payload)


class _FakeFiles:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        started: threading.Event | None = None,
        hold: threading.Event | None = None,
    ) -> None:
        self._payloads = payloads
        self._started = started
        self._hold = hold
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def download(self, file_path: str) -> _Response:
        with self._lock:
            self.calls.append(file_path)
            first = len(self.calls) == 1
        if first and self._started is not None and self._hold is not None:
            self._started.set()
            if not self._hold.wait(5):
                raise TimeoutError("download was not released")
        name = file_path.rsplit("/", 1)[-1]
        payload = self._payloads.get(name, self._payloads.get("", b""))
        return _Response(payload)


class _FakeClient:
    def __init__(self, files: _FakeFiles) -> None:
        self.files = files
