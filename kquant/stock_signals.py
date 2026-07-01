from __future__ import annotations

import json
import math
import os
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
HEALTH_TIMEFRAMES = [
    {"key": "1H", "range": "5d", "interval": "1h"},
    {"key": "1D", "range": "1y", "interval": "1d"},
    {"key": "1W", "range": "5y", "interval": "1wk"},
    {"key": "1M", "range": "10y", "interval": "1mo"},
]
MARKET_OPEN_UTC_HOUR = 13
MARKET_OPEN_UTC_MINUTE = 30
MARKET_CLOSE_UTC_HOUR = 20
PROFILE_CONFIGS: dict[str, dict[str, Any]] = {
    "swing_long_v1": {
        "name": "swing_long_v1",
        "label": "1W Tactical",
        "holding_period": "3-7 trading days",
        "buy_setup_threshold": 82,
        "strict_buy_gate_score": 88,
        "watch_threshold": 65,
        "direction": "long_only",
        "primary_range": "1y",
        "primary_interval": "1d",
        "confirmation_range": "5d",
        "confirmation_interval": "1h",
        "primary_timeframe": "1D",
        "confirmation_timeframe": "1H",
        "focus_window": "5D",
        "focus_horizon_bars": 5,
        "target_return_pct": 2.0,
        "max_atr_pct": 5.0,
        "max_extension_pct": 5.5,
        "confirmation_momentum_min": 0.6,
        "volume_ratio_min": 1.2,
        "focus_win_rate_min": 55.0,
        "focus_avg_return_min": 0.4,
        "formula": "daily trend + 1h trigger + volume confirmation + short risk window",
    },
    "tactical_1w_v1": {
        "name": "tactical_1w_v1",
        "label": "1W Tactical",
        "holding_period": "3-7 trading days",
        "buy_setup_threshold": 82,
        "strict_buy_gate_score": 88,
        "watch_threshold": 65,
        "direction": "long_only",
        "primary_range": "1y",
        "primary_interval": "1d",
        "confirmation_range": "5d",
        "confirmation_interval": "1h",
        "primary_timeframe": "1D",
        "confirmation_timeframe": "1H",
        "focus_window": "5D",
        "focus_horizon_bars": 5,
        "target_return_pct": 2.0,
        "max_atr_pct": 5.0,
        "max_extension_pct": 5.5,
        "confirmation_momentum_min": 0.6,
        "volume_ratio_min": 1.2,
        "focus_win_rate_min": 55.0,
        "focus_avg_return_min": 0.4,
        "formula": "EMA10/20/50 momentum + 1h confirmation + volume expansion + ATR discipline",
    },
    "swing_1_2m_v1": {
        "name": "swing_1_2m_v1",
        "label": "1-2M Swing",
        "holding_period": "20-40 trading days",
        "buy_setup_threshold": 78,
        "strict_buy_gate_score": 84,
        "watch_threshold": 62,
        "direction": "long_only",
        "primary_range": "1y",
        "primary_interval": "1d",
        "confirmation_range": "5y",
        "confirmation_interval": "1wk",
        "primary_timeframe": "1D",
        "confirmation_timeframe": "1W",
        "focus_window": "40D",
        "focus_horizon_bars": 40,
        "target_return_pct": 6.0,
        "max_atr_pct": 6.5,
        "max_extension_pct": 9.0,
        "confirmation_momentum_min": 0.0,
        "volume_ratio_min": 1.05,
        "focus_win_rate_min": 53.0,
        "focus_avg_return_min": 1.8,
        "formula": "daily EMA20/50/200 + weekly trend confirmation + relative strength + volume structure",
    },
    "position_6m_v1": {
        "name": "position_6m_v1",
        "label": "6M Position",
        "holding_period": "3-6 months",
        "buy_setup_threshold": 76,
        "strict_buy_gate_score": 82,
        "watch_threshold": 60,
        "direction": "long_only",
        "primary_range": "5y",
        "primary_interval": "1wk",
        "confirmation_range": "1y",
        "confirmation_interval": "1d",
        "primary_timeframe": "1W",
        "confirmation_timeframe": "1D",
        "focus_window": "126D",
        "focus_horizon_bars": 26,
        "target_return_pct": 12.0,
        "max_atr_pct": 8.0,
        "max_extension_pct": 14.0,
        "confirmation_momentum_min": -0.5,
        "volume_ratio_min": 0.9,
        "focus_win_rate_min": 52.0,
        "focus_avg_return_min": 4.0,
        "formula": "weekly EMA20/50 trend + daily support + layer strength + drawdown tolerance",
    },
    "cycle_1_3y_v1": {
        "name": "cycle_1_3y_v1",
        "label": "1-3Y Cycle",
        "holding_period": "1-3 years",
        "buy_setup_threshold": 72,
        "strict_buy_gate_score": 80,
        "watch_threshold": 58,
        "direction": "long_only",
        "primary_range": "10y",
        "primary_interval": "1mo",
        "confirmation_range": "5y",
        "confirmation_interval": "1wk",
        "primary_timeframe": "1M",
        "confirmation_timeframe": "1W",
        "focus_window": "504D",
        "focus_horizon_bars": 24,
        "target_return_pct": 35.0,
        "max_atr_pct": 12.0,
        "max_extension_pct": 24.0,
        "confirmation_momentum_min": -1.0,
        "volume_ratio_min": 0.75,
        "focus_win_rate_min": 50.0,
        "focus_avg_return_min": 10.0,
        "formula": "monthly/weekly cycle trend + distance from extremes + long relative strength + narrative risk",
    },
}
PROFILE = PROFILE_CONFIGS["swing_long_v1"]
MARKET_REGIME_SYMBOLS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "^VIX": "VIX",
}
STOCK_JOURNAL_STATUSES = {"reviewed", "watch", "skipped", "paper-observed", "manual-traded", "invalidated"}


def profile_config(profile: str | None = None) -> dict[str, Any]:
    key = str(profile or "swing_long_v1")
    return PROFILE_CONFIGS.get(key, PROFILE_CONFIGS["swing_long_v1"])


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


SEARCH_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "英伟达": ("nvda", "nvidia", "gpu", "accelerator", "chips", "ai compute"),
    "微软": ("msft", "microsoft", "cloud", "ai cloud"),
    "谷歌": ("googl", "alphabet", "google", "search", "cloud"),
    "亚马逊": ("amzn", "amazon", "aws", "cloud"),
    "特斯拉": ("tsla", "tesla", "robotics", "autonomy", "ev"),
    "机器人": ("robot", "robotics", "automation", "autonomy", "space robotics"),
    "太空": ("space", "rocket", "satellite", "aerospace", "space robotics"),
    "航天": ("space", "rocket", "satellite", "aerospace", "space robotics"),
    "芯片": ("chips", "semis", "semiconductor", "ai semis", "foundry"),
    "半导体": ("chips", "semis", "semiconductor", "ai semis", "foundry"),
    "云": ("cloud", "ai cloud", "infrastructure"),
    "网络安全": ("security", "cybersecurity", "ai security"),
    "能源": ("energy", "power", "nuclear", "grid"),
    "核电": ("nuclear", "uranium", "power", "ai energy"),
    "比特币": ("bitcoin", "btc", "crypto", "mstr", "coin"),
}

STOCK_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "NVDA": ("英伟达", "nvidia", "gpu", "accelerator"),
    "MSFT": ("微软", "microsoft", "azure"),
    "GOOGL": ("谷歌", "google", "alphabet", "gemini"),
    "AMZN": ("亚马逊", "amazon", "aws"),
    "TSLA": ("特斯拉", "tesla", "robotaxi", "autonomy"),
    "MSTR": ("microstrategy", "strategy", "比特币", "bitcoin", "btc"),
    "RKLB": ("rocket lab", "火箭", "太空", "space"),
    "ASTS": ("satellite", "space mobile", "太空", "卫星"),
    "LUNR": ("moon", "lunar", "space", "太空"),
    "BOTZ": ("robotics etf", "机器人", "automation"),
    "ROBO": ("robotics etf", "机器人", "automation"),
    "ISRG": ("surgical robot", "机器人", "robotics"),
    "SYM": ("warehouse robot", "机器人", "automation"),
}


def expanded_search_terms(raw_query: str) -> list[str]:
    query = str(raw_query or "").strip().lower()
    if not query:
        return []
    terms = [query]
    for alias, expansions in SEARCH_QUERY_ALIASES.items():
        if alias in query:
            terms.extend(item.lower() for item in expansions)
    compact = query.replace(" ", "")
    if compact != query:
        terms.append(compact)
    return list(dict.fromkeys(term for term in terms if term))


def api_stock_search(q: str = "", universe: str = "all", limit: int = 24) -> dict[str, Any]:
    query = str(q or "").strip().lower()
    terms = expanded_search_terms(query)
    limit = max(1, min(int(limit or 24), 50))
    stocks = stock_universe(universe or "all")
    matches: list[dict[str, Any]] = []

    def score_stock(stock: Any) -> int:
        if not terms:
            return 10 if stock.symbol in {"NVDA", "MSTR", "SPY", "QQQ", "RKLB", "TSLA"} else 1
        symbol = stock.symbol.lower()
        name = stock.name.lower()
        layer = stock.layer.lower()
        tags = " ".join(stock.tags).lower()
        aliases = " ".join(STOCK_SEARCH_ALIASES.get(stock.symbol, ())).lower()
        haystack = f"{symbol} {name} {stock.sector.lower()} {layer} {tags} {aliases}"
        score = 0
        for index, term in enumerate(terms):
            weight = 1.0 if index == 0 else 0.72
            if symbol == term:
                score += int(140 * weight)
            if symbol.startswith(term):
                score += int(95 * weight)
            if term in symbol:
                score += int(70 * weight)
            if name.startswith(term):
                score += int(64 * weight)
            if term in name:
                score += int(48 * weight)
            if term in aliases:
                score += int(46 * weight)
            if term in layer:
                score += int(38 * weight)
            if term in tags:
                score += int(34 * weight)
            if term in haystack:
                score += int(12 * weight)
        return score

    for stock in stocks:
        score = score_stock(stock)
        if query and score <= 0:
            continue
        item = stock.to_dict()
        item["match_score"] = score
        item["aliases"] = list(STOCK_SEARCH_ALIASES.get(stock.symbol, ()))
        item["matched_terms"] = terms
        item["search_text"] = f"{stock.symbol} {stock.name} {stock.layer} {' '.join(stock.tags)} {' '.join(item['aliases'])}"
        matches.append(item)

    matches.sort(key=lambda item: (-int(item.get("match_score", 0)), int(item.get("rank", 9999)), str(item.get("symbol", ""))))
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "query": q,
        "expanded_terms": terms,
        "universe": universe or "all",
        "count": len(matches[:limit]),
        "results": matches[:limit],
        "source": "stock_universe_live_only_metadata",
        "live_data_required_for_analysis": True,
        "fixture_user_visible": False,
    }


