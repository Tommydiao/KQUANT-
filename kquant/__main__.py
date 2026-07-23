from __future__ import annotations

import argparse
import json
from pathlib import Path

from .database_migrations import migration_readiness
from .operations import backup_local_workspace, operational_health, restore_drill, run_scheduled_task
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
    database = sub.add_parser("database-status", help="Show local schema migration readiness without exposing credentials.")
    database.add_argument("--database-url", default="")
    database.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    operations = sub.add_parser("operations-health", help="Show local scheduler, notification, and database health.")
    operations.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    backup = sub.add_parser("backup-local", help="Create a verified local SQLite backup. Secrets are excluded.")
    backup.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    backup.add_argument("--backup-dir", default="work/backups")
    drill = sub.add_parser("restore-drill", help="Verify a backup in a temporary location without replacing the active database.")
    drill.add_argument("--backup-path", required=True)
    task = sub.add_parser("run-local-task", help="Run a local idempotent preflight or explicitly enabled candidate refresh.")
    task.add_argument("--name", choices=["preflight", "candidate_refresh"], required=True)
    task.add_argument("--key", required=True)
    task.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    task.add_argument("--outputs-dir", default="outputs")
    task.add_argument("--enable-market-scan", action="store_true")
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
    if args.command == "database-status":
        print(json.dumps(migration_readiness(args.database_url or None, default_path=Path(args.db_path)), indent=2))
    if args.command == "operations-health":
        print(json.dumps(operational_health(Path(args.db_path)), indent=2))
    if args.command == "backup-local":
        print(
            json.dumps(
                backup_local_workspace(
                    Path(args.db_path),
                    backup_dir=Path(args.backup_dir),
                    config_paths=[Path("config/default.yml"), Path("docs/strategy_specification.md")],
                ),
                indent=2,
            )
        )
    if args.command == "restore-drill":
        print(json.dumps(restore_drill(Path(args.backup_path)), indent=2))
    if args.command == "run-local-task":
        db = Path(args.db_path)
        if args.name == "preflight":
            callback = lambda: migration_readiness(default_path=db)
        elif not args.enable_market_scan:
            callback = lambda: {
                "status": "disabled",
                "reason": "candidate_refresh requires --enable-market-scan; no scheduled market call is implicit.",
            }
        else:
            callback = lambda: api_stock_signals(
                source="live", universe="default", profile="swing_long_v1",
                db_path=db, outputs_dir=Path(args.outputs_dir), limit=None,
            )
        print(json.dumps(run_scheduled_task(db, task_name=args.name, idempotency_key=args.key, callback=callback), indent=2))


if __name__ == "__main__":
    main()
