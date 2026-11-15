"""Serve the built SvelteKit app from FastAPI.

`/api` is registered first, in `create_app`. This module only handles other
GET and HEAD paths: a file inside the build directory, or `index.html` so a
client-side route survives a reload. Paths that escape the build directory
are rejected.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response

from consilium.api.errors import fail  # pragma: allowlist secret

_MEDIA_TYPES = {
    ".css": "text/css",
    ".gif": "image/gif",
    ".html": "text/html",
    ".ico": "image/x-icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript",
    ".json": "application/json",
    ".map": "application/json",
    ".mjs": "text/javascript",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".wasm": "application/wasm",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def ready_build_dir(path: Path | None) -> Path | None:
    """Absolute build directory that contains `index.html`, or none."""
    if path is None:
        return None
    candidate = path if path.is_absolute() else Path.cwd() / path
    root = candidate.resolve()
    if (root / "index.html").is_file():
        return root
    return None


def _unsafe_static_path(url_path: str) -> bool:
    if url_path.startswith("/") or "\x00" in url_path or "\\" in url_path:
        return True
    return ".." in Path(url_path).parts


def classify_static(root: Path, url_path: str) -> Path | None:
    """File to serve, or None when the SPA entry should be used.

    Raises `HTTPException` when the path escapes `root`.
    """
    if url_path == "":
        return None
    if _unsafe_static_path(url_path):
        fail(404, "not_found", "Not found.")
    base = root.resolve()
    candidate = (base / url_path).resolve()
    if not candidate.is_relative_to(base):
        fail(404, "not_found", "Not found.")
    if candidate.is_file():
        return candidate
    return None


def media_type_for(path: Path) -> str:
    extra = _MEDIA_TYPES.get(path.suffix.lower())
    if extra is not None:
        return extra
    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def install_spa(app: FastAPI, web_build_dir: Path | None) -> None:
    """Serve `web_build_dir` when it contains `index.html`.

    Missing or empty builds leave `/` to FastAPI. Startup still succeeds, so
    API tests do not need a web build.
    """
    root = ready_build_dir(web_build_dir)
    if root is None:
        return
    index = root / "index.html"

    def respond(url_path: str) -> Response:
        asset = classify_static(root, url_path)
        if asset is None:
            return FileResponse(index, media_type="text/html")
        return FileResponse(asset, media_type=media_type_for(asset))

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def spa_index() -> Response:
        return respond("")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa_path(full_path: str) -> Response:
        # Known API routes are registered first and never reach this handler.
        if full_path == "api" or full_path.startswith("api/"):
            fail(404, "not_found", "Not found.")
        return respond(full_path)
