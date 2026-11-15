"""Database access. Queries live here; routers stay thin."""

from consilium.db.connection import connect, connection_pool  # pragma: allowlist secret
from consilium.db.migrate import (  # pragma: allowlist secret
    LakebaseIndexesNotImplemented,
    migrate,
    migration_status,
)
from consilium.db.seed import STORED_TABLES, seed  # pragma: allowlist secret

__all__ = [
    "STORED_TABLES",
    "LakebaseIndexesNotImplemented",
    "connect",
    "connection_pool",
    "migrate",
    "migration_status",
    "seed",
]
