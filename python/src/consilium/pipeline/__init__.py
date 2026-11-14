"""Offline ingestion.

``manifest`` builds the stage-1 cohort. ``download`` fetches SVS files.
``extract`` reads SVS headers and runs TRIDENT segmentation, patching, and
``conch_v15`` features. ``reports`` and ``encode-concepts`` build stage-7
patients, reports, chunks, and concept embeddings.
"""

from __future__ import annotations

from consilium.pipeline.manifest import build_manifest  # pragma: allowlist secret
from consilium.pipeline.stage_reports import build_stage7  # pragma: allowlist secret

__all__ = ["build_manifest", "build_stage7"]
