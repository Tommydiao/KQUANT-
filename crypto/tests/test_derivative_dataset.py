from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant_crypto.backtest import BacktestBar
from kquant_crypto.derivative_dataset import DerivativeSnapshot, align_derivatives_to_bars


def test_derivatives_align_only_after_source_and_available_time():
    start = datetime(2026, 8, 1, tzinfo=UTC)
    bars = tuple(
        BacktestBar(
            start_time=(start + timedelta(hours=index)).isoformat(),
            open=100 + index,
            high=101 + index,
            low=99 + index,
            close=100.5 + index,
            volume=1000,
        )
        for index in range(4)
    )
    snapshots = (
        DerivativeSnapshot(
            instrument_id="binance:perpetual:BTCUSDT",
            symbol="BTCUSDT",
            event_type="funding_rate",
            source_time=(start + timedelta(hours=1)).isoformat(),
            available_at=(start + timedelta(hours=1)).isoformat(),
            received_at=(start + timedelta(hours=1, minutes=1)).isoformat(),
            funding_rate=0.0001,
            open_interest=None,
            open_interest_value=None,
            provenance="historical_rest_replay",
        ),
        DerivativeSnapshot(
            instrument_id="binance:perpetual:BTCUSDT",
            symbol="BTCUSDT",
            event_type="open_interest",
            source_time=(start + timedelta(hours=2)).isoformat(),
            available_at=(start + timedelta(hours=3)).isoformat(),
            received_at=(start + timedelta(hours=3, minutes=1)).isoformat(),
            funding_rate=None,
            open_interest=110.0,
            open_interest_value=1100.0,
            provenance="historical_rest_replay",
        ),
    )

    aligned = align_derivatives_to_bars(bars, snapshots)

    assert aligned[0] == {"funding_rate": None, "oi_change": None}
    assert aligned[1]["funding_rate"] == 0.0001
    assert aligned[2]["funding_rate"] is None
    assert aligned[3]["funding_rate"] is None
    assert aligned[2]["oi_change"] is None
    assert aligned[3]["oi_change"] is None
