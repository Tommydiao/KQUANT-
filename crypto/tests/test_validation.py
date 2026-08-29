from __future__ import annotations

from kquant_crypto.backtest import BacktestBar, BacktestConfig
from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.strategy_scopes import HISTORICAL_OHLCV_SCOPE, HISTORICAL_OHLCV_WEIGHTS
from kquant_crypto.validation import ValidationConfig, ValidationSeries, evaluate_validation_gate, run_walk_forward_validation


def _bars(count: int = 180) -> tuple[BacktestBar, ...]:
    values = []
    for index in range(count):
        close = 100 + index * 0.15
        values.append(BacktestBar(
            start_time=f"2026-08-{(index // 10) + 1:02d}T{index % 10:02d}:00:00+00:00",
            open=close,
            high=close + 1.0,
            low=close - 0.5,
            close=close + 0.4,
            volume=1000 + index,
        ))
    return tuple(values)


def test_walk_forward_uses_shared_date_partitions_and_locks_test(settings):
    result = run_walk_forward_validation(
        [ValidationSeries("asset:sol", "SOLUSDT", _bars())],
        registry=FactorRegistry(settings.db_path),
        weights={"trend_ema_reclaim": 70.0},
        config=ValidationConfig(
            backtest=BacktestConfig(setup_threshold=60, max_hold_bars=5),
            bootstrap_iterations=200,
        ),
    )
    report = result["report"]
    assert set(report["partitions"]) == {"train", "validation", "test"}
    assert report["split_config"]["dates"]["train"][-1] < report["split_config"]["dates"]["validation"][0]
    assert report["split_config"]["dates"]["validation"][-1] < report["split_config"]["dates"]["test"][0]
    assert report["test_is_locked"] is True
    assert report["overall"]["bootstrap_expected_r_interval_95"] is not None
    assert report["oos_fold_count"] == 3
    assert all(item["test_is_locked"] for item in report["oos_folds"])
    assert report["validation_gate"]["status"] == "NO_GO"
    assert "test_trades" in report["validation_gate"]["failed_checks"]


def test_validation_gate_is_fail_closed_for_missing_metrics():
    result = evaluate_validation_gate({
        "test_is_locked": True,
        "oos_fold_count": 3,
        "partitions": {"test": {"summary": {"sample_count": 200}}},
    })
    assert result["status"] == "NO_GO"
    assert result["passed"] is False
    assert {"bootstrap_expected_r", "profit_factor", "max_drawdown"}.issubset(result["failed_checks"])


def test_historical_scope_is_explicit_and_excludes_live_only_factors(settings):
    result = run_walk_forward_validation(
        [ValidationSeries("asset:sol", "SOLUSDT", _bars())],
        registry=FactorRegistry(settings.db_path),
        weights=dict(HISTORICAL_OHLCV_WEIGHTS),
        config=ValidationConfig(
            feature_scope=HISTORICAL_OHLCV_SCOPE,
            backtest=BacktestConfig(setup_threshold=60, max_hold_bars=5),
            bootstrap_iterations=100,
        ),
    )
    report = result["report"]
    assert report["feature_scope"] == HISTORICAL_OHLCV_SCOPE
    assert "cvd_bias" in report["excluded_factor_ids"]
    assert "funding_extreme" in report["excluded_factor_ids"]
    assert report["feature_scope_limitations"]
