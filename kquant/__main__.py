from __future__ import annotations

import argparse
import base64
import getpass
import json
import secrets
import os
from pathlib import Path

from .database_migrations import apply_sqlite_schema_migrations, migration_readiness
from .data_coverage import api_stock_data_coverage, persist_data_coverage_run
from .operations import backup_local_workspace, operational_health, restore_drill, run_scheduled_task
from .market_data_backfill import create_backfill_job, run_backfill_job, run_longbridge_backfill
from .provider_event_retention import archive_provider_events, provider_event_retention_status
from .production_readiness import (
    evaluate_go_no_go,
    serialize_go_no_go,
    write_personal_production_launch_report,
)
from .security import SecuritySettings, generate_password_hash
from .stock_signals import api_stock_live_data_health, api_stock_signals
from .stock_store import default_db_path
from .theme_taxonomy import build_theme_taxonomy, latest_theme_taxonomy
from .validation_service import api_strategy_validation_latest, run_strategy_validation


def load_local_environment(path: Path = Path(".env")) -> None:
    """Load local-only CLI configuration without overriding the current process environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and value and name not in os.environ:
            os.environ[name] = value


def main() -> None:
    load_local_environment()
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
    coverage = sub.add_parser("data-coverage", help="Report source-aware cached candle coverage without fetching market data.")
    coverage.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    coverage.add_argument("--record", action="store_true", help="Persist an immutable coverage-run record.")
    backfill = sub.add_parser("backfill-market-data", help="Backfill 5y daily and 2y hourly Longbridge candles; reference fallback is never eligible.")
    backfill.add_argument("--universe", default="all")
    backfill.add_argument("--symbols", default="")
    backfill.add_argument("--limit", type=int, default=None)
    backfill.add_argument("--pause-seconds", type=float, default=0.2)
    backfill.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    backfill.add_argument("--outputs-dir", default="outputs")
    queue_backfill = sub.add_parser("queue-market-backfill", help="Create a resumable Longbridge-only market-data backfill job.")
    queue_backfill.add_argument("--symbols", default="")
    queue_backfill.add_argument("--pause-seconds", type=float, default=0.2)
    queue_backfill.add_argument("--max-attempts", type=int, default=3)
    queue_backfill.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    run_backfill = sub.add_parser("run-market-backfill", help="Run one bounded batch from a queued backfill job.")
    run_backfill.add_argument("--job-id", required=True)
    run_backfill.add_argument("--batch-size", type=int, default=10)
    run_backfill.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    retention = sub.add_parser("provider-event-retention", help="Inspect or explicitly archive old provider event records without deleting them.")
    retention.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    retention.add_argument("--retention-days", type=int, default=90)
    retention.add_argument("--archive-dir", default="outputs/archives")
    retention.add_argument("--apply", action="store_true")
    taxonomy = sub.add_parser("build-theme-taxonomy", help="Materialize the versioned point-in-time theme taxonomy.")
    taxonomy.add_argument("--config", default="config/theme_taxonomy_v1.yml")
    taxonomy.add_argument("--as-of-date", default="")
    taxonomy.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    taxonomy_status = sub.add_parser("theme-taxonomy-status", help="Read the latest materialized theme taxonomy.")
    taxonomy_status.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
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
    migrate = sub.add_parser("migrate-database", help="Apply forward-only SQLite schema migrations after backup verification.")
    migrate.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
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
    readiness = sub.add_parser("production-readiness", help="Evaluate strict personal-production gates without any broker access.")
    readiness.add_argument("--strategy-version", default="swing_long_v1.1.0")
    readiness.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    launch_report = sub.add_parser("write-launch-report", help="Write a Go/No-Go launch report; this never enables execution.")
    launch_report.add_argument("--strategy-version", default="swing_long_v1.1.0")
    launch_report.add_argument("--db-path", default=str(default_db_path(Path.cwd())))
    launch_report.add_argument("--output", default="docs/personal_production_launch_report.md")
    login_config = sub.add_parser("local-login-config", help="Print local email-and-password login values after a hidden password prompt.")
    push_config = sub.add_parser("web-push-config", help="Generate a local VAPID key pair for iPhone Home Screen notifications.")
    push_config.add_argument("--write-env", action="store_true", help="Update the ignored local .env without printing key values.")
    args = parser.parse_args()
    if args.command == "local-login-config":
        email = input("KQUANT local login email: ").strip().lower()
        if not email or email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
            raise SystemExit("Enter a valid email address. No configuration was generated.")
        password = getpass.getpass("Choose a KQUANT local login password (12+ characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords did not match. No configuration was generated.")
        print("# Paste these values into the local .env file. Do not commit them.")
        print("KQUANT_LOGIN_ENABLED=true")
        print(f"KQUANT_LOGIN_EMAIL={email}")
        print(f"KQUANT_LOGIN_PASSWORD_HASH={generate_password_hash(password)}")
        print(f"KQUANT_SESSION_SECRET={secrets.token_urlsafe(48)}")
        return
    if args.command == "web-push-config":
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError as exc:
            raise SystemExit("Install project dependencies before generating Web Push keys.") from exc
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_value = private_key.private_numbers().private_value.to_bytes(32, "big")
        public_numbers = private_key.public_key().public_numbers()
        public_value = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")
        encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
        values = {
            "KQUANT_WEB_PUSH_ENABLED": "true",
            "KQUANT_WEB_PUSH_PUBLIC_KEY": encode(public_value),
            "KQUANT_WEB_PUSH_PRIVATE_KEY": encode(private_value),
            "KQUANT_WEB_PUSH_SUBJECT": "mailto:local@kquant.invalid",
        }
        if args.write_env:
            env_path = Path(".env")
            existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
            found: set[str] = set()
            updated: list[str] = []
            for line in existing:
                name = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
                if name in values:
                    updated.append(f"{name}={values[name]}")
                    found.add(name)
                else:
                    updated.append(line)
            if found != set(values):
                updated.extend(f"{name}={value}" for name, value in values.items() if name not in found)
            env_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
            print("Local Web Push configuration was written to the ignored .env file. No key values were printed.")
        else:
            print("# Paste these values into the local .env file. Never commit the private key.")
            for name, value in values.items():
                print(f"{name}={value}")
        return
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
    if args.command == "data-coverage":
        payload = persist_data_coverage_run(Path(args.db_path))["coverage"] if args.record else api_stock_data_coverage(Path(args.db_path))
        print(json.dumps({
            "as_of": payload["as_of"],
            "universe_symbols": payload["universe_symbols"],
            "interval_summary": payload["interval_summary"],
            "market_breadth": payload["market_breadth"],
            "canonical_validation_eligible_symbols": payload["canonical_validation_eligible_symbols"],
        }, indent=2))
    if args.command == "backfill-market-data":
        payload = run_longbridge_backfill(
            db_path=Path(args.db_path),
            outputs_dir=Path(args.outputs_dir),
            universe=args.universe,
            symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None,
            limit=args.limit,
            pause_seconds=max(0.0, args.pause_seconds),
        )
        print(json.dumps({
            "version": payload["version"],
            "requested_symbol_count": payload["requested_symbol_count"],
            "eligible_symbol_count": payload["eligible_symbol_count"],
            "report": str(Path(args.outputs_dir) / "longbridge-backfill-latest.json"),
        }, indent=2))
    if args.command == "queue-market-backfill":
        print(json.dumps(create_backfill_job(
            db_path=Path(args.db_path),
            symbols=[item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None,
            pause_seconds=max(0.0, args.pause_seconds), max_attempts=max(1, args.max_attempts),
        ), indent=2))
    if args.command == "run-market-backfill":
        print(json.dumps(run_backfill_job(db_path=Path(args.db_path), job_id=args.job_id, batch_size=max(1, args.batch_size)), indent=2))
    if args.command == "provider-event-retention":
        if args.apply:
            print(json.dumps(archive_provider_events(db_path=Path(args.db_path), output_dir=Path(args.archive_dir), retention_days=max(1, args.retention_days), apply=True), indent=2))
        else:
            print(json.dumps(provider_event_retention_status(Path(args.db_path), max(1, args.retention_days)), indent=2))
    if args.command == "build-theme-taxonomy":
        print(json.dumps(build_theme_taxonomy(db_path=Path(args.db_path), config_path=Path(args.config), as_of_date=args.as_of_date or None), indent=2))
    if args.command == "theme-taxonomy-status":
        print(json.dumps(latest_theme_taxonomy(Path(args.db_path)), indent=2))
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
    if args.command == "migrate-database":
        print(json.dumps(apply_sqlite_schema_migrations(Path(args.db_path)), indent=2))
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
    if args.command in {"production-readiness", "write-launch-report"}:
        db = Path(args.db_path)
        validation = api_strategy_validation_latest(db)
        historical = (validation.get("evidence") or {}).get("historical_policy_replay") or {}
        report = evaluate_go_no_go(
            db_path=db,
            strategy_version=args.strategy_version,
            historical_validation=historical,
            security_report={
                **SecuritySettings.from_environment().report(),
                "order_submission_enabled": False,
            },
        )
        if args.command == "write-launch-report":
            print(json.dumps(write_personal_production_launch_report(report, Path(args.output)), indent=2))
        else:
            print(serialize_go_no_go(report))


if __name__ == "__main__":
    main()
