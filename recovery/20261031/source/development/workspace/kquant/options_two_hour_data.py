"""Independent prewarm cache. Shares the existing quote runtime, never a trade context."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .market_clock import is_trading_day, session_bounds_utc
from .options_two_hour import STORE, NY, canonical, digest, finite, timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS two_hour_history (
 symbol TEXT NOT NULL, period TEXT NOT NULL, open_at TEXT NOT NULL,
 request_at TEXT NOT NULL, received_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(symbol,period,open_at)
);
CREATE TABLE IF NOT EXISTS two_hour_prewarm (
 session TEXT NOT NULL, symbol TEXT NOT NULL, state TEXT NOT NULL,
 reason TEXT, attempted_at TEXT, retry_at TEXT, payload_json TEXT NOT NULL,
 PRIMARY KEY(session,symbol)
);
CREATE TABLE IF NOT EXISTS two_hour_baselines (
 session TEXT NOT NULL, symbol TEXT NOT NULL, scope_hash TEXT NOT NULL,
 payload_json TEXT NOT NULL, PRIMARY KEY(session,symbol,scope_hash)
);
"""


def initialize(path: Path = STORE) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)


def universe(path: Path) -> dict:
    # Do not call the UI watchlist helper: it can seed or migrate on read.
    from .bounded_sqlite import read_connection
    with read_connection(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("""SELECT m.normalized_symbol AS symbol,
            m.provider_symbol,m.identity_status,m.group_id FROM stock_watchlist_members m
            JOIN stock_watchlist_groups g ON g.group_id=m.group_id
            WHERE m.status='active' AND g.is_active=1 ORDER BY m.normalized_symbol,m.group_id""")]
    items = {}
    for row in rows:
        items.setdefault(row["symbol"], {**row, "groups": []})["groups"].append(row["group_id"])
    return {"scope_hash": digest(rows), "items": list(items.values())}


def sessions_before(day: date, count: int) -> list[str]:
    result = []
    while len(result) < count:
        day -= timedelta(days=1)
        if is_trading_day(day):
            result.append(day.isoformat())
    return list(reversed(result))


def seed_jobs(day: date, manifest: dict, path: Path = STORE) -> None:
    with sqlite3.connect(path) as connection:
        for item in manifest["items"]:
            valid = item["identity_status"] == "verified" and bool(item["provider_symbol"])
            connection.execute("INSERT OR IGNORE INTO two_hour_prewarm VALUES (?,?,?,?,NULL,NULL,?)",
                (day.isoformat(), item["symbol"], "PENDING" if valid else "IDENTITY_UNRESOLVED",
                 None if valid else "IDENTITY_UNRESOLVED", canonical(item)))
        # Resume the earlier daily-only stop so available intraday data is still collected.
        connection.execute("""UPDATE two_hour_prewarm SET state='PENDING',retry_at=NULL
            WHERE session=? AND state='DATA_INSUFFICIENT' AND reason LIKE '%:DAILY_MISSING_%'""",
            (day.isoformat(),))


def reuse_turnover_cache(day: date, symbols: set[str], source: Path, path: Path = STORE,
                         *, slot_end_minute: int = 690) -> int:
    if not source.exists():
        return 0
    days = sessions_before(day, 20)
    with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("""SELECT b.*,r.request_started_at,r.received_at FROM minute_bars b
            JOIN minute_requests r ON b.request_id=r.request_id
            WHERE b.session_date>=? AND b.session_date<? AND b.turnover_source='NATIVE'
            AND b.turnover_currency='USD' AND b.adjustment_mode='ForwardAdjust'""", (days[0], day.isoformat())).fetchall()
    copied = 0
    with sqlite3.connect(path) as connection:
        for row in rows:
            if row["symbol"] not in symbols or row["session_date"] not in days or not row["received_at"]:
                continue
            if not "09:30" <= row["time_et"] < f"{slot_end_minute // 60:02d}:{slot_end_minute % 60:02d}" or not row["lineage_hash"]:
                continue
            if timestamp(row["availability_at"]) > timestamp(row["request_started_at"]) or timestamp(row["request_started_at"]) > timestamp(row["received_at"]):
                continue
            payload = {"symbol": row["symbol"], "open_at": row["timestamp_utc"], "session": row["session_date"],
                       "slot": row["time_et"], "adjustment": "ForwardAdjust", "source": "longbridge_reused_cache",
                       "request_at": row["request_started_at"], "received_at": row["received_at"],
                       "currency": "USD", "turnover_source": "NATIVE", "lineage_hash": row["lineage_hash"]}
            payload.update({key: row[key] for key in ("open", "high", "low", "close", "volume", "turnover")})
            copied += connection.execute("INSERT OR IGNORE INTO two_hour_history VALUES (?,?,?,?,?,?)",
                (row["symbol"], "5m", row["timestamp_utc"], row["request_started_at"], row["received_at"], canonical(payload))).rowcount
    return copied


