"""Offline ingestion.

``manifest`` builds the stage-1 cohort. ``download`` fetches SVS files.
``extract`` reads SVS headers and runs TRIDENT segmentation, patching, and
``conch_v15`` features.
"""

from __future__ import annotations

from consilium.pipeline.manifest import build_manifest  # pragma: allowlist secret

__all__ = ["build_manifest"]
