from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .stock_store import connect


DEFAULT_RETENTION_DAYS = 90


def provider_event_retention_status(db_path: Path, retention_days: int = DEFAULT_RETENTION_DAYS) -> dict[str, Any]:
    before = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    with connect(db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM provider_events").fetchone()[0])
        eligible = int(conn.execute("SELECT COUNT(*) FROM provider_events WHERE created_at < ?", (before,)).fetchone()[0])
        archived = int(conn.execute("SELECT COALESCE(SUM(archived_count), 0) FROM provider_event_archive_runs WHERE status='archived'").fetchone()[0])
    return {
        "policy": "provider_events_archive_before_delete_v1",
        "retention_days": retention_days,
        "archive_before": before,
        "total_events": total,
        "eligible_for_archive": eligible,
        "archived_events": archived,
        "automatic_deletion": False,
    }


def archive_provider_events(
    *, db_path: Path,
    output_dir: Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    apply: bool = False,
) -> dict[str, Any]:
    """Export old provider events first; deletion is explicit and disabled by default."""

    status = provider_event_retention_status(db_path, retention_days)
    archive_id = f"pea_{uuid.uuid4().hex}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"provider-events-{archive_id}.jsonl"
    rows: list[dict[str, Any]] = []
    with connect(db_path) as conn:
        if apply:
            rows = [dict(row) for row in conn.execute("SELECT * FROM provider_events WHERE created_at < ? ORDER BY id", (status["archive_before"],)).fetchall()]
            archive_path.write_text("".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
            # No event deletion occurs here. A separately reviewed retention operation is required.
        conn.execute(
            """
            INSERT INTO provider_event_archive_runs(
              archive_id, provider, before_time, candidate_count, archived_count, archive_path, status, created_at, details_json
            ) VALUES (?, 'all', ?, ?, ?, ?, ?, ?, ?)
            """,
            (archive_id, status["archive_before"], status["eligible_for_archive"], len(rows), str(archive_path), "archived" if apply else "planned", datetime.now(UTC).isoformat(), json.dumps({"deletion": False}, sort_keys=True)),
        )
        conn.commit()
    return {**status, "archive_id": archive_id, "archive_path": str(archive_path), "status": "archived" if apply else "planned", "deleted_events": 0}
