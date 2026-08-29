from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant_crypto.backtest import BacktestBar
from kquant_crypto.roll_engine import RollInput, evaluate_roll
from kquant_crypto.roll_validation import (
    RollBar,
    RollValidationConfig,
    asset_group_for_roll,
    build_roll_series_from_validation,
    run_roll_backtest,
    run_roll_walk_forward,
)
from kquant_crypto.validation import ValidationSeries


def _input(time: str) -> RollInput:
    return RollInput.from_mapping({
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "asset_type": "crypto_spot",
        "as_of_time": time,
        "data_cutoff_time": time,
        "source_status": "live",
        "coverage": 1.0,
        "market_state": "BULL",
        "state_probability": 0.9,
        "target_before_stop_probability": 0.75,
        "positive_return_probability": 0.75,
        "drawdown_probability": 0.1,
        "feature_snapshot_id": "validation_features_v1",
        "model_version": "crypto_bayesian_v1.0.0",
        "research_only": True,
    })


def test_roll_backtest_enters_next_bar_and_stop_wins_same_bar():
    bars = (
        RollBar("2026-08-23T00:00:00+00:00", 100, 101, 99, 100, _input("2026-08-23T00:00:00+00:00")),
        RollBar("2026-08-23T00:01:00+00:00", 100, 120, 80, 100, _input("2026-08-23T00:01:00+00:00")),
        RollBar("2026-08-23T00:02:00+00:00", 100, 101, 99, 100, _input("2026-08-23T00:02:00+00:00")),
    )
    result = run_roll_backtest(bars, config=RollValidationConfig(max_hold_bars=2))
    assert len(result) == 1
    assert result[0].entry_time == bars[1].start_time
    assert result[0].exit_reason == "stop_first"
    assert result[0].realized_r < 0


def test_walk_forward_keeps_date_partitions_and_research_gate_closed():
    bars = []
    for day in range(1, 12):
        for minute in range(4):
            time = f"2026-08-{day:02d}T00:{minute:02d}:00+00:00"
            bars.append(RollBar(time, 100, 102, 99, 101, _input(time)))
    report = run_roll_walk_forward({"ETH": tuple(bars)}, config=RollValidationConfig(max_hold_bars=1, bootstrap_iterations=100))
    assert report["strategy_version"] == "crypto_roll_v1.0.0"
    assert report["test_is_locked"] is True
    assert report["oos_fold_count"] == 3
    assert report["validation_gate"]["status"] == "NO_GO"
    assert "test_trades" in report["validation_gate"]["failed_checks"]


def test_future_bar_perturbation_does_not_change_signal_action():
    prefix = (
        RollBar("2026-08-23T00:00:00+00:00", 100, 101, 99, 100, _input("2026-08-23T00:00:00+00:00")),
        RollBar("2026-08-23T00:01:00+00:00", 100, 101, 99, 100, _input("2026-08-23T00:01:00+00:00")),
    )
    first = run_roll_backtest(prefix + (RollBar("2026-08-23T00:02:00+00:00", 100, 101, 99, 100, _input("2026-08-23T00:02:00+00:00")),))
    second = run_roll_backtest(prefix + (RollBar("2026-08-23T00:02:00+00:00", 1000, 5000, 1, 2000, _input("2026-08-23T00:02:00+00:00")),))
    assert first[0].action == second[0].action
    assert first[0].entry_price == second[0].entry_price


def test_roll_validation_separates_asset_groups():
    assert asset_group_for_roll("BTC", "crypto_spot") == "btc_eth"
    assert asset_group_for_roll("ETHU", "crypto_leveraged_etf") == "ethu"
    assert asset_group_for_roll("MSTU", "crypto_leveraged_etf") == "mstu"
    assert asset_group_for_roll("AAVE", "crypto_spot") == "crypto_alt"


def test_roll_dataset_uses_only_bar_prefix_and_marks_optional_derivatives():
    bars = tuple(
        BacktestBar(
            start_time=(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)).isoformat(),
            open=100 + index * 0.2,
            high=101 + index * 0.2,
            low=99 + index * 0.2,
            close=100 + index * 0.2,
            volume=1000 + index,
        )
        for index in range(70)
    )
    item = ValidationSeries(
        asset_id="asset:BTC",
        symbol="BTCUSDT",
        bars=bars,
        benchmark_bars={"BTC": bars, "ETH": bars},
        derivative_series=(),
    )

    first, first_coverage = build_roll_series_from_validation(
        (item,), source_dataset_id="dataset-v1", interval_minutes=60, min_history_bars=55
    )
    changed_bars = bars[:-1] + (BacktestBar(
        start_time=bars[-1].start_time,
        open=1000,
        high=1100,
        low=900,
        close=1050,
        volume=999999,
    ),)
    changed, _ = build_roll_series_from_validation(
        (ValidationSeries(
            asset_id="asset:BTC",
            symbol="BTCUSDT",
            bars=changed_bars,
            benchmark_bars={"BTC": changed_bars, "ETH": changed_bars},
            derivative_series=(),
        ),),
        source_dataset_id="dataset-v1",
        interval_minutes=60,
        min_history_bars=55,
    )

    assert first_coverage["derivative_values_are_optional_and_missing_is_explicit"] is True
    assert len(first["BTCUSDT"]) == 16
    assert first["BTCUSDT"][0].roll_input.feature_snapshot_id == changed["BTCUSDT"][0].roll_input.feature_snapshot_id
    assert "derivative_evidence_missing" in first["BTCUSDT"][0].roll_input.warnings


def test_roll_dataset_does_not_treat_listed_proxy_history_as_underlying_history():
    bars = tuple(
        BacktestBar(
            start_time=(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)).isoformat(),
            open=100 + index * 0.2,
            high=101 + index * 0.2,
            low=99 + index * 0.2,
            close=100 + index * 0.2,
            volume=1000 + index,
        )
        for index in range(70)
    )
    item = ValidationSeries(
        asset_id="asset:ETHU",
        symbol="ETHU",
        bars=bars,
        benchmark_bars={"ETH": bars},
        instrument_id="listed:US:ETHU",
        asset_type="crypto_leveraged_etf",
        instrument_data_status="",
    )
    built, _ = build_roll_series_from_validation(
        (item,), source_dataset_id="listed-dataset", interval_minutes=60, min_history_bars=55
    )
    decision = evaluate_roll(built["ETHU"][0].roll_input)
    assert decision.action == "DATA_BLOCKED"
    assert "listed_instrument_data_unavailable" in decision.blockers