def classify_failure(exc: Exception) -> str:
    # Keep raw provider messages out of the user-facing status and logs.
    text = str(exc).lower()
    if isinstance(exc, TimeoutError):
        return "TASK_TIMEOUT"
    if "histor" in text and any(word in text for word in ("quota", "limit")):
        return "PROVIDER_HISTORY_SYMBOL_QUOTA"
    if "subscription" in text and any(word in text for word in ("quota", "limit")):
        return "PROVIDER_SUBSCRIPTION_LIMIT"
    if "connection" in text:
        return "PROVIDER_CONNECTION_ERROR"
    if any(word in text for word in ("429", "too many", "rate limit")):
        return "PROVIDER_RATE_LIMIT"
    if "throttl" in text:
        return "SDK_THROTTLE"
    return "PROVIDER_REQUEST_FAILED"


def history(symbol: str, period: str, path: Path = STORE) -> list[dict]:
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        return [json.loads(row[0]) for row in connection.execute(
            "SELECT payload_json FROM two_hour_history WHERE symbol=? AND period=? ORDER BY open_at", (symbol, period))]


def store_response(symbol: str, period: str, rows: list, request_at: datetime,
                   received_at: datetime, path: Path = STORE) -> None:
    from .stock_signals import _parse_longbridge_time
    with sqlite3.connect(path) as connection:
        for row in rows:
            opened = _parse_longbridge_time(row.timestamp)
            if opened is None:
                raise ValueError("INVALID_PROVIDER_BAR_TIME")
            local = opened.astimezone(NY)
            if not is_trading_day(local.date()):
                continue
            start, end = session_bounds_utc(local.date())
            available = end if period == "1d" else opened + timedelta(minutes=5)
            if available > request_at or (period == "5m" and not start <= opened < end):
                continue
            payload = {"symbol": symbol, "open_at": opened.isoformat(), "session": local.date().isoformat(),
                       "raw_timestamp": str(row.timestamp),
                       "timestamp_contract": "EXISTING_SDK_NAIVE_ASIA_SHANGHAI_ADAPTER",
                       "slot": local.strftime("%H:%M"), "adjustment": "ForwardAdjust",
                       "request_at": request_at.isoformat(), "received_at": received_at.isoformat(),
                       "source": "longbridge", "currency": "USD", "turnover_source": "NATIVE"}
            for key in ("open", "high", "low", "close", "volume", "turnover"):
                value = getattr(row, key, None)
                payload[key] = float(value) if value is not None else None
            payload["lineage_hash"] = digest(payload)
            connection.execute("INSERT OR REPLACE INTO two_hour_history VALUES (?,?,?,?,?,?)",
                (symbol, period, opened.isoformat(), request_at.isoformat(), received_at.isoformat(), canonical(payload)))


