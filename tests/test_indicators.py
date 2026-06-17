import pandas as pd

from btc_eth_15m.indicators import atr, ema, rsi


def test_indicators_return_aligned_series():
    frame = pd.DataFrame(
        {
            "high": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25],
            "low": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
            "close": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24],
        }
    )
    assert len(ema(frame["close"], 5)) == len(frame)
    assert len(atr(frame, 5)) == len(frame)
    assert len(rsi(frame["close"], 5)) == len(frame)
    assert rsi(frame["close"], 5).iloc[-1] >= 0

