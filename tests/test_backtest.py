from pathlib import Path

import pandas as pd

from btc_eth_15m.backtest import _daily_return_stats, _slipped_entry_price, _slipped_exit_price


def test_slippage_is_adverse_for_entries_and_exits():
    assert _slipped_entry_price(100, 1, 10) == 100.1
    assert _slipped_entry_price(100, -1, 10) == 99.9
    assert _slipped_exit_price(100, 1, 10) == 99.9
    assert _slipped_exit_price(100, -1, 10) == 100.1


def test_daily_return_stats_measure_target_range():
    equity = pd.DataFrame(
        [
            {"time": "2026-01-01T00:00:00+00:00", "equity": 10000.0},
            {"time": "2026-01-01T23:45:00+00:00", "equity": 10600.0},
            {"time": "2026-01-02T23:45:00+00:00", "equity": 11236.0},
            {"time": "2026-01-03T23:45:00+00:00", "equity": 11011.28},
        ]
    )

    stats = _daily_return_stats(equity, 10000.0)

    assert stats["trading_days"] == 3
    assert round(stats["avg_daily_return_pct"], 3) == 3.333
    assert round(stats["target_range_hit_rate_pct"], 2) == 66.67
    assert round(stats["above_target_min_rate_pct"], 2) == 66.67
    assert round(stats["loss_day_rate_pct"], 2) == 33.33
