from __future__ import annotations

from typing import Any


CANONICAL_SCORING_CONFIG: dict[str, Any] = {
    "schema_version": "score_config_v1",
    "trend": {
        "close_above_ema20": 14.0,
        "ema20_above_ema50": 14.0,
        "ema50_above_ema200": 14.0,
        "return_multiplier": 2.2,
        "return_min": -8.0,
        "return_max": 18.0,
        "score_max": 52.0,
    },
    "trigger": {
        "close_above_ema20": 12.0,
        "ema20_above_ema50": 7.0,
        "momentum_multiplier": 3.0,
        "momentum_min": -8.0,
        "momentum_max": 11.0,
        "score_max": 30.0,
    },
    "volume": {"baseline": 0.75, "multiplier": 18.0, "score_max": 18.0},
    "risk": {
        "starting_score": 18.0,
        "atr_threshold": 5.0,
        "atr_multiplier": 1.4,
        "atr_deduction_max": 8.0,
        "extension_high_threshold": 7.0,
        "extension_high_multiplier": 1.0,
        "extension_high_deduction_max": 7.0,
        "extension_low_threshold": -2.0,
        "extension_low_multiplier": 0.8,
        "extension_low_deduction_max": 5.0,
        "score_max": 18.0,
    },
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def calculate_score_components(
    config: dict[str, Any],
    *,
    close: float,
    ema20: float,
    ema50: float,
    ema200: float,
    hourly_close: float,
    hourly_ema20: float,
    hourly_ema50: float,
    trend_return_pct: float,
    hourly_momentum_pct: float,
    volume_ratio: float,
    atr_pct: float,
    extension_pct: float,
) -> dict[str, Any]:
    trend = dict(config["trend"])
    trigger = dict(config["trigger"])
    volume = dict(config["volume"])
    risk = dict(config["risk"])
    trend_factors = {
        "close_above_ema20": trend["close_above_ema20"] if close > ema20 else 0.0,
        "ema20_above_ema50": trend["ema20_above_ema50"] if ema20 > ema50 else 0.0,
        "ema50_above_ema200": trend["ema50_above_ema200"] if ema50 > ema200 else 0.0,
        "trend_return": _clamp(trend_return_pct * trend["return_multiplier"], trend["return_min"], trend["return_max"]),
    }
    trend_score = _clamp(sum(trend_factors.values()), 0.0, trend["score_max"])
    trigger_factors = {
        "close_above_hourly_ema20": trigger["close_above_ema20"] if hourly_close > hourly_ema20 else 0.0,
        "hourly_ema20_above_ema50": trigger["ema20_above_ema50"] if hourly_ema20 > hourly_ema50 else 0.0,
        "hourly_momentum": _clamp(hourly_momentum_pct * trigger["momentum_multiplier"], trigger["momentum_min"], trigger["momentum_max"]),
    }
    trigger_score = _clamp(sum(trigger_factors.values()), 0.0, trigger["score_max"])
    volume_score = _clamp((volume_ratio - volume["baseline"]) * volume["multiplier"], 0.0, volume["score_max"])
    deductions = {
        "atr": min(risk["atr_deduction_max"], max(0.0, atr_pct - risk["atr_threshold"]) * risk["atr_multiplier"]),
        "extension_high": min(risk["extension_high_deduction_max"], max(0.0, extension_pct - risk["extension_high_threshold"]) * risk["extension_high_multiplier"]),
        "extension_low": min(risk["extension_low_deduction_max"], abs(extension_pct) * risk["extension_low_multiplier"]) if extension_pct < risk["extension_low_threshold"] else 0.0,
    }
    risk_score = _clamp(risk["starting_score"] - sum(deductions.values()), 0.0, risk["score_max"])
    total = _clamp(trend_score + trigger_score + volume_score + risk_score, 0.0, 100.0)
    return {
        "scoring_config_version": config["schema_version"],
        "factors": {"trend": trend_factors, "trigger": trigger_factors, "volume_ratio": volume_ratio},
        "deductions": deductions,
        "trend_score": trend_score,
        "trigger_score": trigger_score,
        "volume_score": volume_score,
        "risk_score": risk_score,
        "total_score": round(total, 1),
    }
