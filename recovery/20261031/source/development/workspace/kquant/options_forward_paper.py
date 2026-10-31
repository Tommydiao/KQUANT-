from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from .market_calendar import market_schedule
from .option_event_coverage import option_event_context
from .options_expression import option_chain, option_contract_snapshot, option_expiries
from .options_cbrm_research import live_opening_participation
from .options_paper_engineering import PaperLedger, content_hash, evaluate_candidate, freeze_plan, select_contract
from .stock_signals import api_stock_candles


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_forward_policy_v1.json"
R3_MANIFEST_PATH = REPO_ROOT / "outputs" / "options_review_r3" / "options-r3-20260920-03" / "manifest.json"
R3_ACCEPTANCE_PATH = REPO_ROOT / "config" / "review_acceptances" / "options_r3_20260920.txt"
OFFLINE_POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_offline_policy_v1.json"
DEFAULT_DB_PATH = REPO_ROOT / "work" / "options_forward_paper" / "options_forward_paper.sqlite3"
DEFAULT_RUN_ID = "options-forward-20260920-01"
ENGINE_VERSION = "options-forward-paper-v0.6.0"
NEW_YORK = ZoneInfo("America/New_York")


FORWARD_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS forward_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  rights_json TEXT NOT NULL,
  policy_hash TEXT NOT NULL,
  r3_bundle_id TEXT NOT NULL,
  r3_bundle_hash TEXT NOT NULL,
  ledger_path TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  next_check_at TEXT,
  permissions_json TEXT NOT NULL,
  detail_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_cycles (
  cycle_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  market_date TEXT NOT NULL,
  bucket TEXT NOT NULL,
  state TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, bucket)
);
CREATE TABLE IF NOT EXISTS forward_observations (
  observation_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  market_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  option_right TEXT NOT NULL,
  state TEXT NOT NULL,
  economic_opportunity_id TEXT,
  dependency_group_id TEXT NOT NULL,
  snapshot_hash TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_group_status (
  run_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  state TEXT NOT NULL,
  reason TEXT NOT NULL,
  candidate_count INTEGER NOT NULL,
  completed_count INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(run_id, profile_id)
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_forward_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(R3_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    approved = policy.get("approved_review_bundle") or {}
    blockers: list[str] = []
    if manifest.get("bundle_id") != approved.get("bundle_id"):
        blockers.append("R3_BUNDLE_ID_MISMATCH")
    if manifest.get("bundle_hash") != approved.get("bundle_hash"):
        blockers.append("R3_BUNDLE_HASH_MISMATCH")
    if (manifest.get("policy_validation") or {}).get("policy_hash") != approved.get("approved_policy_hash"):
        blockers.append("R3_APPROVED_POLICY_HASH_MISMATCH")
    if _sha256_file(OFFLINE_POLICY_PATH) != approved.get("offline_policy_file_sha256"):
        blockers.append("OFFLINE_POLICY_FILE_HASH_MISMATCH")
    expected_ids = {
        "strategy": "STRAT-SHORT-ATM-RANGE-EXPANSION-V1",
        "paper_execution": "PAPER-RECEIPT-TIME-PROXY-V1",
        "capital": "PAPER-RISK-10000-V1",
        "cost": "COST-OPTIONS-CONSERVATIVE-V1",
        "metric": "METRIC-OPTIONS-RESEARCH-GATE-V1",
    }
    if policy.get("selected_policy_ids") != expected_ids:
        blockers.append("POLICY_ID_SET_CHANGED")
    if policy.get("scope") != {"profile_id": "SHORT_ATM_DAYS_WEEK", "rights": ["CALL", "PUT"], "evidence_strata_separate": True}:
        blockers.append("APPROVED_SCOPE_CHANGED")
    permissions = policy.get("permissions") or {}
    forbidden = ("real_account_access", "real_orders", "automatic_capital_increase", "strategy_mutation", "public_trade_signal_generation")
    if any(bool(permissions.get(key)) for key in forbidden):
        blockers.append("FORBIDDEN_PERMISSION_ENABLED")
    if not permissions.get("forward_paper_research") or not permissions.get("automatic_receipt_proxy_paper_entry"):
        blockers.append("FORWARD_PAPER_PERMISSION_MISSING")
    if blockers:
        raise RuntimeError(";".join(blockers))
    policy["policy_hash"] = content_hash({key: value for key, value in policy.items() if key != "policy_hash"})
    return policy


def initialize_forward_store(path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(FORWARD_SCHEMA)
        now = utc_now()
        connection.execute("INSERT OR REPLACE INTO forward_meta VALUES (?,?,?)", ("schema_version", _json(1), now))
        connection.execute("INSERT OR REPLACE INTO forward_meta VALUES (?,?,?)", ("engine_version", _json(ENGINE_VERSION), now))
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return {"path": str(path.resolve()), "schema_version": 1, "integrity_check": integrity}


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _next_market_check(main_db_path: Path, now: datetime) -> str | None:
    current = now.astimezone(UTC)
    local = current.astimezone(NEW_YORK)
    for offset in range(10):
        day = local.date() + timedelta(days=offset)
        schedule = market_schedule(day, main_db_path)
        if not schedule.get("is_trading_day"):
            continue
        earliest = datetime.fromisoformat(str(schedule["regular_open_utc"])) + timedelta(minutes=10)
        latest = datetime.fromisoformat(str(schedule["regular_close_utc"])) - timedelta(minutes=30)
        if current < earliest:
            return earliest.isoformat()
        if current <= latest:
            return current.isoformat()
    return None


def start_or_resume_forward_run(
    *,
    main_db_path: Path,
    store_path: Path = DEFAULT_DB_PATH,
    run_id: str = DEFAULT_RUN_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    policy = load_forward_policy()
    initialize_forward_store(store_path)
    ledger_path = store_path.parent / f"{run_id}-ledger.sqlite3"
    PaperLedger(ledger_path, policy=policy)
    approved = policy["approved_review_bundle"]
    permissions = policy["permissions"]
    detail = {
        "evidence_class": policy["quote_proxy"]["evidence_class"],
        "classification": policy["quote_proxy"]["classification"],
        "natural_opportunities_only": True,
        "model_consumed": False,
        "real_order_path": False,
        "capital_reference_usd": policy["capital_policy"]["reference_capital_usd"],
        "capital_is_simulated_and_frozen": True,
        "owner_acceptance_sha256": _sha256_file(R3_ACCEPTANCE_PATH),
    }
    next_check = _next_market_check(main_db_path, current)
    with _connect(store_path) as connection:
        existing = connection.execute("SELECT * FROM forward_runs WHERE run_id=?", (run_id,)).fetchone()
        if existing:
            if existing["policy_hash"] != policy["policy_hash"] or existing["r3_bundle_hash"] != approved["bundle_hash"]:
                raise RuntimeError("immutable forward run identity collision")
            connection.execute(
                "UPDATE forward_runs SET next_check_at=?,updated_at=? WHERE run_id=?",
                (next_check, current.isoformat(), run_id),
            )
        else:
            connection.execute(
                """INSERT INTO forward_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    "WAIT_MARKET",
                    policy["selected_policy_ids"]["strategy"],
                    policy["scope"]["profile_id"],
                    _json(policy["scope"]["rights"]),
                    policy["policy_hash"],
                    approved["bundle_id"],
                    approved["bundle_hash"],
                    str(ledger_path.resolve()),
                    current.isoformat(),
                    current.isoformat(),
                    next_check,
                    _json(permissions),
                    _json(detail),
                ),
            )
        _upsert_group_status(connection, run_id, "SHORT_ATM_DAYS_WEEK", "WAIT_MARKET", "NEXT_ELIGIBLE_MARKET_WINDOW", 0, 0, current)
        _upsert_group_status(connection, run_id, "MEDIUM_ATM_WEEKS_MONTHS", "NOT_EVALUATED", "RESEARCH_CONTINUES_NOT_APPROVED_FOR_FORWARD_PAPER", 0, 0, current)
        _upsert_group_status(connection, run_id, "LONG_OTM_MONTHS_YEAR", "NOT_EVALUATED", "RESEARCH_CONTINUES_NOT_APPROVED_FOR_FORWARD_PAPER", 0, 0, current)
        connection.commit()
    return forward_status(store_path=store_path, run_id=run_id)


def _upsert_group_status(
    connection: sqlite3.Connection,
    run_id: str,
    profile_id: str,
    state: str,
    reason: str,
    candidates: int,
    completed: int,
    now: datetime,
) -> None:
    connection.execute(
        """INSERT INTO forward_group_status VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(run_id,profile_id) DO UPDATE SET
          state=excluded.state,reason=excluded.reason,candidate_count=excluded.candidate_count,
          completed_count=excluded.completed_count,updated_at=excluded.updated_at""",
        (run_id, profile_id, state, reason, candidates, completed, now.isoformat()),
    )


def set_new_entries_paused(paused: bool, *, store_path: Path = DEFAULT_DB_PATH, reason: str = "operator_request") -> dict[str, Any]:
    initialize_forward_store(store_path)
    with _connect(store_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO forward_meta VALUES (?,?,?)",
            ("new_entries_paused", _json({"paused": bool(paused), "reason": reason}), utc_now()),
        )
        connection.commit()
    return {"paused": bool(paused), "reason": reason, "orders_affected": False, "open_paper_monitoring_continues": True}


def _new_entries_paused(store_path: Path) -> tuple[bool, str]:
    with _connect(store_path) as connection:
        row = connection.execute("SELECT value_json FROM forward_meta WHERE key='new_entries_paused'").fetchone()
    if not row:
        return False, ""
    payload = json.loads(row["value_json"])
    return bool(payload.get("paused")), str(payload.get("reason") or "")


def _closed(candles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item) for item in candles if item.get("bar_state") == "closed_candle"]


def _ema(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    alpha = 2.0 / (length + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _compression_ratio(closes: list[float]) -> float | None:
    if len(closes) < 273:
        return None
    returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes)) if closes[index] > 0 and closes[index - 1] > 0]
    if len(returns) < 272:
        return None
    windows = [statistics.pstdev(returns[index - 20:index]) for index in range(20, len(returns) + 1)]
    historical = windows[-253:-1]
    if not historical or statistics.median(historical) <= 0:
        return None
    return windows[-1] / statistics.median(historical)


def _default_snapshot_provider(symbol: str, right: str, now: datetime, main_db_path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    daily = api_stock_candles(symbol, "2y", "1d", "live", main_db_path, allow_reference_fallback=False, background=True)
    intraday = api_stock_candles(symbol, "1d", "5m", "live", main_db_path, allow_reference_fallback=False, background=True)
    spy_daily = daily if symbol == "SPY" else api_stock_candles("SPY", "2y", "1d", "live", main_db_path, allow_reference_fallback=False, background=True)
    local_day = now.astimezone(NEW_YORK).date()
    def before_today(row):
        try:
            parsed = datetime.fromisoformat(str(row["open_time"]))
            return parsed.tzinfo is not None and parsed.astimezone(NEW_YORK).date() < local_day
        except (KeyError, ValueError, TypeError):
            return False
    daily_rows = sorted((r for r in _closed(daily.get("candles") or []) if before_today(r)), key=lambda r: r["open_time"])
    intraday_rows = _closed(intraday.get("candles") or [])
    spy_rows = sorted((r for r in _closed(spy_daily.get("candles") or []) if before_today(r)), key=lambda r: r["open_time"])
    local_date = now.astimezone(NEW_YORK).date().isoformat()
    today_rows = []
    for row in intraday_rows:
        opened = datetime.fromisoformat(str(row["open_time"]))
        local = opened.astimezone(NEW_YORK) if opened.tzinfo else None
        if (local and local.date() == local_day and local.strftime("%H:%M:%S") in {"09:30:00", "09:35:00"}
                and opened + timedelta(minutes=5) <= now):
            today_rows.append(row)
    first_two = sorted(today_rows, key=lambda row: row["open_time"])
    if len(first_two) != 2 or len({r["open_time"] for r in first_two}) != 2:
        first_two = []
    prior = daily_rows[-20:] if len(daily_rows) >= 20 else []
    prior_session_dates = [datetime.fromisoformat(str(row["open_time"])).astimezone(NEW_YORK).date().isoformat() for row in prior]
    closes = [float(row["close"]) for row in daily_rows if float(row.get("close") or 0) > 0]
    spy_closes = [float(row["close"]) for row in spy_rows if float(row.get("close") or 0) > 0]
    decision = now.astimezone(UTC).isoformat()
    event = option_event_context(main_db_path, symbol, decision, until=(now + timedelta(days=7)).isoformat())
    missing: list[str] = []
    if daily.get("provider_status") != "available" or intraday.get("provider_status") != "available" or spy_daily.get("provider_status") != "available":
        missing.append("LIVE_LONGBRIDGE_BARS_UNAVAILABLE")
    if len(first_two) < 2:
        missing.append("FIRST_TWO_CLOSED_5M_BARS_UNAVAILABLE")
    if len(prior) < 20:
        missing.append("PRIOR_20_SESSIONS_UNAVAILABLE")
    participation = {"status": "PARTIAL_HISTORY", "value": None, "missing": ["OPENING_PAIR_OR_PRIOR_SESSIONS_UNAVAILABLE"]}
    if len(first_two) == 2 and len(prior_session_dates) == 20:
        try:
            participation = live_opening_participation(
                symbol=symbol,
                session=local_date,
                prior_sessions=prior_session_dates,
                as_of=decision,
            )
        except Exception as exc:
            participation = {"status": "UNAVAILABLE", "value": None, "missing": [type(exc).__name__]}
    if participation.get("status") != "AVAILABLE":
        missing.append(f"SAME_CLOCK_TURNOVER_{participation.get('status') or 'UNAVAILABLE'}")
    if not event.get("trade_eligible"):
        missing.append("EVENT_COVERAGE_INCOMPLETE_OR_BLOCKED")
    return {
        "snapshot_id": f"ofs_{content_hash({'symbol': symbol, 'right': right, 'date': local_date, 'decision': decision})[:24]}",
        "symbol": symbol,
        "right": right,
        "market_session_date": local_date,
        "frozen_universe": policy["frozen_universe"],
        "all_bars_closed": not missing or all(item not in missing for item in ("FIRST_TWO_CLOSED_5M_BARS_UNAVAILABLE", "PRIOR_20_SESSIONS_UNAVAILABLE")),
        "max_input_available_at": decision,
        "snapshot_frozen_at": decision,
        "evaluation_started_at": decision,
        "evaluation_finished_at": decision,
        "decision_committed_at": decision,
        "event_status": "CLEAR" if event.get("trade_eligible") else "UNKNOWN",
        "event_context": event,
        "compression_ratio": _compression_ratio(closes),
        "opening_participation": participation.get("value"),
        "opening_participation_evidence": participation,
        "first_5m_close": float(first_two[0]["close"]) if len(first_two) >= 1 else None,
        "second_5m_close": float(first_two[1]["close"]) if len(first_two) >= 2 else None,
        "prior_range_high": max(float(row["high"]) for row in prior) if prior else None,
        "prior_range_low": min(float(row["low"]) for row in prior) if prior else None,
        "spy_prior_close": spy_closes[-1] if spy_closes else None,
        "spy_ema20": _ema(spy_closes, 20),
        "spy_ema50": _ema(spy_closes, 50),
        "underlying_price": float(first_two[-1]["close"]) if first_two else (closes[-1] if closes else None),
        "data_blockers": sorted(set(missing)),
        "source": "LONG_BRIDGE_CLOSED_BARS",
        "source_payload_hashes": {"daily": content_hash(daily), "intraday": content_hash(intraday), "spy_daily": content_hash(spy_daily)},
    }


def _default_contract_provider(candidate: dict[str, Any], snapshot: dict[str, Any], main_db_path: Path, policy: dict[str, Any], *, deadline_at: datetime | None = None) -> list[dict[str, Any]]:
    current = date.fromisoformat(str(candidate["market_session_date"]))
    expiries = option_expiries(str(candidate["symbol"]))
    eligible_expiries = []
    for value in expiries.get("expiries") or []:
        dte = (date.fromisoformat(str(value)) - current).days
        selection = policy["contract_selection"]
        if selection["dte_min"] <= dte <= selection["dte_max"] and (
            selection.get("allowed_dtes") is None or dte in selection["allowed_dtes"]
        ):
            eligible_expiries.append((abs(dte - policy["contract_selection"]["dte_target"]), dte, str(value)))
    contracts: list[dict[str, Any]] = []
    spot = float(snapshot.get("underlying_price") or 0)
    for _, dte, expiry in sorted(eligible_expiries)[:3]:
        if deadline_at is not None and datetime.now(UTC) >= deadline_at:
            break
        chain = option_chain(str(candidate["symbol"]), expiry)
        nearby = sorted(chain.get("contracts") or [], key=lambda item: abs(float(item.get("strike_price") or 0) - spot))[:5]
        for item in nearby:
            if deadline_at is not None and datetime.now(UTC) >= deadline_at:
                break
            contract_id = item.get("call_symbol") if candidate["right"] == "CALL" else item.get("put_symbol")
            if not contract_id:
                continue
            option = option_contract_snapshot(str(contract_id), main_db_path)
            # Depth size units have not been proven to be contract counts. Unknown remains unknown.
            contracts.append({
                "contract_id": str(contract_id),
                "underlying": candidate["symbol"],
                "right": candidate["right"],
                "dte": dte,
                "expiry_date": expiry,
                "delta": option.get("delta"),
                "multiplier": option.get("contract_multiplier"),
                "deliverable": "STANDARD" if option.get("is_standard") else "UNKNOWN",
                "adjusted": not bool(option.get("is_standard")),
                "bid": option.get("bid"),
                "ask": option.get("ask"),
                "bid_size": None,
                "ask_size": None,
                "raw_bid_size": option.get("bid_size"),
                "raw_ask_size": option.get("ask_size"),
                "size_unit_status": "UNVERIFIED_NOT_ASSUMED_CONTRACTS",
                "strike": item.get("strike_price"),
                "snapshot": option,
            })
    return contracts


def _default_quote_provider(plan: dict[str, Any], main_db_path: Path) -> dict[str, Any] | None:
    option = option_contract_snapshot(str(plan["contract"]["contract_id"]), main_db_path)
    if option.get("provider_status") != "available":
        return None
    # The quantity unit is still unverified, so the quote must not become a fill.
    return {
        "quote_event_id": f"fq_{content_hash(option)[:24]}",
        "contract_id": plan["contract"]["contract_id"],
        "evidence_class": "RECEIPT_TIME_QUOTE_PROXY",
        "request_started_at": option.get("bbo_request_started_at"),
        "received_at": option.get("bbo_received_at"),
        "bid": option.get("bid"),
        "ask": option.get("ask"),
        "bid_size": None,
        "ask_size": None,
        "multiplier": option.get("contract_multiplier"),
        "session_health": "HEALTHY" if option.get("depth_status") == "available" else "DEGRADED",
        "cached": False,
        "classification": "RECEIPT_TIME_OBSERVATION_NOT_EXCHANGE_FILL",
        "size_unit_status": "UNVERIFIED_NOT_ASSUMED_CONTRACTS",
    }


def _automatic_entry_allowed() -> bool:
    # A pending manual overlay cannot grant execution, but its restriction must
    # already prevent legacy automatic entry from bypassing owner confirmation.
    try:
        overlay = json.loads((REPO_ROOT / "config" / "options_signal_copilot_v1.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    manual = overlay.get("paper_execution_overlay") or {}
    if manual.get("owner_confirmation_required_for_entry") or manual.get("mode") == "PAPER_MANUAL_CONFIRM":
        return False
    return False  # No non-manual replacement has been approved for this runtime.


def cycle_forward_run(
    *,
    main_db_path: Path,
    store_path: Path = DEFAULT_DB_PATH,
    run_id: str = DEFAULT_RUN_ID,
    now: datetime | None = None,
    snapshot_provider: Callable[[str, str, datetime, Path, dict[str, Any]], dict[str, Any]] | None = None,
    contract_provider: Callable[[dict[str, Any], dict[str, Any], Path, dict[str, Any]], list[dict[str, Any]]] | None = None,
    quote_provider: Callable[[dict[str, Any], Path], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    policy = load_forward_policy()
    start_or_resume_forward_run(main_db_path=main_db_path, store_path=store_path, run_id=run_id, now=current)
    local = current.astimezone(NEW_YORK)
    schedule = market_schedule(local.date(), main_db_path)
    market_open = datetime.fromisoformat(str(schedule["regular_open_utc"])) if schedule.get("regular_open_utc") else None
    market_close = datetime.fromisoformat(str(schedule["regular_close_utc"])) if schedule.get("regular_close_utc") else None
    in_window = bool(schedule.get("is_trading_day") and market_open and market_close and market_open + timedelta(minutes=10) <= current <= market_close - timedelta(minutes=30))
    five_minute = local.replace(minute=(local.minute // 5) * 5, second=0, microsecond=0)
    bucket = f"{local.date()}:{five_minute.strftime('%H:%M') if in_window else 'closed'}"
    cycle_id = f"ofc_{content_hash({'run': run_id, 'bucket': bucket})[:24]}"
    with _connect(store_path) as connection:
        previous = connection.execute("SELECT detail_json,state FROM forward_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
    if previous:
        return {"status": "IDEMPOTENT_REPLAY", "state": previous["state"], "detail": json.loads(previous["detail_json"]), "run_id": run_id}

    paused, pause_reason = _new_entries_paused(store_path)
    if not in_window:
        detail = {"reason": "WAIT_MARKET", "market_date": local.date().isoformat(), "natural_opportunities_created": 0, "fills_created": 0, "next_check_at": _next_market_check(main_db_path, current)}
        _record_cycle(store_path, run_id, cycle_id, local.date().isoformat(), bucket, "WAIT_MARKET", detail, current)
        return {"status": "WAIT_MARKET", "run_id": run_id, **detail}
    if paused:
        detail = {"reason": "NEW_ENTRIES_PAUSED", "pause_reason": pause_reason, "natural_opportunities_created": 0, "fills_created": 0}
        _record_cycle(store_path, run_id, cycle_id, local.date().isoformat(), bucket, "PAUSED", detail, current)
        return {"status": "PAUSED", "run_id": run_id, **detail}

    snapshot_provider = snapshot_provider or _default_snapshot_provider
    contract_provider = contract_provider or _default_contract_provider
    quote_provider = quote_provider or _default_quote_provider
    ledger_path = store_path.parent / f"{run_id}-ledger.sqlite3"
    ledger = PaperLedger(ledger_path, policy=policy)
    with _connect(store_path) as connection:
        seen = {str(row[0]) for row in connection.execute("SELECT economic_opportunity_id FROM forward_observations WHERE run_id=? AND state='ELIGIBLE_RESEARCH_CANDIDATE' AND economic_opportunity_id IS NOT NULL", (run_id,))}
    counts = {"observed": 0, "candidates": 0, "plans": 0, "fills": 0, "data_blocked": 0, "no_candidate": 0}
    reasons: dict[str, int] = {}
    for symbol in policy["frozen_universe"]:
        for right in policy["scope"]["rights"]:
            snapshot = snapshot_provider(symbol, right, current, main_db_path, policy)
            candidate = evaluate_candidate(snapshot, policy=policy, seen_opportunities=seen)
            if snapshot.get("data_blockers"):
                candidate["state"] = "DATA_BLOCKED"
                candidate["reasons"] = sorted(set(candidate.get("reasons") or []) | set(snapshot["data_blockers"]))
            dependency = f"dep_{content_hash({'date': local.date().isoformat(), 'opportunity': candidate['economic_opportunity_id']})[:24]}"
            payload: dict[str, Any] = {"snapshot": snapshot, "candidate": candidate, "selection": None, "entry": None}
            counts["observed"] += 1
            counts["data_blocked" if candidate["state"] == "DATA_BLOCKED" else "no_candidate"] += int(candidate["state"] != "ELIGIBLE_RESEARCH_CANDIDATE")
            for reason in candidate.get("reasons") or []:
                reasons[reason] = reasons.get(reason, 0) + 1
            if candidate["state"] == "ELIGIBLE_RESEARCH_CANDIDATE":
                counts["candidates"] += 1
                contracts = contract_provider(candidate, snapshot, main_db_path, policy)
                selection = select_contract(candidate, contracts, underlying_price=float(snapshot["underlying_price"]), policy=policy)
                payload["selection"] = selection
                if selection.get("selected"):
                    plan = freeze_plan(candidate, selection["selected"], policy=policy)
                    plan["portfolio_id"] = f"forward-paper-{right.lower()}"
                    plan["intent_id"] = f"opi_{content_hash({'plan': plan['plan_id'], 'class': 'forward-paper'})[:24]}"
                    plan["forward_run_id"] = run_id
                    plan["fill_assumption"] = "RECEIPT_TIME_QUOTE_PROXY_NOT_EXCHANGE_FILL"
                    ledger.record_plan(candidate, plan)
                    counts["plans"] += 1
                    if _automatic_entry_allowed():
                        quote = quote_provider(plan, main_db_path)
                        payload["entry"] = ledger.attempt_entry(plan["plan_id"], quote) if quote else {"status": "NO_FILL", "reason": "QUOTE_UNAVAILABLE"}
                    else:
                        payload["entry"] = {"status": "NO_FILL", "reason": "OWNER_CONFIRMATION_REQUIRED_LEGACY_AUTO_PATH_BLOCKED"}
                    if payload["entry"].get("status") == "PAPER_OPEN":
                        counts["fills"] += 1
            _record_observation(store_path, run_id, local.date().isoformat(), symbol, right, candidate, dependency, payload, current)

    state = "OPEN_TRACKING" if counts["fills"] else ("PAPER_CANDIDATE" if counts["candidates"] else "DATA_LIMITED")
    detail = {"counts": counts, "reasons": reasons, "evidence_class": "RECEIPT_TIME_QUOTE_PROXY", "strict_native_bbo_used": False, "orders_created": 0}
    _record_cycle(store_path, run_id, cycle_id, local.date().isoformat(), bucket, state, detail, current)
    _refresh_short_group(store_path, run_id, current, state)
    return {"status": state, "run_id": run_id, **detail}


def _record_cycle(path: Path, run_id: str, cycle_id: str, market_date: str, bucket: str, state: str, detail: dict[str, Any], now: datetime) -> None:
    next_check = detail.get("next_check_at")
    with _connect(path) as connection:
        connection.execute("INSERT OR IGNORE INTO forward_cycles VALUES (?,?,?,?,?,?,?)", (cycle_id, run_id, market_date, bucket, state, _json(detail), now.isoformat()))
        connection.execute("UPDATE forward_runs SET status=?,updated_at=?,next_check_at=? WHERE run_id=?", (state, now.isoformat(), next_check, run_id))
        connection.commit()


def _record_observation(path: Path, run_id: str, market_date: str, symbol: str, right: str, candidate: dict[str, Any], dependency: str, payload: dict[str, Any], now: datetime) -> None:
    observation_id = f"fob_{content_hash({'run': run_id, 'date': market_date, 'symbol': symbol, 'right': right, 'snapshot': candidate.get('snapshot_hash')})[:24]}"
    with _connect(path) as connection:
        existing = connection.execute("SELECT payload_json FROM forward_observations WHERE observation_id=?", (observation_id,)).fetchone()
        encoded = _json(payload)
        if existing and existing["payload_json"] != encoded:
            raise RuntimeError("immutable forward observation collision")
        connection.execute(
            "INSERT OR IGNORE INTO forward_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (observation_id, run_id, market_date, symbol, right, candidate["state"], candidate.get("economic_opportunity_id"), dependency, candidate.get("snapshot_hash"), encoded, now.isoformat()),
        )
        connection.commit()


def _refresh_short_group(path: Path, run_id: str, now: datetime, state: str) -> None:
    summary = _ledger_summary(path.parent / f"{run_id}-ledger.sqlite3")
    with _connect(path) as connection:
        candidates = int(connection.execute("SELECT COUNT(*) FROM forward_observations WHERE run_id=? AND state='ELIGIBLE_RESEARCH_CANDIDATE'", (run_id,)).fetchone()[0])
        _upsert_group_status(connection, run_id, "SHORT_ATM_DAYS_WEEK", state, "FROZEN_FORWARD_PAPER", candidates, int(summary["completed"]), now)
        connection.commit()


def _ledger_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"plans": 0, "open": 0, "completed": 0, "net_results_pending_fees": 0, "by_right": {"CALL": {"completed": 0}, "PUT": {"completed": 0}}}
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        plans = int(connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0])
        rows = connection.execute("SELECT p.*,pl.payload_json plan_json FROM positions p JOIN plans pl ON pl.plan_id=p.plan_id").fetchall()
    by_right = {"CALL": {"completed": 0, "open": 0, "net_r_values": []}, "PUT": {"completed": 0, "open": 0, "net_r_values": []}}
    completed = open_count = pending = 0
    net_rs: list[float] = []
    for row in rows:
        plan = json.loads(row["plan_json"])
        right = str(plan.get("right") or "")
        if row["state"] == "CLOSED":
            completed += 1
            if right in by_right:
                by_right[right]["completed"] += 1
            if row["net_r"] is None:
                pending += 1
            else:
                net_rs.append(float(row["net_r"]))
                if right in by_right:
                    by_right[right]["net_r_values"].append(float(row["net_r"]))
        else:
            open_count += 1
            if right in by_right:
                by_right[right]["open"] += 1
    return {"plans": plans, "open": open_count, "completed": completed, "net_results_pending_fees": pending, "net_r_values": net_rs, "by_right": by_right}


def _ledger_records(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with _connect_readonly(path) as connection:
        rows = connection.execute(
            """
            SELECT
              pl.plan_id,
              pl.state AS plan_state,
              pl.updated_at,
              pl.payload_json AS plan_json,
              p.position_id,
              p.contract_id,
              p.state AS position_state,
              p.quantity,
              p.entry_fill,
              p.entry_fees,
              p.risk_base,
              p.realized_pnl,
              p.net_r,
              p.exit_reason,
              p.updated_at AS position_updated_at
            FROM plans pl
            LEFT JOIN positions p ON p.plan_id=pl.plan_id
            ORDER BY pl.updated_at DESC, pl.plan_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        fill_rows = connection.execute(
            "SELECT plan_id,side,quantity,fill_price,fees,filled_at FROM paper_fills ORDER BY filled_at, paper_fill_id"
        ).fetchall()
    fills_by_plan: dict[str, list[dict[str, Any]]] = {}
    for row in fill_rows:
        fills_by_plan.setdefault(str(row["plan_id"]), []).append(dict(row))
    records: list[dict[str, Any]] = []
    for row in rows:
        plan = json.loads(row["plan_json"])
        records.append(
            {
                "plan_id": row["plan_id"],
                "profile_id": plan.get("profile_id"),
                "symbol": plan.get("symbol"),
                "right": plan.get("right"),
                "contract_symbol": (plan.get("contract") or {}).get("contract_id") or row["contract_id"],
                "plan_state": row["plan_state"],
                "position_state": row["position_state"],
                "quantity": row["quantity"],
                "entry_fill": row["entry_fill"],
                "entry_fees": row["entry_fees"],
                "risk_base": row["risk_base"],
                "realized_pnl": row["realized_pnl"],
                "net_r": row["net_r"],
                "exit_reason": row["exit_reason"],
                "fill_assumption": plan.get("fill_assumption"),
                "evidence_class": "RECEIPT_TIME_QUOTE_PROXY",
                "updated_at": row["position_updated_at"] or row["updated_at"],
                "fills": fills_by_plan.get(str(row["plan_id"]), []),
                "real_order": False,
            }
        )
    return records


def _metric_summary(values: list[float], minimum: int = 200) -> dict[str, Any]:
    if not values:
        return {"completed": 0, "win_rate": None, "payoff": None, "profit_factor": None, "average_net_r": None, "gate_status": "INCONCLUSIVE", "reason": "NO_COMPLETED_FORWARD_PAPER_TRADES"}
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    payoff = (statistics.mean(wins) / abs(statistics.mean(losses))) if wins and losses else None
    pf = gross_win / gross_loss if gross_loss else None
    return {
        "completed": len(values),
        "win_rate": len(wins) / len(values),
        "payoff": payoff,
        "profit_factor": pf,
        "average_net_r": statistics.mean(values),
        "gate_status": "INCONCLUSIVE" if len(values) < minimum else "EVALUATION_REQUIRED",
        "reason": "MINIMUM_SAMPLE_NOT_MET" if len(values) < minimum else "FULL_GATE_REQUIRES_BLOCK_BOOTSTRAP_AND_STRESS_REPLAY",
    }


def forward_status(*, store_path: Path = DEFAULT_DB_PATH, run_id: str = DEFAULT_RUN_ID) -> dict[str, Any]:
    if not store_path.exists():
        return {"status": "NOT_STARTED", "run_id": run_id, "orders_enabled": False, "real_account_enabled": False}
    with _connect_readonly(store_path) as connection:
        run = connection.execute("SELECT * FROM forward_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            return {"status": "NOT_STARTED", "run_id": run_id, "orders_enabled": False, "real_account_enabled": False}
        cycles = [dict(row) for row in connection.execute("SELECT * FROM forward_cycles WHERE run_id=? ORDER BY created_at DESC LIMIT 20", (run_id,))]
        observations = [dict(row) for row in connection.execute("SELECT * FROM forward_observations WHERE run_id=? ORDER BY created_at DESC LIMIT 100", (run_id,))]
        groups = [dict(row) for row in connection.execute("SELECT * FROM forward_group_status WHERE run_id=? ORDER BY profile_id", (run_id,))]
        paused, pause_reason = _new_entries_paused(store_path)
    item = dict(run)
    for key in ("rights_json", "permissions_json", "detail_json"):
        item[key[:-5] if key.endswith("_json") else key] = json.loads(item.pop(key))
    historical_permissions = dict(item["permissions"])
    item["historical_approval_permissions"] = historical_permissions
    item["permissions"] = {
        **historical_permissions,
        "automatic_receipt_proxy_paper_entry": False,
        "manual_owner_confirmation_required": True,
        "legacy_automatic_path_isolated": True,
    }
    for row in cycles:
        row["detail"] = json.loads(row.pop("detail_json"))
    for row in observations:
        row["payload"] = json.loads(row.pop("payload_json"))
    ledger = _ledger_summary(Path(item["ledger_path"]))
    paper_records = _ledger_records(Path(item["ledger_path"]))
    policy = load_forward_policy()
    metrics = {
        right: _metric_summary(list(ledger["by_right"].get(right, {}).get("net_r_values") or []), int(policy["metric_policy"]["minimum_completed_per_profile_right"]))
        for right in policy["scope"]["rights"]
    }
    if ledger["net_r_values"]:
        metrics["COMBINED_DESCRIPTIVE"] = _metric_summary(ledger["net_r_values"], 400)
    return {
        "status": item["status"],
        "run": item,
        "groups": groups,
        "ledger": ledger,
        "paper_records": paper_records,
        "metrics": metrics,
        "cycles": cycles,
        "observations": observations,
        "new_entries_paused": paused,
        "pause_reason": pause_reason,
        "model_status": "NOT_REQUIRED_NO_MODEL_CONSUMED",
        "risk_research": {
            "method": "DETERMINISTIC_ONLY",
            "reference_capital_usd": policy["capital_policy"]["reference_capital_usd"],
            "per_position_premium_cap_usd": policy["capital_policy"]["reference_capital_usd"] * policy["capital_policy"]["per_position_premium_fraction"],
            "total_open_premium_cap_usd": policy["capital_policy"]["reference_capital_usd"] * policy["capital_policy"]["total_open_premium_fraction"],
            "hard_premium_loss_fraction": policy["exit_policy"]["hard_premium_loss_fraction"],
            "monte_carlo_status": "NOT_PREREGISTERED_NOT_RUN",
            "probability_claims": False,
        },
        "evidence_boundary": {
            "execution_evidence": "RECEIPT_TIME_QUOTE_PROXY",
            "native_bbo_event_time_required": False,
            "exchange_fill_claim": False,
            "real_order_path": False,
            "performance_status": "INCONCLUSIVE" if ledger["completed"] < 400 else "EVALUATION_REQUIRED",
        },
        "orders_enabled": False,
        "real_account_enabled": False,
        "automatic_capital_increase": False,
        "legacy_automatic_entry_enabled": False,
    }


def backup_and_verify_forward_store(*, store_path: Path = DEFAULT_DB_PATH, destination: Path | None = None) -> dict[str, Any]:
    initialize_forward_store(store_path)
    target = destination or store_path.parent / "backups" / f"options-forward-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    source = sqlite3.connect(store_path)
    copy = sqlite3.connect(temporary)
    try:
        source.backup(copy)
        copy.commit()
    finally:
        copy.close()
        source.close()
    restored = sqlite3.connect(temporary)
    try:
        integrity = str(restored.execute("PRAGMA integrity_check").fetchone()[0])
        runs = int(restored.execute("SELECT COUNT(*) FROM forward_runs").fetchone()[0])
    finally:
        restored.close()
    if integrity != "ok":
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"forward backup integrity failed: {integrity}")
    temporary.replace(target)
    return {"status": "PASS", "source": str(store_path.resolve()), "backup": str(target.resolve()), "integrity_check": integrity, "run_count": runs, "sha256": _sha256_file(target)}


__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_RUN_ID",
    "ENGINE_VERSION",
    "backup_and_verify_forward_store",
    "cycle_forward_run",
    "forward_status",
    "initialize_forward_store",
    "load_forward_policy",
    "set_new_entries_paused",
    "start_or_resume_forward_run",
]
