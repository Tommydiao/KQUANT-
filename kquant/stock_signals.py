from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
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
RANGE_INTERVAL_SPECS = {
    ("1d", "1m"): {"bars": 390, "step": timedelta(minutes=1), "interval": "1m"},
    ("1d", "5m"): {"bars": 78, "step": timedelta(minutes=5), "interval": "5m"},
    ("5d", "15m"): {"bars": 130, "step": timedelta(minutes=15), "interval": "15m"},
    ("5d", "1h"): {"bars": 35, "step": timedelta(hours=1), "interval": "1h"},
    ("1y", "1d"): {"bars": 252, "step": timedelta(days=1), "interval": "1d"},
    ("5y", "1wk"): {"bars": 260, "step": timedelta(days=7), "interval": "1wk"},
    ("10y", "1mo"): {"bars": 120, "step": timedelta(days=30), "interval": "1mo"},
}
HEALTH_TIMEFRAMES = [
    {"key": "1H", "range": "5d", "interval": "1h"},
    {"key": "1D", "range": "1y", "interval": "1d"},
    {"key": "1W", "range": "5y", "interval": "1wk"},
    {"key": "1M", "range": "10y", "interval": "1mo"},
]
LONG_BRIDGE_CANDLE_SOURCE = "longbridge_candles"
LONG_BRIDGE_STALE_SOURCE = "stale_longbridge_cache"
YAHOO_FALLBACK_SOURCE = "yahoo_public_fallback"
REAL_MONEY_CANDLE_SOURCE = LONG_BRIDGE_CANDLE_SOURCE
LONG_BRIDGE_TIMEOUT_SECONDS = int(os.getenv("KQUANT_LONGBRIDGE_TIMEOUT_SECONDS", "12"))
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
        "stop_loss_pct": 3.5,
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
        "stop_loss_pct": 3.5,
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
        "stop_loss_pct": 5.0,
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
        "stop_loss_pct": 8.0,
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
        "stop_loss_pct": 18.0,
        "formula": "monthly/weekly cycle trend + distance from extremes + long relative strength + narrative risk",
    },
    "high_beta_growth_v1": {
        "name": "high_beta_growth_v1",
        "label": "High-Beta Growth",
        "holding_period": "3-15 trading days",
        "buy_setup_threshold": 78,
        "strict_buy_gate_score": 82,
        "watch_threshold": 62,
        "direction": "long_only",
        "primary_range": "1y",
        "primary_interval": "1d",
        "confirmation_range": "5d",
        "confirmation_interval": "1h",
        "primary_timeframe": "1D",
        "confirmation_timeframe": "1H",
        "focus_window": "10D",
        "focus_horizon_bars": 10,
        "target_return_pct": 6.0,
        "max_atr_pct": 12.0,
        "max_extension_pct": 12.0,
        "confirmation_momentum_min": 0.8,
        "volume_ratio_min": 0.9,
        "focus_win_rate_min": 48.0,
        "focus_avg_return_min": 1.0,
        "stop_loss_pct": 8.0,
        "pullback_ema50_floor": 0.97,
        "high_beta_growth": True,
        "formula": "high-beta growth pullback + 1h momentum turn + looser volume + wider ATR risk",
    },
}
PROFILE = PROFILE_CONFIGS["swing_long_v1"]
MARKET_REGIME_SYMBOLS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "^VIX": "VIX",
}
STOCK_JOURNAL_STATUSES = {
    "probe",
    "full_review",
    "reviewed",
    "watch",
    "skipped",
    "paper-observed",
    "manual-traded",
    "entered-manually",
    "exited-manually",
    "invalidated",
}
MANUAL_ENTRY_JOURNAL_STATUSES = {"manual-traded", "entered-manually"}


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
    "具身智能": ("embodied", "robotics", "automation", "sensors", "machine_vision", "motor_control"),
    "人形机器人": ("humanoid", "robotics", "automation", "embodied", "sensors"),
    "减速器": ("robotics", "automation", "motor_control", "industrial_automation"),
    "传感器": ("sensors", "machine_vision", "lidar", "3d_sensing", "analog_semis"),
    "无人机": ("drones", "unmanned_systems", "low_altitude", "defense_tech", "evtol"),
    "低空经济": ("drones", "evtol", "low_altitude", "autonomous_aircraft", "aviation"),
    "太空": ("space", "rocket", "satellite", "aerospace", "space robotics"),
    "航天": ("space", "rocket", "satellite", "aerospace", "space robotics"),
    "太空探索": ("space", "space_exploration", "launch", "satellite", "lunar"),
    "卫星星座": ("satellite", "space", "satellite_network", "direct_to_device", "earth_observation"),
    "空间计算": ("spatial_computing", "ar", "vr_ar", "mixed_reality", "lidar", "3d_sensing"),
    "激光雷达": ("lidar", "3d_sensing", "4d_sensing", "spatial_computing", "autonomy"),
    "芯片": ("chips", "semis", "semiconductor", "ai semis", "foundry"),
    "半导体": ("chips", "semis", "semiconductor", "ai semis", "foundry"),
    "存储": ("storage", "memory", "nand", "hdd", "ai_storage", "sndk", "wdc", "stx", "mu"),
    "内存": ("memory", "hbm", "storage", "mu", "sndk"),
    "光模块": ("optical", "photonics", "datacenter_interconnect", "ai_networking", "cohr", "fn", "lite", "crdo"),
    "光互联": ("optical", "photonics", "datacenter_interconnect", "ai_networking", "cohr", "fn", "lite", "crdo"),
    "硅光": ("optical", "photonics", "datacenter_interconnect", "cohr", "lite"),
    "gpu云": ("neocloud", "gpu_cloud", "ai_datacenter", "iren", "nbis", "corz"),
    "gpu 云": ("neocloud", "gpu_cloud", "ai_datacenter", "iren", "nbis", "corz"),
    "新云": ("neocloud", "gpu_cloud", "ai_datacenter", "iren", "nbis", "corz"),
    "电源半导体": ("power_semis", "gan", "sic", "ai_power", "nvts", "mpwr", "on"),
    "氮化镓": ("gan", "power_semis", "ai_power", "nvts"),
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
    "AVAV": ("aerovironment", "无人机", "drones", "unmanned systems"),
    "RCAT": ("red cat", "无人机", "drones", "teal drones"),
    "ONDS": ("ondas", "无人机", "autonomous systems", "drones"),
    "UMAC": ("unusual machines", "无人机", "drone components"),
    "EH": ("ehang", "低空经济", "evtol", "autonomous aircraft"),
    "TRMB": ("trimble", "传感器", "positioning", "industrial automation"),
    "KEYS": ("keysight", "传感器", "test equipment", "robotics"),
    "SNAP": ("snap", "空间计算", "ar glasses", "augmented reality"),
    "VUZI": ("vuzix", "空间计算", "ar glasses"),
    "KOPN": ("kopin", "空间计算", "microdisplays", "ar vr"),
    "MVIS": ("microvision", "激光雷达", "lidar", "3d sensing"),
    "LAZR": ("luminar", "激光雷达", "lidar", "autonomy"),
    "HSAI": ("hesai", "激光雷达", "lidar", "3d sensing"),
    "AEVA": ("aeva", "激光雷达", "4d lidar", "sensing"),
    "SPIR": ("spire global", "太空探索", "satellite data"),
    "BKSY": ("blacksky", "太空探索", "satellite imagery"),
    "RDW": ("redwire", "太空探索", "space infrastructure"),
    "GSAT": ("globalstar", "卫星星座", "satellite network"),
    "SATL": ("satellogic", "太空探索", "earth observation"),
    "ARKX": ("space exploration etf", "太空探索", "space etf"),
    "SNDK": ("sandisk", "存储", "nand", "ai storage"),
    "MU": ("micron", "内存", "存储", "hbm"),
    "IREN": ("gpu cloud", "neocloud", "gpu云", "新云", "ai datacenter"),
    "NVTS": ("navitas", "电源半导体", "氮化镓", "gan", "sic"),
    "COHR": ("coherent", "光模块", "光互联", "silicon photonics", "optical"),
    "FN": ("fabrinet", "光模块", "optical manufacturing"),
    "LITE": ("lumentum", "光模块", "光互联", "photonics"),
    "ALAB": ("astera labs", "ai connectivity", "pcie", "datacenter"),
    "CRDO": ("credo", "ai networking", "serdes", "datacenter"),
    "NBIS": ("nebius", "gpu cloud", "neocloud", "gpu云"),
    "CORZ": ("core scientific", "neocloud", "ai datacenter", "bitcoin miner conversion"),
    "SERV": ("serve robotics", "机器人", "delivery robotics", "autonomy"),
    "AMBA": ("ambarella", "edge ai", "computer vision", "autonomy"),
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


def annotate_cache_write_failure(payload: dict[str, Any], exc: Exception) -> None:
    message = f"cache_write_failed: {type(exc).__name__}: {str(exc)[:180]}"
    provider_errors = list(payload.get("provider_errors") or [])
    if message not in provider_errors:
        provider_errors.append(message)
    payload["provider_errors"] = provider_errors
    payload["cache_write_status"] = "failed"
    payload["cache_write_error"] = message
    payload["live_data_returned_despite_cache_write_failure"] = True


def candle_spec(range_value: str, interval: str) -> dict[str, Any]:
    return RANGE_INTERVAL_SPECS.get((range_value, interval), RANGES.get(range_value, RANGES["1y"]))


def preferred_market_data_provider() -> str:
    configured = str(os.getenv("KQUANT_MARKET_DATA_PROVIDER", "")).strip().lower()
    if configured in {"longbridge", "lb"}:
        return "longbridge"
    if configured in {"yahoo", "yahoo_public", "public"}:
        return "yahoo"
    if longbridge_env_ready():
        return "longbridge"
    return "yahoo"


def longbridge_env_ready() -> bool:
    return all(
        bool(os.getenv(name))
        for name in ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")
    )


def longbridge_symbol(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if "." in normalized and normalized.rsplit(".", 1)[-1] in {"US", "HK", "SH", "SZ"}:
        return normalized
    if normalized.startswith("^"):
        return normalized
    return f"{normalized}.US"


def _decimal_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return default


def _pick_attr(item: Any, names: tuple[str, ...]) -> Any:
    if isinstance(item, dict):
        for name in names:
            if name in item:
                return item[name]
    for name in names:
        if hasattr(item, name):
            return getattr(item, name)
    return None


def _parse_market_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            return value.replace(tzinfo=local_tz).astimezone(UTC)
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, UTC)
    text = str(value)
    if text.isdigit():
        return _parse_market_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo
            return parsed.replace(tzinfo=local_tz).astimezone(UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _current_us_regular_session_start(now: datetime | None = None) -> datetime:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    candidate = current.replace(
        hour=MARKET_OPEN_UTC_HOUR,
        minute=MARKET_OPEN_UTC_MINUTE,
        second=0,
        microsecond=0,
    )
    if current < candidate:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _filter_today_intraday_candles(
    candles: list[dict[str, Any]],
    range_value: str,
    interval: str,
) -> list[dict[str, Any]]:
    if range_value != "1d" or interval not in {"1m", "5m"}:
        return candles
    session_start = _current_us_regular_session_start()
    filtered = [
        candle
        for candle in candles
        if (parsed := _parse_market_time(candle.get("open_time"))) is not None and parsed >= session_start
    ]
    return filtered or candles


def _longbridge_period(interval: str) -> Any:
    try:
        from longbridge.openapi import Period  # type: ignore
    except Exception as exc:  # pragma: no cover - optional SDK
        raise RuntimeError("longbridge Python SDK is not installed") from exc

    candidates = {
        "1m": ("Min1", "Min_1", "MIN_1", "OneMinute"),
        "5m": ("Min5", "Min_5", "MIN_5", "FiveMinute"),
        "15m": ("Min15", "Min_15", "MIN_15", "FifteenMinute"),
        "1h": ("Min60", "Min_60", "MIN_60", "Hour", "OneHour"),
        "1d": ("Day", "DAY", "Daily"),
        "1wk": ("Week", "WEEK", "Weekly"),
        "1mo": ("Month", "MONTH", "Monthly"),
    }.get(interval, ("Day", "DAY", "Daily"))
    for name in candidates:
        if hasattr(Period, name):
            return getattr(Period, name)
    raise RuntimeError(f"longbridge SDK does not expose a Period enum for interval {interval}")


def _longbridge_period_name(interval: str) -> str:
    return {
        "1m": "Min_1",
        "5m": "Min_5",
        "15m": "Min_15",
        "1h": "Min_60",
        "1d": "Day",
        "1wk": "Week",
        "1mo": "Month",
    }.get(interval, "Day")


def _run_longbridge_subprocess(action: str, payload: dict[str, Any], timeout_seconds: int | None = None) -> dict[str, Any]:
    timeout = timeout_seconds or LONG_BRIDGE_TIMEOUT_SECONDS
    code = r'''
import json
import os
from datetime import datetime, timezone

from longbridge.openapi import AdjustType, Config, Period, QuoteContext

request = json.loads(__import__("sys").stdin.read())
action = request["action"]
payload = request["payload"]

def pick(obj, names):
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
        if isinstance(obj, dict) and obj.get(name) is not None:
            return obj.get(name)
    return None

def decimal_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        try:
            return float(str(value))
        except Exception:
            return default

def market_time(value):
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        dt = value
    else:
        text = str(value)
        if text.isdigit():
            number = int(text)
            if number > 10_000_000_000:
                number = number / 1000
            return datetime.fromtimestamp(number, tz=timezone.utc).isoformat()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return text
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt.astimezone(timezone.utc).isoformat()

config = Config.from_apikey(
    os.environ.get("LONGBRIDGE_APP_KEY"),
    os.environ.get("LONGBRIDGE_APP_SECRET"),
    os.environ.get("LONGBRIDGE_ACCESS_TOKEN"),
    enable_print_quote_packages=False,
)
ctx = QuoteContext(config)
symbol = payload["symbol"]

if action == "quote":
    rows = ctx.quote([symbol])
    quote = list(rows or [None])[0]
    if quote is None:
        raise RuntimeError("Longbridge returned no quote.")
    quote_time = market_time(pick(quote, ["timestamp", "time", "quote_time", "trade_time"]))
    print(json.dumps({
        "quote_time": quote_time,
        "last": decimal_float(pick(quote, ["last_done", "last", "price", "current_price", "close"])),
        "bid": decimal_float(pick(quote, ["bid", "bid_price"])),
        "ask": decimal_float(pick(quote, ["ask", "ask_price"])),
    }, ensure_ascii=False))
elif action == "candles":
    period = getattr(Period, payload["period"])
    adjust = getattr(AdjustType, "NoAdjust")
    rows = ctx.candlesticks(symbol, period, int(payload["count"]), adjust)
    candles = []
    for row in list(rows or []):
        open_time = market_time(pick(row, ["timestamp", "time", "open_time", "date", "datetime"]))
        open_ = decimal_float(pick(row, ["open", "open_price"]))
        high = decimal_float(pick(row, ["high", "high_price"]))
        low = decimal_float(pick(row, ["low", "low_price"]))
        close = decimal_float(pick(row, ["close", "close_price"]))
        volume = decimal_float(pick(row, ["volume", "turnover", "trade_volume"]), 0.0)
        if open_time is None or None in (open_, high, low, close):
            continue
        candles.append({
            "open_time": open_time,
            "open": round(float(open_), 4),
            "high": round(float(high), 4),
            "low": round(float(low), 4),
            "close": round(float(close), 4),
            "volume": float(volume or 0.0),
        })
    print(json.dumps({"candles": candles}, ensure_ascii=False))
else:
    raise RuntimeError(f"Unsupported Longbridge action: {action}")
'''
    env = os.environ.copy()
    env["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"
    request = json.dumps({"action": action, "payload": payload})
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=request,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Longbridge {action} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or f"Longbridge {action} failed").strip()
        raise RuntimeError(message)
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"Longbridge {action} returned no JSON payload")


def _longbridge_config() -> Any:
    try:
        from longbridge.openapi import Config  # type: ignore
    except Exception as exc:  # pragma: no cover - optional SDK
        raise RuntimeError("longbridge Python SDK is not installed") from exc
    if hasattr(Config, "from_apikey"):
        return Config.from_apikey(
            os.getenv("LONGBRIDGE_APP_KEY"),
            os.getenv("LONGBRIDGE_APP_SECRET"),
            os.getenv("LONGBRIDGE_ACCESS_TOKEN"),
            enable_print_quote_packages=False,
        )
    if hasattr(Config, "from_apikey_env"):
        os.environ.setdefault("LONGBRIDGE_PRINT_QUOTE_PACKAGES", "false")
        return Config.from_apikey_env()
    raise RuntimeError("longbridge SDK does not expose API-key configuration")


def _run_longbridge_call(label: str, fn: Any, timeout_seconds: int | None = None) -> Any:
    timeout = timeout_seconds or LONG_BRIDGE_TIMEOUT_SECONDS
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kquant-longbridge")
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"Longbridge {label} timed out after {timeout}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _longbridge_adjust_type() -> Any:
    try:
        from longbridge.openapi import AdjustType  # type: ignore
    except Exception:  # pragma: no cover - optional SDK
        return None
    for name in ("NoAdjust", "NO_ADJUST", "NoneAdjust", "ForwardAdjust"):
        if hasattr(AdjustType, name):
            return getattr(AdjustType, name)
    return None


def api_stock_market_data_status(db_path: Path | None = None) -> dict[str, Any]:
    provider = preferred_market_data_provider()
    longbridge_ready = longbridge_env_ready()
    sdk_status = "unknown"
    if provider == "longbridge" or longbridge_ready:
        try:
            import longbridge.openapi  # type: ignore  # noqa: F401

            sdk_status = "installed"
        except Exception:
            sdk_status = "missing_sdk"
    status = "available" if provider == "longbridge" and longbridge_ready and sdk_status == "installed" else "missing"
    if provider != "longbridge":
        status = "standby"
    latest_longbridge_cache = None
    path = db_path or default_db_path()
    try:
        with connect(path) as conn:
            row = conn.execute(
                "SELECT MAX(created_at) AS value FROM stock_candles WHERE source = ?",
                (LONG_BRIDGE_CANDLE_SOURCE,),
            ).fetchone()
            latest_longbridge_cache = row["value"] if row else None
    except (OSError, sqlite3.Error):
        latest_longbridge_cache = None
    return {
        "provider": provider,
        "status": status,
        "longbridge_env": "configured" if longbridge_ready else "missing",
        "longbridge_sdk": sdk_status,
        "longbridge_market_data_only": True,
        "longbridge_account_enabled": False,
        "longbridge_trade_enabled": False,
        "default_source_type": LONG_BRIDGE_CANDLE_SOURCE if provider == "longbridge" else "live_yahoo_chart",
        "latest_longbridge_cache": latest_longbridge_cache,
        "yahoo_public_fallback": True,
        "real_money_requires_longbridge_live": True,
    }


