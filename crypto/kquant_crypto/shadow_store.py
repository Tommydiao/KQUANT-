from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash


SHADOW_OBSERVATION_VERSION = "crypto_shadow_observation_v1.0.0"
USER_STATUSES = frozenset({"pending", "reviewed", "skipped", "paper_observed", "manual_note"})
OUTCOME_STATUSES = frozenset({"pending", "completed", "invalidated", "unavailable"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _parse_time(value: Any, field: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _base_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    as_of_time = _parse_time(payload.get("as_of_time"), "as_of_time")
    data_cutoff_time = _parse_time(payload.get("data_cutoff_time"), "data_cutoff_time")
    as_of = datetime.fromisoformat(as_of_time)
    cutoff = datetime.fromisoformat(data_cutoff_time)
    if cutoff > as_of:
        raise ValueError("data_cutoff_time cannot be after as_of_time")
    asset_scope = str(payload.get("asset_scope") or "crypto").lower()
    if asset_scope not in {"crypto", "stock"}:
        raise ValueError("asset_scope must be crypto or stock")
    asset_id = str(payload.get("asset_id") or "")
    symbol = str(payload.get("symbol") or "").upper()
    strategy_version = str(payload.get("strategy_version") or "")
    action = str(payload.get("action") or "")
    strategy_stage = str(payload.get("strategy_stage") or "UNKNOWN")
    if not asset_id or not symbol or not strategy_version or not action:
        raise ValueError("asset_id, symbol, strategy_version and action are required")
    coverage = float(payload.get("coverage", 0.0))
    if not 0.0 <= coverage <= 1.0:
        raise ValueError("coverage must be between 0 and 1")
    source_ids = [str(item) for item in _list(payload.get("source_snapshot_ids")) if str(item).strip()]
    return {
        "asset_scope": asset_scope,
        "asset_id": asset_id,
        "symbol": symbol,
        "strategy_version": strategy_version,
        "action": action,
        "strategy_stage": strategy_stage,
        "as_of_time": as_of_time,
        "data_cutoff_time": data_cutoff_time,
        "source_status": str(payload.get("source_status") or "unknown").lower(),
        "coverage": coverage,
        "hard_veto": bool(payload.get("hard_veto")),
        "feature_snapshot_id": str(payload.get("feature_snapshot_id") or ""),
        "model_version": str(payload.get("model_version") or ""),
        "factor_snapshot_hash": str(payload.get("factor_snapshot_hash") or ""),
        "source_snapshot_ids": source_ids,
        "entry_zone": _list(payload.get("entry_zone")),
        "stop_zone": _list(payload.get("stop_zone")),
        "target_zone": _list(payload.get("target_zone")),
        "bayesian": dict(payload.get("bayesian") or {}),
        "monte_carlo": dict(payload.get("monte_carlo") or {}),
        "ai_rank": float(payload["ai_rank"]) if payload.get("ai_rank") is not None else None,
        "evaluation_id": str(payload.get("evaluation_id") or ""),
        "roll_id": str(payload.get("roll_id") or ""),
    }


def save_shadow_observation(db_path: Path, payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    value = _base_payload(payload)
    digest = stable_hash({"version": SHADOW_OBSERVATION_VERSION, **value})
    observation_id = f"shadow_{digest[:20]}"
    now = _now()
    stored = {
        "observation_id": observation_id,
        **value,
        "user_status": "pending",
        "user_note": "",
        "outcome_status": "pending",
        "outcome": {},
        "content_hash": digest,
        "created_at": now,
        "updated_at": now,
        "version": SHADOW_OBSERVATION_VERSION,
        "research_only": True,
    }
    migrate(db_path)
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM crypto_shadow_observations WHERE content_hash=?",
            (digest,),
        ).fetchone()
        if existing:
            return _row(existing), False
        conn.execute(
            """
            INSERT INTO crypto_shadow_observations(
              observation_id,asset_scope,asset_id,symbol,strategy_version,action,
              strategy_stage,as_of_time,data_cutoff_time,source_status,coverage,
              hard_veto,feature_snapshot_id,model_version,factor_snapshot_hash,
              source_snapshot_ids_json,entry_zone_json,stop_zone_json,
              target_zone_json,bayesian_json,monte_carlo_json,ai_rank,
              evaluation_id,roll_id,user_status,user_note,outcome_status,
              outcome_json,content_hash,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                observation_id, value["asset_scope"], value["asset_id"], value["symbol"],
                value["strategy_version"], value["action"], value["strategy_stage"],
                value["as_of_time"], value["data_cutoff_time"], value["source_status"],
                value["coverage"], int(value["hard_veto"]), value["feature_snapshot_id"],
                value["model_version"], value["factor_snapshot_hash"],
                _json(value["source_snapshot_ids"]), _json(value["entry_zone"]),
                _json(value["stop_zone"]), _json(value["target_zone"]),
                _json(value["bayesian"]), _json(value["monte_carlo"]), value["ai_rank"],
                value["evaluation_id"], value["roll_id"], stored["user_status"],
                stored["user_note"], stored["outcome_status"], _json(stored["outcome"]),
                digest, now, now,
            ),
        )
        conn.execute(
            "INSERT INTO crypto_shadow_audit_events(observation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
            (observation_id, "created", _json({"content_hash": digest, "version": SHADOW_OBSERVATION_VERSION}), now),
        )
    return stored, True


def _row(row: Any) -> dict[str, Any]:
    value = dict(row)
    for key in (
        "source_snapshot_ids_json",
        "entry_zone_json",
        "stop_zone_json",
        "target_zone_json",
        "bayesian_json",
        "monte_carlo_json",
        "outcome_json",
    ):
        value[key.removesuffix("_json")] = json.loads(value.pop(key) or ("[]" if key.endswith("zone_json") or key == "source_snapshot_ids_json" else "{}"))
    value["hard_veto"] = bool(value["hard_veto"])
    value["research_only"] = True
    value["version"] = SHADOW_OBSERVATION_VERSION
    return value


def get_shadow_observation(db_path: Path, observation_id: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM crypto_shadow_observations WHERE observation_id=?",
            (observation_id,),
        ).fetchone()
    return _row(row) if row else None


def list_shadow_observations(db_path: Path, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_shadow_observations ORDER BY as_of_time DESC, created_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [_row(row) for row in rows]


def review_shadow_observation(
    db_path: Path,
    observation_id: str,
    *,
    user_status: str,
    user_note: str = "",
) -> dict[str, Any]:
    status = str(user_status).lower()
    if status not in USER_STATUSES - {"pending"}:
        raise ValueError(f"unsupported user_status: {user_status}")
    migrate(db_path)
    now = _now()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT observation_id FROM crypto_shadow_observations WHERE observation_id=?",
            (observation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        conn.execute(
            "UPDATE crypto_shadow_observations SET user_status=?, user_note=?, updated_at=? WHERE observation_id=?",
            (status, str(user_note or ""), now, observation_id),
        )
        conn.execute(
            "INSERT INTO crypto_shadow_audit_events(observation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
            (observation_id, "user_review", _json({"user_status": status, "user_note": str(user_note or "")}), now),
        )
        value = _row(conn.execute("SELECT * FROM crypto_shadow_observations WHERE observation_id=?", (observation_id,)).fetchone())
    return value


def record_shadow_outcome(
    db_path: Path,
    observation_id: str,
    *,
    outcome_status: str,
    outcome: Mapping[str, Any],
) -> dict[str, Any]:
    status = str(outcome_status).lower()
    if status not in OUTCOME_STATUSES - {"pending"}:
        raise ValueError(f"unsupported outcome_status: {outcome_status}")
    migrate(db_path)
    now = _now()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT outcome_status FROM crypto_shadow_observations WHERE observation_id=?",
            (observation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(observation_id)
        if row["outcome_status"] != "pending":
            raise ValueError("shadow outcome is immutable once completed")
        conn.execute(
            "UPDATE crypto_shadow_observations SET outcome_status=?, outcome_json=?, updated_at=? WHERE observation_id=?",
            (status, _json(dict(outcome)), now, observation_id),
        )
        conn.execute(
            "INSERT INTO crypto_shadow_audit_events(observation_id,event_type,payload_json,created_at) VALUES(?,?,?,?)",
            (observation_id, "outcome_recorded", _json({"outcome_status": status, "outcome": dict(outcome)}), now),
        )
        value = _row(conn.execute("SELECT * FROM crypto_shadow_observations WHERE observation_id=?", (observation_id,)).fetchone())
    return value


def shadow_summary(db_path: Path, *, validation_gate_status: str = "NO_GO") -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS observation_count,
              COUNT(DISTINCT substr(as_of_time, 1, 10)) AS observed_days,
              SUM(CASE WHEN outcome_status='completed' THEN 1 ELSE 0 END) AS completed_outcomes,
              SUM(CASE WHEN user_status='reviewed' THEN 1 ELSE 0 END) AS reviewed_count,
              SUM(CASE WHEN user_status='skipped' THEN 1 ELSE 0 END) AS skipped_count,
              MAX(as_of_time) AS latest_as_of
            FROM crypto_shadow_observations
            """
        ).fetchone()
    observed_days = int(row["observed_days"] or 0)
    validation_passed = str(validation_gate_status).upper() == "PASS"
    gate_passed = observed_days >= 15 and validation_passed
    return {
        "version": SHADOW_OBSERVATION_VERSION,
        "observation_count": int(row["observation_count"] or 0),
        "observed_trading_days": observed_days,
        "required_trading_days": 15,
        "completed_outcomes": int(row["completed_outcomes"] or 0),
        "reviewed_count": int(row["reviewed_count"] or 0),
        "skipped_count": int(row["skipped_count"] or 0),
        "latest_as_of": row["latest_as_of"],
        "validation_gate_status": validation_gate_status,
        "status": "PASS" if gate_passed else "NO_GO",
        "research_only": True,
        "note": "Calendar observations cannot be replaced by simulated days.",
    }


def list_shadow_audit_events(db_path: Path, observation_id: str) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_shadow_audit_events WHERE observation_id=? ORDER BY created_at ASC, event_id ASC",
            (observation_id,),
        ).fetchall()
    return [
        {**dict(row), "payload": json.loads(row["payload_json"])}
        for row in rows
    ]


__all__ = [
    "SHADOW_OBSERVATION_VERSION",
    "save_shadow_observation",
    "get_shadow_observation",
    "list_shadow_observations",
    "review_shadow_observation",
    "record_shadow_outcome",
    "shadow_summary",
    "list_shadow_audit_events",
]
