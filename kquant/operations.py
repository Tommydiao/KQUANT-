from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import smtplib
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import requests

from .stock_store import connect


NOTIFICATION_TYPES = {
    "new_buy_setup",
    "watch_entry_zone",
    "hard_veto",
    "data_anomaly",
    "manual_plan_invalidation",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:20]}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_operational_event(
    db_path: Path,
    *,
    event_type: str,
    severity: str,
    component: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO operational_events(event_type, severity, component, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type[:120], severity[:20], component[:120], message[:1000], json.dumps(payload or {}, ensure_ascii=True), _now()),
        )
        conn.commit()


def run_scheduled_task(
    db_path: Path,
    *,
    task_name: str,
    idempotency_key: str,
    callback: Callable[[], dict[str, Any]],
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Run one local task with durable idempotency and bounded retries."""

    task = task_name.strip().lower()
    if not task or not idempotency_key:
        raise ValueError("task_name and idempotency_key are required.")
    run_id = f"{task}:{idempotency_key}"
    with connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM scheduled_task_runs WHERE run_id = ?", (run_id,)).fetchone()
        if existing and existing["status"] == "completed":
            return {"status": "already_completed", "run": dict(existing), "idempotent": True}
    last_error = ""
    for attempt in range(1, max(1, int(max_attempts)) + 1):
        started = _now()
        with connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scheduled_task_runs(run_id, task_name, status, started_at, completed_at, attempt, detail_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, task, "running", started, "", attempt, "{}"),
            )
            conn.commit()
        try:
            detail = callback() or {}
            completed = _now()
            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE scheduled_task_runs SET status = ?, completed_at = ?, attempt = ?, detail_json = ? WHERE run_id = ?",
                    ("completed", completed, attempt, json.dumps(detail, ensure_ascii=True), run_id),
                )
                conn.commit()
            record_operational_event(db_path, event_type="scheduled_task", severity="info", component=task, message="Task completed.", payload={"run_id": run_id, "attempt": attempt})
            return {"status": "completed", "run_id": run_id, "attempt": attempt, "detail": detail, "idempotent": False}
        except Exception as exc:  # noqa: BLE001 - task failures are persisted for local recovery.
            last_error = str(exc)
            record_operational_event(db_path, event_type="scheduled_task_error", severity="error", component=task, message=last_error, payload={"run_id": run_id, "attempt": attempt})
    completed = _now()
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE scheduled_task_runs SET status = ?, completed_at = ?, detail_json = ? WHERE run_id = ?",
            ("failed", completed, json.dumps({"error": last_error}, ensure_ascii=True), run_id),
        )
        conn.commit()
    return {"status": "failed", "run_id": run_id, "error": last_error, "attempts": max(1, int(max_attempts)), "idempotent": False}


def queue_notification(
    db_path: Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    channel: str = "web",
) -> dict[str, Any]:
    """Persist a personal alert; external delivery is opt-in and never stores a secret."""

    if event_type not in NOTIFICATION_TYPES:
        raise ValueError("Unsupported notification event type.")
    event_id = _id("notification")
    channel = channel.strip().lower() or "web"
    status = "queued" if channel == "web" else "disabled"
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO notification_events(event_id, channel, event_type, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, channel[:50], event_type, status, json.dumps(payload, ensure_ascii=True), _now()),
        )
        conn.commit()
    return {
        "event_id": event_id,
        "event_type": event_type,
        "channel": channel,
        "status": status,
        "external_delivery_enabled": False,
        "secret_values_stored": False,
        "read_only_research": True,
    }


def recent_notifications(db_path: Path, *, limit: int = 50) -> dict[str, Any]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM notification_events ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
    events = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        events.append(item)
    return {"events": events, "read_only_research": True, "external_delivery_enabled": False}


def dispatch_personal_notification(db_path: Path, *, event_id: str) -> dict[str, Any]:
    """Deliver a queued email/Telegram alert only after an explicit local opt-in.

    Tokens and SMTP passwords are read directly from environment variables and
    are never included in the database event, return payload, or log message.
    """

    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM notification_events WHERE event_id = ?", (event_id,)).fetchone()
    if not row:
        raise ValueError("Unknown notification event.")
    event = dict(row)
    payload = json.loads(event["payload_json"])
    channel = event["channel"]
    enabled = os.getenv("KQUANT_ENABLE_NOTIFICATIONS", "false").lower() == "true"
    status = "disabled"
    reason = "KQUANT_ENABLE_NOTIFICATIONS is not true."
    try:
        if enabled and channel == "telegram":
            token = os.getenv("KQUANT_TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("KQUANT_TELEGRAM_CHAT_ID", "")
            if not token or not chat_id:
                reason = "Telegram credentials are missing."
            else:
                text = f"KQUANT {event['event_type']}: {json.dumps(payload, ensure_ascii=True)}"
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text[:3500]},
                    timeout=8,
                )
                response.raise_for_status()
                status, reason = "sent", "telegram_delivered"
        elif enabled and channel == "email":
            host = os.getenv("KQUANT_SMTP_HOST", "")
            recipient = os.getenv("KQUANT_NOTIFICATION_EMAIL_TO", "")
            sender = os.getenv("KQUANT_NOTIFICATION_EMAIL_FROM", recipient)
            if not host or not recipient or not sender:
                reason = "SMTP host/from/to configuration is missing."
            else:
                message = f"Subject: KQUANT {event['event_type']}\n\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
                with smtplib.SMTP(host, int(os.getenv("KQUANT_SMTP_PORT", "587")), timeout=8) as client:
                    if os.getenv("KQUANT_SMTP_STARTTLS", "true").lower() == "true":
                        client.starttls()
                    username = os.getenv("KQUANT_SMTP_USERNAME", "")
                    password = os.getenv("KQUANT_SMTP_PASSWORD", "")
                    if username and password:
                        client.login(username, password)
                    client.sendmail(sender, [recipient], message)
                status, reason = "sent", "email_delivered"
        elif channel == "web":
            status, reason = "queued", "web_notification_available"
        elif channel not in {"email", "telegram", "web"}:
            reason = "Unsupported notification channel."
    except Exception as exc:  # noqa: BLE001 - delivery failures should be inspectable locally.
        status, reason = "failed", str(exc)
        record_operational_event(db_path, event_type="notification_error", severity="error", component="notifications", message=reason, payload={"event_id": event_id, "channel": channel})
    with connect(db_path) as conn:
        conn.execute("UPDATE notification_events SET status = ? WHERE event_id = ?", (status, event_id))
        conn.commit()
    return {"event_id": event_id, "channel": channel, "status": status, "reason": reason, "secret_values_stored": False}


def operational_health(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        tasks = [dict(row) for row in conn.execute("SELECT * FROM scheduled_task_runs ORDER BY started_at DESC LIMIT 50").fetchall()]
        errors = [dict(row) for row in conn.execute("SELECT * FROM operational_events WHERE severity IN ('error', 'critical') ORDER BY created_at DESC LIMIT 20").fetchall()]
    return {
        "status": "caution" if errors else "healthy",
        "task_runs": tasks,
        "recent_errors": errors,
        "components": {
            "database": "reachable",
            "scheduler": "local_manual_trigger",
            "notifications": "web_queue_only",
            "broker_or_execution": "not_present",
        },
        "read_only_research": True,
    }


def backup_local_workspace(
    db_path: Path,
    *,
    backup_dir: Path,
    config_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Make a verified SQLite backup plus selected non-secret configuration files."""

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    db_backup = backup_dir / f"kquant-us-{stamp}.sqlite3"
    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(db_backup))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    artifacts = [{"type": "sqlite", "path": str(db_backup), "sha256": _sha256(db_backup)}]
    for source_path in config_paths or []:
        if not source_path.exists() or source_path.name.startswith(".env"):
            continue
        target = backup_dir / f"{stamp}-{source_path.name}"
        shutil.copy2(source_path, target)
        artifacts.append({"type": "config", "path": str(target), "sha256": _sha256(target)})
    manifest_path = backup_dir / f"kquant-backup-{stamp}.json"
    manifest = {"created_at": _now(), "artifacts": artifacts, "secret_files_excluded": True, "restore_requires_explicit_target": True}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    backup_id = _id("backup")
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO backup_runs(backup_id, backup_type, path, sha256, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (backup_id, "sqlite_workspace", str(manifest_path), _sha256(manifest_path), "verified", _now()),
        )
        conn.commit()
    return {"backup_id": backup_id, "manifest_path": str(manifest_path), "artifacts": artifacts, "status": "verified", "secret_files_excluded": True}


def restore_drill(backup_path: Path) -> dict[str, Any]:
    """Validate a SQLite backup in isolation; never overwrites the active database."""

    if not backup_path.exists():
        raise ValueError("Backup file does not exist.")
    with tempfile.TemporaryDirectory(prefix="kquant-restore-drill-") as directory:
        drill = Path(directory) / "drill.sqlite3"
        shutil.copy2(backup_path, drill)
        conn = sqlite3.connect(str(drill))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            table_count = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            conn.close()
    return {"status": "passed" if integrity == "ok" else "failed", "integrity_check": integrity, "table_count": table_count, "active_database_overwritten": False}


def timed(operation: Callable[[], dict[str, Any]], *, db_path: Path, component: str, event_type: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001
        record_operational_event(db_path, event_type=event_type, severity="error", component=component, message=str(exc))
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    record_operational_event(db_path, event_type=event_type, severity="info", component=component, message="completed", payload={"elapsed_ms": elapsed_ms})
    return {**result, "elapsed_ms": elapsed_ms}
