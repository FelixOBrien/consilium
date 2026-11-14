"""Stage 2: download cohort slides from the GDC data endpoint.

Each row of ``cohort.csv`` is fetched with ``GET /data/{gdc_file_id}`` to
``slides/{slide_id}.svs``. Writes are streamed to ``.svs.part`` and renamed
only after the byte count matches the manifest and the MD5 matches GDC
``files/{id}`` metadata (or an optional ``md5sum`` / ``md5`` column). A slide
that already has the right size is skipped; pass ``verify_md5`` to hash it
too. One failed slide is recorded and the rest of the batch continues.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from consilium.pipeline.cohort import TIER_CASE_COUNTS  # pragma: allowlist secret

GDC_BASE_URL = "https://api.gdc.cancer.gov"
USER_AGENT = "ingestion-pipeline/0.1 (research prototype; not for clinical use)"
CHUNK_BYTES = 1024 * 1024
TRANSIENT_HTTP = frozenset({408, 429, 500, 502, 503, 504})
DEMO_SLIDES = TIER_CASE_COUNTS["demo"]
REQUIRED_COLUMNS = ("slide_id", "gdc_file_id", "file_size")
_HEX = frozenset("0123456789abcdef")


class _Retryable(Exception):
    """A transfer failed in a way that is worth repeating."""


class _Fatal(Exception):
    """A slide cannot be downloaded correctly. Do not retry."""


@dataclass(frozen=True)
class CohortSlide:
    slide_id: str
    gdc_file_id: str
    file_size: int
    case_id: str
    file_name: str
    md5sum: str | None


@dataclass(frozen=True)
class FileDigest:
    md5sum: str
    file_size: int | None


@dataclass(frozen=True)
class SlideDownload:
    slide_id: str
    gdc_file_id: str
    case_id: str
    status: str
    path: str | None
    byte_count: int | None
    md5: str | None
    error: str | None
    attempts: int


@dataclass(frozen=True)
class DownloadResult:
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    elapsed_seconds: float
    seconds_per_slide: float | None
    projected_demo_slides: int
    projected_demo_seconds: float | None
    slides: tuple[SlideDownload, ...]
    report_path: Path

    def summary(self) -> str:
        lines = [
            f"attempted {self.attempted}",
            f"succeeded {self.succeeded}",
            f"skipped {self.skipped}",
            f"failed {self.failed}",
            f"elapsed_seconds {self.elapsed_seconds:.3f}",
            f"seconds_per_slide {_seconds(self.seconds_per_slide)}",
            f"projected_demo_slides {self.projected_demo_slides}",
            f"projected_demo_seconds {_seconds(self.projected_demo_seconds)}",
            f"wrote {self.report_path}",
        ]
        for slide in self.slides:
            if slide.status == "failed":
                lines.append(f"failure {slide.slide_id} {_one_line(slide.error)}")
        return "\n".join(lines) + "\n"


def read_cohort_csv(path: Path) -> list[CohortSlide]:
    """Read the stage-1 manifest. ``md5sum`` or ``md5`` is optional."""
    if not path.is_file():
        raise ValueError(f"cohort file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or ()
        missing = [name for name in REQUIRED_COLUMNS if name not in fieldnames]
        if missing:
            raise ValueError(f"cohort file missing columns: {', '.join(missing)}")
        slides: list[CohortSlide] = []
        seen: set[str] = set()
        for line_no, raw in enumerate(reader, start=2):
            slides.append(_parse_row(raw, line_no, seen))
    return slides


def download_cohort(
    *,
    cohort_csv: Path,
    data_root: Path,
    workers: int = 4,
    verify_md5: bool = False,
    retries: int = 5,
    timeout: float = 300.0,
    base_url: str = GDC_BASE_URL,
    opener: urllib.request.OpenerDirector | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> DownloadResult:
    """Download every manifest slide. Existing valid files are not fetched again."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if retries < 1:
        raise ValueError("retries must be >= 1")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    slides = read_cohort_csv(cohort_csv)
    slides_dir = data_root / "slides"
    report_path = data_root / "trident" / "download_report.json"
    slides_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    client = opener or urllib.request.build_opener()
    root = base_url.rstrip("/")
    started = clock()
    ordered: list[SlideDownload | None] = [None] * len(slides)
    if slides:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _download_one,
                    slide,
                    slides_dir=slides_dir,
                    base_url=root,
                    opener=client,
                    verify_md5=verify_md5,
                    retries=retries,
                    timeout=timeout,
                    sleeper=sleeper,
                ): index
                for index, slide in enumerate(slides)
            }
            for future in as_completed(futures):
                ordered[futures[future]] = future.result()
    elapsed = clock() - started
    results = tuple(item for item in ordered if item is not None)
    succeeded = sum(item.status == "downloaded" for item in results)
    skipped = sum(item.status == "skipped" for item in results)
    failed = sum(item.status == "failed" for item in results)
    per_slide, projected = _projection(elapsed, succeeded)
    result = DownloadResult(
        attempted=len(results),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        elapsed_seconds=elapsed,
        seconds_per_slide=per_slide,
        projected_demo_slides=DEMO_SLIDES,
        projected_demo_seconds=projected,
        slides=results,
        report_path=report_path,
    )
    _write_report(result)
    return result


