from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


FEATURE_CONTRACT_VERSION = "technical_features_v1"


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    minimum_bars: int
    null_policy: str
    description: str


FEATURE_DEFINITIONS = {
    "ema": FeatureDefinition("ema", 1, "unavailable_when_empty", "Recursive EMA seeded with the first close."),
    "atr_pct": FeatureDefinition("atr_pct", 2, "unavailable_when_insufficient", "Mean true range as a percent of close."),
    "rsi_14": FeatureDefinition("rsi_14", 15, "unavailable_when_insufficient", "Wilder 14-period relative strength index."),
    "volume_ratio_20": FeatureDefinition("volume_ratio_20", 2, "unavailable_when_insufficient", "Latest volume divided by preceding up-to-20 bar mean."),
    "trend_slope_pct": FeatureDefinition("trend_slope_pct", 2, "unavailable_when_insufficient", "Close change over the configured completed-bar window."),
    "distance_ema20_pct": FeatureDefinition("distance_ema20_pct", 1, "unavailable_when_empty", "Latest close distance from EMA20."),
    "gap_risk_pct": FeatureDefinition("gap_risk_pct", 2, "unavailable_when_insufficient", "Absolute latest open-to-previous-close gap."),
}


def feature_definitions_payload() -> dict[str, dict[str, object]]:
    return {name: asdict(definition) for name, definition in FEATURE_DEFINITIONS.items()}


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _closes(candles: Iterable[dict[str, Any]]) -> list[float]:
    closes: list[float] = []
    for candle in candles:
        value = _finite_float(candle.get("close"))
        if value is None or value <= 0:
            return []
        closes.append(value)
    return closes


def ema_last(values: list[float], period: int) -> float | None:
    if not values or period <= 0:
        return None
    multiplier = 2 / (period + 1)
    current = values[0]
    for value in values[1:]:
        current = (value - current) * multiplier + current
    return current


def atr_pct(candles: list[dict[str, Any]], period: int = 20) -> float | None:
    if len(candles) < 2:
        return None
    window = candles[-max(period, 2):]
    ranges: list[float] = []
    for index in range(1, len(window)):
        current = window[index]
        previous = window[index - 1]
        high = _finite_float(current.get("high"))
        low = _finite_float(current.get("low"))
        close = _finite_float(current.get("close"))
        previous_close = _finite_float(previous.get("close"))
        if None in {high, low, close, previous_close} or close <= 0:
            return None
        true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
        ranges.append(true_range / close * 100)
    return sum(ranges) / len(ranges) if ranges else None


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100 - 100 / (1 + relative_strength)


def _pct(value: float, reference: float) -> float:
    return (value / max(reference, 0.0001) - 1) * 100


def calculate_feature_snapshot(
    candles: list[dict[str, Any]],
    *,
    timeframe: str,
    ema_periods: tuple[int, ...] = (8, 9, 20, 50, 200),
    atr_period: int = 20,
    rsi_period: int = 14,
    volume_period: int = 20,
    slope_period: int = 20,
    momentum_period: int = 5,
) -> dict[str, Any]:
    """Compute one deterministic feature contract from completed, ordered candles."""
    completed = [item for item in candles if item.get("bar_state") != "forming_candle"]
    closes = _closes(completed)
    values: dict[str, float | None] = {}
    availability: dict[str, dict[str, object]] = {}
    for period in ema_periods:
        key = f"ema_{period}"
        value = ema_last(closes, period)
        values[key] = value
        availability[key] = {"available": value is not None, "minimum_bars": 1, "input_bars": len(closes)}
    atr_value = atr_pct(completed, atr_period)
    rsi_value = rsi(closes, rsi_period)
    latest = closes[-1] if closes else None
    ema20 = values.get("ema_20")
    values["atr_pct"] = atr_value
    values["rsi_14"] = rsi_value
    values["distance_ema20_pct"] = _pct(latest, ema20) if latest is not None and ema20 else None
    values["trend_slope_pct"] = _pct(latest, closes[-1 - slope_period]) if len(closes) > slope_period and latest is not None else None
    values["momentum_pct"] = _pct(latest, closes[-1 - momentum_period]) if len(closes) > momentum_period and latest is not None else None
    volumes = [_finite_float(item.get("volume")) for item in completed]
    baseline_values = volumes[-volume_period - 1:-1]
    if len(volumes) >= 2 and volumes[-1] is not None and baseline_values and all(value is not None for value in baseline_values):
        baseline = [float(value) for value in baseline_values]
        values["volume_ratio_20"] = float(volumes[-1]) / max(sum(baseline) / len(baseline), 1.0)
    else:
        values["volume_ratio_20"] = None
    if len(completed) >= 2:
        open_price = _finite_float(completed[-1].get("open"))
        previous_close = _finite_float(completed[-2].get("close"))
        values["gap_risk_pct"] = abs(_pct(open_price, previous_close)) if open_price and previous_close else None
        values["gap_direction_pct"] = _pct(open_price, previous_close) if open_price and previous_close else None
    else:
        values["gap_risk_pct"] = None
        values["gap_direction_pct"] = None
    for name, definition in FEATURE_DEFINITIONS.items():
        availability[name] = {
            "available": values.get(name) is not None,
            "minimum_bars": definition.minimum_bars,
            "input_bars": len(completed),
            "null_policy": definition.null_policy,
        }
    return {
        "contract_version": FEATURE_CONTRACT_VERSION,
        "timeframe": timeframe,
        "completed_candle_count": len(completed),
        "values": values,
        "availability": availability,
    }
