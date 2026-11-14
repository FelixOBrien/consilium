"""Offline ingestion.

The ``manifest`` subcommand builds the stage-1 cohort manifest.
Later stages are not implemented here.
"""

from __future__ import annotations

from consilium.pipeline.manifest import build_manifest  # pragma: allowlist secret

__all__ = ["build_manifest"]
