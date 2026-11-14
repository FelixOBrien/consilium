"""Text encoders, loaded lazily. `conchz` and `report` stay in separate spaces."""

from consilium.embed.spaces import (  # pragma: allowlist secret
    CONCHZ_DIM,
    REPORT_DIM,
    ConchzEmbedding,
    EmbeddingSpace,
    ReportEmbedding,
    embedding_dim,
)

__all__ = [
    "CONCHZ_DIM",
    "REPORT_DIM",
    "ConchzEmbedding",
    "EmbeddingSpace",
    "ReportEmbedding",
    "embedding_dim",
]
