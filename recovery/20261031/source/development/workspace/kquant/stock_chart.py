"""Read-only chart data contract, isolated from strategy datasets and ledgers."""
from __future__ import annotations

import asyncio
import json
import math
import queue
import re
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .longbridge_provider import longbridge_runtime
from .market_clock import market_clock, is_trading_day, session_bounds_utc
from .stock_signals import _parse_longbridge_time

NY = ZoneInfo("America/New_York")
PERIODS = {"1m": "Min_1", "5m": "Min_5", "15m": "Min_15", "30m": "Min_30", "1h": "Min_60", "1d": "Day", "1wk": "Week", "1mo": "Month"}
COUNTS = {"1m": 1000, "5m": 500, "15m": 1000, "30m": 500, "1h": 300, "1d": 252, "1wk": 260, "1mo": 120}
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.RLock()
_names: dict[str, str] = {}


def number(value):
    try:
        parsed = float(value) if value is not None else None
        return parsed if parsed is not None and math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def event_time(value):
    parsed = _parse_longbridge_time(value) if value is not None else None
    return parsed.isoformat() if parsed else None


def symbol_code(symbol):
    symbol = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", symbol):
        raise ValueError("IDENTITY_UNRESOLVED")
    return symbol if symbol.endswith(".US") else symbol + ".US"


def failure(exc):
    message = str(exc).lower()
    if "histor" in message and any(x in message for x in ("quota", "limit")):
        return "HISTORY_QUOTA"
    if any(x in message for x in ("permission", "entitle", "403")):
        return "PERMISSION_REQUIRED"
    if isinstance(exc, TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, ValueError):
        return "INVALID_REQUEST"
    return "PROVIDER_UNAVAILABLE"


def quote_row(row, received_at):
    fields = {key: number(getattr(row, attribute, None)) for key, attribute in
              (("last", "last_done"), ("previous_close", "prev_close"), ("open", "open"),
               ("high", "high"), ("low", "low"), ("volume", "volume"), ("turnover", "turnover"))}
    fields.update(event_time=event_time(getattr(row, "timestamp", None)), received_at=received_at,
                  source="Longbridge", session="regular", market_session=market_clock().session)
    trade_session = str(getattr(row, "trade_session", "Intraday")).lower()
    if "pre" in trade_session:
        fields["session"] = "pre_market"
    elif "post" in trade_session:
        fields["session"] = "post_market"
    elif "overnight" in trade_session:
        fields["session"] = "overnight"
    for name in ("pre_market", "post_market"):
        extended = getattr(row, name + "_quote", None)
        if extended is not None:
            fields[name] = quote_row(extended, received_at)
            fields[name]["session"] = name
    return fields


def depth_row(row, received_at):
    result = {"received_at": received_at, "source": "Longbridge", "native_time_verified": False}
    for side in ("bid", "ask"):
        levels = list(getattr(row, side + "s", []) or [])
        level = levels[0] if levels else None
        result[side] = number(getattr(level, "price", None))
        result[side + "_size"] = number(getattr(level, "volume", None))
        result[side + "_event_time"] = event_time(getattr(level, "timestamp", None))
    result["native_time_verified"] = bool(result["bid_event_time"] and result["ask_event_time"])
    return result


def snapshot(symbol, kind="quote"):
    started = datetime.now(UTC).isoformat()
    try:
        runtime = longbridge_runtime()
        code = symbol_code(symbol)
        if kind == "depth":
            row, _ = runtime.pull_depth(code, 10)
            payload = depth_row(row, datetime.now(UTC).isoformat())
        else:
            rows = runtime.pull_quotes([code], 10)
            if not rows:
                raise ValueError("EMPTY_QUOTE")
            payload = quote_row(rows[0], datetime.now(UTC).isoformat())
            if code not in _names:
                try:
                    info = runtime.static_info([code], 5)
                    if info:
                        _names[code] = str(getattr(info[0], "name_en", "") or "")
                except Exception:
                    pass
            payload["name"] = _names.get(code)
        return {**payload, "symbol": symbol, "status": "available", "request_at": started,
                "market_session": market_clock().session, "read_only": True}
    except Exception as exc:
        return {"symbol": symbol, "status": "unavailable", "error_code": failure(exc), "request_at": started, "read_only": True}


