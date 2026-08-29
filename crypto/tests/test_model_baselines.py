from __future__ import annotations

from kquant_crypto.backtest import TradeOutcome
from kquant_crypto.model_baselines import run_model_benchmark


def _outcome(index: int, realized_r: float, *, value: float) -> TradeOutcome:
    timestamp = f"2026-08-{index + 1:02d}T00:00:00+00:00"
    return TradeOutcome(
        timestamp,
        timestamp,
        timestamp,
        100.0,
        101.0 if realized_r > 0 else 99.0,
        99.0,
        102.0,
        realized_r,
        "target" if realized_r > 0 else "stop",
        60.0 + value * 10.0,
        ("trend_ema_reclaim", "volume_acceleration"),
        symbol="SOLUSDT",
        factor_values=(("trend_ema_reclaim", value), ("volume_acceleration", value / 2.0)),
    )


def test_model_benchmark_is_train_only_and_non_authoritative():
    result = run_model_benchmark(
        {
            "train": [_outcome(index, 1.0 if index % 2 else -1.0, value=0.2 + index / 10.0) for index in range(8)],
            "validation": [_outcome(10 + index, 1.0 if index % 2 else -1.0, value=0.4 + index / 10.0) for index in range(4)],
            "test": [_outcome(20 + index, 1.0 if index % 2 else -1.0, value=0.5 + index / 10.0) for index in range(4)],
        },
        feature_order=("trend_ema_reclaim", "volume_acceleration"),
        dataset_hash="dataset-hash",
        strategy_version="strategy-v1",
    )
    assert result["test_is_locked"] is True
    assert result["test_results_used_for_selection"] is False
    assert result["selection_partition"] == "none"
    assert result["eval_integration"].startswith("disabled")
    logistic = next(item for item in result["models"] if item["model_type"] == "logistic_numpy")
    assert logistic["status"] == "available_non_authoritative"
    assert logistic["partitions"]["test"]["sample_count"] == 4


def test_model_benchmark_excludes_rows_with_missing_factors():
    missing = TradeOutcome(
        "2026-08-01T00:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
        "2026-08-01T00:00:00+00:00",
        100.0,
        101.0,
        99.0,
        102.0,
        1.0,
        "target",
        65.0,
        ("trend_ema_reclaim", "volume_acceleration"),
        symbol="SOLUSDT",
        factor_values=(("trend_ema_reclaim", 0.5), ("volume_acceleration", None)),
    )
    result = run_model_benchmark(
        {"train": [missing], "validation": [], "test": []},
        feature_order=("trend_ema_reclaim", "volume_acceleration"),
    )
    assert result["sample_counts"]["train"] == {"complete_factor_rows": 0, "raw_trade_rows": 1}