def longbridge_candles(symbol: str, range_value: str, interval: str) -> dict[str, Any]:
    if not longbridge_env_ready():
        return unavailable_candles(
            symbol,
            range_value,
            interval,
            "Longbridge environment variables are missing.",
            source_type=LONG_BRIDGE_CANDLE_SOURCE,
        )
    try:
        import longbridge.openapi  # type: ignore  # noqa: F401
    except Exception as exc:  # pragma: no cover - optional SDK
        return unavailable_candles(
            symbol,
            range_value,
            interval,
            f"longbridge Python SDK unavailable: {exc}",
            source_type=LONG_BRIDGE_CANDLE_SOURCE,
        )
    try:
        lb_symbol = longbridge_symbol(symbol)
        count = int(candle_spec(range_value, interval)["bars"])
        result = _run_longbridge_subprocess(
            "candles",
            {"symbol": lb_symbol, "period": _longbridge_period_name(interval), "count": count},
        )
        candles: list[dict[str, Any]] = []
        for row in list(result.get("candles") or []):
            open_time = _parse_market_time(
                _pick_attr(row, ("timestamp", "time", "open_time", "date", "datetime"))
            )
            open_ = _decimal_float(_pick_attr(row, ("open", "open_price")))
            high = _decimal_float(_pick_attr(row, ("high", "high_price")))
            low = _decimal_float(_pick_attr(row, ("low", "low_price")))
            close = _decimal_float(_pick_attr(row, ("close", "close_price")))
            volume = _decimal_float(_pick_attr(row, ("volume", "turnover", "trade_volume")), 0.0)
            if open_time is None or None in (open_, high, low, close):
                continue
            candles.append(
                {
                    "open_time": open_time.isoformat(),
                    "time": int(open_time.timestamp()),
                    "open": round(float(open_), 4),
                    "high": round(float(high), 4),
                    "low": round(float(low), 4),
                    "close": round(float(close), 4),
                    "volume": float(volume or 0.0),
                    "source": LONG_BRIDGE_CANDLE_SOURCE,
                }
            )
        candles.sort(key=lambda candle: int(candle["time"]))
        candles = _filter_today_intraday_candles(candles, range_value, interval)
        if not candles:
            return unavailable_candles(
                symbol,
                range_value,
                interval,
                "Longbridge returned 0 candles.",
                source_type=LONG_BRIDGE_CANDLE_SOURCE,
            )
        latest_age = max(0, int((datetime.now(UTC) - datetime.fromisoformat(candles[-1]["open_time"])).total_seconds()))
        return {
            "instrument_type": "stock",
            "symbol": symbol,
            "provider_symbol": lb_symbol,
            "range": range_value,
            "interval": interval,
            "source_type": LONG_BRIDGE_CANDLE_SOURCE,
            "provider_status": "available",
            "provider_errors": [],
            "provider": "longbridge",
            "freshness": "live",
            "freshness_seconds": latest_age,
            "session": market_session_now(),
            "candle_time": candles[-1]["open_time"],
            "candles": candles[-count:],
            "real_money_data_source": True,
            "read_only_market_data": True,
        }
    except Exception as exc:  # pragma: no cover - depends on provider/network
        return unavailable_candles(
            symbol,
            range_value,
            interval,
            str(exc),
            source_type=LONG_BRIDGE_CANDLE_SOURCE,
        )


def api_stock_quote(symbol: str, db_path: Path | None = None) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    if preferred_market_data_provider() != "longbridge":
        return {
            "symbol": symbol,
            "provider": preferred_market_data_provider(),
            "provider_status": "standby",
            "source_type": "no_longbridge_quote",
            "message": "Set KQUANT_MARKET_DATA_PROVIDER=longbridge to enable Longbridge realtime quotes.",
            "read_only_market_data": True,
        }
    if not longbridge_env_ready():
        return {
            "symbol": symbol,
            "provider": "longbridge",
            "provider_status": "missing_config",
            "source_type": "longbridge_quote",
            "message": "Longbridge env vars are missing.",
            "read_only_market_data": True,
        }
    try:
        import longbridge.openapi  # type: ignore  # noqa: F401

        lb_symbol = longbridge_symbol(symbol)
        quote = _run_longbridge_subprocess("quote", {"symbol": lb_symbol})
        quote_time = _parse_market_time(quote.get("quote_time"))
        last = _decimal_float(quote.get("last"))
        bid = _decimal_float(quote.get("bid"))
        ask = _decimal_float(quote.get("ask"))
        return {
            "symbol": symbol,
            "provider_symbol": lb_symbol,
            "provider": "longbridge",
            "source_type": "longbridge_quote",
            "provider_status": "available",
            "last": last,
            "bid": bid,
            "ask": ask,
            "quote_time": quote_time.isoformat() if quote_time else None,
            "session": market_session_now(),
            "freshness_seconds": max(0, int((datetime.now(UTC) - quote_time).total_seconds())) if quote_time else None,
            "read_only_market_data": True,
        }
    except Exception as exc:  # pragma: no cover - optional SDK/provider
        return {
            "symbol": symbol,
            "provider": "longbridge",
            "source_type": "longbridge_quote",
            "provider_status": "unavailable",
            "provider_errors": [str(exc)],
            "session": market_session_now(),
            "read_only_market_data": True,
        }


