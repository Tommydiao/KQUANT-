from __future__ import annotations

import argparse
import json

from kquant_crypto.backtest import BacktestConfig, bars_for_duration
from kquant_crypto.config import load_settings
from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.historical_dataset import load_parquet_validation_dataset
from kquant_crypto.model_baselines import run_model_benchmark
from kquant_crypto.strategy_scopes import (
    HISTORICAL_DERIVATIVE_SCOPE,
    HISTORICAL_DERIVATIVE_STRATEGY_VERSION,
    HISTORICAL_DERIVATIVE_WEIGHTS,
    HISTORICAL_OHLCV_SCOPE,
    HISTORICAL_OHLCV_STRATEGY_VERSION,
    HISTORICAL_OHLCV_WEIGHTS,
)
from kquant_crypto.validation import ValidationConfig, run_walk_forward_validation
from kquant_crypto.validation_store import save_validation_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a locked, read-only Crypto Parquet validation replay.")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--min-bars", type=int, default=55)
    parser.add_argument("--include-derivatives", action="store_true")
    parser.add_argument("--max-hold-bars", type=int)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--model-benchmark", action="store_true", help="Add non-authoritative train/validation/test model baselines.")
    args = parser.parse_args()

    settings = load_settings()
    symbols = tuple(item.upper() for item in args.symbols) if args.symbols else None
    dataset = load_parquet_validation_dataset(
        settings.data_dir,
        symbols=symbols,
        interval=args.interval,
        min_bars=args.min_bars,
        include_derivatives=args.include_derivatives,
    )
    if not dataset.series:
        print(json.dumps({"status": "NO_GO", "dataset": dataset.coverage}, ensure_ascii=True, indent=2))
        return 1

    if args.include_derivatives:
        strategy_version = HISTORICAL_DERIVATIVE_STRATEGY_VERSION
        feature_scope = HISTORICAL_DERIVATIVE_SCOPE
        weights = HISTORICAL_DERIVATIVE_WEIGHTS
        suffix = "derivatives"
    else:
        strategy_version = HISTORICAL_OHLCV_STRATEGY_VERSION
        feature_scope = HISTORICAL_OHLCV_SCOPE
        weights = HISTORICAL_OHLCV_WEIGHTS
        suffix = "ohlcv"
    config = ValidationConfig(
        strategy_version=strategy_version,
        dataset_version=f"parquet_{dataset.coverage['dataset_hash'][:16]}_{suffix}",
        feature_scope=feature_scope,
        bar_interval=args.interval,
        backtest=BacktestConfig(
            max_hold_bars=args.max_hold_bars or bars_for_duration(args.interval, hours=24),
        ),
        bootstrap_iterations=args.bootstrap_iterations,
    )
    result = run_walk_forward_validation(
        dataset.series,
        registry=FactorRegistry(settings.db_path),
        weights=dict(weights),
        config=config,
    )
    report = result["report"]
    report["dataset_coverage"] = dataset.coverage
    if args.model_benchmark:
        report["model_benchmarks"] = run_model_benchmark(
            result.get("partition_outcomes", {}),
            feature_order=tuple(sorted(weights)),
            dataset_hash=report["dataset_hash"],
            strategy_version=config.strategy_version,
        )
    run_id = save_validation_run(
        settings.db_path,
        strategy_version=config.strategy_version,
        dataset_version=config.dataset_version,
        split_config=report["split_config"],
        backtest_config=report["backtest_config"],
        status=report["test_evidence_status"],
        report=report,
        outcomes=result["outcomes"],
        partition_outcomes=result.get("partition_outcomes"),
        oos_outcomes_by_fold=result.get("oos_outcomes_by_fold"),
    )
    output = {
        "status": "created",
        "run_id": run_id,
        "strategy_version": config.strategy_version,
        "feature_scope": config.feature_scope,
        "dataset_hash": report["dataset_hash"],
        "test": report["partitions"]["test"]["summary"],
        "oos": report["oos_summary"],
        "read_only_market_data": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
    }
    if args.model_benchmark:
        benchmark = report.get("model_benchmarks", {})
        output["model_benchmark"] = {
            "benchmark_version": benchmark.get("benchmark_version"),
            "sample_counts": benchmark.get("sample_counts"),
            "models": [
                {
                    "model_type": item.get("model_type"),
                    "status": item.get("status"),
                    "test": item.get("partitions", {}).get("test"),
                    "calibration": item.get("calibration"),
                }
                for item in benchmark.get("models", [])
            ],
            "eval_integration": benchmark.get("eval_integration"),
        }
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
