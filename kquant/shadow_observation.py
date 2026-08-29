from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .forward_pilot import MINIMUM_COMPLETE_MARKET_DAYS, forward_pilot_summary, shadow_start_readiness
from .stock_store import connect


SHADOW_OBSERVATION_VERSION = "shadow_observation_v1.0.0"
DEFAULT_STRATEGY_VERSION = "swing_long_v1.1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _count(conn: Any, table: str) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not exists:
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if row else 0)


def _no_session(db_path: Path) -> dict[str, Any]:
    start_gate = shadow_start_readiness(db_path, DEFAULT_STRATEGY_VERSION)
    freeze = start_gate.get("freeze") or {}
    freeze_ready = bool(start_gate.get("allowed"))
    return {
        "status": "not_started",
        "version": SHADOW_OBSERVATION_VERSION,
        "session": None,
        "market_day_count": 0,
        "observed_trading_days": 0,
        "target_trading_days": MINIMUM_COMPLETE_MARKET_DAYS,
        "candidate_count": 0,
        "completed_outcome_count": 0,
        "completed_forward_outcomes": 0,
        "instruction_events": 0,
        "option_paper_observations": 0,
        "minimum_market_days": MINIMUM_COMPLETE_MARKET_DAYS,
        "minimum_market_days_met": False,
        "strategy_freeze_status": freeze.get("status") if freeze else "not_frozen",
        "start_allowed": freeze_ready,
        "go_no_go": "NO_GO",
        "next_action": start_gate.get("reason") or "Review Shadow Observation prerequisites.",
        "shadow_start": start_gate,
        "real_money_allowed": False,
        "read_only_research": True,
        "as_of": _now(),
    }


def latest_shadow_observation(db_path: Path) -> dict[str, Any]:
    """Return one canonical, read-only status for the forward observation run.

    This endpoint never creates a session and never treats a historical or
    simulated day as a real observation day. A missing session is explicit so
    the UI cannot infer that the minimum evidence has been collected.
    """

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM forward_pilot_sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        instruction_events = _count(conn, "trade_instructions")
        option_paper_observations = _count(conn, "option_paper_observations")
    if not row:
        return _no_session(db_path)

    session_id = str(row["session_id"])
    summary = forward_pilot_summary(db_path, session_id)
    session = summary["session"]
    session_status = str(session.get("status") or "unknown")
    market_day_count = int(summary.get("market_day_count") or 0)
    completed = int(summary.get("completed_outcome_count") or 0)
    minimum_met = market_day_count >= MINIMUM_COMPLETE_MARKET_DAYS
    if session_status == "active":
        status = "collecting"
        next_action = "Record each eligible market day before evaluating the research Gate."
    elif session_status == "prepared":
        status = "prepared"
        next_action = "Activate the reviewed observation session before recording a market day."
    elif session_status == "closed":
        status = "closed"
        next_action = "Review the completed evidence; opening a new session requires a new frozen manifest."
    else:
        status = "review"
        next_action = "Inspect the observation session state before continuing."
    if not minimum_met:
        go_no_go = "NO_GO"
    elif completed == 0 or int(summary.get("data_incident_count") or 0) > 0:
        go_no_go = "NO_GO"
    else:
        go_no_go = "REVIEW"
    return {
        "status": status,
        "version": SHADOW_OBSERVATION_VERSION,
        "session": {
            "session_id": session_id,
            "strategy_version": session.get("strategy_version"),
            "mode": session.get("mode"),
            "status": session_status,
            "start_date": session.get("start_date"),
            "created_at": session.get("created_at"),
        },
        "market_day_count": market_day_count,
        "observed_trading_days": market_day_count,
        "target_trading_days": MINIMUM_COMPLETE_MARKET_DAYS,
        "candidate_count": int(summary.get("candidate_count") or 0),
        "completed_outcome_count": completed,
        "completed_forward_outcomes": completed,
        "instruction_events": instruction_events,
        "option_paper_observations": option_paper_observations,
        "outcome_counts": summary.get("outcome_counts") or {},
        "data_incident_count": int(summary.get("data_incident_count") or 0),
        "minimum_market_days": MINIMUM_COMPLETE_MARKET_DAYS,
        "minimum_market_days_met": minimum_met,
        "start_allowed": False,
        "go_no_go": go_no_go,
        "next_action": next_action,
        "real_money_allowed": False,
        "read_only_research": True,
        "as_of": _now(),
    }
