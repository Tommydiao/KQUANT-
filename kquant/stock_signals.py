from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .stock_store import connect, default_db_path
from .stock_universe import stock_universe, stock_universe_payload

UTC = timezone.utc
RANGES = {
    "1d": {"bars": 78, "step": timedelta(minutes=5), "interval": "5m"},
    "5d": {"bars": 35, "step": timedelta(hours=1), "interval": "1h"},
    "1mo": {"bars": 22, "step": timedelta(days=1), "interval": "1d"},
    "3mo": {"bars": 66, "step": timedelta(days=1), "interval": "1d"},
    "1y": {"bars": 252, "step": timedelta(days=1), "interval": "1d"},
    "5y": {"bars": 260, "step": timedelta(days=7), "interval": "1wk"},
    "10y": {"bars": 120, "step": timedelta(days=30), "interval": "1mo"},
}
MARKET_OPEN_UTC_HOUR = 13
MARKET_OPEN_UTC_MINUTE = 30
MARKET_CLOSE_UTC_HOUR = 20
PROFILE = {
    "name": "swing_long_v1",
    "buy_setup_threshold": 82,
    "strict_buy_gate_score": 88,
    "watch_threshold": 65,
    "direction": "long_only",
    "primary_timeframe": "1d",
    "confirmation_timeframe": "1h",
}


def api_stock_universe(universe: str = "default", db_path: Path | None = None) -> dict[str, Any]:
    payload = stock_universe_payload(universe)
    if db_path:
        now = iso_now()
        with connect(db_path) as conn:
            for stock in payload["stocks"]:
                conn.execute(
                    """
                    INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      name=excluded.name,
                      sector=excluded.sector,
                      layer=excluded.layer,
                      tags_json=excluded.tags_json,
                      rank=excluded.rank,
                      active=1,
                      updated_at=excluded.updated_at
                    """,
                    (
                        stock["symbol"],
                        stock["name"],
                        stock["sector"],
                        stock["layer"],
                        json.dumps(stock["tags"]),
                        stock["rank"],
                        now,
                    ),
                )
            conn.commit()
    return payload


def api_stock_candles(
    symbol: str,
    range_value: str = "1y",
    interval: str = "1d",
    source: str = "fixture",
    db_path: Path | None = None,
) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    range_value, interval = normalize_range_interval(range_value, interval)
    if source == "live":
        payload = yahoo_candles(symbol, range_value, interval)
        if payload["provider_status"] != "available" and db_path:
            record_provider_event(
                db_path,
                provider="yahoo_chart",
                instrument="stock",
                symbol=symbol,
                status=payload["provider_status"],
                message="; ".join(payload.get("provider_errors", [])) or "public provider unavailable",
            )
            cached = cached_candles_payload(db_path, symbol, range_value, interval, payload)
            if cached:
                return cached
    else:
        payload = fixture_candles_payload(symbol, range_value, interval)
    if db_path:
        persist_candles(db_path, payload)
    return payload


