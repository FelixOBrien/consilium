"""Stage 6: one JPEG thumbnail pack per slide, plus the alignment check.

Each tissue patch is read at its level-0 ``(x, y)`` with side
``patch_size_level0`` (1024 on a 40x-mpp slide, 512 on a 20x slide). OpenSlide
picks the pyramid level whose downsample is closest without upsampling, and
the region is resized to a compact square only when that level is not already
the thumbnail size. JPEGs are concatenated into ``thumbs/{slide_id}.pack``.
``thumb_offset`` and ``thumb_length`` are stored beside the pack so export
and the alignment check can slice one JPEG back out.

A pack whose index matches the current coordinates, slide file, and JPEG
framing is left untouched. One bad slide is recorded and the run continues.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from consilium.embed.spaces import CONCHZ_DIM  # pragma: allowlist secret
from consilium.embed.text import TextEncoders  # pragma: allowlist secret
from consilium.pipeline.download import (  # pragma: allowlist secret
    DEMO_SLIDES,
    _one_line,
    _seconds,
    _write_json,
    read_cohort_csv,
)
from consilium.pipeline.extract import coords_h5_path  # pragma: allowlist secret
from consilium.pipeline.project import projected_h5_path, read_projected  # pragma: allowlist secret

THUMB_SIDE = 224
JPEG_QUALITY = 80
_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"


def pack_path(data_root: Path, slide_id: str) -> Path:
    return data_root / "thumbs" / f"{slide_id}.pack"


def index_path(data_root: Path, slide_id: str) -> Path:
    return data_root / "thumbs" / f"{slide_id}.index.json"


def pyramid_read(
    level_downsamples: Sequence[float],
    patch_size_level0: int,
    thumb_side: int,
) -> tuple[int, int, bool]:
    """Choose ``(level, read_size, exact)`` the way OpenSlide picks a level.

    ``exact`` means the chosen level already yields ``thumb_side`` pixels, so
    no resize is required. The level is the one with the largest downsample
    that is still less than or equal to ``patch_size_level0 / thumb_side``.
    """
    if patch_size_level0 < 1 or thumb_side < 1:
        raise ValueError("patch and thumbnail sizes must be positive")
    if not level_downsamples:
        raise ValueError("slide has no pyramid levels")
    requested = patch_size_level0 / thumb_side
    level = 0
    best = -1.0
    for index, downsample in enumerate(level_downsamples):
        value = float(downsample)
        if value <= requested + 1e-9 and value >= best:
            best = value
            level = index
    if best <= 0:
        raise ValueError("level downsample must be positive")
    read_size = max(1, int(round(patch_size_level0 / best)))
    return level, read_size, read_size == thumb_side


class SlideSession(Protocol):
    def read_rgb(self, x: int, y: int, patch_size_level0: int, thumb_side: int) -> np.ndarray: ...

    def close(self) -> None: ...


class SlideOpener(Protocol):
    def open(self, path: Path) -> SlideSession: ...


class OpenSlideSession:
    """One open SVS. Reads are level-0 addressed and pyramid-aware."""

    def __init__(self, slide: object) -> None:
        self._slide = slide

    def read_rgb(self, x: int, y: int, patch_size_level0: int, thumb_side: int) -> np.ndarray:
        requested = patch_size_level0 / thumb_side
        level = int(self._slide.get_best_level_for_downsample(requested))  # type: ignore[attr-defined]
        downsample = float(self._slide.level_downsamples[level])  # type: ignore[attr-defined]
        read_size = max(1, int(round(patch_size_level0 / downsample)))
        image = self._slide.read_region((int(x), int(y)), level, (read_size, read_size))  # type: ignore[attr-defined]
        rgb = image.convert("RGB")
        if rgb.size != (thumb_side, thumb_side):
            from PIL import Image

            rgb = rgb.resize((thumb_side, thumb_side), Image.Resampling.BILINEAR)
        array = np.asarray(rgb, dtype=np.uint8)
        if array.shape != (thumb_side, thumb_side, 3):
            raise ValueError(f"thumbnail shape {tuple(array.shape)} is not RGB {thumb_side}")
        return array

    def close(self) -> None:
        self._slide.close()  # type: ignore[attr-defined]


class OpenSlideOpener:
    def open(self, path: Path) -> OpenSlideSession:
        try:
            import openslide
        except ImportError as exc:
            raise RuntimeError(
                "openslide is required to cut patch thumbnails. "
                "Install it with: uv sync --group tiles"
            ) from exc
        try:
            slide = openslide.OpenSlide(str(path))
        except Exception as exc:
            raise RuntimeError(f"unreadable slide: {exc}") from exc
        return OpenSlideSession(slide)


@dataclass(frozen=True)
class ThumbPatch:
    x: int
    y: int
    thumb_offset: int
    thumb_length: int


@dataclass(frozen=True)
class ThumbIndex:
    slide_id: str
    patch_size_level0: int
    thumb_side: int
    jpeg_quality: int
    patches: tuple[ThumbPatch, ...]


@dataclass(frozen=True)
class SlideThumbs:
    slide_id: str
    case_id: str
    status: str
    patch_count: int | None
    path: str | None
    error: str | None


@dataclass(frozen=True)
class ThumbsResult:
    attempted: int
    succeeded: int
    skipped: int
    failed: int
    total_patches: int
    elapsed_seconds: float
    seconds_per_slide: float | None
    projected_demo_slides: int
    projected_demo_seconds: float | None
    slides: tuple[SlideThumbs, ...]
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


@dataclass(frozen=True)
class AlignmentHit:
    prompt: str
    index: int
    x: int
    y: int
    score: float
    path: Path


@dataclass(frozen=True)
class AlignmentResult:
    slide_id: str
    output_dir: Path
    hits: tuple[AlignmentHit, ...]
    strips: tuple[Path, ...]
    manifest_path: Path
    failed: int = 0

    def summary(self) -> str:
        lines = [
            f"slide {self.slide_id}",
            f"hits {len(self.hits)}",
            f"wrote {self.manifest_path}",
        ]
        for strip in self.strips:
            lines.append(f"strip {strip}")
        return "\n".join(lines) + "\n"


def jpeg_framed(blob: bytes) -> bool:
    return len(blob) >= 4 and blob.startswith(_JPEG_SOI) and blob.endswith(_JPEG_EOI)


def encode_jpeg(rgb: np.ndarray, quality: int = JPEG_QUALITY) -> bytes:
    """Encode one RGB thumbnail. The bytes start with SOI and end with EOI."""
    if quality < 1 or quality > 95:
        raise ValueError("jpeg quality must be between 1 and 95")
    array = np.asarray(rgb)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3:
        raise ValueError("thumbnail must be a uint8 RGB array")
    if array.shape[0] < 1 or array.shape[1] < 1:
        raise ValueError("thumbnail is empty")
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(array, mode="RGB").save(buffer, format="JPEG", quality=quality)
    blob = buffer.getvalue()
    if not jpeg_framed(blob):
        raise ValueError("JPEG encoder did not write a framed JPEG")
    return blob


def decode_jpeg(blob: bytes) -> np.ndarray:
    """Decode one pack slice to uint8 RGB. Raises ``ValueError`` when it is not a JPEG."""
    if not jpeg_framed(blob):
        raise ValueError("bytes are not a framed JPEG")
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as image:
        rgb = image.convert("RGB")
        return np.asarray(rgb, dtype=np.uint8)


def read_thumb_index(path: Path) -> ThumbIndex:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("thumbnail index is not an object")
    patches_raw = payload.get("patches")
    if not isinstance(patches_raw, list):
        raise ValueError("thumbnail index has no patches")
    patches: list[ThumbPatch] = []
    for item in patches_raw:
        if not isinstance(item, dict):
            raise ValueError("thumbnail index patch is not an object")
        patches.append(
            ThumbPatch(
                x=int(item["x"]),
                y=int(item["y"]),
                thumb_offset=int(item["thumb_offset"]),
                thumb_length=int(item["thumb_length"]),
            )
        )
    return ThumbIndex(
        slide_id=str(payload["slide_id"]),
        patch_size_level0=int(payload["patch_size_level0"]),
        thumb_side=int(payload["thumb_side"]),
        jpeg_quality=int(payload["jpeg_quality"]),
        patches=tuple(patches),
    )


def read_thumb_jpeg(pack: Path, offset: int, length: int) -> bytes:
    """Slice one JPEG out of a pack. The slice must be a framed JPEG of ``length`` bytes."""
    if offset < 0 or length < 4:
        raise ValueError("thumbnail offset or length is invalid")
    with pack.open("rb") as handle:
        handle.seek(offset)
        blob = handle.read(length)
    if len(blob) != length or not jpeg_framed(blob):
        raise ValueError(f"pack slice at {offset}+{length} is not a JPEG")
    return blob


def thumbs_cohort(
    *,
    cohort_csv: Path,
    data_root: Path,
    opener: SlideOpener | None = None,
    thumb_side: int = THUMB_SIDE,
    jpeg_quality: int = JPEG_QUALITY,
    clock: Callable[[], float] | None = None,
) -> ThumbsResult:
    """Write a thumbnail pack for every manifest slide that has coordinates."""
    if thumb_side < 1:
        raise ValueError("thumb side must be positive")
    if jpeg_quality < 1 or jpeg_quality > 95:
        raise ValueError("jpeg quality must be between 1 and 95")
    slides = read_cohort_csv(cohort_csv)
    report_path = data_root / "trident" / "thumbs_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    reader = opener if opener is not None else OpenSlideOpener()
    now = clock or _perf_counter()
    started = now()
    rows: list[SlideThumbs] = []
    for slide in slides:
        rows.append(
            _thumbs_one(
                slide.slide_id,
                slide.case_id,
                data_root,
                reader,
                thumb_side=thumb_side,
                jpeg_quality=jpeg_quality,
            )
        )
    elapsed = now() - started
    succeeded = sum(item.status == "packed" for item in rows)
    skipped = sum(item.status == "skipped" for item in rows)
    failed = sum(item.status == "failed" for item in rows)
    total = sum(item.patch_count or 0 for item in rows if item.status != "failed")
    per_slide = None if succeeded <= 0 else elapsed / succeeded
    result = ThumbsResult(
        attempted=len(rows),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        total_patches=total,
        elapsed_seconds=elapsed,
        seconds_per_slide=per_slide,
        projected_demo_slides=DEMO_SLIDES,
        projected_demo_seconds=None if per_slide is None else per_slide * DEMO_SLIDES,
        slides=tuple(rows),
        report_path=report_path,
    )
    _write_thumbs_report(result, thumb_side, jpeg_quality)
    return result


def verify_alignment(
    *,
    data_root: Path,
    slide_id: str,
    output_dir: Path,
    prompt: str = "tumour cells",
    contrast: str = "adipose tissue",
    top_k: int = 8,
    encoder: TextEncoders | None = None,
) -> AlignmentResult:
    """Score one slide's projected patches against two prompts and save the top thumbnails.

    The two strips are the smoke-tier check that projection stayed in the text
    space: the patches nearest ``prompt`` should not be the patches nearest
    ``contrast``. Scores are cosine similarity. This does not state a finding.
    """
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if prompt.strip() == "" or contrast.strip() == "":
        raise ValueError("prompts must not be empty")
    projected = read_projected(projected_h5_path(data_root / "trident", slide_id))
    index = read_thumb_index(index_path(data_root, slide_id))
    pack = pack_path(data_root, slide_id)
    if len(index.patches) != projected.features.shape[0]:
        raise ValueError("thumbnail index length does not match projected patches")
    text = encoder if encoder is not None else _default_encoder()
    output_dir.mkdir(parents=True, exist_ok=True)
    hits: list[AlignmentHit] = []
    strips: list[Path] = []
    manifest_prompts: list[dict[str, object]] = []
    for phrase in (prompt, contrast):
        vector = np.asarray(text.encode_image_text(phrase).vector.values, dtype=np.float32)
        if vector.shape != (CONCHZ_DIM,):
            raise ValueError("text vector is not 768-d")
        scores = projected.features @ vector
        order = np.argsort(-scores, kind="stable")
        chosen = [int(item) for item in order[:top_k]]
        images: list[np.ndarray] = []
        phrase_hits: list[dict[str, object]] = []
        slug = _slug(phrase)
        for rank, patch_index in enumerate(chosen):
            recorded = index.patches[patch_index]
            x = int(projected.coords[patch_index, 0])
            y = int(projected.coords[patch_index, 1])
            if recorded.x != x or recorded.y != y:
                raise ValueError(f"thumbnail index row {patch_index} does not match coords")
            blob = read_thumb_jpeg(pack, recorded.thumb_offset, recorded.thumb_length)
            images.append(decode_jpeg(blob))
            destination = output_dir / f"{slug}-{rank:02d}.jpg"
            destination.write_bytes(blob)
            score = float(scores[patch_index])
            hits.append(
                AlignmentHit(
                    prompt=phrase,
                    index=patch_index,
                    x=x,
                    y=y,
                    score=score,
                    path=destination,
                )
            )
            phrase_hits.append(
                {
                    "rank": rank,
                    "patch_index": patch_index,
                    "x": x,
                    "y": y,
                    "score": score,
                    "file": destination.name,
                }
            )
        strip = output_dir / f"{slug}-strip.png"
        _write_strip(images, phrase, strip)
        strips.append(strip)
        manifest_prompts.append({"prompt": phrase, "hits": phrase_hits, "strip": strip.name})
    manifest_path = output_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "slide_id": slide_id,
            "notice": "Embedding similarity between a phrase and a patch. Not a finding.",
            "prompts": manifest_prompts,
        },
    )
    return AlignmentResult(
        slide_id=slide_id,
        output_dir=output_dir,
        hits=tuple(hits),
        strips=tuple(strips),
        manifest_path=manifest_path,
    )


def _thumbs_one(
    slide_id: str,
    case_id: str,
    data_root: Path,
    opener: SlideOpener,
    *,
    thumb_side: int,
    jpeg_quality: int,
) -> SlideThumbs:
    pack = pack_path(data_root, slide_id)
    index = index_path(data_root, slide_id)
    svs = data_root / "slides" / f"{slide_id}.svs"
    coords_path = coords_h5_path(data_root / "trident", slide_id)
    try:
        if not svs.is_file():
            return _row(slide_id, case_id, "failed", None, None, "slide file is missing")
        if not coords_path.is_file():
            return _row(slide_id, case_id, "failed", None, None, "coords H5 is missing")
        coords, level0 = _read_coords(coords_path)
        if _pack_is_current(
            pack,
            index,
            slide_id,
            coords,
            level0,
            svs,
            coords_path,
            thumb_side=thumb_side,
            jpeg_quality=jpeg_quality,
        ):
            return _row(slide_id, case_id, "skipped", int(coords.shape[0]), pack, None)
        _write_pack(
            pack,
            index,
            svs,
            slide_id,
            coords,
            level0,
            coords_path,
            opener,
            thumb_side=thumb_side,
            jpeg_quality=jpeg_quality,
        )
        if not _pack_is_current(
            pack,
            index,
            slide_id,
            coords,
            level0,
            svs,
            coords_path,
            thumb_side=thumb_side,
            jpeg_quality=jpeg_quality,
        ):
            pack.unlink(missing_ok=True)
            index.unlink(missing_ok=True)
            return _row(slide_id, case_id, "failed", None, None, "thumbnail pack failed validation")
        return _row(slide_id, case_id, "packed", int(coords.shape[0]), pack, None)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        pack.unlink(missing_ok=True)
        index.unlink(missing_ok=True)
        return _row(slide_id, case_id, "failed", None, None, str(exc))


def _pack_is_current(
    pack: Path,
    index_file: Path,
    slide_id: str,
    coords: np.ndarray,
    level0: int,
    svs: Path,
    coords_path: Path,
    *,
    thumb_side: int,
    jpeg_quality: int,
) -> bool:
    if not pack.is_file() or not index_file.is_file():
        return False
    try:
        payload = json.loads(index_file.read_text(encoding="utf-8"))
        index = read_thumb_index(index_file)
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        return False
    stat = svs.stat()
    if payload.get("svs_bytes") != stat.st_size or payload.get("svs_mtime_ns") != stat.st_mtime_ns:
        return False
    if payload.get("coords_sha256") != _sha256_file(coords_path):
        return False
    if (
        index.slide_id != slide_id
        or index.patch_size_level0 != level0
        or index.thumb_side != thumb_side
        or index.jpeg_quality != jpeg_quality
        or len(index.patches) != coords.shape[0]
    ):
        return False
    cursor = 0
    try:
        with pack.open("rb") as handle:
            blob_all = handle.read()
    except OSError:
        return False
    for patch, xy in zip(index.patches, coords, strict=True):
        if patch.x != int(xy[0]) or patch.y != int(xy[1]):
            return False
        if patch.thumb_offset != cursor or patch.thumb_length < 4:
            return False
        end = patch.thumb_offset + patch.thumb_length
        if end > len(blob_all) or not jpeg_framed(blob_all[patch.thumb_offset : end]):
            return False
        cursor = end
    return cursor == len(blob_all) and cursor > 0


def _write_pack(
    pack: Path,
    index_file: Path,
    svs: Path,
    slide_id: str,
    coords: np.ndarray,
    level0: int,
    coords_path: Path,
    opener: SlideOpener,
    *,
    thumb_side: int,
    jpeg_quality: int,
) -> None:
    session = opener.open(svs)
    pieces: list[bytes] = []
    patches: list[dict[str, int]] = []
    try:
        cursor = 0
        for xy in coords:
            x = int(xy[0])
            y = int(xy[1])
            rgb = session.read_rgb(x, y, level0, thumb_side)
            blob = encode_jpeg(rgb, jpeg_quality)
            pieces.append(blob)
            patches.append(
                {"x": x, "y": y, "thumb_offset": cursor, "thumb_length": len(blob)}
            )
            cursor += len(blob)
    finally:
        session.close()
    stat = svs.stat()
    payload = {
        "slide_id": slide_id,
        "patch_size_level0": level0,
        "thumb_side": thumb_side,
        "jpeg_quality": jpeg_quality,
        "svs_bytes": stat.st_size,
        "svs_mtime_ns": stat.st_mtime_ns,
        "coords_sha256": _sha256_file(coords_path),
        "patches": patches,
    }
    pack.parent.mkdir(parents=True, exist_ok=True)
    temporary = pack.with_suffix(".pack.part")
    temporary.write_bytes(b"".join(pieces))
    os.replace(temporary, pack)
    _write_json(index_file, payload)


def _read_coords(path: Path) -> tuple[np.ndarray, int]:
    h5py = _h5py()
    with h5py.File(path, "r") as handle:
        if "coords" not in handle:
            raise ValueError("coords H5 has no coords dataset")
        coords = np.asarray(handle["coords"][:])
        raw = handle["coords"].attrs.get("patch_size_level0")
    if coords.ndim != 2 or coords.shape[1] != 2 or coords.shape[0] == 0:
        raise ValueError(f"coords shape {tuple(coords.shape)} is not (N, 2)")
    if raw is None:
        raise ValueError("coords missing attribute patch_size_level0")
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        level0 = int(round(float(raw)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"coords attribute patch_size_level0 is {raw!r}") from exc
    if level0 < 1:
        raise ValueError("patch_size_level0 must be positive")
    return coords, level0


def _write_strip(images: Sequence[np.ndarray], caption: str, path: Path) -> None:
    from PIL import Image, ImageDraw

    if not images:
        raise ValueError("no thumbnails to write")
    side = int(images[0].shape[0])
    gap = 8
    width = side * len(images) + gap * (len(images) - 1)
    header = 28
    canvas = Image.new("RGB", (width, side + header), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 6), caption[:80], fill=(245, 245, 245))
    for index, image in enumerate(images):
        tile = Image.fromarray(np.asarray(image, dtype=np.uint8), mode="RGB")
        if tile.size != (side, side):
            tile = tile.resize((side, side))
        canvas.paste(tile, (index * (side + gap), header))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG")


def _write_thumbs_report(result: ThumbsResult, thumb_side: int, jpeg_quality: int) -> None:
    payload = {
        "stage": "thumbnails",
        "thumb_side": thumb_side,
        "jpeg_quality": jpeg_quality,
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


def _default_encoder() -> TextEncoders:
    from consilium.embed.text import build_text_encoders  # pragma: allowlist secret

    return build_text_encoders()


def _slug(text: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in text.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    return cleaned or "prompt"


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
            "h5py is required to read patch coordinates. "
            "Install it with the dev or pipeline dependency group."
        ) from exc
    return h5py


def _row(
    slide_id: str,
    case_id: str,
    status: str,
    patch_count: int | None,
    path: Path | None,
    error: str | None,
) -> SlideThumbs:
    return SlideThumbs(
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
