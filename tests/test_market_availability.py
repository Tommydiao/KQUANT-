from __future__ import annotations

from kquant.market_availability import candle_available_iso, candle_is_available_at


def test_daily_candle_uses_conservative_end_of_bar_availability() -> None:
    candle = {"open_time": "2026-01-02T14:30:00+00:00"}

    assert candle_available_iso(candle, "1d") == "2026-01-03T14:30:00+00:00"
    assert candle_is_available_at(candle, "1d", "2026-01-03T14:29:59+00:00") is False
    assert candle_is_available_at(candle, "1d", "2026-01-03T14:30:00+00:00") is True


def test_explicit_provider_availability_is_preserved() -> None:
    candle = {
        "open_time": "2026-01-02T14:30:00+00:00",
        "market_available_at": "2026-01-02T21:00:00+00:00",
    }

    assert candle_available_iso(candle, "1d") == "2026-01-02T21:00:00+00:00"