def api_stock_provider_health(db_path: Path | None = None) -> dict[str, Any]:
    path = db_path or default_db_path()
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT provider, status, message, created_at
            FROM provider_events
            ORDER BY id DESC
            LIMIT 60
            """
        ).fetchall()
    error_count = sum(1 for row in rows if row["status"] not in ("available", "fixture_read_only"))
    stale_count = sum(1 for row in rows if row["status"] == "stale_cache")
    return {
        "provider_status": "degraded" if error_count else "available",
        "provider_error_count": error_count,
        "stale_cache_count": stale_count,
        "events": [dict(row) for row in rows],
        "source_policy": "live does not silently mix fixture data",
    }


def api_stock_signals(
    source: str = "fixture",
    universe: str = "default",
    profile: str = "swing_long_v1",
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    db = db_path or default_db_path()
    outputs = outputs_dir or Path("outputs")
    stocks = stock_universe(universe)
    symbols = [stock.symbol for stock in stocks]
    if limit:
        symbols = symbols[: max(1, min(limit, len(symbols)))]
        stocks = stocks[: len(symbols)]
    stock_by_symbol = {stock.symbol: stock for stock in stocks}
    started = iso_now()
    signals: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    label_samples_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        daily = api_stock_candles(symbol, "1y", "1d", source, db)
        hourly = api_stock_candles(symbol, "5d", "1h", source, db)
        if daily["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: daily {daily['provider_status']}")
        if hourly["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: 1h {hourly['provider_status']}")
        signal = build_signal(symbol, daily, hourly)
        stock_meta = stock_by_symbol.get(symbol)
        if stock_meta:
            signal["primary_layer"] = stock_meta.layer
            signal["tags"] = list(stock_meta.tags)
            signal["liquidity_tier"] = stock_meta.liquidity_tier
        label_samples_by_symbol[symbol] = signal.pop("_label_samples", [])
        signals.append(signal)
    signals.sort(key=lambda item: item["score"], reverse=True)
    completed = iso_now()
    run_id = f"stock-{int(time.time())}"
    provider_status = "degraded" if provider_errors else ("fixture_read_only" if source == "fixture" else "available")
    historical_validation = summarize_label_samples(label_samples_by_symbol)
    payload = {
        "run_id": run_id,
        "product": "KQUANT US Stock Signal Terminal",
        "source": source,
        "universe": universe,
        "profile": PROFILE | {"name": profile},
        "started_at": started,
        "completed_at": completed,
        "provider_status": provider_status,
        "provider_error_count": len(provider_errors),
        "provider_errors": provider_errors[:30],
        "historical_validation": historical_validation,
        "counts": {
            "buy_setup": sum(1 for signal in signals if signal["level"] == "BUY SETUP"),
            "watch": sum(1 for signal in signals if signal["level"] == "WATCH"),
            "pass": sum(1 for signal in signals if signal["level"] == "PASS"),
            "total": len(signals),
        },
        "signals": signals,
        "btc_eth_removed_from_main_path": True,
        "options_are_secondary": True,
        "llm_signal_core_enabled": False,
        "broker_order_wiring_enabled": False,
        "_label_samples_by_symbol": label_samples_by_symbol,
    }
    persist_signal_run(db, payload)
    write_reports(outputs, payload)
    return payload


def api_stock_signals_latest(
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
    source: str = "fixture",
    universe: str = "default",
    profile: str = "swing_long_v1",
) -> dict[str, Any]:
    outputs = outputs_dir or Path("outputs")
    report = outputs / "stock-signals-report.json"
    if report.exists():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            if payload.get("source") == source and payload.get("universe") == universe and payload.get("profile", {}).get("name") == profile:
                return payload
        except json.JSONDecodeError:
            pass
    if source == "live":
        return empty_signal_run(source=source, universe=universe, profile=profile, reason="No matching live stock signal report yet. Run a manual live scan.")
    return api_stock_signals(source=source, universe=universe, profile=profile, db_path=db_path, outputs_dir=outputs)


def empty_signal_run(source: str, universe: str, profile: str, reason: str) -> dict[str, Any]:
    now = iso_now()
    return {
        "run_id": "stock-live-not-scanned",
        "product": "KQUANT US Stock Signal Terminal",
        "source": source,
        "universe": universe,
        "profile": PROFILE | {"name": profile},
        "started_at": now,
        "completed_at": now,
        "provider_status": "not_scanned",
        "provider_error_count": 0,
        "provider_errors": [reason],
        "historical_validation": summarize_label_samples({}),
        "counts": {"buy_setup": 0, "watch": 0, "pass": 0, "total": 0},
        "signals": [],
        "btc_eth_removed_from_main_path": True,
        "options_are_secondary": True,
        "llm_signal_core_enabled": False,
        "broker_order_wiring_enabled": False,
    }


def build_signal(symbol: str, daily_payload: dict[str, Any], hourly_payload: dict[str, Any]) -> dict[str, Any]:
    daily = daily_payload["candles"]
    hourly = hourly_payload["candles"]
    if len(daily) < 60 or len(hourly) < 20:
        return empty_signal(symbol, daily_payload, hourly_payload)
    daily_close = [bar["close"] for bar in daily]
    daily_volume = [bar["volume"] for bar in daily]
    hourly_close = [bar["close"] for bar in hourly]
    ema20 = ema_last(daily_close, 20)
    ema50 = ema_last(daily_close, 50)
    ema200 = ema_last(daily_close, 200)
    h_ema20 = ema_last(hourly_close, 20)
    h_ema50 = ema_last(hourly_close, 50)
    close = daily_close[-1]
    previous = daily_close[-6] if len(daily_close) > 6 else daily_close[0]
    trend_return = pct(close, previous)
    volume_ratio = daily_volume[-1] / max(sum(daily_volume[-21:-1]) / max(len(daily_volume[-21:-1]), 1), 1)
    atr_pct = average_true_range_pct(daily[-20:])
    extension_pct = pct(close, ema20)
    one_hour_momentum = pct(hourly_close[-1], hourly_close[-8])
    trend_score = score_trend(close, ema20, ema50, ema200, trend_return)
    trigger_score = score_trigger(hourly_close[-1], h_ema20, h_ema50, one_hour_momentum)
    volume_score = clamp((volume_ratio - 0.75) * 18, 0, 18)
    risk_score = score_risk(atr_pct, extension_pct)
    score = round(clamp(trend_score + trigger_score + volume_score + risk_score, 0, 100), 1)
    features = {
        "close": round(close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "trend_return_5d_pct": round(trend_return, 2),
        "one_hour_momentum_pct": round(one_hour_momentum, 2),
        "volume_ratio": round(volume_ratio, 2),
        "atr_pct": round(atr_pct, 2),
        "extension_pct": round(extension_pct, 2),
        "trend_score": round(trend_score, 1),
        "trigger_score": round(trigger_score, 1),
        "volume_score": round(volume_score, 1),
        "risk_score": round(risk_score, 1),
    }
    score_breakdown = {
        "trend_score": round(trend_score, 1),
        "trigger_score": round(trigger_score, 1),
        "volume_score": round(volume_score, 1),
        "risk_score": round(risk_score, 1),
        "total_score": score,
        "buy_setup_threshold": PROFILE["strict_buy_gate_score"],
        "watch_threshold": PROFILE["watch_threshold"],
        "formula": "trend + 1h trigger + volume confirmation + risk window",
    }
    label_samples = build_historical_label_samples(symbol, daily)
    historical_edge = estimate_historical_edge(label_samples)
    trend_aligned = close > ema20 > ema50 > ema200
    trigger_confirmed = hourly_close[-1] > h_ema20 > h_ema50 and one_hour_momentum >= 0.6
    volume_confirmed = volume_ratio >= 1.2
    risk_window_ok = -1.0 <= extension_pct <= 5.5 and atr_pct <= 5.0
    data_clean = daily_payload["provider_status"] in ("available", "fixture_read_only") and hourly_payload["provider_status"] in (
        "available",
        "fixture_read_only",
    )
    edge_ok = historical_edge["sample_count"] >= 10 and historical_edge["win_rate_5d"] >= 55 and historical_edge["avg_forward_return_5d"] > 0.4
    buy_gates = trend_aligned and trigger_confirmed and volume_confirmed and risk_window_ok and data_clean and edge_ok
    watch_gates = score >= 65 and close > ema50 and one_hour_momentum > -0.4 and data_clean
    level = "BUY SETUP" if score >= PROFILE["strict_buy_gate_score"] and buy_gates else "WATCH" if watch_gates else "PASS"
    risks = []
    if atr_pct > 5:
        risks.append("ATR risk is elevated; size manually and wait for cleaner structure.")
    if extension_pct > 7:
        risks.append("Price is extended above EMA20; avoid chasing a late move.")
    if extension_pct < -2:
        risks.append("Price is below the preferred EMA20 pullback window; wait for recovery confirmation.")
    if volume_ratio < 1:
        risks.append("Volume is not yet confirming the setup.")
    if not trend_aligned:
        risks.append("Daily EMA alignment is not fully bullish yet.")
    if not trigger_confirmed:
        risks.append("1h confirmation is not strong enough for a strict BUY SETUP.")
    if historical_edge["sample_count"] < 8:
        risks.append("Historical edge sample is still too small; treat this as unproven.")
    elif historical_edge["win_rate_5d"] < 52:
        risks.append("Similar historical setups do not yet show enough 5-day win rate.")
    if daily_payload["provider_status"] not in ("available", "fixture_read_only"):
        risks.append("Daily candles have provider caution.")
    if hourly_payload["provider_status"] not in ("available", "fixture_read_only"):
        risks.append("1h confirmation candles have provider caution.")
    if not risks:
        risks.append("No hard data blocker, but confirm price action manually before acting.")
    exit_risk = build_exit_risk(
        close=close,
        ema20=ema20,
        ema50=ema50,
        one_hour_momentum=one_hour_momentum,
        volume_ratio=volume_ratio,
        atr_pct=atr_pct,
        extension_pct=extension_pct,
        data_clean=data_clean,
    )
    return {
        "symbol": symbol,
        "score": score,
        "level": level,
        "direction": "LONG",
        "primary_layer": "US Stock",
        "tags": [],
        "liquidity_tier": "core",
        "trend_summary": f"Daily close {close:.2f}; EMA20 {ema20:.2f}, EMA50 {ema50:.2f}, EMA200 {ema200:.2f}.",
        "trigger_summary": f"1h momentum {one_hour_momentum:.2f}% with close {'above' if hourly_close[-1] >= h_ema20 else 'below'} EMA20.",
        "score_breakdown": score_breakdown,
        "exit_risk": exit_risk,
        "risk_warnings": risks,
        "manual_checklist": [
            "Check the daily trend and EMA20/50/200 alignment.",
            "Confirm the 1h candle structure before entry.",
            "Review ATR distance, gap risk, and volume confirmation.",
            "If this later becomes an option trade, only then review ATM option liquidity.",
        ],
        "data_status": {
            "daily_provider_status": daily_payload["provider_status"],
            "hourly_provider_status": hourly_payload["provider_status"],
            "daily_candles": len(daily),
            "hourly_candles": len(hourly),
            "source": daily_payload["source_type"],
            "freshness": daily_payload["freshness"],
            "data_quality": "clean" if data_clean else "caution",
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "features": features,
        "historical_edge": historical_edge,
        "_label_samples": label_samples,
    }


def empty_signal(symbol: str, daily_payload: dict[str, Any], hourly_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "score": 0,
        "level": "PASS",
        "direction": "LONG",
        "primary_layer": "US Stock",
        "tags": [],
        "liquidity_tier": "core",
        "trend_summary": "Not enough candles to judge daily trend.",
        "trigger_summary": "Not enough 1h candles to confirm entry.",
        "score_breakdown": {
            "trend_score": 0,
            "trigger_score": 0,
            "volume_score": 0,
            "risk_score": 0,
            "total_score": 0,
            "buy_setup_threshold": PROFILE["strict_buy_gate_score"],
            "watch_threshold": PROFILE["watch_threshold"],
            "formula": "trend + 1h trigger + volume confirmation + risk window",
        },
        "exit_risk": {
            "status": "DATA CAUTION",
            "level": "CAUTION",
            "reasons": ["Missing candles prevent exit-risk evaluation."],
            "checklist": ["Refresh data later and do not act on incomplete candles."],
        },
        "risk_warnings": ["Missing market data; skip until provider health improves."],
        "manual_checklist": ["Refresh data later and do not act on incomplete candles."],
        "data_status": {
            "daily_provider_status": daily_payload.get("provider_status", "missing"),
            "hourly_provider_status": hourly_payload.get("provider_status", "missing"),
            "daily_candles": len(daily_payload.get("candles", [])),
            "hourly_candles": len(hourly_payload.get("candles", [])),
            "source": daily_payload.get("source_type", "unknown"),
            "freshness": daily_payload.get("freshness", "missing"),
            "data_quality": "caution",
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "features": {},
        "historical_edge": empty_historical_edge(),
        "_label_samples": [],
    }


def fixture_candles_payload(symbol: str, range_value: str, interval: str) -> dict[str, Any]:
    candles = make_fixture_candles(symbol, range_value, interval)
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": "fixture_read_only",
        "provider_status": "fixture_read_only",
        "provider_errors": [],
        "freshness": "fixture",
        "candles": candles,
    }


def yahoo_candles(symbol: str, range_value: str, interval: str) -> dict[str, Any]:
    params = urlencode({"range": range_value, "interval": interval, "includePrePost": "false"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}"
    try:
        response = requests.get(url, timeout=5, headers={"User-Agent": "kquant-local-research/0.2"})
        if response.status_code == 429:
            return unavailable_candles(symbol, range_value, interval, "HTTP 429: Too Many Requests")
        response.raise_for_status()
        body = response.json()
        chart = body.get("chart", {})
        result = (chart.get("result") or [None])[0]
        if not result:
            error = chart.get("error") or {}
            return unavailable_candles(symbol, range_value, interval, str(error) or "Yahoo chart returned no result")
        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        candles: list[dict[str, Any]] = []
        for index, ts in enumerate(timestamps):
            try:
                open_ = quotes["open"][index]
                high = quotes["high"][index]
                low = quotes["low"][index]
                close = quotes["close"][index]
                volume = quotes["volume"][index] or 0
            except (KeyError, IndexError):
                continue
            if None in (open_, high, low, close):
                continue
            candles.append(
                {
                    "open_time": datetime.fromtimestamp(ts, UTC).isoformat(),
                    "time": int(ts),
                    "open": round(float(open_), 4),
                    "high": round(float(high), 4),
                    "low": round(float(low), 4),
                    "close": round(float(close), 4),
                    "volume": float(volume),
                    "source": "yahoo_chart",
                }
            )
        if not candles:
            return unavailable_candles(symbol, range_value, interval, "Yahoo chart returned 0 candles")
        return {
            "instrument_type": "stock",
            "symbol": symbol,
            "range": range_value,
            "interval": interval,
            "source_type": "live_yahoo_chart",
            "provider_status": "available",
            "provider_errors": [],
            "freshness": "live",
            "candles": candles,
        }
    except Exception as exc:  # pragma: no cover - depends on public provider/network
        return unavailable_candles(symbol, range_value, interval, str(exc))


def unavailable_candles(symbol: str, range_value: str, interval: str, error: str) -> dict[str, Any]:
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": "live_yahoo_chart",
        "provider_status": "unavailable",
        "provider_errors": [error],
        "freshness": "missing",
        "candles": [],
        "live_does_not_fallback_to_fixture": True,
    }


def cached_candles_payload(
    db_path: Path,
    symbol: str,
    range_value: str,
    interval: str,
    failed_payload: dict[str, Any],
) -> dict[str, Any] | None:
    spec = RANGES.get(range_value, RANGES["1y"])
    limit = int(spec["bars"])
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT open_time, open, high, low, close, volume, source, provider_status, created_at
            FROM stock_candles
            WHERE symbol = ? AND interval = ? AND source = 'live_yahoo_chart'
            ORDER BY open_time DESC
            LIMIT ?
            """,
            (symbol, interval, limit),
        ).fetchall()
    if not rows:
        return None
    ordered = list(reversed(rows))
    newest_created = ordered[-1]["created_at"]
    candles = [
        {
            "open_time": row["open_time"],
            "time": int(datetime.fromisoformat(row["open_time"].replace("Z", "+00:00")).timestamp()),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "source": "stale_yahoo_chart_cache",
        }
        for row in ordered
    ]
    age_seconds = max(0, int((datetime.now(UTC) - datetime.fromisoformat(newest_created)).total_seconds()))
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": "stale_yahoo_chart_cache",
        "provider_status": "stale_cache",
        "provider_errors": failed_payload.get("provider_errors", []),
        "freshness": f"stale {age_seconds}s",
        "freshness_seconds": age_seconds,
        "candles": candles,
        "live_does_not_fallback_to_fixture": True,
    }


