"""Deep Zoom descriptors, tiles and thumbnails.

OpenSlide and pack reads block. The slide routes are synchronous, so FastAPI
runs them on its worker threadpool and they stay off the asyncio event loop.
"""

from __future__ import annotations

import io

from PIL import Image

from consilium.tiles.store import SlideStore, StorageError  # pragma: allowlist secret

TILE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_THUMBNAIL_MAX_PX = 512


class TileOutOfRange(Exception):
    """The requested Deep Zoom level, column or row is outside the slide."""


def descriptor(store: SlideStore, storage_key: str) -> str:
    handle = store.acquire(storage_key)
    try:
        with handle.lock:
            return handle.generator.get_dzi("jpeg")
    finally:
        store.release(handle)


def tile_jpeg(store: SlideStore, storage_key: str, level: int, col: int, row: int) -> bytes:
    handle = store.acquire(storage_key)
    try:
        with handle.lock:
            try:
                image = handle.generator.get_tile(level, (col, row))
            except ValueError as exc:
                raise TileOutOfRange from exc
            return _jpeg(image)
    finally:
        store.release(handle)


def slide_thumbnail(store: SlideStore, storage_key: str) -> bytes:
    handle = store.acquire(storage_key)
    try:
        with handle.lock:
            image = handle.slide.get_thumbnail((_THUMBNAIL_MAX_PX, _THUMBNAIL_MAX_PX))
            return _jpeg(image)
    finally:
        store.release(handle)


def pack_jpeg(store: SlideStore, pack_key: str, offset: int, length: int) -> bytes:
    """Exact JPEG bytes from a slide's thumbnail pack."""
    data = store.read_range(pack_key, offset, length)
    if not data.startswith(b"\xff\xd8"):
        raise StorageError("Patch thumbnail is not available.")
    return data


def _jpeg(image: Image.Image) -> bytes:
    if image.mode != "RGB":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()
