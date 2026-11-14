"""Stages 3 and 4: SVS headers, then TRIDENT segmentation, patching, and features.

TRIDENT's CLI and H5 layout were checked against mahmoodlab/TRIDENT commit
``bdeeb74b7eaad8d48bda232bde7de66cae980918`` (2026-10-12). ``DETAILS.md`` is
linked from that README but is not in the tree; the flags below are the ones
``run_batch_of_slides.py`` actually parses.

Patching is 512 px at 20x with no overlap. TRIDENT names the job subdirectory
``20x_512px_0px_overlap``. Coordinates land in ``patches/{slide_id}_patches.h5``
dataset ``coords`` (N, 2) with attributes ``patch_size``, ``patch_size_level0``,
``target_magnification``, and ``overlap``. ``conch_v15`` features land in
``features_conch_v15/{slide_id}.h5`` datasets ``features`` (N, 768) and
``coords`` (N, 2). The 768-d width is the raw CONCH v1.5 vision tower, not the
CONCH-Z space.

A custom slide list CSV with columns ``wsi,mpp`` supplies microns-per-pixel
when the SVS header has magnification but no ``openslide.mpp-x`` / ``aperio.MPP``.
TRIDENT then buckets that value the same way as ``WSI._fetch_magnification``.
A slide that cannot be read, or that has neither value, is recorded and skipped.
Slides whose H5 outputs already validate are not passed to TRIDENT.
"""

from __future__ import annotations

import csv
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from consilium.pipeline.download import (  # pragma: allowlist secret
    DEMO_SLIDES,
    CohortSlide,
    _one_line,
    _seconds,
    _write_json,
    read_cohort_csv,
)

# Raw conch_v15 width (CONCHVisionTower contrast pool). Not CONCH-Z.
CONCH_V15_DIM = 768
PATCH_ENCODER = "conch_v15"
TARGET_MAG = 20
PATCH_SIZE = 512
OVERLAP = 0
SEGMENTERS = ("hest", "grandqc", "otsu")
TRIDENT_COMMIT = "bdeeb74b7eaad8d48bda232bde7de66cae980918"

# Header keys, in the order the slide spec names them.
_MPP_KEYS = (("openslide.mpp-x", "openslide.mpp-x"), ("aperio.MPP", "aperio.MPP"))
_MAG_KEYS = (
    ("openslide.objective-power", "openslide.objective-power"),
    ("aperio.AppMag", "aperio.AppMag"),
)


def coords_dirname() -> str:
    """TRIDENT's ``{mag}x_{patch}px_{overlap}px_overlap`` directory name."""
    return f"{float(TARGET_MAG):g}x_{PATCH_SIZE}px_{OVERLAP}px_overlap"


def coords_h5_path(job_dir: Path, slide_id: str) -> Path:
    return job_dir / coords_dirname() / "patches" / f"{slide_id}_patches.h5"


def features_h5_path(job_dir: Path, slide_id: str) -> Path:
    return job_dir / coords_dirname() / f"features_{PATCH_ENCODER}" / f"{slide_id}.h5"


def trident_magnification(mpp: float) -> int:
    """Magnification bucket TRIDENT uses once ``mpp`` is known.

    Matches ``WSI._fetch_magnification`` at the commit cited above.
    """
    if mpp < 0.16:
        return 80
    if mpp < 0.2:
        return 60
    if mpp < 0.3:
        return 40
    if mpp < 0.6:
        return 20
    if mpp < 1.2:
        return 10
    if mpp < 2.4:
        return 5
    raise ValueError(f"mpp {mpp} is too coarse to place a 20x patch grid")


def level0_patch_px(magnification: int) -> int:
    """Level-0 side length of a 512 px patch at 20x. 1024 at 40x, 512 at 20x."""
    return PATCH_SIZE * magnification // TARGET_MAG


