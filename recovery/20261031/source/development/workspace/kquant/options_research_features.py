from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date, datetime
from typing import Any, Iterable

import numpy as np


FEATURE_SCHEMA_VERSION = "options_research_features_v0.1.0"
DESCRIPTIVE_STATUS = "DESCRIPTIVE_NOT_VALIDATED"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _definition(
    factor_id: str,
    family: str,
    formula: str,
    unit: str,
    lookback: str,
    sources: list[str],
    minimum: str,
    missing: str,
    hypothesis_refs: list[str],
) -> dict[str, Any]:
    payload = {
        "factor_id": factor_id,
        "version": FEATURE_SCHEMA_VERSION,
        "family": family,
        "purpose": "descriptive_research",
        "formula": formula,
        "unit": unit,
        "direction_semantics": "UNKNOWN_NOT_VALIDATED",
        "input_schema": "closed_daily_equity_bars" if family == "equity" else "option_capability_observation_v2",
        "input_sources": sources,
        "lookback": lookback,
        "minimum_input_requirements": minimum,
        "availability_rule": "all inputs must be available no later than the snapshot as-of time",
        "normalization_rule": "none",
        "missing_rule": missing,
        "adjustment_policy": "verified_consistent_adjustment_required_for_experiment; raw basis allowed only for flagged description",
        "hypothesis_refs": hypothesis_refs,
        "status": DESCRIPTIVE_STATUS,
    }
    return {**payload, "definition_hash": content_hash(payload)}


def feature_dictionary() -> list[dict[str, Any]]:
    equity_sources = ["market_candles:longbridge_candles", "stock_universe", "frozen_sector_benchmark_map"]
    option_sources = ["longbridge_option_quote", "longbridge_depth", "longbridge_calc_indexes"]
    definitions = [
        _definition("log_return_5", "equity", "ln(close_t / close_t-5)", "log_return", "5 sessions", equity_sources, "6 aligned closed sessions", "NULL_WITH_REASON", ["H-S-01"]),
        _definition("log_return_20", "equity", "ln(close_t / close_t-20)", "log_return", "20 sessions", equity_sources, "21 aligned closed sessions", "NULL_WITH_REASON", ["H-S-01", "H-M-01"]),
        _definition("log_return_60", "equity", "ln(close_t / close_t-60)", "log_return", "60 sessions", equity_sources, "61 aligned closed sessions", "NULL_WITH_REASON", ["H-M-01", "H-L-01"]),
        _definition("excess_log_return_20_market", "equity", "stock log_return_20 - fixed market benchmark log_return_20", "log_return", "20 sessions", equity_sources, "21 common sessions and frozen market benchmark", "MISSING_MARKET_BENCHMARK", ["H-S-01"]),
        _definition("excess_log_return_20_sector", "equity", "stock log_return_20 - frozen sector benchmark log_return_20", "log_return", "20 sessions", equity_sources, "21 common sessions and frozen sector benchmark", "MISSING_SECTOR_BENCHMARK", ["H-S-01"]),
        _definition("ema20_distance_atr14", "equity", "(close - EMA20) / Wilder_ATR14", "atr_units", "20/14 sessions", equity_sources, "21 closed sessions", "NULL_WITH_REASON", ["H-S-01", "H-M-01"]),
        _definition("realized_volatility_20", "equity", "sample_std(daily log returns,20) * sqrt(252)", "annualized_ratio", "20 returns", equity_sources, "21 continuous closed sessions", "NULL_WITH_REASON", ["H-S-01", "H-M-01"]),
        _definition("relative_volume_20", "equity", "current complete-session volume / mean(previous 20 complete sessions)", "ratio", "21 sessions", equity_sources, "21 complete daily volumes", "NULL_WITH_REASON", ["H-S-01"]),
        _definition("market_sector_residual_observation", "equity", "latest return residual from 60-session OLS on fixed market and sector returns", "log_return", "61 sessions", equity_sources, "61 common sessions; full-rank design", "REGRESSION_INPUT_UNAVAILABLE", ["H-S-01"]),
        _definition("log_moneyness", "option", "ln(strike / underlying spot)", "log_ratio", "snapshot", option_sources, "positive strike and spot", "NULL_WITH_REASON", ["H-S-01", "H-M-01", "H-L-01"]),
        _definition("spread_fraction", "option", "(ask-bid) / ((ask+bid)/2)", "ratio", "snapshot", option_sources, "valid non-crossed two-sided quote", "INVALID_OR_MISSING_BBO", ["H-S-01", "H-M-01", "H-L-01"]),
        _definition("displayed_extrinsic", "option", "mid - intrinsic value", "currency_per_share", "snapshot", option_sources, "standard identity, spot, strike and BBO", "NULL_WITH_REASON", ["H-S-01", "H-M-01", "H-L-01"]),
        _definition("premium_fraction_of_spot", "option", "mid / underlying spot", "ratio", "snapshot", option_sources, "positive mid and spot", "NULL_WITH_REASON", ["H-S-01", "H-M-01", "H-L-01"]),
    ]
    return definitions


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
    return current


