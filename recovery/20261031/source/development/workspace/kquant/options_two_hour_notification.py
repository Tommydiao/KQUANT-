"""An exact O-SETUP decision may exempt qualified 2H alerts from quiet hours only."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .market_clock import is_trading_day, session_bounds_utc
from .options_two_hour import load_policy
from .options_two_hour_data import universe
from .options_signal_copilot import DEFAULT_STORE_PATH

APPROVAL_PATH = Path(__file__).resolve().parents[1] / "config/review_acceptances/options_two_hour_notification_o_setup_v1.json"


def quiet_hour_exception(payload: dict, *, db_path: Path, moment: datetime,
                         approval_path: Path | None = None, signal_store: Path = DEFAULT_STORE_PATH) -> bool:
    path = approval_path or APPROVAL_PATH
    if not path.is_file() or not signal_store.is_file():
        return False
    try:
        current = moment.astimezone(UTC)
        from zoneinfo import ZoneInfo

        day = current.astimezone(ZoneInfo("America/New_York")).date()
        if not is_trading_day(day):
            return False
        opening, closing = session_bounds_utc(day)
        if not opening <= current < min(opening + timedelta(hours=2), closing):
            return False
        approval = json.loads(path.read_text(encoding="utf-8-sig"))
        if not (approval.get("gate") == "O-SETUP" and approval.get("status") == "APPROVED"
                and approval.get("approved_by") == "OWNER"
                and approval.get("choice") == "SESSION_AWARE_RESEARCH_WINDOW_EXCEPTION"
                and approval.get("daily_limit") == 5 and approval.get("repeat") is False
                and approval.get("sound") is False
                and datetime.fromisoformat(approval["approved_at"]).astimezone(UTC) <= current):
            return False
        policy_hash = load_policy()["policy_hash"]
        scope_hash = universe(db_path)["scope_hash"]
        if not (approval.get("policy_hash") == payload.get("policy_hash") == policy_hash
                and approval.get("scope_hash") == payload.get("scope_hash") == scope_hash
                and payload.get("type") == "options_two_hour_research"
                and payload.get("qualified") is True and payload.get("severity") == "INFO"):
            return False
        observed = datetime.fromisoformat(payload["bar_end"]).astimezone(UTC)
        deadline = datetime.fromisoformat(payload["deadline_at"]).astimezone(UTC)
        if not opening + timedelta(minutes=10) <= observed <= current < deadline:
            return False
        with sqlite3.connect(f"file:{signal_store.resolve().as_posix()}?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT payload_json FROM signals WHERE signal_id=?", (payload["signal_id"],)).fetchone()
        if row is None:
            return False
        signal = json.loads(row[0])
        return (signal.get("source") == "FROZEN_RULE" and signal.get("state") == "REVIEW_READY"
                and signal.get("strategy_hash") == policy_hash
                and signal.get("scope_hash") == scope_hash
                and signal.get("economic_opportunity_id") == payload.get("event_id")
                and signal.get("contract_id") == payload.get("contract_id")
                and signal.get("observed_at") == payload.get("bar_end")
                and not signal.get("synthetic"))
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error):
        return False
