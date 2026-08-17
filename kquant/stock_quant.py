from __future__ import annotations

"""Point-in-time Stock Quant Model 0 contracts.

This module is deliberately independent from the dashboard and from the
legacy ``historical_edge`` summaries.  The same pure functions are used by
the live analysis adapter and by historical dataset builders, so a future
bar cannot silently change an earlier feature snapshot.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .quant_dataset import build_quant_dataset, read_quant_dataset
from .scoring import CANONICAL_SCORING_CONFIG, calculate_score_components
from .stock_store import connect
from .technical_features import calculate_feature_snapshot, ema_last


MODEL_0_VERSION = "stock_quant_model_0_v1.0.0"
STOCK_QUANT_DATASET_CONTRACT_VERSION = "stock_quant_dataset_v1.0.0"
STOCK_QUANT_FEATURE_SCHEMA_VERSION = "stock_quant_features_v1.0.0"
STOCK_QUANT_LABEL_SCHEMA_VERSION = "stock_quant_labels_v1.0.0"
STOCK_QUANT_EXECUTION_VERSION = "next_bar_open_stop_first_v1"
DEFAULT_HORIZON_BARS = 5
DEFAULT_COMMISSION_BPS_PER_SIDE = 1.0
DEFAULT_SLIPPAGE_BPS_PER_SIDE = 5.0


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _time(value: Any, *, field: str = "time") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required.")
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _bar_time(bar: dict[str, Any]) -> datetime:
    return _time(bar.get("open_time"), field="bar.open_time")


def _closed_bars(bars: Iterable[dict[str, Any]], as_of: datetime | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in bars:
        if str(raw.get("bar_state") or "").lower() == "forming_candle":
            continue
        try:
            stamp = _bar_time(raw)
        except ValueError:
            continue
        if as_of is not None and stamp > as_of:
            continue
        if all((_number(raw.get(key)) or 0.0) > 0 for key in ("open", "high", "low", "close")):
            rows.append(dict(raw))
    return sorted(rows, key=lambda row: _bar_time(row))


def _close_return(bars: list[dict[str, Any]], periods: int) -> float | None:
    if len(bars) <= periods:
        return None
    current = _number(bars[-1].get("close"))
    previous = _number(bars[-1 - periods].get("close"))
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def _prior_return(bars: list[dict[str, Any]], periods: int) -> float | None:
    if len(bars) <= periods * 2:
        return None
    end = bars[-1 - periods]
    start = bars[-1 - periods * 2]
    current = _number(end.get("close"))
    previous = _number(start.get("close"))
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1.0) * 100.0


def _pct(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return (value / reference - 1.0) * 100.0


def _context_value(context: dict[str, Any] | None, key: str, as_of: datetime) -> tuple[float | None, str, str]:
    if not context:
        return None, "", "missing"
    raw_as_of = context.get("as_of_time") or context.get("as_of")
    if not raw_as_of:
        return None, str(context.get("source") or ""), "missing_as_of"
    try:
        context_time = _time(raw_as_of, field="context.as_of_time")
    except ValueError:
        return None, str(context.get("source") or ""), "invalid_as_of"
    if context_time > as_of:
        return None, str(context.get("source") or ""), "future_context"
    values = context.get("values") if isinstance(context.get("values"), dict) else context
    return _number(values.get(key)), str(context.get("source") or ""), "available"


MODEL_0_FACTOR_DEFINITIONS: dict[str, dict[str, str]] = {
    "trend.price_vs_ema20_pct": {"group": "trend", "formula": "close / EMA20 - 1"},
    "trend.price_vs_ema50_pct": {"group": "trend", "formula": "close / EMA50 - 1"},
    "trend.price_vs_ema200_pct": {"group": "trend", "formula": "close / EMA200 - 1"},
    "trend.ema20_slope_20d_pct": {"group": "trend", "formula": "EMA20 now / EMA20 20 completed bars ago - 1"},
    "trend.ema_alignment": {"group": "trend", "formula": "1 when EMA20 > EMA50 > EMA200, else 0"},
    "relative.spy_5d_excess_pct": {"group": "relative_strength", "formula": "stock 5D return minus SPY 5D return"},
    "relative.qqq_5d_excess_pct": {"group": "relative_strength", "formula": "stock 5D return minus QQQ 5D return"},
    "relative.strength_acceleration_pct": {"group": "relative_strength", "formula": "current 5D return minus prior 5D return"},
    "momentum.return_5d_pct": {"group": "momentum", "formula": "close / close 5 completed bars ago - 1"},
    "momentum.return_20d_pct": {"group": "momentum", "formula": "close / close 20 completed bars ago - 1"},
    "momentum.pullback_from_20d_high_pct": {"group": "momentum", "formula": "close / prior 20-bar high - 1"},
    "volume.volume_ratio_20": {"group": "volume", "formula": "latest volume / preceding 20-bar average"},
    "volume.up_down_volume_ratio_20": {"group": "volume", "formula": "up-volume / down-volume over the last 20 completed bars"},
    "risk.atr_pct_20": {"group": "risk", "formula": "20-bar mean true range / close"},
    "risk.extension_from_ema20_pct": {"group": "risk", "formula": "close / EMA20 - 1"},
    "risk.gap_risk_pct": {"group": "risk", "formula": "absolute latest open / prior close - 1"},
    "theme.relative_strength": {"group": "theme", "formula": "point-in-time theme relative-strength context"},
    "theme.rotation_score": {"group": "theme", "formula": "point-in-time Capital Rotation score context"},
    "leadership.score": {"group": "leadership", "formula": "point-in-time Leadership score context"},
    "event.risk_flag": {"group": "event", "formula": "1 when a known point-in-time event blocks a fresh signal"},
    "event.days_to_event": {"group": "event", "formula": "point-in-time calendar days to the next known event"},
}


def _factor(
    factor_id: str,
    value: float | None,
    *,
    as_of: datetime,
    source: str,
    available: bool | None = None,
    status: str = "available",
) -> dict[str, Any]:
    definition = MODEL_0_FACTOR_DEFINITIONS[factor_id]
    return {
        "factor_id": factor_id,
        "group": definition["group"],
        "formula": definition["formula"],
        "value": round(value, 8) if value is not None else None,
        "as_of_time": _iso(as_of),
        "source": source,
        "available": bool(value is not None) if available is None else bool(available),
        "status": status if value is None else "available",
    }


def _up_down_volume_ratio(bars: list[dict[str, Any]], period: int = 20) -> float | None:
    rows = bars[-period:]
    if len(rows) < 2:
        return None
    up = 0.0
    down = 0.0
    for current, previous in zip(rows[1:], rows[:-1]):
        volume = _number(current.get("volume")) or 0.0
        current_close = _number(current.get("close")) or 0.0
        previous_close = _number(previous.get("close")) or 0.0
        if current_close >= previous_close:
            up += volume
        else:
            down += volume
    if up <= 0 and down <= 0:
        return None
    return min(up / max(down, 1.0), 100.0)


def _prior_high_distance(bars: list[dict[str, Any]], period: int = 20) -> float | None:
    if len(bars) <= period:
        return None
    close = _number(bars[-1].get("close"))
    highs = [_number(row.get("high")) for row in bars[-1 - period : -1]]
    if close is None or not highs or any(value is None for value in highs):
        return None
    return _pct(close, max(float(value) for value in highs))


def build_model0_features(
    symbol: str,
    daily_bars: Iterable[dict[str, Any]],
    confirmation_bars: Iterable[dict[str, Any]] = (),
    *,
    benchmark_bars: dict[str, Iterable[dict[str, Any]]] | None = None,
    theme_context: dict[str, Any] | None = None,
    leadership_context: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    as_of_time: str | datetime | None = None,
    source: str = "longbridge_candles",
    confirmation_timeframe: str = "1H",
    scoring_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the same point-in-time feature vector for live and replay paths."""

    requested_as_of = _time(as_of_time, field="as_of_time") if as_of_time else None
    daily = _closed_bars(daily_bars, requested_as_of)
    if not daily:
        empty_time = requested_as_of or datetime.now(UTC)
        return {
            "model_version": MODEL_0_VERSION,
            "feature_schema_version": STOCK_QUANT_FEATURE_SCHEMA_VERSION,
            "symbol": str(symbol).upper(),
            "as_of_time": _iso(empty_time),
            "feature_available_at": None,
            "signal_time": None,
            "confirmation_timeframe": confirmation_timeframe,
            "source": source,
            "values": {},
            "factors": [],
            "score": None,
            "data_quality": "unavailable",
            "eligibility": {"eligible": False, "reasons": ["No completed daily bars."], "minimum_daily_bars": 200, "minimum_confirmation_bars": 20},
            "feature_snapshot_hash": _hash({"model_version": MODEL_0_VERSION, "symbol": str(symbol).upper(), "status": "unavailable"}),
            "read_only_research": True,
        }

    signal_time = _bar_time(daily[-1])
    effective_as_of = min(signal_time, requested_as_of) if requested_as_of else signal_time
    confirmation = _closed_bars(confirmation_bars, effective_as_of)
    daily_features = calculate_feature_snapshot(daily, timeframe="1D")
    confirmation_features = calculate_feature_snapshot(
        confirmation,
        timeframe=confirmation_timeframe,
        ema_periods=(8, 9, 20, 50),
        momentum_period=7,
    )
    values_daily = daily_features["values"]
    values_confirmation = confirmation_features["values"]
    close = _number(daily[-1].get("close"))
    ema20 = _number(values_daily.get("ema_20"))
    ema50 = _number(values_daily.get("ema_50"))
    ema200 = _number(values_daily.get("ema_200"))
    ema20_ago = None
    if len(daily) > 20:
        historical_closes = [_number(row.get("close")) for row in daily[:-20]]
        if all(value is not None for value in historical_closes):
            ema20_ago = ema_last([float(value) for value in historical_closes], 20)
    stock_return_5d = _close_return(daily, 5)
    stock_return_20d = _close_return(daily, 20)
    prior_return_5d = _prior_return(daily, 5)
    benchmark_values: dict[str, float | None] = {}
    for benchmark, rows in (benchmark_bars or {}).items():
        benchmark_rows = _closed_bars(rows, effective_as_of)
        benchmark_values[benchmark.upper()] = _close_return(benchmark_rows, 5)
    spy_return = benchmark_values.get("SPY")
    qqq_return = benchmark_values.get("QQQ")
    daily_latest = signal_time
    feature_values: dict[str, float | None] = {
        "trend_price_vs_ema20_pct": _pct(close, ema20),
        "trend_price_vs_ema50_pct": _pct(close, ema50),
        "trend_price_vs_ema200_pct": _pct(close, ema200),
        "trend_ema20_slope_20d_pct": _pct(ema20, ema20_ago),
        "trend_ema_alignment": 1.0 if close and ema20 and ema50 and ema200 and close > ema20 > ema50 > ema200 else 0.0,
        "relative_spy_5d_excess_pct": stock_return_5d - spy_return if stock_return_5d is not None and spy_return is not None else None,
        "relative_qqq_5d_excess_pct": stock_return_5d - qqq_return if stock_return_5d is not None and qqq_return is not None else None,
        "relative_strength_acceleration_pct": stock_return_5d - prior_return_5d if stock_return_5d is not None and prior_return_5d is not None else None,
        "momentum_return_5d_pct": stock_return_5d,
        "momentum_return_20d_pct": stock_return_20d,
        "momentum_pullback_from_20d_high_pct": _prior_high_distance(daily),
        "volume_volume_ratio_20": _number(values_daily.get("volume_ratio_20")),
        "volume_up_down_volume_ratio_20": _up_down_volume_ratio(daily),
        "risk_atr_pct_20": _number(values_daily.get("atr_pct")),
        "risk_extension_from_ema20_pct": _pct(close, ema20),
        "risk_gap_risk_pct": _number(values_daily.get("gap_risk_pct")),
    }
    theme_relative, theme_source, theme_status = _context_value(theme_context, "relative_strength", effective_as_of)
    theme_score, _, theme_score_status = _context_value(theme_context, "rotation_score", effective_as_of)
    leadership_score, leadership_source, leadership_status = _context_value(leadership_context, "score", effective_as_of)
    risk_flag, event_source, event_status = _context_value(event_context, "risk_flag", effective_as_of)
    days_to_event, _, days_status = _context_value(event_context, "days_to_event", effective_as_of)
    feature_values.update(
        {
            "theme_relative_strength": theme_relative,
            "theme_rotation_score": theme_score,
            "leadership_score": leadership_score,
            "event_risk_flag": risk_flag,
            "event_days_to_event": days_to_event,
        }
    )

    factor_specs = [
        ("trend.price_vs_ema20_pct", feature_values["trend_price_vs_ema20_pct"], daily_latest, source, "available"),
        ("trend.price_vs_ema50_pct", feature_values["trend_price_vs_ema50_pct"], daily_latest, source, "available"),
        ("trend.price_vs_ema200_pct", feature_values["trend_price_vs_ema200_pct"], daily_latest, source, "available"),
        ("trend.ema20_slope_20d_pct", feature_values["trend_ema20_slope_20d_pct"], daily_latest, source, "available"),
        ("trend.ema_alignment", feature_values["trend_ema_alignment"], daily_latest, source, "available"),
        ("relative.spy_5d_excess_pct", feature_values["relative_spy_5d_excess_pct"], daily_latest, source, "available" if spy_return is not None else "benchmark_missing"),
        ("relative.qqq_5d_excess_pct", feature_values["relative_qqq_5d_excess_pct"], daily_latest, source, "available" if qqq_return is not None else "benchmark_missing"),
        ("relative.strength_acceleration_pct", feature_values["relative_strength_acceleration_pct"], daily_latest, source, "available"),
        ("momentum.return_5d_pct", feature_values["momentum_return_5d_pct"], daily_latest, source, "available"),
        ("momentum.return_20d_pct", feature_values["momentum_return_20d_pct"], daily_latest, source, "available"),
        ("momentum.pullback_from_20d_high_pct", feature_values["momentum_pullback_from_20d_high_pct"], daily_latest, source, "available"),
        ("volume.volume_ratio_20", feature_values["volume_volume_ratio_20"], daily_latest, source, "available"),
        ("volume.up_down_volume_ratio_20", feature_values["volume_up_down_volume_ratio_20"], daily_latest, source, "available"),
        ("risk.atr_pct_20", feature_values["risk_atr_pct_20"], daily_latest, source, "available"),
        ("risk.extension_from_ema20_pct", feature_values["risk_extension_from_ema20_pct"], daily_latest, source, "available"),
        ("risk.gap_risk_pct", feature_values["risk_gap_risk_pct"], daily_latest, source, "available"),
        ("theme.relative_strength", theme_relative, effective_as_of, theme_source, theme_status),
        ("theme.rotation_score", theme_score, effective_as_of, theme_source, theme_score_status),
        ("leadership.score", leadership_score, effective_as_of, leadership_source, leadership_status),
        ("event.risk_flag", risk_flag, effective_as_of, event_source, event_status),
        ("event.days_to_event", days_to_event, effective_as_of, event_source, days_status),
    ]
    factors = [_factor(factor_id, value, as_of=stamp, source=factor_source, status=status) for factor_id, value, stamp, factor_source, status in factor_specs]

    score: dict[str, Any] | None = None
    close_confirmation = _number(confirmation[-1].get("close")) if confirmation else None
    confirmation_ema20 = _number(values_confirmation.get("ema_20"))
    confirmation_ema50 = _number(values_confirmation.get("ema_50"))
    confirmation_momentum = _number(values_confirmation.get("momentum_pct"))
    volume_ratio = _number(values_daily.get("volume_ratio_20"))
    atr_value = _number(values_daily.get("atr_pct"))
    extension = _pct(close, ema20)
    if None not in {close, ema20, ema50, ema200, close_confirmation, confirmation_ema20, confirmation_ema50, confirmation_momentum, volume_ratio, atr_value, extension}:
        score = calculate_score_components(
            dict(scoring_config or CANONICAL_SCORING_CONFIG),
            close=float(close), ema20=float(ema20), ema50=float(ema50), ema200=float(ema200),
            hourly_close=float(close_confirmation), hourly_ema20=float(confirmation_ema20), hourly_ema50=float(confirmation_ema50),
            trend_return_pct=float(stock_return_5d or 0.0), hourly_momentum_pct=float(confirmation_momentum),
            volume_ratio=float(volume_ratio), atr_pct=float(atr_value), extension_pct=float(extension),
        )

    feature_values.update(
        {
            "model0_trend_score": score.get("trend_score") if score else None,
            "model0_trigger_score": score.get("trigger_score") if score else None,
            "model0_volume_score": score.get("volume_score") if score else None,
            "model0_risk_score": score.get("risk_score") if score else None,
            "model0_total_score": score.get("total_score") if score else None,
        }
    )
    reasons: list[str] = []
    if len(daily) < 200:
        reasons.append("Daily history is below the 200-bar Model 0 minimum.")
    if len(confirmation) < 20:
        reasons.append(f"{confirmation_timeframe} confirmation history is below the 20-bar minimum.")
    if source in {"yahoo_public_fallback", "live_yahoo_chart", "stale_yahoo_chart_cache"}:
        reasons.append("Reference data is not eligible for the Model 0 dataset.")
    if any(item[4] in {"future_context", "invalid_as_of"} for item in factor_specs):
        reasons.append("A context input is not point-in-time valid.")
    eligibility = {"eligible": not reasons and score is not None, "reasons": reasons, "minimum_daily_bars": 200, "minimum_confirmation_bars": 20}
    latest_confirmation = _bar_time(confirmation[-1]) if confirmation else None
    feature_available_at = max([stamp for stamp in (signal_time, latest_confirmation) if stamp is not None])
    hash_payload = {
        "model_version": MODEL_0_VERSION,
        "feature_schema_version": STOCK_QUANT_FEATURE_SCHEMA_VERSION,
        "symbol": str(symbol).upper(),
        "signal_time": _iso(signal_time),
        "feature_available_at": _iso(feature_available_at),
        "confirmation_timeframe": confirmation_timeframe,
        "source": source,
        "values": feature_values,
        "factors": factors,
        "score": score,
        "eligibility": eligibility,
    }
    return {
        "model_version": MODEL_0_VERSION,
        "feature_schema_version": STOCK_QUANT_FEATURE_SCHEMA_VERSION,
        "symbol": str(symbol).upper(),
        "as_of_time": _iso(effective_as_of),
        "feature_available_at": _iso(feature_available_at),
        "signal_time": _iso(signal_time),
        "confirmation_timeframe": confirmation_timeframe,
        "source": source,
        "values": feature_values,
        "factors": factors,
        "score": score,
        "data_quality": "available" if not reasons else "caution",
        "eligibility": eligibility,
        "feature_snapshot_hash": _hash(hash_payload),
        "technical_feature_contract": daily_features.get("contract_version"),
        "confirmation_feature_contract": confirmation_features.get("contract_version"),
        "read_only_research": True,
    }