def market_session_now(now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if current.weekday() >= 5:
        return "closed"
    open_time = current.replace(hour=MARKET_OPEN_UTC_HOUR, minute=MARKET_OPEN_UTC_MINUTE, second=0, microsecond=0)
    close_time = current.replace(hour=MARKET_CLOSE_UTC_HOUR, minute=0, second=0, microsecond=0)
    if open_time <= current <= close_time:
        return "regular"
    if current < open_time:
        return "pre_market"
    return "after_hours"


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
        provider = preferred_market_data_provider()
        payload = longbridge_candles(symbol, range_value, interval) if provider == "longbridge" else yahoo_candles(symbol, range_value, interval)
        if payload["provider_status"] != "available" and db_path:
            try:
                record_provider_event(
                    db_path,
                    provider="longbridge_quote" if provider == "longbridge" else "yahoo_chart",
                    instrument="stock",
                    symbol=symbol,
                    status=payload["provider_status"],
                    message="; ".join(payload.get("provider_errors", [])) or "public provider unavailable",
                )
            except (OSError, sqlite3.Error) as exc:
                annotate_cache_write_failure(payload, exc)
            cached = cached_candles_payload(
                db_path,
                symbol,
                range_value,
                interval,
                payload,
                source_types=(LONG_BRIDGE_CANDLE_SOURCE,) if provider == "longbridge" else ("live_yahoo_chart",),
            )
            if cached:
                return cached
            if provider == "longbridge":
                fallback = yahoo_candles(symbol, range_value, interval)
                if fallback["provider_status"] == "available":
                    fallback["source_type"] = YAHOO_FALLBACK_SOURCE
                    fallback["provider_status"] = "fallback"
                    fallback["provider"] = "yahoo_public"
                    fallback["provider_errors"] = payload.get("provider_errors", []) + [
                        "Longbridge unavailable; Yahoo fallback is non-realtime and not valid for money-pilot buy actions."
                    ]
                    fallback["freshness"] = "fallback_non_realtime"
                    fallback["real_money_data_source"] = False
                    fallback["live_does_not_fallback_to_fixture"] = True
                    payload = fallback
    else:
        payload = fixture_candles_payload(symbol, range_value, interval)
    if db_path:
        try:
            persist_candles(db_path, payload)
            payload["cache_write_status"] = "ok"
        except (OSError, sqlite3.Error) as exc:
            annotate_cache_write_failure(payload, exc)
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
        "market_data": api_stock_market_data_status(db_path=path),
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
                expected = int(candle_spec(str(payload.get("range", timeframe["range"])), str(payload.get("interval", timeframe["interval"])))["bars"])
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


def api_stock_monday_readiness_latest(outputs_dir: Path | None = None) -> dict[str, Any]:
    outputs = outputs_dir or Path("outputs")
    report = outputs / "monday-pilot-readiness.json"
    markdown = outputs / "monday-pilot-readiness.md"
    base = {
        "product": "KQUANT US Stock Signal Terminal",
        "source": "local_readiness_audit",
        "report_path": str(report),
        "markdown_path": str(markdown),
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "fixture_user_visible": False,
        "latest_cache_status": "not_scanned",
        "available": False,
    }
    if not report.exists():
        return {
            **base,
            "run_id": "monday-readiness-not-scanned",
            "status": "not_scanned",
            "summary": "No Monday pilot readiness report is available. Run KQUANT_VERIFY.cmd before trusting real-money pilot status.",
            "generated_at_utc": None,
            "critical_failure_count": 0,
            "warning_count": 1,
            "critical_failures": [],
            "warnings": ["Monday pilot readiness has not been verified in this workspace."],
            "checks": [],
            "pilot_rules": {
                "stocks_only": True,
                "max_account_risk_per_trade_pct": 0.25,
                "first_day_max_trades": "1-2",
                "total_first_day_risk_pct": 0.5,
                "journal_before_entry": True,
                "no_trade_during_data_caution": True,
            },
        }
    try:
        payload = json.loads(report.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "run_id": "monday-readiness-read-error",
            "status": "read_error",
            "summary": "Monday pilot readiness report exists but could not be read.",
            "generated_at_utc": None,
            "critical_failure_count": 1,
            "warning_count": 0,
            "critical_failures": [str(exc)],
            "warnings": [],
            "checks": [],
            "pilot_rules": {},
            "latest_cache_status": "read_error",
        }
    if not isinstance(payload, dict):
        return {
            **base,
            "run_id": "monday-readiness-invalid",
            "status": "read_error",
            "summary": "Monday pilot readiness report has an invalid format.",
            "generated_at_utc": None,
            "critical_failure_count": 1,
            "warning_count": 0,
            "critical_failures": ["Readiness report JSON root is not an object."],
            "warnings": [],
            "checks": [],
            "pilot_rules": {},
            "latest_cache_status": "read_error",
        }
    return {
        **base,
        **payload,
        "latest_cache_status": "available",
        "available": True,
        "report_path": str(report),
        "markdown_path": str(markdown),
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "fixture_user_visible": False,
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
        "cache_source": LONG_BRIDGE_STALE_SOURCE
        if any(
            signal.get("data_status", {}).get("source") == LONG_BRIDGE_STALE_SOURCE
            for signal in signals
        )
        else "stale_yahoo_chart_cache"
        if stale_signals
        else LONG_BRIDGE_CANDLE_SOURCE
        if source == "live" and preferred_market_data_provider() == "longbridge" and not provider_errors
        else "live_yahoo_chart"
        if source == "live" and not provider_errors
        else "none",
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


def api_stock_ai_decision(payload: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    """AI-led stock decision with deterministic guardrail vetoes.

    The model is allowed to lead ranking and trade planning, but the hard veto
    layer prevents it from turning bad data or blocked rule states into a buy.
    """

    db = db_path or default_db_path()
    symbol = normalize_symbol(payload.get("symbol") or payload.get("signal_payload", {}).get("symbol") or "NVDA")
    profile = str(payload.get("profile") or payload.get("signal_payload", {}).get("profile_name") or "tactical_1w_v1")
    signal_payload = payload.get("signal_payload")
    if not isinstance(signal_payload, dict) or not signal_payload:
        signal_payload = api_stock_analyze(symbol=symbol, source="live", profile=profile, db_path=db)["signal"]
    profile_comparison = payload.get("profile_comparison") if isinstance(payload.get("profile_comparison"), list) else []
    if not profile_comparison:
        profile_comparison = [
            api_stock_analyze(symbol=symbol, source="live", profile=profile_key, db_path=db)["signal"]
            for profile_key in visible_strategy_profile_keys()
        ]
    journal_limit = int(payload.get("journal_context_limit") or 5)
    journal = api_stock_signal_journal(db_path=db, symbol=symbol, limit=max(1, min(journal_limit, 20)))
    market_regime = api_stock_market_regime(source="live", db_path=db)
    research_context = payload.get("research_context") if isinstance(payload.get("research_context"), dict) else {}
    model = ai_review_model(payload)
    context = ai_decision_context(symbol, profile, signal_payload, profile_comparison, journal, market_regime, research_context)
    veto = ai_hard_veto(signal_payload, market_regime)
    safety = ai_agent_safety_policy(veto)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        decision = unavailable_ai_decision(signal_payload, veto, "OPENAI_API_KEY is not configured.")
        return {
            "product": "KQUANT AI Trading Agent",
            "status": "ai_unavailable",
            "reason": "OPENAI_API_KEY is not configured.",
            "model_name": model,
            "generated_at": iso_now(),
            "input_summary": context["input_summary"],
            "rule_conclusion": signal_payload.get("trade_conclusion", {}),
            "ai_decision": decision,
            "ai_feature_packet": signal_payload.get("ai_feature_packet_v2", {}),
            "ai_feature_packet_version": "ai_feature_packet_v2",
            "entry_plan": decision.get("entry_plan", signal_payload.get("entry_plan", {})),
            "stop_plan": decision.get("stop_plan", signal_payload.get("stop_plan", {})),
            "target_plan": decision.get("target_plan", signal_payload.get("target_plan", {})),
            "risk_reward_plan": decision.get("risk_reward_plan", signal_payload.get("risk_reward_plan", {})),
            "ai_action_validation": decision.get("ai_action_validation", signal_payload.get("ai_action_validation", {})),
            "money_pilot_eligibility": decision.get("money_pilot_eligibility", signal_payload.get("money_pilot_eligibility", {})),
            "probe_eligibility": decision.get("probe_eligibility", signal_payload.get("probe_eligibility", {})),
            "probe_risk_policy": decision.get("probe_risk_policy", signal_payload.get("probe_risk_policy", probe_risk_policy())),
            "probe_blockers": decision.get("probe_blockers", signal_payload.get("probe_blockers", [])),
            "hard_veto": veto,
            "safety_policy": safety,
        }
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=openai_decision_request(model, context),
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
        text = extract_openai_text(raw)
        decision = sanitize_ai_decision(json.loads(text), signal_payload, veto)
        status = "available"
        reason = "ok"
    except Exception as exc:
        decision = unavailable_ai_decision(signal_payload, veto, f"AI decision request failed: {type(exc).__name__}")
        status = "ai_unavailable"
        reason = str(exc)[:240]
    return {
        "product": "KQUANT AI Trading Agent",
        "status": status,
        "reason": reason,
        "model_name": model,
        "generated_at": iso_now(),
        "input_summary": context["input_summary"],
        "rule_conclusion": signal_payload.get("trade_conclusion", {}),
        "ai_decision": decision,
        "ai_feature_packet": signal_payload.get("ai_feature_packet_v2", {}),
        "ai_feature_packet_version": "ai_feature_packet_v2",
        "entry_plan": decision.get("entry_plan", signal_payload.get("entry_plan", {})),
        "stop_plan": decision.get("stop_plan", signal_payload.get("stop_plan", {})),
        "target_plan": decision.get("target_plan", signal_payload.get("target_plan", {})),
        "risk_reward_plan": decision.get("risk_reward_plan", signal_payload.get("risk_reward_plan", {})),
        "ai_action_validation": decision.get("ai_action_validation", signal_payload.get("ai_action_validation", {})),
        "money_pilot_eligibility": decision.get("money_pilot_eligibility", signal_payload.get("money_pilot_eligibility", {})),
        "probe_eligibility": decision.get("probe_eligibility", signal_payload.get("probe_eligibility", {})),
        "probe_risk_policy": decision.get("probe_risk_policy", signal_payload.get("probe_risk_policy", probe_risk_policy())),
        "probe_blockers": decision.get("probe_blockers", signal_payload.get("probe_blockers", [])),
        "hard_veto": veto,
        "safety_policy": safety,
    }


def api_stock_research_chat(payload: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    """Deep research chat for a single stock.

    This endpoint is intentionally read-only. It gives the strongest configured
    research model the current stock context, but it cannot change rule scores,
    trigger scans, access accounts, or submit orders.
    """

    db = db_path or default_db_path()
    symbol = normalize_symbol(payload.get("symbol") or payload.get("signal_payload", {}).get("symbol") or "NVDA")
    profile = str(payload.get("profile") or payload.get("signal_payload", {}).get("profile_name") or "tactical_1w_v1")
    question = str(payload.get("question") or "").strip()
    if not question:
        raise ValueError("Research chat question is required.")
    signal_payload = payload.get("signal_payload")
    if not isinstance(signal_payload, dict) or not signal_payload:
        signal_payload = api_stock_analyze(symbol=symbol, source="live", profile=profile, db_path=db)["signal"]
    ai_decision = payload.get("ai_decision") if isinstance(payload.get("ai_decision"), dict) else {}
    research_context = payload.get("research_context") if isinstance(payload.get("research_context"), dict) else {}
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    language = str(payload.get("language") or "zh").lower()
    primary_model = ai_research_chat_model(payload)
    fallback_model = (
        os.environ.get("KQUANT_AI_RESEARCH_FALLBACK_MODEL", "").strip()
        or os.environ.get("KQUANT_AI_DEEP_MODEL", "").strip()
        or os.environ.get("KQUANT_AI_REVIEW_MODEL", "").strip()
    )
    model_candidates = [primary_model]
    if fallback_model and fallback_model not in model_candidates:
        model_candidates.append(fallback_model)
    context = research_chat_context(
        symbol=symbol,
        profile=profile,
        question=question,
        signal=signal_payload,
        ai_decision=ai_decision,
        research_context=research_context,
        messages=messages,
        language=language,
    )
    safety = {
        "read_only_research": True,
        "ai_research_chat_enabled": True,
        "ai_can_place_orders": False,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "does_not_change_rule_score": True,
        "does_not_trigger_scans": True,
    }
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "product": "KQUANT Deep Research Chat",
            "status": "ai_unavailable",
            "reason": "OPENAI_API_KEY is not configured.",
            "model_name": primary_model,
            "primary_model_name": primary_model,
            "fallback_model_used": False,
            "fallback_reason": "",
            "generated_at": iso_now(),
            "symbol": symbol,
            "profile": profile,
            "question": question,
            "answer": unavailable_research_chat_answer(question),
            "safety_policy": safety,
        }
    answer: dict[str, Any] | None = None
    status = "ai_unavailable"
    reason = "No model request was attempted."
    model_name = primary_model
    fallback_used = False
    fallback_reason = ""
    last_error = ""
    for index, candidate_model in enumerate(model_candidates):
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=openai_research_chat_request(candidate_model, context),
                timeout=120,
            )
            response.raise_for_status()
            raw = response.json()
            text = extract_openai_text(raw)
            answer = sanitize_research_chat_answer(json.loads(text))
            status = "available"
            model_name = candidate_model
            fallback_used = index > 0
            if fallback_used:
                fallback_reason = last_error
                reason = f"fallback_model_used_after_primary_failed: {last_error[:180]}"
            else:
                reason = "ok"
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue
    if answer is None:
        answer = unavailable_research_chat_answer(f"{question}\n\nAI request failed: {last_error}")
        reason = last_error or reason
    return {
        "product": "KQUANT Deep Research Chat",
        "status": status,
        "reason": reason,
        "model_name": model_name,
        "primary_model_name": primary_model,
        "fallback_model_used": fallback_used,
        "fallback_reason": fallback_reason,
        "generated_at": iso_now(),
        "symbol": symbol,
        "profile": profile,
        "question": question,
        "answer": answer,
        "input_summary": context["input_summary"],
        "safety_policy": safety,
    }


def api_stock_ai_daily_agent(
    payload: dict[str, Any] | None = None,
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the daily AI opportunity workflow.

    It scans a bounded candidate set, lets AI rank/plan the opportunities, then
    applies the same hard veto policy. Auto-trigger requests respect a local
    cooldown so opening the dashboard does not repeatedly hit Yahoo/OpenAI.
    """

    payload = payload or {}
    db = db_path or default_db_path()
    outputs = outputs_dir or Path("outputs")
    trigger = str(payload.get("trigger") or "manual").lower()
    cooldown_seconds = max(0, min(int(payload.get("cooldown_seconds") or 1800), 86400))
    if trigger == "auto":
        latest = api_stock_ai_daily_report_latest(outputs_dir=outputs)
        age_seconds = latest.get("age_seconds")
        if (
            latest.get("status") not in ("not_scanned", "report_unreadable")
            and isinstance(age_seconds, int)
            and age_seconds < cooldown_seconds
        ):
            return {
                **latest,
                "auto_run_skipped": True,
                "auto_run_skip_reason": f"cooldown_active_{cooldown_seconds}s",
                "trigger": trigger,
                "cooldown_seconds": cooldown_seconds,
            }
    universe = str(payload.get("universe") or "all")
    source = "live"
    scan_limit = max(5, min(int(payload.get("limit") or 40), 80))
    top_n = max(3, min(int(payload.get("top_n") or 8), 12))
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = visible_strategy_profile_keys()
    profiles = [str(profile) for profile in profiles if str(profile) in PROFILE_CONFIGS][:5]
    market_regime = api_stock_market_regime(source=source, db_path=db)
    candidate_map: dict[str, dict[str, Any]] = {}
    provider_errors: list[str] = []
    for profile in profiles:
        try:
            run = api_stock_signals(
                source=source,
                universe=universe,
                profile=profile,
                db_path=db,
                outputs_dir=outputs,
                limit=scan_limit,
            )
        except Exception as exc:
            provider_errors.append(f"{profile}: {type(exc).__name__}")
            continue
        provider_errors.extend(run.get("provider_errors", [])[:5])
        for signal in run.get("signals", []):
            if not isinstance(signal, dict):
                continue
            existing = candidate_map.get(signal["symbol"])
            if existing is None or ai_candidate_sort_key(signal) > ai_candidate_sort_key(existing):
                candidate_map[signal["symbol"]] = signal
    candidates = sorted(candidate_map.values(), key=ai_candidate_sort_key, reverse=True)[:top_n]
    candidate_context = [ai_daily_candidate_summary(signal, market_regime) for signal in candidates]
    model = ai_review_model({"model_tier": payload.get("model_tier") or "batch", "model": payload.get("model") or ""})
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    run_id = f"ai-daily-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    if not api_key:
        ai_report = unavailable_daily_ai_report(candidate_context, "OPENAI_API_KEY is not configured.")
        status = "ai_unavailable"
        reason = "OPENAI_API_KEY is not configured."
    else:
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=openai_daily_agent_request(model, {
                    "run_id": run_id,
                    "universe": universe,
                    "profiles": profiles,
                    "market_regime": market_regime,
                    "candidates": candidate_context,
                    "provider_errors": provider_errors[:20],
                }),
                timeout=90,
            )
            response.raise_for_status()
            raw = response.json()
            text = extract_openai_text(raw)
            ai_report = sanitize_daily_ai_report(json.loads(text), candidates, market_regime)
            status = "available"
            reason = "ok"
        except Exception as exc:
            ai_report = unavailable_daily_ai_report(candidate_context, f"AI daily agent failed: {type(exc).__name__}")
            status = "ai_unavailable"
            reason = str(exc)[:240]
    payload_out = {
        "product": "KQUANT AI Daily Opportunity Agent",
        "run_id": run_id,
        "status": status,
        "reason": reason,
        "trigger": trigger,
        "cooldown_seconds": cooldown_seconds,
        "model_name": model,
        "generated_at": iso_now(),
        "market_date": ai_market_date(),
        "is_stale": False,
        "age_seconds": 0,
        "auto_run_recommended": False,
        "last_error": None if status == "available" else reason,
        "source": source,
        "universe": universe,
        "profiles": profiles,
        "scanned_candidate_count": len(candidate_map),
        "ai_context_candidate_count": len(candidate_context),
        "provider_errors": provider_errors[:30],
        "market_regime": market_regime,
        "ai_report": ai_report,
        "validation_by_ai_action": ai_report.get("validation_by_ai_action", {}),
        "hard_veto_policy": "AI may lead ranking and planning, but cannot override bad data, stale provider state, broker/order restrictions, or rule vetoes.",
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
    }
    write_ai_daily_report(outputs, payload_out)
    return payload_out


def api_stock_ai_daily_report_latest(outputs_dir: Path | None = None) -> dict[str, Any]:
    outputs = outputs_dir or Path("outputs")
    report = outputs / "ai-daily-opportunities.json"
    if not report.exists():
        return {
            "product": "KQUANT AI Daily Opportunity Agent",
            "status": "not_scanned",
            "reason": "No AI daily opportunity report yet. The dashboard may auto-run when AI is available.",
            "market_date": ai_market_date(),
            "is_stale": True,
            "age_seconds": None,
            "auto_run_recommended": True,
            "last_error": "not_scanned",
            "read_only_research": True,
            "broker_order_wiring_enabled": False,
        }
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        return enrich_ai_daily_report_freshness(payload)
    except json.JSONDecodeError:
        return {
            "product": "KQUANT AI Daily Opportunity Agent",
            "status": "report_unreadable",
            "reason": "Latest AI daily report is not valid JSON.",
            "market_date": ai_market_date(),
            "is_stale": True,
            "age_seconds": None,
            "auto_run_recommended": True,
            "last_error": "report_unreadable",
            "read_only_research": True,
            "broker_order_wiring_enabled": False,
        }


def ai_market_date(now: datetime | None = None) -> str:
    """Return a simple US-market date for the local daily agent.

    The app only needs a stable day key for freshness. Using Eastern time keeps
    reports generated after China midnight attached to the US trading session.
    """

    eastern = timezone(timedelta(hours=-4))
    return (now or datetime.now(UTC)).astimezone(eastern).date().isoformat()


def enrich_ai_daily_report_freshness(payload: dict[str, Any], max_age_seconds: int = 21600) -> dict[str, Any]:
    generated_at = str(payload.get("generated_at") or "")
    age_seconds: int | None = None
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        age_seconds = max(0, int((datetime.now(UTC) - generated.astimezone(UTC)).total_seconds()))
    except ValueError:
        age_seconds = None
    market_date = str(payload.get("market_date") or ai_market_date())
    today = ai_market_date()
    is_stale = market_date != today or age_seconds is None or age_seconds > max_age_seconds
    status = str(payload.get("status") or "unknown")
    last_error = payload.get("last_error") or (payload.get("reason") if status not in ("available", "not_scanned") else None)
    return {
        **payload,
        "market_date": market_date,
        "is_stale": is_stale,
        "age_seconds": age_seconds,
        "auto_run_recommended": is_stale,
        "last_error": last_error,
    }


def api_stock_ai_review_status() -> dict[str, Any]:
    review_model = os.environ.get("KQUANT_AI_REVIEW_MODEL", "gpt-5.4").strip() or "gpt-5.4"
    batch_model = os.environ.get("KQUANT_AI_BATCH_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini"
    deep_model = os.environ.get("KQUANT_AI_DEEP_MODEL", "gpt-5.5").strip() or "gpt-5.5"
    research_model = os.environ.get("KQUANT_AI_RESEARCH_MODEL", "").strip() or "gpt-5.5-pro"
    has_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    return {
        "product": "KQUANT AI Trading Agent",
        "status": "available" if has_key else "missing_key",
        "reason": "OPENAI_API_KEY is configured." if has_key else "OPENAI_API_KEY is not configured on the backend.",
        "setup_hint": "Set OPENAI_API_KEY in the local backend environment and restart KQUANT. Never put this key in web/, GitHub, or Vercel frontend variables.",
        "models": {
            "review": review_model,
            "batch": batch_model,
            "deep": deep_model,
            "research": research_model,
        },
        "manual_trigger_only": False,
        "daily_agent_auto_check_enabled": has_key,
        "read_only_research": True,
        "llm_signal_core_enabled": True,
        "ai_review_only": False,
        "ai_decision_engine_enabled": has_key,
        "daily_opportunity_agent_enabled": has_key,
        "deep_research_chat_enabled": has_key,
        "hard_rule_veto_enabled": True,
        "ai_can_lead_decisions": has_key,
        "ai_can_place_orders": False,
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
            "entered_manually_count": counts.get("entered-manually", 0),
            "exited_manually_count": counts.get("exited-manually", 0),
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
    if status in MANUAL_ENTRY_JOURNAL_STATUSES and (
        planned_entry is None or planned_stop is None or planned_target is None
    ):
        raise ValueError("Manual trade journal entries require planned entry, stop, and target.")
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
    ema8 = ema_last(daily_close, 8)
    ema9 = ema_last(daily_close, 9)
    ema20 = ema_last(daily_close, 20)
    ema50 = ema_last(daily_close, 50)
    ema200 = ema_last(daily_close, 200)
    h_ema8 = ema_last(hourly_close, 8)
    h_ema9 = ema_last(hourly_close, 9)
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
        "ema8": round(ema8, 2),
        "ema9": round(ema9, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "hourly_close": round(hourly_close[-1], 2),
        "hourly_ema8": round(h_ema8, 2),
        "hourly_ema9": round(h_ema9, 2),
        "hourly_ema20": round(h_ema20, 2),
        "hourly_ema50": round(h_ema50, 2),
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
    high_beta_growth = bool(active_profile.get("high_beta_growth"))
    trend_aligned = close > ema20 > ema50 > ema200
    trigger_confirmed = hourly_close[-1] > h_ema20 > h_ema50 and one_hour_momentum >= float(active_profile.get("confirmation_momentum_min", 0.6))
    volume_confirmed = volume_ratio >= float(active_profile.get("volume_ratio_min", 1.2))
    risk_window_ok = -2.5 <= extension_pct <= float(active_profile.get("max_extension_pct", 5.5)) and atr_pct <= float(active_profile.get("max_atr_pct", 5.0))
    if high_beta_growth:
        ema50_floor = float(active_profile.get("pullback_ema50_floor", 0.97))
        trend_aligned = close >= ema50 * ema50_floor and close > ema200
        trigger_confirmed = one_hour_momentum >= float(active_profile.get("confirmation_momentum_min", 0.8)) and hourly_close[-1] > h_ema20
        risk_window_ok = close >= ema50 * ema50_floor and extension_pct <= float(active_profile.get("max_extension_pct", 12.0)) and atr_pct <= float(active_profile.get("max_atr_pct", 12.0))
    daily_status = daily_payload["provider_status"]
    hourly_status = hourly_payload["provider_status"]
    daily_source = str(daily_payload.get("source_type", ""))
    hourly_source = str(hourly_payload.get("source_type", ""))
    longbridge_required = preferred_market_data_provider() == "longbridge"
    realtime_source_clean = (
        not longbridge_required
        or (daily_source == LONG_BRIDGE_CANDLE_SOURCE and hourly_source == LONG_BRIDGE_CANDLE_SOURCE)
    )
    data_clean = daily_status == "available" and hourly_status == "available" and realtime_source_clean
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
    if high_beta_growth:
        watch_gates = score >= float(active_profile["watch_threshold"]) and close > ema200 and one_hour_momentum > -2.0 and has_real_or_internal_data
    else:
        watch_gates = score >= float(active_profile["watch_threshold"]) and close > ema50 and one_hour_momentum > -1.5 and has_real_or_internal_data
    level = "BUY SETUP" if score >= float(active_profile["strict_buy_gate_score"]) and buy_gates else "WATCH" if watch_gates else "PASS"
    risks = []
    if atr_pct > float(active_profile.get("max_atr_pct", 5.0)):
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
        profile=active_profile,
    )
    ai_feature_packet = build_ai_feature_packet_v1(
        symbol=symbol,
        active_profile=active_profile,
        daily_payload=daily_payload,
        hourly_payload=hourly_payload,
        daily=daily,
        hourly=hourly,
        close=close,
        ema8=ema8,
        ema9=ema9,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        h_ema8=h_ema8,
        h_ema9=h_ema9,
        h_ema20=h_ema20,
        h_ema50=h_ema50,
        trend_return=trend_return,
        one_hour_momentum=one_hour_momentum,
        volume_ratio=volume_ratio,
        atr_pct=atr_pct,
        extension_pct=extension_pct,
        score_breakdown=score_breakdown,
        historical_edge=historical_edge,
        trend_aligned=trend_aligned,
        trigger_confirmed=trigger_confirmed,
        volume_confirmed=volume_confirmed,
        risk_window_ok=risk_window_ok,
        edge_ok=edge_ok,
        data_clean=data_clean,
        level=level,
        exit_risk=exit_risk,
    )
    ai_feature_packet_v2 = build_ai_feature_packet_v2(
        symbol=symbol,
        active_profile=active_profile,
        daily_payload=daily_payload,
        hourly_payload=hourly_payload,
        daily=daily,
        hourly=hourly,
        close=close,
        ema8=ema8,
        ema9=ema9,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        h_ema8=h_ema8,
        h_ema9=h_ema9,
        h_ema20=h_ema20,
        h_ema50=h_ema50,
        trend_return=trend_return,
        one_hour_momentum=one_hour_momentum,
        volume_ratio=volume_ratio,
        atr_pct=atr_pct,
        extension_pct=extension_pct,
        score_breakdown=score_breakdown,
        historical_edge=historical_edge,
        trend_aligned=trend_aligned,
        trigger_confirmed=trigger_confirmed,
        volume_confirmed=volume_confirmed,
        risk_window_ok=risk_window_ok,
        edge_ok=edge_ok,
        data_clean=data_clean,
        level=level,
        exit_risk=exit_risk,
    )
    rule_plans = build_rule_trade_plans(
        active_profile=active_profile,
        close=close,
        ema8=ema8,
        ema9=ema9,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        h_ema20=h_ema20,
        h_ema50=h_ema50,
        atr_pct=atr_pct,
        extension_pct=extension_pct,
        one_hour_momentum=one_hour_momentum,
        exit_risk=exit_risk,
        data_clean=data_clean,
    )
    ai_action_validation = build_ai_action_validation(
        "PENDING_AI_DECISION",
        historical_edge,
        active_profile,
        rule_plans["risk_reward_plan"],
    )
    data_status = {
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
        "daily_source_type": daily_source,
        "confirmation_source_type": hourly_source,
        "freshness": daily_payload["freshness"],
        "longbridge_required_for_buy": longbridge_required,
        "longbridge_live_data_clean": bool(
            daily_status == "available"
            and hourly_status == "available"
            and daily_source == LONG_BRIDGE_CANDLE_SOURCE
            and hourly_source == LONG_BRIDGE_CANDLE_SOURCE
        ),
        "data_quality": "clean" if data_clean else "caution",
        "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
    }
    money_pilot_eligibility = build_money_pilot_eligibility(
        action="PENDING_AI_DECISION",
        signal={
            "data_status": data_status,
            "entry_plan": rule_plans["entry_plan"],
            "stop_plan": rule_plans["stop_plan"],
            "target_plan": rule_plans["target_plan"],
            "risk_reward_plan": rule_plans["risk_reward_plan"],
            "historical_edge": historical_edge,
        },
        risk_reward_plan=rule_plans["risk_reward_plan"],
        historical_edge=historical_edge,
        hard_veto_active=not data_clean,
    )
    probe_eligibility = build_probe_eligibility(
        action="PENDING_AI_DECISION",
        signal={
            "data_status": data_status,
            "entry_plan": rule_plans["entry_plan"],
            "stop_plan": rule_plans["stop_plan"],
            "target_plan": rule_plans["target_plan"],
            "risk_reward_plan": rule_plans["risk_reward_plan"],
            "historical_edge": historical_edge,
        },
        risk_reward_plan=rule_plans["risk_reward_plan"],
        historical_edge=historical_edge,
        hard_veto_active=not data_clean,
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
        "data_status": data_status,
        "features": features,
        "ai_feature_packet_v1": ai_feature_packet,
        "ai_feature_packet_v2": ai_feature_packet_v2,
        "entry_plan": rule_plans["entry_plan"],
        "stop_plan": rule_plans["stop_plan"],
        "target_plan": rule_plans["target_plan"],
        "risk_reward_plan": rule_plans["risk_reward_plan"],
        "money_pilot_eligibility": money_pilot_eligibility,
        "probe_eligibility": probe_eligibility,
        "probe_risk_policy": probe_risk_policy(),
        "probe_blockers": probe_eligibility["blockers"],
        "ai_action_evidence": ai_feature_packet_v2["evidence_stack"],
        "ai_action_validation": ai_action_validation,
        "historical_edge": historical_edge,
        "_label_samples": label_samples,
    }


def build_ai_feature_packet_v1(
    *,
    symbol: str,
    active_profile: dict[str, Any],
    daily_payload: dict[str, Any],
    hourly_payload: dict[str, Any],
    daily: list[dict[str, Any]],
    hourly: list[dict[str, Any]],
    close: float,
    ema8: float,
    ema9: float,
    ema20: float,
    ema50: float,
    ema200: float,
    h_ema8: float,
    h_ema9: float,
    h_ema20: float,
    h_ema50: float,
    trend_return: float,
    one_hour_momentum: float,
    volume_ratio: float,
    atr_pct: float,
    extension_pct: float,
    score_breakdown: dict[str, Any],
    historical_edge: dict[str, Any],
    trend_aligned: bool,
    trigger_confirmed: bool,
    volume_confirmed: bool,
    risk_window_ok: bool,
    edge_ok: bool,
    data_clean: bool,
    level: str,
    exit_risk: dict[str, Any],
) -> dict[str, Any]:
    hourly_close = float(hourly[-1]["close"]) if hourly else 0.0
    return {
        "version": "ai_feature_packet_v1",
        "symbol": symbol,
        "profile_name": active_profile["name"],
        "strategy_label": active_profile["label"],
        "holding_period": active_profile["holding_period"],
        "timeframes": {
            "primary": active_profile["primary_timeframe"],
            "confirmation": active_profile["confirmation_timeframe"],
        },
        "price_structure": {
            "close": round(close, 2),
            "ema8": round(ema8, 2),
            "ema9": round(ema9, 2),
            "ema20": round(ema20, 2),
            "ema50": round(ema50, 2),
            "ema200": round(ema200, 2),
            "close_vs_ema8_pct": round(pct(close, ema8), 2),
            "close_vs_ema9_pct": round(pct(close, ema9), 2),
            "close_vs_ema20_pct": round(extension_pct, 2),
            "close_vs_ema50_pct": round(pct(close, ema50), 2),
            "close_vs_ema200_pct": round(pct(close, ema200), 2),
            "trend_return_5d_pct": round(trend_return, 2),
        },
        "confirmation_structure": {
            "close": round(hourly_close, 2),
            "ema8": round(h_ema8, 2),
            "ema9": round(h_ema9, 2),
            "ema20": round(h_ema20, 2),
            "ema50": round(h_ema50, 2),
            "momentum_pct": round(one_hour_momentum, 2),
            "close_above_ema8": hourly_close > h_ema8,
            "close_above_ema9": hourly_close > h_ema9,
            "close_above_ema20": hourly_close > h_ema20,
            "close_above_ema50": hourly_close > h_ema50,
        },
        "volume_volatility": {
            "volume_ratio": round(volume_ratio, 2),
            "atr_pct": round(atr_pct, 2),
        },
        "score_breakdown": score_breakdown,
        "historical_edge": {
            "focus_window": historical_edge.get("focus_window"),
            "focus_win_rate": historical_edge.get("focus_win_rate"),
            "focus_avg_return": historical_edge.get("focus_avg_return"),
            "focus_sample_count": historical_edge.get("focus_sample_count"),
            "sample_count": historical_edge.get("sample_count"),
        },
        "data_quality": {
            "daily_provider_status": daily_payload.get("provider_status"),
            "confirmation_provider_status": hourly_payload.get("provider_status"),
            "daily_candles": len(daily),
            "confirmation_candles": len(hourly),
            "source": daily_payload.get("source_type"),
            "freshness": daily_payload.get("freshness"),
            "clean": data_clean,
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "rule_state": {
            "level": level,
            "trend_aligned": bool(trend_aligned),
            "trigger_confirmed": bool(trigger_confirmed),
            "volume_confirmed": bool(volume_confirmed),
            "risk_window_ok": bool(risk_window_ok),
            "historical_edge_ok": bool(edge_ok),
            "exit_risk": exit_risk.get("status"),
        },
        "ai_policy": {
            "ai_may_lead_ranking_and_plan": True,
            "hard_veto_remains_active": True,
            "cannot_override_provider_failed_or_stale_data": True,
            "cannot_trigger_broker_or_order": True,
        },
    }


def build_ai_feature_packet_v2(
    *,
    symbol: str,
    active_profile: dict[str, Any],
    daily_payload: dict[str, Any],
    hourly_payload: dict[str, Any],
    daily: list[dict[str, Any]],
    hourly: list[dict[str, Any]],
    close: float,
    ema8: float,
    ema9: float,
    ema20: float,
    ema50: float,
    ema200: float,
    h_ema8: float,
    h_ema9: float,
    h_ema20: float,
    h_ema50: float,
    trend_return: float,
    one_hour_momentum: float,
    volume_ratio: float,
    atr_pct: float,
    extension_pct: float,
    score_breakdown: dict[str, Any],
    historical_edge: dict[str, Any],
    trend_aligned: bool,
    trigger_confirmed: bool,
    volume_confirmed: bool,
    risk_window_ok: bool,
    edge_ok: bool,
    data_clean: bool,
    level: str,
    exit_risk: dict[str, Any],
) -> dict[str, Any]:
    daily_close = [float(bar["close"]) for bar in daily]
    hourly_close_values = [float(bar["close"]) for bar in hourly]
    hourly_close = hourly_close_values[-1] if hourly_close_values else 0.0
    daily_vwap20 = vwap_last(daily[-20:])
    hourly_vwap20 = vwap_last(hourly[-20:])
    pullback_reclaim = (
        close >= ema50 * float(active_profile.get("pullback_ema50_floor", 0.98))
        and close <= ema20 * 1.06
        and hourly_close > h_ema20
        and one_hour_momentum > 0
    )
    early_momentum_reclaim = close > ema8 and close > ema9 and hourly_close > h_ema8 and hourly_close > h_ema9
    no_chase_required = extension_pct > float(active_profile.get("max_extension_pct", 5.5)) * 0.7
    evidence_stack = [
        f"1D close vs EMA8/9/20/50/200: {pct(close, ema8):.2f}% / {pct(close, ema9):.2f}% / {extension_pct:.2f}% / {pct(close, ema50):.2f}% / {pct(close, ema200):.2f}%",
        f"1H momentum {one_hour_momentum:.2f}% with close {'above' if hourly_close > h_ema20 else 'below'} EMA20.",
        f"Volume ratio {volume_ratio:.2f}x and ATR {atr_pct:.2f}%.",
        f"Historical {historical_edge.get('focus_window')}: win {historical_edge.get('focus_win_rate')}%, avg {historical_edge.get('focus_avg_return')}%, samples {historical_edge.get('focus_sample_count')}.",
        f"Rule level {level}; exit risk {exit_risk.get('status')}.",
    ]
    return {
        "version": "ai_feature_packet_v2",
        "symbol": symbol,
        "profile": {
            "name": active_profile["name"],
            "label": active_profile["label"],
            "holding_period": active_profile["holding_period"],
            "primary_timeframe": active_profile["primary_timeframe"],
            "confirmation_timeframe": active_profile["confirmation_timeframe"],
            "is_high_beta_growth": bool(active_profile.get("high_beta_growth")),
        },
        "timeframe_summaries": {
            "daily": candle_window_summary(daily, "1D"),
            "confirmation": candle_window_summary(hourly, active_profile["confirmation_timeframe"]),
        },
        "technical_state": {
            "daily": {
                "close": round(close, 2),
                "ema8": round(ema8, 2),
                "ema9": round(ema9, 2),
                "ema20": round(ema20, 2),
                "ema50": round(ema50, 2),
                "ema200": round(ema200, 2),
                "vwap20": round(daily_vwap20, 2),
                "rsi14": round(rsi_last(daily_close, 14), 1),
                "atr14_pct": round(average_true_range_pct(daily[-14:]), 2),
                "volume_ratio_20d": round(volume_ratio, 2),
                "close_vs_ema8_pct": round(pct(close, ema8), 2),
                "close_vs_ema9_pct": round(pct(close, ema9), 2),
                "close_vs_ema20_pct": round(extension_pct, 2),
                "close_vs_ema50_pct": round(pct(close, ema50), 2),
                "close_vs_ema200_pct": round(pct(close, ema200), 2),
                "trend_return_5d_pct": round(trend_return, 2),
            },
            "confirmation": {
                "close": round(hourly_close, 2),
                "ema8": round(h_ema8, 2),
                "ema9": round(h_ema9, 2),
                "ema20": round(h_ema20, 2),
                "ema50": round(h_ema50, 2),
                "vwap20": round(hourly_vwap20, 2),
                "rsi14": round(rsi_last(hourly_close_values, 14), 1),
                "momentum_pct": round(one_hour_momentum, 2),
                "close_vs_vwap20_pct": round(pct(hourly_close, hourly_vwap20), 2),
            },
        },
        "setup_state": {
            "trend_aligned": bool(trend_aligned),
            "trigger_confirmed": bool(trigger_confirmed),
            "volume_confirmed": bool(volume_confirmed),
            "risk_window_ok": bool(risk_window_ok),
            "historical_edge_ok": bool(edge_ok),
            "pullback_reclaim": bool(pullback_reclaim),
            "early_momentum_reclaim": bool(early_momentum_reclaim),
            "no_chase_required": bool(no_chase_required),
        },
        "score_breakdown": score_breakdown,
        "historical_edge": {
            "focus_window": historical_edge.get("focus_window"),
            "focus_win_rate": historical_edge.get("focus_win_rate"),
            "focus_avg_return": historical_edge.get("focus_avg_return"),
            "focus_avg_max_drawdown": historical_edge.get("focus_avg_max_drawdown"),
            "focus_sample_count": historical_edge.get("focus_sample_count"),
            "profile_verdict": historical_edge.get("profile_verdict"),
        },
        "market_and_data_guardrails": {
            "data_clean": bool(data_clean),
            "daily_provider_status": daily_payload.get("provider_status"),
            "confirmation_provider_status": hourly_payload.get("provider_status"),
            "daily_source_type": daily_payload.get("source_type"),
            "confirmation_source_type": hourly_payload.get("source_type"),
            "daily_candles": len(daily),
            "confirmation_candles": len(hourly),
            "source": daily_payload.get("source_type"),
            "freshness": daily_payload.get("freshness"),
            "daily_quote_time": daily_payload.get("quote_time"),
            "daily_candle_time": daily_payload.get("candle_time"),
            "confirmation_candle_time": hourly_payload.get("candle_time"),
            "session": daily_payload.get("session"),
            "longbridge_required_for_buy": preferred_market_data_provider() == "longbridge",
            "longbridge_live_data_clean": bool(
                daily_payload.get("provider_status") == "available"
                and hourly_payload.get("provider_status") == "available"
                and daily_payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE
                and hourly_payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE
            ),
            "real_money_data_source": bool(
                daily_payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE
                and hourly_payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE
            ),
            "live_does_not_fallback_to_fixture": bool(daily_payload.get("live_does_not_fallback_to_fixture")),
        },
        "rule_guardrails": {
            "level": level,
            "exit_risk": exit_risk.get("status"),
            "exit_risk_reasons": list(exit_risk.get("reasons", []))[:5],
            "buy_requires_hard_veto_clear": True,
            "no_broker_or_order_path": True,
        },
        "evidence_stack": evidence_stack,
    }


def candle_window_summary(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    if not candles:
        return {
            "timeframe": timeframe,
            "candles": 0,
            "first_time": None,
            "last_time": None,
            "return_pct": 0.0,
            "range_pct": 0.0,
            "last_close": 0.0,
        }
    first = candles[0]
    last = candles[-1]
    highs = [float(bar["high"]) for bar in candles]
    lows = [float(bar["low"]) for bar in candles]
    first_close = float(first["close"])
    last_close = float(last["close"])
    return {
        "timeframe": timeframe,
        "candles": len(candles),
        "first_time": first.get("open_time"),
        "last_time": last.get("open_time"),
        "return_pct": round(pct(last_close, first_close), 2),
        "range_pct": round(pct(max(highs), min(lows)), 2) if lows else 0.0,
        "last_close": round(last_close, 2),
    }


def vwap_last(candles: list[dict[str, Any]]) -> float:
    numerator = 0.0
    denominator = 0.0
    for candle in candles:
        volume = float(candle.get("volume") or 0)
        typical = (float(candle["high"]) + float(candle["low"]) + float(candle["close"])) / 3
        numerator += typical * volume
        denominator += volume
    if denominator <= 0:
        return float(candles[-1]["close"]) if candles else 0.0
    return numerator / denominator


def rsi_last(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for current, previous in zip(values[-period:], values[-period - 1 : -1]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def build_rule_trade_plans(
    *,
    active_profile: dict[str, Any],
    close: float,
    ema8: float,
    ema9: float,
    ema20: float,
    ema50: float,
    ema200: float,
    h_ema20: float,
    h_ema50: float,
    atr_pct: float,
    extension_pct: float,
    one_hour_momentum: float,
    exit_risk: dict[str, Any],
    data_clean: bool,
) -> dict[str, Any]:
    high_beta = bool(active_profile.get("high_beta_growth"))
    atr_decimal = max(atr_pct / 100, 0.01)
    if high_beta:
        entry_low = min(close, max(ema50 * 0.97, ema20 * 0.96))
        entry_high = max(close * 1.01, ema20 * 1.02)
        stop = min(entry_low * 0.96, ema50 * 0.96, close * (1 - min(max(atr_decimal, 0.06), 0.12)))
        target_one = entry_high + (entry_high - stop) * 2.0
        target_two = entry_high + (entry_high - stop) * 3.0
        size_hint = "High-beta only: staged entry, smaller than normal size, no averaging down."
    else:
        entry_low = min(close, ema20 * 0.99)
        entry_high = max(close * 1.005, ema20 * 1.015)
        stop = min(ema50 * 0.985, close * (1 - min(max(atr_decimal, 0.035), 0.07)))
        target_one = entry_high + (entry_high - stop) * 2.0
        target_two = entry_high + (entry_high - stop) * 2.6
        size_hint = "Standard risk only: size from stop distance; no order is sent by KQUANT."
    entry_mid = (entry_low + entry_high) / 2
    target_mid = (target_one + target_two) / 2
    risk = max(entry_mid - stop, 0.01)
    reward = max(target_mid - entry_mid, 0.0)
    rr = reward / risk if risk > 0 else 0.0
    data_note = "live data clean" if data_clean else "data caution; do not use for a fresh trade"
    invalidation = [
        f"Daily close loses planned stop near {stop:.2f}.",
        f"1H close loses EMA20/EMA50 area near {h_ema20:.2f}/{h_ema50:.2f}.",
        f"Exit risk changes to {exit_risk.get('status')} with expanding ATR or failed reclaim.",
        "Provider data becomes stale or failed.",
    ]
    no_chase = (
        "Wait for pullback/retest; current extension is high."
        if extension_pct > float(active_profile.get("max_extension_pct", 5.5)) * 0.7
        else "Entry should remain inside planned zone; no chase above zone."
    )
    return {
        "entry_plan": {
            "zone": f"{entry_low:.2f} - {entry_high:.2f}",
            "entry_low": round(entry_low, 2),
            "entry_high": round(entry_high, 2),
            "trigger": "1H momentum reclaim plus daily structure confirmation" if one_hour_momentum > 0 else "Wait for 1H momentum to turn positive before acting.",
            "no_chase_rule": no_chase,
            "data_note": data_note,
        },
        "stop_plan": {
            "zone": f"near {stop:.2f}",
            "stop": round(stop, 2),
            "basis": "EMA50/ATR structural stop for high-beta pullback" if high_beta else "EMA50/ATR structural stop for tactical swing",
            "invalidation": invalidation,
        },
        "target_plan": {
            "zone": f"{target_one:.2f} - {target_two:.2f}",
            "target_low": round(target_one, 2),
            "target_high": round(target_two, 2),
            "management": "Take partials or trail only after price confirms; no automatic execution.",
        },
        "risk_reward_plan": {
            "risk_reward": f"{rr:.1f}R",
            "risk_reward_value": round(rr, 2),
            "position_size_hint": size_hint,
            "minimum_for_money_pilot": 2.0,
            "eligible_for_manual_money_review": bool(data_clean and rr >= 2.0 and exit_risk.get("status") not in {"DATA CAUTION", "EXIT RISK", "SETUP INVALIDATED"}),
        },
    }


BUY_REVIEW_ACTIONS = {"AI_BUY_CANDIDATE", "AI_PULLBACK_BUY"}
PROBE_REVIEW_ACTIONS = {"AI_PROBE_BUY"}
AI_REVIEW_ACTIONS = BUY_REVIEW_ACTIONS | PROBE_REVIEW_ACTIONS
MONEY_PILOT_MIN_RR = 2.0
MONEY_PILOT_MIN_WIN_RATE = 50.0
MONEY_PILOT_MIN_SAMPLES = 30
PROBE_MIN_RR = 1.5
PROBE_MIN_WIN_RATE = 45.0
PROBE_MIN_SAMPLES = 20
PROBE_DEFAULT_RISK_PCT = 0.15
PROBE_MAX_RISK_PCT = 0.20


def clear_plan_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text not in {"unavailable", "not_available", "none", "nan", "-", "n/a"}


def build_money_pilot_eligibility(
    *,
    action: str,
    signal: dict[str, Any],
    risk_reward_plan: dict[str, Any] | None = None,
    historical_edge: dict[str, Any] | None = None,
    hard_veto_active: bool = False,
    journal_saved: bool = False,
) -> dict[str, Any]:
    """Deterministic gate for whether an AI action can enter manual money review.

    This gate intentionally stays stricter than the AI action itself. The AI may
    surface a watch or pullback idea, but real-money review needs positive
    historical evidence, clear R/R, clean live data, and a saved journal plan.
    """

    risk_plan = risk_reward_plan or signal.get("risk_reward_plan") or {}
    edge = historical_edge or signal.get("historical_edge") or {}
    data_status = signal.get("data_status") or {}
    entry_plan = signal.get("entry_plan") or {}
    stop_plan = signal.get("stop_plan") or {}
    target_plan = signal.get("target_plan") or {}
    rr_value = float(risk_plan.get("risk_reward_value") or 0)
    win_rate = float(edge.get("focus_win_rate", edge.get("win_rate_5d", 0)) or 0)
    sample_count = int(edge.get("focus_sample_count", edge.get("sample_count", 0)) or 0)
    daily_status = data_status.get("daily_provider_status")
    hourly_status = data_status.get("hourly_provider_status")
    live_data_ok = (
        data_status.get("data_quality") == "clean"
        and daily_status == "available"
        and hourly_status == "available"
        and int(data_status.get("daily_candles") or 0) > 0
        and int(data_status.get("hourly_candles") or 0) > 0
    )
    stop_clear = clear_plan_text(stop_plan.get("zone")) and clear_plan_text(stop_plan.get("stop"))
    target_clear = clear_plan_text(target_plan.get("zone")) and (
        clear_plan_text(target_plan.get("target_low")) or clear_plan_text(target_plan.get("target_high"))
    )
    entry_clear = clear_plan_text(entry_plan.get("zone")) and (
        clear_plan_text(entry_plan.get("entry_low")) or clear_plan_text(entry_plan.get("entry_high"))
    )
    invalidation_clear = bool(stop_plan.get("invalidation"))
    criteria = {
        "allowed_action": action in BUY_REVIEW_ACTIONS,
        "live_data_clean": live_data_ok,
        "hard_veto_clear": not hard_veto_active,
        "risk_reward_ok": rr_value >= MONEY_PILOT_MIN_RR,
        "historical_win_rate_ok": win_rate >= MONEY_PILOT_MIN_WIN_RATE,
        "sample_quality_ok": sample_count >= MONEY_PILOT_MIN_SAMPLES,
        "entry_stop_target_clear": entry_clear and stop_clear and target_clear and invalidation_clear,
        "journal_saved": bool(journal_saved),
    }
    labels = {
        "allowed_action": "AI action is not a buy-review action.",
        "live_data_clean": "Live daily/confirmation candles are not clean.",
        "hard_veto_clear": "Hard veto is active.",
        "risk_reward_ok": f"R:R is below {MONEY_PILOT_MIN_RR:.1f}.",
        "historical_win_rate_ok": f"Historical focus win rate is below {MONEY_PILOT_MIN_WIN_RATE:.0f}%.",
        "sample_quality_ok": f"Historical sample count is below {MONEY_PILOT_MIN_SAMPLES}.",
        "entry_stop_target_clear": "Entry/stop/target/invalidation plan is incomplete.",
        "journal_saved": "Journal must be saved before any manual real-money trade.",
    }
    review_keys = [key for key in criteria if key != "journal_saved"]
    eligible_for_review = all(criteria[key] for key in review_keys)
    ready_for_real_money = eligible_for_review and criteria["journal_saved"]
    blockers = [labels[key] for key, passed in criteria.items() if not passed]
    return {
        "version": "money_pilot_gate_v1",
        "action": action,
        "eligible_for_review": eligible_for_review,
        "ready_for_real_money": ready_for_real_money,
        "requires_journal": True,
        "journal_saved": bool(journal_saved),
        "criteria": criteria,
        "blockers": blockers,
        "minimum_risk_reward": MONEY_PILOT_MIN_RR,
        "minimum_win_rate": MONEY_PILOT_MIN_WIN_RATE,
        "minimum_samples": MONEY_PILOT_MIN_SAMPLES,
        "risk_reward_value": round(rr_value, 2),
        "historical_win_rate": round(win_rate, 1),
        "sample_count": sample_count,
        "policy": "Manual money pilot requires AI buy action, clean live data, hard-veto clear, R>=2, win rate>=50%, sufficient samples, clear stop/target, and saved journal.",
    }


def probe_risk_policy() -> dict[str, Any]:
    return {
        "version": "probe_risk_policy_v1",
        "default_risk_pct_of_account": PROBE_DEFAULT_RISK_PCT,
        "max_risk_pct_of_account": PROBE_MAX_RISK_PCT,
        "position_size_hint": "Starter position only; not full-size and not a chase entry.",
        "no_averaging_down": True,
        "requires_journal": True,
        "manual_execution_only": True,
        "policy": "AI_PROBE_BUY is a small-size research candidate, not a formal money-pilot buy candidate.",
    }


def build_probe_eligibility(
    *,
    action: str,
    signal: dict[str, Any],
    risk_reward_plan: dict[str, Any] | None = None,
    historical_edge: dict[str, Any] | None = None,
    hard_veto_active: bool = False,
    journal_saved: bool = False,
) -> dict[str, Any]:
    """Lighter gate for high-beta starter/probe ideas.

    This intentionally does not change the formal money-pilot gate. It only
    determines whether an AI idea can be displayed as a small-size probe
    candidate that still requires manual journal review.
    """

    risk_plan = risk_reward_plan or signal.get("risk_reward_plan") or {}
    edge = historical_edge or signal.get("historical_edge") or {}
    data_status = signal.get("data_status") or {}
    entry_plan = signal.get("entry_plan") or {}
    stop_plan = signal.get("stop_plan") or {}
    target_plan = signal.get("target_plan") or {}
    rr_value = float(risk_plan.get("risk_reward_value") or 0)
    win_rate = float(edge.get("focus_win_rate", edge.get("win_rate_5d", 0)) or 0)
    sample_count = int(edge.get("focus_sample_count", edge.get("sample_count", 0)) or 0)
    expected_value_r = (win_rate / 100 * rr_value) - ((100 - win_rate) / 100) if rr_value > 0 else 0.0
    daily_status = data_status.get("daily_provider_status")
    hourly_status = data_status.get("hourly_provider_status")
    live_data_ok = (
        data_status.get("data_quality") == "clean"
        and daily_status == "available"
        and hourly_status == "available"
        and int(data_status.get("daily_candles") or 0) > 0
        and int(data_status.get("hourly_candles") or 0) > 0
    )
    stop_clear = clear_plan_text(stop_plan.get("zone")) and clear_plan_text(stop_plan.get("stop"))
    target_clear = clear_plan_text(target_plan.get("zone")) and (
        clear_plan_text(target_plan.get("target_low")) or clear_plan_text(target_plan.get("target_high"))
    )
    entry_clear = clear_plan_text(entry_plan.get("zone")) and (
        clear_plan_text(entry_plan.get("entry_low")) or clear_plan_text(entry_plan.get("entry_high"))
    )
    invalidation_clear = bool(stop_plan.get("invalidation"))
    criteria = {
        "allowed_action": action in AI_REVIEW_ACTIONS,
        "live_data_clean": live_data_ok,
        "hard_veto_clear": not hard_veto_active,
        "risk_reward_ok": rr_value >= PROBE_MIN_RR,
        "historical_win_rate_ok": win_rate >= PROBE_MIN_WIN_RATE,
        "sample_quality_ok": sample_count >= PROBE_MIN_SAMPLES,
        "expected_value_positive": expected_value_r > 0,
        "entry_stop_target_clear": entry_clear and stop_clear and target_clear and invalidation_clear,
        "journal_saved": bool(journal_saved),
    }
    labels = {
        "allowed_action": "AI action is not eligible for probe review.",
        "live_data_clean": "Live daily/confirmation candles are not clean.",
        "hard_veto_clear": "Hard veto is active.",
        "risk_reward_ok": f"R:R is below {PROBE_MIN_RR:.1f}.",
        "historical_win_rate_ok": f"Historical focus win rate is below {PROBE_MIN_WIN_RATE:.0f}%.",
        "sample_quality_ok": f"Historical sample count is below {PROBE_MIN_SAMPLES}.",
        "expected_value_positive": "Expected R is not positive.",
        "entry_stop_target_clear": "Entry/stop/target/invalidation plan is incomplete.",
        "journal_saved": "Journal must be saved before any manual probe.",
    }
    review_keys = [key for key in criteria if key != "journal_saved"]
    eligible_for_probe_review = all(criteria[key] for key in review_keys)
    ready_for_probe_trade = eligible_for_probe_review and criteria["journal_saved"]
    blockers = [labels[key] for key, passed in criteria.items() if not passed]
    return {
        "version": "probe_gate_v1",
        "action": action,
        "eligible_for_probe_review": eligible_for_probe_review,
        "ready_for_probe_trade": ready_for_probe_trade,
        "requires_journal": True,
        "journal_saved": bool(journal_saved),
        "criteria": criteria,
        "blockers": blockers,
        "minimum_risk_reward": PROBE_MIN_RR,
        "minimum_win_rate": PROBE_MIN_WIN_RATE,
        "minimum_samples": PROBE_MIN_SAMPLES,
        "risk_reward_value": round(rr_value, 2),
        "historical_win_rate": round(win_rate, 1),
        "sample_count": sample_count,
        "expected_value_r": round(expected_value_r, 2),
        "risk_policy": probe_risk_policy(),
        "policy": "Probe review requires clean live data, hard-veto clear, R>=1.5, win rate>=45%, samples>=20, positive expected R, clear plan, and saved journal before any manual starter entry.",
    }


def build_ai_action_validation(
    action: str,
    historical_edge: dict[str, Any],
    profile: dict[str, Any],
    risk_reward_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    samples = int(historical_edge.get("focus_sample_count", historical_edge.get("sample_count", 0)) or 0)
    win_rate = float(historical_edge.get("focus_win_rate", historical_edge.get("win_rate_5d", 0)) or 0)
    avg_return = float(historical_edge.get("focus_avg_return", historical_edge.get("avg_forward_return_5d", 0)) or 0)
    avg_drawdown = float(historical_edge.get("focus_avg_max_drawdown", historical_edge.get("avg_max_drawdown_5d", 0)) or 0)
    rr_value = float((risk_reward_plan or {}).get("risk_reward_value") or 0)
    target_hit_rate = float(historical_edge.get("focus_target_hit_rate", historical_edge.get("target_hit_rate_5d", 0)) or 0)
    stop_hit_rate = float(historical_edge.get("focus_stop_hit_rate", 0) or 0)
    target_before_stop = float(historical_edge.get("focus_target_before_stop_proxy", 0) or 0)
    expected_value_r = (win_rate / 100 * rr_value) - ((100 - win_rate) / 100) if rr_value > 0 else 0.0
    evidence_quality = "robust" if samples >= 50 else "limited" if samples >= 10 else "insufficient"
    buy_like = action in {"AI_BUY_CANDIDATE", "AI_PULLBACK_BUY", "AI_PROBE_BUY", "PENDING_AI_DECISION"}
    money_pilot_eligible = (
        action in BUY_REVIEW_ACTIONS
        and samples >= MONEY_PILOT_MIN_SAMPLES
        and win_rate >= MONEY_PILOT_MIN_WIN_RATE
        and rr_value >= MONEY_PILOT_MIN_RR
        and expected_value_r > 0
    )
    probe_eligible = (
        action in AI_REVIEW_ACTIONS
        and samples >= PROBE_MIN_SAMPLES
        and win_rate >= PROBE_MIN_WIN_RATE
        and rr_value >= PROBE_MIN_RR
        and expected_value_r > 0
    )
    verdict = (
        "positive"
        if samples >= MONEY_PILOT_MIN_SAMPLES and win_rate >= MONEY_PILOT_MIN_WIN_RATE and avg_return > 0 and rr_value >= MONEY_PILOT_MIN_RR
        else "unproven"
    )
    if buy_like and samples < 30:
        verdict = "limited_evidence"
    return {
        "version": "ai_action_validation_v1",
        "action": action,
        "profile_name": profile["name"],
        "focus_window": historical_edge.get("focus_window", profile.get("focus_window")),
        "sample_count": samples,
        "evidence_quality": evidence_quality,
        "win_rate": round(win_rate, 1),
        "avg_forward_return": round(avg_return, 2),
        "avg_max_drawdown": round(avg_drawdown, 2),
        "target_hit_rate": round(target_hit_rate, 1),
        "stop_hit_rate": round(stop_hit_rate, 1),
        "target_before_stop_proxy": round(target_before_stop, 1),
        "risk_reward_value": round(rr_value, 2),
        "expected_value_r": round(expected_value_r, 2),
        "avg_return_to_drawdown": round(avg_return / max(abs(avg_drawdown), 0.01), 2),
        "noise_rate": round(max(0.0, 100 - win_rate), 1),
        "money_pilot_eligible": money_pilot_eligible,
        "money_pilot_min_risk_reward": MONEY_PILOT_MIN_RR,
        "money_pilot_min_win_rate": MONEY_PILOT_MIN_WIN_RATE,
        "money_pilot_min_samples": MONEY_PILOT_MIN_SAMPLES,
        "probe_eligible": probe_eligible,
        "probe_min_risk_reward": PROBE_MIN_RR,
        "probe_min_win_rate": PROBE_MIN_WIN_RATE,
        "probe_min_samples": PROBE_MIN_SAMPLES,
        "verdict": verdict,
        "note": "Validation is historical research evidence, not a performance guarantee.",
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
        "ai_feature_packet_v1": {
            "version": "ai_feature_packet_v1",
            "status": "unavailable",
            "reason": "Missing candles prevent AI feature construction.",
        },
        "ai_feature_packet_v2": {
            "version": "ai_feature_packet_v2",
            "status": "unavailable",
            "reason": "Missing live candles prevent AI feature construction.",
            "market_and_data_guardrails": {
                "data_clean": False,
                "daily_provider_status": daily_payload.get("provider_status", "missing"),
                "confirmation_provider_status": hourly_payload.get("provider_status", "missing"),
                "daily_candles": len(daily_payload.get("candles", [])),
                "confirmation_candles": len(hourly_payload.get("candles", [])),
            },
            "evidence_stack": ["Missing live candles; do not create an AI buy candidate."],
        },
        "entry_plan": {
            "zone": "unavailable",
            "entry_low": None,
            "entry_high": None,
            "trigger": "Missing candles prevent entry planning.",
            "no_chase_rule": "No trade during data caution.",
            "data_note": "provider data is missing",
        },
        "stop_plan": {
            "zone": "unavailable",
            "stop": None,
            "basis": "Missing candles prevent stop planning.",
            "invalidation": ["Provider data must refresh before any manual trade."],
        },
        "target_plan": {
            "zone": "unavailable",
            "target_low": None,
            "target_high": None,
            "management": "No target until live data is available.",
        },
        "risk_reward_plan": {
            "risk_reward": "unavailable",
            "risk_reward_value": 0,
            "position_size_hint": "No new exposure during data caution.",
            "minimum_for_money_pilot": 2.0,
            "eligible_for_manual_money_review": False,
        },
        "money_pilot_eligibility": {
            "version": "money_pilot_gate_v1",
            "action": "PENDING_AI_DECISION",
            "eligible_for_review": False,
            "ready_for_real_money": False,
            "requires_journal": True,
            "journal_saved": False,
            "criteria": {
                "allowed_action": False,
                "live_data_clean": False,
                "hard_veto_clear": False,
                "risk_reward_ok": False,
                "historical_win_rate_ok": False,
                "sample_quality_ok": False,
                "entry_stop_target_clear": False,
                "journal_saved": False,
            },
            "blockers": ["Missing live candles prevent money-pilot review."],
            "minimum_risk_reward": MONEY_PILOT_MIN_RR,
            "minimum_win_rate": MONEY_PILOT_MIN_WIN_RATE,
            "minimum_samples": MONEY_PILOT_MIN_SAMPLES,
            "risk_reward_value": 0.0,
            "historical_win_rate": 0.0,
            "sample_count": 0,
            "policy": "Manual money pilot requires clean live data, R>=2, win rate>=50%, sufficient samples, clear stop/target, and saved journal.",
        },
        "probe_eligibility": {
            "version": "probe_gate_v1",
            "action": "PENDING_AI_DECISION",
            "eligible_for_probe_review": False,
            "ready_for_probe_trade": False,
            "requires_journal": True,
            "journal_saved": False,
            "criteria": {
                "allowed_action": False,
                "live_data_clean": False,
                "hard_veto_clear": False,
                "risk_reward_ok": False,
                "historical_win_rate_ok": False,
                "sample_quality_ok": False,
                "expected_value_positive": False,
                "entry_stop_target_clear": False,
                "journal_saved": False,
            },
            "blockers": ["Missing live candles prevent probe review."],
            "minimum_risk_reward": PROBE_MIN_RR,
            "minimum_win_rate": PROBE_MIN_WIN_RATE,
            "minimum_samples": PROBE_MIN_SAMPLES,
            "risk_reward_value": 0.0,
            "historical_win_rate": 0.0,
            "sample_count": 0,
            "expected_value_r": 0.0,
            "risk_policy": probe_risk_policy(),
            "policy": "Probe review requires clean live data, R>=1.5, win rate>=45%, samples>=20, positive expected R, a clear plan, and saved journal.",
        },
        "probe_risk_policy": probe_risk_policy(),
        "probe_blockers": ["Missing live candles prevent probe review."],
        "ai_action_evidence": ["Missing candles; AI action validation unavailable."],
        "ai_action_validation": {
            "version": "ai_action_validation_v1",
            "action": "PENDING_AI_DECISION",
            "profile_name": active_profile["name"],
            "focus_window": active_profile.get("focus_window"),
            "sample_count": 0,
            "evidence_quality": "insufficient",
            "win_rate": 0.0,
            "avg_forward_return": 0.0,
            "avg_max_drawdown": 0.0,
            "target_hit_rate": 0.0,
            "stop_hit_rate": 0.0,
            "target_before_stop_proxy": 0.0,
            "risk_reward_value": 0.0,
            "expected_value_r": 0.0,
            "avg_return_to_drawdown": 0.0,
            "noise_rate": 100.0,
            "money_pilot_eligible": False,
            "money_pilot_min_risk_reward": MONEY_PILOT_MIN_RR,
            "money_pilot_min_win_rate": MONEY_PILOT_MIN_WIN_RATE,
            "money_pilot_min_samples": MONEY_PILOT_MIN_SAMPLES,
            "probe_eligible": False,
            "probe_min_risk_reward": PROBE_MIN_RR,
            "probe_min_win_rate": PROBE_MIN_WIN_RATE,
            "probe_min_samples": PROBE_MIN_SAMPLES,
            "verdict": "no_live_data",
            "note": "Provider data is missing; no AI buy candidate is allowed.",
        },
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


def unavailable_candles(
    symbol: str,
    range_value: str,
    interval: str,
    error: str,
    *,
    source_type: str = "live_yahoo_chart",
) -> dict[str, Any]:
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": source_type,
        "provider_status": "unavailable",
        "provider_errors": [error],
        "freshness": "missing",
        "candles": [],
        "live_does_not_fallback_to_fixture": True,
        "real_money_data_source": False,
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
    source_types: tuple[str, ...] = ("live_yahoo_chart",),
) -> dict[str, Any] | None:
    spec = candle_spec(range_value, interval)
    limit = int(spec["bars"])
    placeholders = ",".join("?" for _ in source_types)
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT open_time, open, high, low, close, volume, source, provider_status, created_at
            FROM stock_candles
            WHERE symbol = ? AND interval = ? AND source IN ({placeholders})
            ORDER BY open_time DESC
            LIMIT ?
            """,
            (symbol, interval, *source_types, limit),
        ).fetchall()
    if not rows:
        return None
    ordered = list(reversed(rows))
    newest_created = ordered[-1]["created_at"]
    source_type = str(ordered[-1]["source"] or source_types[0])
    stale_source = LONG_BRIDGE_STALE_SOURCE if source_type == LONG_BRIDGE_CANDLE_SOURCE else "stale_yahoo_chart_cache"
    candles = [
        {
            "open_time": row["open_time"],
            "time": int(datetime.fromisoformat(row["open_time"].replace("Z", "+00:00")).timestamp()),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "source": stale_source,
        }
        for row in ordered
    ]
    age_seconds = max(0, int((datetime.now(UTC) - datetime.fromisoformat(newest_created)).total_seconds()))
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": stale_source,
        "provider_status": "stale_cache",
        "provider_errors": failed_payload.get("provider_errors", []),
        "freshness": f"stale {age_seconds}s",
        "freshness_seconds": age_seconds,
        "candles": candles,
        "live_does_not_fallback_to_fixture": True,
        "real_money_data_source": False,
    }


def make_fixture_candles(symbol: str, range_value: str, interval: str) -> list[dict[str, Any]]:
    spec = candle_spec(range_value, interval)
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
    spec = candle_spec(range_value, interval)
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
    if range_value == "1d" and interval in {"1m", "5m"}:
        day = previous_trading_days(end, 1)[-1]
        start = datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
        step_minutes = 1 if interval == "1m" else 5
        bars = 390 if interval == "1m" else 78
        return [start + timedelta(minutes=step_minutes * index) for index in range(bars)]
    if range_value == "5d" and interval in {"15m", "1h"}:
        timestamps: list[datetime] = []
        step = timedelta(minutes=15) if interval == "15m" else timedelta(hours=1)
        bars_per_day = 26 if interval == "15m" else 7
        for day in previous_trading_days(end, 5):
            start = datetime(day.year, day.month, day.day, MARKET_OPEN_UTC_HOUR, MARKET_OPEN_UTC_MINUTE, tzinfo=UTC)
            timestamps.extend(start + step * index for index in range(bars_per_day))
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
        source_type = str(payload["source_type"])
        if source_type == "fixture_read_only":
            provider_name = "fixture"
        elif source_type in {LONG_BRIDGE_CANDLE_SOURCE, LONG_BRIDGE_STALE_SOURCE}:
            provider_name = "longbridge_quote"
        else:
            provider_name = "yahoo_chart"
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
            "- AI Trading Agent is a manual-trigger decision layer: it can rank, plan, and challenge the rule conclusion.",
            "- Hard rule veto remains active: stale data, provider failure, blocked rule states, and broker/order restrictions cannot be overridden by AI.",
            "- Broker and order wiring remain disabled; all AI output is read-only research for human execution.",
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


def write_ai_daily_report(outputs_dir: Path, payload: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    public_payload = {key: value for key, value in payload.items() if not key.startswith("_")}
    (outputs_dir / "ai-daily-opportunities.json").write_text(json.dumps(public_payload, indent=2), encoding="utf-8")
    ai_report = payload.get("ai_report", {})
    market = payload.get("market_regime", {})
    lines = [
        "# KQUANT AI Daily Opportunities",
        "",
        f"- Run: `{payload.get('run_id')}`",
        f"- Status: `{payload.get('status')}` / `{payload.get('reason')}`",
        f"- Model: `{payload.get('model_name')}`",
        f"- Universe: `{payload.get('universe')}`",
        f"- Profiles: `{', '.join(payload.get('profiles', []))}`",
        f"- Candidates passed to AI: `{payload.get('ai_context_candidate_count', 0)}`",
        f"- Market regime: `{market.get('regime', 'unknown')}` / score `{market.get('score', 0)}`",
        f"- Read-only: `{payload.get('read_only_research')}`",
        f"- Broker order wiring: `{payload.get('broker_order_wiring_enabled')}`",
        "",
        "## Daily Summary",
        "",
        str(ai_report.get("daily_summary") or "No AI summary."),
        "",
        "## AI Action Validation",
        "",
    ]
    validation_by_action = payload.get("validation_by_ai_action") or ai_report.get("validation_by_ai_action", {})
    if validation_by_action:
        lines.extend(
            [
                "| Action | Signals | Samples | Win Rate | Exp R | Avg R/R | Target Hit | Stop Hit | Money Eligible | Limited Evidence |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for action, stats in validation_by_action.items():
            lines.append(
                f"| {action} | {stats.get('signals', 0)} | {stats.get('total_samples', 0)} | "
                f"{stats.get('avg_win_rate', 0)}% | {stats.get('avg_expected_value_r', 0)} | "
                f"{stats.get('avg_risk_reward', 0)}R | {stats.get('avg_target_hit_rate', 0)}% | "
                f"{stats.get('avg_stop_hit_rate', 0)}% | {stats.get('money_pilot_eligible_count', 0)} | "
                f"{stats.get('limited_evidence_count', 0)} |"
            )
    else:
        lines.append("- No AI action validation yet.")
    lines.extend(
        [
            "",
        "## Top AI Buy Candidates",
        "",
        ]
    )
    top = ai_report.get("top_buy_candidates", [])
    if top:
        for item in top:
            lines.extend(
                [
                    f"### {item.get('symbol')} - {item.get('action')} - {item.get('confidence')}",
                    "",
                    f"- Best profile: `{item.get('best_profile')}`",
                    f"- Entry: {item.get('entry_zone')}",
                    f"- Stop: {item.get('stop_zone')}",
                    f"- Target: {item.get('target_zone')}",
                    f"- R/R: `{item.get('risk_reward')}`",
                    f"- Size: {item.get('position_size_hint')}",
                    f"- Why: {'; '.join(item.get('why_now', []))}",
                    f"- Risk: {'; '.join(item.get('risk_flags', []))}",
                    "",
                ]
            )
    else:
        lines.append("- None. AI did not produce a hard-veto-clean buy candidate.")
    lines.extend(["", "## Watch for Pullback", ""])
    for item in ai_report.get("watch_for_pullback", [])[:10]:
        lines.append(f"- `{item.get('symbol')}` {item.get('action')} / {item.get('best_profile')}: {item.get('entry_zone')}")
    lines.extend(["", "## Avoid / Risk Elevated", ""])
    for item in ai_report.get("avoid_or_risk_elevated", [])[:10]:
        lines.append(f"- `{item.get('symbol')}` {item.get('action')}: {'; '.join(item.get('risk_flags', []))}")
    lines.extend(
        [
            "",
            "## MSTR Cycle Update",
            "",
            str(ai_report.get("mstr_cycle_update") or "No MSTR update."),
            "",
            "## Data Quality Warnings",
            "",
        ]
    )
    for warning in ai_report.get("data_quality_warnings", []):
        lines.append(f"- {warning}")
    (outputs_dir / "ai-daily-opportunities.md").write_text("\n".join(lines), encoding="utf-8")


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
        live_count = conn.execute(
            "SELECT COUNT(*) AS count FROM stock_candles WHERE source IN ('live_yahoo_chart', ?)",
            (LONG_BRIDGE_CANDLE_SOURCE,),
        ).fetchone()["count"]
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
    if (normalized_range, normalized_interval) not in RANGE_INTERVAL_SPECS:
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
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_profile = profile or PROFILE
    high_beta_growth = bool(active_profile.get("high_beta_growth"))
    reasons: list[str] = []
    status = "CLEAR"
    level = "HOLD"
    if not data_clean:
        status = "DATA CAUTION"
        level = "CAUTION"
        reasons.append("Provider or freshness caution; do not rely on the setup until candles are clean.")
    if high_beta_growth:
        ema50_floor = float(active_profile.get("pullback_ema50_floor", 0.97))
        if close < ema50 * 0.96:
            status = "SETUP INVALIDATED"
            level = "EXIT RISK"
            reasons.append("High-beta structure is invalidated below the EMA50 risk floor.")
        elif close < ema20 and one_hour_momentum >= float(active_profile.get("confirmation_momentum_min", 0.8)) and close >= ema50 * ema50_floor:
            status = "PULLBACK RISK" if status == "CLEAR" else status
            level = "CAUTION" if level == "HOLD" else level
            reasons.append("High-beta pullback is below EMA20, but 1h momentum is turning up near EMA50 support.")
        elif close < ema20:
            status = "EXIT RISK" if status == "CLEAR" else status
            level = "CAUTION" if level == "HOLD" else level
            reasons.append("High-beta pullback lacks enough 1h momentum confirmation.")
    elif close < ema50:
        status = "SETUP INVALIDATED"
        level = "EXIT RISK"
        reasons.append("Daily close is below EMA50; long setup structure is invalidated.")
    elif close < ema20:
        status = "EXIT RISK"
        level = "CAUTION"
        reasons.append("Daily close is below EMA20; momentum is losing the preferred trend support.")
    momentum_exit = -1.5 if high_beta_growth else -0.7
    if one_hour_momentum < momentum_exit:
        status = "EXIT RISK" if status == "CLEAR" else status
        level = "CAUTION" if level == "HOLD" else level
        reasons.append("1h momentum is negative enough to require manual risk review.")
    if volume_ratio >= 1.6 and one_hour_momentum < 0:
        status = "EXIT RISK"
        level = "EXIT RISK"
        reasons.append("Downside 1h momentum is appearing with elevated volume.")
    if high_beta_growth and atr_pct > 12:
        status = "HIGH VOLATILITY RISK" if status == "CLEAR" else status
        level = "CAUTION" if level == "HOLD" else level
        reasons.append("High-beta ATR is above the system limit; use smaller size or wait for volatility compression.")
    elif not high_beta_growth and atr_pct > 6:
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
    high_beta_growth = signal.get("profile_name") == "high_beta_growth_v1"
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
    if high_beta_growth:
        required_checks.append("High-beta setups require smaller size, staged entry, and AI Review before action.")
        risk_controls.append("High-beta BUY is a manual review candidate only; use smaller size and a wider volatility-aware stop.")
    data_clean = data_status.get("data_quality") == "clean"
    min_focus_win = 48 if high_beta_growth else 52
    min_focus_avg = 1.0 if high_beta_growth else 0
    historical_positive = (
        historical.get("sample_count", 0) >= 10
        and historical.get("focus_win_rate", historical.get("win_rate_5d", 0)) >= min_focus_win
        and historical.get("focus_avg_return", historical.get("avg_forward_return_5d", 0)) >= min_focus_avg
    )
    acceptable_exit_statuses = {"CLEAR", "PULLBACK RISK"} if high_beta_growth else {"CLEAR"}
    exit_clear = exit_risk.get("status") in acceptable_exit_statuses
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
            "status": "READY_FOR_HIGH_BETA_REVIEW" if high_beta_growth else "READY_FOR_MANUAL_REVIEW",
            "ready": True,
            "market_regime": market_state,
            "reasons": [
                "High-beta growth gate passed; review size, staged entry, stop, and AI Review before action."
                if high_beta_growth
                else "All strict data, historical, exit-risk, and market filters passed."
            ],
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
    high_beta_growth = signal.get("profile_name") == "high_beta_growth_v1"
    market_state = str(market_regime.get("regime", "DATA_CAUTION"))
    data_clean = data_status.get("data_quality") == "clean"
    min_focus_win = 48 if high_beta_growth else 52
    min_focus_avg = 1.0 if high_beta_growth else 0
    historical_positive = (
        historical.get("sample_count", 0) >= 10
        and historical.get("focus_win_rate", historical.get("win_rate_5d", 0)) >= min_focus_win
        and historical.get("focus_avg_return", historical.get("avg_forward_return_5d", 0)) >= min_focus_avg
    )
    exit_status = str(exit_risk.get("status", "DATA CAUTION"))
    acceptable_exit_statuses = {"CLEAR", "PULLBACK RISK"} if high_beta_growth else {"CLEAR"}
    exit_clear = exit_status in acceptable_exit_statuses
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
    if high_beta_growth:
        why.append("High-beta profile requires smaller size, staged entry, and AI Review before action.")

    if readiness.get("ready") is True and signal.get("level") == "BUY SETUP" and data_clean and historical_positive and exit_clear:
        action = "BUY"
        confidence = "HIGH" if market_state == "RISK_ON" else "MEDIUM"
        risk_bucket = "high_beta_risk" if high_beta_growth else "standard_risk" if confidence == "HIGH" else "light_risk"
        summary = f"BUY: {signal.get('strategy_label', signal.get('profile_name', 'profile'))} setup is ready for manual review."
    elif exit_status in {"EXIT RISK", "SETUP INVALIDATED", "TAKE PROFIT WATCH"}:
        action = "EXIT_REVIEW"
        confidence = "MEDIUM"
        risk_bucket = "avoid"
        summary = f"EXIT REVIEW: {exit_status} blocks a fresh long and requires position review if already held."
    elif signal.get("level") == "WATCH" and data_clean and market_state in {"RISK_ON", "MIXED"}:
        action = "WAIT"
        confidence = "MEDIUM"
        risk_bucket = "high_beta_risk" if high_beta_growth else "light_risk"
        summary = (
            "WAIT: high-beta setup is researchable, but it still needs AI Review and staged-entry discipline."
            if high_beta_growth
            else "WAIT: setup is researchable, but one or more strict buy gates are missing."
        )
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
        "why": why[:6],
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


def ai_research_chat_model(payload: dict[str, Any]) -> str:
    requested = str(payload.get("model") or "").strip()
    if requested:
        return requested
    return os.environ.get("KQUANT_AI_RESEARCH_MODEL", "").strip() or "gpt-5.5-pro"


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
        "ai_feature_packet_v2": signal.get("ai_feature_packet_v2"),
        "entry_plan": signal.get("entry_plan"),
        "stop_plan": signal.get("stop_plan"),
        "target_plan": signal.get("target_plan"),
        "risk_reward_plan": signal.get("risk_reward_plan"),
        "ai_action_validation": signal.get("ai_action_validation"),
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


def visible_strategy_profile_keys() -> list[str]:
    return [
        "tactical_1w_v1",
        "swing_1_2m_v1",
        "position_6m_v1",
        "cycle_1_3y_v1",
        "high_beta_growth_v1",
    ]


def ai_agent_safety_policy(veto: dict[str, Any]) -> dict[str, Any]:
    return {
        "read_only_research": True,
        "ai_leads_decision_layer": True,
        "hard_rule_veto_enabled": True,
        "hard_veto_active": bool(veto.get("active")),
        "llm_signal_core_enabled": True,
        "broker_order_wiring_enabled": False,
        "account_access_enabled": False,
        "order_submission_enabled": False,
        "manual_human_execution_only": True,
    }


def ai_hard_veto(signal: dict[str, Any], market_regime: dict[str, Any]) -> dict[str, Any]:
    data_status = signal.get("data_status", {})
    trade_conclusion = signal.get("trade_conclusion", {})
    exit_risk = signal.get("exit_risk", {})
    historical = signal.get("historical_edge", {})
    reasons: list[str] = []
    guardrail_warnings: list[str] = []
    data_quality = data_status.get("data_quality")
    daily_status = data_status.get("daily_provider_status")
    hourly_status = data_status.get("hourly_provider_status")
    if data_quality != "clean":
        reasons.append(f"data_quality={data_quality or 'missing'}")
    if daily_status != "available" or hourly_status != "available":
        reasons.append(f"provider daily={daily_status or 'missing'} hourly={hourly_status or 'missing'}")
    if int(data_status.get("daily_candles") or 0) <= 0 or int(data_status.get("hourly_candles") or 0) <= 0:
        reasons.append("missing live candles")
    market_state = str(market_regime.get("regime", "DATA_CAUTION"))
    if market_state in {"RISK_OFF", "DATA_CAUTION"}:
        reasons.append(f"market_regime={market_state}")
    exit_status = str(exit_risk.get("status", "DATA CAUTION"))
    if exit_status == "DATA CAUTION":
        reasons.append(f"exit_risk={exit_status}")
    elif exit_status in {"EXIT RISK", "SETUP INVALIDATED", "PULLBACK RISK", "HIGH VOLATILITY RISK"}:
        guardrail_warnings.append(f"exit_risk={exit_status}")
    if trade_conclusion.get("action") in {"DO_NOT_BUY", "EXIT_REVIEW"}:
        guardrail_warnings.append(f"rule_action={trade_conclusion.get('action')}")
    focus_win = float(historical.get("focus_win_rate", historical.get("win_rate_5d", 0)) or 0)
    focus_avg = float(historical.get("focus_avg_return", historical.get("avg_forward_return_5d", 0)) or 0)
    if focus_win < 45 or focus_avg < -1:
        guardrail_warnings.append(f"weak_historical_edge win={round(focus_win, 1)} avg={round(focus_avg, 2)}")
    return {
        "active": bool(reasons),
        "reasons": reasons[:8],
        "guardrail_warnings": guardrail_warnings[:8],
        "can_ai_buy": not reasons,
        "veto_version": "ai_primary_v2",
        "policy": (
            "AI leads opportunity recognition. Hard veto blocks only non-negotiable data/market safety failures; "
            "rule action, exit-risk structure, and historical edge are guardrails the AI must explain and size around."
        ),
    }


def ai_decision_context(
    symbol: str,
    profile: str,
    signal: dict[str, Any],
    profile_comparison: list[Any],
    journal: dict[str, Any],
    market_regime: dict[str, Any],
    research_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = ai_review_context(symbol, profile, signal, profile_comparison, journal)
    base["market_regime"] = {
        "regime": market_regime.get("regime"),
        "label": market_regime.get("label"),
        "score": market_regime.get("score"),
        "high_confidence_allowed": market_regime.get("high_confidence_allowed"),
        "reasons": market_regime.get("reasons", [])[:5],
    }
    base["hard_veto"] = ai_hard_veto(signal, market_regime)
    base["ai_feature_packet_v1"] = signal.get("ai_feature_packet_v1") or {
        "version": "ai_feature_packet_v1",
        "status": "unavailable",
        "reason": "Signal payload did not include a computed AI feature packet.",
        "features": signal.get("features", {}),
        "data_status": signal.get("data_status", {}),
    }
    base["ai_feature_packet_v2"] = signal.get("ai_feature_packet_v2") or {
        "version": "ai_feature_packet_v2",
        "status": "unavailable",
        "reason": "Signal payload did not include AI Feature Packet v2.",
        "features": signal.get("features", {}),
        "data_status": signal.get("data_status", {}),
    }
    base["rule_trade_plans"] = {
        "entry_plan": signal.get("entry_plan", {}),
        "stop_plan": signal.get("stop_plan", {}),
        "target_plan": signal.get("target_plan", {}),
        "risk_reward_plan": signal.get("risk_reward_plan", {}),
    }
    base["ai_action_validation_baseline"] = signal.get("ai_action_validation", {})
    base["research_context"] = research_context or {
        "status": "disabled",
        "note": "External research layer is disabled; use KQUANT live data, rule guardrails, AI command, historical edge, and journal context.",
    }
    base["task"] = (
        "Lead the manual trading decision. Produce a practical entry/stop/target plan, "
        "using KQUANT technical inputs, journal context, and hard vetoes, "
        "and never propose automatic execution."
    )
    return base


def openai_decision_request(model: str, context: dict[str, Any]) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "AI_BUY_CANDIDATE",
                    "AI_PULLBACK_BUY",
                    "AI_PROBE_BUY",
                    "AI_REVERSAL_WATCH",
                    "AI_BREAKOUT_WATCH",
                    "AI_WAIT",
                    "AI_AVOID",
                    "AI_HOLD_TRAIL",
                    "AI_EXIT_REVIEW",
                ],
            },
            "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "risk_bucket": {"type": "string", "enum": ["standard_risk", "light_risk", "high_beta_risk", "avoid"]},
            "entry_zone": {"type": "string"},
            "stop_zone": {"type": "string"},
            "target_zone": {"type": "string"},
            "risk_reward": {"type": "string"},
            "position_size_hint": {"type": "string"},
            "why_now": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "what_invalidates_this_setup": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "best_profile": {"type": "string"},
            "human_checklist": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "summary": {"type": "string"},
        },
        "required": [
            "action",
            "confidence",
            "risk_bucket",
            "entry_zone",
            "stop_zone",
            "target_zone",
            "risk_reward",
            "position_size_hint",
            "why_now",
            "what_invalidates_this_setup",
            "best_profile",
            "human_checklist",
            "summary",
        ],
    }
    system = (
        "You are KQUANT AI Primary Trade Engine v2. You lead opportunity recognition and manual trade planning, "
        "while remaining strictly read-only. Treat ai_feature_packet_v2 as the primary structured trading input, "
        "including 1D/1H summaries, EMA8/9/20/50/200, VWAP, RSI14, volume, ATR, historical edge, and market context. "
        "Use rule_trade_plans as the deterministic baseline, but improve or reject the plan if the evidence demands it. "
        "The rule conclusion is a guardrail input, not the final decision. If hard_veto.active is true, do not output "
        "AI_BUY_CANDIDATE, AI_PULLBACK_BUY, or AI_PROBE_BUY. AI_PROBE_BUY means a starter-position research candidate, "
        "not a formal buy; use it only when hard veto is clear, R/R and historical evidence are positive but the full money "
        "pilot gate is not met. If rule guardrails are negative but hard veto is clear, you may output AI_PROBE_BUY, "
        "AI_PULLBACK_BUY, AI_REVERSAL_WATCH, or AI_BREAKOUT_WATCH only with explicit entry zone, stop zone, no-chase "
        "condition, small-size hint, and invalidation. Never place orders, never access broker accounts, and never "
        "promise profit. Return concise, actionable, risk-aware planning for a human trader."
    )
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kquant_ai_decision",
                "schema": schema,
                "strict": True,
            }
        },
    }


