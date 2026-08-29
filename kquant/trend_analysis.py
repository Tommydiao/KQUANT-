from __future__ import annotations

from typing import Any


def _pct(value: float, reference: float) -> float:
    return (value / max(reference, 0.0001) - 1) * 100


def analyze_daily_trend(candles: list[dict[str, Any]], feature_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Describe daily trend structure without mutating any score or threshold."""
    completed = [item for item in candles if item.get("bar_state") != "forming_candle"]
    values = dict(feature_snapshot.get("values") or {})
    if not completed:
        return {
            "status": "unavailable",
            "direction": "unknown",
            "strength": "unknown",
            "reasons": ["no_completed_daily_candles"],
        }
    close = float(completed[-1]["close"])
    ema20 = float(values.get("ema_20") or 0)
    ema50 = float(values.get("ema_50") or 0)
    ema200 = float(values.get("ema_200") or 0)
    slope = values.get("trend_slope_pct")
    extension = values.get("distance_ema20_pct")
    atr_value = values.get("atr_pct")
    bullish_alignment = bool(close > ema20 > ema50 > ema200)
    bearish_alignment = bool(close < ema20 < ema50 < ema200)
    recent = completed[-20:]
    midpoint = max(1, len(recent) // 2)
    earlier = recent[:midpoint]
    later = recent[midpoint:]
    higher_highs = bool(earlier and later and max(float(item["high"]) for item in later) >= max(float(item["high"]) for item in earlier))
    higher_lows = bool(earlier and later and min(float(item["low"]) for item in later) >= min(float(item["low"]) for item in earlier))
    lower_highs = bool(earlier and later and max(float(item["high"]) for item in later) <= max(float(item["high"]) for item in earlier))
    lower_lows = bool(earlier and later and min(float(item["low"]) for item in later) <= min(float(item["low"]) for item in earlier))
    if bullish_alignment and higher_highs and higher_lows and slope is not None and float(slope) > 0:
        direction = "uptrend"
        strength = "strong" if float(slope) >= 3 else "moderate"
    elif bearish_alignment and lower_highs and lower_lows and slope is not None and float(slope) < 0:
        direction = "downtrend"
        strength = "strong" if float(slope) <= -3 else "moderate"
    else:
        direction = "mixed"
        strength = "weak"
    extension_value = float(extension) if extension is not None else None
    if extension_value is None:
        extension_risk = "unknown"
    elif extension_value > 7:
        extension_risk = "chase_risk"
    elif extension_value > 5.5:
        extension_risk = "extended"
    elif extension_value < -2.5:
        extension_risk = "below_trend_support"
    else:
        extension_risk = "within_window"
    macro_risks: list[str] = []
    if close <= ema200:
        macro_risks.append("below_ema200")
    if atr_value is not None and float(atr_value) > 5:
        macro_risks.append("elevated_atr")
    if extension_risk in {"chase_risk", "below_trend_support"}:
        macro_risks.append(extension_risk)
    return {
        "status": "available",
        "direction": direction,
        "strength": strength,
        "ema_alignment": {
            "bullish": bullish_alignment,
            "bearish": bearish_alignment,
            "close_vs_ema20_pct": round(_pct(close, ema20), 3) if ema20 else None,
            "ema20_vs_ema50_pct": round(_pct(ema20, ema50), 3) if ema50 else None,
            "ema50_vs_ema200_pct": round(_pct(ema50, ema200), 3) if ema200 else None,
        },
        "price_structure": {
            "lookback_bars": len(recent),
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "lower_highs": lower_highs,
            "lower_lows": lower_lows,
        },
        "trend_slope_pct": round(float(slope), 3) if slope is not None else None,
        "extension_risk": extension_risk,
        "higher_timeframe_risks": macro_risks,
    }