def _wilder_atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    ranges: list[float] = []
    for index in range(1, len(bars)):
        high = _number(bars[index].get("high"))
        low = _number(bars[index].get("low"))
        previous_close = _number(bars[index - 1].get("close"))
        if high is None or low is None or previous_close is None:
            return None
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if len(ranges) < period:
        return None
    atr = sum(ranges[:period]) / period
    for value in ranges[period:]:
        atr = ((period - 1) * atr + value) / period
    return atr


def _series_by_date(bars: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["market_date"]): item for item in bars if item.get("market_date")}


def _log_return(series: dict[str, dict[str, Any]], ordered_dates: list[str], end_index: int, periods: int) -> float | None:
    if end_index < periods:
        return None
    end = _number(series[ordered_dates[end_index]].get("close"))
    start = _number(series[ordered_dates[end_index - periods]].get("close"))
    if end is None or start is None or end <= 0 or start <= 0:
        return None
    return math.log(end / start)


def _aligned_returns(
    stock: dict[str, dict[str, Any]],
    market: dict[str, dict[str, Any]],
    sector: dict[str, dict[str, Any]],
    dates: list[str],
) -> tuple[np.ndarray, np.ndarray] | None:
    common = [value for value in dates if value in stock and value in market and value in sector]
    if len(common) < 62:
        return None
    common = common[-62:]
    stock_values = np.asarray([float(stock[value]["close"]) for value in common], dtype=float)
    market_values = np.asarray([float(market[value]["close"]) for value in common], dtype=float)
    sector_values = np.asarray([float(sector[value]["close"]) for value in common], dtype=float)
    if np.any(stock_values <= 0) or np.any(market_values <= 0) or np.any(sector_values <= 0):
        return None
    y = np.diff(np.log(stock_values))
    x = np.column_stack([np.ones(len(y)), np.diff(np.log(market_values)), np.diff(np.log(sector_values))])
    if len(y) < 60 or np.linalg.matrix_rank(x[:-1]) < x.shape[1]:
        return None
    return x, y