def sanitize_ai_decision(decision: dict[str, Any], signal: dict[str, Any], veto: dict[str, Any]) -> dict[str, Any]:
    allowed_actions = {
        "AI_BUY_CANDIDATE",
        "AI_PULLBACK_BUY",
        "AI_PROBE_BUY",
        "AI_REVERSAL_WATCH",
        "AI_BREAKOUT_WATCH",
        "AI_WAIT",
        "AI_AVOID",
        "AI_HOLD_TRAIL",
        "AI_EXIT_REVIEW",
    }
    buy_actions = {"AI_BUY_CANDIDATE", "AI_PULLBACK_BUY"}
    probe_actions = {"AI_PROBE_BUY"}
    watch_actions = {"AI_REVERSAL_WATCH", "AI_BREAKOUT_WATCH"}
    action = decision.get("action") if decision.get("action") in allowed_actions else "AI_WAIT"
    rule_action = (signal.get("trade_conclusion") or {}).get("action", "DO_NOT_BUY")
    if veto.get("active") and action in (buy_actions | probe_actions):
        action = "AI_EXIT_REVIEW" if rule_action == "EXIT_REVIEW" else "AI_AVOID"
    if veto.get("active") and action in watch_actions:
        action = "AI_WAIT"
    allowed_confidence = {"HIGH", "MEDIUM", "LOW"}
    confidence = decision.get("confidence") if decision.get("confidence") in allowed_confidence else "LOW"
    if veto.get("active") and confidence == "HIGH":
        confidence = "LOW"
    if veto.get("guardrail_warnings") and action in (buy_actions | probe_actions) and confidence == "HIGH":
        confidence = "MEDIUM"
    risk_bucket = decision.get("risk_bucket")
    if risk_bucket not in {"standard_risk", "light_risk", "high_beta_risk", "avoid"}:
        risk_bucket = "avoid" if veto.get("active") else "light_risk"
    if action in probe_actions and risk_bucket == "standard_risk":
        risk_bucket = "high_beta_risk"
    if veto.get("active") and action in {"AI_AVOID", "AI_EXIT_REVIEW"}:
        risk_bucket = "avoid"
    probe_check = build_probe_eligibility(
        action=action,
        signal=signal,
        risk_reward_plan=signal.get("risk_reward_plan") or {},
        historical_edge=signal.get("historical_edge") or {},
        hard_veto_active=bool(veto.get("active")),
    )
    if action in probe_actions and not probe_check.get("eligible_for_probe_review"):
        action = "AI_WAIT"
        confidence = "LOW" if confidence == "HIGH" else confidence
        risk_bucket = "light_risk" if not veto.get("active") else "avoid"
        probe_check = build_probe_eligibility(
            action=action,
            signal=signal,
            risk_reward_plan=signal.get("risk_reward_plan") or {},
            historical_edge=signal.get("historical_edge") or {},
            hard_veto_active=bool(veto.get("active")),
        )
    action_validation = build_ai_action_validation(
        action,
        signal.get("historical_edge") or {},
        profile_config(str(signal.get("profile_name") or "tactical_1w_v1")),
        signal.get("risk_reward_plan") or {},
    )
    money_pilot = build_money_pilot_eligibility(
        action=action,
        signal=signal,
        risk_reward_plan=signal.get("risk_reward_plan") or {},
        historical_edge=signal.get("historical_edge") or {},
        hard_veto_active=bool(veto.get("active")),
    )
    return {
        "action": action,
        "confidence": confidence,
        "risk_bucket": risk_bucket,
        "entry_zone": str(decision.get("entry_zone") or "Wait for a cleaner live-data setup.")[:180],
        "stop_zone": str(decision.get("stop_zone") or "Define stop before any manual action.")[:180],
        "target_zone": str(decision.get("target_zone") or "No target until setup quality improves.")[:180],
        "risk_reward": str(decision.get("risk_reward") or "not_available")[:80],
        "position_size_hint": str(decision.get("position_size_hint") or "manual sizing only; no automatic order")[:160],
        "why_now": safe_string_list(decision.get("why_now"), 6),
        "what_invalidates_this_setup": safe_string_list(decision.get("what_invalidates_this_setup"), 6),
        "best_profile": str(decision.get("best_profile") or signal.get("profile_name") or "")[:80],
        "human_checklist": safe_string_list(decision.get("human_checklist"), 6),
        "summary": str(decision.get("summary") or "AI decision generated for manual review only.")[:600],
        "rule_action": rule_action,
        "hard_veto_applied": bool(veto.get("active")),
        "hard_veto_reasons": veto.get("reasons", []),
        "guardrail_warnings": veto.get("guardrail_warnings", []),
        "entry_plan": signal.get("entry_plan", {}),
        "stop_plan": signal.get("stop_plan", {}),
        "target_plan": signal.get("target_plan", {}),
        "risk_reward_plan": signal.get("risk_reward_plan", {}),
        "ai_action_validation": action_validation,
        "money_pilot_eligibility": money_pilot,
        "probe_eligibility": probe_check,
        "probe_risk_policy": probe_risk_policy(),
        "probe_blockers": probe_check["blockers"],
        "ai_feature_packet_version": "ai_feature_packet_v2",
        "ai_primary_engine_version": "ai_primary_v2",
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "order_submission_enabled": False,
    }


