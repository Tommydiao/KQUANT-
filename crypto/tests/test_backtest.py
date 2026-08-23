from __future__ import annotations

from kquant_crypto.backtest import BacktestBar, BacktestConfig, bars_for_duration, date_split, run_early_start_backtest, summarize_outcomes
from kquant_crypto.factor_registry import FactorRegistry


def _bars(count: int = 140) -> tuple[BacktestBar, ...]:
    values = []
    for index in range(count):
        close = 100 + index * 0.25
        values.append(BacktestBar(
            start_time=f"2026-08-{(index // 10) + 1:02d}T{index % 10:02d}:00:00+00:00",
            open=close,
            high=close + 1.0,
            low=close - 0.5,
            close=close + 0.5,
            volume=1000 + index * 5,
        ))
    return tuple(values)


def test_backtest_uses_next_bar_and_reports_costed_results(settings):
    registry = FactorRegistry(settings.db_path)
    outcomes = run_early_start_backtest(
        registry,
        _bars(),
        weights={"trend_ema_reclaim": 70.0},
        config=BacktestConfig(setup_threshold=60, max_hold_bars=8),
    )
    assert outcomes
    assert all(outcome.entry_time != outcome.signal_time for outcome in outcomes)
    summary = summarize_outcomes(outcomes)
    assert summary["sample_count"] == len(outcomes)
    assert summary["evidence_status"] == "insufficient"


def test_date_split_keeps_dates_together_and_has_three_partitions():
    timestamps = [f"2026-08-{day:02d}T00:00:00+00:00" for day in range(1, 11) for _ in range(3)]
    split = date_split(timestamps, embargo_bars=2)
    assert split.train and split.validation and split.test
    assert set(split.train).isdisjoint(split.validation)
    assert set(split.validation).isdisjoint(split.test)
    assert split.embargoed


def test_bars_for_duration_is_interval_aware():
    assert bars_for_duration("1m", hours=24) == 1440
    assert bars_for_duration("15m", hours=24) == 96
    assert bars_for_duration("1h", hours=24) == 24
