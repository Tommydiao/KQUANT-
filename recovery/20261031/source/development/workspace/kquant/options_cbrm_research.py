"""Isolated DEV_ONLY data and event pipeline for CBRM V0.2.

The module deliberately has no runtime strategy consumer.  Historical 5 minute
bars live in a separate database and every output is tagged as an underlying
proxy, never option PnL.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime, time as wall_time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from .local_env import load_market_data_env
from .longbridge_provider import longbridge_runtime
from .options_conditional_model import fit_development
from .options_breakout_math import opening_participation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "options_conditional_breakout_research_v0_2.json"
DEFAULT_STORE = ROOT / "work" / "cbrm_v0_2" / "cbrm.sqlite3"
DEFAULT_DAILY_STORE = ROOT / "work" / "options_review_r1" / "options_review_r1.sqlite3"
DEFAULT_OUTPUT = ROOT / "outputs" / "cbrm_v0_2"
DEFAULT_AUDIT_RESULT = DEFAULT_OUTPUT / "cbrm-audit-v0-2-1-20260921-01" / "audit.json"
DAILY_BUNDLE = "options-r1-20260920-02"
PROVIDER_MINUTE_START = date(2023, 9, 1)
NY = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")
VERSION = "cbrm-research-v0.2.1-audit"


SCHEMA = """
CREATE TABLE IF NOT EXISTS research_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS minute_requests (
  request_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  request_started_at TEXT NOT NULL,
  received_at TEXT,
  error_code TEXT,
  response_hash TEXT
);
CREATE TABLE IF NOT EXISTS minute_bars (
  symbol TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  session_date TEXT NOT NULL,
  time_et TEXT NOT NULL,
  source_timestamp TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  turnover REAL,
  turnover_currency TEXT,
  turnover_source TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  availability_at TEXT NOT NULL,
  request_id TEXT NOT NULL,
  lineage_hash TEXT NOT NULL,
  PRIMARY KEY(symbol, timestamp_utc)
);
CREATE INDEX IF NOT EXISTS idx_cbrm_bars_session ON minute_bars(symbol, session_date, time_et);
CREATE TABLE IF NOT EXISTS breakout_events (
  run_id TEXT NOT NULL,
  economic_event_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  right TEXT NOT NULL,
  session_date TEXT NOT NULL,
  signal_at TEXT NOT NULL,
  reference_entry_at TEXT,
  horizon_end TEXT,
  label_available_at TEXT,
  state TEXT NOT NULL,
  c_state TEXT NOT NULL,
  v_state TEXT NOT NULL,
  f0_state TEXT NOT NULL,
  f1_state TEXT NOT NULL,
  f2_state TEXT NOT NULL,
  F INTEGER,
  Y REAL,
  payload_json TEXT NOT NULL,
  lineage_hash TEXT NOT NULL,
  PRIMARY KEY(run_id, economic_event_id)
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_protocol(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def initialize_store(path: Path = DEFAULT_STORE) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO research_meta VALUES (?,?,?)",
            ("schema_version", canonical(1), utc_now()),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"path": str(path.resolve()), "integrity_check": integrity, "version": VERSION}


def _chunks(start: date, end: date, days: int = 12) -> Iterable[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=days - 1))
        yield cursor, stop
        cursor = stop + timedelta(days=1)


def _provider_timestamp(value: datetime) -> tuple[datetime, datetime]:
    # Longbridge SDK 4.4.1 renders its UTC wire timestamp as a naive local
    # Asia/Shanghai datetime in this environment. Preserve the raw value and
    # make the conversion explicit rather than pretending it is UTC.
    aware = value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value
    utc_value = aware.astimezone(UTC)
    return utc_value, utc_value.astimezone(NY)