def unavailable_ai_decision(signal: dict[str, Any], veto: dict[str, Any], reason: str) -> dict[str, Any]:
    rule_action = (signal.get("trade_conclusion") or {}).get("action", "DO_NOT_BUY")
    if rule_action == "BUY" and not veto.get("active"):
        action = "AI_WAIT"
    elif rule_action == "EXIT_REVIEW":
        action = "AI_EXIT_REVIEW"
    elif veto.get("active"):
        action = "AI_AVOID"
    else:
        action = "AI_WAIT"
    action_validation = build_ai_action_validation(
        action,
        signal.get("historical_edge") or {},
        profile_config(str(signal.get("profile_name") or "tactical_1w_v1")),
        signal.get("risk_reward_plan") or {},
    )
    money_pilot = build_money_pilot_eligibility(
        action=action,
        signal=signal,
        risk_reward_plan=signal.get("risk_reward_plan") or {},
        historical_edge=signal.get("historical_edge") or {},
        hard_veto_active=bool(veto.get("active")),
    )
    probe_check = build_probe_eligibility(
        action=action,
        signal=signal,
        risk_reward_plan=signal.get("risk_reward_plan") or {},
        historical_edge=signal.get("historical_edge") or {},
        hard_veto_active=bool(veto.get("active")),
    )
    return {
        "action": action,
        "confidence": "LOW",
        "risk_bucket": "avoid" if veto.get("active") else "light_risk",
        "entry_zone": "AI unavailable; use rule setup and live K-lines only.",
        "stop_zone": "No AI stop plan. Define manually before any trade.",
        "target_zone": "No AI target plan. Define manually before any trade.",
        "risk_reward": "unavailable",
        "position_size_hint": "AI unavailable; keep manual sizing conservative.",
        "why_now": [
            "AI Trading Agent is unavailable.",
            "Rule system and live-data guardrails remain active.",
        ],
        "what_invalidates_this_setup": veto.get("reasons", [])[:4] or ["Provider/data/risk state worsens."],
        "best_profile": signal.get("profile_name", ""),
        "human_checklist": [
            "Confirm live candles are available.",
            "Check rule conclusion, market regime, and exit risk.",
            "Save a journal plan before acting manually.",
        ],
        "summary": reason,
        "rule_action": rule_action,
        "hard_veto_applied": bool(veto.get("active")),
        "hard_veto_reasons": veto.get("reasons", []),
        "guardrail_warnings": veto.get("guardrail_warnings", []),
        "entry_plan": signal.get("entry_plan", {}),
        "stop_plan": signal.get("stop_plan", {}),
        "target_plan": signal.get("target_plan", {}),
        "risk_reward_plan": signal.get("risk_reward_plan", {}),
        "ai_action_validation": action_validation,
        "money_pilot_eligibility": money_pilot,
        "probe_eligibility": probe_check,
        "probe_risk_policy": probe_risk_policy(),
        "probe_blockers": probe_check["blockers"],
        "ai_feature_packet_version": "ai_feature_packet_v2",
        "ai_primary_engine_version": "ai_primary_v2",
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "order_submission_enabled": False,
    }


