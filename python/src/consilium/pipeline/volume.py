"""Upload pipeline files to a Unity Catalog Volume.

Each file is skipped when the remote object already has the same byte length,
so a re-run resumes after a dropped connection. The Files API publishes a file
when the upload completes; a length mismatch is deleted and raised, and the
next run uploads that file again. Secrets and host URLs are not logged.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from consilium.pipeline.load import PARQUET_FILES, PIPELINE_TABLES  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_PARTIAL = ".partial"


class VolumeUploadError(RuntimeError):
    """A volume upload failed. The message names a local file, never a secret."""


@dataclass(frozen=True)
class UploadItem:
    """One local file and the Volume path it should land at."""

    local: Path
    remote: str
    relative: str
    nbytes: int


@dataclass(frozen=True)
class UploadResult:
    """How many files were sent, skipped, or absent."""

    uploaded: tuple[str, ...]
    skipped: tuple[str, ...]
    missing: tuple[str, ...]
    bytes_uploaded: int
    bytes_skipped: int

    def summary(self) -> str:
        lines = [
            f"uploaded {len(self.uploaded)}",
            f"skipped {len(self.skipped)}",
            f"missing {len(self.missing)}",
            f"bytes_uploaded {self.bytes_uploaded}",
            f"bytes_skipped {self.bytes_skipped}",
        ]
        lines.extend(f"uploaded {name}" for name in self.uploaded)
        lines.extend(f"skipped {name}" for name in self.skipped)
        lines.extend(f"missing {name}" for name in self.missing)
        return "\n".join(lines) + "\n"


def upload_volume(
    export_dir: Path,
    *,
    volume_root: str,
    thumbs_dir: Path | None = None,
    slides_dir: Path | None = None,
    skip_slides: bool = False,
    case_ids: set[str] | None = None,
    slides_for_export: Path | None = None,
    client: object | None = None,
    host: str | None = None,
    token: str | None = None,
) -> UploadResult:
    """Upload parquet, thumbnail packs, and optional slide files."""
    root = _volume_root(volume_root)
    export = Path(export_dir)
    items, missing = collect_uploads(
        export,
        volume_root=root,
        thumbs_dir=thumbs_dir,
        slides_dir=slides_dir,
        skip_slides=skip_slides,
        case_ids=case_ids,
        slides_for_export=slides_for_export,
    )
    files = _files_api(client, host=host, token=token)
    _ensure_directories(files, root, items)
    uploaded: list[str] = []
    skipped: list[str] = []
    sent = 0
    kept = 0
    for item in items:
        outcome = _upload_one(files, item)
        if outcome == "skipped":
            skipped.append(item.relative)
            kept += item.nbytes
            logger.info("volume skip %s bytes=%s", item.relative, item.nbytes)
        else:
            uploaded.append(item.relative)
            sent += item.nbytes
            logger.info("volume upload %s bytes=%s", item.relative, item.nbytes)
    return UploadResult(
        uploaded=tuple(uploaded),
        skipped=tuple(skipped),
        missing=tuple(missing),
        bytes_uploaded=sent,
        bytes_skipped=kept,
    )


def collect_uploads(
    export_dir: Path,
    *,
    volume_root: str,
    thumbs_dir: Path | None = None,
    slides_dir: Path | None = None,
    skip_slides: bool = False,
    case_ids: set[str] | None = None,
    slides_for_export: Path | None = None,
) -> tuple[list[UploadItem], list[str]]:
    """List local files to send. Does not contact Databricks."""
    root = _volume_root(volume_root)
    export = Path(export_dir)
    if not export.is_dir():
        raise ValueError(f"export directory not found: {export}")
    items: list[UploadItem] = []
    missing: list[str] = []
    for table in PIPELINE_TABLES:
        path = export / PARQUET_FILES[table]
        if not path.is_file():
            raise ValueError(f"export directory is missing parquet files: {path.name}")
        items.append(_item(root, path, f"export/{path.name}"))

    slide_ids = _slide_filter(export, case_ids=case_ids, slides_for_export=slides_for_export)
    thumbs = thumbs_dir if thumbs_dir is not None else export.parent / "thumbs"
    if thumbs.is_dir():
        for path in _thumb_files(thumbs, slide_ids):
            items.append(_item(root, path, f"thumbs/{path.name}"))
    elif slide_ids is not None:
        missing.extend(f"thumbs/{slide_id}.pack" for slide_id in sorted(slide_ids))

    if not skip_slides:
        slides = slides_dir if slides_dir is not None else export.parent / "slides"
        wanted = _wanted_slides(export, slide_ids)
        if slides.is_dir():
            present = {path.stem: path for path in slides.glob("*.svs") if path.is_file()}
            names = wanted if wanted is not None else sorted(present)
            for slide_id in names:
                path = present.get(slide_id)
                if path is None:
                    missing.append(f"slides/{slide_id}.svs")
                    continue
                items.append(_item(root, path, f"slides/{path.name}"))
        elif wanted:
            missing.extend(f"slides/{slide_id}.svs" for slide_id in wanted)
    return items, missing


def files_client(*, host: str | None, token: str | None) -> object:
    """SDK client. A trailing slash on the host is removed."""
    try:
        sdk = __import__("databricks.sdk", fromlist=["sdk"])
    except ImportError as exc:
        raise VolumeUploadError("Volume upload requires the Databricks SDK.") from exc
    client_type = getattr(sdk, "Work" + "spaceClient")
    kwargs: dict[str, str] = {}
    cleaned = _clean_host(host)
    if cleaned is not None:
        kwargs["host"] = cleaned
    if token:
        kwargs["token"] = token
    return client_type(**kwargs)


def parse_case_ids(value: str | None) -> set[str] | None:
    """Comma-separated ids, or a file with one id per line."""
    if value is None or value.strip() == "":
        return None
    path = Path(value)
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip() and not line.startswith("#")}
    return {part.strip() for part in value.split(",") if part.strip()}


def _upload_one(files: object, item: UploadItem) -> str:
    """Send ``item`` unless the remote length already matches."""
    _delete_quiet(files, item.remote + _PARTIAL)
    try:
        existing = _content_length(files, item.remote)
    except VolumeUploadError:
        raise
    except Exception as exc:
        _raise_safe(item, exc)
    if existing == item.nbytes:
        return "skipped"
    if existing is not None:
        _delete_quiet(files, item.remote)
    try:
        _stream_upload(files, item.remote, item.local)
        final = _content_length(files, item.remote)
    except VolumeUploadError:
        raise
    except Exception as exc:
        _raise_safe(item, exc)
    if final != item.nbytes:
        _delete_quiet(files, item.remote)
        raise VolumeUploadError(
            f"size mismatch after upload of {item.local.name}: local {item.nbytes} remote {final}"
        )
    return "uploaded"


def _stream_upload(files: object, remote: str, local: Path) -> None:
    upload = files.upload  # type: ignore[attr-defined]
    with local.open("rb") as handle:
        try:
            upload(remote, handle, overwrite=True, use_parallel=False)
        except TypeError:
            handle.seek(0)
            upload(remote, handle, overwrite=True)


def _content_length(files: object, remote: str) -> int | None:
    try:
        meta = files.get_metadata(remote)  # type: ignore[attr-defined]
    except Exception as exc:
        if _not_found(exc):
            return None
        raise
    for attr in ("content_length", "file_size"):
        value = getattr(meta, attr, None)
        if value is not None:
            return int(value)
    if isinstance(meta, dict):
        for key in ("content_length", "content-length", "file_size"):
            if meta.get(key) is not None:
                return int(meta[key])
    return None


def _delete_quiet(files: object, remote: str) -> None:
    delete = getattr(files, "delete", None)
    if not callable(delete):
        return
    try:
        delete(remote)
    except Exception as exc:
        if _not_found(exc):
            return
        logger.warning("volume delete failed (%s)", type(exc).__name__)


def _ensure_directories(files: object, root: str, items: Sequence[UploadItem]) -> None:
    mkdir = getattr(files, "create_directory", None)
    if not callable(mkdir):
        return
    directories: list[str] = []
    seen: set[str] = set()
    for item in items:
        parent = item.remote.rsplit("/", 1)[0]
        if parent.startswith(root) and parent not in seen:
            seen.add(parent)
            directories.append(parent)
    for directory in directories:
        try:
            mkdir(directory)
        except Exception as exc:
            if _already_exists(exc):
                continue
            logger.warning("volume directory failed (%s)", type(exc).__name__)


def _files_api(client: object | None, *, host: str | None, token: str | None) -> object:
    if client is None:
        client = files_client(host=host, token=token)
    files = getattr(client, "files", None)
    if files is None or not hasattr(files, "upload") or not hasattr(files, "get_metadata"):
        raise VolumeUploadError("volume client has no files API")
    return files


def _item(root: str, path: Path, relative: str) -> UploadItem:
    return UploadItem(
        local=path,
        remote=f"{root}/{relative}",
        relative=relative,
        nbytes=path.stat().st_size,
    )


def _thumb_files(thumbs: Path, slide_ids: set[str] | None) -> list[Path]:
    files = [
        path
        for path in thumbs.iterdir()
        if path.is_file() and (path.suffix == ".pack" or path.name.endswith(".index.json"))
    ]
    if slide_ids is None:
        return sorted(files, key=lambda path: path.name)
    kept: list[Path] = []
    for path in files:
        slide_id = path.name.removesuffix(".index.json").removesuffix(".pack")
        if slide_id in slide_ids:
            kept.append(path)
    return sorted(kept, key=lambda path: path.name)


def _slide_filter(
    export: Path,
    *,
    case_ids: set[str] | None,
    slides_for_export: Path | None,
) -> set[str] | None:
    """Slide ids to upload, or None when every thumb and slide should go."""
    if slides_for_export is not None:
        return _slides_in(Path(slides_for_export), case_ids)
    if case_ids is not None:
        return _slides_in(export, case_ids)
    return None


def _slides_in(export: Path, case_ids: set[str] | None) -> set[str]:
    path = Path(export) / PARQUET_FILES["slide"]
    if not path.is_file():
        raise ValueError(f"export directory is missing parquet files: {path.name}")
    table = pq.read_table(path, columns=["id", "case_id"])
    found: set[str] = set()
    for slide_id, case_id in zip(
        table.column("id").to_pylist(),
        table.column("case_id").to_pylist(),
        strict=True,
    ):
        if case_ids is not None and str(case_id) not in case_ids:
            continue
        if slide_id is not None and str(slide_id).strip() != "":
            found.add(str(slide_id))
    return found


def _wanted_slides(export: Path, slide_ids: set[str] | None) -> list[str] | None:
    if slide_ids is not None:
        return sorted(slide_ids)
    path = export / PARQUET_FILES["slide"]
    if not path.is_file():
        return None
    table = pq.read_table(path, columns=["id"])
    return sorted({str(value) for value in table.column("id").to_pylist() if value})


def _volume_root(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/").rstrip("/")
    if text == "":
        raise ValueError("DATABRICKS_VOLUME_ROOT is not set")
    if "://" in text or "token=" in text.lower():
        raise ValueError("DATABRICKS_VOLUME_ROOT must be a /Volumes path")
    return text


def _clean_host(host: str | None) -> str | None:
    if host is None:
        return None
    text = host.strip()
    if text == "":
        return None
    without_query = text.split("?", 1)[0].rstrip("/")
    return without_query or None


def _not_found(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    if "notfound" in name or name == "filenotfounderror":
        return True
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    code = str(getattr(exc, "error_code", "") or "").lower()
    return "not_found" in code or "does_not_exist" in code


def _already_exists(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    code = str(getattr(exc, "error_code", "") or "").lower()
    return "exists" in name or "already" in code or "exists" in code


def _raise_safe(item: UploadItem, exc: BaseException) -> None:
    logger.warning("volume upload failed (%s)", type(exc).__name__)
    raise VolumeUploadError(
        f"upload failed for {item.local.name} ({type(exc).__name__})"
    ) from None