def fetch_minute_history(
    *,
    protocol: dict[str, Any],
    store_path: Path = DEFAULT_STORE,
    start: date | None = None,
    end: date | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """Resume bounded Longbridge ForwardAdjust 5m collection."""
    from longbridge.openapi import AdjustType, Period  # type: ignore

    initialize_store(store_path)
    load_market_data_env()
    requested_start = start or date.fromisoformat(protocol["data"]["start"])
    requested_end = end or date.fromisoformat(protocol["data"]["end"])
    effective_start = max(requested_start, PROVIDER_MINUTE_START)
    symbols = list(protocol["data"]["universe"])
    summary: dict[str, Any] = {
        "requested_start": requested_start.isoformat(),
        "provider_minute_start": PROVIDER_MINUTE_START.isoformat(),
        "effective_start": effective_start.isoformat(),
        "end": requested_end.isoformat(),
        "symbols": {},
        "adjustment_mode": "ForwardAdjust",
        "turnover": "NATIVE_USD",
    }
    runtime = longbridge_runtime()
    with sqlite3.connect(store_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        for symbol in symbols:
            completed = failed = inserted = requests = 0
            for begin, finish in _chunks(effective_start, requested_end):
                request_id = f"m5_{digest([symbol, begin.isoformat(), finish.isoformat(), 'ForwardAdjust'])[:24]}"
                existing = connection.execute(
                    "SELECT status,row_count FROM minute_requests WHERE request_id=?", (request_id,)
                ).fetchone()
                if existing and existing[0] == "COMPLETE":
                    completed += 1
                    continue
                requests += 1
                started = utc_now()
                error: Exception | None = None
                rows = []
                for attempt in range(retries + 1):
                    try:
                        rows = runtime.history_candlesticks_by_date(
                            f"{symbol}.US", Period.Min_5, AdjustType.ForwardAdjust, begin, finish, 30
                        )
                        error = None
                        break
                    except Exception as exc:  # provider evidence is recorded below
                        error = exc
                        if attempt < retries:
                            time.sleep(0.5 * (attempt + 1))
                received = utc_now()
                if error is not None:
                    failed += 1
                    connection.execute(
                        "INSERT OR REPLACE INTO minute_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (request_id, symbol, begin.isoformat(), finish.isoformat(), "ForwardAdjust", "FAILED", 0,
                         started, received, type(error).__name__ + ":" + str(error)[:500], None),
                    )
                    connection.commit()
                    continue
                normalized = []
                for row in rows:
                    ts = getattr(row, "timestamp", None)
                    if not isinstance(ts, datetime):
                        continue
                    ts_utc, ts_ny = _provider_timestamp(ts)
                    if ts_ny.time() < wall_time(9, 30) or ts_ny.time() > wall_time(15, 55):
                        continue
                    values = {
                        key: float(getattr(row, key)) for key in ("open", "high", "low", "close", "volume")
                    }
                    turnover_raw = getattr(row, "turnover", None)
                    turnover = None if turnover_raw is None else float(turnover_raw)
                    if not all(math.isfinite(v) for v in values.values()) or min(values[k] for k in ("open", "high", "low", "close")) <= 0:
                        continue
                    if turnover is not None and (not math.isfinite(turnover) or turnover < 0):
                        turnover = None
                    row_payload = {
                        "symbol": symbol,
                        "timestamp_utc": ts_utc.isoformat(),
                        "session_date": ts_ny.date().isoformat(),
                        "time_et": ts_ny.strftime("%H:%M"),
                        "source_timestamp": str(ts),
                        **values,
                        "turnover": turnover,
                    }
                    normalized.append(row_payload)
                response_hash = digest(normalized)
                connection.executemany(
                    """INSERT OR REPLACE INTO minute_bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [
                        (r["symbol"], r["timestamp_utc"], r["session_date"], r["time_et"], r["source_timestamp"],
                         r["open"], r["high"], r["low"], r["close"], r["volume"], r["turnover"],
                         "USD" if r["turnover"] is not None else None, "NATIVE", "ForwardAdjust",
                         (datetime.fromisoformat(r["timestamp_utc"]) + timedelta(minutes=5)).isoformat(), request_id,
                         digest([request_id, r]))
                        for r in normalized
                    ],
                )
                connection.execute(
                    "INSERT OR REPLACE INTO minute_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (request_id, symbol, begin.isoformat(), finish.isoformat(), "ForwardAdjust", "COMPLETE",
                     len(normalized), started, received, None, response_hash),
                )
                connection.commit()
                completed += 1
                inserted += len(normalized)
            count, first_day, last_day = connection.execute(
                "SELECT COUNT(*),MIN(session_date),MAX(session_date) FROM minute_bars WHERE symbol=?", (symbol,)
            ).fetchone()
            summary["symbols"][symbol] = {
                "completed_chunks": completed,
                "new_requests": requests,
                "failed_chunks": failed,
                "new_rows_seen": inserted,
                "stored_rows": count,
                "first_session": first_day,
                "last_session": last_day,
            }
            print(canonical({"symbol": symbol, **summary["symbols"][symbol]}), flush=True)
        connection.execute(
            "INSERT OR REPLACE INTO research_meta VALUES (?,?,?)",
            ("last_fetch", canonical(summary), utc_now()),
        )
        connection.commit()
    return summary


def live_opening_participation(
    *,
    symbol: str,
    session: str,
    prior_sessions: list[str],
    as_of: str,
    store_path: Path = DEFAULT_STORE,
    refresh: bool = True,
) -> dict[str, Any]:
    """Bounded, resumable native-turnover input for the frozen evaluator."""
    if len(prior_sessions) != 20:
        return {"status": "PARTIAL_HISTORY", "value": None, "missing": ["EXACT_PRECEDING_20_CALENDAR_SESSIONS_REQUIRED"],
                "formula_version": "opening-turnover-v0.2", "symbol": symbol, "session": session}
    protocol = load_protocol()
    protocol = {**protocol, "data": {**protocol["data"], "universe": [symbol.upper()]}}
    if refresh:
        fetch_minute_history(
            protocol=protocol,
            store_path=store_path,
            start=date.fromisoformat(prior_sessions[0]),
            end=date.fromisoformat(session),
        )
    if not store_path.exists():
        return {"status": "CACHE_MISSING", "value": None, "missing": ["TURNOVER_STORE_UNAVAILABLE"]}
    required = [*prior_sessions, session]
    placeholders = ",".join("?" for _ in required)
    connection = sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        f"""SELECT symbol,timestamp_utc,availability_at,turnover,turnover_source,turnover_currency,time_et,session_date
              FROM minute_bars
             WHERE symbol=? AND session_date IN ({placeholders}) AND time_et IN ('09:30','09:35')""",
        [symbol.upper(), *required],
    ).fetchall()
    connection.close()
    normalized = [
        {"symbol": row["symbol"], "open_time": row["timestamp_utc"], "available_at": row["availability_at"],
         "turnover": row["turnover"], "turnover_source": row["turnover_source"], "currency": row["turnover_currency"],
         "interval": "5m"} for row in rows
    ]
    result = opening_participation(
        normalized, session=session, prior_sessions=prior_sessions, as_of=as_of, symbol=symbol.upper()
    )
    result["store"] = str(store_path.resolve())
    result["provider_adjustment"] = "ForwardAdjust"
    result["historical_availability"] = "BAR_END_PROXY"
    return result


def _daily_rows(path: Path, symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    placeholders = ",".join("?" for _ in symbols)
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        f"""SELECT symbol,market_date,source_timestamp,open,high,low,close,volume,turnover,lineage_hash
              FROM adjusted_daily_bars
             WHERE bundle_id=? AND adjustment_mode='FORWARD_ADJUST' AND symbol IN ({placeholders})
             ORDER BY symbol,market_date""",
        [DAILY_BUNDLE, *symbols],
    ).fetchall()
    connection.close()
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[row["symbol"]].append(dict(row))
    return result


def _minute_rows(path: Path, symbols: list[str]) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    placeholders = ",".join("?" for _ in symbols)
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        f"SELECT * FROM minute_bars WHERE symbol IN ({placeholders}) ORDER BY symbol,timestamp_utc", symbols
    ).fetchall()
    connection.close()
    result: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        item = dict(row)
        result[item["symbol"]][item["session_date"]][item["time_et"]] = item
    return result


def _std(values: list[float]) -> float | None:
    if len(values) < 2 or not all(math.isfinite(value) for value in values):
        return None
    return statistics.pstdev(values)


def _ema(values: list[float], span: int) -> float | None:
    if len(values) < span:
        return None
    alpha = 2.0 / (span + 1.0)
    value = statistics.mean(values[:span])
    for item in values[span:]:
        value = alpha * item + (1.0 - alpha) * value
    return value


def _daily_features(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    closes = [float(row["close"]) for row in rows]
    returns = [None] + [math.log(closes[i] / closes[i - 1]) for i in range(1, len(rows))]
    rv20: dict[int, float] = {}
    for i in range(20, len(rows)):
        value = _std([float(x) for x in returns[i - 19:i + 1] if x is not None])
        if value is not None:
            rv20[i] = value
    tr: list[float | None] = [None]
    for i in range(1, len(rows)):
        high, low, prev_close = float(rows[i]["high"]), float(rows[i]["low"]), closes[i - 1]
        tr.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    for i, row in enumerate(rows):
        item: dict[str, Any] = {"index": i, "date": row["market_date"]}
        if i >= 20:
            prior = rows[i - 20:i]
            item.update(
                breakout_high=max(float(value["high"]) for value in prior),
                breakout_low=min(float(value["low"]) for value in prior),
                previous_close=closes[i - 1],
            )
            valid_tr = [float(value) for value in tr[i - 13:i + 1] if value is not None]
            item["atr14"] = statistics.mean(valid_tr) if len(valid_tr) == 14 else None
        else:
            item.update(breakout_high=None, breakout_low=None, previous_close=None, atr14=None)
        numerator = rv20.get(i - 1)
        history = [rv20[j] for j in range(max(20, i - 253), i - 1) if j in rv20]
        item["compression"] = numerator / statistics.median(history) if numerator is not None and len(history) == 252 and statistics.median(history) > 0 else None
        item["source_lineage_hash"] = row["lineage_hash"]
        features[row["market_date"]] = item
    return features


def _complete_session(bars: dict[str, dict[str, Any]]) -> bool:
    if "09:30" not in bars:
        return False
    times = sorted(datetime.strptime(key, "%H:%M") for key in bars)
    return all((times[i] - times[i - 1]) == timedelta(minutes=5) for i in range(1, len(times)))


def _thirty_minute_closes(
    sessions: list[str],
    all_bars: dict[str, dict[str, dict[str, Any]]],
    event_session: str,
    horizon_session: str,
) -> tuple[list[dict[str, Any]], str | None]:
    result: list[dict[str, Any]] = []
    for session in sessions:
        if session < event_session or session > horizon_session:
            continue
        bars = all_bars.get(session, {})
        if not _complete_session(bars):
            return [], f"INCOMPLETE_PATH_{session}"
        keys = sorted(bars)
        for offset in range(0, len(keys), 6):
            bucket = keys[offset:offset + 6]
            if len(bucket) != 6:
                continue
            start = bucket[0]
            if session == event_session and start < "10:00":
                continue
            last = bars[bucket[-1]]
            completed_at = datetime.fromisoformat(last["timestamp_utc"]) + timedelta(minutes=5)
            result.append({"session": session, "start_et": start, "completed_at": completed_at.isoformat(), "close": float(last["close"])})
    return result, None


def _label_event(
    *, event: dict[str, Any], sessions: list[str], session_index: int,
    bars: dict[str, dict[str, dict[str, Any]]], horizon_days: int,
) -> dict[str, Any]:
    horizon_index = session_index + horizon_days - 1
    if horizon_index >= len(sessions):
        return {"state": "LABEL_NOT_MATURE", "reason": "HORIZON_AFTER_DATA_END"}
    event_session = event["session"]
    horizon_session = sessions[horizon_index]
    entry = bars.get(event_session, {}).get("09:45")
    bar_0940 = bars.get(event_session, {}).get("09:40")
    if entry is None or bar_0940 is None:
        return {"state": "CENSORED", "reason": "MISSING_REFERENCE_ENTRY_BAR"}
    level = float(event["level"])
    right = event["right"]
    entry_price = float(entry["open"])
    pre_close = float(bar_0940["close"])
    cancelled_at_t0 = (right == "CALL" and min(entry_price, pre_close) < level) or (right == "PUT" and max(entry_price, pre_close) > level)
    if cancelled_at_t0:
        return {
            "state": "CANCELLED_AT_T0", "reason": "FIVE_MINUTE_RECONFIRMATION_FAILED_AT_REFERENCE_ENTRY",
            "reference_entry_at": entry["timestamp_utc"], "reference_entry_price": entry_price,
            "reconfirmation_bar_start": bar_0940["timestamp_utc"],
            "reconfirmation_available_at": (
                datetime.fromisoformat(bar_0940["timestamp_utc"]) + timedelta(minutes=5)
            ).isoformat(),
            "reconfirmation_close": pre_close,
            "not_a_30m_label_invalidation": True,
        }
    path_sessions = sessions[session_index:horizon_index + 1]
    observations, error = _thirty_minute_closes(path_sessions, bars, event_session, horizon_session)
    if error:
        return {"state": "CENSORED", "reason": error, "reference_entry_at": entry["timestamp_utc"], "reference_entry_price": entry_price}
    horizon_candidates = [row for row in observations if row["session"] == horizon_session and row["start_et"] <= "15:00"]
    if not horizon_candidates:
        return {"state": "CENSORED", "reason": "MISSING_HORIZON_OBSERVATION", "reference_entry_at": entry["timestamp_utc"], "reference_entry_price": entry_price}
    horizon = horizon_candidates[-1]
    horizon_at = datetime.fromisoformat(horizon["completed_at"])
    invalidation = None
    for row in observations:
        at = datetime.fromisoformat(row["completed_at"])
        if at >= horizon_at:
            continue
        crossed = (right == "CALL" and row["close"] < level) or (right == "PUT" and row["close"] > level)
        if crossed:
            invalidation = row
            break
    stop = invalidation or horizon
    direction = 1.0 if right == "CALL" else -1.0
    atr = float(event["features"]["atr14"])
    y = direction * (float(stop["close"]) - entry_price) / atr
    return {
        "state": "MATURE", "reason": None,
        "reference_entry_at": entry["timestamp_utc"], "reference_entry_price": entry_price,
        "horizon_end": horizon["completed_at"], "label_available_at": stop["completed_at"],
        "stop_kind": "INVALIDATION" if invalidation else "HORIZON",
        "stop_price": float(stop["close"]), "F": 1 if invalidation else 0, "Y": y,
        "simple_directional_return": direction * (float(stop["close"]) / entry_price - 1.0),
    }


def build_events(
    *, protocol: dict[str, Any], run_id: str, store_path: Path = DEFAULT_STORE,
    daily_store: Path = DEFAULT_DAILY_STORE,
) -> dict[str, Any]:
    initialize_store(store_path)
    symbols = list(protocol["data"]["universe"])
    daily = _daily_rows(daily_store, symbols)
    minute = _minute_rows(store_path, symbols)
    daily_features = {symbol: _daily_features(rows) for symbol, rows in daily.items()}
    daily_by_date = {symbol: {row["market_date"]: row for row in rows} for symbol, rows in daily.items()}
    sessions_by_symbol = {symbol: [row["market_date"] for row in rows] for symbol, rows in daily.items()}
    spy_closes = [float(row["close"]) for row in daily.get("SPY", [])]
    spy_dates = [row["market_date"] for row in daily.get("SPY", [])]
    spy_index = {day: index for index, day in enumerate(spy_dates)}
    start = max(PROVIDER_MINUTE_START, date.fromisoformat(protocol["data"]["start"])).isoformat()
    end = date.fromisoformat(protocol["data"]["end"]).isoformat()
    events: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for symbol in symbols:
        symbol_events = base_dates = opening_complete = 0
        sessions = sessions_by_symbol.get(symbol, [])
        index_by_session = {day: index for index, day in enumerate(sessions)}
        for session in sessions:
            if session < start or session > end or session not in minute.get(symbol, {}):
                continue
            idx = index_by_session[session]
            bars = minute[symbol][session]
            first, second = bars.get("09:30"), bars.get("09:35")
            if first is None or second is None:
                continue
            opening_complete += 1
            feature = daily_features[symbol].get(session, {})
            atr, high, low = feature.get("atr14"), feature.get("breakout_high"), feature.get("breakout_low")
            spy_i = spy_index.get(session)
            if atr is None or atr <= 0 or high is None or low is None or spy_i is None or spy_i < 50:
                continue
            market_history = spy_closes[:spy_i]
            spy_previous = market_history[-1]
            ema20, ema50 = _ema(market_history, 20), _ema(market_history, 50)
            candidates = []
            if float(first["close"]) > high and float(second["close"]) > high and ema50 is not None and spy_previous >= ema50:
                candidates.append(("CALL", 1.0, high, ema50, "SPY_PREVIOUS_CLOSE_GTE_EMA50"))
            if float(first["close"]) < low and float(second["close"]) < low and ema20 is not None and spy_previous < ema20:
                candidates.append(("PUT", -1.0, low, ema20, "SPY_PREVIOUS_CLOSE_LT_EMA20"))
            if not candidates:
                continue
            base_dates += 1
            prior_sessions = sessions[max(0, idx - 20):idx]
            prior_turnover = []
            missing_turnover = []
            for prior in prior_sessions:
                previous_bars = minute.get(symbol, {}).get(prior, {})
                parts = [previous_bars.get("09:30"), previous_bars.get("09:35")]
                if len(parts) != 2 or any(part is None or part.get("turnover") is None for part in parts):
                    missing_turnover.append(prior)
                else:
                    prior_turnover.append(sum(float(part["turnover"]) for part in parts))
            current_parts = [first.get("turnover"), second.get("turnover")]
            baseline = statistics.median(prior_turnover) if len(prior_turnover) == 20 else None
            if any(value is None for value in current_parts):
                v_state, v_value = "UNKNOWN_CURRENT_TURNOVER", None
            elif baseline is None:
                v_state, v_value = "UNKNOWN_PARTIAL_HISTORY", None
            elif baseline <= 0:
                v_state, v_value = "UNKNOWN_ZERO_BASELINE", None
            else:
                v_value = sum(float(value) for value in current_parts) / baseline
                v_state = "PASS" if v_value >= 1.5 else "FAIL"
            compression = feature.get("compression")
            c_state = "UNKNOWN" if compression is None else ("PASS" if compression <= 0.8 else "FAIL")
            for right, direction, level, market_ema, market_rule in candidates:
                economic_id = f"cbrm_{digest([symbol, right, session])[:24]}"
                payload = {
                    "economic_event_id": economic_id, "symbol": symbol, "right": right, "session": session,
                    "level": level, "signal_at": second["availability_at"],
                    "opening_bars": [{key: row[key] for key in ("timestamp_utc", "time_et", "open", "high", "low", "close", "turnover", "availability_at", "lineage_hash")} for row in (first, second)],
                    "market_confirmation": {"rule": market_rule, "spy_previous_close": spy_previous, "ema": market_ema},
                    "features": {
                        "C": compression, "V": v_value, "V_log": math.log(v_value) if v_value is not None and v_value > 0 else None,
                        "B": direction * (float(second["close"]) - level) / float(atr),
                        "G": direction * (float(first["open"]) - float(feature["previous_close"])) / float(atr),
                        "atr14": float(atr),
                    },
                    "filter_states": {"C": c_state, "V": v_state},
                    "participation": {"current_d10": None if any(value is None for value in current_parts) else sum(float(value) for value in current_parts),
                                      "baseline_median": baseline, "prior_sessions": prior_sessions, "missing_sessions": missing_turnover,
                                      "turnover_source": "NATIVE", "currency": "USD"},
                    "daily_lineage_hash": feature.get("source_lineage_hash"),
                    "target_kind": "UNDERLYING_PROXY_NOT_OPTION_PNL", "production_consumption": False,
                }
                label = _label_event(event=payload, sessions=sessions, session_index=idx, bars=minute[symbol], horizon_days=protocol["horizon"][right])
                payload["label"] = label
                payload["group_states"] = {
                    "F0": "PASS",
                    "F1": "PASS" if c_state == "PASS" else ("UNKNOWN" if c_state == "UNKNOWN" else "FAIL"),
                    "F2": "PASS" if c_state == "PASS" and v_state == "PASS" else ("UNKNOWN" if "UNKNOWN" in (c_state, v_state) or v_state.startswith("UNKNOWN") else "FAIL"),
                }
                events.append(payload)
                symbol_events += 1
        coverage[symbol] = {"sessions_with_opening_pair": opening_complete, "base_session_dates": base_dates, "base_events": symbol_events,
                            "minute_first": min(minute.get(symbol, {"": {}}).keys()) if minute.get(symbol) else None,
                            "minute_last": max(minute.get(symbol, {"": {}}).keys()) if minute.get(symbol) else None}
    with sqlite3.connect(store_path) as connection:
        connection.execute("DELETE FROM breakout_events WHERE run_id=?", (run_id,))
        connection.executemany(
            "INSERT INTO breakout_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (run_id, e["economic_event_id"], e["symbol"], e["right"], e["session"], e["signal_at"],
                 e["label"].get("reference_entry_at"), e["label"].get("horizon_end"), e["label"].get("label_available_at"),
                 e["label"]["state"], e["filter_states"]["C"], e["filter_states"]["V"],
                 e["group_states"]["F0"], e["group_states"]["F1"], e["group_states"]["F2"],
                 e["label"].get("F"), e["label"].get("Y"), canonical(e), digest(e)) for e in events
            ],
        )
        connection.execute("INSERT OR REPLACE INTO research_meta VALUES (?,?,?)", (f"event_run:{run_id}", canonical({"events": len(events), "coverage": coverage}), utc_now()))
        connection.commit()
    return {"run_id": run_id, "events": events, "coverage": coverage, "data_hash": digest(events), "protocol_hash": digest(protocol)}


def _group_stats(events: list[dict[str, Any]], group: str, right: str) -> dict[str, Any]:
    chosen = [e for e in events if e["right"] == right and e["group_states"][group] == "PASS"]
    mature = [e for e in chosen if e["label"]["state"] == "MATURE"]
    y = [float(e["label"]["Y"]) for e in mature]
    f = [int(e["label"]["F"]) for e in mature]
    return {
        "base_selected": len(chosen), "mature": len(mature), "unique_dates": len({e["session"] for e in mature}),
        "symbols": sorted({e["symbol"] for e in mature}),
        "cancelled_at_t0": sum(e["label"]["state"] in {"CANCELLED_AT_T0", "INVALID_BEFORE_T0"} for e in chosen),
        "invalid_before_t0": sum(e["label"]["state"] in {"CANCELLED_AT_T0", "INVALID_BEFORE_T0"} for e in chosen),
        "censored": sum(e["label"]["state"] in {"CENSORED", "LABEL_NOT_MATURE"} for e in chosen),
        "failure_rate": statistics.mean(f) if f else None, "mean_Y": statistics.mean(y) if y else None,
        "median_Y": statistics.median(y) if y else None,
    }


def _block_bootstrap(events: list[dict[str, Any]], right: str, protocol: dict[str, Any]) -> dict[str, Any]:
    eligible = [e for e in events if e["right"] == right and e["label"]["state"] == "MATURE"]
    dates = sorted({e["session"] for e in eligible})
    block = int(protocol["ablation"]["synchronous_session_block_length"])
    repeats = int(protocol["ablation"]["bootstrap_repetitions"])
    if len(dates) < block:
        return {"status": "INSUFFICIENT_DATES", "unique_dates": len(dates)}
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in eligible:
        by_date[event["session"]].append(event)
    rng = np.random.default_rng(int(protocol["ablation"]["seed"]))
    values: dict[str, list[float]] = {"mean_Y": [], "failure_rate": []}
    replicate_denominators: dict[str, list[dict[str, int]]] = {"mean_Y": [], "failure_rate": []}
    starts = np.arange(0, len(dates) - block + 1)
    blocks_needed = math.ceil(len(dates) / block)
    for _ in range(repeats):
        sampled: list[dict[str, Any]] = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            for day in dates[int(start):int(start) + block]:
                sampled.extend(by_date[day])
        for metric, label_key in (("mean_Y", "Y"), ("failure_rate", "F")):
            f1 = [float(e["label"][label_key]) for e in sampled if e["group_states"]["F1"] == "PASS"]
            f2 = [float(e["label"][label_key]) for e in sampled if e["group_states"]["F2"] == "PASS"]
            if f1 and f2:
                values[metric].append(statistics.mean(f2) - statistics.mean(f1))
                replicate_denominators[metric].append({"f1_events": len(f1), "f2_events": len(f2)})
    point_estimates = {}
    date_weighted_estimates = {}
    for metric, label_key in (("mean_Y", "Y"), ("failure_rate", "F")):
        f1 = [float(e["label"][label_key]) for e in eligible if e["group_states"]["F1"] == "PASS"]
        f2 = [float(e["label"][label_key]) for e in eligible if e["group_states"]["F2"] == "PASS"]
        point_estimates[metric] = statistics.mean(f2) - statistics.mean(f1) if f1 and f2 else None
        per_date_f1 = [
            statistics.mean(float(e["label"][label_key]) for e in by_date[day] if e["group_states"]["F1"] == "PASS")
            for day in dates if any(e["group_states"]["F1"] == "PASS" for e in by_date[day])
        ]
        per_date_f2 = [
            statistics.mean(float(e["label"][label_key]) for e in by_date[day] if e["group_states"]["F2"] == "PASS")
            for day in dates if any(e["group_states"]["F2"] == "PASS" for e in by_date[day])
        ]
        date_weighted_estimates[metric] = statistics.mean(per_date_f2) - statistics.mean(per_date_f1) if per_date_f1 and per_date_f2 else None
    return {
        "status": "DEV_ONLY", "comparison": "F2_MINUS_F1", "repetitions": repeats, "block_sessions": block,
        "estimand": "EVENT_WEIGHTED_F2_MINUS_F1",
        "sampling_unit": "SYNCHRONOUS_MARKET_SESSION_BLOCK",
        **{metric: {
                    "point_estimate": point_estimates[metric],
                    "bootstrap_replicate_mean": statistics.mean(items) if items else None,
                    "bootstrap_bias_vs_point": statistics.mean(items) - point_estimates[metric] if items and point_estimates[metric] is not None else None,
                    "date_weighted_descriptive_estimate": date_weighted_estimates[metric],
                    "ci_95": [float(np.quantile(items, .025)), float(np.quantile(items, .975))] if items else None,
                    "valid_repetitions": len(items),
                    "empty_group_repetitions": repeats - len(items),
                    "replicate_denominators": {
                        "f1_events_min": min((row["f1_events"] for row in replicate_denominators[metric]), default=None),
                        "f1_events_max": max((row["f1_events"] for row in replicate_denominators[metric]), default=None),
                        "f2_events_min": min((row["f2_events"] for row in replicate_denominators[metric]), default=None),
                        "f2_events_max": max((row["f2_events"] for row in replicate_denominators[metric]), default=None),
                    },
                    "legacy_estimate_field_meaning": "BOOTSTRAP_REPLICATE_MEAN_NOT_ORIGINAL_POINT_ESTIMATE",
                    } for metric, items in values.items()},
    }


def analyze_and_fit(
    *, event_payload: dict[str, Any], protocol: dict[str, Any], output_dir: Path,
) -> dict[str, Any]:
    events = event_payload["events"]
    output_dir.mkdir(parents=True, exist_ok=False)
    stats = {right: {group: _group_stats(events, group, right) for group in ("F0", "F1", "F2")} for right in ("CALL", "PUT")}
    bootstrap = {right: _block_bootstrap(events, right, protocol) for right in ("CALL", "PUT")}
    models: dict[str, Any] = {}
    split = protocol["split"]["dates"]
    for right in ("CALL", "PUT"):
        common = []
        for event in events:
            features = event["features"]
            if event["right"] != right or event["label"]["state"] != "MATURE" or any(features.get(key) is None for key in ("C", "V_log", "B", "G")):
                continue
            common.append({
                "economic_event_id": event["economic_event_id"], "session": event["session"], "right": right,
                "signal_at": event["signal_at"], "label_available_at": event["label"]["label_available_at"],
                "F": event["label"]["F"], "Y": event["label"]["Y"],
                "features": {key: features[key] for key in ("C", "V_log", "B", "G")},
            })
        common.sort(key=lambda row: (row["session"], row["economic_event_id"]))
        train = [row for row in common if split["TRAIN"][0] <= row["session"] <= split["TRAIN"][1]]
        partitions = {}
        for name in ("VALIDATION", "TEST"):
            evaluate = [row for row in common if split[name][0] <= row["session"] <= split[name][1]]
            if not evaluate:
                partitions[name] = {"model_status": "NO_EVALUATION_EVENTS", "production_consumption": False}
                continue
            first_signal = min(datetime.fromisoformat(row["signal_at"]) for row in evaluate)
            purged_train = [row for row in train if datetime.fromisoformat(row["label_available_at"]) < first_signal]
            try:
                partitions[name] = fit_development(purged_train, evaluate, protocol=protocol)
            except Exception as exc:
                partitions[name] = {"model_status": "NOT_FIT", "reason": type(exc).__name__ + ":" + str(exc),
                                    "training_events": len(purged_train), "evaluation_events": len(evaluate), "production_consumption": False}
            partitions[name]["training_events"] = len(purged_train)
            partitions[name]["evaluation_events"] = len(evaluate)
        models[right] = {"common_eligible_events": len(common), "common_sample_hash": digest(common), "partitions": partitions}
        (output_dir / f"{right.lower()}_common_events.jsonl").write_text("".join(canonical(row) + "\n" for row in common), encoding="utf-8")
    all_events_path = output_dir / "events.jsonl"
    all_events_path.write_text("".join(canonical(event) + "\n" for event in events), encoding="utf-8")
    result = {
        "run_id": event_payload["run_id"], "status": "DEV_ONLY", "target_kind": "UNDERLYING_PROXY_NOT_OPTION_PNL",
        "production_consumption": False, "event_count": len(events), "data_hash": event_payload["data_hash"],
        "protocol_hash": event_payload["protocol_hash"], "coverage": event_payload["coverage"],
        "ablation": stats, "bootstrap": bootstrap, "models": models,
        "artifacts": {"events": str(all_events_path.resolve())},
    }
    (output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return result


def status(store_path: Path = DEFAULT_STORE) -> dict[str, Any]:
    if not store_path.exists():
        return {"status": "NOT_BUILT", "production_consumption": False}
    connection = sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    bars = [dict(row) for row in connection.execute("SELECT symbol,COUNT(*) bars,COUNT(DISTINCT session_date) sessions,MIN(session_date) first_session,MAX(session_date) last_session FROM minute_bars GROUP BY symbol ORDER BY symbol")]
    events = [dict(row) for row in connection.execute("SELECT run_id,right,COUNT(*) events,SUM(CASE WHEN state='MATURE' THEN 1 ELSE 0 END) mature,SUM(CASE WHEN f2_state='PASS' THEN 1 ELSE 0 END) f2_pass FROM breakout_events GROUP BY run_id,right ORDER BY run_id,right")]
    latest = connection.execute("SELECT value_json FROM research_meta WHERE key='last_fetch'").fetchone()
    connection.close()
    return {"status": "DEV_ONLY", "version": VERSION, "bars": bars, "events": events,
            "last_fetch": json.loads(latest[0]) if latest else None, "production_consumption": False,
            "option_profit_probability": None, "expected_option_pnl": None}


def review_payload(
    store_path: Path = DEFAULT_STORE,
    result_path: Path = DEFAULT_OUTPUT / "cbrm-dev-v0-2-20260921-01" / "result.json",
    audit_path: Path = DEFAULT_AUDIT_RESULT,
    *,
    symbol: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    base = status(store_path)
    if not store_path.exists():
        return base
    connection = sqlite3.connect(f"file:{store_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    where = "WHERE run_id=?"
    values: list[Any] = ["cbrm-dev-v0-2-20260921-01"]
    if symbol:
        where += " AND symbol=?"
        values.append(symbol.upper())
    values.append(max(1, min(int(limit), 100)))
    rows = connection.execute(
        f"SELECT payload_json FROM breakout_events {where} ORDER BY session_date DESC, symbol, right LIMIT ?", values
    ).fetchall()
    connection.close()
    events = [json.loads(row[0]) for row in rows]
    compact_result = None
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        compact_result = {
            "run_id": result["run_id"], "status": result["status"], "event_count": result["event_count"],
            "data_hash": result["data_hash"], "protocol_hash": result["protocol_hash"],
            "ablation": result["ablation"], "bootstrap": result["bootstrap"],
            "models": {
                right: {
                    "common_eligible_events": value["common_eligible_events"],
                    "common_sample_hash": value["common_sample_hash"],
                    "partitions": {
                        name: {
                            "model_status": partition.get("model_status"),
                            "training_events": partition.get("training_events"),
                            "evaluation_events": partition.get("evaluation_events"),
                            "variants": {
                                variant: {key: metrics.get(key) for key in ("log_loss", "baseline_log_loss", "brier", "baseline_brier", "quantile_metrics", "crossing_count")}
                                for variant, metrics in partition.get("variants", {}).items()
                            },
                            "reason": partition.get("reason"),
                        } for name, partition in value["partitions"].items()
                    },
                } for right, value in result["models"].items()
            },
        }
    evidence_audit = None
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        evidence_audit = {
            "audit_id": audit["audit_id"],
            "audit_sha256": audit["audit_sha256"],
            "status": audit["status"],
            "statistics": audit["statistics"],
            "timing": {key: value for key, value in audit["timing"].items() if key != "events"},
            "complete_case": audit["complete_case"],
            "decision": audit["decision"],
        }
    return {**base, "latest_events": events, "research_result": compact_result, "evidence_audit": evidence_audit,
            "model_loaded_by_runtime": False, "activity_policy_changed": False,
            "real_orders_enabled": False, "automatic_paper_entry_enabled": False}


__all__ = ["fetch_minute_history", "build_events", "analyze_and_fit", "initialize_store", "live_opening_participation", "load_protocol", "review_payload", "status"]