def research_chat_context(
    symbol: str,
    profile: str,
    question: str,
    signal: dict[str, Any],
    ai_decision: dict[str, Any],
    research_context: dict[str, Any],
    messages: list[Any],
    language: str,
) -> dict[str, Any]:
    compact_messages = [
        {
            "role": str(message.get("role") or "")[:20],
            "content": str(message.get("content") or "")[:1200],
        }
        for message in messages[-8:]
        if isinstance(message, dict) and str(message.get("content") or "").strip()
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
        "historical_edge": signal.get("historical_edge"),
        "data_status": signal.get("data_status"),
        "features": {
            key: signal.get("features", {}).get(key)
            for key in ["close", "ema20", "ema50", "ema200", "atr_pct", "volume_ratio", "rsi14", "momentum_1h_pct"]
        },
        "trend_summary": signal.get("trend_summary"),
        "trigger_summary": signal.get("trigger_summary"),
        "risk_warnings": signal.get("risk_warnings", [])[:8],
        "ai_feature_packet_v2": signal.get("ai_feature_packet_v2"),
        "entry_plan": signal.get("entry_plan"),
        "stop_plan": signal.get("stop_plan"),
        "target_plan": signal.get("target_plan"),
        "risk_reward_plan": signal.get("risk_reward_plan"),
        "ai_action_validation": signal.get("ai_action_validation"),
        "money_pilot_eligibility": signal.get("money_pilot_eligibility"),
    }
    decision_payload = ai_decision.get("ai_decision") if isinstance(ai_decision.get("ai_decision"), dict) else ai_decision
    return {
        "input_summary": {
            "symbol": symbol,
            "profile": profile,
            "question": question[:240],
            "language": "zh" if language.startswith("zh") else "en",
            "messages": len(compact_messages),
            "rule_level": signal.get("level"),
            "rule_score": signal.get("score"),
            "ai_action": decision_payload.get("action") if isinstance(decision_payload, dict) else None,
        },
        "task": (
            "Answer the user's deep research question using KQUANT live technical inputs, AI trading command, "
            "historical edge, journal context, and safety guardrails. Be specific, trader-oriented, and skeptical. "
            "You may challenge the setup, ask for patience, or propose what would change the view. "
            "Do not place orders, access brokerage accounts, or promise profit."
        ),
        "question": question,
        "language": "zh" if language.startswith("zh") else "en",
        "signal": compact_signal,
        "ai_decision": decision_payload if isinstance(decision_payload, dict) else {},
        "research_context": research_context or {
            "status": "disabled",
            "note": "External research layer is disabled; use KQUANT live data, AI command, historical edge, and journal context.",
        },
        "recent_messages": compact_messages,
        "safety": {
            "read_only_research": True,
            "no_broker": True,
            "no_order_submission": True,
            "human_execution_only": True,
        },
    }


