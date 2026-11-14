"""Database access. Queries live here; routers stay thin."""

from consilium.db.connection import connect, connection_pool  # pragma: allowlist secret
from consilium.db.migrate import (  # pragma: allowlist secret
    LakebaseIndexesNotImplemented,
    LakebaseMigrationRefused,
    migrate,
    migration_status,
)

__all__ = [
    "LakebaseIndexesNotImplemented",
    "LakebaseMigrationRefused",
    "connect",
    "connection_pool",
    "migrate",
    "migration_status",
]