def assemble(symbol: str, day: date, scope_hash: str, now: datetime, path: Path = STORE,
             *, slot_end_minute: int = 690) -> tuple[dict | None, list[str]]:
    from .options_full_watch import _compression_ratio, _ema
    previous = sessions_before(day, 273)
    days = previous[-20:]
    daily = {row["session"]: row for row in history(symbol, "1d", path) if row["session"] in previous}
    spy = {row["session"]: row for row in history("SPY", "1d", path) if row["session"] in previous}
    reasons = []
    if len(daily) != 273:
        reasons.append("CONTIGUOUS_273_DAILY_BARS_MISSING")
    if any(session not in spy for session in previous):
        reasons.append("SPY_HISTORY_MISSING")
    if not 690 <= slot_end_minute <= 960 or slot_end_minute % 5:
        raise ValueError("INVALID_INTRADAY_SLOT_END")
    slots = [f"{minute // 60:02d}:{minute % 60:02d}" for minute in range(570, slot_end_minute, 5)]
    turnover_reason = "NATIVE_20_SESSION_2H_TURNOVER_MISSING" if slot_end_minute == 690 else "NATIVE_20_SESSION_INTRADAY_TURNOVER_MISSING"
    minute = {(row["session"], row["slot"]): row for row in history(symbol, "5m", path) if row["session"] in days}
    if any((session, slot) not in minute for session in days for slot in slots):
        reasons.append(turnover_reason)
    opening, _ = session_bounds_utc(day)
    if now >= opening:
        reasons.append("PREOPEN_FREEZE_MISSED")
    if reasons:
        return None, reasons
    source = list(daily.values()) + list(spy.values()) + [minute[(session, slot)] for session in days for slot in slots]
    if any(timestamp(row["received_at"]) > now for row in source):
        return None, ["SOURCE_TIME_CONFLICT"]
    if any(not finite(row.get(key)) or row[key] <= 0 for row in list(daily.values()) + list(spy.values()) for key in ("high", "low", "close")):
        return None, ["INVALID_DAILY_PRICE"]
    if any(not finite(minute[(session, slot)].get("turnover")) or minute[(session, slot)]["turnover"] < 0 for session in days for slot in slots):
        return None, ["NATIVE_TURNOVER_INVALID"]
    closes = [daily[session]["close"] for session in previous]
    spy_closes = [spy[session]["close"] for session in previous]
    compression = _compression_ratio(closes)
    if compression is None:
        return None, ["COMPRESSION_UNAVAILABLE"]
    baseline = {"symbol": symbol, "session": day.isoformat(), "scope_hash": scope_hash, "frozen_at": now.isoformat(),
                "max_input_available_at": max(row["received_at"] for row in source),
                "compression": compression, "range_high": max(daily[session]["high"] for session in days),
                "range_low": min(daily[session]["low"] for session in days),
                "spy_close": spy_closes[-1], "spy_ema20": _ema(spy_closes, 20), "spy_ema50": _ema(spy_closes, 50),
                "prior_sessions": days, "turnover_by_session": {session: {slot: minute[(session, slot)]["turnover"] for slot in slots} for session in days},
                "source_hash": digest([row["lineage_hash"] for row in source]), "adjustment": "ForwardAdjust"}
    return baseline, []


