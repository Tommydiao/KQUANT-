from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate


class PaperGateError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _evaluation(db_path: Path, evaluation_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT result_json FROM crypto_evaluation_runs WHERE evaluation_id=?",
            (evaluation_id,),
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def create_paper_observation(db_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    evaluation_id = str(payload.get("evaluation_id") or "")
    evaluation = _evaluation(db_path, evaluation_id)
    if evaluation is None:
        raise PaperGateError("evaluation_not_found")
    if not evaluation.get("allowed_paper"):
        raise PaperGateError("evaluation_paper_gate_closed")
    if evaluation.get("decision") != "PAPER_REVIEW":
        raise PaperGateError("evaluation_decision_not_paper_review")
    for field_name in ("plan_id", "asset_id", "asset_type", "symbol"):
        if str(payload.get(field_name) or "") != str(evaluation.get(field_name) or ""):
            raise PaperGateError("paper_payload_evaluation_mismatch")
    required = ("plan_id", "asset_id", "asset_type", "symbol", "entry_price", "units", "risk_per_unit", "entry_snapshot_id")
    missing = [key for key in required if payload.get(key) in (None, "")]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    entry_snapshot_id = str(payload["entry_snapshot_id"])
    bound_snapshots = {
        str(item)
        for item in (evaluation.get("source_snapshot_ids") or [])
        if str(item).strip()
    }
    bound_snapshots.update(
        str(item)
        for item in (evaluation.get("snapshot_bindings") or {}).values()
        if str(item).strip()
    )
    if entry_snapshot_id not in bound_snapshots:
        raise PaperGateError("entry_snapshot_not_bound_to_evaluation")
    entry_price = float(payload["entry_price"])
    units = float(payload["units"])
    risk_per_unit = float(payload["risk_per_unit"])
    if entry_price <= 0 or units <= 0 or risk_per_unit <= 0:
        raise ValueError("entry_price, units and risk_per_unit must be positive")
    observation_id = f"paper_{uuid4().hex}"
    now = _now()
    value = {
        "observation_id": observation_id,
        "evaluation_id": evaluation_id,
        "plan_id": str(payload["plan_id"]),
        "asset_id": str(payload["asset_id"]),
        "asset_type": str(payload["asset_type"]),
        "symbol": str(payload["symbol"]),
        "status": "OPEN",
        "entry_price": entry_price,
        "exit_price": None,
        "units": units,
        "risk_per_unit": risk_per_unit,
        "realized_r": None,
        "entry_snapshot_id": entry_snapshot_id,
        "exit_snapshot_id": None,
        "observed_at": str(payload.get("observed_at") or now),
        "closed_at": None,
        "metadata": dict(payload.get("metadata") or {}),
        "created_at": now,
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_paper_observations(
              observation_id,evaluation_id,plan_id,asset_id,asset_type,symbol,
              status,entry_price,exit_price,units,risk_per_unit,realized_r,
              entry_snapshot_id,exit_snapshot_id,observed_at,closed_at,
              metadata_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                value["observation_id"], value["evaluation_id"], value["plan_id"], value["asset_id"],
                value["asset_type"], value["symbol"], value["status"], value["entry_price"],
                value["exit_price"], value["units"], value["risk_per_unit"], value["realized_r"],
                value["entry_snapshot_id"], value["exit_snapshot_id"], value["observed_at"],
                value["closed_at"], json.dumps(value["metadata"], ensure_ascii=True, sort_keys=True), value["created_at"],
            ),
        )
    return value


def close_paper_observation(db_path: Path, observation_id: str, *, exit_price: float, exit_snapshot_id: str, status: str = "CLOSED") -> dict[str, Any]:
    if exit_price <= 0 or not exit_snapshot_id:
        raise ValueError("exit_price and exit_snapshot_id are required")
    migrate(db_path)
    closed_at = _now()
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM crypto_paper_observations WHERE observation_id=?", (observation_id,)).fetchone()
        if row is None:
            raise KeyError(observation_id)
        if row["status"] != "OPEN":
            raise ValueError("paper observation is already closed")
        realized_r = (float(exit_price) - float(row["entry_price"])) / float(row["risk_per_unit"])
        conn.execute(
            "UPDATE crypto_paper_observations SET status=?, exit_price=?, realized_r=?, exit_snapshot_id=?, closed_at=? WHERE observation_id=?",
            (status, float(exit_price), realized_r, exit_snapshot_id, closed_at, observation_id),
        )
        value = dict(conn.execute("SELECT * FROM crypto_paper_observations WHERE observation_id=?", (observation_id,)).fetchone())
    value["metadata"] = json.loads(value.pop("metadata_json"))
    return value


def list_paper_observations(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_paper_observations ORDER BY observed_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    values = []
    for row in rows:
        value = dict(row)
        value["metadata"] = json.loads(value.pop("metadata_json"))
        values.append(value)
    return values
