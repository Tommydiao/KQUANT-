"""Independent two-hour research kernel; no broker or Paper execution dependencies."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from contextlib import closing
from .options_data_paths import connect_store
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/options_two_hour_research_v1.json"
STORE = ROOT / "work/options_full_watch/full_watch.sqlite3"
NY = ZoneInfo("America/New_York")
SCHEMA = """
CREATE TABLE IF NOT EXISTS two_hour_jobs (
 job_id TEXT PRIMARY KEY, session TEXT NOT NULL, symbol TEXT NOT NULL,
 slot TEXT NOT NULL, queued_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
 state TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 retry_at TEXT, reason TEXT, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS two_hour_pending ON two_hour_jobs(state,retry_at,queued_at);
CREATE TABLE IF NOT EXISTS two_hour_evaluations (
 evaluation_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, symbol TEXT NOT NULL,
 right_name TEXT NOT NULL, session TEXT NOT NULL, slot TEXT NOT NULL,
 state TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS two_hour_candidates (
 event_id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL, payload_json TEXT NOT NULL,
 published_at TEXT
);
CREATE TABLE IF NOT EXISTS two_hour_bars (
 evidence_id TEXT PRIMARY KEY, session TEXT NOT NULL, symbol TEXT NOT NULL,
 open_at TEXT NOT NULL, received_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS two_hour_bar_lookup ON two_hour_bars(session,symbol,open_at,received_at);
CREATE TABLE IF NOT EXISTS two_hour_observations (
 event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, active INTEGER NOT NULL,
 payload_json TEXT NOT NULL
);
"""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return result.astimezone(UTC)


def finite(value: Any) -> bool:
    return not isinstance(value, bool) and value is not None and isinstance(value, (int, float)) and math.isfinite(value)


def entry_cutoff(schedule: dict, policy: dict) -> datetime:
    opening = timestamp(schedule["regular_open_utc"])
    closing = timestamp(schedule["regular_close_utc"])
    cutoff = opening + timedelta(minutes=policy["entry_window_minutes"])
    if policy.get("entry_cutoff_minutes_before_close") is not None:
        cutoff = min(cutoff, closing - timedelta(minutes=policy["entry_cutoff_minutes_before_close"]))
    return min(cutoff, closing)


def load_policy() -> dict:
    policy = json.loads(CONFIG.read_text(encoding="utf-8"))
    base = ROOT / "config" / policy["base_policy_file"]
    if hashlib.sha256(base.read_bytes()).hexdigest() != policy["base_policy_sha256"]:
        raise ValueError("BASE_POLICY_HASH_MISMATCH")
    if any(policy[key] for key in ("paper_enabled", "automatic_paper_enabled", "real_orders_enabled")):
        raise ValueError("RESEARCH_POLICY_CANNOT_ENABLE_EXECUTION")
    inherited = json.loads(base.read_text(encoding="utf-8"))
    policy["inherited_contracts"] = {key: inherited[key] for key in
        ("contract_selection", "exit_policy", "right_policies", "quote_proxy", "capital_policy", "cost_policy", "metric_policy")}
    policy["inherited_contracts"]["right_policies"] = {
        right: {"maximum_holding_sessions": values["maximum_holding_sessions"],
                "confirmation": "ROLLING_TWO_COMPLETE_5M_IN_ENTRY_WINDOW"}
        for right, values in inherited["right_policies"].items()}
    policy["policy_hash"] = digest(policy)
    return policy


def entry_window_gate(*, action: str, confirmed_at: str, quote_received_at: str | None,
                      schedule: dict, policy: dict | None = None) -> str | None:
    """Additional timing gate only; never grants approval or execution authority."""
    if action == "EXIT":
        return None
    if action != "ENTRY":
        return "INVALID_ACTION"
    policy = policy or load_policy()
    if not schedule.get("is_trading_day"):
        return "NOT_TRADING_DAY"
    opening = timestamp(schedule["regular_open_utc"])
    earliest = opening + timedelta(minutes=10)
    cutoff = entry_cutoff(schedule, policy)
    confirmed = timestamp(confirmed_at)
    if not earliest <= confirmed < cutoff:
        return "ENTRY_CONFIRMATION_OUTSIDE_WINDOW"
    if quote_received_at is not None:
        received = timestamp(quote_received_at)
        if received <= confirmed:
            return "QUOTE_NOT_AFTER_CONFIRMATION"
        if received >= cutoff:
            return "ENTRY_QUOTE_AFTER_CUTOFF"
    return None


def initialize(path: Path = STORE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() != "wal":
            raise RuntimeError("RESEARCH_QUEUE_WAL_UNAVAILABLE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(SCHEMA)


def save_bar(bar: dict, session: str, path: Path = STORE) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT OR IGNORE INTO two_hour_bars VALUES (?,?,?,?,?,?)",
                           (digest(bar), session, bar["symbol"], bar["open_at"], bar["received_at"], canonical(bar)))


def stored_bars(symbol: str, session: str, path: Path = STORE) -> dict:
    with sqlite3.connect(path) as connection:
        rows = connection.execute("SELECT payload_json FROM two_hour_bars WHERE session=? AND symbol=? ORDER BY received_at",
                                  (session, symbol)).fetchall()
    return {timestamp(bar["open_at"]): bar for bar in (json.loads(row[0]) for row in rows)}


def evaluate_pair(*, symbol: str, right: str, baseline: dict, bars: list[dict],
                  schedule: dict, event_clear: bool, now: datetime,
                  scope_hash: str, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    now = timestamp(now)
    opening = timestamp(schedule["regular_open_utc"])
    cutoff = entry_cutoff(schedule, policy)
    session = opening.astimezone(NY).date().isoformat()
    blockers: list[str] = []
    if right not in policy["rights"]:
        raise ValueError("INVALID_RIGHT")
    if not schedule.get("is_trading_day"):
        blockers.append("NOT_TRADING_DAY")
    if baseline.get("session") != session or baseline.get("symbol") != symbol:
        blockers.append("BASELINE_IDENTITY_OR_SESSION_MISMATCH")
    try:
        if timestamp(baseline["frozen_at"]) > opening or timestamp(baseline["max_input_available_at"]) > timestamp(baseline["frozen_at"]):
            blockers.append("BASELINE_NOT_FROZEN_BEFORE_OPEN")
    except (KeyError, ValueError, TypeError):
        blockers.append("BASELINE_TIME_MISSING")
    baseline_values = ("compression", "range_high", "range_low", "spy_close", "spy_ema20", "spy_ema50")
    if any(not finite(baseline.get(key)) for key in baseline_values):
        blockers.append("BASELINE_FEATURE_MISSING")
    if any(finite(baseline.get(key)) and baseline[key] <= 0 for key in baseline_values if key != "compression"):
        blockers.append("INVALID_BASELINE_PRICE")
    bar_end = None
    received_at = None
    slots = []
    if len(bars) != 2:
        blockers.append("EXACTLY_TWO_BARS_REQUIRED")
    else:
        try:
            starts = [timestamp(bar["open_at"]) for bar in bars]
            bar_end = starts[-1] + timedelta(minutes=5)
            if starts[1] - starts[0] != timedelta(minutes=5) or starts[0] < opening or (starts[0] - opening).total_seconds() % 300:
                blockers.append("NONCONTIGUOUS_OR_NONREGULAR_BARS")
            for bar, start in zip(bars, starts):
                received = timestamp(bar["received_at"])
                available = timestamp(bar["available_at"])
                if not bar.get("closed") or bar.get("interval") != "5m":
                    blockers.append("FORMING_OR_WRONG_PERIOD")
                if available < start + timedelta(minutes=5) or available > received or received > now:
                    blockers.append("BAR_TIME_CONFLICT")
                if bar.get("symbol") != symbol:
                    blockers.append("BAR_SYMBOL_MISMATCH")
                if not finite(bar.get("close")) or bar["close"] <= 0:
                    blockers.append("INVALID_BAR_CLOSE")
                if not finite(bar.get("turnover")) or bar["turnover"] < 0 or bar.get("turnover_source") != "NATIVE" or bar.get("currency") != "USD":
                    blockers.append("NATIVE_TURNOVER_MISSING")
            received_at = max(timestamp(bar["received_at"]) for bar in bars)
            slots = [start.astimezone(NY).strftime("%H:%M") for start in starts]
        except (KeyError, ValueError, TypeError):
            blockers.append("BAR_TIME_MISSING")
    prior = baseline.get("prior_sessions") or []
    history = baseline.get("turnover_by_session") or {}
    totals = []
    if len(prior) != 20 or len(set(prior)) != 20 or any(day >= session for day in prior):
        blockers.append("EXACT_PRIOR_20_SESSIONS_REQUIRED")
    elif len(slots) == 2:
        for day in prior:
            values = [history.get(day, {}).get(slot) for slot in slots]
            if not all(finite(value) and value >= 0 for value in values):
                blockers.append("SAME_SLOT_HISTORY_MISSING")
            else:
                totals.append(sum(values))
    denominator = statistics.median(totals) if len(totals) == 20 else None
    participation = None
    if denominator is not None and denominator <= 0:
        blockers.append("TURNOVER_BASELINE_NOT_POSITIVE")
    if denominator and len(bars) == 2 and all(finite(bar.get("turnover")) and bar["turnover"] >= 0 for bar in bars):
        participation = sum(bar["turnover"] for bar in bars) / denominator
    if participation is None:
        blockers.append("PARTICIPATION_UNAVAILABLE")
    if not event_clear:
        blockers.append("EVENT_UNKNOWN_OR_BLOCKED")
    conditions = {"compression": None, "participation": None, "breakout": None, "market": None}
    if finite(baseline.get("compression")):
        conditions["compression"] = 0 <= baseline["compression"] <= policy["compression_max"]
    if participation is not None:
        conditions["participation"] = participation >= policy["participation_min"]
    if len(bars) == 2 and all(finite(bar.get("close")) for bar in bars):
        boundary = baseline.get("range_high" if right == "CALL" else "range_low")
        if finite(boundary):
            conditions["breakout"] = all(bar["close"] > boundary if right == "CALL" else bar["close"] < boundary for bar in bars)
    market_keys = ("spy_close", "spy_ema50" if right == "CALL" else "spy_ema20")
    if all(finite(baseline.get(key)) for key in market_keys):
        conditions["market"] = baseline[market_keys[0]] >= baseline[market_keys[1]] if right == "CALL" else baseline[market_keys[0]] < baseline[market_keys[1]]
    deadline = min(bar_end + timedelta(seconds=policy["alert_deadline_seconds"]), cutoff) if bar_end else None
    if now >= cutoff or (bar_end and bar_end >= cutoff):
        state = "ENTRY_WINDOW_CLOSED"
    elif blockers:
        state = "UNKNOWN"
    elif deadline and now > deadline:
        state = "MISSED_EVALUATION_WINDOW"
    elif all(value is True for value in conditions.values()):
        state = "RESEARCH_CANDIDATE"
    else:
        state = "CONDITION_NOT_MET"
    event_id = digest({"policy": policy["policy_hash"], "scope": scope_hash, "symbol": symbol, "right": right, "session": session})
    return {"event_id": event_id, "evaluation_id": digest({"event": event_id, "baseline": baseline, "bars": bars, "now": now}),
            "policy_id": policy["policy_id"], "policy_hash": policy["policy_hash"], "scope_hash": scope_hash,
            "symbol": symbol, "right": right, "session": session, "slot": slots[-1] if slots else "",
            "state": state, "blockers": sorted(set(blockers)), "conditions": conditions,
            "participation": participation, "baseline_median": denominator, "baseline_hash": digest(baseline),
            "rule_evidence": {"compression": {"actual": baseline.get("compression"), "maximum": policy["compression_max"]},
                "participation": {"actual": participation, "minimum": policy["participation_min"]},
                "breakout": {"closes": [bar.get("close") for bar in bars], "boundary": baseline.get("range_high" if right == "CALL" else "range_low"), "comparison": ">" if right == "CALL" else "<"},
                "market": {"close": baseline.get("spy_close"), "ema": baseline.get("spy_ema50" if right == "CALL" else "spy_ema20"), "comparison": ">=" if right == "CALL" else "<"}},
            "bar_evidence": bars, "baseline_evidence": baseline, "data_complete": not blockers,
            "bar_end": bar_end.isoformat() if bar_end else None, "received_at": received_at.isoformat() if received_at else None,
            "evaluated_at": now.isoformat(), "deadline_at": deadline.isoformat() if deadline else None,
            "entry_cutoff": cutoff.isoformat(), "paper_eligible": False, "real_orders_enabled": False,
            "bar_close_to_evaluation_seconds": (now - bar_end).total_seconds() if bar_end else None,
            "receipt_to_evaluation_seconds": (now - received_at).total_seconds() if received_at else None}


def persist_evaluation(result: dict, path: Path = STORE) -> dict:
    with sqlite3.connect(path, timeout=30) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if result["state"] == "RESEARCH_CANDIDATE":
            inserted = connection.execute("INSERT OR IGNORE INTO two_hour_candidates VALUES (?,?,?,NULL)",
                (result["event_id"], result["evaluation_id"], canonical(result))).rowcount
            if not inserted:
                result = {**result, "state": "DUPLICATE_CANDIDATE"}
        connection.execute("INSERT OR IGNORE INTO two_hour_evaluations VALUES (?,?,?,?,?,?,?,?,?)",
            (result["evaluation_id"], result["event_id"], result["symbol"], result["right"], result["session"],
             result["slot"], result["state"], canonical(result), result["evaluated_at"]))
    return result


def enqueue(*, session: str, symbol: str, slot: str, payload: dict, now: datetime,
            deadline: datetime, path: Path = STORE, timeout: float = 30) -> str:
    key = digest({"session": session, "symbol": symbol, "slot": slot,
                  "kind": payload.get("kind", "RULE"), "evaluation_id": payload.get("evaluation_id"),
                  "policy_hash": payload.get("policy_hash"), "scope_hash": payload.get("scope_hash"),
                  "bars": payload.get("bars")})
    with closing(connect_store(path, timeout=timeout)) as connection, connection:
        connection.execute("INSERT OR IGNORE INTO two_hour_jobs VALUES (?,?,?,?,?,?,'PENDING',NULL,NULL,0,NULL,NULL,?)",
                           (key, session, symbol, slot, timestamp(now).isoformat(), timestamp(deadline).isoformat(), canonical(payload)))
    return key


def claim(*, owner: str, now: datetime, path: Path = STORE, lease_seconds: int = 10, kind: str = "RULE", timeout: float = 30) -> dict | None:
    stamp = timestamp(now).isoformat()
    with closing(connect_store(path, timeout=timeout)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""UPDATE two_hour_jobs SET state='MISSED_EVALUATION_WINDOW',reason='LOCAL_DEADLINE_EXCEEDED'
            WHERE state IN ('PENDING','LEASED') AND julianday(deadline_at)<=julianday(?)
              AND COALESCE(json_extract(payload_json,'$.kind'),'RULE')=?""", (stamp, kind))
        row = connection.execute("""SELECT j.* FROM two_hour_jobs j WHERE julianday(deadline_at)>julianday(?) AND
            COALESCE(json_extract(payload_json,'$.kind'),'RULE')=? AND
            ((state='PENDING' AND (retry_at IS NULL OR julianday(retry_at)<=julianday(?)))
             OR (state='LEASED' AND julianday(lease_until)<=julianday(?)))
            ORDER BY julianday(deadline_at), attempts, julianday(queued_at), symbol LIMIT 1""",
            (stamp, kind, stamp, stamp)).fetchone()
        if not row:
            return None
        until = min(timestamp(row["deadline_at"]), timestamp(now) + timedelta(seconds=lease_seconds)).isoformat()
        connection.execute("UPDATE two_hour_jobs SET state='LEASED',lease_owner=?,lease_until=?,attempts=attempts+1 WHERE job_id=?", (owner, until, row["job_id"]))
        return {**dict(row), "attempts": row["attempts"] + 1, "lease_owner": owner, "lease_until": until, "payload": json.loads(row["payload_json"])}


def finish(job: dict, *, owner: str, now: datetime, reason: str | None = None,
           retry_at: datetime | None = None, path: Path = STORE, timeout: float = 30) -> bool:
    stamp = timestamp(now).isoformat()
    state = "DONE" if reason is None else "FAILED"
    if retry_at is not None:
        state = "PENDING" if timestamp(retry_at) < timestamp(job["deadline_at"]) else "MISSED_EVALUATION_WINDOW"
    with closing(connect_store(path, timeout=timeout)) as connection, connection:
        return bool(connection.execute("""UPDATE two_hour_jobs SET state=?,reason=?,retry_at=?,lease_owner=NULL,lease_until=NULL
             WHERE job_id=? AND state='LEASED' AND lease_owner=? AND julianday(lease_until)>=julianday(?)""",
             (state, reason, timestamp(retry_at).isoformat() if retry_at else None, job["job_id"], owner, stamp)).rowcount)


def status(path: Path = STORE, *, now: datetime | None = None, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    base = {"status": "NOT_INITIALIZED", "policy": policy, "paper_enabled": False, "real_orders_enabled": False}
    if not path.exists():
        return base
    now = now or datetime.now(UTC)
    session = now.astimezone(NY).date().isoformat()
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='two_hour_jobs'").fetchone()
        if not exists:
            return base
        jobs = dict(connection.execute("SELECT state,COUNT(*) FROM two_hour_jobs GROUP BY state"))
        evaluations = dict(connection.execute("SELECT state,COUNT(*) FROM two_hour_evaluations GROUP BY state"))
        recent = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM two_hour_evaluations ORDER BY created_at DESC LIMIT 30")]
        current = [json.loads(row[0]) for row in connection.execute("""
            SELECT e.payload_json FROM two_hour_evaluations e JOIN (
                SELECT rowid AS evidence_rowid, ROW_NUMBER() OVER (
                    PARTITION BY symbol,right_name ORDER BY created_at DESC,rowid DESC
                ) AS rank_in_direction FROM two_hour_evaluations WHERE session=?
            ) ranked ON e.rowid=ranked.evidence_rowid WHERE rank_in_direction=1""", (session,))]
        evaluation_records, late_records, last_bar_end = connection.execute("""
            SELECT COUNT(*), COALESCE(SUM(COALESCE(json_extract(payload_json,'$.timing_state'),state)
                ='MISSED_EVALUATION_WINDOW'),0), MAX(json_extract(payload_json,'$.bar_end'))
            FROM two_hour_evaluations WHERE session=?""", (session,)).fetchone()
        last = connection.execute("""SELECT json_extract(payload_json,'$.evaluated_at')
            FROM two_hour_evaluations WHERE session=? ORDER BY created_at DESC,rowid DESC LIMIT 1""",
            (session,)).fetchone()
        first_trigger_rows = [json.loads(row[0]) for row in connection.execute("""
            SELECT payload_json FROM (
                SELECT payload_json, ROW_NUMBER() OVER (
                    PARTITION BY event_id ORDER BY created_at,rowid
                ) AS rank_in_event FROM two_hour_evaluations WHERE session=?
                AND json_type(payload_json,'$.conditions.compression')='true'
                AND json_type(payload_json,'$.conditions.participation')='true'
                AND json_type(payload_json,'$.conditions.breakout')='true'
                AND json_type(payload_json,'$.conditions.market')='true'
            ) WHERE rank_in_event=1""", (session,))]
        today_jobs = dict(connection.execute("SELECT state,COUNT(*) FROM two_hour_jobs WHERE session=? GROUP BY state", (session,)))
        candidates = [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM two_hour_candidates")
                      if json.loads(row[0]).get("session") == session]
        observations = []
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='two_hour_observations'").fetchone():
            observations = [{**json.loads(row[0]), "watch_created_at": row[1], "active": bool(row[2])} for row in connection.execute(
                "SELECT payload_json,created_at,active FROM two_hour_observations ORDER BY created_at DESC")]
        prewarm = []
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='two_hour_prewarm'").fetchone():
            prewarm = [{"session": row[0], "symbol": row[1], "state": row[2], "reason": row[3], "attempted_at": row[4]}
                       for row in connection.execute("SELECT session,symbol,state,reason,attempted_at FROM two_hour_prewarm WHERE session=(SELECT MAX(session) FROM two_hour_prewarm) ORDER BY symbol")]
    for item in current:
        item["display_state"] = display_state(item, now)
    trigger_history = [{**item, "display_state": display_state(item, now)}
                       for item in first_trigger_rows]
    active_candidates = [item for item in candidates if display_state(item, now) == "QUALIFIED_SIGNAL"]
    pending_triggers = [item for item in current if item["display_state"] == "PENDING_VERIFICATION"]
    reasons = {}
    for item in current:
        for reason in item.get("blockers", []):
            reasons[reason] = reasons.get(reason, 0) + 1
    complete = [item for item in current if item.get("data_complete") is True and not item.get("blockers")]
    numeric = [item for item in current if all(value is not None for value in item.get("conditions", {}).values()) and item.get("conditions")]
    summary = {"session": session, "evaluated_symbols": len({item["symbol"] for item in current}),
               "evaluated_directions": len(current), "evaluation_records": evaluation_records, "complete_directions": len(complete),
               "numeric_directions": len(numeric), "unknown_directions": sum(item["state"] == "UNKNOWN" for item in current),
               "condition_not_met": sum(item["state"] == "CONDITION_NOT_MET" for item in current),
               "candidate_count": len(candidates), "blockers": reasons, "jobs": today_jobs,
               "late_records": late_records,
               "last_evaluation_at": last[0] if last else None,
               "last_bar_end": last_bar_end,
               "scope_hashes": sorted({item.get("scope_hash", "") for item in current})}
    current_prewarm = [item for item in prewarm if item["session"] == session]
    ready_symbols = {item["symbol"] for item in current_prewarm if item["state"] == "READY"}
    summary["registered_symbols"] = len(current_prewarm)
    summary["latest_prewarm_session"] = prewarm[0]["session"] if prewarm else None
    summary["ready_symbols"] = len(ready_symbols)
    summary["unassessed_ready_symbols"] = len(ready_symbols - {item["symbol"] for item in current})
    return {"status": "RESEARCH_ONLY", "policy": policy, "jobs": jobs, "evaluations": evaluations,
            "summary": summary, "current_evaluations": [_list_row(item) for item in current],
            "candidates": [_list_row(item) for item in candidates],
            "observations": [_list_row(item) for item in observations],
            "qualified_signals": [_list_row(item) for item in active_candidates],
            "pending_triggers": [_list_row(item) for item in pending_triggers],
            "trigger_history": [_list_row(item) for item in trigger_history],
            "as_of": now.isoformat(),
            "recent": [_list_row(item) for item in recent], "prewarm": prewarm,
            "counts_are_all_recorded_sessions": True,
            "paper_enabled": False, "real_orders_enabled": False}


def _list_row(item: dict) -> dict:
    keys = ("evaluation_id", "event_id", "symbol", "right", "session", "slot", "state", "display_state",
            "blockers", "conditions", "rule_evidence", "event_reason", "data_complete", "timing_state",
            "contract_id", "contract_symbol", "bar_end", "received_at", "evaluated_at", "deadline_at",
            "entry_cutoff", "watch_created_at", "active", "policy_id", "policy_hash", "scope_hash")
    result = {key: item[key] for key in keys if key in item}
    qualification = item.get("contract_qualification")
    if isinstance(qualification, dict):
        result["contract_qualification"] = {key: qualification[key] for key in ("status", "contract_id", "checked_at") if key in qualification}
        selected = qualification.get("selected")
        if isinstance(selected, dict):
            result["contract_qualification"]["selected"] = {
                key: selected[key] for key in ("expiry_date", "strike", "dte", "multiplier") if key in selected
            }
    coverage = item.get("event_coverage")
    if isinstance(coverage, dict):
        result["event_coverage"] = {key: coverage[key] for key in ("status", "missing_categories", "trade_eligible") if key in coverage}
    return result


def display_state(item: dict, now: datetime) -> str:
    if item.get("entry_cutoff") and timestamp(now) >= timestamp(item["entry_cutoff"]):
        return "ENTRY_WINDOW_CLOSED"
    if item.get("deadline_at") and timestamp(now) > timestamp(item["deadline_at"]):
        return "EXPIRED"
    if item.get("timing_state") == "MISSED_EVALUATION_WINDOW":
        return "MISSED_EVALUATION_WINDOW"
    conditions = item.get("conditions", {})
    if conditions and all(conditions.get(key) is True for key in ("compression", "participation", "breakout", "market")):
        qualification = item.get("contract_qualification") or {}
        if not item.get("blockers") and qualification.get("status") == "PASS" and qualification.get("contract_id"):
            return "QUALIFIED_SIGNAL"
        return "PENDING_VERIFICATION"
    return item.get("state", "UNKNOWN")


def evaluation_detail(evaluation_id: str, path: Path = STORE) -> dict:
    if not path.exists():
        raise KeyError(evaluation_id)
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT event_id,payload_json FROM two_hour_evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        if not row:
            raise KeyError(evaluation_id)
        history = [json.loads(r[0]) for r in connection.execute(
            "SELECT payload_json FROM two_hour_evaluations WHERE event_id=? ORDER BY created_at", (row[0],))]
        publication = connection.execute("SELECT published_at FROM two_hour_candidates WHERE event_id=?", (row[0],)).fetchone()
    return {"evaluation": json.loads(row[1]), "history": history,
            "publication": publication[0] if publication else None, "immutable_evidence": True,
            "current_display_state": display_state(json.loads(row[1]), datetime.now(UTC))}


def set_observation(evaluation_id: str, active: bool, path: Path = STORE) -> dict:
    # This is a research bookmark, never a Paper intent or an execution approval.
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT event_id,payload_json FROM two_hour_evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        if row is None:
            raise ValueError("EVALUATION_NOT_FOUND")
        connection.execute("INSERT INTO two_hour_observations VALUES (?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET active=excluded.active,payload_json=excluded.payload_json",
                           (row[0], datetime.now(UTC).isoformat(), int(active), row[1]))
    return {"status": "WATCHING" if active else "REMOVED", "event_id": row[0], "paper_eligible": False}
