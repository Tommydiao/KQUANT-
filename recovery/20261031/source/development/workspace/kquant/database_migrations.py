from __future__ import annotations

"""Compatibility facade for the explicit KQUANT SQLite migration registry."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .db.migrations import LATEST_SCHEMA_VERSION, apply_sqlite_migrations, inspect_sqlite_migrations
from .stock_store import default_db_path


SCHEMA_VERSION = LATEST_SCHEMA_VERSION


@dataclass(frozen=True)
class DatabaseTarget:
    scheme: str
    location: str
    runtime_supported: bool
    operational_mode: str


def database_target(database_url: str | None = None, *, default_path: Path | None = None) -> DatabaseTarget:
    value = str(database_url or os.getenv("KQUANT_DATABASE_URL") or "").strip()
    if not value:
        return DatabaseTarget("sqlite", str(default_path or default_db_path()), True, "local_development")
    parsed = urlparse(value)
    if parsed.scheme in {"sqlite", "sqlite3"}:
        path = parsed.path or parsed.netloc
        return DatabaseTarget("sqlite", path, True, "local_development")
    if parsed.scheme in {"postgres", "postgresql"}:
        return DatabaseTarget("postgresql", "postgresql://[redacted]", False, "production_contract_pending_adapter")
    return DatabaseTarget(parsed.scheme or "unknown", "[redacted]", False, "unsupported")


def apply_sqlite_schema_migrations(db_path: Path) -> dict[str, object]:
    """Apply forward-only migrations. Kept for CLI and legacy caller compatibility."""

    return apply_sqlite_migrations(Path(db_path))


def migration_readiness(database_url: str | None = None, *, default_path: Path | None = None) -> dict[str, object]:
    """Inspect migration state without mutating a database."""

    target = database_target(database_url, default_path=default_path)
    payload: dict[str, object] = {
        "target": target.scheme,
        "location": target.location,
        "schema_version": LATEST_SCHEMA_VERSION,
        "runtime_supported": target.runtime_supported,
        "operational_mode": target.operational_mode,
        "rollback_strategy": "verified_backup_restore",
        "read_only_research": True,
    }
    if target.scheme == "sqlite":
        payload["migration"] = inspect_sqlite_migrations(Path(target.location))
    elif target.scheme == "postgresql":
        payload["migration"] = {
            "status": "blocked",
            "reason": "The current SQLite query runtime has no tested PostgreSQL adapter. Do not point production traffic at this URL yet.",
            "required_before_enablement": ["PostgreSQL adapter", "transaction/query parity tests", "staging restore drill"],
        }
    else:
        payload["migration"] = {"status": "blocked", "reason": "Unsupported database scheme."}
    return payload