def build_model0_label(
    candles: Iterable[dict[str, Any]],
    signal_index: int,
    stop_price: float,
    target_price: float,
    horizon_bars: int = DEFAULT_HORIZON_BARS,
    *,
    commission_bps_per_side: float = DEFAULT_COMMISSION_BPS_PER_SIDE,
    slippage_bps_per_side: float = DEFAULT_SLIPPAGE_BPS_PER_SIDE,
    same_bar_policy: str = "stop_first",
) -> dict[str, Any]:
    """Create a forward label using next-bar-open execution and conservative fills."""

    rows = _closed_bars(candles)
    entry_index = int(signal_index) + 1
    if entry_index >= len(rows):
        return {"completed": False, "outcome": "insufficient_future_bars", "label_schema_version": STOCK_QUANT_LABEL_SCHEMA_VERSION}
    raw_entry = _number(rows[entry_index].get("open")) or 0.0
    stop = float(stop_price)
    target = float(target_price)
    slip = float(slippage_bps_per_side) / 10_000
    commission = float(commission_bps_per_side) / 10_000
    entry_price = raw_entry * (1 + slip)
    risk_per_share = entry_price - stop
    if entry_price <= 0 or risk_per_share <= 0 or target <= entry_price:
        return {"completed": False, "outcome": "invalid_trade_plan", "label_schema_version": STOCK_QUANT_LABEL_SCHEMA_VERSION}
    end_index = min(len(rows) - 1, entry_index + max(1, int(horizon_bars)) - 1)
    max_drawdown_pct = 0.0
    max_runup_pct = 0.0
    exit_price = (_number(rows[end_index].get("close")) or raw_entry) * (1 - slip)
    exit_index = end_index
    outcome = "time_exit"
    target_first = False
    stop_first = False
    for index in range(entry_index, end_index + 1):
        bar = rows[index]
        bar_open = _number(bar.get("open")) or 0.0
        bar_high = _number(bar.get("high")) or 0.0
        bar_low = _number(bar.get("low")) or 0.0
        max_drawdown_pct = min(max_drawdown_pct, (bar_low / entry_price - 1) * 100)
        max_runup_pct = max(max_runup_pct, (bar_high / entry_price - 1) * 100)
        if bar_open <= stop:
            exit_price = bar_open * (1 - slip)
            exit_index, outcome, stop_first = index, "gap_stop", True
            break
        if bar_open >= target:
            exit_price = bar_open * (1 - slip)
            exit_index, outcome, target_first = index, "gap_target", True
            break
        hit_stop = bar_low <= stop
        hit_target = bar_high >= target
        if hit_stop and hit_target:
            if same_bar_policy != "stop_first":
                raise ValueError("Only stop_first same-bar handling is supported.")
            exit_price = stop * (1 - slip)
            exit_index, outcome, stop_first = index, "same_bar_stop_first", True
            break
        if hit_stop:
            exit_price = stop * (1 - slip)
            exit_index, outcome, stop_first = index, "stop", True
            break
        if hit_target:
            exit_price = target * (1 - slip)
            exit_index, outcome, target_first = index, "target", True
            break
    round_trip_cost = (entry_price + exit_price) * commission
    realized_r = (exit_price - entry_price - round_trip_cost) / risk_per_share
    raw_exit = _number(rows[exit_index].get("close")) or exit_price
    forward_return_gross = (raw_exit / raw_entry - 1) * 100 if raw_entry > 0 else 0.0
    forward_return_net = (exit_price / entry_price - 1) * 100
    return {
        "completed": True,
        "label_schema_version": STOCK_QUANT_LABEL_SCHEMA_VERSION,
        "execution_version": STOCK_QUANT_EXECUTION_VERSION,
        "signal_index": int(signal_index),
        "entry_index": entry_index,
        "exit_index": exit_index,
        "entry_time": _iso(_bar_time(rows[entry_index])),
        "exit_time": _iso(_bar_time(rows[exit_index])),
        "label_end_time": _iso(_bar_time(rows[exit_index])),
        "entry_price": round(entry_price, 8),
        "exit_price": round(exit_price, 8),
        "stop_price": round(stop, 8),
        "target_price": round(target, 8),
        "horizon_bars": max(1, int(horizon_bars)),
        "forward_return_gross_pct": round(forward_return_gross, 8),
        "forward_return_pct": round(forward_return_net, 8),
        "max_run_up_pct": round(max_runup_pct, 8),
        "max_drawdown_pct": round(max_drawdown_pct, 8),
        "realized_r": round(realized_r, 8),
        "target": 1.0 if realized_r > 0 else 0.0,
        "outcome": outcome,
        "target_first": target_first,
        "stop_first": stop_first,
        "commission_bps_per_side": float(commission_bps_per_side),
        "slippage_bps_per_side": float(slippage_bps_per_side),
        "same_bar_policy": same_bar_policy,
    }


