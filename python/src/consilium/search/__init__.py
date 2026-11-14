"""Vector, keyword, and fused retrieval.

`search_patches`, `search_reports` and `similar_cases` are the functions the
HTTP routes, the consult agent and the retrieval eval call. They take a
psycopg connection and the text encoders; they do not require FastAPI.

`conchz` (768-d) and `report` (384-d) are never compared with each other.
"""

from consilium.search.common import (  # pragma: allowlist secret
    HNSW_EF_SEARCH,
    HNSW_ITERATIVE_SCAN,
    SearchError,
    configure_hnsw,
)
from consilium.search.patches import search_patches  # pragma: allowlist secret
from consilium.search.reports import search_reports  # pragma: allowlist secret
from consilium.search.similar import case_precedent_text, similar_cases  # pragma: allowlist secret

__all__ = [
    "HNSW_EF_SEARCH",
    "HNSW_ITERATIVE_SCAN",
    "SearchError",
    "case_precedent_text",
    "configure_hnsw",
    "search_patches",
    "search_reports",
    "similar_cases",
]
