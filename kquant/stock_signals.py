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
    "5d": {"bars": 130, "step": timedelta(minutes=15), "interval": "15m"},
    "1mo": {"bars": 22, "step": timedelta(days=1), "interval": "1d"},
    "3mo": {"bars": 66, "step": timedelta(days=1), "interval": "1d"},
    "1y": {"bars": 252, "step": timedelta(days=1), "interval": "1d"},
}
PROFILE = {
    "name": "swing_long_v1",
    "buy_setup_threshold": 82,
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
    return {
        "provider_status": "degraded" if error_count else "available",
        "provider_error_count": error_count,
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
    symbols = [stock.symbol for stock in stock_universe(universe)]
    if limit:
        symbols = symbols[: max(1, min(limit, len(symbols)))]
    started = iso_now()
    signals: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    for symbol in symbols:
        daily = api_stock_candles(symbol, "1y", "1d", source, db)
        hourly = api_stock_candles(symbol, "5d", "1h", source, db)
        if daily["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: daily {daily['provider_status']}")
        if hourly["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: 1h {hourly['provider_status']}")
        signal = build_signal(symbol, daily, hourly)
        signals.append(signal)
    signals.sort(key=lambda item: item["score"], reverse=True)
    completed = iso_now()
    run_id = f"stock-{int(time.time())}"
    provider_status = "degraded" if provider_errors else ("fixture_read_only" if source == "fixture" else "available")
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
            return json.loads(report.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return api_stock_signals(source=source, universe=universe, profile=profile, db_path=db_path, outputs_dir=outputs)


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
    level = "BUY SETUP" if score >= 82 else "WATCH" if score >= 65 else "PASS"
    risks = []
    if atr_pct > 5:
        risks.append("ATR risk is elevated; size manually and wait for cleaner structure.")
    if extension_pct > 7:
        risks.append("Price is extended above EMA20; avoid chasing a late move.")
    if volume_ratio < 1:
        risks.append("Volume is not yet confirming the setup.")
    if daily_payload["provider_status"] not in ("available", "fixture_read_only"):
        risks.append("Daily candles have provider caution.")
    if hourly_payload["provider_status"] not in ("available", "fixture_read_only"):
        risks.append("1h confirmation candles have provider caution.")
    if not risks:
        risks.append("No hard data blocker, but confirm price action manually before acting.")
    return {
        "symbol": symbol,
        "score": score,
        "level": level,
        "direction": "LONG",
        "trend_summary": f"Daily close {close:.2f}; EMA20 {ema20:.2f}, EMA50 {ema50:.2f}, EMA200 {ema200:.2f}.",
        "trigger_summary": f"1h momentum {one_hour_momentum:.2f}% with close {'above' if hourly_close[-1] >= h_ema20 else 'below'} EMA20.",
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
        },
        "features": {
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
        },
    }


def empty_signal(symbol: str, daily_payload: dict[str, Any], hourly_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "score": 0,
        "level": "PASS",
        "direction": "LONG",
        "trend_summary": "Not enough candles to judge daily trend.",
        "trigger_summary": "Not enough 1h candles to confirm entry.",
        "risk_warnings": ["Missing market data; skip until provider health improves."],
        "manual_checklist": ["Refresh data later and do not act on incomplete candles."],
        "data_status": {
            "daily_provider_status": daily_payload.get("provider_status", "missing"),
            "hourly_provider_status": hourly_payload.get("provider_status", "missing"),
            "daily_candles": len(daily_payload.get("candles", [])),
            "hourly_candles": len(hourly_payload.get("candles", [])),
            "source": daily_payload.get("source_type", "unknown"),
            "freshness": daily_payload.get("freshness", "missing"),
        },
        "features": {},
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


def make_fixture_candles(symbol: str, range_value: str, interval: str) -> list[dict[str, Any]]:
    spec = RANGES.get(range_value, RANGES["1y"])
    bars = int(spec["bars"])
    step = spec["step"]
    seed = sum((index + 1) * ord(char) for index, char in enumerate(symbol))
    base = 42 + (seed % 520)
    if symbol in {"SPY", "QQQ", "DIA", "IWM"}:
        base += 180
    trend_bias = ((seed % 19) - 7) / 1000
    if any(tag in symbol for tag in ("NVDA", "MSFT", "AMZN", "AVGO", "PLTR", "AMD")):
        trend_bias += 0.0018
    now = datetime(2026, 6, 17, 20, 0, tzinfo=UTC)
    start = now - step * bars
    price = float(base)
    candles: list[dict[str, Any]] = []
    for index in range(bars):
        wave = math.sin((index + seed) * 0.17) * 0.018 + math.cos((index + seed) * 0.047) * 0.009
        impulse = math.sin((index + seed) * 0.61) * 0.004
        drift = trend_bias + wave * 0.18 + impulse
        open_ = price
        close = max(3.0, price * (1 + drift))
        spread = max(close * (0.005 + abs(wave) * 0.8), 0.05)
        high = max(open_, close) + spread
        low = max(0.5, min(open_, close) - spread * 0.84)
        volume = int(900_000 + (seed % 800_000) + abs(wave) * 35_000_000 + (index % 17) * 41_000)
        open_time = start + step * index
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
        for message in payload.get("provider_errors", []):
            conn.execute(
                """
                INSERT INTO provider_events(provider, instrument, symbol, status, message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("yahoo_chart", "stock", payload["symbol"], payload["provider_status"], str(message), now),
            )
        conn.commit()


def persist_signal_run(db_path: Path, payload: dict[str, Any]) -> None:
    now = iso_now()
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
        conn.execute(
            "INSERT INTO audit_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
            ("stock_signal_run", json.dumps({"run_id": payload["run_id"], "counts": payload["counts"]}), now),
        )
        conn.commit()


def write_reports(outputs_dir: Path, payload: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "stock-signals-report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
        "## Top Setups",
        "",
    ]
    for signal in payload["signals"][:20]:
        lines.extend(
            [
                f"### {signal['symbol']} - {signal['level']} - {signal['score']}/100",
                "",
                f"- Trend: {signal['trend_summary']}",
                f"- Trigger: {signal['trigger_summary']}",
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
    normalized_interval = (interval or RANGES[normalized_range]["interval"]).lower()
    allowed = {"5m", "15m", "1h", "1d"}
    if normalized_interval not in allowed:
        normalized_interval = str(RANGES[normalized_range]["interval"])
    return normalized_range, normalized_interval


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


def pct(value: float, reference: float) -> float:
    return (value / max(reference, 0.0001) - 1) * 100


def clamp(value: float, min_value: float, max_value: float) -> float:
    return min(max(value, min_value), max_value)


def iso_now() -> str:
    return datetime.now(UTC).isoformat()
