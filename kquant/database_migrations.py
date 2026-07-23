from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .stock_store import connect, default_db_path


SCHEMA_VERSION = 1
MIGRATION_NAME = "initial_stock_research_schema"


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
    """Initialize/version the SQLite schema without destructive rewrites."""

    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY version").fetchall()
        if not any(int(row["version"]) == SCHEMA_VERSION for row in existing):
            conn.execute(
                "INSERT INTO schema_migrations(version, name, applied_at, rollback_note) VALUES (?, ?, ?, ?)",
                (SCHEMA_VERSION, MIGRATION_NAME, now, "Restore a verified SQLite backup; schema migrations are forward-only."),
            )
            conn.commit()
        rows = conn.execute("SELECT version, name, applied_at, rollback_note FROM schema_migrations ORDER BY version").fetchall()
    return {
        "target": "sqlite",
        "schema_version": SCHEMA_VERSION,
        "applied": [dict(row) for row in rows],
        "rollback": "restore_verified_sqlite_backup",
        "destructive_operations": False,
    }


def migration_readiness(database_url: str | None = None, *, default_path: Path | None = None) -> dict[str, object]:
    target = database_target(database_url, default_path=default_path)
    payload: dict[str, object] = {
        "target": target.scheme,
        "location": target.location,
        "schema_version": SCHEMA_VERSION,
        "runtime_supported": target.runtime_supported,
        "operational_mode": target.operational_mode,
        "rollback_strategy": "verified_backup_restore",
        "read_only_research": True,
    }
    if target.scheme == "sqlite":
        payload["migration"] = apply_sqlite_schema_migrations(Path(target.location))
    elif target.scheme == "postgresql":
        payload["migration"] = {
            "status": "blocked",
            "reason": "The current SQLite query runtime has no tested PostgreSQL adapter. Do not point production traffic at this URL yet.",
            "required_before_enablement": ["PostgreSQL adapter", "transaction/query parity tests", "staging restore drill"],
        }
    else:
        payload["migration"] = {"status": "blocked", "reason": "Unsupported database scheme."}
    return payload
