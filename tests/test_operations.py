from __future__ import annotations

from pathlib import Path

from kquant.database_migrations import apply_sqlite_schema_migrations, migration_readiness
from kquant.operations import (
    backup_local_workspace,
    dispatch_personal_notification,
    operational_health,
    queue_notification,
    restore_drill,
    run_scheduled_task,
)
from kquant.stock_store import connect


def test_schema_migration_is_versioned_and_postgres_is_fail_safe(tmp_path: Path) -> None:
    db = tmp_path / "ops.sqlite3"
    assert apply_sqlite_schema_migrations(db)["schema_version"] == 1
    assert migration_readiness("postgresql://secret@example/db")["runtime_supported"] is False


def test_tasks_notifications_and_monitoring_are_durable_and_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "ops.sqlite3"
    first = run_scheduled_task(db, task_name="preflight", idempotency_key="2026-01-01", callback=lambda: {"checked": True})
    assert first["status"] == "completed"
    assert run_scheduled_task(db, task_name="preflight", idempotency_key="2026-01-01", callback=lambda: {"checked": False})["status"] == "already_completed"
    notice = queue_notification(db, event_type="data_anomaly", payload={"symbol": "NVDA"})
    assert notice["external_delivery_enabled"] is False
    assert dispatch_personal_notification(db, event_id=notice["event_id"])["status"] == "queued"
    assert operational_health(db)["status"] == "healthy"


def test_backup_restore_drill_never_overwrites_live_database(tmp_path: Path) -> None:
    db = tmp_path / "ops.sqlite3"
    with connect(db) as conn:
        conn.execute("INSERT INTO audit_events(event_type, payload_json, created_at) VALUES (?, ?, ?)", ("test", "{}", "2026-01-01T00:00:00+00:00"))
        conn.commit()
    backup = backup_local_workspace(db, backup_dir=tmp_path / "backups")
    sqlite_artifact = Path(next(item["path"] for item in backup["artifacts"] if item["type"] == "sqlite"))
    drill = restore_drill(sqlite_artifact)
    assert drill["status"] == "passed"
    assert drill["active_database_overwritten"] is False