def bar_row(row, interval, now):
    opened = _parse_longbridge_time(row.timestamp)
    if opened is None or opened > now:
        return None
    local = opened.astimezone(NY)
    values = {key: number(getattr(row, key, None)) for key in ("open", "high", "low", "close", "volume", "turnover")}
    if any(values[key] is None or values[key] <= 0 for key in ("open", "high", "low", "close")):
        return None
    if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"]):
        return None
    session_date = local.date()
    if interval in ("1d", "1wk", "1mo"):
        last = session_date
        if interval == "1wk":
            last += timedelta(days=4 - last.weekday())
        elif interval == "1mo":
            last = (last.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        while not is_trading_day(last):
            last -= timedelta(days=1)
        _, closed = session_bounds_utc(last)
    else:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}[interval]
        closed = opened + timedelta(minutes=minutes)
        if is_trading_day(session_date):
            start, end = session_bounds_utc(session_date)
            if start <= opened < end:
                closed = min(closed, end)
    return {**values, "open_time": opened.isoformat(), "close_time": closed.isoformat(),
            "trading_date": session_date.isoformat(), "bar_state": "closed" if now >= closed else "forming",
            "raw_timestamp": str(row.timestamp), "trade_session": str(getattr(row, "trade_session", "Unknown"))}


def chart_candles(symbol, interval="5m", session="regular", adjustment="none", before=None, limit=1000, raw_sdk=False):
    if interval not in PERIODS or session not in ("regular", "extended") or adjustment not in ("none", "forward") or not 1 <= limit <= 1000:
        return {"status": "unavailable", "error_code": "INVALID_REQUEST", "candles": []}
    if raw_sdk and (interval != "1m" or session != "regular" or adjustment != "none" or not before or limit > 30):
        return {"status": "unavailable", "error_code": "BOUNDED_RAW_SDK_CURSOR_REQUIRED", "candles": []}
    key = (symbol, interval, session, adjustment, before, limit, raw_sdk)
    with _lock:
        cached = _cache.get(key)
        ttl = 15 if market_clock().session in ("regular", "pre_market", "after_hours") else 300
        if cached and time.monotonic() - cached[0] < ttl:
            return {**cached[1], "delivery": "cache"}
        try:
            from longbridge.openapi import AdjustType, Period, TradeSessions
            code = symbol_code(symbol)
            period = getattr(Period, PERIODS[interval])
            adjust = AdjustType.NoAdjust if adjustment == "none" else AdjustType.ForwardAdjust
            sessions = TradeSessions.Intraday if session == "regular" else TradeSessions.All
            runtime = longbridge_runtime()
            count = min(limit + int(bool(before)), COUNTS[interval])
            started = datetime.now(UTC)
            if before:
                boundary = datetime.fromisoformat(before.replace("Z", "+00:00"))
                if boundary.tzinfo is None or boundary > started:
                    raise ValueError("INVALID_CURSOR")
                # The wire cursor is a market date/minute, unlike SDK result
                # timestamps which are returned as host-local naive datetimes.
                sdk_time = boundary.astimezone(NY).replace(tzinfo=None)
                rows = runtime.call("chart_history", lambda ctx: ctx.history_candlesticks_by_offset(code, period, adjust, False, count, sdk_time, sessions), 12)
            else:
                rows = runtime.call("chart_candles", lambda ctx: ctx.candlesticks(code, period, count, adjust, sessions), 12)
            received = datetime.now(UTC)
            future_count = sum(1 for row in rows if (stamp := _parse_longbridge_time(row.timestamp)) is not None and stamp > received)
            bars = [bar for row in rows if (bar := bar_row(row, interval, received)) is not None]
            bars = sorted({bar["open_time"]: bar for bar in bars}.values(), key=lambda bar: bar["open_time"])
            if before:
                bars = [bar for bar in bars if datetime.fromisoformat(bar["open_time"]) < boundary]
                bars = bars[-limit:]
            visible_from = bars[0]["open_time"] if bars else None
            if not before and interval not in ("1d", "1wk", "1mo") and bars:
                dates = sorted({bar["trading_date"] for bar in bars})
                wanted = dates[-(1 if interval in ("1m", "5m") else 5):]
                visible_from = next(bar["open_time"] for bar in bars if bar["trading_date"] in wanted)
            payload = {"symbol": symbol, "interval": interval, "session": session, "adjustment": adjustment,
                       "source": "Longbridge", "request_at": started.isoformat(), "received_at": received.isoformat(),
                       "market_session": market_clock(received).session, "status": "available" if bars else "empty",
                       "future_bars_rejected": future_count,
                       "candles": bars, "visible_from": visible_from, "next_before": bars[0]["open_time"] if bars and len(rows) >= count else None,
                       "read_only": True, "timestamp_contract": "EXISTING_SDK_NAIVE_ASIA_SHANGHAI_ADAPTER",
                       "cursor_timezone": "America/New_York" if before else None,
                       "sdk_cursor": sdk_time.isoformat() if before else None}
            if raw_sdk:
                from .options_opening_trend_sdk import candle_evidence
                payload["sdk_evidence"] = [candle_evidence(row, provider_symbol=code,
                    interface="QuoteContext.history_candlesticks_by_offset",
                    received_at=received.isoformat(), requested_at=started.isoformat()) for row in rows]
                payload["evidence_context"] = "LATE_RAW_SDK_DIAGNOSTIC_NOT_INSTANT_SIGNAL"
            _cache[key] = (time.monotonic(), payload)
            if len(_cache) > 128:
                _cache.pop(next(iter(_cache)))
            return payload
        except Exception as exc:
            return {**(cached[1] if cached else {}), "symbol": symbol, "status": "stale" if cached else "unavailable",
                    "error_code": failure(exc), "candles": cached[1]["candles"] if cached else []}


