"""Offline research CLI. Does not import KQUANT execution or service modules."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.timeseries_forecast.contracts import Run, freeze, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "fetch", "build", "retrieve", "train", "evaluate", "report", "status"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config/timeseries_forecast_v1.json")
    parser.add_argument("--fold", choices=["dev_2022", "dev_2023", "dev_2024"], default="dev_2022")
    parser.add_argument("--method", choices=["constant", "ar1", "nearest", "dtw", "tcn", "tcn_1h"], default="nearest")
    parser.add_argument("--partition", choices=["validation", "report", "appendix"], default="report")
    parser.add_argument("--seed", type=int, default=20260913)
    parser.add_argument("--max-samples", type=int, default=0, help="Per-invocation compute budget; partial runs NEVER pass gates. Chunks contain 16 rows.")
    parser.add_argument("--recover-stale-lock", help="Status only: archive an orphaned research phase lock after verifying its PID is absent")
    args = parser.parse_args()
    if not args.run_id.replace("_", "").replace("-", "").isalnum():
        parser.error("Invalid run ID")
    path = ROOT / "outputs/timeseries_forecast" / args.run_id
    if args.command == "freeze":
        freeze(path, args.config, ROOT)
        print(path)
        return
    run = Run(path)
    if args.recover_stale_lock:
        if args.command != "status":
            parser.error("Lock recovery is status-only")
        from kquant_crypto.timeseries_forecast.contracts import recover_lock
        print(recover_lock(run, args.recover_stale_lock))
    fold = next(f for f in run.config["folds"] if f["id"] == args.fold)
    if args.command == "fetch":
        from kquant_crypto.timeseries_forecast.data import fetch
        fetch(run)
    elif args.command == "build":
        from kquant_crypto.timeseries_forecast.data import build
        from kquant_crypto.timeseries_forecast.sequences import audit_sequences
        build(run)
        audit_sequences(run)
    elif args.command == "train":
        from kquant_crypto.timeseries_forecast.experiment import train
        train(run, fold, args.seed, args.method == "tcn_1h")
    elif args.command == "retrieve":
        from kquant_crypto.timeseries_forecast.experiment import predict
        predict(run, fold, args.method, kind=args.partition, seed=args.seed, max_samples=args.max_samples)
    elif args.command in ("evaluate", "report"):
        from kquant_crypto.timeseries_forecast.evaluation import evaluate, report
        print((evaluate if args.command == "evaluate" else report)(run))
    else:
        for p in sorted(path.glob("*/complete.json")):
            print(p.parent.name, "COMPLETE")
        for p in sorted(path.glob("*_progress.json")):
            print(p.name, read_json(p))
        for p in path.glob("*/writer.lock"):
            print("LOCK_REQUIRES_PROCESS_CHECK", p, read_json(p))
        print("DEV_ONLY; execution disabled; sealed history preserved")
        print("BASELINE_CHANGED", run.baseline_changes())


if __name__ == "__main__":
    main()