def compute_equity_feature_snapshot(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    market_bars: list[dict[str, Any]],
    sector_bars: list[dict[str, Any]] | None,
    sector_benchmark: str | None,
    market_benchmark: str = "SPY",
) -> dict[str, Any]:
    stock = _series_by_date(bars)
    market = _series_by_date(market_bars)
    sector = _series_by_date(sector_bars or [])
    dates = sorted(stock)
    values: dict[str, float | None] = {}
    missing: dict[str, str] = {}
    flags: list[str] = []
    if not dates:
        flags.append("NO_CLOSED_DAILY_DATA")
    if any(str(item.get("adjustment_mode")) != "verified_adjusted" for item in bars):
        flags.append("UNADJUSTED_PRICE_BASIS_DESCRIPTIVE_ONLY")
    end_index = len(dates) - 1
    for periods in (5, 20, 60):
        factor_id = f"log_return_{periods}"
        values[factor_id] = _log_return(stock, dates, end_index, periods) if dates else None
        if values[factor_id] is None:
            missing[factor_id] = "INSUFFICIENT_ALIGNED_DAILY_HISTORY"
    common_market = [value for value in dates if value in market]
    if len(common_market) >= 21:
        stock_return = _log_return(stock, common_market, len(common_market) - 1, 20)
        market_return = _log_return(market, common_market, len(common_market) - 1, 20)
        values["excess_log_return_20_market"] = stock_return - market_return if stock_return is not None and market_return is not None else None
    else:
        values["excess_log_return_20_market"] = None
    if values["excess_log_return_20_market"] is None:
        missing["excess_log_return_20_market"] = "MISSING_MARKET_BENCHMARK"
    common_sector = [value for value in dates if value in sector]
    if sector_benchmark and len(common_sector) >= 21:
        stock_return = _log_return(stock, common_sector, len(common_sector) - 1, 20)
        sector_return = _log_return(sector, common_sector, len(common_sector) - 1, 20)
        values["excess_log_return_20_sector"] = stock_return - sector_return if stock_return is not None and sector_return is not None else None
    else:
        values["excess_log_return_20_sector"] = None
    if values["excess_log_return_20_sector"] is None:
        missing["excess_log_return_20_sector"] = "MISSING_SECTOR_BENCHMARK"
    ordered_bars = [stock[value] for value in dates]
    closes = [_number(item.get("close")) for item in ordered_bars]
    valid_closes = [float(value) for value in closes if value is not None]
    ema20 = _ema(valid_closes, 20) if len(valid_closes) == len(closes) else None
    atr14 = _wilder_atr(ordered_bars, 14)
    latest_close = valid_closes[-1] if valid_closes else None
    values["ema20_distance_atr14"] = (latest_close - ema20) / atr14 if latest_close is not None and ema20 is not None and atr14 and atr14 > 0 else None
    if values["ema20_distance_atr14"] is None:
        missing["ema20_distance_atr14"] = "INSUFFICIENT_OR_INVALID_OHLC_HISTORY"
    if len(valid_closes) >= 21:
        returns = [math.log(valid_closes[index] / valid_closes[index - 1]) for index in range(len(valid_closes) - 20, len(valid_closes))]
        values["realized_volatility_20"] = statistics.stdev(returns) * math.sqrt(252) if len(returns) >= 2 else None
    else:
        values["realized_volatility_20"] = None
    if values["realized_volatility_20"] is None:
        missing["realized_volatility_20"] = "INSUFFICIENT_DAILY_RETURNS"
    volumes = [_number(item.get("volume")) for item in ordered_bars]
    if len(volumes) >= 21 and all(value is not None and value >= 0 for value in volumes[-21:]):
        baseline = sum(float(value) for value in volumes[-21:-1]) / 20
        values["relative_volume_20"] = float(volumes[-1]) / baseline if baseline > 0 else None
    else:
        values["relative_volume_20"] = None
    if values["relative_volume_20"] is None:
        missing["relative_volume_20"] = "INSUFFICIENT_COMPLETE_VOLUME_HISTORY"
    regression = _aligned_returns(stock, market, sector, dates) if sector_benchmark else None
    if regression is not None:
        x, y = regression
        beta, *_ = np.linalg.lstsq(x[:-1], y[:-1], rcond=None)
        values["market_sector_residual_observation"] = float(y[-1] - x[-1] @ beta)
    else:
        values["market_sector_residual_observation"] = None
    if values["market_sector_residual_observation"] is None:
        missing["market_sector_residual_observation"] = "REGRESSION_INPUT_UNAVAILABLE"
    source_refs = sorted({str(item.get("source_ref") or "") for item in ordered_bars if item.get("source_ref")})
    max_available = max((str(item.get("available_at")) for item in ordered_bars if item.get("available_at")), default=None)
    as_of = dates[-1] if dates else None
    material = {
        "symbol": symbol,
        "as_of_market_time": as_of,
        "market_benchmark": market_benchmark,
        "sector_benchmark": sector_benchmark,
        "values": values,
        "source_refs": source_refs,
    }
    return {
        "snapshot_id": f"eqf-{content_hash(material)[:24]}",
        "schema_version": FEATURE_SCHEMA_VERSION,
        "entity_type": "UNDERLYING",
        "entity_id": symbol,
        "as_of_market_time": as_of,
        "max_input_available_at": max_available,
        "market_benchmark": market_benchmark,
        "sector_benchmark": sector_benchmark,
        "values": values,
        "missing_reasons": missing,
        "coverage_count": len(ordered_bars),
        "quality_flags": sorted(set(flags)),
        "lineage_hash": content_hash(material),
        "status": DESCRIPTIVE_STATUS,
    }