def make_fixture_candles(symbol: str, range_value: str, interval: str) -> list[dict[str, Any]]:
    spec = RANGES.get(range_value, RANGES["1y"])
    bars = int(spec["bars"])
    seed = sum((index + 1) * ord(char) for index, char in enumerate(symbol))
    base = 42 + (seed % 520)
    if symbol in {"SPY", "QQQ", "DIA", "IWM"}:
        base += 180
    trend_bias = ((seed % 19) - 7) / 1000
    if any(tag in symbol for tag in ("NVDA", "MSFT", "AMZN", "AVGO", "PLTR", "AMD")):
        trend_bias += 0.0018
    now = datetime(2026, 6, 17, 20, 0, tzinfo=UTC)
    timestamps = fixture_market_timestamps(range_value, interval, now)
    price = float(base)
    candles: list[dict[str, Any]] = []
    for index, open_time in enumerate(timestamps[-bars:]):
        wave = math.sin((index + seed) * 0.17) * 0.018 + math.cos((index + seed) * 0.047) * 0.009
        impulse = math.sin((index + seed) * 0.61) * 0.004
        drift = trend_bias + wave * 0.18 + impulse
        open_ = price
        close = max(3.0, price * (1 + drift))
        spread = max(close * (0.005 + abs(wave) * 0.8), 0.05)
        high = max(open_, close) + spread
        low = max(0.5, min(open_, close) - spread * 0.84)
        volume = int(900_000 + (seed % 800_000) + abs(wave) * 35_000_000 + (index % 17) * 41_000)
        candles.append(
            {
                "open_time": open_time.isoformat(),
                "time": int(open_time.timestamp()),
                "open": round(open_, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "close": round(close, 4),
                "volume": volume,
                "source": "fixture",
            }
        )
        price = close
    return candles


def fixture_market_timestamps(range_value: str, interval: str, end: datetime) -> list[datetime]:
    spec = RANGES.get(range_value, RANGES["1y"])
    bars = int(spec["bars"])
    if interval == "1d":
        return [
            datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
            for day in previous_trading_days(end, bars)
        ]
    if interval == "1wk":
        return [
            datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
            for day in previous_weekly_trading_days(end, bars)
        ]
    if interval == "1mo":
        return [
            datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
            for day in previous_monthly_trading_days(end, bars)
        ]
    if range_value == "1d" and interval == "5m":
        day = previous_trading_days(end, 1)[-1]
        start = datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
        return [start + timedelta(minutes=5 * index) for index in range(78)]
    if range_value == "5d" and interval == "1h":
        timestamps: list[datetime] = []
        for day in previous_trading_days(end, 5):
            start = datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
            timestamps.extend(start + timedelta(hours=index) for index in range(7))
        return timestamps
    step = spec["step"]
    start = end - step * bars
    return [start + step * index for index in range(bars)]


def previous_trading_days(end: datetime, count: int) -> list[datetime]:
    day = datetime(end.year, end.month, end.day, tzinfo=UTC)
    days: list[datetime] = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return list(reversed(days))


def previous_weekly_trading_days(end: datetime, count: int) -> list[datetime]:
    anchor = previous_trading_days(end, 1)[-1]
    days: list[datetime] = []
    cursor = anchor
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=7)
    return list(reversed(days))


