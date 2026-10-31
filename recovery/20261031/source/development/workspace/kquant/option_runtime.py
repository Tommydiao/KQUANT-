"""Local process locks and persistent checkpoints for the existing option supervisor."""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .stock_store import connect


class OptionProcessLock:
    def __init__(self, db_path: Path, name: str):
        self.path = db_path.resolve().with_name(f"{db_path.name}.option-{name}.lock")
        self.file = None

    def acquire(self) -> bool:
        if self.file is not None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        self.file = handle
        return True

    def release(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None


def write_heartbeat(db_path: Path, worker: str, owner: str, status: str, detail: dict, now: datetime) -> None:
    with connect(db_path) as conn:
        conn.execute("""INSERT INTO option_runtime_heartbeat VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(worker) DO UPDATE SET owner=excluded.owner, updated_at=excluded.updated_at,
            status=excluded.status, detail_json=excluded.detail_json""",
            (worker, owner, now.isoformat(), status, json.dumps(detail, sort_keys=True)))
        conn.commit()


def checkpoint(db_path: Path, task_key: str) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM option_runtime_tasks WHERE task_key=?", (task_key,)).fetchone()
    return dict(row) if row else None


def record_task(db_path: Path, task_key: str, kind: str, market_date: str, status: str, detail: dict, now: datetime) -> None:
    encoded = json.dumps(detail, sort_keys=True)
    stamp = now.isoformat()
    with connect(db_path) as conn:
        conn.execute("""INSERT INTO option_runtime_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_key) DO UPDATE SET status=excluded.status,
            attempts=option_runtime_tasks.attempts + CASE WHEN excluded.status='running' THEN 1 ELSE 0 END,
            started_at=CASE WHEN excluded.status='running' THEN excluded.started_at ELSE option_runtime_tasks.started_at END,
            finished_at=excluded.finished_at, detail_json=excluded.detail_json""", (
            task_key, kind, market_date, status, int(status == "running"),
            stamp if status == "running" else None, None if status == "running" else stamp, encoded,
        ))
        conn.execute("INSERT INTO option_runtime_events VALUES (?, ?, ?, ?, ?)",
                     (uuid.uuid4().hex, task_key, status, stamp, encoded))
        conn.commit()


def runtime_status(db_path: Path) -> dict:
    with connect(db_path) as conn:
        workers = [dict(row) for row in conn.execute("SELECT * FROM option_runtime_heartbeat")]
        tasks = [dict(row) for row in conn.execute("SELECT * FROM option_runtime_tasks ORDER BY started_at DESC LIMIT 12")]
    for row in workers + tasks:
        row["detail"] = json.loads(row.pop("detail_json"))
    for row in workers:
        row["heartbeat_age_seconds"] = (datetime.now(UTC) - datetime.fromisoformat(row["updated_at"])).total_seconds()
        row["live_heartbeat"] = row["status"] == "running" and 0 <= row["heartbeat_age_seconds"] <= 120
    return {"workers": workers, "recent_tasks": tasks}