def compute_option_feature_snapshot(sample: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    spot = _number(sample.get("underlying_last"))
    strike = _number(sample.get("strike_price"))
    bid = _number(sample.get("bid"))
    ask = _number(sample.get("ask"))
    right = str(sample.get("right") or "UNKNOWN").upper()
    flags: list[str] = []
    missing: dict[str, str] = {}
    mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid and bid >= 0 else None
    if mid is None:
        flags.append("INVALID_OR_MISSING_BBO")
    values: dict[str, float | int | str | None] = {
        "underlying_spot": spot,
        "strike_price": strike,
        "right": right,
        "contract_multiplier": _number(sample.get("contract_multiplier")),
        "bid": bid,
        "ask": ask,
        "bid_size": _number(sample.get("bid_size")),
        "ask_size": _number(sample.get("ask_size")),
        "mid": mid,
        "implied_volatility_ratio": _number(sample.get("option_quote_iv_ratio")),
        "delta": _number(sample.get("delta")),
        "gamma": _number(sample.get("gamma")),
        "theta_per_day": _number(sample.get("theta_per_day")),
        "vega_per_volatility_point": (_number(sample.get("vega_raw_per_100pct_iv")) or 0.0) / 100 if _number(sample.get("vega_raw_per_100pct_iv")) is not None else None,
        "rho_per_rate_percentage_point": (_number(sample.get("rho_raw_per_100pct_rate")) or 0.0) / 100 if _number(sample.get("rho_raw_per_100pct_rate")) is not None else None,
        "open_interest": _number(sample.get("open_interest")),
        "volume": _number(sample.get("volume")),
    }
    values["log_moneyness"] = math.log(strike / spot) if strike and spot and strike > 0 and spot > 0 else None
    values["spread_fraction"] = (ask - bid) / mid if mid and bid is not None and ask is not None else None
    if spot is not None and strike is not None and right in {"CALL", "PUT"}:
        intrinsic = max(spot - strike, 0.0) if right == "CALL" else max(strike - spot, 0.0)
    else:
        intrinsic = None
    values["intrinsic_value"] = intrinsic
    values["displayed_extrinsic"] = mid - intrinsic if mid is not None and intrinsic is not None else None
    values["premium_fraction_of_spot"] = mid / spot if mid is not None and spot and spot > 0 else None
    try:
        anchor_date = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()
        expiry_date = date.fromisoformat(str(sample.get("expiry_date")))
        values["remaining_calendar_days"] = (expiry_date - anchor_date).days
    except (TypeError, ValueError):
        values["remaining_calendar_days"] = None
        missing["remaining_calendar_days"] = "EXPIRY_OR_ANCHOR_TIME_INVALID"
    for factor_id in ("log_moneyness", "spread_fraction", "displayed_extrinsic", "premium_fraction_of_spot"):
        if values.get(factor_id) is None:
            missing[factor_id] = "INPUT_UNAVAILABLE"
    if sample.get("source_bbo_time") is None:
        flags.append("SOURCE_BBO_TIME_UNKNOWN")
    if not bool(sample.get("strict_fill_eligible")):
        flags.append("STRICT_FILL_INELIGIBLE")
    material = {
        "contract_id": sample.get("contract_id"),
        "as_of": as_of,
        "values": values,
        "source_times": {
            "quote_received_at": sample.get("quote_received_at"),
            "depth_received_at": sample.get("depth_received_at"),
            "calc_received_at": sample.get("calc_received_at"),
            "source_bbo_time": sample.get("source_bbo_time"),
        },
    }
    return {
        "snapshot_id": f"opf-{content_hash(material)[:24]}",
        "schema_version": FEATURE_SCHEMA_VERSION,
        "entity_type": "OPTION_CONTRACT",
        "entity_id": str(sample.get("contract_id") or ""),
        "as_of_market_time": None,
        "max_input_available_at": max(
            (str(value) for value in (sample.get("quote_received_at"), sample.get("depth_received_at"), sample.get("calc_received_at")) if value),
            default=None,
        ),
        "observation_anchor_at": as_of,
        "values": values,
        "missing_reasons": missing,
        "coverage_count": 1,
        "quality_flags": sorted(set(flags)),
        "lineage_hash": content_hash(material),
        "status": DESCRIPTIVE_STATUS,
    }


__all__ = [
    "DESCRIPTIVE_STATUS",
    "FEATURE_SCHEMA_VERSION",
    "compute_equity_feature_snapshot",
    "compute_option_feature_snapshot",
    "content_hash",
    "feature_dictionary",
]