def openai_research_chat_request(model: str, context: dict[str, Any]) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string"},
            "direct_view": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 7},
            "risk_flags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
            "what_to_check_next": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6},
            "evidence_used": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 6},
            "follow_up_questions": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
            "safety_note": {"type": "string"},
        },
        "required": [
            "answer",
            "direct_view",
            "key_points",
            "risk_flags",
            "what_to_check_next",
            "evidence_used",
            "follow_up_questions",
            "safety_note",
        ],
    }
    language = context.get("language", "zh")
    system = (
        "You are KQUANT Deep Research Chat, the strongest-model research layer inside a read-only stock research terminal. "
        "Use the supplied live K-line facts, rule signals, AI trading command, historical edge, and journal context. "
        "Answer like a senior trading research partner: concise, evidence-based, skeptical, and practical. "
        "Never claim certainty, never promise returns, never place orders, and never ask for broker credentials. "
        f"Return the answer in {'Simplified Chinese' if language == 'zh' else 'English'}."
    )
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kquant_deep_research_chat",
                "schema": schema,
                "strict": True,
            }
        },
    }


def sanitize_research_chat_answer(answer: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer": str(answer.get("answer") or "No answer returned.")[:4000],
        "direct_view": str(answer.get("direct_view") or "research_only")[:400],
        "key_points": safe_string_list(answer.get("key_points"), 7),
        "risk_flags": safe_string_list(answer.get("risk_flags"), 6),
        "what_to_check_next": safe_string_list(answer.get("what_to_check_next"), 6),
        "evidence_used": safe_string_list(answer.get("evidence_used"), 6),
        "follow_up_questions": safe_string_list(answer.get("follow_up_questions"), 5),
        "safety_note": str(answer.get("safety_note") or "Read-only research; human execution only.")[:500],
    }


def unavailable_research_chat_answer(question: str) -> dict[str, Any]:
    return {
        "answer": "AI research chat is unavailable because the backend model key or request failed. Live K-lines, rule guardrails, and AI Daily reports remain usable.",
        "direct_view": "AI unavailable; use rule system and K-line evidence only.",
        "key_points": [
            "The question was received, but no model answer was generated.",
            "Do not treat missing AI output as a buy or sell signal.",
        ],
        "risk_flags": ["AI unavailable", "Manual verification required"],
        "what_to_check_next": [
            "Confirm OPENAI_API_KEY is set in the backend environment.",
            "Confirm KQUANT backend was restarted after setting the key.",
        ],
        "evidence_used": [],
        "follow_up_questions": [
            "Should I inspect live K-lines and rule guardrails instead?",
            "Should I retry after backend model configuration is fixed?",
        ],
        "safety_note": "Read-only research only; no broker, account, or order path is connected.",
    }


def ai_candidate_sort_key(signal: dict[str, Any]) -> tuple[float, float, float]:
    action = (signal.get("trade_conclusion") or {}).get("action", "")
    action_bonus = {"BUY": 30, "WAIT": 16, "HOLD_TRAIL": 10, "EXIT_REVIEW": 4, "DO_NOT_BUY": 0}.get(action, 0)
    edge = signal.get("historical_edge", {})
    return (
        float(signal.get("score", 0) or 0) + action_bonus,
        float(edge.get("focus_avg_return", edge.get("avg_forward_return_5d", 0)) or 0),
        float(edge.get("focus_win_rate", edge.get("win_rate_5d", 0)) or 0),
    )


def ai_daily_candidate_summary(signal: dict[str, Any], market_regime: dict[str, Any]) -> dict[str, Any]:
    veto = ai_hard_veto(signal, market_regime)
    research_summary: dict[str, Any] = {
        "status": "disabled",
        "evidence_count": 0,
        "top_evidence": [],
        "note": "External research layer removed; daily agent uses KQUANT live data, rule guardrails, market regime, and journal context.",
    }
    return {
        "symbol": signal.get("symbol"),
        "profile_name": signal.get("profile_name"),
        "strategy_label": signal.get("strategy_label"),
        "holding_period": signal.get("holding_period"),
        "layer": signal.get("primary_layer"),
        "level": signal.get("level"),
        "score": signal.get("score"),
        "rule_action": (signal.get("trade_conclusion") or {}).get("action"),
        "risk_bucket": (signal.get("trade_conclusion") or {}).get("risk_bucket"),
        "trend_summary": signal.get("trend_summary"),
        "trigger_summary": signal.get("trigger_summary"),
        "exit_risk": (signal.get("exit_risk") or {}).get("status"),
        "historical_edge": {
            "window": (signal.get("historical_edge") or {}).get("focus_window"),
            "win_rate": (signal.get("historical_edge") or {}).get("focus_win_rate"),
            "avg_return": (signal.get("historical_edge") or {}).get("focus_avg_return"),
            "sample_count": (signal.get("historical_edge") or {}).get("focus_sample_count"),
        },
        "data_status": signal.get("data_status"),
        "ai_feature_packet_v1": signal.get("ai_feature_packet_v1"),
        "ai_feature_packet_v2": signal.get("ai_feature_packet_v2"),
        "rule_trade_plans": {
            "entry_plan": signal.get("entry_plan", {}),
            "stop_plan": signal.get("stop_plan", {}),
            "target_plan": signal.get("target_plan", {}),
            "risk_reward_plan": signal.get("risk_reward_plan", {}),
        },
        "ai_action_validation_baseline": signal.get("ai_action_validation", {}),
        "money_pilot_eligibility_baseline": signal.get("money_pilot_eligibility", {}),
        "probe_eligibility_baseline": signal.get("probe_eligibility", {}),
        "probe_risk_policy": signal.get("probe_risk_policy", probe_risk_policy()),
        "hard_veto": veto,
        "research_context": research_summary,
    }


