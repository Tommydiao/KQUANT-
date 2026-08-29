from __future__ import annotations

import argparse
import json

from kquant_crypto.config import load_settings
from kquant_crypto.historical_dataset import load_parquet_validation_dataset
from kquant_crypto.roll_engine import ROLL_ASSET_MAP
from kquant_crypto.roll_validation import (
    RollValidationConfig,
    build_roll_series_from_validation,
    run_roll_walk_forward,
)
from kquant_crypto.roll_validation_store import save_roll_validation_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the locked crypto_roll_v1 replay from closed Parquet bars."
    )
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--min-bars", type=int, default=220)
    parser.add_argument("--max-hold-bars", type=int, default=24)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--include-derivatives", action="store_true")
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
        output = {
            "status": "NO_GO",
            "reason": "no eligible closed-bar series",
            "dataset_coverage": dataset.coverage,
            "read_only_market_data": True,
            "account_access": False,
            "wallet_access": False,
            "order_submission": False,
        }
        print(json.dumps(output, ensure_ascii=True, indent=2, default=str))
        return 1

    roll_series, roll_coverage = build_roll_series_from_validation(
        dataset.series,
        source_dataset_id=str(dataset.coverage.get("dataset_hash") or "unknown"),
        interval_minutes=max(1, int(args.interval.rstrip("mMhHdD")) * ({"m": 1, "h": 60, "d": 1440}.get(args.interval[-1:].lower(), 60))),
        min_history_bars=max(1, args.min_bars),
    )
    report = run_roll_walk_forward(
        roll_series,
        config=RollValidationConfig(
            max_hold_bars=max(1, args.max_hold_bars),
            bootstrap_iterations=max(100, args.bootstrap_iterations),
        ),
    )
    report["dataset_coverage"] = dataset.coverage
    report["roll_input_coverage"] = roll_coverage
    report["source_contract"] = "closed_binance_spot_parquet_only"
    report["asset_types_observed"] = ["crypto_spot"]
    observed_assets = {str(symbol).removesuffix("USDT") for symbol in roll_coverage["eligible_symbols"]}
    report["missing_roll_assets"] = sorted(set(ROLL_ASSET_MAP) - observed_assets)
    run_id = save_roll_validation_report(settings.db_path, report)
    test = report["partitions"]["test"]["summary"]
    output = {
        "status": "created",
        "run_id": run_id,
        "strategy_version": report["strategy_version"],
        "validation_version": report["validation_version"],
        "dataset_hash": report["dataset_hash"],
        "roll_input_coverage": roll_coverage,
        "test": test,
        "oos": report["oos_summary"],
        "validation_gate": report["validation_gate"],
        "read_only_market_data": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
    }
    print(json.dumps(output, ensure_ascii=True, indent=2, default=str))
    return 0 if report["validation_gate"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
