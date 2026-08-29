from __future__ import annotations

from typing import Any


def analyze_confirmation(
    candles: list[dict[str, Any]],
    feature_snapshot: dict[str, Any],
    *,
    minimum_momentum_pct: float,
    timeframe: str = "1H",
) -> dict[str, Any]:
    """Audit a completed confirmation series using its actual timeframe."""
    normalized_timeframe = str(timeframe or "1H").upper()
    completed = [item for item in candles if item.get("bar_state") != "forming_candle"]
    values = dict(feature_snapshot.get("values") or {})
    forming_count = len(candles) - len(completed)
    if len(completed) < 20:
        return {
            "status": "unavailable",
            "strict_confirmation": False,
            "forming_candle_count": forming_count,
            "timeframe": normalized_timeframe,
            "reasons": ["insufficient_completed_confirmation_candles"],
        }
    close = float(completed[-1]["close"])
    high = float(completed[-1]["high"])
    low = float(completed[-1]["low"])
    ema20 = float(values.get("ema_20") or 0)
    ema50 = float(values.get("ema_50") or 0)
    momentum = values.get("momentum_pct")
    volume_ratio = values.get("volume_ratio_20")
    previous_highs = [float(item["high"]) for item in completed[-11:-1]]
    previous_close = float(completed[-2]["close"])
    strict_confirmation = bool(
        close > ema20 > ema50
        and momentum is not None
        and float(momentum) >= minimum_momentum_pct
    )
    breakout = bool(previous_highs and close > max(previous_highs))
    pullback_reclaim = bool(low <= ema20 * 1.005 and close >= ema20 and close >= previous_close)
    volume_confirmation = bool(volume_ratio is not None and float(volume_ratio) >= 1.0)
    if breakout:
        setup_mode = "breakout"
    elif pullback_reclaim:
        setup_mode = "pullback_reclaim"
    else:
        setup_mode = "continuation_or_none"
    reasons = []
    if not strict_confirmation:
        reasons.append("ema_or_momentum_confirmation_missing")
    if not volume_confirmation:
        reasons.append("confirmation_volume_not_expanding")
    if forming_count:
        reasons.append("forming_confirmation_candles_excluded")
    return {
        "status": "available",
        "timeframe": normalized_timeframe,
        "strict_confirmation": strict_confirmation,
        "setup_mode": setup_mode,
        "breakout": breakout,
        "pullback_reclaim": pullback_reclaim,
        "volume_confirmation": volume_confirmation,
        "confirmation_volume_ratio": round(float(volume_ratio), 3) if volume_ratio is not None else None,
        "momentum_pct": round(float(momentum), 3) if momentum is not None else None,
        "ema20": round(ema20, 4),
        "ema50": round(ema50, 4),
        "latest_close": close,
        "latest_high": high,
        "forming_candle_count": forming_count,
        "reasons": reasons,
    }


def analyze_hourly_confirmation(
    candles: list[dict[str, Any]],
    feature_snapshot: dict[str, Any],
    *,
    minimum_momentum_pct: float,
) -> dict[str, Any]:
    """Backward-compatible 1H wrapper for saved reports and older callers."""
    result = analyze_confirmation(
        candles,
        feature_snapshot,
        minimum_momentum_pct=minimum_momentum_pct,
        timeframe="1H",
    )
    result["hourly_volume_ratio"] = result.get("confirmation_volume_ratio")
    result["reasons"] = [
        reason.replace("confirmation", "hourly") for reason in result.get("reasons", [])
    ]
    return result
