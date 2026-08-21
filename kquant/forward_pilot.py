from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .stock_store import connect
from .stock_quant_validation import latest_stock_quant_validation
from .strategy_freeze import strategy_freeze_status


FORWARD_MODES = {"paper_observation", "paper_simulation"}
FORWARD_STATUSES = {"prepared", "active", "closed"}
OUTCOME_STATUSES = {"pending", "not_triggered", "triggered", "stopped", "target", "time_exit", "invalidated", "skipped"}
MINIMUM_COMPLETE_MARKET_DAYS = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _loads(value: Any) -> dict[str, Any]:
    try:
        return dict(json.loads(str(value or "{}")))
    except (TypeError, json.JSONDecodeError):
        return {}


def _session_row(db_path: Path, session_id: str) -> Any:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM forward_pilot_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if not row:
        raise ValueError("Unknown forward pilot session.")
    return row


def _session_payload(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["rules"] = _loads(item.pop("rules_json"))
    item["read_only_research"] = True
    item["no_broker_or_order_api"] = True
    return item


def shadow_start_readiness(db_path: Path, strategy_version: str) -> dict[str, Any]:
    """Fail closed unless the freeze is linked to a passing Stock Quant run."""

    freeze = strategy_freeze_status(db_path, strategy_version)
    if not freeze or freeze.get("status") != "frozen":
        return {
            "allowed": False,
            "code": "strategy_not_frozen",
            "reason": "Freeze and review the strategy manifest before opening forward observation.",
            "freeze": freeze,
        }
    validation_payload = latest_stock_quant_validation(db_path)
    validation = dict(validation_payload.get("run") or validation_payload)
    summary = dict(validation.get("summary") or {})
    checks = dict(summary.get("overall_gate_checks") or {})
    eligible = bool(
        validation.get("gate_status") == "pass"
        and validation.get("dataset_integrity_status") == "verified"
        and validation.get("current_contract_compatible") is True
        and summary.get("deployment_status") == "eligible"
        and summary.get("deployment_model")
        and checks
        and all(bool(value) for value in checks.values())
        and not list(summary.get("deployment_blockers") or [])
    )
    if not eligible:
        return {
            "allowed": False,
            "code": "stock_quant_validation_not_passed",
            "reason": "A passing, immutable Stock Quant Phase 5 validation is required before Shadow Observation.",
            "freeze": freeze,
            "validation_run_id": validation.get("run_id"),
            "deployment_blockers": list(summary.get("deployment_blockers") or []),
        }
    if str(freeze.get("validation_fingerprint") or "") != str(validation.get("content_hash") or ""):
        return {
            "allowed": False,
            "code": "freeze_validation_mismatch",
            "reason": "The frozen strategy manifest is not linked to the current eligible Stock Quant validation run.",
            "freeze": freeze,
            "validation_run_id": validation.get("run_id"),
        }
    return {
        "allowed": True,
        "code": "ready",
        "reason": "The frozen strategy is linked to an eligible Stock Quant validation run.",
        "freeze": freeze,
        "validation_run_id": validation.get("run_id"),
        "deployment_model": summary.get("deployment_model"),
    }


def prepare_forward_pilot(
    *,
    db_path: Path,
    strategy_version: str,
    universe_name: str,
    universe_snapshot_hash: str,
    start_date: str,
    mode: str = "paper_observation",
) -> dict[str, Any]:
    """Open a forward-observation session only from a frozen strategy manifest."""

    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in FORWARD_MODES:
        raise ValueError("Unsupported forward pilot mode.")
    if not universe_snapshot_hash:
        raise ValueError("A frozen universe snapshot hash is required.")
    start_gate = shadow_start_readiness(db_path, strategy_version)
    if not start_gate["allowed"]:
        return {
            "status": "blocked",
            "reason": start_gate["reason"],
            "strategy_version": strategy_version,
            "shadow_start": start_gate,
            "read_only_research": True,
        }
    freeze = dict(start_gate["freeze"] or {})
    session_id = _stable_id("forward", strategy_version, universe_name, universe_snapshot_hash, start_date, normalized_mode)
    rules = {
        "strategy_changes_allowed": False,
        "universe_changes_allowed": False,
        "real_money_allowed": False,
        "manual_observation_required": True,
        "minimum_complete_market_days_for_go_no_go": MINIMUM_COMPLETE_MARKET_DAYS,
    }
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO forward_pilot_sessions(
              session_id, strategy_version, strategy_config_hash, universe_name,
              universe_snapshot_hash, validation_fingerprint, mode, status,
              start_date, end_date, rules_json, created_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id, strategy_version, freeze["strategy_config_hash"], universe_name,
                universe_snapshot_hash, freeze["validation_fingerprint"], normalized_mode,
                "prepared", start_date, None, json.dumps(rules, ensure_ascii=True), now, None,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM forward_pilot_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return {"status": "prepared", "session": _session_payload(row), "freeze": freeze, "read_only_research": True}


def activate_forward_pilot(db_path: Path, session_id: str) -> dict[str, Any]:
    session = _session_row(db_path, session_id)
    if session["status"] == "closed":
        raise ValueError("A closed forward pilot cannot be reactivated.")
    start_gate = shadow_start_readiness(db_path, str(session["strategy_version"]))
    if not start_gate["allowed"]:
        return {
            "status": "blocked",
            "reason": start_gate["reason"],
            "session": _session_payload(session),
            "shadow_start": start_gate,
            "read_only_research": True,
        }
    with connect(db_path) as conn:
        conn.execute("UPDATE forward_pilot_sessions SET status = 'active' WHERE session_id = ?", (session_id,))
        conn.commit()
    return {"status": "active", "session": _session_payload(_session_row(db_path, session_id)), "read_only_research": True}


def record_forward_day(
    *,
    db_path: Path,
    session_id: str,
    market_date: str,
    preflight: dict[str, Any],
    scan: dict[str, Any],
    phase: str = "daily_observation",
) -> dict[str, Any]:
    """Save the exact daily candidate queue before outcomes are known."""

    session = _session_row(db_path, session_id)
    if session["status"] != "active":
        raise ValueError("Forward pilot must be active before recording a market day.")
    candidates = list((scan.get("daily_candidates") or {}).get("buy_setups") or []) + list((scan.get("daily_candidates") or {}).get("watch") or [])
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO forward_pilot_days(session_id, market_date, phase, preflight_json, scan_json, close_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, market_date) DO UPDATE SET
              phase=excluded.phase, preflight_json=excluded.preflight_json, scan_json=excluded.scan_json, updated_at=excluded.updated_at
            """,
            (session_id, market_date, phase[:80], json.dumps(preflight, ensure_ascii=True), json.dumps(scan, ensure_ascii=True), "{}", now, now),
        )
        for item in candidates:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            signal_id = f"{scan.get('run_id') or market_date}:{symbol}"
            candidate_id = _stable_id("candidate", session_id, market_date, signal_id)
            plan = dict(item.get("plan") or item.get("entry_plan") or {})
            conn.execute(
                """
                INSERT OR REPLACE INTO forward_pilot_candidates(
                  candidate_id, session_id, market_date, signal_id, symbol, rank, level,
                  data_status, veto_status, plan_json, snapshot_json, trigger_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id, session_id, market_date, signal_id, symbol, int(item.get("rank") or 0),
                    str(item.get("bucket") or item.get("level") or "WATCH"), str(item.get("data_status") or "unknown"),
                    str(item.get("veto_status") or "unknown"), json.dumps(plan, ensure_ascii=True),
                    json.dumps(item, ensure_ascii=True), "pending", now,
                ),
            )
        conn.commit()
    return forward_pilot_summary(db_path, session_id)


def close_forward_day(
    *,
    db_path: Path,
    session_id: str,
    market_date: str,
    close_notes: dict[str, Any],
) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT session_id FROM forward_pilot_days WHERE session_id = ? AND market_date = ?", (session_id, market_date)).fetchone()
        if not row:
            raise ValueError("No forward pilot day exists for that market date.")
        conn.execute(
            "UPDATE forward_pilot_days SET close_json = ?, updated_at = ? WHERE session_id = ? AND market_date = ?",
            (json.dumps(close_notes, ensure_ascii=True), _now(), session_id, market_date),
        )
        conn.commit()
    return forward_pilot_summary(db_path, session_id)


def record_forward_outcome(
    *,
    db_path: Path,
    candidate_id: str,
    outcome_status: str,
    entry_price: float | None = None,
    exit_price: float | None = None,
    realized_r: float | None = None,
    notes: str = "",
    deviations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = str(outcome_status).strip().lower()
    if status not in OUTCOME_STATUSES:
        raise ValueError("Unsupported forward outcome status.")
    with connect(db_path) as conn:
        candidate = conn.execute("SELECT candidate_id FROM forward_pilot_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not candidate:
            raise ValueError("Unknown forward candidate.")
        now = _now()
        triggered_at = now if status in {"triggered", "stopped", "target", "time_exit"} else None
        completed_at = now if status in {"stopped", "target", "time_exit", "invalidated", "not_triggered", "skipped"} else None
        conn.execute(
            """
            INSERT INTO forward_pilot_outcomes(
              candidate_id, outcome_status, triggered_at, completed_at, entry_price,
              exit_price, realized_r, deviation_json, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(candidate_id) DO UPDATE SET
              outcome_status=excluded.outcome_status, triggered_at=excluded.triggered_at,
              completed_at=excluded.completed_at, entry_price=excluded.entry_price,
              exit_price=excluded.exit_price, realized_r=excluded.realized_r,
              deviation_json=excluded.deviation_json, notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (
                candidate_id, status, triggered_at, completed_at, entry_price, exit_price,
                realized_r, json.dumps(deviations or {}, ensure_ascii=True), notes[:4000], now,
            ),
        )
        conn.execute("UPDATE forward_pilot_candidates SET trigger_status = ? WHERE candidate_id = ?", (status, candidate_id))
        conn.commit()
        row = conn.execute("SELECT * FROM forward_pilot_outcomes WHERE candidate_id = ?", (candidate_id,)).fetchone()
    result = dict(row)
    result["deviations"] = _loads(result.pop("deviation_json"))
    result["read_only_research"] = True
    return result


def forward_pilot_summary(db_path: Path, session_id: str) -> dict[str, Any]:
    session = _session_payload(_session_row(db_path, session_id))
    with connect(db_path) as conn:
        days = [dict(row) for row in conn.execute("SELECT * FROM forward_pilot_days WHERE session_id = ? ORDER BY market_date", (session_id,)).fetchall()]
        candidates = [dict(row) for row in conn.execute("SELECT * FROM forward_pilot_candidates WHERE session_id = ? ORDER BY market_date, rank", (session_id,)).fetchall()]
        outcomes = [dict(row) for row in conn.execute("SELECT * FROM forward_pilot_outcomes WHERE candidate_id IN (SELECT candidate_id FROM forward_pilot_candidates WHERE session_id = ?)", (session_id,)).fetchall()]
    outcome_by_id = {str(row["candidate_id"]): row for row in outcomes}
    completed = [row for row in outcomes if row["outcome_status"] in {"stopped", "target", "time_exit", "invalidated", "not_triggered", "skipped"}]
    r_values = [_number(row.get("realized_r")) for row in completed if row.get("realized_r") is not None]
    data_incidents = sum(1 for day in days if str(_loads(day["preflight_json"]).get("status") or "").lower() not in {"pass", "ready", "healthy"})
    return {
        "session": session,
        "market_day_count": len(days),
        "candidate_count": len(candidates),
        "outcome_counts": dict(Counter(str(row["outcome_status"]) for row in outcomes)),
        "completed_outcome_count": len(completed),
        "average_r": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
        "data_incident_count": data_incidents,
        "minimum_market_days_met": len(days) >= MINIMUM_COMPLETE_MARKET_DAYS,
        "candidate_traceability_complete": all(candidate["candidate_id"] in outcome_by_id or candidate["trigger_status"] == "pending" for candidate in candidates),
        "strategy_changes_allowed": False,
        "real_money_allowed": False,
        "read_only_research": True,
    }


def initialize_paper_simulation(
    *,
    db_path: Path,
    session_id: str,
    initial_cash: float,
    risk_per_trade_pct: float = 0.25,
    max_positions: int = 3,
    max_daily_risk_pct: float = 0.75,
) -> dict[str, Any]:
    """Create an explicitly simulated cash account, never a broker account."""

    session = _session_row(db_path, session_id)
    if session["status"] != "active":
        raise ValueError("Forward pilot must be active before initializing paper simulation.")
    if _number(initial_cash) <= 0 or not 0 < _number(risk_per_trade_pct) <= 0.25:
        raise ValueError("Paper risk per trade must be greater than 0 and no more than 0.25%.")
    if not 1 <= int(max_positions) <= 10 or not 0 < _number(max_daily_risk_pct) <= 2:
        raise ValueError("Invalid paper portfolio limits.")
    account_id = _stable_id("paper", session_id)
    now = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_simulation_accounts(
              account_id, session_id, initial_cash, cash, risk_per_trade_pct,
              max_positions, max_daily_risk_pct, no_averaging, no_chasing,
              status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (account_id, session_id, initial_cash, initial_cash, risk_per_trade_pct, max_positions,
             max_daily_risk_pct, 1, 1, "active", now, now),
        )
        conn.commit()
    return paper_simulation_summary(db_path, account_id)


def _paper_account(db_path: Path, account_id: str) -> Any:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM paper_simulation_accounts WHERE account_id = ?", (account_id,)).fetchone()
    if not row:
        raise ValueError("Unknown paper simulation account.")
    return row


def enter_paper_position(
    *,
    db_path: Path,
    account_id: str,
    candidate_id: str,
    entry_time: str,
    entry_price: float,
    stop_price: float,
    target_price: float,
    entry_plan_high: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Record a human-declared simulated fill with strict risk/no-chase checks."""

    account = _paper_account(db_path, account_id)
    entry = _number(entry_price)
    stop = _number(stop_price)
    target = _number(target_price)
    if entry <= 0 or stop <= 0 or stop >= entry or target <= entry:
        raise ValueError("Paper entry requires positive entry, lower stop, and higher target.")
    with connect(db_path) as conn:
        candidate = conn.execute("SELECT * FROM forward_pilot_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not candidate:
            raise ValueError("Paper entry must reference a recorded forward candidate.")
        open_positions = conn.execute("SELECT * FROM paper_simulation_positions WHERE account_id = ? AND status = 'open'", (account_id,)).fetchall()
        if len(open_positions) >= int(account["max_positions"]):
            raise ValueError("Paper max simultaneous positions reached.")
        if any(str(row["symbol"]) == str(candidate["symbol"]) for row in open_positions):
            raise ValueError("Paper no-averaging rule blocks a second open position in the same symbol.")
        plan_high = _number(entry_plan_high) if entry_plan_high is not None else _number(_loads(candidate["plan_json"]).get("entry_high"))
        if int(account["no_chasing"]) and plan_high > 0 and entry > plan_high:
            raise ValueError("Paper no-chasing rule blocks an entry above the planned entry zone.")
        risk_per_share = entry - stop
        risk_budget = _number(account["initial_cash"]) * _number(account["risk_per_trade_pct"]) / 100
        daily_open_risk = sum(_number(row["shares"]) * (_number(row["entry_price"]) - _number(row["stop_price"])) for row in open_positions if str(row["entry_time"])[:10] == entry_time[:10])
        daily_cap = _number(account["initial_cash"]) * _number(account["max_daily_risk_pct"]) / 100
        shares = math.floor(min(risk_budget / risk_per_share, _number(account["cash"]) / entry, max(0.0, daily_cap - daily_open_risk) / risk_per_share))
        if shares <= 0:
            raise ValueError("Paper cash or daily risk limit blocks this entry.")
        position_id = _stable_id("paper-position", account_id, candidate_id, entry_time)
        now = _now()
        cash = _number(account["cash"]) - shares * entry
        conn.execute(
            """
            INSERT INTO paper_simulation_positions(
              position_id, account_id, candidate_id, symbol, entry_time, entry_price,
              shares, stop_price, target_price, entry_plan_high, status, exit_time,
              exit_price, realized_r, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (position_id, account_id, candidate_id, candidate["symbol"], entry_time, entry, shares,
             stop, target, plan_high or None, "open", None, None, None, notes[:4000], now, now),
        )
        conn.execute("UPDATE paper_simulation_accounts SET cash = ?, updated_at = ? WHERE account_id = ?", (cash, now, account_id))
        conn.commit()
    return paper_simulation_summary(db_path, account_id)


def exit_paper_position(
    *,
    db_path: Path,
    account_id: str,
    position_id: str,
    exit_time: str,
    exit_price: float,
    notes: str = "",
) -> dict[str, Any]:
    account = _paper_account(db_path, account_id)
    price = _number(exit_price)
    if price <= 0:
        raise ValueError("Paper exit price must be positive.")
    with connect(db_path) as conn:
        position = conn.execute("SELECT * FROM paper_simulation_positions WHERE position_id = ? AND account_id = ?", (position_id, account_id)).fetchone()
        if not position or position["status"] != "open":
            raise ValueError("Unknown or closed paper position.")
        risk = (_number(position["entry_price"]) - _number(position["stop_price"])) * int(position["shares"])
        realized_r = (price - _number(position["entry_price"])) * int(position["shares"]) / max(risk, 0.0001)
        now = _now()
        cash = _number(account["cash"]) + price * int(position["shares"])
        conn.execute(
            "UPDATE paper_simulation_positions SET status = 'closed', exit_time = ?, exit_price = ?, realized_r = ?, notes = ?, updated_at = ? WHERE position_id = ?",
            (exit_time, price, realized_r, notes[:4000], now, position_id),
        )
        conn.execute("UPDATE paper_simulation_accounts SET cash = ?, updated_at = ? WHERE account_id = ?", (cash, now, account_id))
        conn.commit()
    return paper_simulation_summary(db_path, account_id)


def paper_simulation_summary(db_path: Path, account_id: str) -> dict[str, Any]:
    account = dict(_paper_account(db_path, account_id))
    with connect(db_path) as conn:
        positions = [dict(row) for row in conn.execute("SELECT * FROM paper_simulation_positions WHERE account_id = ? ORDER BY entry_time", (account_id,)).fetchall()]
    closed = [row for row in positions if row["status"] == "closed"]
    r_values = [_number(row["realized_r"]) for row in closed if row["realized_r"] is not None]
    cumulative, peak, max_drawdown = 0.0, 0.0, 0.0
    for value in r_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    return {
        "account": {key: value for key, value in account.items() if key not in {"created_at", "updated_at"}},
        "positions": positions,
        "open_position_count": sum(1 for row in positions if row["status"] == "open"),
        "closed_position_count": len(closed),
        "average_r": round(sum(r_values) / len(r_values), 4) if r_values else 0.0,
        "max_drawdown_r": round(max_drawdown, 4),
        "simulated_only": True,
        "no_broker_or_order_api": True,
        "no_leverage": True,
    }
