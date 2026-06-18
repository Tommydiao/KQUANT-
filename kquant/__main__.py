from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stock_signals import api_stock_signals
from .stock_store import default_db_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m kquant")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("stock-scan", help="Run the US stock signal scan.")
    scan.add_argument("--source", choices=["fixture", "live"], default="fixture")
    scan.add_argument("--universe", choices=["default", "ai", "ai_five_layer", "all"], default="default")
    scan.add_argument("--profile", default="swing_long_v1")
    scan.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    scan.add_argument("--outputs-dir", default="outputs")
    scan.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.command == "stock-scan":
        payload = api_stock_signals(
            source=args.source,
            universe=args.universe,
            profile=args.profile,
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
            limit=args.limit,
        )
        print(json.dumps({"run_id": payload["run_id"], "counts": payload["counts"], "provider_status": payload["provider_status"]}, indent=2))


if __name__ == "__main__":
    main()
