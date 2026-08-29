from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kquant.historical_replay import slice_completed_candles_as_of
from kquant.stock_signals import reconstruct_signal


def _candles(count: int, start: datetime, step: timedelta) -> list[dict]:
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.25
        rows.append(
            {
                "open_time": (start + step * index).isoformat(),
                "open": close - 0.1,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1_000_000 + index * 10_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def _payload(candles: list[dict], interval: str) -> dict:
    return {
        "symbol": "NVDA",
        "interval": interval,
        "source_type": "longbridge_candles",
        "provider_status": "available",
        "freshness": "market_closed",
        "data_quality": {"status": "clean", "hard_veto_reasons": []},
        "candles": candles,
    }


def test_time_slice_excludes_forming_and_future_candles() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = _candles(3, start, timedelta(hours=1))
    candles[1]["bar_state"] = "forming_candle"

    sliced = slice_completed_candles_as_of(candles, start + timedelta(hours=1, minutes=30))

    assert [item["open_time"] for item in sliced] == [candles[0]["open_time"]]


def test_reconstruct_signal_is_stable_when_future_candles_change() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    daily = _candles(80, start, timedelta(days=1))
    hourly = _candles(30, start, timedelta(hours=1))
    as_of = daily[69]["open_time"]
    daily_payload = _payload(daily, "1d")
    hourly_payload = _payload(hourly, "1h")

    baseline = reconstruct_signal("NVDA", as_of, "swing_long_v1.1.0", daily_payload=daily_payload, hourly_payload=hourly_payload)
    mutated = _payload([dict(item) for item in daily], "1d")
    mutated["candles"][75].update({"open": 1_000.0, "high": 2_000.0, "low": 900.0, "close": 1_900.0})
    repeated = reconstruct_signal("NVDA", as_of, "swing_long_v1.1.0", daily_payload=mutated, hourly_payload=hourly_payload)

    assert baseline["reconstruction"]["no_future_data"] is True
    assert baseline["reconstruction"]["daily_completed_bars"] == 70
    assert repeated["signal"]["score"] == baseline["signal"]["score"]
    with pytest.raises(ValueError):
        reconstruct_signal("NVDA", as_of, "swing_long_v1.0.0", daily_payload=daily_payload, hourly_payload=hourly_payload)
