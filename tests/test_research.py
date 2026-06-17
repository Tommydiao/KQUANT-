from pathlib import Path

from btc_eth_15m.research import _daily_target_ok, _paper_observation_ok


def test_paper_observation_gate_requires_robust_positive_branch():
    assert _paper_observation_ok(
        {
            "profit_factor": 1.06,
            "avg_r": 0.01,
            "max_drawdown_pct": -24.0,
            "positive_years": 3,
            "positive_symbols": 2,
            "symbol_count": 2,
            "avg_daily_return_pct": 5.5,
            "target_range_hit_rate_pct": 55.0,
            "loss_day_rate_pct": 20.0,
        }
    )
    assert not _paper_observation_ok(
        {
            "profit_factor": 1.06,
            "avg_r": -0.01,
            "max_drawdown_pct": -24.0,
            "positive_years": 3,
            "positive_symbols": 2,
            "symbol_count": 2,
            "avg_daily_return_pct": 5.5,
            "target_range_hit_rate_pct": 55.0,
            "loss_day_rate_pct": 20.0,
        }
    )


def test_daily_target_gate_requires_consistent_target_days():
    assert _daily_target_ok(
        {
            "avg_daily_return_pct": 5.5,
            "target_range_hit_rate_pct": 55.0,
            "loss_day_rate_pct": 20.0,
        }
    )
    assert not _daily_target_ok(
        {
            "avg_daily_return_pct": 5.5,
            "target_range_hit_rate_pct": 5.0,
            "loss_day_rate_pct": 20.0,
        }
    )
