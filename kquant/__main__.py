from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stock_signals import api_stock_live_data_health, api_stock_signals
from .stock_store import default_db_path
from .validation_service import run_strategy_validation


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m kquant")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("stock-scan", help="Run the US stock signal scan.")
    scan.add_argument("--source", choices=["live"], default="live")
    scan.add_argument("--universe", choices=["default", "ai", "ai_five_layer", "all"], default="default")
    scan.add_argument("--profile", default="swing_long_v1")
    scan.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    scan.add_argument("--outputs-dir", default="outputs")
    scan.add_argument("--limit", type=int, default=None)
    scan.add_argument("--layer", default="")
    health = sub.add_parser("stock-health", help="Run a live-only US stock data health scan.")
    health.add_argument("--universes", default="default,ai_five_layer")
    health.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    health.add_argument("--outputs-dir", default="outputs")
    health.add_argument("--limit", type=int, default=None)
    health.add_argument("--scan-pause-seconds", type=float, default=0.0)
    validation = sub.add_parser("validate-strategies", help="Run deterministic walk-forward strategy validation.")
    validation.add_argument("--profiles", default="tactical_1w_v1,high_beta_growth_v1")
    validation.add_argument("--universe", default="default")
    validation.add_argument("--symbols", default="")
    validation.add_argument("--start", default="")
    validation.add_argument("--end", default="")
    validation.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    validation.add_argument("--outputs-dir", default="outputs")
    args = parser.parse_args()
    if args.command == "stock-scan":
        payload = api_stock_signals(
            source=args.source,
            universe=args.universe,
            profile=args.profile,
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
            limit=args.limit,
            layer=args.layer or None,
        )
        print(json.dumps({"run_id": payload["run_id"], "counts": payload["counts"], "provider_status": payload["provider_status"]}, indent=2))
    if args.command == "stock-health":
        payload = api_stock_live_data_health(
            universes=[item.strip() for item in args.universes.split(",") if item.strip()],
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
            limit=args.limit,
            scan_pause_seconds=args.scan_pause_seconds,
        )
        print(json.dumps({"run_id": payload["run_id"], "summary": payload["summary"]}, indent=2))
    if args.command == "validate-strategies":
        payload = run_strategy_validation(
            profiles=[item.strip() for item in args.profiles.split(",") if item.strip()],
            start=args.start or None,
            end=args.end or None,
            universe=args.universe,
            symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None,
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
        )
        print(
            json.dumps(
                {
                    "run_id": payload["run_id"],
                    "dataset_id": payload["dataset_id"],
                    "summary": payload["summary"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