def fallback_mpp(magnification: float) -> float:
    """10/mag, so 40x -> 0.25 and 20x -> 0.5, rounded the way TRIDENT stores mpp."""
    if magnification <= 0:
        raise ValueError("magnification must be positive")
    return round(10.0 / float(magnification), 4)


@dataclass(frozen=True)
class SlideGeometry:
    slide_id: str
    case_id: str
    width_px: int | None
    height_px: int | None
    magnification: float | None
    magnification_source: str | None
    mpp: float | None
    mpp_source: str | None
    trident_magnification: int | None
    patch_size_level0: int | None
    error: str | None


@dataclass(frozen=True)
class SlideExtract:
    slide_id: str
    case_id: str
    status: str
    patch_count: int | None
    coords_path: str | None
    features_path: str | None
    error: str | None


@dataclass(frozen=True)
class ExtractResult:
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    total_patches: int
    elapsed_seconds: float
    seconds_per_slide: float | None
    projected_demo_slides: int
    projected_demo_seconds: float | None
    slides: tuple[SlideExtract, ...]
    headers_path: Path
    report_path: Path
    custom_list_path: Path | None
    command: tuple[str, ...] | None

    def summary(self) -> str:
        lines = [
            f"attempted {self.attempted}",
            f"succeeded {self.succeeded}",
            f"skipped {self.skipped}",
            f"failed {self.failed}",
            f"total_patches {self.total_patches}",
            f"elapsed_seconds {self.elapsed_seconds:.3f}",
            f"seconds_per_slide {_seconds(self.seconds_per_slide)}",
            f"projected_demo_slides {self.projected_demo_slides}",
            f"projected_demo_seconds {_seconds(self.projected_demo_seconds)}",
            f"wrote {self.headers_path}",
            f"wrote {self.report_path}",
        ]
        for slide in self.slides:
            if slide.status == "failed":
                lines.append(f"failure {slide.slide_id} {_one_line(slide.error)}")
        return "\n".join(lines) + "\n"


class HeaderSource:
    """Reads level-0 dimensions and the OpenSlide property map for one file."""

    def read(self, path: Path) -> tuple[int, int, Mapping[str, str]]:
        raise NotImplementedError


class OpenSlideHeaderSource(HeaderSource):
    def read(self, path: Path) -> tuple[int, int, Mapping[str, str]]:
        import openslide

        slide = openslide.OpenSlide(str(path))
        try:
            width, height = slide.dimensions
            properties = {str(key): str(slide.properties[key]) for key in slide.properties}
        finally:
            slide.close()
        return int(width), int(height), properties


def geometry_from_properties(
    slide_id: str,
    case_id: str,
    width: int,
    height: int,
    properties: Mapping[str, str],
) -> SlideGeometry:
    """Resolve mpp, magnification, and the level-0 patch size TRIDENT will write."""
    mpp, mpp_source = _first_positive(properties, _MPP_KEYS)
    magnification, magnification_source = _first_positive(properties, _MAG_KEYS)
    error: str | None = None
    if width <= 0 or height <= 0:
        error = "slide header has no level-0 dimensions"
    if mpp is None and magnification is not None and error is None:
        mpp = fallback_mpp(magnification)
        mpp_source = "magnification_fallback"
    derived: int | None = None
    patch: int | None = None
    if error is None and mpp is not None:
        try:
            derived = trident_magnification(mpp)
        except ValueError as exc:
            error = str(exc)
        else:
            patch = level0_patch_px(derived)
    if magnification is None and derived is not None:
        magnification = float(derived)
        magnification_source = "mpp"
    if error is None and (mpp is None or magnification is None):
        error = "slide header has no microns-per-pixel or magnification"
    if error is not None:
        patch = None
        derived = None
    return SlideGeometry(
        slide_id=slide_id,
        case_id=case_id,
        width_px=width if width > 0 else None,
        height_px=height if height > 0 else None,
        magnification=magnification,
        magnification_source=magnification_source,
        mpp=mpp,
        mpp_source=mpp_source,
        trident_magnification=derived,
        patch_size_level0=patch,
        error=error,
    )


