import pandas as pd

from btc_eth_15m.config import StrategyConfig
from btc_eth_15m.strategy import generate_signals


def test_strategy_adds_signal_without_future_rows():
    rows = []
    price = 100.0
    for idx in range(260):
        price += 0.2
        rows.append(
            {
                "open": price - 0.1,
                "high": price + 0.4,
                "low": price - 0.5,
                "close": price,
                "volume": 1000 + idx,
            }
        )
    frame = pd.DataFrame(rows)
    full = generate_signals(frame, StrategyConfig())
    truncated = generate_signals(frame.iloc[:-1], StrategyConfig())
    assert "signal" in full.columns
    assert full["signal"].iloc[:-1].reset_index(drop=True).equals(truncated["signal"].reset_index(drop=True))

