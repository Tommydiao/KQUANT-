from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .option_event_coverage import option_event_context
from .options_cbrm_research import live_opening_participation
from .options_expression import option_chain, option_expiries
from .options_paper_engineering import content_hash, evaluate_candidate
from .options_radar import RADAR_UNIVERSE
from .options_forward_paper import load_forward_policy
from .stock_signals import api_stock_candles, api_stock_quotes_batch
from .stock_watchlist import list_stock_watchlist_groups, watchlist_audit
from .options_data_paths import connect_store, resolve_stores
from .policy_availability import PolicyConfigUnavailable, read_policy


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "options_full_watch_research_v1.json"
DEFAULT_STORE_PATH = resolve_stores(REPO_ROOT)["full_watch"]
SCOPE_ID = "FULL_WATCH_RULE_RESEARCH_V1"
ENGINE_VERSION = "options-full-watch-v1.3.0"
NEW_YORK = ZoneInfo("America/New_York")


STORE_SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS full_watch_runs (
  run_id TEXT PRIMARY KEY,
  scope_id TEXT NOT NULL,
  universe_hash TEXT NOT NULL,
  market_date TEXT NOT NULL,
  as_of TEXT NOT NULL,
  status TEXT NOT NULL,
  counts_json TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS full_watch_evaluations (
  run_id TEXT NOT NULL,
  economic_event_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  option_right TEXT NOT NULL,
  is_core INTEGER NOT NULL,
  state TEXT NOT NULL,
  coverage_state TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  quote_json TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  evaluation_json TEXT NOT NULL,
  option_check_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(run_id, symbol, option_right),
  FOREIGN KEY(run_id) REFERENCES full_watch_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_full_watch_eval_latest
ON full_watch_evaluations(run_id, state, symbol, option_right);
CREATE TABLE IF NOT EXISTS full_watch_option_checks (
  check_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  status TEXT NOT NULL,
  expiry_count INTEGER NOT NULL,
  nearest_expiry TEXT,
  chain_row_count INTEGER,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_full_watch_option_checks_symbol
ON full_watch_option_checks(symbol, requested_at DESC);
CREATE TABLE IF NOT EXISTS full_watch_quota_queue (
  symbol TEXT PRIMARY KEY,
  group_rank INTEGER NOT NULL,
  state TEXT NOT NULL,
  reason TEXT NOT NULL,
  last_attempt_at TEXT,
  updated_at TEXT NOT NULL
);
"""


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _config() -> dict[str, Any]:
    payload = read_policy(CONFIG_PATH, capability="full_watch")
    if payload.get("config_id") != SCOPE_ID:
        raise ValueError("FULL_WATCH_CONFIG_ID_MISMATCH")
    return payload


def full_watch_policy_status() -> dict[str, Any]:
    try:
        _config()
    except PolicyConfigUnavailable as exc:
        return exc.status()
    except ValueError:
        return PolicyConfigUnavailable(CONFIG_PATH, "full_watch", "POLICY_CONFIG_INVALID").status()
    return {"current_policy_available": True}


def initialize_full_watch_store(store_path: Path = DEFAULT_STORE_PATH) -> dict[str, Any]:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_store(store_path) as connection:
        connection.executescript(STORE_SCHEMA)
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    return {
        "status": "INITIALIZED",
        "path": str(store_path.resolve()),
        "engine_version": ENGINE_VERSION,
        "integrity_check": integrity,
    }


def _connect(store_path: Path = DEFAULT_STORE_PATH, *, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True)
    else:
        connection = connect_store(store_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def build_universe_manifest(main_db_path: Path) -> dict[str, Any]:
    audit = watchlist_audit(main_db_path)
    groups = list_stock_watchlist_groups(main_db_path).get("groups", [])
    core = set(RADAR_UNIVERSE)
    items: list[dict[str, Any]] = []
    for item in audit.get("items", []):
        symbol = str(item.get("symbol") or "")
        items.append(
            {
                "symbol": symbol,
                "raw_symbols": list(item.get("raw_symbols") or []),
                "groups": list(item.get("groups") or []),
                "provider_symbol": item.get("provider_symbol"),
                "display_name": item.get("display_name"),
                "market": item.get("market"),
                "security_type": item.get("security_type"),
                "identity_status": item.get("identity_status"),
                "identity_reason": item.get("identity_reason"),
                "quote_support_status": item.get("quote_support_status"),
                "history_support_status": item.get("history_support_status"),
                "options_support_status": item.get("options_support_status"),
                "is_core12": symbol in core,
            }
        )
    material = {
        "watchlist_version": audit.get("version"),
        "groups": [{"group_id": row.get("group_id"), "name": row.get("display_name"), "count": row.get("member_count")} for row in groups],
        "items": items,
    }
    universe_hash = _sha(material)
    return {
        "scope_id": SCOPE_ID,
        "universe_hash": universe_hash,
        "source": "stock_watchlist_groups+stock_watchlist_members",
        "group_count": int(audit.get("group_count") or 0),
        "membership_count": int(audit.get("membership_count") or 0),
        "distinct_symbol_count": int(audit.get("distinct_symbol_count") or 0),
        "identity_status_counts": dict(audit.get("identity_status_counts") or {}),
        "core12_count": sum(bool(item["is_core12"]) for item in items),
        "core12_intersection": [item["symbol"] for item in items if item["is_core12"]],
        "full_watch_only_count": sum(not bool(item["is_core12"]) for item in items),
        "groups": material["groups"],
        "items": items,
        "unknown_symbols_preserved": [item["symbol"] for item in items if item["identity_status"] != "verified"],
        "hardcoded_universe_limit": None,
        "generated_at": _now().isoformat(),
    }


def save_universe_manifest(main_db_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = build_universe_manifest(main_db_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**manifest, "artifact_path": str(output_path.resolve()), "artifact_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest()}


def scheduled_probe_symbols(main_db_path: Path, market_date: date, *, maximum: int = 8, store_path: Path = DEFAULT_STORE_PATH) -> list[str]:
    """Choose a bounded, deterministic, group-fair data refresh batch.

    The returned batch limits provider work, never the scan denominator. Every
    watchlist item still receives an evaluation row or an explicit deferred
    state in the same run.
    """

    manifest = build_universe_manifest(main_db_path)
    by_group: dict[str, list[str]] = {}
    all_verified: list[str] = []
    for item in manifest["items"]:
        if item.get("identity_status") != "verified" or not item.get("provider_symbol"):
            continue
        symbol = str(item["symbol"])
        all_verified.append(symbol)
        for group in item.get("groups") or []:
            by_group.setdefault(str(group.get("group_id") or ""), []).append(symbol)
    selected: list[str] = []
    attempted: set[str] = set()
    if store_path.exists():
        with _connect(store_path, read_only=True) as connection:
            attempted = {str(row["symbol"]) for row in connection.execute(
                "SELECT symbol,last_attempt_at FROM full_watch_quota_queue WHERE last_attempt_at IS NOT NULL"
            ) if _local_date(str(row["last_attempt_at"])) == market_date.isoformat()}
    all_verified = [symbol for symbol in all_verified if symbol not in attempted]
    by_group = {group: [symbol for symbol in values if symbol not in attempted] for group, values in by_group.items()}
    if maximum <= 0:
        return []
    ordinal = market_date.toordinal()
    for group_id in sorted(by_group):
        values = sorted(set(by_group[group_id]))
        if not values:
            continue
        symbol = values[ordinal % len(values)]
        if symbol not in selected:
            selected.append(symbol)
        if len(selected) >= maximum:
            return selected
    values = sorted(set(all_verified))
    if values:
        start = ordinal % len(values)
        for offset in range(len(values)):
            symbol = values[(start + offset) % len(values)]
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= maximum:
                break
    return selected


def _deduped_candles(main_db_path: Path, symbol: str, interval: str) -> list[dict[str, Any]]:
    if not main_db_path.exists():
        return []
    with sqlite3.connect(f"file:{main_db_path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT open_time,open,high,low,close,volume,bar_state,primary_source,
                   provider_status,updated_at
            FROM market_candles
            WHERE symbol=? AND interval=?
            ORDER BY open_time,updated_at
            """,
            (symbol, interval),
        ).fetchall()
    by_open: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        if item.get("bar_state") == "closed_candle":
            by_open[str(item["open_time"])] = item
    return [by_open[key] for key in sorted(by_open)]


def _local_date(value: str) -> str | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(NEW_YORK).date().isoformat()
    except (TypeError, ValueError):
        return None


def _local_time(value: str) -> time | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(NEW_YORK).time().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _daily_session_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one closed daily candle per New York session.

    Historical caches can contain the same session at provider-native midnight
    and at a legacy chart timestamp.  Provider-native Longbridge evidence wins;
    the latest update breaks ties within the same source class.
    """

    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        session = _local_date(str(row.get("open_time") or ""))
        if not session:
            continue
        current = selected.get(session)
        score = (
            1 if str(row.get("primary_source") or "") == "longbridge_candles" else 0,
            str(row.get("updated_at") or ""),
        )
        current_score = (
            1 if current and str(current.get("primary_source") or "") == "longbridge_candles" else 0,
            str(current.get("updated_at") or "") if current else "",
        )
        if current is None or score > current_score:
            selected[session] = row
    return [selected[key] for key in sorted(selected)]


def _closed_bar_available_at(value: str, *, minutes: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(minutes=minutes)).astimezone(UTC).isoformat()


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


def _ema(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    alpha = 2.0 / (length + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _latest_opening_pair(rows: Iterable[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        session = _local_date(str(row.get("open_time") or ""))
        opened = _local_time(str(row.get("open_time") or ""))
        if not session or opened not in {time(9, 30), time(9, 35)}:
            continue
        grouped.setdefault(session, {})[opened.strftime("%H:%M")] = row
    for session in sorted(grouped, reverse=True):
        pair = grouped[session]
        if {"09:30", "09:35"}.issubset(pair):
            return session, [pair["09:30"], pair["09:35"]]
    return None, []


def _refresh_opening_bars(main_db_path: Path, symbols: Iterable[str]) -> dict[str, str]:
    results: dict[str, str] = {}
    for symbol in dict.fromkeys(str(value).upper() for value in symbols if value):
        payload = api_stock_candles(symbol, "1d", "5m", "live", main_db_path, allow_reference_fallback=False, background=True)
        results[symbol] = str(payload.get("provider_status") or "unavailable")
    return results


def _reference_snapshot(
    main_db_path: Path,
    symbol: str,
    right: str,
    *,
    universe: list[str],
    as_of: datetime,
    participation_allowed: bool,
) -> dict[str, Any]:
    daily = _daily_session_rows(_deduped_candles(main_db_path, symbol, "1d"))
    intraday = _deduped_candles(main_db_path, symbol, "5m")
    intraday = [row for row in intraday
                if datetime.fromisoformat(_closed_bar_available_at(str(row["open_time"]), minutes=5)) <= as_of]
    spy_daily = daily if symbol == "SPY" else _daily_session_rows(_deduped_candles(main_db_path, "SPY", "1d"))
    session, first_two = _latest_opening_pair(intraday)
    decision = as_of.isoformat()
    missing: list[str] = []
    if not daily:
        missing.append("DAILY_HISTORY_UNAVAILABLE")
    if not session or len(first_two) != 2:
        missing.append("FIRST_TWO_CLOSED_5M_BARS_UNAVAILABLE")
    prior = [row for row in daily if session and (_local_date(str(row["open_time"])) or "") < session][-20:]
    prior_dates = list(dict.fromkeys(_local_date(str(row["open_time"])) for row in prior if _local_date(str(row["open_time"]))))
    if len(prior) < 20:
        missing.append("PRIOR_20_SESSIONS_UNAVAILABLE")
    historical = [row for row in daily if not session or (_local_date(str(row["open_time"])) or "") < session]
    closes = [float(row["close"]) for row in historical if float(row.get("close") or 0) > 0]
    spy_rows = [row for row in spy_daily if not session or (_local_date(str(row["open_time"])) or "") < session]
    spy_closes = [float(row["close"]) for row in spy_rows if float(row.get("close") or 0) > 0]
    compression = _compression_ratio(closes)
    if compression is None:
        missing.append("COMPRESSION_HISTORY_UNAVAILABLE")
    participation: dict[str, Any] = {
        "status": "NOT_REQUESTED",
        "value": None,
        "missing": ["PARTICIPATION_QUERY_DEFERRED"],
    }
    if session and len(prior_dates) == 20:
        try:
            participation = live_opening_participation(
                symbol=symbol,
                session=session,
                prior_sessions=prior_dates,
                as_of=_closed_bar_available_at(str(first_two[-1]["open_time"]), minutes=5),
                refresh=participation_allowed,
            )
        except Exception as exc:  # pragma: no cover - provider dependent
            participation = {"status": "UNAVAILABLE", "value": None, "missing": [type(exc).__name__]}
    if participation.get("status") != "AVAILABLE":
        missing.append(f"SAME_CLOCK_TURNOVER_{participation.get('status') or 'UNAVAILABLE'}")
        if not participation_allowed:
            missing.append("LOCAL_RUN_BUDGET_EXHAUSTED")
    event = option_event_context(main_db_path, symbol, decision, until=(as_of + timedelta(days=7)).isoformat())
    if not event.get("trade_eligible"):
        missing.append("EVENT_COVERAGE_INCOMPLETE_OR_BLOCKED")
    latest_data_time = max((str(row["open_time"]) for row in (first_two or historical[-1:])), default=None)
    current_session = as_of.astimezone(NEW_YORK).date().isoformat()
    if session and session != current_session:
        missing.append("REFERENCE_SESSION_NOT_CURRENT")
    snapshot = {
        "snapshot_id": f"fws_{content_hash({'symbol': symbol, 'right': right, 'session': session, 'as_of': decision})[:24]}",
        "symbol": symbol,
        "right": right,
        "market_session_date": session or current_session,
        "reference_session": session,
        "frozen_universe": universe,
        "all_bars_closed": len(first_two) == 2 and len(prior) == 20,
        "max_input_available_at": decision,
        "snapshot_frozen_at": decision,
        "evaluation_started_at": decision,
        "evaluation_finished_at": decision,
        "decision_committed_at": decision,
        "event_status": "CLEAR" if event.get("trade_eligible") else "UNKNOWN",
        "event_context": event,
        "compression_ratio": compression,
        "opening_participation": participation.get("value"),
        "opening_participation_evidence": participation,
        "first_5m_close": float(first_two[0]["close"]) if first_two else None,
        "second_5m_close": float(first_two[1]["close"]) if first_two else None,
        "prior_range_high": max(float(row["high"]) for row in prior) if prior else None,
        "prior_range_low": min(float(row["low"]) for row in prior) if prior else None,
        "spy_prior_close": spy_closes[-1] if spy_closes else None,
        "spy_ema20": _ema(spy_closes, 20),
        "spy_ema50": _ema(spy_closes, 50),
        "underlying_price": float(first_two[-1]["close"]) if first_two else (closes[-1] if closes else None),
        "data_blockers": sorted(set(missing)),
        "source": "LOCAL_LONG_BRIDGE_CACHE_PLUS_BOUNDED_NATIVE_TURNOVER",
        "latest_data_time": latest_data_time,
        "scope_extrapolation": True,
        "cbrm_consumed": False,
    }
    return snapshot


def _rule_components(snapshot: dict[str, Any], right: str, policy: dict[str, Any]) -> dict[str, Any]:
    candidate = policy["candidate_contract"]
    values = {
        "compression": snapshot.get("compression_ratio"),
        "participation": snapshot.get("opening_participation"),
        "first_close": snapshot.get("first_5m_close"),
        "second_close": snapshot.get("second_5m_close"),
        "range_high": snapshot.get("prior_range_high"),
        "range_low": snapshot.get("prior_range_low"),
        "spy_close": snapshot.get("spy_prior_close"),
        "spy_ema20": snapshot.get("spy_ema20"),
        "spy_ema50": snapshot.get("spy_ema50"),
    }
    compression_pass = None if values["compression"] is None else 0 <= float(values["compression"]) <= float(candidate["compression_ratio_max"])
    participation_pass = None if values["participation"] is None else float(values["participation"]) >= float(candidate["opening_participation_min"])
    range_pass = None
    market_pass = None
    if all(values[key] is not None for key in ("first_close", "second_close", "range_high", "range_low")):
        if right == "CALL":
            range_pass = float(values["first_close"]) > float(values["range_high"]) and float(values["second_close"]) > float(values["range_high"])
        else:
            range_pass = float(values["first_close"]) < float(values["range_low"]) and float(values["second_close"]) < float(values["range_low"])
    if all(values[key] is not None for key in ("spy_close", "spy_ema20", "spy_ema50")):
        market_pass = float(values["spy_close"]) >= float(values["spy_ema50"]) if right == "CALL" else float(values["spy_close"]) < float(values["spy_ema20"])
    return {
        "values": values,
        "compression_pass": compression_pass,
        "participation_pass": participation_pass,
        "range_confirmation_pass": range_pass,
        "market_confirmation_pass": market_pass,
        "event_gate": snapshot.get("event_status"),
        "all_required_available": not bool(snapshot.get("data_blockers")),
    }


def run_full_watch_scan(
    main_db_path: Path,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    now: datetime | None = None,
    live_probe_symbols: Iterable[str] = (),
) -> dict[str, Any]:
    current = _now(now)
    config = _config()
    initialize_full_watch_store(store_path)
    manifest = build_universe_manifest(main_db_path)
    symbols = [str(item["symbol"]) for item in manifest["items"]]
    verified = [str(item["symbol"]) for item in manifest["items"] if item.get("identity_status") == "verified" and item.get("provider_symbol")]
    probe_symbols = [symbol for symbol in dict.fromkeys(str(value).upper() for value in live_probe_symbols) if symbol in verified]
    refresh_results = _refresh_opening_bars(main_db_path, probe_symbols) if probe_symbols else {}
    quotes = api_stock_quotes_batch(verified, db_path=main_db_path)
    quote_by_symbol = {str(item.get("symbol") or ""): item for item in quotes.get("items", [])}
    policy = load_forward_policy()
    config_hash = _sha(config)
    run_material = {
        "scope": SCOPE_ID,
        "universe": manifest["universe_hash"],
        "as_of": current.isoformat(),
        "config": config_hash,
    }
    run_id = f"fwr_{content_hash(run_material)[:24]}"
    counts = {
        "symbols_total": len(symbols),
        "rights_total": len(symbols) * len(config["rights"]),
        "pass": 0,
        "fail": 0,
        "unknown": 0,
        "quota_deferred": 0,
        "identity_unconfirmed_symbols": 0,
        "quote_available_symbols": 0,
        "shared_snapshot_symbols": 0,
        "complete_rule_calculations": 0,
        "refresh_attempted_symbols": len(probe_symbols),
        "current_complete_rule_calculations": 0,
        "missed_evaluation_window": 0,
        "core12_symbols": int(manifest["core12_count"]),
        "full_watch_only_symbols": int(manifest["full_watch_only_count"]),
    }
    now_text = current.isoformat()
    planned_at = datetime.combine(current.astimezone(NEW_YORK).date(), time(9, 40), tzinfo=NEW_YORK).astimezone(UTC)
    deadline_at = planned_at + timedelta(minutes=5)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    item_by_symbol = {str(item["symbol"]): item for item in manifest["items"]}
    for rank, symbol in enumerate(symbols):
        identity = item_by_symbol[symbol]
        quote = quote_by_symbol.get(symbol) or {
            "symbol": symbol,
            "provider_status": "not_requested" if not identity.get("provider_symbol") else "unavailable",
            "status_reason": identity.get("identity_reason") or "provider_returned_no_row",
        }
        if quote.get("provider_status") == "available":
            counts["quote_available_symbols"] += 1
        if identity.get("identity_status") != "verified":
            counts["identity_unconfirmed_symbols"] += 1
        shared_snapshot = None
        if identity.get("identity_status") == "verified":
            shared_snapshot = _reference_snapshot(
                main_db_path, symbol, "CALL", universe=symbols, as_of=current,
                participation_allowed=symbol in probe_symbols,
            )
            counts["shared_snapshot_symbols"] += 1
        for right in config["rights"]:
            if identity.get("identity_status") != "verified":
                snapshot = {
                    "snapshot_id": f"fws_{content_hash({'symbol': symbol, 'right': right, 'identity': identity.get('identity_reason')})[:24]}",
                    "symbol": symbol,
                    "right": right,
                    "market_session_date": current.astimezone(NEW_YORK).date().isoformat(),
                    "frozen_universe": symbols,
                    "data_blockers": ["IDENTITY_UNCONFIRMED"],
                    "identity": identity,
                    "scope_extrapolation": True,
                    "cbrm_consumed": False,
                }
                evaluation = {
                    "economic_opportunity_id": f"oop_{content_hash({'policy_id': policy['policy_id'], 'symbol': symbol, 'right': right, 'session': snapshot['market_session_date']})[:24]}",
                    "state": "DATA_BLOCKED",
                    "reasons": ["IDENTITY_UNCONFIRMED"],
                    "symbol": symbol,
                    "right": right,
                }
                coverage_state = "UNKNOWN_IDENTITY"
            else:
                snapshot = {**shared_snapshot, "right": right,
                            "snapshot_id": f"fws_{content_hash({'symbol': symbol, 'right': right, 'as_of': now_text})[:24]}"}
                evaluation = evaluate_candidate(snapshot, policy=policy, seen_opportunities=seen)
                if snapshot.get("data_blockers"):
                    evaluation["state"] = "DATA_BLOCKED"
                    evaluation["reasons"] = sorted(set(evaluation.get("reasons") or []) | set(snapshot["data_blockers"]))
                evaluation["rule_components"] = _rule_components(snapshot, right, policy)
                numeric_complete = all(evaluation["rule_components"][key] is not None for key in (
                    "compression_pass", "participation_pass", "range_confirmation_pass", "market_confirmation_pass"
                ))
                finished_at = _now()
                current_data = snapshot.get("reference_session") == current.astimezone(NEW_YORK).date().isoformat()
                evaluation["timing"] = {
                    "planned_at": planned_at.isoformat(), "deadline_at": deadline_at.isoformat(),
                    "evaluation_finished_at": finished_at.isoformat(),
                    "planned_to_finished_seconds": (finished_at - planned_at).total_seconds(),
                    "data_session_is_current": current_data,
                    "missed_evaluation_window": finished_at > deadline_at,
                    "deadline_is_engineering_target_not_strategy_extension": True,
                }
                if numeric_complete:
                    counts["complete_rule_calculations"] += 1
                    if current_data:
                        counts["current_complete_rule_calculations"] += 1
                if finished_at > deadline_at:
                    counts["missed_evaluation_window"] += 1
                if evaluation["state"] == "ELIGIBLE_RESEARCH_CANDIDATE":
                    coverage_state = "PASS"
                elif any("DEFERRED" in reason or reason == "LOCAL_RUN_BUDGET_EXHAUSTED" for reason in evaluation.get("reasons") or []):
                    coverage_state = "QUOTA_DEFERRED"
                elif evaluation["state"] == "DATA_BLOCKED":
                    coverage_state = "UNKNOWN"
                else:
                    coverage_state = "FAIL"
            counts[coverage_state.lower() if coverage_state.lower() in counts else "unknown"] += 1
            rows.append(
                {
                    "run_id": run_id,
                    "economic_event_id": evaluation["economic_opportunity_id"],
                    "symbol": symbol,
                    "right": right,
                    "is_core12": bool(identity.get("is_core12")),
                    "state": evaluation["state"],
                    "coverage_state": coverage_state,
                    "reasons": list(evaluation.get("reasons") or []),
                    "quote": quote,
                    "snapshot": snapshot,
                    "evaluation": evaluation,
                    "option_check_status": "OPTION_CHECK_NOT_REQUESTED",
                    "created_at": now_text,
                }
            )
    status = "RUN_FINISHED_WITH_GAPS" if counts["unknown"] or counts["quota_deferred"] else "COMPLETE"
    with _connect(store_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO full_watch_runs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                SCOPE_ID,
                manifest["universe_hash"],
                current.astimezone(NEW_YORK).date().isoformat(),
                now_text,
                status,
                _json(counts),
                _json(manifest),
                config_hash,
                now_text,
            ),
        )
        for item in rows:
            connection.execute(
                "INSERT INTO full_watch_evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    item["economic_event_id"],
                    item["symbol"],
                    item["right"],
                    int(item["is_core12"]),
                    item["state"],
                    item["coverage_state"],
                    _json(item["reasons"]),
                    _json(item["quote"]),
                    _json(item["snapshot"]),
                    _json(item["evaluation"]),
                    item["option_check_status"],
                    now_text,
                ),
            )
        for rank, symbol in enumerate(symbols):
            state = "PROBED" if symbol in probe_symbols else ("IDENTITY_UNCONFIRMED" if item_by_symbol[symbol].get("identity_status") != "verified" else "QUOTA_DEFERRED")
            reason = refresh_results.get(symbol) or ("IDENTITY_UNCONFIRMED" if state == "IDENTITY_UNCONFIRMED" else "LOCAL_RUN_BUDGET_EXHAUSTED")
            connection.execute(
                """INSERT INTO full_watch_quota_queue VALUES (?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET group_rank=excluded.group_rank,state=excluded.state,
                  reason=excluded.reason,last_attempt_at=COALESCE(excluded.last_attempt_at,full_watch_quota_queue.last_attempt_at),updated_at=excluded.updated_at""",
                (symbol, rank, state, reason, now_text if symbol in probe_symbols else None, now_text),
            )
        connection.commit()
    return full_watch_status(store_path=store_path, run_id=run_id)


def check_full_watch_options(
    symbol: str,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    include_chain_sample: bool = True,
) -> dict[str, Any]:
    _config()  # Reject absent policy before a store write or provider request.
    initialize_full_watch_store(store_path)
    normalized = symbol.strip().upper()
    requested = _now()
    requested_at = requested.isoformat()
    expiries = option_expiries(normalized)
    raw_values = [str(value) for value in expiries.get("expiries") or []]
    market_date = requested.astimezone(NEW_YORK).date()
    values: list[str] = []
    expired_values: list[str] = []
    for value in raw_values:
        try:
            expiry_date = date.fromisoformat(value)
        except ValueError:
            continue
        if expiry_date < market_date:
            expired_values.append(value)
        else:
            values.append(value)
    values = sorted(set(values))
    nearest = values[0] if values else None
    chain_rows: list[dict[str, Any]] = []
    status = "AVAILABLE" if nearest else "UNAVAILABLE"
    error = None
    chain: dict[str, Any] = {}
    if nearest and include_chain_sample:
        try:
            chain = option_chain(normalized, nearest)
            chain_rows = list(chain.get("contracts") or chain.get("items") or [])
            if not chain_rows or chain.get("provider_status") in {"unavailable", "missing_config", "error"}:
                status = "PARTIAL"
                error = "CHAIN_REQUEST_FAILED" if chain.get("provider_errors") else "CHAIN_EMPTY"
        except Exception as exc:  # pragma: no cover - provider dependent
            status = "PARTIAL"
            error = type(exc).__name__
    payload = {
        "symbol": normalized,
        "status": status,
        "requested_at": requested_at,
        "received_at": _now().isoformat(),
        "expiry_provider_status": expiries.get("provider_status", "unknown"),
        "chain_provider_status": chain.get("provider_status", "not_requested"),
        "expiry_provider_error_count": len(expiries.get("provider_errors") or []),
        "chain_provider_error_count": len(chain.get("provider_errors") or []),
        "expiry_count": len(values),
        "expired_expiry_count": len(expired_values),
        "nearest_expiry": nearest,
        "chain_row_count": len(chain_rows) if include_chain_sample else None,
        "expiries": values,
        "chain_sample_requested": include_chain_sample,
        "error_type": error,
        "research_only": True,
        "contract_selected": False,
        "signal_generated": False,
        "paper_created": False,
        "real_order_created": False,
    }
    check_id = f"fwo_{content_hash(payload)[:24]}"
    with _connect(store_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO full_watch_option_checks VALUES (?,?,?,?,?,?,?,?,?)",
            (check_id, normalized, requested_at, status, len(values), nearest, payload["chain_row_count"], _json(payload), requested_at),
        )
        latest = connection.execute("SELECT run_id FROM full_watch_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if latest:
            connection.execute(
                "UPDATE full_watch_evaluations SET option_check_status=? WHERE run_id=? AND symbol=?",
                (status, latest["run_id"], normalized),
            )
        connection.commit()
    return payload


def full_watch_status(
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    run_id: str | None = None,
    scope: str = "full",
    state: str = "",
    query: str = "",
) -> dict[str, Any]:
    try:
        config = _config()
    except PolicyConfigUnavailable as exc:
        return {**exc.status(), "scope_id": SCOPE_ID, "engine_version": ENGINE_VERSION,
                "signals_generated": False, "evaluations": [],
                "evaluation_records_complete": False}
    if not store_path.exists():
        return {
            "status": "NOT_STARTED",
            "scope_id": SCOPE_ID,
            "signals_generated": False,
            "paper_enabled": False,
            "real_orders_enabled": False,
            "evaluations": [],
        }
    with _connect(store_path, read_only=True) as connection:
        run = connection.execute(
            "SELECT * FROM full_watch_runs WHERE run_id=?" if run_id else "SELECT * FROM full_watch_runs ORDER BY created_at DESC LIMIT 1",
            (run_id,) if run_id else (),
        ).fetchone()
        if not run:
            return {"status": "NOT_STARTED", "scope_id": SCOPE_ID, "evaluations": []}
        clauses = ["run_id=?"]
        values: list[Any] = [run["run_id"]]
        if scope.lower() == "core":
            clauses.append("is_core=1")
        if state:
            clauses.append("coverage_state=?")
            values.append(state.upper())
        if query.strip():
            clauses.append("symbol LIKE ?")
            values.append(f"%{query.strip().upper()}%")
        evaluations = [dict(row) for row in connection.execute(
            f"SELECT * FROM full_watch_evaluations WHERE {' AND '.join(clauses)} ORDER BY symbol,option_right",
            values,
        ).fetchall()]
        option_checks = [dict(row) for row in connection.execute(
            "SELECT * FROM full_watch_option_checks ORDER BY requested_at DESC LIMIT 100"
        ).fetchall()]
        queue = [dict(row) for row in connection.execute(
            "SELECT * FROM full_watch_quota_queue ORDER BY group_rank,symbol"
        ).fetchall()]
    for item in evaluations:
        for key in ("reasons_json", "quote_json", "snapshot_json", "evaluation_json"):
            item[key[:-5]] = json.loads(item.pop(key))
        item["is_core12"] = bool(item.pop("is_core"))
    for item in option_checks:
        item["payload"] = json.loads(item.pop("payload_json"))
    run_item = dict(run)
    run_item["counts"] = json.loads(run_item.pop("counts_json"))
    run_item["manifest"] = json.loads(run_item.pop("manifest_json"))
    return {
        "status": run_item["status"],
        "current_policy_available": True,
        "scope_id": SCOPE_ID,
        "engine_version": ENGINE_VERSION,
        "run": run_item,
        "display_scope": scope.lower(),
        "returned_evaluation_count": len(evaluations),
        "evaluations": evaluations,
        "option_checks": option_checks,
        "quota_queue": queue,
        "research_boundary": {
            "scope_extrapolation": True,
            "core12_historical_benchmark_only": True,
            "cbrm_consumed": False,
            "signals_generated": False,
            "paper_scope_approved": bool(config["paper_scope_approved"]),
            "automatic_paper_enabled": False,
            "real_orders_enabled": False,
            "performance_status": "NOT_EVALUATED_FULL_WATCH",
        },
    }


__all__ = [
    "DEFAULT_STORE_PATH",
    "ENGINE_VERSION",
    "SCOPE_ID",
    "build_universe_manifest",
    "check_full_watch_options",
    "full_watch_status",
    "initialize_full_watch_store",
    "run_full_watch_scan",
    "scheduled_probe_symbols",
    "save_universe_manifest",
]
