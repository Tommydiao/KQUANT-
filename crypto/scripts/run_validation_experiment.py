from __future__ import annotations

import argparse
import json

from kquant_crypto.backtest import BacktestConfig, bars_for_duration
from kquant_crypto.config import load_settings
from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.historical_dataset import load_parquet_validation_dataset
from kquant_crypto.strategy_scopes import (
    HISTORICAL_DERIVATIVE_SCOPE,
    HISTORICAL_DERIVATIVE_STRATEGY_VERSION,
    HISTORICAL_DERIVATIVE_WEIGHTS,
    HISTORICAL_OHLCV_SCOPE,
    HISTORICAL_OHLCV_STRATEGY_VERSION,
    HISTORICAL_OHLCV_WEIGHTS,
)
from kquant_crypto.validation import ValidationConfig
from kquant_crypto.validation_experiments import ValidationCandidate, run_validation_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="Select Crypto validation parameters from the validation partition only.")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--include-derivatives", action="store_true")
    parser.add_argument("--setup-threshold", type=float, action="append", dest="thresholds")
    parser.add_argument("--max-hold-bars", type=int)
    args = parser.parse_args()

    settings = load_settings()
    symbols = tuple(item.upper() for item in args.symbols) if args.symbols else None
    dataset = load_parquet_validation_dataset(
        settings.data_dir,
        symbols=symbols,
        interval=args.interval,
        include_derivatives=args.include_derivatives,
    )
    if not dataset.series:
        print(json.dumps({"status": "NO_GO", "dataset": dataset.coverage}, ensure_ascii=True, indent=2))
        return 1

    thresholds = args.thresholds or [50.0, 60.0, 70.0]
    hold_bars = args.max_hold_bars or bars_for_duration(args.interval, hours=24)
    candidates = tuple(
        ValidationCandidate(
            candidate_id=f"setup_{threshold:g}_hold_{hold_bars}",
            backtest_overrides={"setup_threshold": threshold, "max_hold_bars": hold_bars},
        )
        for threshold in thresholds
    )
    if args.include_derivatives:
        strategy_version = HISTORICAL_DERIVATIVE_STRATEGY_VERSION
        scope = HISTORICAL_DERIVATIVE_SCOPE
        weights = HISTORICAL_DERIVATIVE_WEIGHTS
    else:
        strategy_version = HISTORICAL_OHLCV_STRATEGY_VERSION
        scope = HISTORICAL_OHLCV_SCOPE
        weights = HISTORICAL_OHLCV_WEIGHTS
    experiment = run_validation_experiment(
        dataset.series,
        registry=FactorRegistry(settings.db_path),
        weights=dict(weights),
        candidates=candidates,
        base_config=ValidationConfig(
            strategy_version=strategy_version,
            dataset_version=f"experiment_{dataset.coverage['dataset_hash'][:16]}",
            feature_scope=scope,
            bar_interval=args.interval,
            backtest=BacktestConfig(max_hold_bars=hold_bars),
        ),
    )
    print(json.dumps({
        "status": "created",
        "dataset_coverage": dataset.coverage,
        "experiment": experiment.as_dict(),
        "read_only_market_data": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
