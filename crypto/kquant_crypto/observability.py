from __future__ import annotations

"""Small, secret-free operational summary for local and staging checks."""

import sqlite3
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .db.migrations import connect, migration_status, migrate
from .backup import latest_backup_status
from .staging import staging_status
from .config import API_CONTRACT_VERSION, APP_VERSION, FRONTEND_CONTRACT_VERSION


OBSERVABILITY_VERSION = "crypto_observability_v1.0.0"
_TABLES = (
    "provider_events",
    "operational_events",
    "crypto_data_snapshots",
    "crypto_external_evidence",
    "crypto_roll_decisions",
    "crypto_shadow_observations",
    "crypto_validation_runs",
    "crypto_roll_validation_runs",
)


def _table_counts(db_path: Path) -> dict[str, int]:
    with connect(db_path) as conn:
        result: dict[str, int] = {}
        for table in _TABLES:
            try:
                result[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                result[table] = 0
    return result


def _latest(db_path: Path, table: str, column: str) -> str | None:
    with connect(db_path) as conn:
        try:
            row = conn.execute(f"SELECT MAX({column}) FROM {table}").fetchone()
        except sqlite3.OperationalError:
            return None
    return row[0] if row and row[0] else None


def build_observability_summary(
    db_path: Path,
    *,
    settings: Any | None = None,
    providers: Mapping[str, Any] | None = None,
    runtime: Mapping[str, Any] | None = None,
    shadow: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # The schema call is intentionally read-only.  Startup performs migration;
    # operational dashboards must not acquire a DDL lock.
    schema = migration_status(db_path)
    counts = _table_counts(db_path)
    backup_root = getattr(settings, "root_dir", db_path.parent.parent) / "work" / "backups"
    return {
        "version": OBSERVABILITY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": (runtime or {}).get("started_at"),
        "build_sha": os.getenv("KQUANT_CRYPTO_BUILD_SHA", "local")[:80],
        "version_matrix": {
            "application": APP_VERSION,
            "api": API_CONTRACT_VERSION,
            "frontend": FRONTEND_CONTRACT_VERSION,
            "schema": schema["current_version"],
            "strategy": "crypto_roll_v1.0.0",
        },
        "schema": {
            "status": schema["status"],
            "current_version": schema["current_version"],
            "latest_version": schema["latest_version"],
            "fingerprint": schema["fingerprint"],
        },
        "providers": dict(providers or {}),
        "runtime": dict(runtime or {}),
        "storage": {
            "database_path_configured": True,
            "table_counts": counts,
            "last_provider_event": _latest(db_path, "provider_events", "received_at"),
            "last_operational_event": _latest(db_path, "operational_events", "created_at"),
            "last_data_snapshot": _latest(db_path, "crypto_data_snapshots", "created_at"),
        },
        "shadow": dict(shadow or {}),
        "staging": staging_status(settings),
        "backup": latest_backup_status(backup_root),
        "secrets_exposed": False,
        "research_only": True,
    }


__all__ = ["OBSERVABILITY_VERSION", "build_observability_summary"]