def build_stock_quant_item(
    symbol: str,
    daily_bars: list[dict[str, Any]],
    confirmation_bars: list[dict[str, Any]],
    *,
    signal_index: int,
    stop_price: float,
    target_price: float,
    source_snapshot_id: str,
    benchmark_bars: dict[str, Iterable[dict[str, Any]]] | None = None,
    theme_context: dict[str, Any] | None = None,
    leadership_context: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    horizon_bars: int = DEFAULT_HORIZON_BARS,
) -> dict[str, Any]:
    rows = _closed_bars(daily_bars)
    if signal_index < 0 or signal_index >= len(rows):
        raise ValueError("signal_index is outside the completed daily-bar range.")
    snapshot = build_model0_features(
        symbol,
        rows[: signal_index + 1],
        confirmation_bars,
        benchmark_bars=benchmark_bars,
        theme_context=theme_context,
        leadership_context=leadership_context,
        event_context=event_context,
        as_of_time=_bar_time(rows[signal_index]),
    )
    label = build_model0_label(rows, signal_index, stop_price, target_price, horizon_bars)
    if not label.get("completed"):
        raise ValueError(f"Cannot build completed stock quant item: {label.get('outcome')}")
    features = {str(key): value for key, value in snapshot["values"].items()}
    return {
        "item_id": f"{str(symbol).upper()}-{snapshot['signal_time']}",
        "symbol": str(symbol).upper(),
        "signal_time": snapshot["signal_time"],
        "feature_available_at": snapshot["feature_available_at"],
        "label_end_time": label["label_end_time"],
        "source_snapshot_id": source_snapshot_id,
        "features": features,
        "label": label,
        "feature_snapshot": snapshot,
        "model_version": MODEL_0_VERSION,
    }