def read_slide_geometry(
    slide: CohortSlide,
    slides_dir: Path,
    source: HeaderSource,
) -> SlideGeometry:
    path = slides_dir / f"{slide.slide_id}.svs"
    if not path.is_file():
        return _blank_geometry(slide, "slide file is missing")
    try:
        width, height, properties = source.read(path)
    except Exception as exc:
        return _blank_geometry(slide, f"unreadable slide: {exc}")
    return geometry_from_properties(slide.slide_id, slide.case_id, width, height, properties)


def validate_features(
    job_dir: Path,
    slide_id: str,
    *,
    expected_level0: int | None,
) -> tuple[int | None, str | None]:
    """Return ``(patch_count, error)``. ``error`` is None when both H5 files validate."""
    coords_path = coords_h5_path(job_dir, slide_id)
    features_path = features_h5_path(job_dir, slide_id)
    if not coords_path.is_file() or not features_path.is_file():
        return None, "coords or features H5 is missing"
    h5py = _h5py()
    try:
        with h5py.File(coords_path, "r") as handle:
            if "coords" not in handle:
                return None, "coords H5 has no coords dataset"
            coords = handle["coords"]
            shape_error = _coords_shape(coords.shape, "coords")
            if shape_error is not None:
                return None, shape_error
            if coords.dtype.kind not in {"i", "u"}:
                return None, "coords dataset is not an integer type"
            patch_count = int(coords.shape[0])
            for key, expected in (
                ("patch_size", PATCH_SIZE),
                ("target_magnification", TARGET_MAG),
                ("overlap", OVERLAP),
            ):
                mismatch = _attr_equals(coords.attrs, key, expected)
                if mismatch is not None:
                    return None, mismatch
            if expected_level0 is not None:
                mismatch = _attr_equals(coords.attrs, "patch_size_level0", expected_level0)
                if mismatch is not None:
                    return None, mismatch
        with h5py.File(features_path, "r") as handle:
            if "features" not in handle or "coords" not in handle:
                return None, "features H5 is missing the features or coords dataset"
            features = handle["features"]
            feature_coords = handle["coords"]
            if features.ndim != 2 or int(features.shape[1]) != CONCH_V15_DIM:
                return None, f"features shape {tuple(features.shape)} is not (N, {CONCH_V15_DIM})"
            if features.dtype.kind != "f":
                return None, "features dataset is not floating point"
            if int(features.shape[0]) != patch_count:
                return None, "feature row count does not match coords"
            shape_error = _coords_shape(feature_coords.shape, "features coords")
            if shape_error is not None or int(feature_coords.shape[0]) != patch_count:
                return None, "features coords do not match the coords H5"
            encoder = _attr_text(features.attrs.get("encoder"))
            if encoder != PATCH_ENCODER:
                return None, f"features encoder is {encoder!r}, expected {PATCH_ENCODER}"
    except OSError as exc:
        return None, f"could not read H5 output: {exc}"
    return patch_count, None


def build_trident_command(
    *,
    wsi_dir: Path,
    job_dir: Path,
    custom_list: Path,
    gpu: int,
    segmenter: str,
    executable: str = "trident",
) -> list[str]:
    """Argv for ``trident batch``, matching the current ``run_batch_of_slides`` flags."""
    if segmenter not in SEGMENTERS:
        raise ValueError(f"unknown segmenter {segmenter!r}")
    return [
        executable,
        "batch",
        "--",
        "--task",
        "all",
        "--wsi_dir",
        str(wsi_dir),
        "--job_dir",
        str(job_dir),
        "--custom_list_of_wsis",
        str(custom_list),
        "--wsi_ext",
        ".svs",
        "--reader_type",
        "openslide",
        "--segmenter",
        segmenter,
        "--mag",
        str(TARGET_MAG),
        "--patch_size",
        str(PATCH_SIZE),
        "--overlap",
        str(OVERLAP),
        "--patch_encoder",
        PATCH_ENCODER,
        "--skip_errors",
        "--clear_dead_locks",
        "--gpus",
        str(gpu),
    ]


