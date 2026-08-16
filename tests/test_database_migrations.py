from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kquant.database_migrations import apply_sqlite_schema_migrations, migration_readiness
from kquant.db import LATEST_SCHEMA_VERSION, DatabaseMigrationError
from kquant.stock_store import SCHEMA


def test_migrations_create_auditable_idempotent_schema(tmp_path: Path) -> None:
    db = tmp_path / "fresh.sqlite3"

    first = apply_sqlite_schema_migrations(db)
    second = apply_sqlite_schema_migrations(db)

    assert first["schema_version"] == LATEST_SCHEMA_VERSION
    assert first["newly_applied"] == list(range(1, LATEST_SCHEMA_VERSION + 1))
    assert second["newly_applied"] == []
    assert first["schema_fingerprint"] == second["schema_fingerprint"]
    with sqlite3.connect(db) as conn:
        migration_columns = {row[1] for row in conn.execute("PRAGMA table_info(schema_migrations)")}
        assert {"checksum", "applied_by", "details_json"} <= migration_columns
        assert conn.execute("SELECT COUNT(*) FROM schema_migration_audit").fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM schema_fingerprints").fetchone()[0] >= 1


def test_existing_legacy_database_is_upgraded_without_removing_legacy_tables(tmp_path: Path) -> None:
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO schema_migrations(version, name, applied_at, rollback_note) VALUES (?, ?, ?, ?)",
            (1, "initial_stock_research_schema", "2026-01-01T00:00:00+00:00", "restore backup"),
        )
        conn.execute("CREATE TABLE equity_live_orders(order_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO equity_live_orders(order_id) VALUES ('legacy-order')")
        conn.commit()

    result = apply_sqlite_schema_migrations(db)

    assert result["newly_applied"] == list(range(2, LATEST_SCHEMA_VERSION + 1))
    assert {item["object_name"] for item in result["quarantined_objects"]} == {"equity_live_orders"}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT order_id FROM equity_live_orders").fetchone()[0] == "legacy-order"
        assert conn.execute("SELECT checksum FROM schema_migrations WHERE version = 1").fetchone()[0]


def test_readiness_is_read_only_for_missing_database(tmp_path: Path) -> None:
    db = tmp_path / "missing.sqlite3"

    payload = migration_readiness(default_path=db)

    assert payload["migration"]["status"] == "initialization_required"
    assert not db.exists()


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "tampered.sqlite3"
    apply_sqlite_schema_migrations(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = ?", (LATEST_SCHEMA_VERSION,))
        conn.commit()

    with pytest.raises(DatabaseMigrationError, match="checksum mismatch"):
        apply_sqlite_schema_migrations(db)