def build_stock_quant_dataset(
    db_path: Path,
    items: Iterable[dict[str, Any]],
    *,
    dataset_id: str | None = None,
    universe_registry_id: str = "",
    source_policy_version: str = "longbridge_pit_stock_quant_v1",
    embargo_days: int = 5,
) -> dict[str, Any]:
    """Seal Model 0 items in the generic dataset plus a stock-specific audit run."""

    rows = [dict(item) for item in items]
    if not rows:
        raise ValueError("At least one stock quant item is required.")
    dataset = build_quant_dataset(
        db_path,
        rows,
        dataset_id=dataset_id,
        universe_registry_id=universe_registry_id,
        source_policy_version=source_policy_version,
        embargo_days=embargo_days,
        contract_version=STOCK_QUANT_DATASET_CONTRACT_VERSION,
        feature_schema_version=STOCK_QUANT_FEATURE_SCHEMA_VERSION,
        label_schema_version=STOCK_QUANT_LABEL_SCHEMA_VERSION,
    )
    run_hash = _hash({"model_version": MODEL_0_VERSION, "dataset_id": dataset["dataset_id"], "content_hash": dataset["content_hash"]})
    run_id = f"sqr_{run_hash[:24]}"
    created_at = datetime.now(UTC).isoformat()
    original_by_item = {str(item["item_id"]): item for item in rows}
    with connect(db_path) as conn:
        existing = conn.execute("SELECT content_hash FROM stock_quant_runs WHERE run_id = ?", (run_id,)).fetchone()
        if existing and str(existing["content_hash"]) != run_hash:
            raise ValueError("Stock quant run id already exists with a different content hash.")
        conn.execute(
            """
            INSERT OR IGNORE INTO stock_quant_runs(
              run_id, dataset_id, model_version, feature_schema_version,
              label_schema_version, strategy_version, config_json,
              content_hash, status, read_only_research, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sealed', 1, ?)
            """,
            (run_id, dataset["dataset_id"], MODEL_0_VERSION, STOCK_QUANT_FEATURE_SCHEMA_VERSION,
             STOCK_QUANT_LABEL_SCHEMA_VERSION, "swing_long_v1.1.0", _canonical({"execution_version": STOCK_QUANT_EXECUTION_VERSION, "embargo_days": embargo_days}), run_hash, created_at),
        )
        for item in dataset["items"]:
            item_id = str(item["item_id"])
            original = original_by_item.get(item_id, item)
            feature_snapshot = original.get("feature_snapshot") if isinstance(original.get("feature_snapshot"), dict) else {}
            label = original.get("label") if isinstance(original.get("label"), dict) else item.get("label", {})
            conn.execute(
                """
                INSERT OR IGNORE INTO stock_quant_feature_snapshots(
                  run_id, item_id, symbol, signal_time, feature_available_at,
                  feature_snapshot_hash, source_snapshot_id, feature_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, item_id, item["symbol"], item["signal_time"], item["feature_available_at"],
                 str(feature_snapshot.get("feature_snapshot_hash") or _hash(item["features"])), item["source_snapshot_id"], _canonical(feature_snapshot or item["features"]), created_at),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO stock_quant_labels(
                  run_id, item_id, symbol, entry_time, exit_time, entry_price,
                  exit_price, stop_price, target_price, horizon_bars,
                  forward_return_pct, max_run_up_pct, max_drawdown_pct,
                  realized_r, target_first, stop_first, outcome, label_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, item_id, item["symbol"], label.get("entry_time"), label.get("exit_time"), label.get("entry_price"),
                 label.get("exit_price"), label.get("stop_price"), label.get("target_price"), label.get("horizon_bars"),
                 label.get("forward_return_pct"), label.get("max_run_up_pct"), label.get("max_drawdown_pct"), label.get("realized_r"),
                 int(bool(label.get("target_first"))), int(bool(label.get("stop_first"))), label.get("outcome", ""), _canonical(label), created_at),
            )
        conn.commit()
    return stock_quant_run_detail(db_path, run_id)


def stock_quant_run_detail(db_path: Path, run_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM stock_quant_runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"Unknown stock quant run: {run_id}")
        feature_count = conn.execute("SELECT COUNT(*) AS count FROM stock_quant_feature_snapshots WHERE run_id = ?", (run_id,)).fetchone()["count"]
        label_count = conn.execute("SELECT COUNT(*) AS count FROM stock_quant_labels WHERE run_id = ?", (run_id,)).fetchone()["count"]
    return {**dict(run), "config": json.loads(run["config_json"]), "feature_count": int(feature_count), "label_count": int(label_count), "read_only_research": True}


def latest_stock_quant_run(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT run_id FROM stock_quant_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return {"status": "not_materialized", "runs": [], "read_only_research": True}
    detail = stock_quant_run_detail(db_path, str(row["run_id"]))
    return {"status": "materialized", "run": detail, "read_only_research": True}


def stock_quant_ranking(db_path: Path, limit: int = 50) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM stock_quant_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if run is None:
            return {"status": "not_materialized", "ranking": [], "read_only_research": True}
        rows = conn.execute(
            "SELECT symbol, signal_time, feature_snapshot_hash, feature_json, source_snapshot_id FROM stock_quant_feature_snapshots WHERE run_id = ?",
            (run["run_id"],),
        ).fetchall()
    ranking = []
    for row in rows:
        payload = json.loads(row["feature_json"])
        values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
        ranking.append({"symbol": row["symbol"], "signal_time": row["signal_time"], "model0_score": values.get("model0_total_score"), "feature_snapshot_hash": row["feature_snapshot_hash"], "source_snapshot_id": row["source_snapshot_id"]})
    ranking.sort(key=lambda item: (float(item["model0_score"] or -1), item["symbol"]), reverse=True)
    return {"status": "materialized", "run_id": run["run_id"], "model_version": run["model_version"], "ranking": ranking[: max(1, min(int(limit), 200))], "read_only_research": True}


def stock_quant_symbol_detail(db_path: Path, symbol: str) -> dict[str, Any]:
    normalized = str(symbol or "").upper().strip()
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM stock_quant_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if run is None:
            return {"status": "not_materialized", "symbol": normalized, "read_only_research": True}
        row = conn.execute(
            "SELECT * FROM stock_quant_feature_snapshots WHERE run_id = ? AND symbol = ? ORDER BY signal_time DESC LIMIT 1",
            (run["run_id"], normalized),
        ).fetchone()
        label = conn.execute(
            "SELECT * FROM stock_quant_labels WHERE run_id = ? AND symbol = ? ORDER BY exit_time DESC LIMIT 1",
            (run["run_id"], normalized),
        ).fetchone()
    if row is None:
        return {"status": "not_available", "symbol": normalized, "run_id": run["run_id"], "read_only_research": True}
    return {
        "status": "available",
        "symbol": normalized,
        "run_id": run["run_id"],
        "model_version": run["model_version"],
        "feature_snapshot": json.loads(row["feature_json"]),
        "label": json.loads(label["label_json"]) if label else None,
        "read_only_research": True,
    }


__all__ = [
    "MODEL_0_VERSION",
    "STOCK_QUANT_DATASET_CONTRACT_VERSION",
    "STOCK_QUANT_FEATURE_SCHEMA_VERSION",
    "STOCK_QUANT_LABEL_SCHEMA_VERSION",
    "STOCK_QUANT_EXECUTION_VERSION",
    "MODEL_0_FACTOR_DEFINITIONS",
    "build_model0_features",
    "build_model0_label",
    "build_stock_quant_item",
    "build_stock_quant_dataset",
    "latest_stock_quant_run",
    "stock_quant_ranking",
    "stock_quant_symbol_detail",
    "stock_quant_run_detail",
]
