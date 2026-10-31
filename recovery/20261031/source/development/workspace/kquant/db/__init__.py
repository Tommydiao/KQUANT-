"""Explicit SQLite schema migration support for KQUANT."""

from .migrations import (
    LATEST_SCHEMA_VERSION,
    DatabaseMigrationError,
    apply_sqlite_migrations,
    inspect_sqlite_migrations,
    schema_fingerprint,
)

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "DatabaseMigrationError",
    "apply_sqlite_migrations",
    "inspect_sqlite_migrations",
    "schema_fingerprint",
]
