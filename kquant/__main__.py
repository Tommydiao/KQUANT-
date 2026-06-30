from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mstr_cycle import api_mstr_cycle_radar
from .stock_signals import api_stock_live_data_health, api_stock_signals
from .stock_store import default_db_path


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
    mstr = sub.add_parser("mstr-cycle", help="Run the MSTR cycle bottom radar.")
    mstr.add_argument("--source", choices=["live"], default="live")
    mstr.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    mstr.add_argument("--outputs-dir", default="outputs")
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
    if args.command == "mstr-cycle":
        payload = api_mstr_cycle_radar(
            source=args.source,
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
        )
        print(
            json.dumps(
                {
                    "run_id": payload["run_id"],
                    "level": payload["level"],
                    "bottom_score": payload["bottom_score"],
                    "distribution_risk_score": payload["distribution_risk_score"],
                    "provider_status": payload["provider_status"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