def prewarm_one(runtime, manifest: dict, day: date, *, path: Path = STORE,
                now: datetime | None = None, slot_end_minute: int = 690) -> dict:
    """One bounded request per turn; persistent oldest-attempt ordering is fair."""
    from longbridge.openapi import Period, AdjustType
    now = now or datetime.now(UTC)
    opening, _ = session_bounds_utc(day)
    if now >= opening:
        return {"state": "PREWARM_WINDOW_CLOSED"}
    with sqlite3.connect(path) as connection:
        row = connection.execute("""SELECT symbol,payload_json FROM two_hour_prewarm
            WHERE session=? AND state IN ('PENDING','RETRY') AND (retry_at IS NULL OR retry_at<=?)
            ORDER BY COALESCE(attempted_at,''),symbol LIMIT 1""", (day.isoformat(), now.isoformat())).fetchone()
        if not row:
            return {"state": "NO_PENDING_PREWARM"}
        symbol, item = row[0], json.loads(row[1])
        connection.execute("UPDATE two_hour_prewarm SET attempted_at=? WHERE session=? AND symbol=?", (now.isoformat(), day.isoformat(), symbol))
    try:
        baseline, reasons = (assemble(symbol, day, manifest["scope_hash"], now, path)
                             if slot_end_minute == 690 else assemble(symbol, day, manifest["scope_hash"], now, path,
                                                                      slot_end_minute=slot_end_minute))
        if baseline:
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT OR IGNORE INTO two_hour_baselines VALUES (?,?,?,?)", (day.isoformat(), symbol, manifest["scope_hash"], canonical(baseline)))
                connection.execute("UPDATE two_hour_prewarm SET state='READY',reason=NULL WHERE session=? AND symbol=?", (day.isoformat(), symbol))
            return {"symbol": symbol, "state": "READY"}
        request_at = now
        daily_missing = "CONTIGUOUS_273_DAILY_BARS_MISSING" in reasons and not item.get("daily_checked")
        if daily_missing or "SPY_HISTORY_MISSING" in reasons:
            target = symbol if daily_missing else "SPY"
            provider = item["provider_symbol"] if target == symbol else "SPY.US"
            rows = runtime.candlesticks(provider, Period.Day, 300, AdjustType.ForwardAdjust, 10)
            store_response(target, "1d", rows, request_at, datetime.now(UTC), path)
            required = set(sessions_before(day, 273))
            available = {row["session"] for row in history(target, "1d", path)}
            if target == symbol:
                item["daily_checked"] = True
                item["daily_missing_sessions"] = sorted(required - available)
                with sqlite3.connect(path) as connection:
                    connection.execute("UPDATE two_hour_prewarm SET payload_json=? WHERE session=? AND symbol=?",
                                       (canonical(item), day.isoformat(), symbol))
            if not required.issubset(available):
                if target == "SPY":
                    raise ValueError("SPY_HISTORY_INCOMPLETE")
        elif any(reason in reasons for reason in ("NATIVE_20_SESSION_2H_TURNOVER_MISSING", "NATIVE_20_SESSION_INTRADAY_TURNOVER_MISSING")):
            present = {(row["session"], row["slot"]) for row in history(symbol, "5m", path)}
            missing = [session for session in sessions_before(day, 20) if any((session, f"{m // 60:02d}:{m % 60:02d}") not in present for m in range(570, slot_end_minute, 5))]
            target = date.fromisoformat(missing[0])
            # Five calendar days bound the page while amortizing provider requests.
            end = min(target + timedelta(days=4), date.fromisoformat(sessions_before(day, 20)[-1]))
            rows = runtime.history_candlesticks_by_date(item["provider_symbol"], Period.Min_5, AdjustType.ForwardAdjust, target, end, 10)
            store_response(symbol, "5m", rows, request_at, datetime.now(UTC), path)
            actual = {row["slot"] for row in history(symbol, "5m", path)
                      if row["session"] == target.isoformat() and finite(row.get("turnover"))}
            required_slots = {f"{m // 60:02d}:{m % 60:02d}" for m in range(570, slot_end_minute, 5)}
            if not required_slots.issubset(actual):
                reason = f"NATIVE_HISTORY_INCOMPLETE:{target.isoformat()}:{len(required_slots - actual)}_OF_{len(required_slots)}"
                with sqlite3.connect(path) as connection:
                    connection.execute("UPDATE two_hour_prewarm SET state='DATA_INSUFFICIENT',reason=? WHERE session=? AND symbol=?",
                                       (reason, day.isoformat(), symbol))
                return {"symbol": symbol, "state": "DATA_INSUFFICIENT", "reason": reason}
        else:
            reason = (f"DAILY_MISSING_{len(item['daily_missing_sessions'])}_OF_273"
                      if item.get("daily_missing_sessions") else ",".join(reasons))
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE two_hour_prewarm SET state='DATA_INSUFFICIENT',reason=? WHERE session=? AND symbol=?",
                                   (reason, day.isoformat(), symbol))
            return {"symbol": symbol, "state": "DATA_INSUFFICIENT", "reason": reason}
        reason, retry = ",".join(reasons), now + timedelta(seconds=2)
    except Exception as exc:
        reason, retry = classify_failure(exc), now + timedelta(seconds=60)
        if reason == "PROVIDER_HISTORY_SYMBOL_QUOTA":
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE two_hour_prewarm SET state='QUOTA_DEFERRED',reason=?,retry_at=NULL WHERE session=? AND symbol=?",
                                   (reason, day.isoformat(), symbol))
            return {"symbol": symbol, "state": "QUOTA_DEFERRED", "reason": reason}
        # Safe diagnostics distinguish local parsing defects from provider failures.
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        location = frames[-1] if frames else None
        if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)) and location and Path(location.filename).name in {"options_two_hour.py", "options_two_hour_data.py"}:
            reason = "LOCAL_DATA_PROCESSING_ERROR"
        reason += ":" + type(exc).__name__
        if location:
            reason += f":{Path(location.filename).name}:{location.lineno}"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE two_hour_prewarm SET state='RETRY',reason=?,retry_at=? WHERE session=? AND symbol=?",
                           (reason, retry.isoformat(), day.isoformat(), symbol))
    return {"symbol": symbol, "state": "RETRY", "reason": reason}
