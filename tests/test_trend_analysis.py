from __future__ import annotations

from kquant.technical_features import calculate_feature_snapshot
from kquant.trend_analysis import analyze_daily_trend


def _trend_candles() -> list[dict]:
    rows = []
    for index in range(40):
        close = 100.0 + index
        rows.append(
            {
                "open_time": f"2026-02-{index + 1:02d}T14:30:00+00:00",
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def test_daily_trend_reports_bullish_structure_and_extension_risk() -> None:
    candles = _trend_candles()
    analysis = analyze_daily_trend(candles, calculate_feature_snapshot(candles, timeframe="1D"))

    assert analysis["direction"] == "uptrend"
    assert analysis["ema_alignment"]["bullish"] is True
    assert analysis["price_structure"]["higher_highs"] is True
    assert analysis["price_structure"]["higher_lows"] is True
    assert analysis["extension_risk"] in {"within_window", "extended", "chase_risk"}