def _parse_row(raw: Mapping[str, str | None], line_no: int, seen: set[str]) -> CohortSlide:
    slide_id = (raw.get("slide_id") or "").strip()
    file_id = (raw.get("gdc_file_id") or "").strip()
    if not slide_id or not file_id:
        raise ValueError(f"cohort row {line_no} is missing slide_id or gdc_file_id")
    if slide_id in {".", ".."} or "/" in slide_id or "\\" in slide_id:
        raise ValueError(f"cohort row {line_no} has an unsafe slide_id")
    if slide_id in seen:
        raise ValueError(f"duplicate slide_id {slide_id}")
    seen.add(slide_id)
    try:
        file_size = int((raw.get("file_size") or "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cohort row {line_no} has a bad file_size") from exc
    if file_size <= 0:
        raise ValueError(f"cohort row {line_no} has a non-positive file_size")
    md5sum = _optional_md5(raw)
    return CohortSlide(
        slide_id=slide_id,
        gdc_file_id=file_id,
        file_size=file_size,
        case_id=(raw.get("case_id") or "").strip(),
        file_name=(raw.get("file_name") or "").strip(),
        md5sum=md5sum,
    )


def _optional_md5(raw: Mapping[str, str | None]) -> str | None:
    for key in ("md5sum", "md5"):
        text = (raw.get(key) or "").strip().lower()
        if not text:
            continue
        if len(text) != 32 or any(char not in _HEX for char in text):
            raise ValueError(f"cohort md5 for {raw.get('slide_id')!r} is not 32 hex characters")
        return text
    return None


def _download_one(
    slide: CohortSlide,
    *,
    slides_dir: Path,
    base_url: str,
    opener: urllib.request.OpenerDirector,
    verify_md5: bool,
    retries: int,
    timeout: float,
    sleeper: Callable[[float], None],
) -> SlideDownload:
    destination = slides_dir / f"{slide.slide_id}.svs"
    partial = slides_dir / f"{slide.slide_id}.svs.part"
    try:
        return _download_with_retries(
            slide,
            destination=destination,
            partial=partial,
            base_url=base_url,
            opener=opener,
            verify_md5=verify_md5,
            retries=retries,
            timeout=timeout,
            sleeper=sleeper,
        )
    except Exception as exc:
        _unlink(partial)
        return _failed(slide, destination, str(exc), attempts=1)


def _download_with_retries(
    slide: CohortSlide,
    *,
    destination: Path,
    partial: Path,
    base_url: str,
    opener: urllib.request.OpenerDirector,
    verify_md5: bool,
    retries: int,
    timeout: float,
    sleeper: Callable[[float], None],
) -> SlideDownload:
    if _already_valid(
        slide,
        destination,
        verify_md5=verify_md5,
        base_url=base_url,
        opener=opener,
        timeout=timeout,
    ):
        return SlideDownload(
            slide_id=slide.slide_id,
            gdc_file_id=slide.gdc_file_id,
            case_id=slide.case_id,
            status="skipped",
            path=str(destination),
            byte_count=slide.file_size,
            md5=slide.md5sum,
            error=None,
            attempts=0,
        )
    digest: FileDigest | None = None
    last_error = "download failed"
    for attempt in range(1, retries + 1):
        try:
            if digest is None:
                digest = _fetch_digest(opener, base_url, slide.gdc_file_id, timeout)
                _check_manifest_digest(slide, digest)
            _unlink(partial)
            actual_md5 = _stream_slide(
                opener,
                f"{base_url}/data/{urllib.parse.quote(slide.gdc_file_id)}",
                partial,
                expected_size=slide.file_size,
                expected_md5=digest.md5sum,
                timeout=timeout,
            )
            os.replace(partial, destination)
            return SlideDownload(
                slide_id=slide.slide_id,
                gdc_file_id=slide.gdc_file_id,
                case_id=slide.case_id,
                status="downloaded",
                path=str(destination),
                byte_count=slide.file_size,
                md5=actual_md5,
                error=None,
                attempts=attempt,
            )
        except _Fatal as exc:
            _unlink(partial)
            return _failed(slide, destination, str(exc), attempts=attempt)
        except _Retryable as exc:
            last_error = str(exc)
            _unlink(partial)
            if attempt < retries:
                sleeper(_backoff(attempt))
                continue
        except (TimeoutError, ConnectionError, urllib.error.URLError, OSError) as exc:
            last_error = str(exc)
            _unlink(partial)
            if attempt < retries:
                sleeper(_backoff(attempt))
                continue
    _unlink(partial)
    return _failed(slide, destination, last_error, attempts=retries)


def _already_valid(
    slide: CohortSlide,
    destination: Path,
    *,
    verify_md5: bool,
    base_url: str,
    opener: urllib.request.OpenerDirector,
    timeout: float,
) -> bool:
    if not destination.is_file():
        return False
    if destination.stat().st_size != slide.file_size:
        return False
    if not verify_md5:
        return True
    try:
        expected = slide.md5sum
        if expected is None:
            expected = _fetch_digest(opener, base_url, slide.gdc_file_id, timeout).md5sum
    except (_Retryable, _Fatal):
        return False
    return _md5_file(destination) == expected


def _check_manifest_digest(slide: CohortSlide, digest: FileDigest) -> None:
    if slide.md5sum is not None and slide.md5sum != digest.md5sum:
        raise _Fatal(
            f"cohort md5sum {slide.md5sum} does not match GDC md5sum {digest.md5sum}"
        )
    if digest.file_size is not None and digest.file_size != slide.file_size:
        raise _Fatal(
            f"GDC file_size {digest.file_size} does not match manifest file_size {slide.file_size}"
        )


def _fetch_digest(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    file_id: str,
    timeout: float,
) -> FileDigest:
    query = urllib.parse.urlencode({"fields": "md5sum,file_size", "pretty": "false"})
    url = f"{base_url}/files/{urllib.parse.quote(file_id)}?{query}"
    payload = _read_json(opener, url, timeout)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _Fatal("GDC file metadata has no data object")
    raw_md5 = data.get("md5sum")
    if not isinstance(raw_md5, str):
        raise _Fatal("GDC file metadata has no md5sum")
    md5sum = raw_md5.strip().lower()
    if len(md5sum) != 32 or any(char not in _HEX for char in md5sum):
        raise _Fatal(f"GDC md5sum is not 32 hex characters: {raw_md5!r}")
    raw_size = data.get("file_size")
    file_size: int | None
    if raw_size is None:
        file_size = None
    elif isinstance(raw_size, bool) or not isinstance(raw_size, int):
        raise _Fatal(f"GDC file_size is not an integer: {raw_size!r}")
    else:
        file_size = raw_size
    return FileDigest(md5sum=md5sum, file_size=file_size)


def _read_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    timeout: float,
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
        raise _Retryable(f"GDC metadata request failed: {exc}") from exc
    try:
        parsed = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _Fatal("GDC metadata was not JSON") from exc
    if not isinstance(parsed, dict):
        raise _Fatal("GDC metadata was not a JSON object")
    return parsed


def _stream_slide(
    opener: urllib.request.OpenerDirector,
    url: str,
    partial: Path,
    *,
    expected_size: int,
    expected_md5: str,
    timeout: float,
) -> str:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
        raise _Retryable(f"GDC data request failed: {exc}") from exc
    digest = hashlib.md5()
    written = 0
    try:
        with response:
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type.lower() or "text/" in content_type.lower():
                snippet = response.read(120)
                kind = content_type or "a document"
                raise _Fatal(f"GDC returned {kind} instead of a slide: {snippet!r}")
            partial.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > expected_size:
                        raise _Fatal(
                            f"download grew past manifest size {expected_size} "
                            f"({written} bytes received)"
                        )
                    handle.write(chunk)
                    digest.update(chunk)
    except _Fatal:
        raise
    except _Retryable:
        raise
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
        raise _Retryable(f"GDC data stream failed after {written} bytes: {exc}") from exc
    if written != expected_size:
        raise _Retryable(f"size {written} != manifest file_size {expected_size}")
    actual = digest.hexdigest()
    if actual != expected_md5:
        raise _Fatal(f"md5 {actual} != expected {expected_md5}")
    return actual


def _raise_http(exc: urllib.error.HTTPError) -> None:
    if exc.code in TRANSIENT_HTTP:
        raise _Retryable(f"HTTP {exc.code}") from exc
    raise _Fatal(f"HTTP {exc.code}") from exc


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _backoff(attempt: int) -> float:
    return min(30.0, 0.5 * (2 ** (attempt - 1)))


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _failed(slide: CohortSlide, destination: Path, error: str, *, attempts: int) -> SlideDownload:
    kept = destination.is_file()
    return SlideDownload(
        slide_id=slide.slide_id,
        gdc_file_id=slide.gdc_file_id,
        case_id=slide.case_id,
        status="failed",
        path=str(destination) if kept else None,
        byte_count=destination.stat().st_size if kept else None,
        md5=None,
        error=error,
        attempts=attempts,
    )


def _projection(elapsed: float, succeeded: int) -> tuple[float | None, float | None]:
    """Wall time per newly downloaded slide, and the same rate times the demo tier."""
    if succeeded <= 0:
        return None, None
    per_slide = elapsed / succeeded
    return per_slide, per_slide * DEMO_SLIDES


def _seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _one_line(error: str | None) -> str:
    text = " ".join((error or "unknown error").split())
    if len(text) > 300:
        return text[:297] + "..."
    return text


def _write_report(result: DownloadResult) -> None:
    payload = {
        "stage": "download",
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "skipped": result.skipped,
        "failed": result.failed,
        "elapsed_seconds": result.elapsed_seconds,
        "seconds_per_slide": result.seconds_per_slide,
        "projected_demo_slides": result.projected_demo_slides,
        "projected_demo_seconds": result.projected_demo_seconds,
        "slides": [
            {
                "slide_id": slide.slide_id,
                "case_id": slide.case_id,
                "gdc_file_id": slide.gdc_file_id,
                "status": slide.status,
                "path": slide.path,
                "bytes": slide.byte_count,
                "md5": slide.md5,
                "error": slide.error,
                "attempts": slide.attempts,
            }
            for slide in result.slides
        ],
    }
    _write_json(result.report_path, payload)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
