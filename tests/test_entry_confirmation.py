from __future__ import annotations

from kquant.entry_confirmation import analyze_hourly_confirmation
from kquant.technical_features import calculate_feature_snapshot


def _hourly_candles() -> list[dict]:
    rows = []
    for index in range(30):
        close = 100.0 + index * 0.8
        rows.append(
            {
                "open_time": f"2026-03-01T{index % 24:02d}:00:00+00:00",
                "open": close - 0.3,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1_000_000 + index * 20_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def test_hourly_confirmation_uses_only_closed_bars() -> None:
    candles = _hourly_candles()
    candles.append({**candles[-1], "open_time": "2026-03-02T06:00:00+00:00", "close": 999.0, "high": 1000.0, "bar_state": "forming_candle"})
    snapshot = calculate_feature_snapshot(candles, timeframe="1H", ema_periods=(8, 9, 20, 50), momentum_period=7)
    confirmation = analyze_hourly_confirmation(candles, snapshot, minimum_momentum_pct=0.6)

    assert confirmation["strict_confirmation"] is True
    assert confirmation["latest_close"] < 200
    assert confirmation["forming_candle_count"] == 1
    assert "forming_hourly_candles_excluded" in confirmation["reasons"]