def run_trident_command(command: Sequence[str]) -> int:
    try:
        completed = subprocess.run(list(command), check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "trident was not found on PATH. Clone https://github.com/mahmoodlab/TRIDENT "
            "and install it into this environment (`uv pip install -e /path/to/TRIDENT`)."
        ) from exc
    return int(completed.returncode)


def extract_cohort(
    *,
    cohort_csv: Path,
    data_root: Path,
    gpu: int = 0,
    segmenter: str = "hest",
    header_source: HeaderSource | None = None,
    runner: Callable[[Sequence[str]], int] | None = None,
    trident_executable: str = "trident",
    clock: Callable[[], float] | None = None,
) -> ExtractResult:
    """Inspect headers, skip valid H5 outputs, and run TRIDENT on the rest."""
    if segmenter not in SEGMENTERS:
        raise ValueError(f"unknown segmenter {segmenter!r}")
    slides = read_cohort_csv(cohort_csv)
    slides_dir = data_root / "slides"
    job_dir = data_root / "trident"
    headers_path = job_dir / "slide_headers.parquet"
    report_path = job_dir / "extract_report.json"
    custom_list_path = job_dir / "custom_list_of_wsis.csv"
    job_dir.mkdir(parents=True, exist_ok=True)
    source = header_source if header_source is not None else _require_openslide()
    invoke = runner if runner is not None else run_trident_command
    now = clock or _perf_counter()
    started = now()
    geometries = [read_slide_geometry(slide, slides_dir, source) for slide in slides]
    _write_headers(headers_path, geometries)
    outcomes: list[SlideExtract | None] = [None] * len(slides)
    pending: list[tuple[int, CohortSlide, SlideGeometry]] = []
    for index, (slide, geometry) in enumerate(zip(slides, geometries, strict=True)):
        if geometry.error is not None:
            outcomes[index] = _extract_row(slide, job_dir, "failed", None, geometry.error)
            continue
        patch_count, error = validate_features(
            job_dir,
            slide.slide_id,
            expected_level0=geometry.patch_size_level0,
        )
        if error is None:
            outcomes[index] = _extract_row(slide, job_dir, "skipped", patch_count, None)
            continue
        _prepare_pending(job_dir, slide.slide_id, geometry.patch_size_level0)
        pending.append((index, slide, geometry))
    command: tuple[str, ...] | None = None
    list_written: Path | None = None
    run_error: str | None = None
    exit_code: int | None = None
    if pending:
        list_written = custom_list_path
        _write_custom_list(custom_list_path, [(item[1], item[2]) for item in pending])
        argv = build_trident_command(
            wsi_dir=slides_dir,
            job_dir=job_dir,
            custom_list=custom_list_path,
            gpu=gpu,
            segmenter=segmenter,
            executable=trident_executable,
        )
        command = tuple(argv)
        try:
            exit_code = invoke(argv)
        except (OSError, RuntimeError) as exc:
            run_error = str(exc)
    if pending:
        for index, slide, geometry in pending:
            if run_error is not None:
                outcomes[index] = _extract_row(slide, job_dir, "failed", None, run_error)
                continue
            patch_count, error = validate_features(
                job_dir,
                slide.slide_id,
                expected_level0=geometry.patch_size_level0,
            )
            if error is None:
                outcomes[index] = _extract_row(slide, job_dir, "extracted", patch_count, None)
                continue
            detail = error
            if exit_code not in (None, 0):
                detail = f"{error}; trident exit {exit_code}"
            outcomes[index] = _extract_row(slide, job_dir, "failed", None, detail)
    elapsed = now() - started
    rows = tuple(item for item in outcomes if item is not None)
    succeeded = sum(item.status == "extracted" for item in rows)
    skipped = sum(item.status == "skipped" for item in rows)
    failed = sum(item.status == "failed" for item in rows)
    total_patches = sum(item.patch_count or 0 for item in rows if item.status != "failed")
    per_slide = None if succeeded <= 0 else elapsed / succeeded
    projected = None if per_slide is None else per_slide * DEMO_SLIDES
    result = ExtractResult(
        attempted=len(rows),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        total_patches=total_patches,
        elapsed_seconds=elapsed,
        seconds_per_slide=per_slide,
        projected_demo_slides=DEMO_SLIDES,
        projected_demo_seconds=projected,
        slides=rows,
        headers_path=headers_path,
        report_path=report_path,
        custom_list_path=list_written,
        command=command,
    )
    _write_extract_report(result, exit_code)
    return result