def api_stock_candles(
    symbol: str,
    range_value: str = "1y",
    interval: str = "1d",
    source: str = "live",
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


def api_stock_market_regime(source: str = "live", db_path: Path | None = None) -> dict[str, Any]:
    db = db_path or default_db_path()
    source = "live" if source != "fixture" else "fixture"
    components: dict[str, dict[str, Any]] = {}
    provider_errors: list[str] = []
    for symbol, label in MARKET_REGIME_SYMBOLS.items():
        payload = api_stock_candles(symbol, "1y", "1d", source, db)
        component = market_regime_component(symbol, label, payload)
        components[symbol] = component
        if component["provider_status"] != "available":
            provider_errors.append(f"{symbol}: {component['provider_status']}")

    spy = components.get("SPY", {})
    qqq = components.get("QQQ", {})
    iwm = components.get("IWM", {})
    vix = components.get("^VIX", {})
    data_clean = not provider_errors
    spy_bull = bool(spy.get("above_ema50") and spy.get("ema20_above_ema50") and spy.get("above_ema200"))
    qqq_bull = bool(qqq.get("above_ema50") and qqq.get("ema20_above_ema50") and qqq.get("above_ema200"))
    iwm_bull = bool(iwm.get("above_ema50") and iwm.get("above_ema200"))
    vix_close = float(vix.get("close") or 99.0)
    vix_calm = vix_close < 22
    vix_stressed = vix_close >= 28
    risk_off = bool(
        not data_clean
        or vix_stressed
        or spy.get("below_ema200")
        or qqq.get("below_ema200")
        or spy.get("return_20d_pct", 0) <= -8
        or qqq.get("return_20d_pct", 0) <= -10
    )
    risk_on = bool(data_clean and spy_bull and qqq_bull and vix_calm and iwm_bull)
    if not data_clean:
        regime = "DATA_CAUTION"
        label = "Data Caution"
    elif risk_off:
        regime = "RISK_OFF"
        label = "Risk Off"
    elif risk_on:
        regime = "RISK_ON"
        label = "Risk On"
    else:
        regime = "MIXED"
        label = "Mixed"
    score = 0
    score += 24 if spy_bull else 8 if spy.get("above_ema50") else 0
    score += 24 if qqq_bull else 8 if qqq.get("above_ema50") else 0
    score += 14 if iwm_bull else 5 if iwm.get("above_ema50") else 0
    score += 18 if vix_calm else 8 if vix_close < 28 else 0
    score += 10 if spy.get("return_20d_pct", 0) > 0 else 0
    score += 10 if qqq.get("return_20d_pct", 0) > 0 else 0
    score = int(clamp(score, 0, 100))
    reasons: list[str] = []
    if data_clean:
        reasons.append(f"SPY {'above' if spy.get('above_ema50') else 'below'} EMA50; QQQ {'above' if qqq.get('above_ema50') else 'below'} EMA50.")
        reasons.append(f"VIX {vix_close:.2f}; below 22 favors risk-on, above 28 blocks high confidence.")
    else:
        reasons.append("One or more benchmark candles are unavailable or stale; high-confidence stock setups are blocked.")
    if regime == "RISK_OFF":
        reasons.append("Risk-off regime: BUY SETUPs can only remain review candidates, not ready signals.")
    elif regime == "MIXED":
        reasons.append("Mixed regime: require cleaner stock-specific confirmation before manual action.")
    elif regime == "RISK_ON":
        reasons.append("Market regime supports long-only review if the individual stock gate is clean.")
    return {
        "as_of": iso_now(),
        "source": source,
        "regime": regime,
        "label": label,
        "score": score,
        "high_confidence_allowed": regime == "RISK_ON",
        "manual_rule": "Use this as a market filter only; it does not create buy or sell orders.",
        "components": components,
        "provider_status": "available" if data_clean else "degraded",
        "provider_error_count": len(provider_errors),
        "provider_errors": provider_errors,
        "reasons": reasons,
        "live_only_policy": "market regime uses live Yahoo public chart or stale real cache only",
        "fixture_user_visible": False,
    }


def empty_market_regime(reason: str = "No market regime scan yet.") -> dict[str, Any]:
    return {
        "as_of": iso_now(),
        "source": "live",
        "regime": "DATA_CAUTION",
        "label": "Data Caution",
        "score": 0,
        "high_confidence_allowed": False,
        "manual_rule": "Market regime must be checked before manual review.",
        "components": {},
        "provider_status": "not_scanned",
        "provider_error_count": 1,
        "provider_errors": [reason],
        "reasons": [reason],
        "live_only_policy": "market regime uses live Yahoo public chart or stale real cache only",
        "fixture_user_visible": False,
    }


def api_stock_live_data_health(
    universes: list[str] | tuple[str, ...] | None = None,
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
    limit: int | None = None,
    scan_pause_seconds: float = 0.0,
) -> dict[str, Any]:
    db = db_path or default_db_path()
    outputs = outputs_dir or Path("outputs")
    requested_universes = list(universes or ["default", "ai_five_layer"])
    started = iso_now()
    universe_reports: list[dict[str, Any]] = []
    total_symbols = 0
    total_checks = 0
    provider_error_count = 0
    stale_cache_count = 0
    available_count = 0

    for universe in requested_universes:
        stocks = stock_universe(universe)
        if limit:
            stocks = stocks[: max(1, min(limit, len(stocks)))]
        symbol_reports: list[dict[str, Any]] = []
        for stock in stocks:
            timeframe_reports: list[dict[str, Any]] = []
            for timeframe in HEALTH_TIMEFRAMES:
                payload = api_stock_candles(
                    stock.symbol,
                    str(timeframe["range"]),
                    str(timeframe["interval"]),
                    "live",
                    db,
                )
                candles = payload.get("candles", [])
                status = str(payload.get("provider_status", "unknown"))
                if status == "available":
                    available_count += 1
                elif status == "stale_cache":
                    stale_cache_count += 1
                else:
                    provider_error_count += 1
                total_checks += 1
                expected = int(RANGES[str(payload.get("range", timeframe["range"]))]["bars"])
                timeframe_reports.append(
                    {
                        "timeframe": timeframe["key"],
                        "range": payload.get("range"),
                        "interval": payload.get("interval"),
                        "source_type": payload.get("source_type"),
                        "provider_status": status,
                        "freshness": payload.get("freshness"),
                        "stale_age_seconds": int(payload.get("freshness_seconds") or extract_stale_seconds(payload.get("freshness"))),
                        "candle_count": len(candles),
                        "expected_bars": expected,
                        "count_ok": len(candles) >= max(1, int(expected * 0.75)),
                        "first_time": candles[0]["open_time"] if candles else "",
                        "last_time": candles[-1]["open_time"] if candles else "",
                        "provider_errors": payload.get("provider_errors", [])[:3],
                    }
                )
                if scan_pause_seconds > 0:
                    time.sleep(scan_pause_seconds)
            symbol_reports.append(
                {
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "layer": stock.layer,
                    "timeframes": timeframe_reports,
                    "provider_status": rollup_timeframe_status(timeframe_reports),
                }
            )
        total_symbols += len(stocks)
        universe_reports.append(
            {
                "universe": universe,
                "symbol_count": len(stocks),
                "symbols": symbol_reports,
                "provider_status": rollup_symbol_status(symbol_reports),
            }
        )

    completed = iso_now()
    summary = {
        "symbol_count": total_symbols,
        "timeframe_checks": total_checks,
        "available_checks": available_count,
        "stale_cache_checks": stale_cache_count,
        "provider_error_checks": provider_error_count,
        "provider_status": "degraded" if provider_error_count else "available",
    }
    payload = {
        "run_id": f"stock-health-{int(time.time())}",
        "product": "KQUANT US Stock Signal Terminal",
        "source": "live",
        "started_at": started,
        "completed_at": completed,
        "universes": requested_universes,
        "timeframes": HEALTH_TIMEFRAMES,
        "summary": summary,
        "daily_usability": live_health_usability(summary),
        "database": database_health_summary(db),
        "live_only_policy": "live Yahoo public chart or stale real cache only; fixture is not user-visible",
        "fixture_user_visible": False,
        "universes_detail": universe_reports,
    }
    write_stock_live_data_health_report(outputs, payload)
    return payload


def api_stock_live_data_health_latest(outputs_dir: Path | None = None) -> dict[str, Any]:
    outputs = outputs_dir or Path("outputs")
    report = outputs / "stock-live-data-health.json"
    if report.exists():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["latest_cache_status"] = "available"
            return payload
        except json.JSONDecodeError:
            pass
    summary = {
        "symbol_count": 0,
        "timeframe_checks": 0,
        "available_checks": 0,
        "stale_cache_checks": 0,
        "provider_error_checks": 0,
        "provider_status": "not_scanned",
    }
    now = iso_now()
    return {
        "run_id": "stock-health-not-scanned",
        "product": "KQUANT US Stock Signal Terminal",
        "source": "live",
        "started_at": now,
        "completed_at": now,
        "universes": [],
        "timeframes": HEALTH_TIMEFRAMES,
        "summary": summary,
        "daily_usability": live_health_usability(summary),
        "database": {},
        "live_only_policy": "latest health reads the last report only and never hits Yahoo",
        "fixture_user_visible": False,
        "universes_detail": [],
        "latest_cache_status": "not_scanned",
    }


def api_stock_signals(
    source: str = "live",
    universe: str = "default",
    profile: str = "swing_long_v1",
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
    limit: int | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    db = db_path or default_db_path()
    outputs = outputs_dir or Path("outputs")
    active_profile = profile_config(profile)
    stocks = stock_universe(universe)
    scan_layer = str(layer or "").strip()
    if scan_layer:
        stocks = [stock for stock in stocks if stock.layer.lower() == scan_layer.lower()]
    universe_total = len(stocks)
    symbols = [stock.symbol for stock in stocks]
    if limit:
        symbols = symbols[: max(1, min(limit, len(symbols)))]
        stocks = stocks[: len(symbols)]
    stock_by_symbol = {stock.symbol: stock for stock in stocks}
    started = iso_now()
    signals: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    label_samples_by_symbol: dict[str, list[dict[str, Any]]] = {}
    market_regime = api_stock_market_regime(source=source, db_path=db)
    for symbol in symbols:
        primary = api_stock_candles(
            symbol,
            str(active_profile["primary_range"]),
            str(active_profile["primary_interval"]),
            source,
            db,
        )
        confirmation = api_stock_candles(
            symbol,
            str(active_profile["confirmation_range"]),
            str(active_profile["confirmation_interval"]),
            source,
            db,
        )
        if primary["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: {active_profile['primary_timeframe']} {primary['provider_status']}")
        if confirmation["provider_status"] not in ("available", "fixture_read_only"):
            provider_errors.append(f"{symbol}: {active_profile['confirmation_timeframe']} {confirmation['provider_status']}")
        signal = build_signal(symbol, primary, confirmation, active_profile)
        stock_meta = stock_by_symbol.get(symbol)
        if stock_meta:
            signal["primary_layer"] = stock_meta.layer
            signal["tags"] = list(stock_meta.tags)
            signal["liquidity_tier"] = stock_meta.liquidity_tier
        label_samples_by_symbol[symbol] = signal.pop("_label_samples", [])
        signals.append(signal)
    for signal in signals:
        signal["review_bucket"] = signal_review_bucket(signal)
        signal["downgraded_reasons"] = downgraded_reasons(signal)
        signal["readiness_gate"] = build_trade_readiness(signal, market_regime)
        signal["trade_conclusion"] = build_trade_conclusion(signal, market_regime)
    signals = sort_signals_for_review(signals)
    completed = iso_now()
    run_id = f"stock-{int(time.time())}"
    provider_status = "degraded" if provider_errors else ("fixture_read_only" if source == "fixture" else "available")
    historical_validation = summarize_label_samples(label_samples_by_symbol)
    profile_validation = summarize_profile_validation(label_samples_by_symbol, active_profile)
    stale_signals = [
        signal
        for signal in signals
        if signal.get("data_status", {}).get("daily_provider_status") == "stale_cache"
        or signal.get("data_status", {}).get("hourly_provider_status") == "stale_cache"
    ]
    provider_coverage = signal_provider_coverage(signals, universe_total)
    data_downgraded_count = sum(
        1
        for signal in signals
        if any(reason in signal.get("downgraded_reasons", []) for reason in ("data quality is not clean", "provider degraded or using stale cache"))
    )
    stale_age_seconds = max((extract_stale_seconds(signal.get("data_status", {}).get("freshness")) for signal in stale_signals), default=0)
    payload = {
        "run_id": run_id,
        "product": "KQUANT US Stock Signal Terminal",
        "source": source,
        "universe": universe,
        "scan_layer": scan_layer or "all_layers",
        "universe_total": universe_total,
        "scanned_count": len(signals),
        "provider_coverage": provider_coverage,
        "downgraded_by_data_count": data_downgraded_count,
        "profile": active_profile,
        "started_at": started,
        "completed_at": completed,
        "provider_status": provider_status,
        "provider_error_count": len(provider_errors),
        "provider_errors": provider_errors[:30],
        "market_regime": market_regime,
        "live_only_policy": "user-facing stock terminal uses live Yahoo public chart or stale real cache only",
        "fixture_user_visible": False,
        "cache_source": "stale_yahoo_chart_cache" if stale_signals else "live_yahoo_chart" if source == "live" and not provider_errors else "none",
        "stale_signal_count": len(stale_signals),
        "stale_age": f"{stale_age_seconds}s" if stale_age_seconds else "none",
        "stale_age_seconds": stale_age_seconds,
        "historical_validation": historical_validation,
        "validation_by_strategy_profile": profile_validation,
        "validation_by_level": summarize_validation_by_level(signals),
        "review_counts": summarize_review_counts(signals),
        "trade_conclusion_counts": summarize_trade_conclusions(signals),
        "high_priority_policy": "BUY SETUP requires clean live data, positive profile-specific historical edge, clear exit risk, and market-regime approval",
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
    source: str = "live",
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


def api_stock_analyze(
    symbol: str,
    source: str = "live",
    profile: str = "swing_long_v1",
    db_path: Path | None = None,
) -> dict[str, Any]:
    db = db_path or default_db_path()
    active_profile = profile_config(profile)
    normalized_symbol = normalize_symbol(symbol)
    all_stocks = stock_universe("all")
    stock_meta = next((stock for stock in all_stocks if stock.symbol == normalized_symbol), None)
    primary = api_stock_candles(
        normalized_symbol,
        str(active_profile["primary_range"]),
        str(active_profile["primary_interval"]),
        source,
        db,
    )
    confirmation = api_stock_candles(
        normalized_symbol,
        str(active_profile["confirmation_range"]),
        str(active_profile["confirmation_interval"]),
        source,
        db,
    )
    market_regime = api_stock_market_regime(source=source, db_path=db)
    signal = build_signal(normalized_symbol, primary, confirmation, active_profile)
    if stock_meta:
        signal["primary_layer"] = stock_meta.layer
        signal["tags"] = list(stock_meta.tags)
        signal["liquidity_tier"] = stock_meta.liquidity_tier
    else:
        signal["primary_layer"] = "Ad-hoc Live Symbol"
        signal["tags"] = []
        signal["liquidity_tier"] = "ad_hoc"
    signal["review_bucket"] = signal_review_bucket(signal)
    signal["downgraded_reasons"] = downgraded_reasons(signal)
    signal["readiness_gate"] = build_trade_readiness(signal, market_regime)
    signal["trade_conclusion"] = build_trade_conclusion(signal, market_regime)
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "symbol": normalized_symbol,
        "source": source,
        "profile": active_profile,
        "universe_match": stock_meta is not None,
        "universe_meta": (
            {
                "symbol": stock_meta.symbol,
                "name": stock_meta.name,
                "sector": stock_meta.sector,
                "layer": stock_meta.layer,
                "tags": list(stock_meta.tags),
                "rank": stock_meta.rank,
                "liquidity_tier": stock_meta.liquidity_tier,
            }
            if stock_meta
            else {
                "symbol": normalized_symbol,
                "name": normalized_symbol,
                "sector": "Ad-hoc",
                "layer": "Ad-hoc Live Symbol",
                "tags": [],
                "rank": 0,
                "liquidity_tier": "ad_hoc",
            }
        ),
        "primary_candles": candle_payload_meta(primary),
        "confirmation_candles": candle_payload_meta(confirmation),
        "signal": signal,
        "market_regime": market_regime,
        "journal_summary": api_stock_signal_journal(db_path=db, symbol=normalized_symbol, limit=10)["summary"],
        "fixture_user_visible": False,
        "broker_order_wiring_enabled": False,
        "llm_signal_core_enabled": False,
    }


def api_stock_ai_review(payload: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    db = db_path or default_db_path()
    symbol = normalize_symbol(payload.get("symbol") or payload.get("signal_payload", {}).get("symbol") or "NVDA")
    profile = str(payload.get("profile") or payload.get("signal_payload", {}).get("profile_name") or "tactical_1w_v1")
    signal_payload = payload.get("signal_payload")
    if not isinstance(signal_payload, dict) or not signal_payload:
        signal_payload = api_stock_analyze(symbol=symbol, source="live", profile=profile, db_path=db)["signal"]
    profile_comparison = payload.get("profile_comparison") if isinstance(payload.get("profile_comparison"), list) else []
    journal_limit = int(payload.get("journal_context_limit") or 5)
    journal = api_stock_signal_journal(db_path=db, symbol=symbol, limit=max(1, min(journal_limit, 20)))
    model = ai_review_model(payload)
    safety = {
        "read_only_research": True,
        "llm_signal_core_enabled": False,
        "ai_review_only": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "does_not_override_rule_conclusion": True,
    }
    context = ai_review_context(symbol, profile, signal_payload, profile_comparison, journal)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "product": "KQUANT AI Review Assistant",
            "status": "ai_review_unavailable",
            "reason": "OPENAI_API_KEY is not configured.",
            "model_name": model,
            "generated_at": iso_now(),
            "input_summary": context["input_summary"],
            "rule_conclusion": signal_payload.get("trade_conclusion", {}),
            "ai_review": unavailable_ai_review(signal_payload, "OPENAI_API_KEY is not configured."),
            "safety_policy": safety,
        }
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=openai_review_request(model, context),
            timeout=45,
        )
        response.raise_for_status()
        raw = response.json()
        text = extract_openai_text(raw)
        review = sanitize_ai_review(json.loads(text), signal_payload)
        status = "available"
        reason = "ok"
    except Exception as exc:
        review = unavailable_ai_review(signal_payload, f"AI review request failed: {type(exc).__name__}")
        status = "ai_review_unavailable"
        reason = str(exc)[:240]
    return {
        "product": "KQUANT AI Review Assistant",
        "status": status,
        "reason": reason,
        "model_name": model,
        "generated_at": iso_now(),
        "input_summary": context["input_summary"],
        "rule_conclusion": signal_payload.get("trade_conclusion", {}),
        "ai_review": review,
        "safety_policy": safety,
    }


def api_stock_ai_review_status() -> dict[str, Any]:
    review_model = os.environ.get("KQUANT_AI_REVIEW_MODEL", "gpt-5.4").strip() or "gpt-5.4"
    batch_model = os.environ.get("KQUANT_AI_BATCH_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    deep_model = os.environ.get("KQUANT_AI_DEEP_MODEL", "gpt-5.5").strip() or "gpt-5.5"
    has_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    return {
        "product": "KQUANT AI Review Assistant",
        "status": "available" if has_key else "missing_key",
        "reason": "OPENAI_API_KEY is configured." if has_key else "OPENAI_API_KEY is not configured on the backend.",
        "setup_hint": "Set OPENAI_API_KEY in the local backend environment and restart KQUANT. Never put this key in web/, GitHub, or Vercel frontend variables.",
        "models": {
            "review": review_model,
            "batch": batch_model,
            "deep": deep_model,
        },
        "manual_trigger_only": True,
        "read_only_research": True,
        "llm_signal_core_enabled": False,
        "ai_review_only": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "key_location": "backend_environment_only",
    }


def api_stock_signal_journal(
    db_path: Path | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    db = db_path or default_db_path()
    normalized_symbol = normalize_symbol(symbol) if symbol else ""
    limit = max(1, min(int(limit), 200))
    with connect(db) as conn:
        if normalized_symbol:
            rows = conn.execute(
                """
                SELECT id, run_id, symbol, strategy_profile, rule_conclusion, ai_review_verdict, status, notes, planned_entry, planned_stop,
                       planned_target, outcome, reviewed_at, created_at
                FROM stock_signal_journal
                WHERE symbol = ?
                ORDER BY reviewed_at DESC, id DESC
                LIMIT ?
                """,
                (normalized_symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, run_id, symbol, strategy_profile, rule_conclusion, ai_review_verdict, status, notes, planned_entry, planned_stop,
                       planned_target, outcome, reviewed_at, created_at
                FROM stock_signal_journal
                ORDER BY reviewed_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    entries = [stock_journal_row(row) for row in rows]
    counts = {status: 0 for status in sorted(STOCK_JOURNAL_STATUSES)}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "symbol": normalized_symbol or "all",
        "entries": entries,
        "counts": counts,
        "summary": {
            "total_entries": len(entries),
            "reviewed_count": counts.get("reviewed", 0),
            "watch_count": counts.get("watch", 0),
            "skipped_count": counts.get("skipped", 0),
            "paper_observed_count": counts.get("paper-observed", 0),
            "manual_traded_note_count": counts.get("manual-traded", 0),
            "invalidated_count": counts.get("invalidated", 0),
        },
        "safety": {
            "read_only_research": True,
            "broker_order_wiring_enabled": False,
            "account_access_enabled": False,
            "llm_signal_core_enabled": False,
        },
    }


def api_stock_signal_journal_entry(payload: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    status = str(payload.get("status") or "reviewed")
    if status not in STOCK_JOURNAL_STATUSES:
        raise ValueError("Invalid stock signal journal status.")
    symbol = normalize_symbol(payload.get("symbol") or "")
    if not symbol:
        raise ValueError("A stock symbol is required.")
    db = db_path or default_db_path()
    now = iso_now()
    run_id = str(payload.get("run_id") or latest_stock_run_id(db) or "manual-review")
    strategy_profile = str(payload.get("strategy_profile") or payload.get("profile_name") or "")[:80]
    rule_conclusion = str(payload.get("rule_conclusion") or "")[:80]
    ai_review_verdict = str(payload.get("ai_review_verdict") or "")[:80]
    notes = str(payload.get("notes") or "")[:4000]
    outcome = str(payload.get("outcome") or "")[:2000]
    planned_entry = optional_float(payload.get("planned_entry"))
    planned_stop = optional_float(payload.get("planned_stop"))
    planned_target = optional_float(payload.get("planned_target"))
    with connect(db) as conn:
        cursor = conn.execute(
            """
            INSERT INTO stock_signal_journal (
              run_id, symbol, strategy_profile, rule_conclusion, ai_review_verdict, status, notes, planned_entry, planned_stop,
              planned_target, outcome, reviewed_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                symbol,
                strategy_profile,
                rule_conclusion,
                ai_review_verdict,
                status,
                notes,
                planned_entry,
                planned_stop,
                planned_target,
                outcome,
                now,
                now,
            ),
        )
        entry_id = int(cursor.lastrowid)
        conn.commit()
        row = conn.execute(
            """
            SELECT id, run_id, symbol, strategy_profile, rule_conclusion, ai_review_verdict, status, notes, planned_entry, planned_stop,
                   planned_target, outcome, reviewed_at, created_at
            FROM stock_signal_journal
            WHERE id = ?
            """,
            (entry_id,),
        ).fetchone()
    return {
        "entry": stock_journal_row(row),
        "journal": api_stock_signal_journal(db_path=db, symbol=symbol, limit=50),
        "safety": {
            "read_only_research": True,
            "broker_order_wiring_enabled": False,
            "account_access_enabled": False,
        },
    }


def empty_signal_run(source: str, universe: str, profile: str, reason: str) -> dict[str, Any]:
    now = iso_now()
    universe_total = len(stock_universe(universe))
    active_profile = profile_config(profile)
    return {
        "run_id": "stock-live-not-scanned",
        "product": "KQUANT US Stock Signal Terminal",
        "source": source,
        "universe": universe,
        "universe_total": universe_total,
        "scanned_count": 0,
        "provider_coverage": signal_provider_coverage([], universe_total),
        "downgraded_by_data_count": 0,
        "profile": active_profile,
        "started_at": now,
        "completed_at": now,
        "provider_status": "not_scanned",
        "provider_error_count": 0,
        "provider_errors": [reason],
        "market_regime": empty_market_regime(reason),
        "live_only_policy": "user-facing stock terminal uses live Yahoo public chart or stale real cache only",
        "fixture_user_visible": False,
        "cache_source": "none",
        "stale_signal_count": 0,
        "stale_age": "none",
        "stale_age_seconds": 0,
        "historical_validation": summarize_label_samples({}),
        "validation_by_strategy_profile": summarize_profile_validation({}, active_profile),
        "validation_by_level": summarize_validation_by_level([]),
        "review_counts": summarize_review_counts([]),
        "trade_conclusion_counts": summarize_trade_conclusions([]),
        "high_priority_policy": "BUY SETUP requires clean live data, positive profile-specific historical edge, clear exit risk, and market-regime approval",
        "counts": {"buy_setup": 0, "watch": 0, "pass": 0, "total": 0},
        "signals": [],
        "btc_eth_removed_from_main_path": True,
        "options_are_secondary": True,
        "llm_signal_core_enabled": False,
        "broker_order_wiring_enabled": False,
    }


def extract_stale_seconds(freshness: Any) -> int:
    text = str(freshness or "")
    if not text.startswith("stale "):
        return 0
    value = text.removeprefix("stale ").removesuffix("s")
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def build_signal(
    symbol: str,
    daily_payload: dict[str, Any],
    hourly_payload: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_profile = profile or PROFILE
    daily = daily_payload["candles"]
    hourly = hourly_payload["candles"]
    if len(daily) < 60 or len(hourly) < 20:
        return empty_signal(symbol, daily_payload, hourly_payload, active_profile)
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
        "buy_setup_threshold": active_profile["strict_buy_gate_score"],
        "watch_threshold": active_profile["watch_threshold"],
        "formula": active_profile.get("formula", "trend + trigger + volume confirmation + risk window"),
    }
    label_samples = build_historical_label_samples(symbol, daily)
    historical_edge = estimate_historical_edge(label_samples)
    historical_edge = profile_historical_edge(historical_edge, label_samples, active_profile)
    trend_aligned = close > ema20 > ema50 > ema200
    trigger_confirmed = hourly_close[-1] > h_ema20 > h_ema50 and one_hour_momentum >= float(active_profile.get("confirmation_momentum_min", 0.6))
    volume_confirmed = volume_ratio >= float(active_profile.get("volume_ratio_min", 1.2))
    risk_window_ok = -2.5 <= extension_pct <= float(active_profile.get("max_extension_pct", 5.5)) and atr_pct <= float(active_profile.get("max_atr_pct", 5.0))
    daily_status = daily_payload["provider_status"]
    hourly_status = hourly_payload["provider_status"]
    data_clean = daily_status == "available" and hourly_status == "available"
    has_real_or_internal_data = daily_status in ("available", "stale_cache", "fixture_read_only") and hourly_status in (
        "available",
        "stale_cache",
        "fixture_read_only",
    )
    edge_ok = (
        historical_edge["sample_count"] >= 10
        and historical_edge.get("focus_win_rate", historical_edge["win_rate_5d"]) >= float(active_profile.get("focus_win_rate_min", 55.0))
        and historical_edge.get("focus_avg_return", historical_edge["avg_forward_return_5d"]) > float(active_profile.get("focus_avg_return_min", 0.4))
    )
    buy_gates = trend_aligned and trigger_confirmed and volume_confirmed and risk_window_ok and data_clean and edge_ok
    watch_gates = score >= float(active_profile["watch_threshold"]) and close > ema50 and one_hour_momentum > -1.5 and has_real_or_internal_data
    level = "BUY SETUP" if score >= float(active_profile["strict_buy_gate_score"]) and buy_gates else "WATCH" if watch_gates else "PASS"
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
        "profile_name": active_profile["name"],
        "strategy_label": active_profile["label"],
        "holding_period": active_profile["holding_period"],
        "primary_timeframe": active_profile["primary_timeframe"],
        "confirmation_timeframe": active_profile["confirmation_timeframe"],
        "primary_layer": "US Stock",
        "tags": [],
        "liquidity_tier": "core",
        "trend_summary": f"Daily close {close:.2f}; EMA20 {ema20:.2f}, EMA50 {ema50:.2f}, EMA200 {ema200:.2f}.",
        "trigger_summary": f"1h momentum {one_hour_momentum:.2f}% with close {'above' if hourly_close[-1] >= h_ema20 else 'below'} EMA20.",
        "score_breakdown": score_breakdown,
        "exit_risk": exit_risk,
        "exit_plan": build_exit_plan(active_profile, exit_risk, close, ema20, ema50, extension_pct),
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
            "primary_provider_status": daily_payload["provider_status"],
            "confirmation_provider_status": hourly_payload["provider_status"],
            "daily_candles": len(daily),
            "hourly_candles": len(hourly),
            "primary_candles": len(daily),
            "confirmation_candles": len(hourly),
            "primary_timeframe": active_profile["primary_timeframe"],
            "confirmation_timeframe": active_profile["confirmation_timeframe"],
            "source": daily_payload["source_type"],
            "freshness": daily_payload["freshness"],
            "data_quality": "clean" if data_clean else "caution",
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "features": features,
        "historical_edge": historical_edge,
        "_label_samples": label_samples,
    }


def empty_signal(
    symbol: str,
    daily_payload: dict[str, Any],
    hourly_payload: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_profile = profile or PROFILE
    return {
        "symbol": symbol,
        "score": 0,
        "level": "PASS",
        "direction": "LONG",
        "profile_name": active_profile["name"],
        "strategy_label": active_profile["label"],
        "holding_period": active_profile["holding_period"],
        "primary_timeframe": active_profile["primary_timeframe"],
        "confirmation_timeframe": active_profile["confirmation_timeframe"],
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
            "buy_setup_threshold": active_profile["strict_buy_gate_score"],
            "watch_threshold": active_profile["watch_threshold"],
            "formula": active_profile.get("formula", "trend + confirmation + volume + risk"),
        },
        "exit_risk": {
            "status": "DATA CAUTION",
            "level": "CAUTION",
            "reasons": ["Missing candles prevent exit-risk evaluation."],
            "checklist": ["Refresh data later and do not act on incomplete candles."],
        },
        "exit_plan": {
            "status": "SETUP INVALIDATED",
            "holding_period": active_profile["holding_period"],
            "rules": ["Missing candles prevent a valid exit plan."],
            "read_only_research": True,
        },
        "risk_warnings": ["Missing market data; skip until provider health improves."],
        "manual_checklist": ["Refresh data later and do not act on incomplete candles."],
        "data_status": {
            "daily_provider_status": daily_payload.get("provider_status", "missing"),
            "hourly_provider_status": hourly_payload.get("provider_status", "missing"),
            "primary_provider_status": daily_payload.get("provider_status", "missing"),
            "confirmation_provider_status": hourly_payload.get("provider_status", "missing"),
            "daily_candles": len(daily_payload.get("candles", [])),
            "hourly_candles": len(hourly_payload.get("candles", [])),
            "primary_candles": len(daily_payload.get("candles", [])),
            "confirmation_candles": len(hourly_payload.get("candles", [])),
            "primary_timeframe": active_profile["primary_timeframe"],
            "confirmation_timeframe": active_profile["confirmation_timeframe"],
            "source": daily_payload.get("source_type", "unknown"),
            "freshness": daily_payload.get("freshness", "missing"),
            "data_quality": "caution",
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "features": {},
        "historical_edge": profile_historical_edge(empty_historical_edge(), [], active_profile),
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


def market_regime_component(symbol: str, label: str, payload: dict[str, Any]) -> dict[str, Any]:
    candles = payload.get("candles", [])
    status = str(payload.get("provider_status", "missing"))
    if len(candles) < 60:
        return {
            "symbol": symbol,
            "label": label,
            "provider_status": status,
            "source_type": payload.get("source_type", "unknown"),
            "freshness": payload.get("freshness", "missing"),
            "candle_count": len(candles),
            "close": None,
            "ema20": None,
            "ema50": None,
            "ema200": None,
            "return_20d_pct": 0.0,
            "above_ema50": False,
            "above_ema200": False,
            "below_ema200": True,
            "ema20_above_ema50": False,
        }
    closes = [float(bar["close"]) for bar in candles]
    close = closes[-1]
    ema20 = ema_last(closes, 20)
    ema50 = ema_last(closes, 50)
    ema200 = ema_last(closes, 200)
    return_20d = pct(close, closes[-21] if len(closes) > 21 else closes[0])
    return {
        "symbol": symbol,
        "label": label,
        "provider_status": status,
        "source_type": payload.get("source_type", "unknown"),
        "freshness": payload.get("freshness", "missing"),
        "candle_count": len(candles),
        "close": round(close, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "return_20d_pct": round(return_20d, 2),
        "above_ema50": close > ema50,
        "above_ema200": close > ema200,
        "below_ema200": close < ema200,
        "ema20_above_ema50": ema20 > ema50,
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
    profile_validation = payload.get("validation_by_strategy_profile", {})
    market_regime = payload.get("market_regime", {})
    conclusion_counts = payload.get("trade_conclusion_counts", {})
    lines = [
        "# KQUANT US Stock Signals",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Source: `{payload['source']}`",
        f"- Universe: `{payload['universe']}`",
        f"- Scan layer: `{payload.get('scan_layer', 'all_layers')}`",
        f"- Universe total / scanned: `{payload.get('universe_total', payload['counts']['total'])}` / `{payload.get('scanned_count', payload['counts']['total'])}`",
        f"- Profile: `{payload['profile']['name']}` / `{payload['profile'].get('holding_period', '')}`",
        f"- Provider: `{payload['provider_status']}` / errors `{payload['provider_error_count']}`",
        f"- Provider coverage: `{payload.get('provider_coverage', {})}`",
        f"- Downgraded by data: `{payload.get('downgraded_by_data_count', 0)}`",
        f"- Live-only policy: `{payload.get('live_only_policy')}`",
        f"- Cache source: `{payload.get('cache_source')}` / stale age `{payload.get('stale_age')}`",
        f"- Fixture user visible: `{payload.get('fixture_user_visible')}`",
        f"- Market regime: `{market_regime.get('regime', 'unknown')}` / score `{market_regime.get('score', 0)}`",
        f"- High confidence allowed: `{market_regime.get('high_confidence_allowed', False)}`",
        f"- Counts: BUY SETUP `{payload['counts']['buy_setup']}`, WATCH `{payload['counts']['watch']}`, PASS `{payload['counts']['pass']}`",
        f"- Action conclusions: BUY `{conclusion_counts.get('BUY', 0)}`, WAIT `{conclusion_counts.get('WAIT', 0)}`, DO_NOT_BUY `{conclusion_counts.get('DO_NOT_BUY', 0)}`, EXIT_REVIEW `{conclusion_counts.get('EXIT_REVIEW', 0)}`",
        f"- Review counts: High Priority `{payload.get('review_counts', {}).get('high_priority', 0)}`, Watch `{payload.get('review_counts', {}).get('watch', 0)}`, Downgraded `{payload.get('review_counts', {}).get('downgraded', 0)}`",
        "",
        "## Market Regime",
        "",
        f"- State: `{market_regime.get('label', market_regime.get('regime', 'unknown'))}`",
        f"- Rule: {market_regime.get('manual_rule', 'Check market regime manually before acting.')}",
        f"- Reasons: {'; '.join(market_regime.get('reasons', [])[:4])}",
            "",
            "## Action Conclusions",
            "",
            "| Action | Count | Meaning |",
            "| --- | ---: | --- |",
            f"| BUY | {conclusion_counts.get('BUY', 0)} | Rule setup is ready for manual review. |",
            f"| WAIT | {conclusion_counts.get('WAIT', 0)} | Researchable, but strict buy gates are missing. |",
            f"| DO_NOT_BUY | {conclusion_counts.get('DO_NOT_BUY', 0)} | New long is blocked by rule/data/risk filters. |",
            f"| EXIT_REVIEW | {conclusion_counts.get('EXIT_REVIEW', 0)} | Existing position needs manual risk review; no fresh long. |",
            "",
            "## AI Review Notes",
            "",
            "- AI Review is manual-trigger commentary only; it does not change score, level, or action conclusion.",
            "- `llm_signal_core_enabled` remains `False`; broker and order wiring remain disabled.",
            "",
            "## Historical Validation",
        "",
        f"- Samples: `{validation.get('sample_count', 0)}`",
        f"- 5D win rate: `{validation.get('win_rate_5d', 0)}%`",
        f"- Avg 5D return: `{validation.get('avg_forward_return_5d', 0)}%`",
        f"- Avg 5D drawdown: `{validation.get('avg_max_drawdown_5d', 0)}%`",
        "- Note: historical labels are research validation, not an execution signal.",
        "",
        "## Validation by Strategy Profile",
        "",
        f"- Profile: `{profile_validation.get('profile_name', payload['profile']['name'])}`",
        f"- Holding period: `{profile_validation.get('holding_period', payload['profile'].get('holding_period', ''))}`",
        f"- Focus window: `{profile_validation.get('focus_window', '-')}`",
        f"- Samples: `{profile_validation.get('sample_count', 0)}`",
        f"- Win / target hit: `{profile_validation.get('win_rate', 0)}%` / `{profile_validation.get('target_hit_rate', 0)}%`",
        f"- Avg return / drawdown: `{profile_validation.get('avg_forward_return', 0)}%` / `{profile_validation.get('avg_max_drawdown', 0)}%`",
        f"- Verdict: `{profile_validation.get('verdict', 'missing')}`",
        "",
        "## Validation by Level",
        "",
        "| Level | Signals | Samples | 5D Win | Avg 5D Return | Avg 5D Drawdown | Noise Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for level, stats in payload.get("validation_by_level", {}).items():
        lines.append(
            f"| {level} | {stats.get('signal_count', 0)} | {stats.get('sample_count', 0)} | "
            f"{stats.get('win_rate_5d', 0)}% | {stats.get('avg_forward_return_5d', 0)}% | "
            f"{stats.get('avg_max_drawdown_5d', 0)}% | {stats.get('noise_rate', 0)}% |"
        )
    lines.extend(
        [
            "",
        "## High Priority Setups",
        "",
        ]
    )
    high_priority = [signal for signal in payload["signals"] if signal.get("review_bucket") == "high_priority"]
    if high_priority:
        for signal in high_priority[:12]:
            lines.extend(
                [
                    f"- `{signal['symbol']}` {signal['score']}/100 - {signal['trend_summary']} / {signal['trigger_summary']}",
                ]
            )
    else:
        lines.append("- None. A setup must have clean data, positive historical edge, and clear exit risk.")
    lines.extend(
        [
            "",
            "## Rejected / Downgraded Reasons",
            "",
        ]
    )
    downgraded = [signal for signal in payload["signals"] if signal.get("review_bucket") != "high_priority"]
    if downgraded:
        for signal in downgraded[:20]:
            reasons = "; ".join(signal.get("downgraded_reasons", [])[:3]) or "No high-priority confirmation."
            lines.append(f"- `{signal['symbol']}` {signal['level']} {signal['score']}/100: {reasons}")
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
        "## Top Setups",
        "",
        ]
    )
    for signal in payload["signals"][:20]:
        lines.extend(
            [
                f"### {signal['symbol']} - {signal['level']} - {signal['score']}/100",
                "",
                f"- Layer: {signal.get('primary_layer', 'US Stock')} / {signal.get('liquidity_tier', 'core')}",
                f"- Trend: {signal['trend_summary']}",
                f"- Trigger: {signal['trigger_summary']}",
                f"- Trade Conclusion: {signal.get('trade_conclusion', {})}",
                f"- Score Breakdown: {signal.get('score_breakdown', {})}",
                f"- Exit Risk: {signal.get('exit_risk', {})}",
                f"- Exit Plan: {signal.get('exit_plan', {})}",
                f"- Readiness Gate: {signal.get('readiness_gate', {})}",
                f"- Historical Edge: {signal.get('historical_edge', empty_historical_edge())}",
                f"- Data: {signal['data_status']}",
                f"- Risks: {'; '.join(signal['risk_warnings'])}",
                "",
            ]
        )
    (outputs_dir / "stock-signals-report.md").write_text("\n".join(lines), encoding="utf-8")


def write_stock_live_data_health_report(outputs_dir: Path, payload: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "stock-live-data-health.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = payload["summary"]
    database = payload["database"]
    usability = payload.get("daily_usability", {})
    lines = [
        "# KQUANT Stock Live Data Health",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Source: `{payload['source']}`",
        f"- Universes: `{', '.join(payload['universes'])}`",
        f"- Daily usability: `{usability.get('label', usability.get('status', 'unknown'))}` - {usability.get('reason', '')}",
        f"- Symbols: `{summary['symbol_count']}`",
        f"- Timeframe checks: `{summary['timeframe_checks']}`",
        f"- Available / stale / failed: `{summary['available_checks']}` / `{summary['stale_cache_checks']}` / `{summary['provider_error_checks']}`",
        f"- Provider status: `{summary['provider_status']}`",
        f"- Live-only policy: `{payload['live_only_policy']}`",
        "",
        "## Database",
        "",
        f"- Path: `{database['path']}`",
        f"- Tables ready: `{database['tables_ready']}`",
        f"- Live candles: `{database['live_candle_count']}`",
        f"- Stale-cache rows: `{database['stale_cache_row_count']}`",
        f"- Provider events: `{database['provider_event_count']}`",
        f"- Latest candle write: `{database['latest_candle_write']}`",
        "",
        "## Universe Summary",
        "",
    ]
    for universe in payload["universes_detail"]:
        lines.extend(
            [
                f"### {universe['universe']} - {universe['provider_status']}",
                "",
                "| Symbol | Layer | 1H | 1D | 1W | 1M |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for symbol in universe["symbols"][:120]:
            by_key = {item["timeframe"]: item for item in symbol["timeframes"]}
            lines.append(
                "| {symbol} | {layer} | {h1} | {d1} | {w1} | {m1} |".format(
                    symbol=symbol["symbol"],
                    layer=symbol["layer"],
                    h1=format_health_cell(by_key.get("1H")),
                    d1=format_health_cell(by_key.get("1D")),
                    w1=format_health_cell(by_key.get("1W")),
                    m1=format_health_cell(by_key.get("1M")),
                )
            )
        lines.append("")
    (outputs_dir / "stock-live-data-health.md").write_text("\n".join(lines), encoding="utf-8")


def format_health_cell(item: dict[str, Any] | None) -> str:
    if not item:
        return "-"
    status = item["provider_status"]
    count = item["candle_count"]
    if status == "available":
        return f"OK {count}"
    if status == "stale_cache":
        return f"STALE {count} / {item['stale_age_seconds']}s"
    return f"FAIL {count}"


def rollup_timeframe_status(timeframes: list[dict[str, Any]]) -> str:
    statuses = {item["provider_status"] for item in timeframes}
    if statuses == {"available"}:
        return "available"
    if statuses <= {"available", "stale_cache"}:
        return "stale_cache"
    return "degraded"


def rollup_symbol_status(symbols: list[dict[str, Any]]) -> str:
    statuses = {item["provider_status"] for item in symbols}
    if statuses == {"available"}:
        return "available"
    if statuses <= {"available", "stale_cache"}:
        return "stale_cache"
    return "degraded"


def database_health_summary(db_path: Path) -> dict[str, Any]:
    required_tables = [
        "stock_universe",
        "stock_candles",
        "provider_events",
        "audit_events",
        "stock_features",
        "stock_labels",
        "stock_backtest_runs",
    ]
    with connect(db_path) as conn:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ({})".format(
                ",".join("?" for _ in required_tables)
            ),
            required_tables,
        ).fetchall()
        present = {row["name"] for row in table_rows}
        latest = conn.execute("SELECT MAX(created_at) AS value FROM stock_candles").fetchone()["value"]
        live_count = conn.execute("SELECT COUNT(*) AS count FROM stock_candles WHERE source='live_yahoo_chart'").fetchone()["count"]
        stale_count = conn.execute("SELECT COUNT(*) AS count FROM stock_candles WHERE provider_status='stale_cache'").fetchone()["count"]
        provider_events = conn.execute("SELECT COUNT(*) AS count FROM provider_events").fetchone()["count"]
        feature_count = conn.execute("SELECT COUNT(*) AS count FROM stock_features").fetchone()["count"]
        label_count = conn.execute("SELECT COUNT(*) AS count FROM stock_labels").fetchone()["count"]
        backtest_count = conn.execute("SELECT COUNT(*) AS count FROM stock_backtest_runs").fetchone()["count"]
    return {
        "path": str(db_path),
        "tables_ready": all(table in present for table in required_tables),
        "missing_tables": [table for table in required_tables if table not in present],
        "live_candle_count": int(live_count),
        "stale_cache_row_count": int(stale_count),
        "provider_event_count": int(provider_events),
        "feature_count": int(feature_count),
        "label_count": int(label_count),
        "backtest_run_count": int(backtest_count),
        "latest_candle_write": latest or "none",
    }


def normalize_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol or "SPY").upper() if ch.isalnum() or ch in ".-^")[:16] or "SPY"


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


def build_exit_plan(
    profile: dict[str, Any],
    exit_risk: dict[str, Any],
    close: float,
    ema20: float,
    ema50: float,
    extension_pct: float,
) -> dict[str, Any]:
    status = str(exit_risk.get("status", "CLEAR"))
    if status in {"SETUP INVALIDATED", "DATA CAUTION"}:
        plan_status = status
    elif status in {"EXIT RISK", "TAKE PROFIT WATCH"}:
        plan_status = status
    elif extension_pct > float(profile.get("max_extension_pct", 8.0)) * 0.85:
        plan_status = "TAKE PROFIT WATCH"
    else:
        plan_status = "HOLD / TRAIL"
    return {
        "status": plan_status,
        "holding_period": profile["holding_period"],
        "profile_name": profile["name"],
        "rules": [
            f"STOP LOSS: review manually if price loses EMA50 near {ema50:.2f}.",
            f"SETUP INVALIDATED: trend thesis weakens if price cannot reclaim EMA20 near {ema20:.2f}.",
            "TAKE PROFIT WATCH: protect gains if price becomes extended or momentum diverges.",
            f"HOLD / TRAIL: valid only while the {profile['primary_timeframe']} structure remains intact.",
        ],
        "current_close": round(close, 2),
        "read_only_research": True,
    }


def build_trade_readiness(signal: dict[str, Any], market_regime: dict[str, Any]) -> dict[str, Any]:
    data_status = signal.get("data_status", {})
    historical = signal.get("historical_edge", {})
    exit_risk = signal.get("exit_risk", {})
    market_state = str(market_regime.get("regime", "DATA_CAUTION"))
    review_bucket = str(signal.get("review_bucket") or signal_review_bucket(signal))
    reasons: list[str] = []
    required_checks = [
        "Confirm daily trend: price above key EMAs and not extended.",
        "Confirm 1H structure: momentum is not fading at the trigger.",
        "Confirm market regime: avoid fresh longs when regime is RISK_OFF.",
        "Save a manual journal note with planned entry, stop, and target.",
    ]
    risk_controls = [
        "Read-only research only; no broker, account, or order wiring is connected.",
        "Skip the setup if data becomes stale, provider fails, or price gaps away.",
        "Treat WATCH as research only until the strict gate becomes ready.",
    ]
    data_clean = data_status.get("data_quality") == "clean"
    historical_positive = (
        historical.get("sample_count", 0) >= 10
        and historical.get("focus_win_rate", historical.get("win_rate_5d", 0)) >= 52
        and historical.get("focus_avg_return", historical.get("avg_forward_return_5d", 0)) > 0
    )
    exit_clear = exit_risk.get("status") == "CLEAR"
    if not data_clean:
        reasons.append("Data quality is not clean; provider or stale-cache caution blocks readiness.")
    if market_state in {"RISK_OFF", "DATA_CAUTION"}:
        reasons.append(f"Market regime is {market_state}; high-confidence long review is blocked.")
    if signal.get("level") == "PASS":
        reasons.append("Signal level is PASS.")
    if not historical_positive:
        reasons.append("Historical edge is not positive enough for strict review.")
    if not exit_clear:
        reasons.append(f"Exit risk is {exit_risk.get('status', 'unknown')}.")
    if review_bucket != "high_priority":
        reasons.append("Signal is not in the High Priority review bucket.")
    ready = (
        signal.get("level") == "BUY SETUP"
        and review_bucket == "high_priority"
        and data_clean
        and historical_positive
        and exit_clear
        and market_state in {"RISK_ON", "MIXED"}
    )
    if ready:
        return {
            "status": "READY_FOR_MANUAL_REVIEW",
            "ready": True,
            "market_regime": market_state,
            "reasons": ["All strict data, historical, exit-risk, and market filters passed."],
            "required_checks": required_checks,
            "risk_controls": risk_controls,
            "read_only_research": True,
        }
    if signal.get("level") == "WATCH" and data_clean and market_state in {"RISK_ON", "MIXED"}:
        return {
            "status": "REVIEW_ONLY",
            "ready": False,
            "market_regime": market_state,
            "reasons": reasons or ["WATCH setup can be studied, but it is not ready for action."],
            "required_checks": required_checks,
            "risk_controls": risk_controls,
            "read_only_research": True,
        }
    return {
        "status": "BLOCKED",
        "ready": False,
        "market_regime": market_state,
        "reasons": reasons or ["Setup is blocked by the strict local gate."],
        "required_checks": required_checks,
        "risk_controls": risk_controls,
        "read_only_research": True,
    }


def build_trade_conclusion(signal: dict[str, Any], market_regime: dict[str, Any]) -> dict[str, Any]:
    """Translate rule outputs into a manual trading conclusion.

    This is intentionally deterministic. AI review may comment on this output later,
    but it must not overwrite the rule conclusion.
    """

    data_status = signal.get("data_status", {})
    historical = signal.get("historical_edge", {})
    exit_risk = signal.get("exit_risk", {})
    readiness = signal.get("readiness_gate", {})
    market_state = str(market_regime.get("regime", "DATA_CAUTION"))
    data_clean = data_status.get("data_quality") == "clean"
    historical_positive = (
        historical.get("sample_count", 0) >= 10
        and historical.get("focus_win_rate", historical.get("win_rate_5d", 0)) >= 52
        and historical.get("focus_avg_return", historical.get("avg_forward_return_5d", 0)) > 0
    )
    exit_status = str(exit_risk.get("status", "DATA CAUTION"))
    exit_clear = exit_status == "CLEAR"
    blockers: list[str] = []
    why: list[str] = []
    invalidation = [
        "Provider status becomes stale or failed.",
        "Price loses the profile's key EMA structure.",
        "Market regime turns RISK_OFF.",
        "Exit Risk changes to EXIT RISK or SETUP INVALIDATED.",
    ]

    if not data_clean:
        blockers.append("Data quality is not clean.")
    if market_state in {"RISK_OFF", "DATA_CAUTION"}:
        blockers.append(f"Market regime is {market_state}.")
    if not historical_positive:
        blockers.append("Profile-specific historical edge is not positive enough.")
    if not exit_clear:
        blockers.append(f"Exit risk is {exit_status}.")
    if signal.get("level") == "PASS":
        blockers.append("Rule level is PASS.")

    if signal.get("level") == "BUY SETUP":
        why.append("Rule system classifies this as BUY SETUP.")
    elif signal.get("level") == "WATCH":
        why.append("Rule system classifies this as WATCH, not a strict buy.")
    else:
        why.append("Rule system does not currently support a new long entry.")
    why.append(f"Trade readiness is {readiness.get('status', 'unknown')}.")
    why.append(f"Market regime is {market_state}.")
    why.append(
        f"Historical focus {historical.get('focus_window', 'n/a')}: win {historical.get('focus_win_rate', 0)}%, avg return {historical.get('focus_avg_return', 0)}%."
    )
    why.append(f"Exit risk status is {exit_status}.")

    if readiness.get("ready") is True and signal.get("level") == "BUY SETUP" and data_clean and historical_positive and exit_clear:
        action = "BUY"
        confidence = "HIGH" if market_state == "RISK_ON" else "MEDIUM"
        risk_bucket = "standard_risk" if confidence == "HIGH" else "light_risk"
        summary = f"BUY: {signal.get('strategy_label', signal.get('profile_name', 'profile'))} setup is ready for manual review."
    elif exit_status in {"EXIT RISK", "SETUP INVALIDATED", "TAKE PROFIT WATCH"}:
        action = "EXIT_REVIEW"
        confidence = "MEDIUM"
        risk_bucket = "avoid"
        summary = f"EXIT REVIEW: {exit_status} blocks a fresh long and requires position review if already held."
    elif signal.get("level") == "WATCH" and data_clean and market_state in {"RISK_ON", "MIXED"}:
        action = "WAIT"
        confidence = "MEDIUM"
        risk_bucket = "light_risk"
        summary = "WAIT: setup is researchable, but one or more strict buy gates are missing."
    else:
        action = "DO_NOT_BUY"
        confidence = "LOW"
        risk_bucket = "avoid"
        summary = "DO NOT BUY: current rule, data, risk, or market filters block a new long."

    return {
        "action": action,
        "confidence": confidence,
        "risk_bucket": risk_bucket,
        "decision_summary": summary,
        "why": why[:5],
        "blockers": blockers[:6],
        "invalidation": invalidation,
        "profile_name": signal.get("profile_name", ""),
        "holding_period": signal.get("holding_period", ""),
        "position_context": "no_position_assumed",
        "read_only_research": True,
        "llm_signal_core_enabled": False,
        "broker_order_wiring_enabled": False,
    }


def ai_review_model(payload: dict[str, Any]) -> str:
    requested = str(payload.get("model") or "").strip()
    tier = str(payload.get("model_tier") or "review").strip().lower()
    if requested:
        return requested
    if tier == "batch":
        return os.environ.get("KQUANT_AI_BATCH_MODEL", "gpt-5.4-mini")
    if tier in {"deep", "final", "gpt-5.5"}:
        return os.environ.get("KQUANT_AI_DEEP_MODEL", "gpt-5.5")
    return os.environ.get("KQUANT_AI_REVIEW_MODEL", "gpt-5.4")


def ai_review_context(
    symbol: str,
    profile: str,
    signal: dict[str, Any],
    profile_comparison: list[Any],
    journal: dict[str, Any],
) -> dict[str, Any]:
    comparison = [
        {
            "profile_name": item.get("profile_name"),
            "strategy_label": item.get("strategy_label"),
            "holding_period": item.get("holding_period"),
            "level": item.get("level"),
            "score": item.get("score"),
            "trade_conclusion": item.get("trade_conclusion"),
            "exit_risk": item.get("exit_risk", {}).get("status"),
            "focus_edge": {
                "window": item.get("historical_edge", {}).get("focus_window"),
                "win_rate": item.get("historical_edge", {}).get("focus_win_rate"),
                "avg_return": item.get("historical_edge", {}).get("focus_avg_return"),
            },
        }
        for item in profile_comparison[:4]
        if isinstance(item, dict)
    ]
    journal_entries = [
        {
            "status": entry.get("status"),
            "strategy_profile": entry.get("strategy_profile"),
            "notes": entry.get("notes"),
            "outcome": entry.get("outcome"),
            "reviewed_at": entry.get("reviewed_at"),
        }
        for entry in journal.get("entries", [])[:5]
    ]
    compact_signal = {
        "symbol": signal.get("symbol", symbol),
        "profile_name": signal.get("profile_name", profile),
        "strategy_label": signal.get("strategy_label"),
        "holding_period": signal.get("holding_period"),
        "level": signal.get("level"),
        "score": signal.get("score"),
        "trade_conclusion": signal.get("trade_conclusion"),
        "score_breakdown": signal.get("score_breakdown"),
        "exit_risk": signal.get("exit_risk"),
        "readiness_gate": signal.get("readiness_gate"),
        "historical_edge": signal.get("historical_edge"),
        "data_status": signal.get("data_status"),
        "risk_warnings": signal.get("risk_warnings", [])[:8],
        "trend_summary": signal.get("trend_summary"),
        "trigger_summary": signal.get("trigger_summary"),
    }
    return {
        "input_summary": {
            "symbol": symbol,
            "profile": profile,
            "rule_action": (signal.get("trade_conclusion") or {}).get("action"),
            "rule_level": signal.get("level"),
            "score": signal.get("score"),
            "journal_entries": len(journal_entries),
            "profile_comparison_count": len(comparison),
        },
        "signal": compact_signal,
        "profile_comparison": comparison,
        "journal_entries": journal_entries,
    }


def openai_review_request(model: str, context: dict[str, Any]) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ai_review_verdict": {"type": "string", "enum": ["supports_rule_conclusion", "caution", "disagrees"]},
            "quality_filter": {"type": "string", "enum": ["high_quality", "mixed", "low_quality"]},
            "rr_improvement_notes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "risk_questions": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "journal_prompt": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "downgrade_suggestion": {"type": "string", "enum": ["none", "consider_wait", "avoid_new_entry", "exit_review_if_holding"]},
            "summary": {"type": "string"},
        },
        "required": [
            "ai_review_verdict",
            "quality_filter",
            "rr_improvement_notes",
            "risk_questions",
            "journal_prompt",
            "downgrade_suggestion",
            "summary",
        ],
    }
    system = (
        "You are KQUANT AI Review Assistant. You are a read-only trading review layer. "
        "Do not place orders, do not access broker accounts, do not change the rule score, "
        "and do not upgrade a rule DO_NOT_BUY into BUY. Focus on risk, setup quality, "
        "risk/reward improvement, and journal discipline. Be concise and practical."
    )
    user = json.dumps(context, ensure_ascii=False)
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kquant_ai_review",
                "schema": schema,
                "strict": True,
            }
        },
    }


def extract_openai_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not contain text output.")


def sanitize_ai_review(review: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    rule_action = (signal.get("trade_conclusion") or {}).get("action", "DO_NOT_BUY")
    allowed_verdicts = {"supports_rule_conclusion", "caution", "disagrees"}
    allowed_quality = {"high_quality", "mixed", "low_quality"}
    allowed_downgrades = {"none", "consider_wait", "avoid_new_entry", "exit_review_if_holding"}
    sanitized = {
        "ai_review_verdict": review.get("ai_review_verdict") if review.get("ai_review_verdict") in allowed_verdicts else "caution",
        "quality_filter": review.get("quality_filter") if review.get("quality_filter") in allowed_quality else "mixed",
        "rr_improvement_notes": safe_string_list(review.get("rr_improvement_notes"), 6),
        "risk_questions": safe_string_list(review.get("risk_questions"), 6),
        "journal_prompt": safe_string_list(review.get("journal_prompt"), 6),
        "downgrade_suggestion": review.get("downgrade_suggestion") if review.get("downgrade_suggestion") in allowed_downgrades else "none",
        "summary": str(review.get("summary") or "AI review completed. Treat as commentary, not a signal-core override.")[:600],
        "rule_action": rule_action,
        "does_not_override_rule_conclusion": True,
        "cannot_upgrade_do_not_buy_to_buy": True,
    }
    if rule_action in {"DO_NOT_BUY", "EXIT_REVIEW"} and sanitized["ai_review_verdict"] == "supports_rule_conclusion":
        sanitized["quality_filter"] = "low_quality" if rule_action == "DO_NOT_BUY" else sanitized["quality_filter"]
    return sanitized


def unavailable_ai_review(signal: dict[str, Any], reason: str) -> dict[str, Any]:
    action = (signal.get("trade_conclusion") or {}).get("action", "DO_NOT_BUY")
    return {
        "ai_review_verdict": "caution",
        "quality_filter": "mixed",
        "rr_improvement_notes": [
            "AI review is unavailable; use the rule conclusion, K-line, historical edge, and exit-risk panels.",
            "Do not upgrade the setup without clean data and a saved manual journal plan.",
        ],
        "risk_questions": [
            "Is provider data live and clean?",
            "Does the selected holding-period system match the intended trade?",
        ],
        "journal_prompt": [
            "Record why the rule conclusion was accepted or rejected.",
            "Record planned entry, stop, target, and invalidation before acting manually.",
        ],
        "downgrade_suggestion": "none" if action == "BUY" else "consider_wait",
        "summary": reason,
        "rule_action": action,
        "does_not_override_rule_conclusion": True,
        "cannot_upgrade_do_not_buy_to_buy": True,
    }


def safe_string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text[:280])
        if len(result) >= limit:
            break
    return result


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
    horizons = [3, 5, 10, 20, 24, 26, 40, 63, 126]
    for index in range(70, len(candles) - 3):
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
        future = candles[index + 1 :]
        if len(future) < 3:
            continue
        entry = close
        forward_by_horizon = {horizon: pct(future[horizon - 1]["close"], entry) for horizon in horizons if len(future) >= horizon}
        drawdown_by_horizon = {
            horizon: min(pct(bar["low"], entry) for bar in future[:horizon]) for horizon in horizons if len(future) >= horizon
        }
        runup_by_horizon = {
            horizon: max(pct(bar["high"], entry) for bar in future[:horizon]) for horizon in horizons if len(future) >= horizon
        }
        forward_3d = forward_by_horizon.get(3, 0.0)
        forward_5d = forward_by_horizon.get(5, forward_3d)
        forward_10d = forward_by_horizon.get(10, forward_5d)
        max_drawdown_5d = drawdown_by_horizon.get(5, drawdown_by_horizon.get(3, 0.0))
        max_runup_5d = runup_by_horizon.get(5, runup_by_horizon.get(3, 0.0))
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
                "forward_returns_by_horizon": {str(key): round(value, 4) for key, value in forward_by_horizon.items()},
                "max_drawdowns_by_horizon": {str(key): round(value, 4) for key, value in drawdown_by_horizon.items()},
                "max_runups_by_horizon": {str(key): round(value, 4) for key, value in runup_by_horizon.items()},
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


def profile_historical_edge(edge: dict[str, Any], samples: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    horizon = int(profile.get("focus_horizon_bars", 5))
    focus_returns = [
        float((sample.get("forward_returns_by_horizon") or {}).get(str(horizon)))
        for sample in samples
        if (sample.get("forward_returns_by_horizon") or {}).get(str(horizon)) is not None
    ]
    focus_drawdowns = [
        float((sample.get("max_drawdowns_by_horizon") or {}).get(str(horizon)))
        for sample in samples
        if (sample.get("max_drawdowns_by_horizon") or {}).get(str(horizon)) is not None
    ]
    target = float(profile.get("target_return_pct", 2.0))
    if not focus_returns:
        return edge | {
            "focus_window": profile.get("focus_window", "5D"),
            "focus_horizon_bars": horizon,
            "focus_sample_count": 0,
            "focus_win_rate": 0.0,
            "focus_target_hit_rate": 0.0,
            "focus_avg_return": 0.0,
            "focus_avg_max_drawdown": 0.0,
            "profile_verdict": "limited",
            "profile_note": "Not enough historical samples for this holding-period profile.",
        }
    win_rate = sum(1 for value in focus_returns if value > 0) / len(focus_returns) * 100
    target_hit_rate = sum(1 for value in focus_returns if value >= target) / len(focus_returns) * 100
    avg_return = sum(focus_returns) / len(focus_returns)
    avg_drawdown = sum(focus_drawdowns) / len(focus_drawdowns) if focus_drawdowns else 0.0
    verdict = (
        "positive"
        if win_rate >= float(profile.get("focus_win_rate_min", 52.0)) and avg_return > float(profile.get("focus_avg_return_min", 0.0))
        else "unproven"
    )
    return edge | {
        "focus_window": profile.get("focus_window", "5D"),
        "focus_horizon_bars": horizon,
        "focus_sample_count": len(focus_returns),
        "focus_win_rate": round(win_rate, 1),
        "focus_target_hit_rate": round(target_hit_rate, 1),
        "focus_avg_return": round(avg_return, 2),
        "focus_avg_max_drawdown": round(avg_drawdown, 2),
        "profile_verdict": verdict,
        "profile_note": f"Profile edge uses {profile.get('focus_window')} forward-return samples, not generic 5D only.",
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


def summarize_profile_validation(label_samples_by_symbol: dict[str, list[dict[str, Any]]], profile: dict[str, Any]) -> dict[str, Any]:
    samples = [sample for symbol_samples in label_samples_by_symbol.values() for sample in symbol_samples]
    edge = profile_historical_edge(empty_historical_edge(), samples, profile)
    return {
        "profile_name": profile["name"],
        "label": profile["label"],
        "holding_period": profile["holding_period"],
        "focus_window": edge["focus_window"],
        "focus_horizon_bars": edge["focus_horizon_bars"],
        "sample_count": edge["focus_sample_count"],
        "win_rate": edge["focus_win_rate"],
        "target_hit_rate": edge["focus_target_hit_rate"],
        "avg_forward_return": edge["focus_avg_return"],
        "avg_max_drawdown": edge["focus_avg_max_drawdown"],
        "verdict": edge["profile_verdict"],
        "note": "Strategy-profile validation uses the profile holding window, not generic 5D only.",
    }


def summarize_validation_by_level(signals: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for level in ("BUY SETUP", "WATCH", "PASS"):
        level_signals = [signal for signal in signals if signal.get("level") == level]
        total_samples = sum(int((signal.get("historical_edge") or {}).get("sample_count", 0)) for signal in level_signals)
        result[level] = {
            "signal_count": len(level_signals),
            "sample_count": total_samples,
            "win_rate_5d": weighted_historical_metric(level_signals, "win_rate_5d", total_samples),
            "target_hit_rate_5d": weighted_historical_metric(level_signals, "target_hit_rate_5d", total_samples),
            "avg_forward_return_5d": weighted_historical_metric(level_signals, "avg_forward_return_5d", total_samples),
            "avg_max_drawdown_5d": weighted_historical_metric(level_signals, "avg_max_drawdown_5d", total_samples),
            "noise_rate": round(100 - weighted_historical_metric(level_signals, "target_hit_rate_5d", total_samples), 1) if total_samples else 0.0,
        }
    return result


def live_health_usability(summary: dict[str, Any]) -> dict[str, Any]:
    checks = int(summary.get("timeframe_checks", 0) or 0)
    failed = int(summary.get("provider_error_checks", 0) or 0)
    stale = int(summary.get("stale_cache_checks", 0) or 0)
    if checks <= 0:
        return {
            "status": "not_scanned",
            "label": "Not scanned",
            "reason": "No live health report yet. Run a manual health check before trusting signals.",
            "failed_ratio": 0.0,
        }
    failed_ratio = round((failed + stale) / checks, 4)
    if failed == 0 and stale == 0:
        return {
            "status": "daily_usable",
            "label": "Daily usable",
            "reason": "All checked timeframes returned live candles.",
            "failed_ratio": failed_ratio,
        }
    if failed_ratio <= 0.25:
        return {
            "status": "degraded",
            "label": "Degraded",
            "reason": "Some symbols are stale or failed; use Data Caution and review only clean setups.",
            "failed_ratio": failed_ratio,
        }
    return {
        "status": "not_usable",
        "label": "Not usable",
        "reason": "Too many provider failures or stale-cache reads for a reliable daily scan.",
        "failed_ratio": failed_ratio,
    }


def signal_review_bucket(signal: dict[str, Any]) -> str:
    data = signal.get("data_status") or {}
    edge = signal.get("historical_edge") or {}
    exit_risk = signal.get("exit_risk") or {}
    clean_data = (
        data.get("data_quality") == "clean"
        and data.get("daily_provider_status") == "available"
        and data.get("hourly_provider_status") == "available"
    )
    if (
        signal.get("level") == "BUY SETUP"
        and clean_data
        and edge.get("profile_verdict", edge.get("verdict")) == "positive"
        and exit_risk.get("status") == "CLEAR"
    ):
        return "high_priority"
    if signal.get("level") == "PASS":
        return "pass"
    return "watch"


def downgraded_reasons(signal: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    data = signal.get("data_status") or {}
    edge = signal.get("historical_edge") or {}
    exit_risk = signal.get("exit_risk") or {}
    features = signal.get("features") or {}
    if data.get("data_quality") != "clean":
        reasons.append("data quality is not clean")
    if data.get("daily_provider_status") != "available" or data.get("hourly_provider_status") != "available":
        reasons.append("provider degraded or using stale cache")
    if edge.get("profile_verdict", edge.get("verdict")) != "positive":
        reasons.append("profile historical edge is not positive")
    if exit_risk.get("status") not in (None, "CLEAR"):
        reasons.append(f"exit risk is {exit_risk.get('status')}")
    if float(features.get("extension_pct", 0.0) or 0.0) > 8:
        reasons.append("price is extended above EMA20")
    if float(features.get("atr_pct", 0.0) or 0.0) > 5:
        reasons.append("ATR risk is elevated")
    if signal.get("level") == "PASS":
        reasons.append("score or trend confirmation is below watch threshold")
    if not reasons and signal.get("review_bucket") != "high_priority":
        reasons.append("not enough clean confirmation for high priority")
    return reasons[:6]


def summarize_review_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "high_priority": sum(1 for signal in signals if signal.get("review_bucket") == "high_priority"),
        "watch": sum(1 for signal in signals if signal.get("review_bucket") == "watch"),
        "pass": sum(1 for signal in signals if signal.get("review_bucket") == "pass"),
        "downgraded": sum(1 for signal in signals if signal.get("review_bucket") != "high_priority"),
    }


def summarize_trade_conclusions(signals: list[dict[str, Any]]) -> dict[str, int]:
    actions = ["BUY", "WAIT", "DO_NOT_BUY", "HOLD_TRAIL", "EXIT_REVIEW"]
    return {action: sum(1 for signal in signals if (signal.get("trade_conclusion") or {}).get("action") == action) for action in actions}


def signal_provider_coverage(signals: list[dict[str, Any]], universe_total: int) -> dict[str, Any]:
    available = stale = failed = 0
    for signal in signals:
        data = signal.get("data_status") or {}
        statuses = {data.get("daily_provider_status"), data.get("hourly_provider_status")}
        if statuses == {"available"}:
            available += 1
        elif "available" in statuses or "stale_cache" in statuses:
            stale += 1
        else:
            failed += 1
    scanned = len(signals)
    return {
        "universe_total": universe_total,
        "scanned": scanned,
        "available": available,
        "stale_or_partial": stale,
        "failed": failed,
        "unscanned": max(0, universe_total - scanned),
        "coverage_pct": round(scanned / universe_total * 100, 1) if universe_total else 0.0,
    }


def candle_payload_meta(payload: dict[str, Any]) -> dict[str, Any]:
    candles = payload.get("candles", [])
    return {
        "symbol": payload.get("symbol"),
        "range": payload.get("range"),
        "interval": payload.get("interval"),
        "source_type": payload.get("source_type"),
        "provider_status": payload.get("provider_status"),
        "freshness": payload.get("freshness"),
        "freshness_seconds": payload.get("freshness_seconds", 0),
        "candle_count": len(candles),
        "first_time": candles[0].get("open_time") if candles else "",
        "last_time": candles[-1].get("open_time") if candles else "",
        "provider_errors": payload.get("provider_errors", [])[:5],
        "live_does_not_fallback_to_fixture": bool(payload.get("live_does_not_fallback_to_fixture")),
    }


def sort_signals_for_review(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket_rank = {"high_priority": 0, "watch": 1, "pass": 2}

    def sort_key(signal: dict[str, Any]) -> tuple[float, float, float, float]:
        edge = signal.get("historical_edge") or {}
        exit_risk = signal.get("exit_risk") or {}
        data = signal.get("data_status") or {}
        clean_data_bonus = 1.0 if data.get("data_quality") == "clean" else 0.0
        exit_clear_bonus = 1.0 if exit_risk.get("status") == "CLEAR" else 0.0
        edge_score = float(edge.get("win_rate_5d", 0.0) or 0.0) + float(edge.get("avg_forward_return_5d", 0.0) or 0.0)
        return (
            bucket_rank.get(str(signal.get("review_bucket")), 9),
            -clean_data_bonus,
            -exit_clear_bonus,
            -(edge_score + float(signal.get("score", 0.0) or 0.0) * 0.15),
        )

    return sorted(signals, key=sort_key)


def latest_stock_run_id(db_path: Path) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT run_id
            FROM stock_signal_runs
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
    return str(row["run_id"]) if row else None


def stock_journal_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "run_id": row["run_id"],
        "symbol": row["symbol"],
        "strategy_profile": row["strategy_profile"] if "strategy_profile" in row.keys() else "",
        "rule_conclusion": row["rule_conclusion"] if "rule_conclusion" in row.keys() else "",
        "ai_review_verdict": row["ai_review_verdict"] if "ai_review_verdict" in row.keys() else "",
        "status": row["status"],
        "notes": row["notes"],
        "planned_entry": row["planned_entry"],
        "planned_stop": row["planned_stop"],
        "planned_target": row["planned_target"],
        "outcome": row["outcome"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "read_only_research": True,
    }


def optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def weighted_historical_metric(signals: list[dict[str, Any]], metric: str, total_samples: int) -> float:
    if total_samples <= 0:
        return 0.0
    value = 0.0
    for signal in signals:
        edge = signal.get("historical_edge") or {}
        sample_count = int(edge.get("sample_count", 0))
        value += float(edge.get(metric, 0.0)) * sample_count
    return round(value / total_samples, 2)


def pct(value: float, reference: float) -> float:
    return (value / max(reference, 0.0001) - 1) * 100


def clamp(value: float, min_value: float, max_value: float) -> float:
    return min(max(value, min_value), max_value)


def iso_now() -> str:
    return datetime.now(UTC).isoformat()
