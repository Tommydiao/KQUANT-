import pandas as pd
import pytest

from btc_eth_15m.config import StrategyConfig
from btc_eth_15m.strategy import _apply_post_signal_filters, generate_signals


def _sample_frame(rows=320):
    data = []
    price = 100.0
    for idx in range(rows):
        price += 0.08 if idx < rows // 2 else -0.02
        data.append(
            {
                "open": price - 0.05,
                "high": price + 0.35,
                "low": price - 0.35,
                "close": price,
                "volume": 1000 + idx % 25,
            }
        )
    return pd.DataFrame(data)


@pytest.mark.parametrize("mode", ["trend_pullback", "breakout_failure", "volatility_breakout", "range_reversion"])
def test_strategy_modes_emit_signal_columns(mode):
    frame = _sample_frame()
    result = generate_signals(frame, StrategyConfig(mode=mode))
    assert "signal" in result.columns
    assert "signal_atr" in result.columns
    assert set(result["signal"].dropna().unique()).issubset({-1, 0, 1})


def test_regime_filter_can_reduce_signals():
    frame = _sample_frame(420)
    loose = generate_signals(frame, StrategyConfig(mode="breakout_failure", regime_filter="none"))
    filtered = generate_signals(frame, StrategyConfig(mode="breakout_failure", regime_filter="trend"))
    assert (filtered["signal"] != 0).sum() <= (loose["signal"] != 0).sum()


def test_post_signal_filters_can_limit_side_and_hour():
    frame = pd.DataFrame(
        {
            "signal": [1, -1, -1],
            "htf_gap_bps": [200.0, 200.0, 200.0],
            "atr_pct": [0.005, 0.005, 0.005],
            "regime_atr_pct": [0.005, 0.005, 0.005],
            "volume_ratio": [1.0, 1.0, 1.0],
            "open_datetime": pd.to_datetime(
                [
                    "2026-01-01T01:00:00Z",
                    "2026-01-01T02:00:00Z",
                    "2026-01-01T13:00:00Z",
                ],
                utc=True,
            ),
        }
    )

    result = _apply_post_signal_filters(
        frame.copy(),
        StrategyConfig(side_filter="short", signal_start_hour_utc=0, signal_end_hour_utc=6),
    )

    assert result["signal"].tolist() == [0, -1, 0]