def _perf_counter() -> Callable[[], float]:
    import time

    return time.perf_counter


def _require_openslide() -> OpenSlideHeaderSource:
    try:
        import openslide  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "openslide is required to read SVS headers. Install it with: uv sync --group tiles"
        ) from exc
    return OpenSlideHeaderSource()


def _h5py() -> object:
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError(
            "h5py is required to validate TRIDENT H5 files. "
            "Install it with the dev or pipeline dependency group."
        ) from exc
    return h5py


def _blank_geometry(slide: CohortSlide, error: str) -> SlideGeometry:
    return SlideGeometry(
        slide_id=slide.slide_id,
        case_id=slide.case_id,
        width_px=None,
        height_px=None,
        magnification=None,
        magnification_source=None,
        mpp=None,
        mpp_source=None,
        trident_magnification=None,
        patch_size_level0=None,
        error=error,
    )


def _first_positive(
    properties: Mapping[str, str],
    keys: tuple[tuple[str, str], ...],
) -> tuple[float | None, str | None]:
    for key, source in keys:
        raw = properties.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value, source
    return None, None


def _coords_shape(shape: tuple[int, ...], label: str) -> str | None:
    if len(shape) != 2 or int(shape[1]) != 2:
        return f"{label} shape {tuple(shape)} is not (N, 2)"
    return None


