"""Offline ingestion.

``manifest`` builds the stage-1 cohort. ``download`` fetches SVS files.
``extract`` reads SVS headers and runs TRIDENT segmentation, patching, and
``conch_v15`` features. ``reports`` builds stage-7 patients, reports, chunks,
and concept rows. ``project`` maps features into CONCH-Z. ``thumbs`` writes
patch thumbnail packs. ``export`` writes slide, patch, and concept parquet,
keeping stage-7 concept rows and reading ``patient_id`` from ``path_case``.
``load`` copies parquet into Postgres and builds indexes. ``run`` executes
every stage in that order, with ``reports`` before ``export``. ``worker``
claims queued single-slide jobs and runs those stages for one slide.
"""

from __future__ import annotations

from consilium.pipeline.manifest import build_manifest  # pragma: allowlist secret
from consilium.pipeline.stage_reports import build_stage7  # pragma: allowlist secret

__all__ = ["build_manifest", "build_stage7"]
