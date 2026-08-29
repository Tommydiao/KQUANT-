from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .roll_engine import RollDecision


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def save_roll_decision(db_path: Path, decision: RollDecision) -> tuple[dict[str, Any], bool]:
    migrate(db_path)
    payload = decision.to_mapping()
    content_hash = stable_hash(payload)
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT payload_json FROM crypto_roll_plans WHERE content_hash=?",
            (content_hash,),
        ).fetchone()
        if existing is not None:
            return json.loads(existing["payload_json"]), False
        conn.execute(
            """
            INSERT INTO crypto_roll_plans(
              roll_id,asset_id,symbol,asset_type,strategy_version,policy_version,
              action,status,as_of_time,data_cutoff_time,source_status,coverage,
              hard_veto,roll_capital,remaining_risk,feature_snapshot_id,model_version,
              source_snapshot_ids_json,blockers_json,warnings_json,payload_json,
              content_hash,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision.roll_id, decision.asset_id, decision.symbol, decision.asset_type,
                decision.strategy_version, decision.policy_version, decision.action,
                decision.status, decision.as_of_time, decision.data_cutoff_time,
                decision.source_status, decision.coverage, int(decision.hard_veto),
                decision.roll_capital, decision.remaining_risk, decision.feature_snapshot_id,
                decision.model_version, _dump(list(decision.source_snapshot_ids)),
                _dump(list(decision.blockers)), _dump(list(decision.warnings)),
                _dump(payload), content_hash, datetime.now(UTC).isoformat(),
            ),
        )
    return payload, True


def get_roll_decision(db_path: Path, roll_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT payload_json FROM crypto_roll_plans WHERE roll_id=?", (roll_id,)).fetchone()
    return json.loads(row["payload_json"]) if row else None


def list_roll_decisions(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM crypto_roll_plans ORDER BY as_of_time DESC, created_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def list_current_roll_decisions(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    items = list_roll_decisions(db_path, max(limit * 4, limit))
    current: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        asset_id = str(item.get("asset_id") or item.get("symbol") or "")
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        current.append(item)
        if len(current) >= limit:
            break
    return current


def record_roll_ledger_event(
    db_path: Path,
    *,
    asset_id: str,
    symbol: str,
    event_type: str,
    realized_profit: float,
    rolled_capital: float,
    remaining_risk: float,
    occurred_at: str,
    roll_id: str | None = None,
    user_note: str = "",
) -> dict[str, Any]:
    if realized_profit < 0 or rolled_capital < 0 or remaining_risk < 0:
        raise ValueError("roll ledger values cannot be negative")
    if rolled_capital > realized_profit:
        raise ValueError("rolled_capital cannot exceed realized_profit")
    payload = {
        "asset_id": asset_id,
        "symbol": symbol,
        "event_type": event_type,
        "realized_profit": float(realized_profit),
        "rolled_capital": float(rolled_capital),
        "remaining_risk": float(remaining_risk),
        "occurred_at": occurred_at,
        "roll_id": roll_id,
        "user_note": user_note,
    }
    content_hash = stable_hash(payload)
    result = {"ledger_id": f"ledger_{content_hash[:20]}", "content_hash": content_hash, **payload}
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_roll_ledger(
              ledger_id,roll_id,asset_id,symbol,event_type,realized_profit,
              rolled_capital,remaining_risk,user_note,occurred_at,content_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                result["ledger_id"], roll_id, asset_id, symbol, event_type,
                float(realized_profit), float(rolled_capital), float(remaining_risk),
                user_note, occurred_at, content_hash,
            ),
        )
    return result


def list_roll_ledger(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_roll_ledger ORDER BY occurred_at DESC, ledger_id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "save_roll_decision",
    "get_roll_decision",
    "list_roll_decisions",
    "list_current_roll_decisions",
    "record_roll_ledger_event",
    "list_roll_ledger",
]
