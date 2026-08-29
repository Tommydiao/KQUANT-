from __future__ import annotations

"""Fail-closed PostgreSQL staging readiness and migration compatibility.

SQLite remains the local runtime.  PostgreSQL support is explicit and
optional: no connection is attempted until a staging DSN is configured and
the operator invokes the verifier or migration command.
"""

import importlib.util
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .db.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS


STAGING_CONTRACT_VERSION = "crypto_staging_contract_v1.1.0"
POSTGRES_DRIVER_PACKAGE = "psycopg"
_AUTOINCREMENT = re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE)
_INTEGER_PRIMARY = re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\b", re.IGNORECASE)


def _dsn(settings: Any | None = None) -> str:
    return str(
        getattr(settings, "staging_database_url", "")
        or os.getenv("KQUANT_CRYPTO_STAGING_DATABASE_URL", "")
    ).strip()


def _driver_available() -> bool:
    return importlib.util.find_spec(POSTGRES_DRIVER_PACKAGE) is not None


def _safe_scheme(value: str) -> str:
    try:
        return urlsplit(value).scheme.lower()
    except ValueError:
        return ""


def postgres_sql(sql: str) -> str:
    """Translate the deliberately small SQLite DDL subset to PostgreSQL."""

    translated = _AUTOINCREMENT.sub("BIGSERIAL PRIMARY KEY", str(sql))
    translated = _INTEGER_PRIMARY.sub("BIGINT PRIMARY KEY", translated)
    translated = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", translated, flags=re.IGNORECASE)
    # The current migration SQL does not contain INSERT OR IGNORE, but keeping
    # the replacement here documents the only conflict syntax translation the
    # staging runner permits.
    translated = translated.replace("BEGIN;", "").replace("COMMIT;", "")
    return translated


def postgres_migration_plan() -> list[dict[str, Any]]:
    """Return a deterministic, secret-free PostgreSQL migration plan."""

    hooks = {
        7: (
            "ALTER TABLE crypto_trade_plan_drafts ADD COLUMN IF NOT EXISTS snapshot_bindings_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE crypto_evaluation_runs ADD COLUMN IF NOT EXISTS snapshot_bindings_json TEXT NOT NULL DEFAULT '{}'",
        ),
        11: (
            "ALTER TABLE crypto_validation_trades ADD COLUMN IF NOT EXISTS evidence_partition TEXT NOT NULL DEFAULT 'legacy'",
            "ALTER TABLE crypto_validation_trades ADD COLUMN IF NOT EXISTS oos_fold INTEGER",
            "CREATE INDEX IF NOT EXISTS idx_crypto_validation_trades_evidence ON crypto_validation_trades(run_id, evidence_partition, oos_fold, signal_time)",
        ),
        12: (
            "ALTER TABLE crypto_validation_trades ADD COLUMN IF NOT EXISTS factor_values_json TEXT NOT NULL DEFAULT '{}'",
        ),
    }
    return [
        {
            "version": migration.version,
            "name": migration.name,
            "checksum": migration.checksum,
            "sql": postgres_sql(migration.sql),
            "hook_sql": list(hooks.get(migration.version, ())),
        }
        for migration in MIGRATIONS
    ]


def staging_status(settings: Any | None = None) -> dict[str, Any]:
    dsn = _dsn(settings)
    scheme = _safe_scheme(dsn)
    configured = bool(dsn)
    valid_scheme = scheme in {"postgres", "postgresql"}
    driver = _driver_available()
    if not configured:
        status = "not_configured"
        compatibility = "not_configured"
    elif not valid_scheme:
        status = "invalid_database_url"
        compatibility = "blocked"
    elif not driver:
        status = "configured_driver_missing"
        compatibility = "portable_plan_ready_driver_required"
    else:
        status = "configured_pending_connection"
        compatibility = "portable_plan_ready"
    return {
        "contract_version": STAGING_CONTRACT_VERSION,
        "status": status,
        "postgres_configured": configured,
        "postgres_scheme": scheme or None,
        "driver_available": driver,
        "sqlite_development": True,
        "query_contract": "portable_sqlite_postgres_subset",
        "migration_plan_version": LATEST_SCHEMA_VERSION,
        "migration_compatibility": compatibility,
        "protected_backend_required": True,
        "research_only": True,
        "secrets_exposed": False,
        "dsn_exposed": False,
    }


def verify_staging(settings: Any | None = None, *, apply_migrations: bool = False) -> dict[str, Any]:
    """Verify or migrate an explicitly configured staging PostgreSQL DSN."""

    dsn = _dsn(settings)
    status = staging_status(settings)
    if not dsn:
        return {**status, "connection_status": "not_configured", "migration_status": "not_run"}
    if status["postgres_scheme"] not in {"postgres", "postgresql"}:
        return {**status, "connection_status": "blocked", "migration_status": "not_run", "error_type": "invalid_scheme"}
    if not status["driver_available"]:
        return {**status, "connection_status": "blocked", "migration_status": "not_run", "error_type": "driver_missing"}
    try:
        import psycopg  # type: ignore

        with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                migration_status = "verified_connection_only"
                applied: list[int] = []
                if apply_migrations:
                    cursor.execute(
                        "CREATE TABLE IF NOT EXISTS schema_migrations (version BIGINT PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
                    )
                    cursor.execute(
                        "CREATE TABLE IF NOT EXISTS schema_migration_audit (audit_id BIGSERIAL PRIMARY KEY, version BIGINT NOT NULL, name TEXT NOT NULL, checksum TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL, recorded_at TEXT NOT NULL)"
                    )
                    cursor.execute(
                        "CREATE TABLE IF NOT EXISTS schema_fingerprints (fingerprint TEXT PRIMARY KEY, schema_version BIGINT NOT NULL, object_count BIGINT NOT NULL, computed_at TEXT NOT NULL)"
                    )
                    cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
                    applied = [int(row[0]) for row in cursor.fetchall()]
                    for item in postgres_migration_plan():
                        if item["version"] in applied:
                            continue
                        cursor.execute(item["sql"])
                        for hook in item["hook_sql"]:
                            cursor.execute(hook)
                        cursor.execute(
                            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(%s,%s,%s,now()) ON CONFLICT (version) DO NOTHING",
                            (item["version"], item["name"], item["checksum"]),
                        )
                        cursor.execute(
                            "INSERT INTO schema_migration_audit(version,name,checksum,status,details_json,recorded_at) VALUES(%s,%s,%s,%s,%s,now())",
                            (item["version"], item["name"], item["checksum"], "applied", "{}"),
                        )
                        applied.append(item["version"])
                    migration_status = "migrated" if len(applied) == LATEST_SCHEMA_VERSION else "partial"
        return {
            **status,
            "connection_status": "available",
            "migration_status": migration_status,
            "applied_versions": sorted(applied),
            "schema_version": max(applied, default=0),
        }
    except Exception as exc:  # Do not expose DSN or provider response bodies.
        return {
            **status,
            "connection_status": "unavailable",
            "migration_status": "not_run",
            "error_type": type(exc).__name__,
        }


__all__ = [
    "STAGING_CONTRACT_VERSION",
    "POSTGRES_DRIVER_PACKAGE",
    "postgres_sql",
    "postgres_migration_plan",
    "staging_status",
    "verify_staging",
]
