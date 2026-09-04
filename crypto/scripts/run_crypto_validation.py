from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kquant_crypto.backtest import BacktestConfig, bars_for_duration
from kquant_crypto.config import load_settings
from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.historical_dataset import load_parquet_validation_dataset
from kquant_crypto.model_baselines import run_model_benchmark
from kquant_crypto.strategy_scopes import (
    HISTORICAL_DERIVATIVE_SCOPE,
    HISTORICAL_DERIVATIVE_STRATEGY_VERSION,
    HISTORICAL_DERIVATIVE_WEIGHTS,
    HISTORICAL_FUNDING_SCOPE,
    HISTORICAL_FUNDING_STRATEGY_VERSION,
    HISTORICAL_FUNDING_WEIGHTS,
    HISTORICAL_OHLCV_SCOPE,
    HISTORICAL_PERPETUAL_OHLCV_STRATEGY_VERSION,
    HISTORICAL_SPOT_OHLCV_STRATEGY_VERSION,
    HISTORICAL_OHLCV_WEIGHTS,
)
from kquant_crypto.validation import ValidationConfig, run_walk_forward_validation
from kquant_crypto.validation_store import save_validation_run
from kquant_crypto.strategy_momentum_v21 import (
    FACTOR_IDS as MOMENTUM_V21_FACTOR_IDS,
    LIVE_ONLY_FACTOR_IDS as MOMENTUM_V21_LIVE_ONLY_FACTOR_IDS,
    STRATEGY_VERSION as MOMENTUM_V21_STRATEGY_VERSION,
    score_spot_momentum_v21,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a locked, read-only Crypto Parquet validation replay.")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--min-bars", type=int, default=55)
    parser.add_argument("--include-derivatives", action="store_true")
    parser.add_argument("--max-hold-bars", type=int)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--model-benchmark", action="store_true", help="Add non-authoritative train/validation/test model baselines.")
    parser.add_argument("--market-type", choices=["spot", "perpetual"], default="spot")
    parser.add_argument("--direction", choices=["long", "short"], default="long")
    parser.add_argument(
        "--strategy-version",
        help=f"Use {MOMENTUM_V21_STRATEGY_VERSION} for the shared v2.1 challenger kernel.",
    )
    args = parser.parse_args()

    settings = load_settings()
    symbols = tuple(item.upper() for item in args.symbols) if args.symbols else None
    if args.direction == "short":
        print(json.dumps({
            "status": "NO_GO",
            "reason": "independent_short_strategy_not_implemented",
            "strategy_version": "crypto_perpetual_short_v1.0.0",
            "market_type": args.market_type,
            "direction": args.direction,
        }, ensure_ascii=True, indent=2))
        return 2
    dataset = load_parquet_validation_dataset(
        settings.data_dir,
        symbols=symbols,
        interval=args.interval,
        min_bars=args.min_bars,
        include_derivatives=args.include_derivatives,
        market_type=args.market_type,
    )
    if not dataset.series:
        print(json.dumps({"status": "NO_GO", "dataset": dataset.coverage}, ensure_ascii=True, indent=2))
        return 1

    score_policy = None
    requested_strategy = str(args.strategy_version or "")
    if requested_strategy == MOMENTUM_V21_STRATEGY_VERSION:
        if args.market_type != "spot" or args.direction != "long" or args.include_derivatives:
            parser.error(f"{MOMENTUM_V21_STRATEGY_VERSION} requires spot long OHLCV input")
        strategy_version = MOMENTUM_V21_STRATEGY_VERSION
        feature_scope = "ohlcv_only_limited_v21"
        weights = {
            factor_id: 1.0
            for factor_id in MOMENTUM_V21_FACTOR_IDS
            if factor_id not in MOMENTUM_V21_LIVE_ONLY_FACTOR_IDS
        }
        score_policy = lambda registry, values: score_spot_momentum_v21(
            registry,
            values,
            include_live_only=False,
        )
        suffix = "momentum_v21_ohlcv"
    elif requested_strategy:
        parser.error(f"unsupported strategy version: {requested_strategy}")
    elif args.include_derivatives:
        event_types = set((dataset.coverage.get("derivative_coverage") or {}).get("event_types") or ())
        if "open_interest" in event_types:
            strategy_version = HISTORICAL_DERIVATIVE_STRATEGY_VERSION
            feature_scope = HISTORICAL_DERIVATIVE_SCOPE
            weights = HISTORICAL_DERIVATIVE_WEIGHTS
            suffix = "derivatives"
        else:
            strategy_version = HISTORICAL_FUNDING_STRATEGY_VERSION
            feature_scope = HISTORICAL_FUNDING_SCOPE
            weights = HISTORICAL_FUNDING_WEIGHTS
            suffix = "funding"
    else:
        strategy_version = (
            HISTORICAL_SPOT_OHLCV_STRATEGY_VERSION
            if args.market_type == "spot"
            else HISTORICAL_PERPETUAL_OHLCV_STRATEGY_VERSION
        )
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
            fee_bps_per_side=10.0 if args.market_type == "spot" else 5.0,
            slippage_bps_per_side=5.0,
            market_type=args.market_type,
            direction=args.direction,
            include_funding=args.market_type == "perpetual" and args.include_derivatives,
        ),
        bootstrap_iterations=args.bootstrap_iterations,
        market_type=args.market_type,
        direction=args.direction,
    )
    result = run_walk_forward_validation(
        dataset.series,
        registry=FactorRegistry(settings.db_path),
        weights=dict(weights),
        config=config,
        score_policy=score_policy,
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
        "market_type": args.market_type,
        "direction": args.direction,
        "dataset_hash": report["dataset_hash"],
        "test": report["partitions"]["test"]["summary"],
        "oos": report["oos_summary"],
        "stress": report["stress"],
        "validation_gate": report["validation_gate"],
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
