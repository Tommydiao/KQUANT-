from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db.migrations import connect, migrate
from .instruction_models import TradeInstruction


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _load(row: Any) -> dict[str, Any] | None:
    return json.loads(row["payload_json"]) if row else None


def save_instruction(db_path: Path, instruction: TradeInstruction) -> tuple[dict[str, Any], bool]:
    """Persist one material-state projection and de-duplicate retries."""

    migrate(db_path)
    payload = instruction.to_mapping()
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT payload_json FROM crypto_trade_instructions WHERE plan_id=? AND material_state_hash=?",
            (instruction.plan_id, instruction.material_state_hash),
        ).fetchone()
        if existing is not None:
            return _load(existing) or payload, False
        conn.execute(
            """
            INSERT INTO crypto_trade_instructions(
              instruction_id,plan_id,evaluation_id,asset_id,symbol,asset_type,
              strategy_version,state,evaluation_decision,execution_class,
              allowed_alert,allowed_paper,allowed_shadow,factor_snapshot_hash,
              material_state_hash,expires_at,created_at,updated_at,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                instruction.instruction_id, instruction.plan_id, instruction.evaluation_id,
                instruction.asset_id, instruction.symbol, instruction.asset_type,
                instruction.strategy_version, instruction.state, instruction.evaluation_decision,
                instruction.execution_class, int(instruction.allowed_alert),
                int(instruction.allowed_paper), int(instruction.allowed_shadow),
                instruction.factor_snapshot_hash, instruction.material_state_hash,
                instruction.expires_at, instruction.created_at, instruction.updated_at,
                _dump(payload),
            ),
        )
        conn.execute(
            """
            INSERT INTO crypto_instruction_events(
              instruction_id,evaluation_id,from_state,to_state,event_type,reason,created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                instruction.instruction_id, instruction.evaluation_id, None,
                instruction.state, "created", instruction.evaluation_decision,
                instruction.created_at,
            ),
        )
    return payload, True


def get_instruction(db_path: Path, instruction_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        return _load(conn.execute(
            "SELECT payload_json FROM crypto_trade_instructions WHERE instruction_id=?",
            (instruction_id,),
        ).fetchone())


def list_instructions(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT payload_json FROM crypto_trade_instructions ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def list_current_instructions(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Return the latest non-terminal instruction per asset."""

    items = list_instructions(db_path, max(limit * 4, limit))
    terminal = {"INVALIDATED", "EXPIRED"}
    current: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        asset_id = str(item.get("asset_id") or item.get("symbol") or "")
        if asset_id in seen:
            continue
        # The newest terminal state suppresses all older projections for the
        # asset; never resurrect a stale monitoring instruction in the UI.
        seen.add(asset_id)
        if item.get("state") in terminal:
            continue
        current.append(item)
        if len(current) >= limit:
            break
    return current


def list_instruction_events(db_path: Path, instruction_id: str) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_instruction_events WHERE instruction_id=? ORDER BY created_at ASC, event_id ASC",
            (instruction_id,),
        ).fetchall()
    return [dict(row) for row in rows]
