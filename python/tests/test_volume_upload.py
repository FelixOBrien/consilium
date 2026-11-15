"""Volume uploads skip matching files and never echo a secret."""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from consilium.pipeline import __main__ as pipeline_main  # pragma: allowlist secret
from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret
from consilium.pipeline.volume import (  # pragma: allowlist secret
    VolumeUploadError,
    collect_uploads,
    files_client,
    upload_volume,
)

_ROOT = "/Volumes/main/consilium/raw"  # pragma: allowlist secret


class _Meta:
    def __init__(self, content_length: int) -> None:
        self.content_length = content_length


class _Files:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[str] = []
        self.deletes: list[str] = []
        self.directories: list[str] = []
        self.meta_error: BaseException | None = None
        self.corrupt = False

    def get_metadata(self, path: str) -> _Meta:
        if self.meta_error is not None:
            raise self.meta_error
        if path not in self.objects:
            raise FileNotFoundError(path)
        return _Meta(len(self.objects[path]))

    def upload(
        self,
        path: str,
        contents: object,
        overwrite: bool = True,
        use_parallel: bool = False,
    ) -> None:
        del overwrite, use_parallel
        data = contents.read()  # type: ignore[attr-defined]
        self.objects[path] = b"x" if self.corrupt else data
        self.uploads.append(path)

    def delete(self, path: str) -> None:
        self.deletes.append(path)
        self.objects.pop(path, None)

    def create_directory(self, path: str) -> None:
        self.directories.append(path)


class _Client:
    def __init__(self) -> None:
        self.files = _Files()


def test_matching_length_is_skipped_and_a_mismatch_is_replaced(tmp_path: Path) -> None:
    export, thumbs, slides = _tree(tmp_path)
    client = _Client()
    first = upload_volume(
        export,
        volume_root=_ROOT + "/",
        thumbs_dir=thumbs,
        slides_dir=slides,
        client=client,
    )
    assert any(name.startswith("export/") for name in first.uploaded)
    assert any(name.startswith("slides/") for name in first.uploaded)
    uploaded = list(client.files.uploads)
    second = upload_volume(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
        client=client,
    )
    assert second.uploaded == ()
    assert client.files.uploads == uploaded

    remote = f"{_ROOT}/slides/slide-a.svs"
    client.files.objects[remote] = b"short"
    third = upload_volume(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
        skip_slides=False,
        client=client,
    )
    assert "slides/slide-a.svs" in third.uploaded
    assert client.files.objects[remote] == (slides / "slide-a.svs").read_bytes()


def test_size_mismatch_after_upload_deletes_and_hides_the_exception(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    export, thumbs, slides = _tree(tmp_path)
    client = _Client()
    client.files.corrupt = True
    with pytest.raises(VolumeUploadError) as caught:
        upload_volume(
            export,
            volume_root=_ROOT,
            thumbs_dir=thumbs,
            slides_dir=slides,
            client=client,
        )
    message = str(caught.value)
    assert "size mismatch" in message
    assert "https://" not in message
    assert client.files.objects == {}


def test_remote_error_does_not_log_the_token(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    export, thumbs, slides = _tree(tmp_path)
    client = _Client()
    secret = "dapi-secret-value"
    client.files.meta_error = RuntimeError(f"https://example.cloud.databricks.com/?token={secret}")
    with pytest.raises(VolumeUploadError) as caught:
        upload_volume(
            export,
            volume_root=_ROOT,
            thumbs_dir=thumbs,
            slides_dir=slides,
            client=client,
            token=secret,
        )
    assert secret not in str(caught.value)
    assert secret not in caplog.text
    assert "https://" not in str(caught.value)
    assert "https://" not in caplog.text
    assert "RuntimeError" in str(caught.value)


def test_filters_and_missing_slides(tmp_path: Path) -> None:
    export, thumbs, slides = _tree(tmp_path)
    items, missing = collect_uploads(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
        case_ids={"case-a"},
    )
    relatives = {item.relative for item in items}
    assert "slides/slide-a.svs" in relatives
    assert "slides/slide-b.svs" not in relatives
    assert "thumbs/slide-a.pack" in relatives
    assert "thumbs/slide-b.index.json" not in relatives
    assert missing == []

    skipped, _missing = collect_uploads(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
        skip_slides=True,
    )
    assert all(not item.relative.startswith("slides/") for item in skipped)

    other = tmp_path / "subset"
    _write_slides(other, [("slide-b", "case-b")])
    selected, absent = collect_uploads(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
        slides_for_export=other,
    )
    names = {item.relative for item in selected}
    assert "slides/slide-b.svs" in names
    assert "slides/slide-a.svs" not in names
    assert absent == []

    (slides / "slide-b.svs").unlink()
    _items, gone = collect_uploads(
        export,
        volume_root=_ROOT,
        thumbs_dir=thumbs,
        slides_dir=slides,
    )
    assert "slides/slide-b.svs" in gone


def test_files_client_strips_host_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _SdkClient:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    module = types.ModuleType("databricks.sdk")
    setattr(module, "Work" + "spaceClient", _SdkClient)
    monkeypatch.setitem(sys.modules, "databricks.sdk", module)
    files_client(host="https://example.cloud.databricks.com///?o=1", token="secret-token")
    assert captured["host"] == "https://example.cloud.databricks.com"
    assert captured["token"] == "secret-token"


def test_volume_root_rejects_a_url(tmp_path: Path) -> None:
    export, thumbs, slides = _tree(tmp_path)
    with pytest.raises(ValueError, match="/Volumes"):
        collect_uploads(export, volume_root="https://example.cloud.databricks.com/Volumes/raw")
    del thumbs, slides


def test_cli_requires_a_volume_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    export, _thumbs, _slides = _tree(tmp_path)
    code = pipeline_main.main(["upload-volume", "--from", str(export)])
    assert code == 1
    assert "DATABRICKS_VOLUME_ROOT" in capsys.readouterr().err


def _tree(root: Path) -> tuple[Path, Path, Path]:
    export = root / "export"
    _write_slides(export, [("slide-a", "case-a"), ("slide-b", "case-b")])
    for table in PIPELINE_TABLES:
        path = export / PARQUET_FILES[table]
        if path.exists():
            continue
        pq.write_table(pa.table({"id": pa.array([], type=pa.string())}), path)
    thumbs = root / "thumbs"
    slides = root / "slides"
    thumbs.mkdir()
    slides.mkdir()
    for name in ("slide-a", "slide-b"):
        (thumbs / f"{name}.pack").write_bytes(b"pack-" + name.encode())
        (thumbs / f"{name}.index.json").write_text("{}", encoding="utf-8")
        (slides / f"{name}.svs").write_bytes(b"svs-" + name.encode())
    return export, thumbs, slides


def _write_slides(directory: Path, rows: list[tuple[str, str]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "id": [row[0] for row in rows],
            "case_id": [row[1] for row in rows],
        }
    )
    pq.write_table(table, directory / PARQUET_FILES["slide"])
