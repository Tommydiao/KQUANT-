"""Independent one-minute research rules and append-only evidence storage."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from . import __file__ as _package_file

from .options_data_paths import connect_store, resolve_stores

ROOT = Path(_package_file).resolve().parents[1]
CONFIG = ROOT / "config/options_one_minute_momentum_v1.json"
EVENT_PROPOSAL = ROOT / "config/options_one_minute_event_coverage_v1.json"
EVENT_APPROVAL = ROOT / "config/review_acceptances/options_one_minute_event_o_setup_v1.json"
STRATEGY_APPROVAL = ROOT / "config/review_acceptances/options_one_minute_strategy_o_setup_v1.json"
STORE = resolve_stores(ROOT)["minute"]
EXPIRY_AUDIT_DIR = ROOT / "outputs/one-minute-shadow"
NY = ZoneInfo("America/New_York")

SCHEMA = """
CREATE TABLE IF NOT EXISTS one_minute_history (
 symbol TEXT NOT NULL, session TEXT NOT NULL, slot TEXT NOT NULL,
 payload_json TEXT NOT NULL, PRIMARY KEY(symbol,session,slot)
);
CREATE TABLE IF NOT EXISTS one_minute_history_pages (
 symbol TEXT NOT NULL, session TEXT NOT NULL, state TEXT NOT NULL,
 requested_at TEXT NOT NULL, received_at TEXT, row_count INTEGER NOT NULL,
 reason TEXT, PRIMARY KEY(symbol,session)
);
CREATE TABLE IF NOT EXISTS one_minute_prewarm (
 session TEXT NOT NULL, symbol TEXT NOT NULL, state TEXT NOT NULL,
 reason TEXT, checked_at TEXT, payload_json TEXT NOT NULL,
 PRIMARY KEY(session,symbol)
);
CREATE TABLE IF NOT EXISTS one_minute_bars (
 evidence_id TEXT PRIMARY KEY, session TEXT NOT NULL, symbol TEXT NOT NULL,
 open_at TEXT NOT NULL, received_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS one_minute_bars_lookup ON one_minute_bars(session,symbol,open_at,received_at);
CREATE TABLE IF NOT EXISTS one_minute_evaluations (
 evaluation_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, session TEXT NOT NULL,
 symbol TEXT NOT NULL, right_name TEXT NOT NULL, bar_end TEXT NOT NULL,
 state TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS one_minute_evaluations_lookup ON one_minute_evaluations(session,symbol,right_name,created_at);
CREATE INDEX IF NOT EXISTS one_minute_status_metadata ON one_minute_evaluations(session,symbol,right_name,created_at,bar_end,state);
CREATE TABLE IF NOT EXISTS one_minute_candidates (
 event_id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL,
 session TEXT NOT NULL, published_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS one_minute_manual_positions (
 position_id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, symbol TEXT NOT NULL,
 right_name TEXT NOT NULL, contract_id TEXT NOT NULL, opened_at TEXT NOT NULL,
 open_quantity INTEGER NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS one_minute_manual_events (
 event_id TEXT PRIMARY KEY, position_id TEXT NOT NULL, operation_key TEXT NOT NULL UNIQUE,
 event_type TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS one_minute_exit_alerts (
 alert_id TEXT PRIMARY KEY, position_id TEXT NOT NULL, reason TEXT NOT NULL,
 created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
"""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def finite(value: Any) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def load_policy(path: Path = CONFIG) -> dict:
    policy = json.loads(path.read_text(encoding="utf-8"))
    event = json.loads(EVENT_PROPOSAL.read_text(encoding="utf-8"))
    if any(policy[key] for key in ("paper_enabled", "automatic_paper_enabled", "real_orders_enabled", "llm_required", "cbrm_consumed")):
        raise ValueError("ONE_MINUTE_RESEARCH_CANNOT_ENABLE_EXECUTION")
    if (policy["status"] != "RESEARCH_ONLY_PENDING_O_SETUP" or policy["bar_minutes"] != 1
            or policy["price_adjustment"] != "NoAdjust"
            or policy["event_policy_id"] != event["policy_id"]):
        raise ValueError("ONE_MINUTE_POLICY_IDENTITY_CHANGED")
    policy["policy_hash"] = digest(policy)
    return policy


def approval_status(policy: dict, scope_hash: str | None) -> dict:
    """Report exact owner bindings; a plan request alone never enables signal delivery."""
    strategy_file_hash = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    event_file_hash = hashlib.sha256(EVENT_PROPOSAL.read_bytes()).hexdigest()
    result = {}
    for name, path, file_hash, policy_id in (
        ("strategy", STRATEGY_APPROVAL, strategy_file_hash, policy["policy_id"]),
        ("event", EVENT_APPROVAL, event_file_hash, "EVENT-COVERAGE-ONE-MINUTE-SAME-DAY-V1"),
    ):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            accepted = (scope_hash is not None and row.get("status") == "APPROVED"
                        and row.get("approved_by") == "OWNER" and row.get("gate") == "O-SETUP"
                        and row.get("policy_id") == policy_id and row.get("policy_sha256") == file_hash
                        and row.get("strategy_hash") == policy["policy_hash"]
                        and row.get("scope_hash") == scope_hash)
        except (OSError, ValueError, TypeError):
            accepted = False
        result[name] = {"exact_binding_accepted": bool(accepted), "policy_id": policy_id,
                        "proposal_sha256": file_hash}
    result["qualified_signal_pipeline_enabled"] = all(
        result[name]["exact_binding_accepted"] for name in ("strategy", "event"))
    result["scope_hash"] = scope_hash
    return result


def initialize(path: Path = STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_store(path)) as connection:
        if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
            raise RuntimeError("MINUTE_WAL_UNAVAILABLE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(SCHEMA)


def session_times(schedule: dict, policy: dict) -> dict:
    opening = timestamp(schedule["regular_open_utc"])
    closing = timestamp(schedule["regular_close_utc"])
    if closing <= opening:
        raise ValueError("INVALID_MARKET_SESSION")
    return {"open": opening, "close": closing,
            "entry_cutoff": closing - timedelta(minutes=policy["entry_cutoff_minutes_before_close"]),
            "exit_reminder": closing - timedelta(minutes=policy["exit_reminder_minutes_before_close"]),
            "planned_exit": closing - timedelta(minutes=policy["planned_exit_minutes_before_close"])}


def _usable_history_sample(row: Any, *, now: datetime, adjustment: str) -> bool:
    if not isinstance(row, dict) or not finite(row.get("turnover")) or not finite(row.get("range")):
        return False
    if row["turnover"] < 0 or row["range"] < 0 or row.get("adjustment") != adjustment:
        return False
    if not row.get("source_hash") or not row.get("received_at"):
        return False
    try:
        return timestamp(row["received_at"]) <= now
    except (ValueError, TypeError):
        return False


def evaluate(*, symbol: str, right: str, bar: dict, previous: list[dict],
             history: dict, schedule: dict, scope_hash: str, now: datetime,
             event: dict | None = None, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    if right not in policy["rights"]:
        raise ValueError("INVALID_RIGHT")
    current = timestamp(now)
    times = session_times(schedule, policy)
    session = times["open"].astimezone(NY).date().isoformat()
    start = timestamp(bar["open_at"])
    end = start + timedelta(minutes=1)
    deadline = min(end + timedelta(seconds=policy["signal_deadline_seconds"]), times["entry_cutoff"])
    direction = 1 if right == "CALL" else -1
    reasons: list[str] = []
    factors: dict[str, Any] = {}
    if not schedule.get("is_trading_day") or not times["open"] <= start < times["close"]:
        reasons.append("OUTSIDE_REGULAR_SESSION")
    if (start - times["open"]).total_seconds() % 60 or start.second or start.microsecond:
        reasons.append("MISALIGNED_MINUTE")
    if bar.get("symbol") != symbol or bar.get("interval") != "1m":
        reasons.append("BAR_IDENTITY_OR_PERIOD")
    try:
        received = timestamp(bar["received_at"])
        available = timestamp(bar["available_at"])
        if available != end or received < end or received > current or not bar.get("closed"):
            reasons.append("BAR_NOT_USABLE_AFTER_CLOSE")
    except (KeyError, TypeError, ValueError):
        reasons.append("BAR_TIME_MISSING")
    if not all(finite(bar.get(field)) for field in ("open", "high", "low", "close", "turnover")):
        reasons.append("BAR_PRICE_OR_TURNOVER_MISSING")
    else:
        o, h, l, c, amount = (bar[field] for field in ("open", "high", "low", "close", "turnover"))
        if not 0 < l <= min(o, c) <= max(o, c) <= h or amount < 0 or h == l:
            reasons.append("INVALID_OHLC_OR_RANGE")
    if bar.get("turnover_source") != "NATIVE" or bar.get("currency") != "USD":
        reasons.append("NATIVE_USD_TURNOVER_MISSING")
    if current >= times["entry_cutoff"] or end >= times["entry_cutoff"]:
        reasons.append("ENTRY_WINDOW_CLOSED")
    if current > deadline:
        reasons.append("SIGNAL_DEADLINE_EXCEEDED")
    if history.get("symbol") != symbol or history.get("session") != session:
        reasons.append("HISTORY_IDENTITY_MISMATCH")
    prior_sessions = history.get("prior_sessions") or []
    from .options_two_hour_data import sessions_before
    if prior_sessions != sessions_before(times["open"].astimezone(NY).date(), 20):
        reasons.append("EXACT_PRIOR_20_SESSIONS_REQUIRED")
    slot = start.astimezone(NY).strftime("%H:%M")
    samples = [history.get("slots", {}).get(day, {}).get(slot) for day in prior_sessions]
    baseline_amount = baseline_range = None
    if len(prior_sessions) == 20:
        if all(_usable_history_sample(row, now=current, adjustment=policy["price_adjustment"])
               for row in samples):
            baseline_amount = statistics.median(row["turnover"] for row in samples)
            baseline_range = statistics.median(row["range"] for row in samples)
        else:
            reasons.append("SAME_MINUTE_HISTORY_MISSING")
    if baseline_amount is not None and (baseline_amount <= 0 or baseline_range <= 0):
        reasons.append("ZERO_HISTORY_BASELINE")
    if start == times["open"]:
        if previous:
            reasons.append("FIRST_MINUTE_HAS_PRIOR_BARS")
    else:
        required = min(int((start - times["open"]).total_seconds() // 60), policy["prior_intraday_bars_max"])
        if len(previous) != required:
            reasons.append("CONTIGUOUS_PRIOR_MINUTES_MISSING")
        else:
            for index, old in enumerate(previous):
                try:
                    valid_time = timestamp(old["open_at"]) == start - timedelta(minutes=required - index)
                    closed_at = timestamp(old["available_at"])
                    received_at = timestamp(old["received_at"])
                except (KeyError, TypeError, ValueError):
                    valid_time = False
                    closed_at = received_at = current
                if (old.get("symbol") != symbol or old.get("interval") != "1m" or not old.get("closed")
                        or not valid_time or received_at < closed_at or received_at > current
                        or not all(finite(old.get(field)) for field in ("high", "low"))):
                    reasons.append("CONTIGUOUS_PRIOR_MINUTES_MISSING")
                    break
    structural_errors = {"OUTSIDE_REGULAR_SESSION", "MISALIGNED_MINUTE", "BAR_IDENTITY_OR_PERIOD",
                         "BAR_NOT_USABLE_AFTER_CLOSE", "BAR_TIME_MISSING", "BAR_PRICE_OR_TURNOVER_MISSING",
                         "INVALID_OHLC_OR_RANGE", "NATIVE_USD_TURNOVER_MISSING", "HISTORY_IDENTITY_MISMATCH",
                         "EXACT_PRIOR_20_SESSIONS_REQUIRED", "SAME_MINUTE_HISTORY_MISSING",
                         "ZERO_HISTORY_BASELINE", "FIRST_MINUTE_HAS_PRIOR_BARS",
                         "CONTIGUOUS_PRIOR_MINUTES_MISSING"}
    if not structural_errors.intersection(reasons):
        spread = bar["high"] - bar["low"]
        signed_body = direction * (bar["close"] - bar["open"]) / spread
        location = (bar["close"] - bar["low"]) / spread
        participation = bar["turnover"] / baseline_amount
        expansion = spread / baseline_range
        breakout = None if start == times["open"] else (
            bar["close"] - max(old["high"] for old in previous) if direction == 1
            else min(old["low"] for old in previous) - bar["close"])
        factors = {"signed_body": signed_body, "close_location": location,
                   "participation": participation, "expansion": expansion,
                   "breakout_distance": breakout, "opening_rule": start == times["open"],
                   "history_turnover_median": baseline_amount, "history_range_median": baseline_range,
                   "history_sessions": prior_sessions,
                   "history_source_hashes": [row.get("source_hash") for row in samples],
                   "history_adjustments": sorted({row.get("adjustment") for row in samples if row.get("adjustment")})}
        if signed_body < policy["momentum_body_min"]:
            reasons.append("MOMENTUM_BELOW_THRESHOLD")
        if direction * (location - .5) < policy["close_location_min"] - .5:
            reasons.append("CLOSE_LOCATION_BELOW_THRESHOLD")
        if participation < policy["participation_min"]:
            reasons.append("PARTICIPATION_BELOW_THRESHOLD")
        if not policy["expansion_min"] <= expansion <= policy["expansion_max"]:
            reasons.append("EXPANSION_OUTSIDE_RANGE")
        if breakout is not None and breakout <= 0:
            reasons.append("LOCAL_BREAKOUT_NOT_CONFIRMED")
    if factors and not reasons and not (event or {}).get("trade_eligible"):
        reasons.append("EVENT_COVERAGE_PENDING")
    state = ("ENTRY_WINDOW_CLOSED" if "ENTRY_WINDOW_CLOSED" in reasons else
             "MISSED" if "SIGNAL_DEADLINE_EXCEEDED" in reasons else
             "NUMERIC_PASS_EVENT_PENDING" if reasons == ["EVENT_COVERAGE_PENDING"] else
             "NUMERIC_PASS" if not reasons else "INCOMPLETE" if any(reason in reasons for reason in (
                 "SAME_MINUTE_HISTORY_MISSING", "EXACT_PRIOR_20_SESSIONS_REQUIRED", "BAR_NOT_USABLE_AFTER_CLOSE",
                 "CONTIGUOUS_PRIOR_MINUTES_MISSING", "BAR_PRICE_OR_TURNOVER_MISSING", "ZERO_HISTORY_BASELINE",
                 "INVALID_OHLC_OR_RANGE", "BAR_TIME_MISSING", "NATIVE_USD_TURNOVER_MISSING"))
             else "NO_TRIGGER")
    event_id = digest([policy["policy_hash"], scope_hash, session, symbol, right])
    result = {"policy_id": policy["policy_id"], "policy_hash": policy["policy_hash"],
              "scope_hash": scope_hash, "session": session, "symbol": symbol, "right": right,
              "event_id": event_id, "bar_end": end.isoformat(), "deadline_at": deadline.isoformat(),
              "evaluated_at": current.isoformat(), "state": state, "reasons": reasons,
              "factor_evidence": factors, "bar_evidence": bar,
              "event_coverage": event or {"status": "NOT_EVALUATED"},
              "paper_enabled": False, "real_orders_enabled": False}
    result["evaluation_id"] = digest([event_id, end.isoformat(), current.isoformat(), state, reasons])
    return result


def save_bar(bar: dict, session: str, path: Path = STORE) -> None:
    save_bars([bar], session, path)


def missed_evaluation(*, symbol, right, bar, scope_hash, now, deadline, policy=None):
    """Archive an expired task without asserting anything about unexamined inputs."""
    policy = policy or load_policy()
    current = timestamp(now)
    if current <= timestamp(deadline):
        raise ValueError("TASK_NOT_EXPIRED")
    opened = timestamp(bar["open_at"])
    session = opened.astimezone(NY).date().isoformat()
    end = opened + timedelta(minutes=1)
    event_id = digest([policy["policy_hash"], scope_hash, session, symbol, right])
    reasons = ["SIGNAL_DEADLINE_EXCEEDED"]
    result = {"policy_id": policy["policy_id"], "policy_hash": policy["policy_hash"],
              "scope_hash": scope_hash, "session": session, "symbol": symbol, "right": right,
              "event_id": event_id, "bar_end": end.isoformat(), "deadline_at": timestamp(deadline).isoformat(),
              "evaluated_at": current.isoformat(), "state": "MISSED", "reasons": reasons,
              "factor_evidence": {}, "bar_evidence": bar,
              "not_evaluated_stages": ["history", "mathematics", "events", "contract"],
              "event_coverage": {"status": "NOT_EVALUATED_AFTER_DEADLINE", "trade_eligible": False},
              "paper_enabled": False, "real_orders_enabled": False}
    result["evaluation_id"] = digest([event_id, end.isoformat(), current.isoformat(), "MISSED", reasons])
    return result


def save_bars(bars: list[dict], session: str, path: Path = STORE) -> None:
    with closing(connect_store(path)) as connection, connection:
        connection.executemany("INSERT INTO one_minute_bars VALUES (?,?,?,?,?,?) ON CONFLICT(evidence_id) DO NOTHING",
            [(digest(bar), session, bar["symbol"], bar["open_at"], bar["received_at"], canonical(bar)) for bar in bars])


def stored_bars(symbol: str, session: str, path: Path = STORE) -> dict[datetime, dict]:
    with closing(sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        rows = connection.execute("SELECT payload_json FROM one_minute_bars WHERE session=? AND symbol=? ORDER BY received_at",
                                  (session, symbol)).fetchall()
    return {timestamp(bar["open_at"]): bar for bar in (json.loads(row[0]) for row in rows)}


def persist_evaluation(result: dict, path: Path = STORE) -> None:
    persist_evaluations([result], path)


def persist_evaluations(results: list[dict], path: Path = STORE) -> None:
    with closing(connect_store(path)) as connection, connection:
        connection.executemany("INSERT OR IGNORE INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)",
            [(result["evaluation_id"], result["event_id"], result["session"], result["symbol"],
              result["right"], result["bar_end"], result["state"], canonical(result), result["evaluated_at"])
             for result in results])


def expiry_audit(session: str, dates: list[str], scope_hash: str | None,
                 symbols: set[str], audit_dir: Path = EXPIRY_AUDIT_DIR) -> dict:
    """Expose a dated provider check only for the exact watchlist and policy window."""
    path = audit_dir / f"expiry-audit-{session.replace('-', '')}.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        items = report["items"]
        checked = timestamp(report["as_of"])
        if (not scope_hash or report["scope_hash"] != scope_hash
                or report["target_dates"] != dates
                or checked.astimezone(NY).date().isoformat() != session
                or len(items) != len(symbols)
                or {item["symbol"] for item in items} != symbols):
            raise ValueError("AUDIT_CONTEXT_MISMATCH")
        available = [item for item in items if item["provider_status"] == "available"]
        unresolved = [item for item in items if item["provider_status"] == "IDENTITY_UNCONFIRMED"]
        failed = len(items) - len(available) - len(unresolved)
        matched = [{"symbol": item["symbol"], "dates": item["matched_expiries"]}
                   for item in available if item["matched_expiries"]]
        if (any(set(item["matched_expiries"]) - set(dates) for item in available)
                or report["total"] != len(items) or report["matched"] != len(matched)
                or report["no_match"] != len(available) - len(matched)
                or report["identity_unconfirmed"] != len(unresolved)
                or report["failed"] != failed):
            raise ValueError("AUDIT_COUNTS_MISMATCH")
        return {"status": "COMPLETE_WITH_IDENTITY_GAPS" if not failed and unresolved else
                "COMPLETE" if not failed else "PARTIAL", "checked_at": checked.isoformat(),
                "verified_identity_queried": len(available), "matched": len(matched),
                "no_matching_expiry": len(available) - len(matched),
                "identity_unconfirmed": len(unresolved), "query_failed": failed,
                "matched_symbols": matched,
                "unconfirmed_symbols": [item["symbol"] for item in unresolved],
                "items": [{"symbol": item["symbol"], "provider_status": item["provider_status"],
                           "matched_expiries": item["matched_expiries"], "reason": item.get("reason")}
                          for item in items],
                "source": report["source"], "evidence_path": str(path)}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "NOT_VERIFIED", "verified_identity_queried": 0,
                "matched": None, "no_matching_expiry": None,
                "identity_unconfirmed": None, "query_failed": None}


def evaluation_detail(evaluation_id: str, path: Path = STORE) -> dict:
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT payload_json FROM one_minute_evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
    if row is None:
        raise KeyError(evaluation_id)
    return json.loads(row[0])


def status(path: Path = STORE, *, now: datetime | None = None, policy: dict | None = None,
           scope_hash: str | None = None, history_sessions: list[str] | None = None) -> dict:
    policy = policy or load_policy()
    current = timestamp(now or datetime.now(UTC))
    session = current.astimezone(NY).date().isoformat()
    expiry_dates = [date.fromisoformat(session) + timedelta(days=int(dte))
                    for dte in policy["contracts"]["allowed_calendar_dtes"]]
    contract_window = {"calendar_dtes": policy["contracts"]["allowed_calendar_dtes"],
                       "dates": [value.isoformat() for value in expiry_dates],
                       "weekend_only": bool(expiry_dates) and all(value.weekday() >= 5 for value in expiry_dates),
                       "provider_expiries_verified_for_all": False}
    event_policy = json.loads(EVENT_PROPOSAL.read_text(encoding="utf-8"))
    event_policy["proposal_sha256"] = hashlib.sha256(EVENT_PROPOSAL.read_bytes()).hexdigest()
    approvals = approval_status(policy, scope_hash)
    from .options_one_minute_status import evaluation_view, validate_history_sessions
    if history_sessions is None:
        from .options_two_hour_data import sessions_before
        prior_sessions = sessions_before(date.fromisoformat(session), policy["history_sessions"])
    else:
        prior_sessions = validate_history_sessions(history_sessions, session=session,
                                                   count=policy["history_sessions"])
    if not path.exists():
        return {"status": "RESEARCH_ONLY_PENDING_O_SETUP", "initialized": False,
                "policy": policy, "event_policy": event_policy, "approvals": approvals,
                "contract_window": contract_window, "session": session,
                "summary": None, "candidates": [], "current_evaluations": [], "paper_enabled": False}
    from .bounded_sqlite import read_connection
    with read_connection(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        prewarm = [dict(row) for row in connection.execute(
            "SELECT symbol,state,reason,checked_at FROM one_minute_prewarm WHERE session=? ORDER BY symbol", (session,))]
        contract_window["universe_expiry_audit"] = expiry_audit(
            session, contract_window["dates"], scope_hash, {row["symbol"] for row in prewarm})
        page_counts = dict(connection.execute("""
            SELECT p.state,COUNT(*) FROM one_minute_history_pages p
            JOIN one_minute_prewarm w ON w.symbol=p.symbol AND w.session=?
            WHERE p.session>=? AND p.session<? AND w.state!='IDENTITY_UNRESOLVED'
            GROUP BY p.state""", (session, prior_sessions[0], session)).fetchall())
        view = evaluation_view(connection, session=session, policy_hash=policy["policy_hash"],
                               scope_hash=scope_hash)
        rows, bar_rows = view["rows"], view["bar_rows"]
        last_bar_end, last_evaluation_at = view["last_bar_end"], view["last_evaluation_at"]
        evaluation_counts, recent_observations = view["counts"], view["recent_observations"]
        candidates = [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM one_minute_candidates WHERE session=? ORDER BY published_at DESC", (session,))]
    for row in recent_observations:
        row["observation_expired"] = current > timestamp(row["deadline_at"])
    current_rows = sorted(rows, key=lambda row: (row["symbol"], row["right"]))
    # Keep legacy per-direction latest rows, but never call them a single-bar scan.
    at_bar = {(row["symbol"], row["right"]): row for row in bar_rows}
    bar_coverage = []
    for item in prewarm:
        directions = {}
        for right in policy["rights"]:
            evaluation = at_bar.get((item["symbol"], right))
            directions[right] = {"state": evaluation["state"] if evaluation else "NOT_EVALUATED_AT_BAR",
                "event_state": (evaluation.get("event_coverage") or {}).get("status", "NOT_EVALUATED") if evaluation else "NOT_EVALUATED",
                "contract_state": (evaluation.get("contract_qualification") or {}).get("status", "NOT_EVALUATED") if evaluation else "NOT_EVALUATED",
                "qualification_blockers": evaluation.get("qualification_blockers", []) if evaluation else [],
                "evaluation_id": evaluation.get("evaluation_id") if evaluation else None,
                "numeric_complete": bool(evaluation and evaluation.get("factor_evidence") and
                    evaluation["state"] in {"NO_TRIGGER", "NUMERIC_PASS", "NUMERIC_PASS_EVENT_PENDING"})}
        bar_coverage.append({"symbol": item["symbol"], "history_state": item["state"],
                             "history_reason": item["reason"], "directions": directions})
    bar_summary = {"session": session, "bar_end": last_bar_end, "policy_hash": policy["policy_hash"],
        "scope_hash": scope_hash, "registered_symbols": len(prewarm),
        "expected_directions": len(prewarm) * len(policy["rights"]),
        "evaluated_directions": sum(d["evaluation_id"] is not None for row in bar_coverage for d in row["directions"].values()),
        "numeric_complete_directions": sum(d["numeric_complete"] for row in bar_coverage for d in row["directions"].values()),
        "as_of": current.isoformat()}
    summary = {"registered_symbols": len(prewarm), "history_ready": sum(row["state"] == "READY" for row in prewarm),
               "history_days_fetched": sum(page_counts.get(state, 0) for state in
                   ("FETCHED", "EMPTY", "PARTIAL_RETRY", "PARTIAL_FINAL")),
               "history_partial_retry_days": page_counts.get("PARTIAL_RETRY", 0),
               "history_partial_final_days": page_counts.get("PARTIAL_FINAL", 0),
               "history_days_required": len(prior_sessions) * sum(row["state"] != "IDENTITY_UNRESOLVED" for row in prewarm),
               "history_days_empty": page_counts.get("EMPTY", 0),
               "history_pending": sum(row["state"] in {"PENDING", "RETRY"} for row in prewarm),
               "history_deferred": sum(row["state"] in {"QUOTA_DEFERRED", "DATA_INSUFFICIENT"} for row in prewarm),
               "identity_unresolved": sum(row["state"] == "IDENTITY_UNRESOLVED" for row in prewarm),
               "evaluated_directions": len(current_rows), "numeric_directions": sum(bool(row["factor_evidence"]) for row in current_rows),
               "complete_directions": sum(row["state"] in {"NUMERIC_PASS", "NUMERIC_PASS_EVENT_PENDING", "NO_TRIGGER"} and bool(row["factor_evidence"]) for row in current_rows),
               "numeric_trigger_pending": sum(row["state"] == "NUMERIC_PASS_EVENT_PENDING" for row in current_rows),
               "saved_evaluations": sum(evaluation_counts.values()),
               "saved_numeric_triggers": evaluation_counts.get("NUMERIC_PASS_EVENT_PENDING", 0),
               "data_incomplete": sum(row["state"] == "INCOMPLETE" for row in current_rows),
               "rule_not_met": sum(row["state"] == "NO_TRIGGER" and bool(row["factor_evidence"]) for row in current_rows),
               "qualified_candidates": len(candidates), "last_bar_end": last_bar_end,
               "last_evaluation_at": last_evaluation_at}
    return {"status": "RESEARCH_ONLY_PENDING_O_SETUP", "initialized": True,
            "policy": policy, "event_policy": event_policy, "approvals": approvals,
            "contract_window": contract_window, "session": session,
            "summary": summary, "prewarm": prewarm, "current_evaluations": current_rows,
            "summary_basis": "LATEST_PER_DIRECTION_MIXED_BARS", "bar_summary": bar_summary,
            "bar_coverage": bar_coverage,
            "recent_numeric_observations": recent_observations,
            "candidates": candidates, "paper_enabled": False, "real_orders_enabled": False}
