from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


def save_roll_validation_report(db_path: Path, report: dict[str, Any]) -> str:
    payload = json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    run_key = {"dataset_hash": report.get("dataset_hash"), "report": report}
    run_id = f"roll_validation_{stable_hash(run_key)[:20]}"
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_roll_validation_runs(
              run_id,strategy_version,validation_version,dataset_hash,status,report_json,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                run_id,
                str(report.get("strategy_version") or ""),
                str(report.get("validation_version") or ""),
                str(report.get("dataset_hash") or ""),
                str(report.get("validation_gate", {}).get("status") or "NO_GO"),
                payload,
                datetime.now(UTC).isoformat(),
            ),
        )
    return run_id


def get_roll_validation_report(db_path: Path, run_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT report_json FROM crypto_roll_validation_runs WHERE run_id=?", (run_id,)).fetchone()
    return json.loads(row["report_json"]) if row else None


def latest_roll_validation_report(db_path: Path) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT report_json FROM crypto_roll_validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return json.loads(row["report_json"]) if row else None


__all__ = ["save_roll_validation_report", "get_roll_validation_report", "latest_roll_validation_report"]