def _attr_equals(attrs: Mapping[str, object], key: str, expected: int) -> str | None:
    if key not in attrs:
        return f"coords missing attribute {key}"
    raw = attrs[key]
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        value = int(round(float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return f"coords attribute {key} is {raw!r}"
    if value != expected:
        return f"coords attribute {key} is {value}, expected {expected}"
    return None


def _attr_text(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


def _extract_row(
    slide: CohortSlide,
    job_dir: Path,
    status: str,
    patch_count: int | None,
    error: str | None,
) -> SlideExtract:
    coords = coords_h5_path(job_dir, slide.slide_id)
    features = features_h5_path(job_dir, slide.slide_id)
    return SlideExtract(
        slide_id=slide.slide_id,
        case_id=slide.case_id,
        status=status,
        patch_count=patch_count,
        coords_path=str(coords) if coords.is_file() else None,
        features_path=str(features) if features.is_file() else None,
        error=error,
    )


def _discard_outputs(job_dir: Path, slide_id: str) -> None:
    for path in (coords_h5_path(job_dir, slide_id), features_h5_path(job_dir, slide_id)):
        path.unlink(missing_ok=True)


def _prepare_pending(job_dir: Path, slide_id: str, expected_level0: int | None) -> None:
    """Drop outputs TRIDENT would treat as finished even though they do not validate.

    A missing features file keeps a valid coords file so patching is not repeated.
    """
    coords = coords_h5_path(job_dir, slide_id)
    features = features_h5_path(job_dir, slide_id)
    if coords.is_file() and features.is_file():
        _discard_outputs(job_dir, slide_id)
        return
    if features.is_file():
        features.unlink()
    if coords.is_file() and not _coords_file_valid(coords, expected_level0):
        coords.unlink()


def _coords_file_valid(path: Path, expected_level0: int | None) -> bool:
    h5py = _h5py()
    try:
        with h5py.File(path, "r") as handle:
            if "coords" not in handle:
                return False
            coords = handle["coords"]
            shape_error = _coords_shape(coords.shape, "coords")
            if shape_error is not None or coords.dtype.kind not in {"i", "u"}:
                return False
            for key, expected in (
                ("patch_size", PATCH_SIZE),
                ("target_magnification", TARGET_MAG),
                ("overlap", OVERLAP),
            ):
                if _attr_equals(coords.attrs, key, expected) is not None:
                    return False
            if expected_level0 is not None and _attr_equals(
                coords.attrs, "patch_size_level0", expected_level0
            ):
                return False
    except OSError:
        return False
    return True


def _write_custom_list(path: Path, pending: Sequence[tuple[CohortSlide, SlideGeometry]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("wsi", "mpp"), lineterminator="\n")
        writer.writeheader()
        for slide, geometry in pending:
            if geometry.mpp is None:
                continue
            writer.writerow({"wsi": f"{slide.slide_id}.svs", "mpp": format(geometry.mpp, ".10g")})
    os.replace(temporary, path)


def _write_headers(path: Path, geometries: Sequence[SlideGeometry]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    def column(name: str, values: list[object], typ: pa.DataType) -> pa.Array:
        return pa.array(values, type=typ)

    table = pa.table(
        {
            "slide_id": column("slide_id", [item.slide_id for item in geometries], pa.string()),
            "case_id": column("case_id", [item.case_id for item in geometries], pa.string()),
            "width_px": column("width_px", [item.width_px for item in geometries], pa.int64()),
            "height_px": column("height_px", [item.height_px for item in geometries], pa.int64()),
            "magnification": column(
                "magnification", [item.magnification for item in geometries], pa.float64()
            ),
            "magnification_source": column(
                "magnification_source",
                [item.magnification_source for item in geometries],
                pa.string(),
            ),
            "mpp": column("mpp", [item.mpp for item in geometries], pa.float64()),
            "mpp_source": column(
                "mpp_source", [item.mpp_source for item in geometries], pa.string()
            ),
            "trident_magnification": column(
                "trident_magnification",
                [item.trident_magnification for item in geometries],
                pa.int64(),
            ),
            "patch_size_level0": column(
                "patch_size_level0", [item.patch_size_level0 for item in geometries], pa.int64()
            ),
            "error": column("error", [item.error for item in geometries], pa.string()),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    pq.write_table(table, temporary)
    os.replace(temporary, path)


def _write_extract_report(result: ExtractResult, exit_code: int | None) -> None:
    slides = result.slides
    payload = {
        "stage": "extract",
        "trident_commit": TRIDENT_COMMIT,
        "patch_encoder": PATCH_ENCODER,
        "mag": TARGET_MAG,
        "patch_size": PATCH_SIZE,
        "overlap": OVERLAP,
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "skipped": result.skipped,
        "failed": result.failed,
        "total_patches": result.total_patches,
        "elapsed_seconds": result.elapsed_seconds,
        "seconds_per_slide": result.seconds_per_slide,
        "projected_demo_slides": result.projected_demo_slides,
        "projected_demo_seconds": result.projected_demo_seconds,
        "trident_exit_code": exit_code,
        "command": list(result.command) if result.command is not None else None,
        "custom_list": str(result.custom_list_path) if result.custom_list_path else None,
        "headers": str(result.headers_path),
        "slides": [
            {
                "slide_id": slide.slide_id,
                "case_id": slide.case_id,
                "status": slide.status,
                "patch_count": slide.patch_count,
                "coords_path": slide.coords_path,
                "features_path": slide.features_path,
                "error": slide.error,
            }
            for slide in slides
        ],
    }
    _write_json(result.report_path, payload)
