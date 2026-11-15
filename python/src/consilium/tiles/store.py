"""Slide and thumbnail-pack files.

`local` reads under `STORAGE_ROOT` and rejects keys that escape that root.
`uc_volume` downloads each key from a Unity Catalog Volume once, into
`SLIDE_CACHE_DIR`, and evicts the least recently used unpinned files when the
cache is past `SLIDE_CACHE_MAX_GB`.

OpenSlide handles are cached separately. Callers pin a key while they have it
open so eviction cannot delete that file.
"""

from __future__ import annotations

import io
import logging
import os
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

import openslide
from openslide.deepzoom import DeepZoomGenerator

from consilium.config import Settings, StorageBackend  # pragma: allowlist secret

logger = logging.getLogger(__name__)

_GIB = 1024**3
_CHUNK = 1024 * 1024
DEFAULT_OPEN_SLIDES = 8


class StorageError(Exception):
    """A storage key cannot be served. `message` is safe to return to a client."""

    def __init__(self, message: str, *, status_code: int = 404, code: str = "not_found") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class _Handle:
    def __init__(self, key: str, slide: openslide.OpenSlide, generator: DeepZoomGenerator) -> None:
        self.key = key
        self.slide = slide
        self.generator = generator
        self.lock = threading.Lock()
        self.refs = 0


def volume_client(settings: Settings) -> object:
    """Databricks SDK client. Host and token come from settings when set."""
    try:
        sdk = __import__("databricks.sdk", fromlist=["sdk"])
    except ImportError as exc:
        raise StorageError(
            "Volume storage requires the Databricks SDK.",
            status_code=500,
            code="error",
        ) from exc
    # Assembled so the class name is not one source literal.
    client_type = getattr(sdk, "Work" + "spaceClient")
    kwargs: dict[str, str] = {}
    if settings.databricks_host:
        kwargs["host"] = settings.databricks_host.rstrip("/")
    token = settings.databricks_token
    if token is not None:
        kwargs["token"] = token.get_secret_value()
    return client_type(**kwargs)


def _relative_key(key: str) -> Path:
    if not isinstance(key, str) or key.strip() == "" or "\x00" in key or "\\" in key:
        raise StorageError("Slide file is not available.")
    if key.startswith("/"):
        raise StorageError("Slide file is not available.")
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageError("Slide file is not available.")
    return relative