async def chart_stream(request, symbol, interval="5m", session="regular", adjustment="none"):
    from longbridge.openapi import Period
    runtime = longbridge_runtime()
    owner = "chart-" + uuid.uuid4().hex
    code = symbol_code(symbol)
    sink = runtime.event_queue(owner)
    try:
        # SDK streaming candles are unadjusted regular-session only. Other chart
        # contracts refresh from their explicit snapshot, never relabel push bars.
        period = getattr(Period, PERIODS[interval]) if session == "regular" and adjustment == "none" else None
        await asyncio.to_thread(runtime.retain_subscription, owner, code, quote=True, depth=True, period=period)
        yield "event: ready\ndata: {}\n\n"
        while not await request.is_disconnected():
            try:
                kind, event_symbol, row, received = await asyncio.to_thread(sink.get, True, 5)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if event_symbol != code:
                continue
            if kind == "quote":
                payload = quote_row(row, received)
            elif kind == "depth":
                payload = depth_row(row, received)
            elif kind == "candle" and period is not None and getattr(row, "period", None) == period:
                payload = bar_row(row.candlestick, interval, datetime.now(UTC))
                if payload is None:
                    continue
                payload["bar_state"] = "closed" if getattr(row, "is_confirmed", False) else "forming"
            else:
                continue
            yield "data: " + json.dumps({"kind": kind, "symbol": symbol, "received_at": received, "payload": payload}) + "\n\n"
    except Exception as exc:
        yield "event: failure\ndata: " + json.dumps({"error_code": failure(exc)}) + "\n\n"
    finally:
        await asyncio.to_thread(runtime.release_subscriptions, owner)
