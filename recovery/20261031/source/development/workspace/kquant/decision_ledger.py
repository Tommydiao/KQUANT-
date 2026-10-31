from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .stock_store import connect


USER_DECISIONS = {"take", "skip", "wait", "observe"}
EXECUTION_STATES = {"not_executed", "manual_execution_reported", "not_recorded"}
ERROR_OWNERS = {
    "normal_strategy_loss",
    "data_issue",
    "strategy_issue",
    "user_chased_entry",
    "user_ignored_stop",
    "user_oversized",
    "user_sold_early",
    "user_violated_no_trade",
    "market_event",
    "unclassified",
}
JOURNAL_STAGES = {"pre_trade", "skipped", "entry", "exit", "review"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ledger_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    for field in ("data_snapshot_json", "system_decision_json", "entry_plan_json"):
        key = field.removesuffix("_json")
        try:
            payload[key] = json.loads(payload.pop(field))
        except (TypeError, json.JSONDecodeError):
            payload[key] = {}
    payload["read_only_research"] = True
    payload["no_order_submission"] = True
    return payload


def create_decision_ledger_entry(payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    signal_id = str(payload.get("signal_id") or "").strip()
    strategy_version = str(payload.get("strategy_version") or "legacy_unversioned").strip()
    user_decision = str(payload.get("user_decision") or "observe").strip().lower()
    execution = str(payload.get("final_execution") or "not_executed").strip().lower()
    error_owner = str(payload.get("error_owner") or "unclassified").strip().lower()
    if not symbol or not signal_id:
        raise ValueError("symbol and signal_id are required for a decision ledger entry.")
    if user_decision not in USER_DECISIONS:
        raise ValueError("Invalid user_decision.")
    if execution not in EXECUTION_STATES:
        raise ValueError("Invalid final_execution state.")
    if error_owner not in ERROR_OWNERS:
        raise ValueError("Invalid error_owner.")
    now = _now()
    ledger_id = str(payload.get("ledger_id") or _stable_id("ledger", signal_id, symbol, now))
    row_values = {
        "ledger_id": ledger_id,
        "signal_id": signal_id[:160],
        "symbol": symbol[:24],
        "strategy_version": strategy_version[:120],
        "data_snapshot_json": json.dumps(dict(payload.get("data_snapshot") or {}), ensure_ascii=True),
        "system_decision_json": json.dumps(dict(payload.get("system_decision") or {}), ensure_ascii=True),
        "user_decision": user_decision,
        "entry_plan_json": json.dumps(dict(payload.get("entry_plan") or {}), ensure_ascii=True),
        "veto_status": str(payload.get("veto_status") or "unknown")[:120],
        "final_execution": execution,
        "outcome": str(payload.get("outcome") or "pending")[:500],
        "outcome_r": _number(payload.get("outcome_r")),
        "error_owner": error_owner,
        "lesson": str(payload.get("lesson") or "")[:4000],
        "created_at": now,
        "updated_at": now,
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO decision_ledger(
              ledger_id, signal_id, symbol, strategy_version, data_snapshot_json,
              system_decision_json, user_decision, entry_plan_json, veto_status,
              final_execution, outcome, outcome_r, error_owner, lesson, created_at, updated_at
            ) VALUES (
              :ledger_id, :signal_id, :symbol, :strategy_version, :data_snapshot_json,
              :system_decision_json, :user_decision, :entry_plan_json, :veto_status,
              :final_execution, :outcome, :outcome_r, :error_owner, :lesson, :created_at, :updated_at
            )
            """,
            row_values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM decision_ledger WHERE ledger_id = ?", (ledger_id,)).fetchone()
    return _ledger_row(row)


def list_decision_ledger(db_path: Path, *, symbol: str | None = None, limit: int = 100) -> dict[str, Any]:
    count = max(1, min(int(limit), 500))
    with connect(db_path) as conn:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM decision_ledger WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
                (symbol.strip().upper(), count),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM decision_ledger ORDER BY created_at DESC LIMIT ?", (count,)).fetchall()
    entries = [_ledger_row(row) for row in rows]
    return {"entries": entries, "count": len(entries), "read_only_research": True, "no_order_submission": True}


def record_manual_trade_journal(payload: dict[str, Any], db_path: Path) -> dict[str, Any]:
    ledger_id = str(payload.get("ledger_id") or "").strip()
    symbol = str(payload.get("symbol") or "").strip().upper()
    stage = str(payload.get("stage") or "pre_trade").strip().lower()
    if not ledger_id or not symbol:
        raise ValueError("ledger_id and symbol are required for a trade journal record.")
    if stage not in JOURNAL_STAGES:
        raise ValueError("Invalid trade journal stage.")
    values = {
        "ledger_id": ledger_id,
        "symbol": symbol[:24],
        "stage": stage,
        "reason": str(payload.get("reason") or "")[:2000],
        "plan_followed": None if payload.get("plan_followed") is None else int(bool(payload.get("plan_followed"))),
        "actual_entry": _number(payload.get("actual_entry")),
        "actual_exit": _number(payload.get("actual_exit")),
        "result_r": _number(payload.get("result_r")),
        "emotion": str(payload.get("emotion") or "")[:500],
        "screenshot_ref": str(payload.get("screenshot_ref") or "")[:1000],
        "notes": str(payload.get("notes") or "")[:4000],
        "review": str(payload.get("review") or "")[:4000],
        "created_at": _now(),
    }
    with connect(db_path) as conn:
        ledger = conn.execute("SELECT ledger_id FROM decision_ledger WHERE ledger_id = ?", (ledger_id,)).fetchone()
        if not ledger:
            raise ValueError("Unknown ledger_id.")
        cursor = conn.execute(
            """
            INSERT INTO manual_trade_journal(
              ledger_id, symbol, stage, reason, plan_followed, actual_entry, actual_exit,
              result_r, emotion, screenshot_ref, notes, review, created_at
            ) VALUES (
              :ledger_id, :symbol, :stage, :reason, :plan_followed, :actual_entry, :actual_exit,
              :result_r, :emotion, :screenshot_ref, :notes, :review, :created_at
            )
            """,
            values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM manual_trade_journal WHERE id = ?", (cursor.lastrowid,)).fetchone()
    result = dict(row)
    result["plan_followed"] = None if result["plan_followed"] is None else bool(result["plan_followed"])
    result["read_only_research"] = True
    result["no_order_submission"] = True
    return result


def classify_error_owner(value: str | None) -> dict[str, str]:
    normalized = str(value or "unclassified").strip().lower()
    if normalized not in ERROR_OWNERS:
        normalized = "unclassified"
    labels = {
        "normal_strategy_loss": "Normal strategy loss",
        "data_issue": "Data issue",
        "strategy_issue": "Strategy issue",
        "user_chased_entry": "User chased entry",
        "user_ignored_stop": "User ignored stop",
        "user_oversized": "User oversized",
        "user_sold_early": "User sold early",
        "user_violated_no_trade": "User violated NO TRADE",
        "market_event": "Random market event",
        "unclassified": "Unclassified",
    }
    owner = "user" if normalized.startswith("user_") else "system" if normalized in {"data_issue", "strategy_issue"} else "market"
    return {"code": normalized, "label": labels[normalized], "owner": owner}


def weekly_personal_review(db_path: Path, *, week_start: str | None = None) -> dict[str, Any]:
    try:
        start = date.fromisoformat(week_start) if week_start else (datetime.now(UTC).date() - timedelta(days=datetime.now(UTC).weekday()))
    except ValueError as exc:
        raise ValueError("week_start must use YYYY-MM-DD.") from exc
    end = start + timedelta(days=7)
    with connect(db_path) as conn:
        ledger_rows = conn.execute(
            "SELECT * FROM decision_ledger WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        journal_rows = conn.execute(
            "SELECT * FROM manual_trade_journal WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    ledgers = [_ledger_row(row) for row in ledger_rows]
    journal = [dict(row) for row in journal_rows]
    outcomes = [float(entry["outcome_r"]) for entry in ledgers if entry.get("outcome_r") is not None]
    wins = [value for value in outcomes if value > 0]
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in outcomes:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    owners = Counter(entry["error_owner"] for entry in ledgers if entry["error_owner"] != "unclassified")
    violations = sum(1 for entry in ledgers if entry["error_owner"].startswith("user_"))
    blocked = sum(1 for entry in ledgers if str(entry.get("veto_status")).lower() in {"blocked", "active", "vetoed"})
    leading_error = owners.most_common(1)[0][0] if owners else "none_recorded"
    return {
        "week_start": start.isoformat(),
        "week_end_exclusive": end.isoformat(),
        "signal_count": len(ledgers),
        "manual_execution_reported_count": sum(1 for entry in ledgers if entry["final_execution"] == "manual_execution_reported"),
        "win_rate_pct": round(len(wins) / len(outcomes) * 100, 4) if outcomes else 0.0,
        "average_r": round(sum(outcomes) / len(outcomes), 4) if outcomes else 0.0,
        "max_drawdown_r": round(max_drawdown, 4),
        "system_blocked_count": blocked,
        "user_violation_count": violations,
        "most_common_error": classify_error_owner(leading_error),
        "next_week_one_improvement": (
            "Record a complete pre-trade plan before any manual action."
            if leading_error == "none_recorded"
            else f"Address {classify_error_owner(leading_error)['label'].lower()} before adding new discretionary complexity."
        ),
        "journal_record_count": len(journal),
        "read_only_research": True,
        "no_order_submission": True,
    }