def openai_daily_agent_request(model: str, context: dict[str, Any]) -> dict[str, Any]:
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "symbol": {"type": "string"},
            "action": {
                "type": "string",
                "enum": [
                    "AI_BUY_CANDIDATE",
                    "AI_PULLBACK_BUY",
                    "AI_PROBE_BUY",
                    "AI_REVERSAL_WATCH",
                    "AI_BREAKOUT_WATCH",
                    "AI_WAIT",
                    "AI_AVOID",
                    "AI_HOLD_TRAIL",
                    "AI_EXIT_REVIEW",
                ],
            },
            "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "best_profile": {"type": "string"},
            "entry_zone": {"type": "string"},
            "stop_zone": {"type": "string"},
            "target_zone": {"type": "string"},
            "risk_reward": {"type": "string"},
            "position_size_hint": {"type": "string"},
            "why_now": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
            "risk_flags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
        },
        "required": [
            "symbol",
            "action",
            "confidence",
            "best_profile",
            "entry_zone",
            "stop_zone",
            "target_zone",
            "risk_reward",
            "position_size_hint",
            "why_now",
            "risk_flags",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "top_buy_candidates": {"type": "array", "items": item_schema, "maxItems": 5},
            "probe_candidates": {"type": "array", "items": item_schema, "maxItems": 6},
            "watch_for_pullback": {"type": "array", "items": item_schema, "maxItems": 8},
            "avoid_or_risk_elevated": {"type": "array", "items": item_schema, "maxItems": 8},
            "mstr_cycle_update": {"type": "string"},
            "data_quality_warnings": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
            "daily_summary": {"type": "string"},
        },
        "required": [
            "top_buy_candidates",
            "probe_candidates",
            "watch_for_pullback",
            "avoid_or_risk_elevated",
            "mstr_cycle_update",
            "data_quality_warnings",
            "daily_summary",
        ],
    }
    system = (
        "You are KQUANT Daily Opportunity Agent running AI Primary Trade Engine v2. Rank a small set of manual trading opportunities. "
        "Use ai_feature_packet_v2 as the primary structured technical-data packet for each candidate. "
        "Use rule_trade_plans and ai_action_validation_baseline as deterministic baselines for entry, stop, target, R/R, and evidence quality. "
        "Respect hard_veto: candidates with hard_veto.active cannot be top_buy_candidates or probe_candidates. "
        "Rule PASS/EXIT_REVIEW, exit-risk warnings, and weak historical edge are guardrails, not final conclusions; "
        "if hard veto is clear, you may propose AI_PROBE_BUY for starter-position research candidates that are too early for full-size review, "
        "or pullback/reversal/breakout watch plans with explicit risk controls. Keep AI_PROBE_BUY separate from top_buy_candidates. "
        "No broker, no account access, no order placement, no profit promises. Be concise and practical."
    )
    return {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "kquant_ai_daily_opportunities",
                "schema": schema,
                "strict": True,
            }
        },
    }


def ai_daily_item_sort_key(item: dict[str, Any]) -> tuple[float, float, float, float]:
    validation = item.get("ai_action_validation") if isinstance(item.get("ai_action_validation"), dict) else {}
    money = item.get("money_pilot_eligibility") if isinstance(item.get("money_pilot_eligibility"), dict) else {}
    return (
        1.0 if money.get("eligible_for_review") else 0.0,
        float(validation.get("expected_value_r") or 0),
        float(validation.get("risk_reward_value") or 0),
        float(validation.get("win_rate") or 0),
    )


def sanitize_daily_ai_report(report: dict[str, Any], candidates: list[dict[str, Any]], market_regime: dict[str, Any]) -> dict[str, Any]:
    by_symbol = {signal.get("symbol"): signal for signal in candidates}

    def sanitize_items(items: Any, allow_buy: bool) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        if not isinstance(items, list):
            return sanitized
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            symbol = normalize_symbol(item.get("symbol", ""))
            signal = by_symbol.get(symbol)
            veto = ai_hard_veto(signal, market_regime) if signal else {"active": True, "reasons": ["symbol not in rule candidate set"]}
            allowed_actions = {
                "AI_BUY_CANDIDATE",
                "AI_PULLBACK_BUY",
                "AI_PROBE_BUY",
                "AI_REVERSAL_WATCH",
                "AI_BREAKOUT_WATCH",
                "AI_WAIT",
                "AI_AVOID",
                "AI_HOLD_TRAIL",
                "AI_EXIT_REVIEW",
            }
            action = item.get("action") if item.get("action") in allowed_actions else "AI_WAIT"
            if veto.get("active") and action in AI_REVIEW_ACTIONS:
                action = "AI_AVOID"
            if action in {"AI_BUY_CANDIDATE", "AI_PULLBACK_BUY"} and not allow_buy:
                action = "AI_WAIT"
            action_validation = build_ai_action_validation(
                action,
                (signal or {}).get("historical_edge") or {},
                profile_config(str((signal or {}).get("profile_name") or "tactical_1w_v1")),
                (signal or {}).get("risk_reward_plan") or {},
            )
            money_pilot = build_money_pilot_eligibility(
                action=action,
                signal=signal or {},
                risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                historical_edge=(signal or {}).get("historical_edge") or {},
                hard_veto_active=bool(veto.get("active")),
            )
            probe_check = build_probe_eligibility(
                action=action,
                signal=signal or {},
                risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                historical_edge=(signal or {}).get("historical_edge") or {},
                hard_veto_active=bool(veto.get("active")),
            )
            risk_flags = safe_string_list(item.get("risk_flags"), 5) + list(veto.get("reasons", [])[:3])
            if action in BUY_REVIEW_ACTIONS and not money_pilot.get("eligible_for_review"):
                risk_flags.append("money_pilot_not_eligible")
            if action == "AI_PROBE_BUY" and not probe_check.get("eligible_for_probe_review"):
                risk_flags.append("probe_not_eligible")
            sanitized.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "confidence": item.get("confidence") if item.get("confidence") in {"HIGH", "MEDIUM", "LOW"} else "LOW",
                    "best_profile": str(item.get("best_profile") or (signal or {}).get("profile_name") or "")[:80],
                    "entry_zone": str(item.get("entry_zone") or "")[:160],
                    "stop_zone": str(item.get("stop_zone") or "")[:160],
                    "target_zone": str(item.get("target_zone") or "")[:160],
                    "risk_reward": str(item.get("risk_reward") or "")[:80],
                    "position_size_hint": str(item.get("position_size_hint") or "manual sizing only")[:160],
                    "why_now": safe_string_list(item.get("why_now"), 4),
                    "risk_flags": risk_flags[:8],
                    "hard_veto_applied": bool(veto.get("active")),
                    "guardrail_warnings": list(veto.get("guardrail_warnings", [])[:5]),
                    "ai_action_validation": action_validation,
                    "money_pilot_eligibility": money_pilot,
                    "probe_eligibility": probe_check,
                    "probe_risk_policy": probe_risk_policy(),
                    "probe_blockers": probe_check["blockers"],
                    "ai_feature_packet_version": "ai_feature_packet_v2",
                }
            )
        return sanitized

    raw_top = sanitize_items(report.get("top_buy_candidates"), allow_buy=True)
    raw_probe = sanitize_items(report.get("probe_candidates"), allow_buy=False)
    raw_watch = sanitize_items(report.get("watch_for_pullback"), allow_buy=False)
    raw_avoid = sanitize_items(report.get("avoid_or_risk_elevated"), allow_buy=False)
    eligible_top = [
        item
        for item in raw_top
        if item.get("action") in BUY_REVIEW_ACTIONS and (item.get("money_pilot_eligibility") or {}).get("eligible_for_review")
    ]
    downgraded_from_top = [
        item
        for item in raw_top
        if item not in eligible_top
    ]
    probe_items = [
        item
        for item in raw_probe
        if item.get("action") == "AI_PROBE_BUY" and (item.get("probe_eligibility") or {}).get("eligible_for_probe_review")
    ]
    still_watch_from_top = []
    for item in downgraded_from_top:
        if item.get("action") in BUY_REVIEW_ACTIONS:
            signal = by_symbol.get(item.get("symbol"))
            probe_check = build_probe_eligibility(
                action=item.get("action"),
                signal=signal or {},
                risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                historical_edge=(signal or {}).get("historical_edge") or {},
                hard_veto_active=bool(item.get("hard_veto_applied")),
            )
            if probe_check.get("eligible_for_probe_review"):
                item["action"] = "AI_PROBE_BUY"
                item["risk_flags"] = (item.get("risk_flags") or []) + ["downgraded_to_probe_by_money_pilot_gate"]
                item["probe_eligibility"] = probe_check
                item["probe_risk_policy"] = probe_risk_policy()
                item["probe_blockers"] = probe_check["blockers"]
                item["ai_action_validation"] = build_ai_action_validation(
                    "AI_PROBE_BUY",
                    (signal or {}).get("historical_edge") or {},
                    profile_config(str((signal or {}).get("profile_name") or "tactical_1w_v1")),
                    (signal or {}).get("risk_reward_plan") or {},
                )
                item["money_pilot_eligibility"] = build_money_pilot_eligibility(
                    action="AI_PROBE_BUY",
                    signal=signal or {},
                    risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                    historical_edge=(signal or {}).get("historical_edge") or {},
                    hard_veto_active=bool(item.get("hard_veto_applied")),
                )
                probe_items.append(item)
            else:
                item["action"] = "AI_WAIT"
                item["risk_flags"] = (item.get("risk_flags") or []) + ["downgraded_from_top_by_money_pilot_gate"]
                validation = build_ai_action_validation(
                    "AI_WAIT",
                    (signal or {}).get("historical_edge") or {},
                    profile_config(str((signal or {}).get("profile_name") or "tactical_1w_v1")),
                    (signal or {}).get("risk_reward_plan") or {},
                )
                item["ai_action_validation"] = validation
                item["money_pilot_eligibility"] = build_money_pilot_eligibility(
                    action="AI_WAIT",
                    signal=signal or {},
                    risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                    historical_edge=(signal or {}).get("historical_edge") or {},
                    hard_veto_active=bool(item.get("hard_veto_applied")),
                )
                item["probe_eligibility"] = build_probe_eligibility(
                    action="AI_WAIT",
                    signal=signal or {},
                    risk_reward_plan=(signal or {}).get("risk_reward_plan") or {},
                    historical_edge=(signal or {}).get("historical_edge") or {},
                    hard_veto_active=bool(item.get("hard_veto_applied")),
                )
                item["probe_blockers"] = item["probe_eligibility"]["blockers"]
                still_watch_from_top.append(item)
        elif item.get("action") == "AI_PROBE_BUY":
            probe_check = item.get("probe_eligibility") or {}
            if probe_check.get("eligible_for_probe_review"):
                probe_items.append(item)
            else:
                item["action"] = "AI_WAIT"
                item["risk_flags"] = (item.get("risk_flags") or []) + ["probe_not_eligible"]
                still_watch_from_top.append(item)
        else:
            still_watch_from_top.append(item)
    eligible_top = sorted(eligible_top, key=ai_daily_item_sort_key, reverse=True)[:5]
    probe_items = sorted(probe_items, key=ai_daily_item_sort_key, reverse=True)[:6]
    watch_items = sorted(still_watch_from_top + raw_watch, key=ai_daily_item_sort_key, reverse=True)[:8]
    avoid_items = sorted(raw_avoid, key=ai_daily_item_sort_key, reverse=True)[:8]
    sanitized_report = {
        "top_buy_candidates": eligible_top,
        "probe_candidates": probe_items,
        "watch_for_pullback": watch_items,
        "avoid_or_risk_elevated": avoid_items,
        "mstr_cycle_update": str(report.get("mstr_cycle_update") or "MSTR cycle update not generated.")[:500],
        "data_quality_warnings": safe_string_list(report.get("data_quality_warnings"), 8),
        "daily_summary": str(report.get("daily_summary") or "AI daily opportunity report generated for manual review only.")[:700],
    }
    sanitized_report["validation_by_ai_action"] = summarize_ai_report_action_validation(sanitized_report)
    return sanitized_report


def unavailable_daily_ai_report(candidates: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    watch = []
    avoid = []
    for candidate in candidates[:8]:
        item = {
            "symbol": candidate.get("symbol", ""),
            "action": "AI_WAIT" if not candidate.get("hard_veto", {}).get("active") else "AI_AVOID",
            "confidence": "LOW",
            "best_profile": candidate.get("profile_name", ""),
            "entry_zone": "AI unavailable; use rule system and live K-lines only.",
            "stop_zone": "Define manually before acting.",
            "target_zone": "Define manually before acting.",
            "risk_reward": "unavailable",
            "position_size_hint": "manual sizing only",
            "why_now": [candidate.get("trigger_summary") or "Rule candidate was shortlisted."],
            "risk_flags": candidate.get("hard_veto", {}).get("reasons", [])[:5] or ["AI unavailable"],
            "hard_veto_applied": bool(candidate.get("hard_veto", {}).get("active")),
            "ai_action_validation": candidate.get("ai_action_validation_baseline", {}),
            "money_pilot_eligibility": candidate.get("money_pilot_eligibility_baseline", {}),
            "probe_eligibility": candidate.get("probe_eligibility_baseline", {}),
            "probe_risk_policy": probe_risk_policy(),
            "probe_blockers": (candidate.get("probe_eligibility_baseline") or {}).get("blockers", ["AI unavailable"]),
            "ai_feature_packet_version": "ai_feature_packet_v2",
        }
        if item["action"] == "AI_WAIT":
            watch.append(item)
        else:
            avoid.append(item)
    fallback_report = {
        "top_buy_candidates": [],
        "probe_candidates": [],
        "watch_for_pullback": watch,
        "avoid_or_risk_elevated": avoid,
        "mstr_cycle_update": "AI unavailable; review MSTR Cycle Radar manually.",
        "data_quality_warnings": [reason],
        "daily_summary": "AI Daily Agent is unavailable. Rule shortlist is shown without AI-led ranking.",
    }
    fallback_report["validation_by_ai_action"] = summarize_ai_report_action_validation(fallback_report)
    return fallback_report


def summarize_ai_report_action_validation(ai_report: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for section in ("top_buy_candidates", "probe_candidates", "watch_for_pullback", "avoid_or_risk_elevated"):
        for item in ai_report.get(section, []) or []:
            if not isinstance(item, dict):
                continue
            validation = item.get("ai_action_validation")
            if not isinstance(validation, dict):
                continue
            buckets.setdefault(str(item.get("action") or "UNKNOWN"), []).append(validation)
    summary: dict[str, Any] = {}
    for action, validations in buckets.items():
        samples = [int(item.get("sample_count") or 0) for item in validations]
        wins = [float(item.get("win_rate") or 0) for item in validations]
        returns = [float(item.get("avg_forward_return") or 0) for item in validations]
        drawdowns = [float(item.get("avg_max_drawdown") or 0) for item in validations]
        expected_r = [float(item.get("expected_value_r") or 0) for item in validations]
        rr_values = [float(item.get("risk_reward_value") or 0) for item in validations]
        target_hits = [float(item.get("target_hit_rate") or 0) for item in validations]
        stop_hits = [float(item.get("stop_hit_rate") or 0) for item in validations]
        summary[action] = {
            "signals": len(validations),
            "total_samples": sum(samples),
            "avg_win_rate": round(sum(wins) / max(len(wins), 1), 1),
            "avg_forward_return": round(sum(returns) / max(len(returns), 1), 2),
            "avg_max_drawdown": round(sum(drawdowns) / max(len(drawdowns), 1), 2),
            "avg_expected_value_r": round(sum(expected_r) / max(len(expected_r), 1), 2),
            "avg_risk_reward": round(sum(rr_values) / max(len(rr_values), 1), 2),
            "avg_target_hit_rate": round(sum(target_hits) / max(len(target_hits), 1), 1),
            "avg_stop_hit_rate": round(sum(stop_hits) / max(len(stop_hits), 1), 1),
            "money_pilot_eligible_count": sum(1 for item in validations if item.get("money_pilot_eligible")),
            "probe_eligible_count": sum(1 for item in validations if item.get("probe_eligible")),
            "limited_evidence_count": sum(1 for item in validations if item.get("evidence_quality") != "robust"),
        }
    return summary


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
    focus_runups = [
        float((sample.get("max_runups_by_horizon") or {}).get(str(horizon)))
        for sample in samples
        if (sample.get("max_runups_by_horizon") or {}).get(str(horizon)) is not None
    ]
    target = float(profile.get("target_return_pct", 2.0))
    stop_loss = float(profile.get("stop_loss_pct", 3.5))
    if not focus_returns:
        return edge | {
            "focus_window": profile.get("focus_window", "5D"),
            "focus_horizon_bars": horizon,
            "focus_sample_count": 0,
            "focus_win_rate": 0.0,
            "focus_target_hit_rate": 0.0,
            "focus_stop_hit_rate": 0.0,
            "focus_target_before_stop_proxy": 0.0,
            "focus_expected_value_r": 0.0,
            "focus_avg_return": 0.0,
            "focus_avg_max_drawdown": 0.0,
            "profile_verdict": "limited",
            "profile_note": "Not enough historical samples for this holding-period profile.",
        }
    win_rate = sum(1 for value in focus_returns if value > 0) / len(focus_returns) * 100
    target_hit_rate = sum(1 for value in focus_returns if value >= target) / len(focus_returns) * 100
    stop_hit_rate = sum(1 for value in focus_drawdowns if value <= -stop_loss) / max(len(focus_drawdowns), 1) * 100
    target_before_stop_proxy = (
        sum(
            1
            for runup, drawdown in zip(focus_runups, focus_drawdowns)
            if runup >= target and drawdown > -stop_loss
        )
        / max(min(len(focus_runups), len(focus_drawdowns)), 1)
        * 100
    )
    avg_return = sum(focus_returns) / len(focus_returns)
    avg_drawdown = sum(focus_drawdowns) / len(focus_drawdowns) if focus_drawdowns else 0.0
    reward_r = target / max(stop_loss, 0.01)
    expected_value_r = (win_rate / 100 * reward_r) - ((100 - win_rate) / 100)
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
        "focus_stop_hit_rate": round(stop_hit_rate, 1),
        "focus_target_before_stop_proxy": round(target_before_stop_proxy, 1),
        "focus_expected_value_r": round(expected_value_r, 2),
        "focus_stop_loss_pct": round(stop_loss, 2),
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
    high_beta_growth = signal.get("profile_name") == "high_beta_growth_v1"
    clean_data = (
        data.get("data_quality") == "clean"
        and data.get("daily_provider_status") == "available"
        and data.get("hourly_provider_status") == "available"
    )
    acceptable_exit_statuses = {"CLEAR", "PULLBACK RISK"} if high_beta_growth else {"CLEAR"}
    if (
        signal.get("level") == "BUY SETUP"
        and clean_data
        and edge.get("profile_verdict", edge.get("verdict")) == "positive"
        and exit_risk.get("status") in acceptable_exit_statuses
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
    high_beta_growth = signal.get("profile_name") == "high_beta_growth_v1"
    if data.get("data_quality") != "clean":
        reasons.append("data quality is not clean")
    if data.get("daily_provider_status") != "available" or data.get("hourly_provider_status") != "available":
        reasons.append("provider degraded or using stale cache")
    if edge.get("profile_verdict", edge.get("verdict")) != "positive":
        reasons.append("profile historical edge is not positive")
    acceptable_exit_statuses = (None, "CLEAR", "PULLBACK RISK") if high_beta_growth else (None, "CLEAR")
    if exit_risk.get("status") not in acceptable_exit_statuses:
        reasons.append(f"exit risk is {exit_risk.get('status')}")
    if float(features.get("extension_pct", 0.0) or 0.0) > 8:
        reasons.append("price is extended above EMA20")
    atr_limit = 12 if high_beta_growth else 5
    if float(features.get("atr_pct", 0.0) or 0.0) > atr_limit:
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