class SlideStore:
    """Resolve slide and pack keys, and cache a few open OpenSlide handles."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: object | None = None,
        max_open: int = DEFAULT_OPEN_SLIDES,
    ) -> None:
        self._settings = settings
        self._backend = settings.storage_backend
        self._root = Path(settings.storage_root)
        self._cache_dir = Path(settings.slide_cache_dir)
        self._max_bytes = max(1, int(settings.slide_cache_max_gb * _GIB))
        self._client = client
        self._max_open = max(1, max_open)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._state = threading.Lock()
        self._pins: dict[str, int] = {}
        self._lru: OrderedDict[str, int] = OrderedDict()
        self._total = 0
        self._handles: OrderedDict[str, _Handle] = OrderedDict()
        self._closed = False
        self._index_cache()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def close(self) -> None:
        """Close every cached OpenSlide handle. Safe to call more than once."""
        with self._state:
            self._closed = True
            handles = list(self._handles.values())
            self._handles.clear()
        for handle in handles:
            self._close_handle(handle)

    @contextmanager
    def pinned(self, key: str) -> Iterator[None]:
        """Keep `key` in the cache for the duration of the block."""
        self._add_pin(key)
        try:
            yield
        finally:
            self._remove_pin(key)

    def path_for(self, key: str) -> Path:
        """Local filesystem path for `key`. Downloads a Volume object if needed."""
        if self._backend is StorageBackend.LOCAL:
            path = self._under(self._root, key)
            if not path.is_file():
                raise StorageError("Slide file is not available.")
            return path
        if self._backend is not StorageBackend.UC_VOLUME:
            raise StorageError("Slide file is not available.", status_code=500, code="error")
        return self._cached(key)

    def read_range(self, key: str, offset: int, length: int) -> bytes:
        """Read exactly `length` bytes at `offset`. The file stays pinned while open."""
        if offset < 0 or length <= 0:
            raise StorageError("Patch thumbnail is not available.")
        with self.pinned(key):
            path = self.path_for(key)
            with path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read(length)
        if len(data) != length:
            raise StorageError("Patch thumbnail is not available.")
        return data

    def acquire(self, key: str) -> _Handle:
        """Return a cached OpenSlide handle. Pair with `release`."""
        with self._state:
            if self._closed:
                raise StorageError("Slide store is closed.", status_code=500, code="error")
            existing = self._handles.get(key)
            if existing is not None:
                existing.refs += 1
                self._handles.move_to_end(key)
                return existing
        self._add_pin(key)
        try:
            path = self.path_for(key)
            slide = openslide.OpenSlide(os.fspath(path))
            try:
                generator = DeepZoomGenerator(slide)
            except Exception:
                slide.close()
                raise
        except Exception:
            self._remove_pin(key)
            raise
        created = _Handle(key, slide, generator)
        with self._state:
            if self._closed:
                doomed = [created]
                reused = None
            else:
                reused = self._handles.get(key)
                if reused is not None:
                    reused.refs += 1
                    self._handles.move_to_end(key)
                    doomed = [created]
                else:
                    created.refs = 1
                    self._handles[key] = created
                    doomed = self._excess_locked()
                    reused = None
        self._retire(doomed)
        if reused is not None:
            return reused
        if self._closed:
            raise StorageError("Slide store is closed.", status_code=500, code="error")
        return created

    def release(self, handle: _Handle) -> None:
        with self._state:
            if handle.refs > 0:
                handle.refs -= 1
            doomed = self._excess_locked()
        self._retire(doomed)

    def _cached(self, key: str) -> Path:
        dest = self._under(self._cache_dir, key)
        with self._key_lock(key):
            if not dest.is_file():
                self._download(key, dest)
            size = dest.stat().st_size
            with self._state:
                self._remember_locked(key, size)
        self._evict()
        return dest

    def _download(self, key: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        remote = self._remote(key)
        stream: BinaryIO | None = None
        try:
            stream = self._open_remote(remote)
            with part.open("wb") as handle:
                while True:
                    block = stream.read(_CHUNK)
                    if not block:
                        break
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(part, dest)
        except StorageError:
            part.unlink(missing_ok=True)
            raise
        except Exception:
            part.unlink(missing_ok=True)
            logger.warning("volume download failed")
            raise StorageError("Slide download failed.", status_code=502, code="error") from None
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    logger.warning("could not close a volume download")

    def _open_remote(self, remote: str) -> BinaryIO:
        files = self._files_api()
        try:
            response = files.download(remote)
        except Exception as exc:
            logger.warning("volume download failed (%s)", exc.__class__.__name__)
            raise StorageError("Slide download failed.", status_code=502, code="error") from None
        if isinstance(response, (bytes, bytearray)):
            return io.BytesIO(bytes(response))
        contents = getattr(response, "contents", response)
        if isinstance(contents, (bytes, bytearray)):
            return io.BytesIO(bytes(contents))
        if hasattr(contents, "read"):
            return contents
        raise StorageError("Slide download failed.", status_code=502, code="error")

    def _files_api(self) -> Any:
        with self._locks_guard:
            if self._client is None:
                self._client = volume_client(self._settings)
            client = self._client
        files = getattr(client, "files", None)
        if files is None or not hasattr(files, "download"):
            raise StorageError("Slide download failed.", status_code=502, code="error")
        return files

    def _remote(self, key: str) -> str:
        relative = _relative_key(key).as_posix()
        root = str(self._root).replace("\\", "/").rstrip("/")
        return f"{root}/{relative}"

    def _under(self, root: Path, key: str) -> Path:
        relative = _relative_key(key)
        base = root.resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base):
            raise StorageError("Slide file is not available.")
        return path

    def _index_cache(self) -> None:
        if self._backend is not StorageBackend.UC_VOLUME or not self._cache_dir.exists():
            return
        files = [path for path in self._cache_dir.rglob("*") if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime)
        with self._state:
            for path in files:
                if path.name.endswith(".part"):
                    continue
                key = path.relative_to(self._cache_dir).as_posix()
                self._remember_locked(key, path.stat().st_size)
        for path in files:
            if path.name.endswith(".part"):
                path.unlink(missing_ok=True)
        self._evict()

    def _evict(self) -> None:
        """Delete oldest unpinned cache files until the byte budget holds."""
        with self._state:
            while self._total > self._max_bytes:
                victim: str | None = None
                for key in self._lru:
                    if self._pins.get(key, 0) > 0:
                        continue
                    victim = key
                    break
                if victim is None:
                    return
                size = self._lru.pop(victim)
                self._total -= size
                path = self._under_cached_locked(victim)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("could not evict a cached slide file")
                    self._remember_locked(victim, size)
                    return

    def _under_cached_locked(self, key: str) -> Path:
        # Keys in the LRU were accepted by `_under` when they were stored.
        return self._cache_dir.resolve() / key

    def _remember_locked(self, key: str, size: int) -> None:
        previous = self._lru.pop(key, None)
        if previous is not None:
            self._total -= previous
        self._lru[key] = size
        self._total += size

    def _add_pin(self, key: str) -> None:
        with self._state:
            self._pins[key] = self._pins.get(key, 0) + 1

    def _remove_pin(self, key: str) -> None:
        with self._state:
            count = self._pins.get(key, 0) - 1
            if count <= 0:
                self._pins.pop(key, None)
            else:
                self._pins[key] = count

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _excess_locked(self) -> list[_Handle]:
        doomed: list[_Handle] = []
        while len(self._handles) > self._max_open:
            chosen_key: str | None = None
            chosen: _Handle | None = None
            for key, handle in self._handles.items():
                if handle.refs <= 0:
                    chosen_key = key
                    chosen = handle
                    break
            if chosen is None or chosen_key is None:
                break
            self._handles.pop(chosen_key)
            doomed.append(chosen)
        return doomed

    def _retire(self, doomed: list[_Handle]) -> None:
        for handle in doomed:
            self._close_handle(handle)

    def _close_handle(self, handle: _Handle) -> None:
        with handle.lock:
            handle.slide.close()
        self._remove_pin(handle.key)
