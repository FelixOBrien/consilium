"""Stage 5: project TRIDENT ``conch_v15`` features into the CONCH-Z space.

The CONCH-Z model card and ``ConchVisionTower.project`` (revision
``60211fced9c25a014494e248eedb6a6be80109f7``) define the map as

    features @ visual.proj_contrast

then L2-normalisation. ``visual.proj_contrast`` is one float32 matrix of
shape (768, 768). This module reads that tensor with an HTTP range request
and does not download or instantiate the 307M vision backbone.

The slide vector is the L2-normalised mean of the projected patch vectors.
A slide whose output already matches the current weight and the current
source H5 is skipped. One bad slide is recorded and the run continues.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from consilium.embed.spaces import CONCHZ_DIM, UNIT_NORM_ATOL  # pragma: allowlist secret
from consilium.embed.text import scrub_secret  # pragma: allowlist secret
from consilium.pipeline.download import (  # pragma: allowlist secret
    DEMO_SLIDES,
    _one_line,
    _seconds,
    _write_json,
    read_cohort_csv,
)
from consilium.pipeline.extract import (  # pragma: allowlist secret
    CONCH_V15_DIM,
    coords_dirname,
    coords_h5_path,
    features_h5_path,
    validate_features,
)

CONCHZ_REPO = "MahmoodLab/CONCH-Z"
CONCHZ_REVISION = "60211fced9c25a014494e248eedb6a6be80109f7"
PROJ_CONTRAST_KEY = "visual.proj_contrast"
_WEIGHT_URL = (
    f"https://huggingface.co/{CONCHZ_REPO}/resolve/{CONCHZ_REVISION}/model.safetensors"
)
_USER_AGENT = "ingestion-pipeline/0.1 (research prototype; not for clinical use)"


def projected_h5_path(job_dir: Path, slide_id: str) -> Path:
    """Per-slide CONCH-Z features, next to the TRIDENT job and not in git."""
    return job_dir / coords_dirname() / "features_conchz" / f"{slide_id}.h5"


def l2_normalize(values: np.ndarray) -> np.ndarray:
    """Unit-norm float32 copy of a vector ``(...,)`` or a batch ``(N, dim)``."""
    array = np.asarray(values, dtype=np.float64)
    squeezed = False
    if array.ndim == 1:
        array = array.reshape(1, -1)
        squeezed = True
    elif array.ndim != 2:
        raise ValueError("expected a vector or a batch of vectors")
    if array.shape[0] == 0 or array.shape[1] == 0:
        raise ValueError("cannot L2-normalise an empty vector")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms <= 0):
        raise ValueError("cannot L2-normalise a zero or non-finite vector")
    unit = np.asarray(array / norms, dtype=np.float32)
    again = np.linalg.norm(unit, axis=1, keepdims=True)
    unit = np.asarray(unit / again, dtype=np.float32)
    unit = np.ascontiguousarray(unit)
    if squeezed:
        return unit.reshape(-1)
    return unit


def mean_embedding(patches: np.ndarray) -> np.ndarray:
    """L2-normalised mean of projected patch rows. This is the slide vector."""
    matrix = np.asarray(patches)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        raise ValueError("slide vector needs at least one patch")
    return l2_normalize(matrix.mean(axis=0))


class LinearProjector:
    """``features @ weight`` then L2-normalise, the CONCH-Z image projection.

    ``weight`` is ``visual.proj_contrast`` for the real model. Tests pass any
    (768, 768) matrix. ``fingerprint`` is the sha256 of that matrix so a
    weight change re-projects slides that were built with the previous one.
    """

    def __init__(self, weight: np.ndarray, *, name: str = "linear") -> None:
        array = np.asarray(weight, dtype=np.float32)
        if array.shape != (CONCHZ_DIM, CONCHZ_DIM):
            raise ValueError(
                f"{name} weight shape {tuple(array.shape)} is not ({CONCHZ_DIM}, {CONCHZ_DIM})"
            )
        if not np.isfinite(array).all():
            raise ValueError(f"{name} weight contains a non-finite value")
        self.name = name
        self.weight = np.ascontiguousarray(array)
        self._fingerprint = hashlib.sha256(self.weight.tobytes()).hexdigest()

    def fingerprint(self) -> str:
        return self._fingerprint

    def project(self, features: np.ndarray) -> np.ndarray:
        """Project ``(N, 768)`` CONCH v1.5 features to unit-norm CONCH-Z rows."""
        matrix = np.asarray(features)
        if matrix.ndim != 2 or matrix.shape[1] != CONCHZ_DIM:
            raise ValueError(f"features shape {tuple(matrix.shape)} is not (N, {CONCHZ_DIM})")
        if matrix.shape[0] == 0:
            raise ValueError("slide has no patches to project")
        if not np.isfinite(matrix).all():
            raise ValueError("features contain a non-finite value")
        # float32 matches the checkpoint and `features @ proj_contrast`.
        projected = np.asarray(matrix, dtype=np.float32) @ self.weight
        return l2_normalize(projected)


def fetch_proj_contrast(token: str, *, cache_dir: Path | None = None) -> np.ndarray:
    """Load ``visual.proj_contrast`` only.

    The safetensors header is a few dozen kilobytes and the matrix is 2.3 MB.
    A cache hit does not touch the network. The vision-tower tensors stay on
    the server.
    """
    secret = token.strip()
    if secret == "":
        raise RuntimeError(
            "HF_TOKEN is not set. CONCH-Z weights are gated and were not downloaded."
        )
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "consilium"  # pragma: allowlist secret
    directory = cache_dir
    directory.mkdir(parents=True, exist_ok=True)
    cache = directory / f"conchz-visual-proj-contrast-{CONCHZ_REVISION[:12]}.npy"
    if cache.is_file():
        cached = _load_cached_weight(cache)
        if cached is not None:
            return cached
    try:
        weight = _download_proj_contrast(secret)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "CONCH-Z projection download failed: " + scrub_secret(str(exc), secret)
        ) from None
    temporary = cache.with_suffix(".part.npy")
    np.save(temporary, weight)
    os.replace(temporary, cache)
    return weight


@dataclass(frozen=True)
class ProjectedSlide:
    features: np.ndarray
    coords: np.ndarray
    slide_embedding: np.ndarray
    patch_size_level0: int | None
    fingerprint: str


@dataclass(frozen=True)
class SlideProject:
    slide_id: str
    case_id: str
    status: str
    patch_count: int | None
    path: str | None
    error: str | None


@dataclass(frozen=True)
class ProjectResult:
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    total_patches: int
    elapsed_seconds: float
    seconds_per_slide: float | None
    projected_demo_slides: int
    projected_demo_seconds: float | None
    slides: tuple[SlideProject, ...]
    report_path: Path

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
            f"wrote {self.report_path}",
        ]
        for slide in self.slides:
            if slide.status == "failed":
                lines.append(f"failure {slide.slide_id} {_one_line(slide.error)}")
        return "\n".join(lines) + "\n"


def read_projected(path: Path) -> ProjectedSlide:
    """Read one projected slide. Raises ``ValueError`` when the file is unusable."""
    h5py = _h5py()
    with h5py.File(path, "r") as handle:
        names = {"features", "coords", "slide_embedding"}
        if not names <= set(handle):
            raise ValueError("projected H5 is missing features, coords, or slide_embedding")
        features = np.asarray(handle["features"][:], dtype=np.float32)
        coords = np.asarray(handle["coords"][:])
        slide = np.asarray(handle["slide_embedding"][:], dtype=np.float32)
        level0 = _optional_int(handle["coords"].attrs.get("patch_size_level0"))
        fingerprint = _attr_text(handle["features"].attrs.get("proj_fingerprint")) or ""
    _check_projected_arrays(features, coords, slide)
    return ProjectedSlide(
        features=features,
        coords=coords,
        slide_embedding=slide,
        patch_size_level0=level0,
        fingerprint=fingerprint,
    )


def project_cohort(
    *,
    cohort_csv: Path,
    data_root: Path,
    projector: LinearProjector,
    clock: Callable[[], float] | None = None,
) -> ProjectResult:
    """Project every manifest slide. Valid current outputs are not rewritten."""
    slides = read_cohort_csv(cohort_csv)
    job_dir = data_root / "trident"
    report_path = job_dir / "project_report.json"
    job_dir.mkdir(parents=True, exist_ok=True)
    now = clock or _perf_counter()
    started = now()
    fingerprint = projector.fingerprint()
    rows: list[SlideProject] = []
    for slide in slides:
        rows.append(_project_one(slide.slide_id, slide.case_id, job_dir, projector, fingerprint))
    elapsed = now() - started
    succeeded = sum(item.status == "projected" for item in rows)
    skipped = sum(item.status == "skipped" for item in rows)
    failed = sum(item.status == "failed" for item in rows)
    total_patches = sum(item.patch_count or 0 for item in rows if item.status != "failed")
    per_slide = None if succeeded <= 0 else elapsed / succeeded
    result = ProjectResult(
        attempted=len(rows),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        total_patches=total_patches,
        elapsed_seconds=elapsed,
        seconds_per_slide=per_slide,
        projected_demo_slides=DEMO_SLIDES,
        projected_demo_seconds=None if per_slide is None else per_slide * DEMO_SLIDES,
        slides=tuple(rows),
        report_path=report_path,
    )
    _write_project_report(result, fingerprint)
    return result


def _project_one(
    slide_id: str,
    case_id: str,
    job_dir: Path,
    projector: LinearProjector,
    fingerprint: str,
) -> SlideProject:
    destination = projected_h5_path(job_dir, slide_id)
    try:
        patch_count, error = validate_features(job_dir, slide_id, expected_level0=None)
        if error is not None:
            return _row(slide_id, case_id, "failed", None, None, error)
        if _output_is_current(job_dir, slide_id, fingerprint):
            return _row(slide_id, case_id, "skipped", patch_count, destination, None)
        _write_projected(job_dir, slide_id, destination, projector, fingerprint)
        written, error = _validate_written(destination, job_dir, slide_id, fingerprint)
        if error is not None:
            destination.unlink(missing_ok=True)
            return _row(slide_id, case_id, "failed", None, None, error)
        return _row(slide_id, case_id, "projected", written, destination, None)
    except (OSError, RuntimeError, ValueError) as exc:
        destination.unlink(missing_ok=True)
        return _row(slide_id, case_id, "failed", None, None, str(exc))


def _output_is_current(job_dir: Path, slide_id: str, fingerprint: str) -> bool:
    path = projected_h5_path(job_dir, slide_id)
    if not path.is_file():
        return False
    try:
        return _validate_written(path, job_dir, slide_id, fingerprint)[1] is None
    except (OSError, RuntimeError, ValueError):
        return False


def _validate_written(
    path: Path,
    job_dir: Path,
    slide_id: str,
    fingerprint: str,
) -> tuple[int | None, str | None]:
    h5py = _h5py()
    source_features = features_h5_path(job_dir, slide_id)
    source_coords = coords_h5_path(job_dir, slide_id)
    try:
        with h5py.File(path, "r") as handle:
            missing = {"features", "coords", "slide_embedding"} - set(handle)
            if missing:
                return None, "projected H5 is missing features, coords, or slide_embedding"
            attrs = handle["features"].attrs
            if _attr_text(attrs.get("proj_fingerprint")) != fingerprint:
                return None, "projected H5 was built with a different projection"
            if _attr_text(attrs.get("source_features_sha256")) != _sha256_file(source_features):
                return None, "source features changed after projection"
            if _attr_text(attrs.get("source_coords_sha256")) != _sha256_file(source_coords):
                return None, "source coords changed after projection"
            features = np.asarray(handle["features"][:], dtype=np.float32)
            coords = np.asarray(handle["coords"][:])
            slide = np.asarray(handle["slide_embedding"][:], dtype=np.float32)
        with h5py.File(source_coords, "r") as handle:
            source = np.asarray(handle["coords"][:])
    except OSError as exc:
        return None, f"could not read projected H5: {exc}"
    if coords.shape != source.shape or not np.array_equal(coords, source):
        return None, "projected coords do not match the TRIDENT coords"
    try:
        _check_projected_arrays(features, coords, slide)
    except ValueError as exc:
        return None, str(exc)
    return int(features.shape[0]), None


def _check_projected_arrays(
    features: np.ndarray,
    coords: np.ndarray,
    slide: np.ndarray,
) -> None:
    if features.ndim != 2 or features.shape[1] != CONCHZ_DIM or features.shape[0] == 0:
        raise ValueError(
            f"projected features shape {tuple(features.shape)} is not (N, {CONCHZ_DIM})"
        )
    if coords.ndim != 2 or coords.shape[1] != 2 or coords.shape[0] != features.shape[0]:
        raise ValueError("projected coords do not match the feature rows")
    if slide.shape != (CONCHZ_DIM,):
        raise ValueError(f"slide vector shape {tuple(slide.shape)} is not ({CONCHZ_DIM},)")
    if not np.isfinite(features).all() or not np.isfinite(slide).all():
        raise ValueError("projected H5 contains a non-finite value")
    norms = np.linalg.norm(features, axis=1)
    if np.any(np.abs(norms - 1.0) > UNIT_NORM_ATOL):
        raise ValueError("a projected patch vector is not unit-norm")
    slide_norm = float(np.linalg.norm(slide))
    if abs(slide_norm - 1.0) > UNIT_NORM_ATOL:
        raise ValueError(f"slide vector is not unit-norm (norm {slide_norm:.6f})")
    expected = mean_embedding(features)
    if not np.allclose(slide, expected, rtol=0.0, atol=1e-5):
        raise ValueError("slide vector is not the normalised mean of the patch vectors")


def _write_projected(
    job_dir: Path,
    slide_id: str,
    destination: Path,
    projector: LinearProjector,
    fingerprint: str,
) -> None:
    h5py = _h5py()
    source_features = features_h5_path(job_dir, slide_id)
    source_coords = coords_h5_path(job_dir, slide_id)
    with h5py.File(source_features, "r") as handle:
        raw = np.asarray(handle["features"][:])
        if raw.ndim != 2 or int(raw.shape[1]) != CONCH_V15_DIM:
            raise ValueError(f"features shape {tuple(raw.shape)} is not (N, {CONCH_V15_DIM})")
    with h5py.File(source_coords, "r") as handle:
        coords = np.asarray(handle["coords"][:])
        coord_attrs = {key: handle["coords"].attrs[key] for key in handle["coords"].attrs}
    if coords.shape[0] != raw.shape[0]:
        raise ValueError("feature row count does not match coords")
    projected = projector.project(raw)
    slide_vector = mean_embedding(projected)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".h5.part")
    try:
        with h5py.File(temporary, "w") as handle:
            features = handle.create_dataset("features", data=projected)
            features.attrs["encoder"] = "conchz"
            features.attrs["source_encoder"] = "conch_v15"
            features.attrs["projection"] = PROJ_CONTRAST_KEY
            features.attrs["proj_fingerprint"] = fingerprint
            features.attrs["source_features_sha256"] = _sha256_file(source_features)
            features.attrs["source_coords_sha256"] = _sha256_file(source_coords)
            features.attrs["space"] = "conchz"
            written_coords = handle.create_dataset("coords", data=coords)
            for key, value in coord_attrs.items():
                written_coords.attrs[key] = value
            handle.create_dataset("slide_embedding", data=slide_vector)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_project_report(result: ProjectResult, fingerprint: str) -> None:
    payload = {
        "stage": "project",
        "projection": PROJ_CONTRAST_KEY,
        "conchz_revision": CONCHZ_REVISION,
        "proj_fingerprint": fingerprint,
        "attempted": result.attempted,
        "succeeded": result.succeeded,
        "skipped": result.skipped,
        "failed": result.failed,
        "total_patches": result.total_patches,
        "elapsed_seconds": result.elapsed_seconds,
        "seconds_per_slide": result.seconds_per_slide,
        "projected_demo_slides": result.projected_demo_slides,
        "projected_demo_seconds": result.projected_demo_seconds,
        "slides": [
            {
                "slide_id": slide.slide_id,
                "case_id": slide.case_id,
                "status": slide.status,
                "patch_count": slide.patch_count,
                "path": slide.path,
                "error": slide.error,
            }
            for slide in result.slides
        ],
    }
    _write_json(result.report_path, payload)


def _download_proj_contrast(token: str) -> np.ndarray:
    header_size = int.from_bytes(_ranged(token, 0, 7), "little")
    if header_size <= 0 or header_size > 5_000_000:
        raise RuntimeError(f"CONCH-Z safetensors header length {header_size} is not usable")
    header_bytes = _ranged(token, 8, 8 + header_size - 1)
    try:
        header = json.loads(header_bytes)
    except json.JSONDecodeError as exc:
        raise RuntimeError("CONCH-Z safetensors header was not JSON") from exc
    if not isinstance(header, dict) or PROJ_CONTRAST_KEY not in header:
        prefixes = sorted(
            {
                key.split(".", 1)[0]
                for key in header
                if isinstance(key, str) and key != "__metadata__"
            }
        ) if isinstance(header, dict) else []
        raise RuntimeError(
            f"CONCH-Z checkpoint has no {PROJ_CONTRAST_KEY}. Top-level prefixes: {prefixes}"
        )
    info = header[PROJ_CONTRAST_KEY]
    if not isinstance(info, dict):
        raise RuntimeError(f"{PROJ_CONTRAST_KEY} metadata is not an object")
    if info.get("dtype") != "F32" or list(info.get("shape") or []) != [CONCHZ_DIM, CONCHZ_DIM]:
        raise RuntimeError(
            f"{PROJ_CONTRAST_KEY} is {info.get('dtype')} {info.get('shape')}, "
            f"expected F32 [{CONCHZ_DIM}, {CONCHZ_DIM}]"
        )
    offsets = info.get("data_offsets")
    if (
        not isinstance(offsets, list)
        or len(offsets) != 2
        or not all(isinstance(item, int) for item in offsets)
    ):
        raise RuntimeError(f"{PROJ_CONTRAST_KEY} is missing data offsets")
    begin, end = int(offsets[0]), int(offsets[1])
    expected = CONCHZ_DIM * CONCHZ_DIM * 4
    if end - begin != expected or begin < 0:
        raise RuntimeError(f"{PROJ_CONTRAST_KEY} byte length {end - begin} != {expected}")
    absolute = 8 + header_size
    blob = _ranged(token, absolute + begin, absolute + end - 1)
    weight = np.frombuffer(blob, dtype="<f4").reshape(CONCHZ_DIM, CONCHZ_DIM)
    if not np.isfinite(weight).all():
        raise RuntimeError(f"{PROJ_CONTRAST_KEY} contains a non-finite value")
    return np.ascontiguousarray(weight)


def _ranged(token: str, start: int, end_inclusive: int) -> bytes:
    expected = end_inclusive - start + 1
    request = urllib.request.Request(
        _WEIGHT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Range": f"bytes={start}-{end_inclusive}",
            "User-Agent": _USER_AGENT,
        },
        method="GET",
    )
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            scrub_secret(f"CONCH-Z projection download failed: HTTP {exc.code}", token)
        ) from None
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
        raise RuntimeError(
            "CONCH-Z projection download failed: " + scrub_secret(str(exc), token)
        ) from None
    with response:
        if response.status != 206:
            raise RuntimeError(
                f"CONCH-Z weight server returned HTTP {response.status} instead of a byte range"
            )
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != expected:
            raise RuntimeError(f"CONCH-Z range length {length} != {expected}")
        blob = response.read(expected + 1)
    if len(blob) != expected:
        raise RuntimeError(f"CONCH-Z range returned {len(blob)} bytes, expected {expected}")
    return blob


def _load_cached_weight(path: Path) -> np.ndarray | None:
    try:
        weight = np.load(path)
    except (OSError, ValueError):
        return None
    if weight.shape != (CONCHZ_DIM, CONCHZ_DIM) or weight.dtype != np.float32:
        return None
    if not np.isfinite(weight).all():
        return None
    return np.ascontiguousarray(weight)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _h5py() -> object:
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError(
            "h5py is required to read TRIDENT H5 files. "
            "Install it with the dev or pipeline dependency group."
        ) from exc
    return h5py


def _attr_text(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return int(round(float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _row(
    slide_id: str,
    case_id: str,
    status: str,
    patch_count: int | None,
    path: Path | None,
    error: str | None,
) -> SlideProject:
    return SlideProject(
        slide_id=slide_id,
        case_id=case_id,
        status=status,
        patch_count=patch_count,
        path=str(path) if path is not None and path.is_file() else None,
        error=error,
    )


def _perf_counter() -> Callable[[], float]:
    import time

    return time.perf_counter