def previous_monthly_trading_days(end: datetime, count: int) -> list[datetime]:
    months: list[datetime] = []
    year = end.year
    month = end.month
    while len(months) < count:
        first = datetime(year, month, 1, tzinfo=UTC)
        cursor = first
        while cursor.weekday() >= 5:
            cursor += timedelta(days=1)
        if cursor <= end:
            months.append(cursor)
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


def persist_candles(db_path: Path, payload: dict[str, Any]) -> None:
    now = iso_now()
    with connect(db_path) as conn:
        for candle in payload.get("candles", []):
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_candles
                (symbol, interval, open_time, open, high, low, close, volume, source, provider_status, freshness_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["symbol"],
                    payload["interval"],
                    candle["open_time"],
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                    candle["volume"],
                    payload["source_type"],
                    payload["provider_status"],
                    0,
                    now,
                ),
            )
        provider_name = "fixture" if payload["source_type"] == "fixture_read_only" else "yahoo_chart"
        messages = payload.get("provider_errors", []) or [f"{len(payload.get('candles', []))} candles from {payload['source_type']}"]
        for message in messages:
            conn.execute(
                """
                INSERT INTO provider_events(provider, instrument, symbol, status, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (provider_name, "stock", payload["symbol"], payload["provider_status"], str(message), now),
            )
        conn.commit()


def record_provider_event(
    db_path: Path,
    provider: str,
    instrument: str,
    symbol: str,
    status: str,
    message: str,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO provider_events(provider, instrument, symbol, status, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (provider, instrument, symbol, status, message, iso_now()),
        )
        conn.commit()


def persist_signal_run(db_path: Path, payload: dict[str, Any]) -> None:
    now = iso_now()
    label_samples_by_symbol = payload.get("_label_samples_by_symbol", {})
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO stock_signal_runs
            (run_id, source, universe, profile, started_at, completed_at, provider_status,
             provider_error_count, buy_setup_count, watch_count, pass_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["source"],
                payload["universe"],
                payload["profile"]["name"],
                payload["started_at"],
                payload["completed_at"],
                payload["provider_status"],
                payload["provider_error_count"],
                payload["counts"]["buy_setup"],
                payload["counts"]["watch"],
                payload["counts"]["pass"],
            ),
        )
        for signal in payload["signals"]:
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_signals
                (run_id, symbol, score, level, trend_summary, trigger_summary,
                 risk_warnings_json, manual_checklist_json, data_status_json, features_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    signal["symbol"],
                    signal["score"],
                    signal["level"],
                    signal["trend_summary"],
                    signal["trigger_summary"],
                    json.dumps(signal["risk_warnings"]),
                    json.dumps(signal["manual_checklist"]),
                    json.dumps(signal["data_status"]),
                    json.dumps(signal["features"]),
                    now,
                ),
            )
            feature_time = signal.get("data_status", {}).get("freshness", now)
            conn.execute(
                """
                INSERT OR REPLACE INTO stock_features
                (run_id, symbol, feature_time, profile, features_json, data_status_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["run_id"],
                    signal["symbol"],
                    str(feature_time),
                    payload["profile"]["name"],
                    json.dumps(signal["features"]),
                    json.dumps(signal["data_status"]),
                    now,
                ),
            )
            for sample in label_samples_by_symbol.get(signal["symbol"], []):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO stock_labels
                    (run_id, symbol, signal_time, forward_return_3d, forward_return_5d, forward_return_10d,
                     max_drawdown_5d, hit_target_before_stop, close_above_entry_after_5d, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["run_id"],
                        signal["symbol"],
                        sample["signal_time"],
                        sample["forward_return_3d"],
                        sample["forward_return_5d"],
                        sample["forward_return_10d"],
                        sample["max_drawdown_5d"],
                        sample["hit_target_before_stop"],
                        sample["close_above_entry_after_5d"],
                        now,
                    ),
                )
        validation = payload.get("historical_validation", {})
        conn.execute(
            """
            INSERT OR REPLACE INTO stock_backtest_runs
            (run_id, profile, sample_count, win_rate_5d, avg_forward_return_5d, avg_max_drawdown_5d,
             buy_setup_count, watch_count, pass_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["profile"]["name"],
                int(validation.get("sample_count", 0)),
                float(validation.get("win_rate_5d", 0.0)),
                float(validation.get("avg_forward_return_5d", 0.0)),
                float(validation.get("avg_max_drawdown_5d", 0.0)),
                payload["counts"]["buy_setup"],
                payload["counts"]["watch"],
                payload["counts"]["pass"],
                now,
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
            ("stock_signal_run", json.dumps({"run_id": payload["run_id"], "counts": payload["counts"]}), now),
        )
        conn.commit()


def write_reports(outputs_dir: Path, payload: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    public_payload = {key: value for key, value in payload.items() if not key.startswith("_")}
    (outputs_dir / "stock-signals-report.json").write_text(json.dumps(public_payload, indent=2), encoding="utf-8")
    validation = payload.get("historical_validation", {})
    lines = [
        "# KQUANT US Stock Signals",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Source: `{payload['source']}`",
        f"- Universe: `{payload['universe']}`",
        f"- Profile: `{payload['profile']['name']}`",
        f"- Provider: `{payload['provider_status']}` / errors `{payload['provider_error_count']}`",
        f"- Counts: BUY SETUP `{payload['counts']['buy_setup']}`, WATCH `{payload['counts']['watch']}`, PASS `{payload['counts']['pass']}`",
        "",
        "## Historical Validation",
        "",
        f"- Samples: `{validation.get('sample_count', 0)}`",
        f"- 5D win rate: `{validation.get('win_rate_5d', 0)}%`",
        f"- Avg 5D return: `{validation.get('avg_forward_return_5d', 0)}%`",
        f"- Avg 5D drawdown: `{validation.get('avg_max_drawdown_5d', 0)}%`",
        "- Note: historical labels are research validation, not an execution signal.",
        "",
        "## Top Setups",
        "",
    ]
    for signal in payload["signals"][:20]:
        lines.extend(
            [
                f"### {signal['symbol']} - {signal['level']} - {signal['score']}/100",
                "",
                f"- Layer: {signal.get('primary_layer', 'US Stock')} / {signal.get('liquidity_tier', 'core')}",
                f"- Trend: {signal['trend_summary']}",
                f"- Trigger: {signal['trigger_summary']}",
                f"- Score Breakdown: {signal.get('score_breakdown', {})}",
                f"- Exit Risk: {signal.get('exit_risk', {})}",
                f"- Historical Edge: {signal.get('historical_edge', empty_historical_edge())}",
                f"- Data: {signal['data_status']}",
                f"- Risks: {'; '.join(signal['risk_warnings'])}",
                "",
            ]
        )
    (outputs_dir / "stock-signals-report.md").write_text("\n".join(lines), encoding="utf-8")


def normalize_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol or "SPY").upper() if ch.isalnum() or ch in ".-")[:16] or "SPY"


def normalize_range_interval(range_value: str, interval: str) -> tuple[str, str]:
    normalized_range = (range_value or "1y").lower()
    if normalized_range not in RANGES:
        normalized_range = "1y"
    expected_interval = str(RANGES[normalized_range]["interval"])
    normalized_interval = (interval or expected_interval).lower()
    if normalized_interval != expected_interval:
        normalized_interval = expected_interval
    return normalized_range, normalized_interval


def build_exit_risk(
    *,
    close: float,
    ema20: float,
    ema50: float,
    one_hour_momentum: float,
    volume_ratio: float,
    atr_pct: float,
    extension_pct: float,
    data_clean: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    status = "CLEAR"
    level = "HOLD"
    if not data_clean:
        status = "DATA CAUTION"
        level = "CAUTION"
        reasons.append("Provider or freshness caution; do not rely on the setup until candles are clean.")
    if close < ema50:
        status = "SETUP INVALIDATED"
        level = "EXIT RISK"
        reasons.append("Daily close is below EMA50; long setup structure is invalidated.")
    elif close < ema20:
        status = "EXIT RISK"
        level = "CAUTION"
        reasons.append("Daily close is below EMA20; momentum is losing the preferred trend support.")
    if one_hour_momentum < -0.7:
        status = "EXIT RISK" if status == "CLEAR" else status
        level = "CAUTION" if level == "HOLD" else level
        reasons.append("1h momentum is negative enough to require manual risk review.")
    if volume_ratio >= 1.6 and one_hour_momentum < 0:
        status = "EXIT RISK"
        level = "EXIT RISK"
        reasons.append("Downside 1h momentum is appearing with elevated volume.")
    if atr_pct > 6:
        status = "EXIT RISK" if status == "CLEAR" else status
        level = "CAUTION" if level == "HOLD" else level
        reasons.append("ATR is elevated; position risk is expanding.")
    if extension_pct > 8:
        status = "TAKE PROFIT WATCH" if status == "CLEAR" else status
        level = "CAUTION" if level == "HOLD" else level
        reasons.append("Price is extended above EMA20; avoid adding and consider profit protection.")
    if not reasons:
        reasons.append("No exit-risk trigger from trend, 1h momentum, ATR, or extension checks.")
    return {
        "status": status,
        "level": level,
        "reasons": reasons,
        "checklist": [
            "If already watching or holding, review daily EMA20/EMA50 support first.",
            "Confirm whether 1h momentum is improving or deteriorating.",
            "Use this as a manual risk reminder, not an automated sell instruction.",
        ],
    }


def score_trend(close: float, ema20: float, ema50: float, ema200: float, trend_return: float) -> float:
    score = 0.0
    if close > ema20:
        score += 14
    if ema20 > ema50:
        score += 14
    if ema50 > ema200:
        score += 14
    score += clamp(trend_return * 2.2, -8, 18)
    return clamp(score, 0, 52)


def score_trigger(close: float, ema20: float, ema50: float, momentum: float) -> float:
    score = 0.0
    if close > ema20:
        score += 12
    if ema20 > ema50:
        score += 7
    score += clamp(momentum * 3.0, -8, 11)
    return clamp(score, 0, 30)


def score_risk(atr_pct: float, extension_pct: float) -> float:
    score = 18.0
    if atr_pct > 5:
        score -= min(8, (atr_pct - 5) * 1.4)
    if extension_pct > 7:
        score -= min(7, (extension_pct - 7) * 1.0)
    if extension_pct < -2:
        score -= min(5, abs(extension_pct) * 0.8)
    return clamp(score, 0, 18)


def ema_last(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    multiplier = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value - current) * multiplier + current
    return current


def average_true_range_pct(candles: list[dict[str, Any]]) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )
        ranges.append(true_range / max(current["close"], 0.01) * 100)
    return sum(ranges) / max(len(ranges), 1)


def build_historical_label_samples(symbol: str, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    if len(candles) < 90:
        return samples
    for index in range(70, len(candles) - 10):
        window = candles[: index + 1]
        closes = [bar["close"] for bar in window]
        volumes = [bar["volume"] for bar in window]
        close = closes[-1]
        ema20 = ema_last(closes, 20)
        ema50 = ema_last(closes, 50)
        ema200 = ema_last(closes, 200)
        trend_return = pct(close, closes[-6] if len(closes) > 6 else closes[0])
        volume_ratio = volumes[-1] / max(sum(volumes[-21:-1]) / max(len(volumes[-21:-1]), 1), 1)
        atr_pct = average_true_range_pct(window[-20:])
        extension_pct = pct(close, ema20)
        daily_score = (
            score_trend(close, ema20, ema50, ema200, trend_return)
            + clamp((volume_ratio - 0.75) * 12, 0, 12)
            + score_risk(atr_pct, extension_pct)
        )
        if daily_score < 54 or close < ema50:
            continue
        future = candles[index + 1 : index + 11]
        if len(future) < 10:
            continue
        entry = close
        forward_3d = pct(future[2]["close"], entry)
        forward_5d = pct(future[4]["close"], entry)
        forward_10d = pct(future[9]["close"], entry)
        max_drawdown_5d = min(pct(bar["low"], entry) for bar in future[:5])
        max_runup_5d = max(pct(bar["high"], entry) for bar in future[:5])
        samples.append(
            {
                "symbol": symbol,
                "signal_time": candles[index]["open_time"],
                "setup_score": round(daily_score, 1),
                "forward_return_3d": round(forward_3d, 4),
                "forward_return_5d": round(forward_5d, 4),
                "forward_return_10d": round(forward_10d, 4),
                "max_drawdown_5d": round(max_drawdown_5d, 4),
                "hit_target_before_stop": int(max_runup_5d >= 2.5 and max_drawdown_5d > -3.5),
                "close_above_entry_after_5d": int(forward_5d > 0),
            }
        )
    return samples[-80:]


def estimate_historical_edge(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return empty_historical_edge()
    returns_5d = [float(sample["forward_return_5d"]) for sample in samples]
    drawdowns_5d = [float(sample["max_drawdown_5d"]) for sample in samples]
    hit_count = sum(int(sample["hit_target_before_stop"]) for sample in samples)
    win_count = sum(1 for value in returns_5d if value > 0)
    return {
        "sample_count": len(samples),
        "win_rate_5d": round(win_count / len(samples) * 100, 1),
        "target_hit_rate_5d": round(hit_count / len(samples) * 100, 1),
        "avg_forward_return_3d": round(sum(float(sample["forward_return_3d"]) for sample in samples) / len(samples), 2),
        "avg_forward_return_5d": round(sum(returns_5d) / len(samples), 2),
        "avg_forward_return_10d": round(sum(float(sample["forward_return_10d"]) for sample in samples) / len(samples), 2),
        "avg_max_drawdown_5d": round(sum(drawdowns_5d) / len(samples), 2),
        "verdict": "positive" if win_count / len(samples) >= 0.52 and sum(returns_5d) / len(samples) > 0.2 else "unproven",
    }


def empty_historical_edge() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "win_rate_5d": 0.0,
        "target_hit_rate_5d": 0.0,
        "avg_forward_return_3d": 0.0,
        "avg_forward_return_5d": 0.0,
        "avg_forward_return_10d": 0.0,
        "avg_max_drawdown_5d": 0.0,
        "verdict": "missing",
    }


def summarize_label_samples(label_samples_by_symbol: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    samples = [sample for symbol_samples in label_samples_by_symbol.values() for sample in symbol_samples]
    edge = estimate_historical_edge(samples)
    return {
        "method": "rule-candidate forward return labels",
        "sample_count": edge["sample_count"],
        "win_rate_5d": edge["win_rate_5d"],
        "target_hit_rate_5d": edge["target_hit_rate_5d"],
        "avg_forward_return_5d": edge["avg_forward_return_5d"],
        "avg_max_drawdown_5d": edge["avg_max_drawdown_5d"],
        "note": "Historical labels are for research validation, not an execution signal.",
    }


def pct(value: float, reference: float) -> float:
    return (value / max(reference, 0.0001) - 1) * 100


def clamp(value: float, min_value: float, max_value: float) -> float:
    return min(max(value, min_value), max_value)


def iso_now() -> str:
    return datetime.now(UTC).isoformat()
