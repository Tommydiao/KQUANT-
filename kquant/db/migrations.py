from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


LEGACY_SCHEMA_VERSION = 1
LATEST_SCHEMA_VERSION = 7
LEGACY_MIGRATION_NAME = "initial_stock_research_schema"

QUARANTINED_LEGACY_TABLES: dict[str, str] = {
    "equity_broker_controls": "Historical broker-control data is outside the read-only KQUANT v2 runtime.",
    "equity_live_orders": "Historical live-order data is outside the read-only KQUANT v2 runtime.",
    "equity_order_intents": "Historical order-intent data is outside the read-only KQUANT v2 runtime.",
    "mstr_cycle_journal": "Historical MSTR/BTC-cycle data is not part of the stock-first v2 runtime.",
    "mstr_cycle_runs": "Historical MSTR/BTC-cycle data is not part of the stock-first v2 runtime.",
    "stock_daily_runs": "Legacy daily-run records are retained pending a provenance migration.",
}


class DatabaseMigrationError(RuntimeError):
    """Raised when a migration ledger is tampered with or cannot advance safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    apply: Callable[[sqlite3.Connection], None]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _checksum(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _open_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
    )


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_legacy_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL,
          rollback_note TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _legacy_checksum() -> str:
    # Import lazily so stock_store can call the migration runner without a
    # module-import cycle. The checksum covers the exact legacy bootstrap shape.
    from kquant.stock_store import LEGACY_COLUMN_PATCHES, SCHEMA

    payload = {
        "schema": SCHEMA,
        "column_patches": LEGACY_COLUMN_PATCHES,
        "contract": "legacy_schema_bootstrap_v1",
    }
    return _checksum(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _apply_legacy_schema(conn: sqlite3.Connection) -> None:
    from kquant.stock_store import initialize_legacy_schema

    initialize_legacy_schema(conn)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _apply_explicit_framework(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "schema_migrations", "checksum", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "schema_migrations", "applied_by", "TEXT NOT NULL DEFAULT 'legacy'")
    _add_column_if_missing(conn, "schema_migrations", "details_json", "TEXT NOT NULL DEFAULT '{}'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration_audit (
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          version INTEGER NOT NULL,
          name TEXT NOT NULL,
          checksum TEXT NOT NULL,
          status TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_fingerprints (
          fingerprint TEXT PRIMARY KEY,
          schema_version INTEGER NOT NULL,
          object_count INTEGER NOT NULL,
          computed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_quarantine (
          object_name TEXT PRIMARY KEY,
          object_type TEXT NOT NULL,
          status TEXT NOT NULL,
          reason TEXT NOT NULL,
          recorded_at TEXT NOT NULL
        )
        """
    )
    for table, reason in QUARANTINED_LEGACY_TABLES.items():
        if _table_exists(conn, table):
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_quarantine(
                  object_name, object_type, status, reason, recorded_at
                ) VALUES (?, 'table', 'quarantined', ?, ?)
                """,
                (table, reason, _now()),
            )


def _framework_checksum() -> str:
    return _checksum(
        "explicit_schema_migration_framework_v2|"
        "schema_migrations.checksum,applied_by,details_json|"
        "schema_migration_audit|schema_fingerprints|schema_quarantine|"
        + "|".join(sorted(QUARANTINED_LEGACY_TABLES))
    )


def _apply_data_snapshot_contract(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_snapshots (
          snapshot_id TEXT PRIMARY KEY,
          contract_version TEXT NOT NULL,
          snapshot_kind TEXT NOT NULL,
          scope_json TEXT NOT NULL,
          as_of_time TEXT NOT NULL,
          available_at TEXT NOT NULL,
          eligibility_status TEXT NOT NULL,
          item_count INTEGER NOT NULL,
          eligible_item_count INTEGER NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_data_snapshots_kind_as_of
        ON data_snapshots(snapshot_kind, as_of_time DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_snapshot_items (
          snapshot_id TEXT NOT NULL,
          item_key TEXT NOT NULL,
          item_type TEXT NOT NULL,
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL,
          as_of_time TEXT NOT NULL,
          available_at TEXT NOT NULL,
          fetched_at TEXT NOT NULL,
          eligibility_status TEXT NOT NULL,
          exclusion_reason TEXT NOT NULL DEFAULT '',
          content_hash TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (snapshot_id, item_key),
          FOREIGN KEY (snapshot_id) REFERENCES data_snapshots(snapshot_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_data_snapshot_items_symbol_interval
        ON data_snapshot_items(symbol, interval, as_of_time DESC)
        """
    )


def _data_snapshot_checksum() -> str:
    return _checksum(
        "data_snapshot_contract_v1|data_snapshots|data_snapshot_items|"
        "source,as_of_time,available_at,fetched_at,eligibility_status,content_hash"
    )


def _apply_data_trust_contract(conn: sqlite3.Connection) -> None:
    """Add durable operational records without rewriting legacy market data."""

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS universe_registry_versions (
          registry_id TEXT PRIMARY KEY,
          registry_name TEXT NOT NULL,
          source TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          symbol_count INTEGER NOT NULL,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS universe_registry_members (
          registry_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          name TEXT NOT NULL,
          sector TEXT NOT NULL,
          layer TEXT NOT NULL,
          tags_json TEXT NOT NULL,
          rank_value INTEGER NOT NULL,
          active INTEGER NOT NULL,
          eligibility_status TEXT NOT NULL,
          provenance TEXT NOT NULL,
          PRIMARY KEY (registry_id, symbol),
          FOREIGN KEY (registry_id) REFERENCES universe_registry_versions(registry_id)
        );
        CREATE INDEX IF NOT EXISTS idx_universe_registry_members_symbol
        ON universe_registry_members(symbol, registry_id);
        CREATE TABLE IF NOT EXISTS data_coverage_runs (
          coverage_run_id TEXT PRIMARY KEY,
          registry_id TEXT NOT NULL,
          contract_version TEXT NOT NULL,
          as_of_time TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          summary_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (registry_id) REFERENCES universe_registry_versions(registry_id)
        );
        CREATE TABLE IF NOT EXISTS data_coverage_items (
          coverage_run_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          source TEXT NOT NULL,
          provider_status TEXT NOT NULL,
          adjustment_mode TEXT NOT NULL,
          candle_count INTEGER NOT NULL,
          first_time TEXT,
          last_time TEXT,
          fetched_at TEXT,
          gap_count INTEGER NOT NULL,
          max_gap_seconds INTEGER,
          eligibility_status TEXT NOT NULL,
          details_json TEXT NOT NULL,
          PRIMARY KEY (coverage_run_id, symbol, interval),
          FOREIGN KEY (coverage_run_id) REFERENCES data_coverage_runs(coverage_run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_data_coverage_items_symbol_interval
        ON data_coverage_items(symbol, interval, coverage_run_id DESC);
        CREATE TABLE IF NOT EXISTS market_backfill_jobs (
          job_id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          registry_id TEXT NOT NULL,
          status TEXT NOT NULL,
          requested_intervals_json TEXT NOT NULL,
          pause_seconds REAL NOT NULL,
          max_attempts INTEGER NOT NULL,
          requested_at TEXT NOT NULL,
          started_at TEXT,
          completed_at TEXT,
          last_error TEXT NOT NULL DEFAULT '',
          details_json TEXT NOT NULL,
          FOREIGN KEY (registry_id) REFERENCES universe_registry_versions(registry_id)
        );
        CREATE TABLE IF NOT EXISTS market_backfill_job_items (
          job_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          range_value TEXT NOT NULL,
          minimum_bars INTEGER NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt_at TEXT,
          last_error TEXT NOT NULL DEFAULT '',
          result_json TEXT NOT NULL DEFAULT '{}',
          updated_at TEXT NOT NULL,
          PRIMARY KEY (job_id, symbol, interval),
          FOREIGN KEY (job_id) REFERENCES market_backfill_jobs(job_id)
        );
        CREATE INDEX IF NOT EXISTS idx_market_backfill_job_items_pending
        ON market_backfill_job_items(job_id, status, next_attempt_at);
        CREATE TABLE IF NOT EXISTS provider_event_archive_runs (
          archive_id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          before_time TEXT NOT NULL,
          candidate_count INTEGER NOT NULL,
          archived_count INTEGER NOT NULL,
          archive_path TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          details_json TEXT NOT NULL
        );
        """
    )


def _data_trust_checksum() -> str:
    return _checksum(
        "data_trust_v1|universe_registry_versions|universe_registry_members|"
        "data_coverage_runs|data_coverage_items|market_backfill_jobs|"
        "market_backfill_job_items|provider_event_archive_runs"
    )


def _apply_theme_taxonomy_contract(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS theme_taxonomy_runs (
          run_id TEXT PRIMARY KEY,
          taxonomy_version TEXT NOT NULL,
          taxonomy_hash TEXT NOT NULL,
          registry_id TEXT NOT NULL,
          as_of_date TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL,
          summary_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (registry_id) REFERENCES universe_registry_versions(registry_id)
        );
        CREATE INDEX IF NOT EXISTS idx_theme_taxonomy_runs_version_date
        ON theme_taxonomy_runs(taxonomy_version, as_of_date DESC);
        CREATE TABLE IF NOT EXISTS theme_definitions (
          taxonomy_version TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          dimension_type TEXT NOT NULL,
          parent_id TEXT,
          slug TEXT NOT NULL,
          display_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          rule_json TEXT NOT NULL,
          status TEXT NOT NULL,
          effective_from TEXT NOT NULL,
          effective_to TEXT,
          content_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (taxonomy_version, definition_id)
        );
        CREATE INDEX IF NOT EXISTS idx_theme_definitions_dimension_status
        ON theme_definitions(taxonomy_version, dimension_type, status);
        CREATE TABLE IF NOT EXISTS theme_memberships (
          run_id TEXT NOT NULL,
          taxonomy_version TEXT NOT NULL,
          registry_id TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          dimension_type TEXT NOT NULL,
          weight REAL NOT NULL,
          confidence REAL NOT NULL,
          evidence_json TEXT NOT NULL,
          review_status TEXT NOT NULL,
          valid_from TEXT NOT NULL,
          valid_to TEXT,
          created_at TEXT NOT NULL,
          PRIMARY KEY (run_id, definition_id, symbol),
          FOREIGN KEY (run_id) REFERENCES theme_taxonomy_runs(run_id),
          FOREIGN KEY (taxonomy_version, definition_id)
            REFERENCES theme_definitions(taxonomy_version, definition_id)
        );
        CREATE INDEX IF NOT EXISTS idx_theme_memberships_symbol_dimension
        ON theme_memberships(symbol, taxonomy_version, dimension_type);
        CREATE INDEX IF NOT EXISTS idx_theme_memberships_definition
        ON theme_memberships(taxonomy_version, definition_id, review_status);
        CREATE TABLE IF NOT EXISTS theme_membership_audit (
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          action TEXT NOT NULL,
          reason TEXT NOT NULL,
          recorded_at TEXT NOT NULL,
          FOREIGN KEY (run_id) REFERENCES theme_taxonomy_runs(run_id)
        );
        """
    )


def _theme_taxonomy_checksum() -> str:
    return _checksum(
        "theme_taxonomy_v1|theme_taxonomy_runs|theme_definitions|"
        "theme_memberships|theme_membership_audit|effective_from,effective_to"
    )


def _apply_capital_rotation_contract(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS capital_rotation_runs (
          run_id TEXT PRIMARY KEY,
          taxonomy_run_id TEXT NOT NULL,
          as_of_time TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL,
          summary_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (taxonomy_run_id) REFERENCES theme_taxonomy_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_capital_rotation_runs_as_of
        ON capital_rotation_runs(as_of_time DESC);
        CREATE TABLE IF NOT EXISTS capital_rotation_scores (
          run_id TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          dimension_type TEXT NOT NULL,
          rank_value INTEGER,
          member_count INTEGER NOT NULL,
          eligible_member_count INTEGER NOT NULL,
          score REAL,
          status TEXT NOT NULL,
          data_quality TEXT NOT NULL,
          top_member_contribution REAL,
          features_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (run_id, definition_id),
          FOREIGN KEY (run_id) REFERENCES capital_rotation_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_capital_rotation_scores_rank
        ON capital_rotation_scores(run_id, rank_value);
        CREATE TABLE IF NOT EXISTS capital_rotation_members (
          run_id TEXT NOT NULL,
          definition_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          weight REAL NOT NULL,
          contribution REAL,
          features_json TEXT NOT NULL,
          data_quality TEXT NOT NULL,
          PRIMARY KEY (run_id, definition_id, symbol),
          FOREIGN KEY (run_id) REFERENCES capital_rotation_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_capital_rotation_members_symbol
        ON capital_rotation_members(symbol, run_id);
        """
    )


def _capital_rotation_checksum() -> str:
    return _checksum(
        "capital_rotation_v0.1|capital_rotation_runs|capital_rotation_scores|"
        "capital_rotation_members|single_member_contribution_cap_15pct"
    )


def _apply_quant_dataset_contract(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS quant_datasets (
          dataset_id TEXT PRIMARY KEY,
          contract_version TEXT NOT NULL,
          feature_schema_version TEXT NOT NULL,
          label_schema_version TEXT NOT NULL,
          universe_registry_id TEXT NOT NULL,
          source_policy_version TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          split_config_json TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL,
          test_partition_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_quant_datasets_created
        ON quant_datasets(created_at DESC);
        CREATE TABLE IF NOT EXISTS quant_dataset_partitions (
          dataset_id TEXT NOT NULL,
          split_name TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT NOT NULL,
          embargo_start_date TEXT NOT NULL,
          embargo_end_date TEXT NOT NULL,
          item_count INTEGER NOT NULL,
          content_hash TEXT NOT NULL,
          sealed INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          PRIMARY KEY (dataset_id, split_name),
          FOREIGN KEY (dataset_id) REFERENCES quant_datasets(dataset_id)
        );
        CREATE TABLE IF NOT EXISTS quant_dataset_items (
          dataset_id TEXT NOT NULL,
          item_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          signal_time TEXT NOT NULL,
          feature_available_at TEXT NOT NULL,
          label_end_time TEXT NOT NULL,
          split_name TEXT NOT NULL,
          feature_json TEXT NOT NULL,
          label_json TEXT NOT NULL,
          feature_hash TEXT NOT NULL,
          label_hash TEXT NOT NULL,
          source_snapshot_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (dataset_id, item_id),
          FOREIGN KEY (dataset_id) REFERENCES quant_datasets(dataset_id)
        );
        CREATE INDEX IF NOT EXISTS idx_quant_dataset_items_split_time
        ON quant_dataset_items(dataset_id, split_name, signal_time, symbol);
        CREATE TABLE IF NOT EXISTS quant_model_artifacts (
          artifact_id TEXT PRIMARY KEY,
          model_name TEXT NOT NULL,
          model_version TEXT NOT NULL,
          dataset_id TEXT NOT NULL,
          split_policy TEXT NOT NULL,
          feature_schema_version TEXT NOT NULL,
          label_schema_version TEXT NOT NULL,
          feature_order_json TEXT NOT NULL,
          train_config_json TEXT NOT NULL,
          random_seed INTEGER NOT NULL,
          environment_json TEXT NOT NULL,
          artifact_json TEXT NOT NULL,
          artifact_hash TEXT NOT NULL UNIQUE,
          test_partition_hash TEXT NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY (dataset_id) REFERENCES quant_datasets(dataset_id)
        );
        CREATE INDEX IF NOT EXISTS idx_quant_model_artifacts_dataset
        ON quant_model_artifacts(dataset_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS quant_model_metrics (
          artifact_id TEXT NOT NULL,
          split_name TEXT NOT NULL,
          metric_name TEXT NOT NULL,
          metric_value REAL,
          details_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (artifact_id, split_name, metric_name),
          FOREIGN KEY (artifact_id) REFERENCES quant_model_artifacts(artifact_id)
        );
        """
    )


def _quant_dataset_checksum() -> str:
    return _checksum(
        "stock_quant_dataset_v0.1|quant_datasets|quant_dataset_partitions|"
        "quant_dataset_items|quant_model_artifacts|quant_model_metrics|sealed_test_partition"
    )


def _migrations() -> tuple[Migration, ...]:
    return (
        Migration(LEGACY_SCHEMA_VERSION, LEGACY_MIGRATION_NAME, _legacy_checksum(), _apply_legacy_schema),
        Migration(2, "explicit_schema_migration_framework", _framework_checksum(), _apply_explicit_framework),
        Migration(3, "data_snapshot_contract", _data_snapshot_checksum(), _apply_data_snapshot_contract),
        Migration(4, "data_trust_registry_and_backfill_contract", _data_trust_checksum(), _apply_data_trust_contract),
        Migration(5, "theme_taxonomy_contract", _theme_taxonomy_checksum(), _apply_theme_taxonomy_contract),
        Migration(6, "capital_rotation_contract", _capital_rotation_checksum(), _apply_capital_rotation_contract),
        Migration(7, "quant_dataset_and_model_artifact_contract", _quant_dataset_checksum(), _apply_quant_dataset_contract),
    )


def schema_fingerprint(conn: sqlite3.Connection) -> tuple[str, int]:
    rows = conn.execute(
        """
        SELECT type, name, COALESCE(sql, '') AS sql
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger', 'view')
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    payload = [dict(row) for row in rows]
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _checksum(encoded), len(payload)


def _record_audit(
    conn: sqlite3.Connection,
    *,
    migration: Migration,
    status: str,
    detail: dict[str, object],
) -> None:
    conn.execute(
        """
        INSERT INTO schema_migration_audit(version, name, checksum, status, detail_json, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            migration.version,
            migration.name,
            migration.checksum,
            status,
            json.dumps(detail, ensure_ascii=True, sort_keys=True),
            _now(),
        ),
    )


def _current_rows(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {
        int(row["version"]): row
        for row in conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    }


def _verify_checksum(conn: sqlite3.Connection, migration: Migration) -> None:
    row = _current_rows(conn).get(migration.version)
    if row is None:
        raise DatabaseMigrationError(f"Migration {migration.version} is missing after apply.")
    columns = _column_names(conn, "schema_migrations")
    if "checksum" not in columns:
        return
    recorded = str(row["checksum"] or "")
    if not recorded:
        conn.execute(
            "UPDATE schema_migrations SET checksum = ?, applied_by = ?, details_json = ? WHERE version = ?",
            (
                migration.checksum,
                "legacy_backfill",
                json.dumps({"checksum_backfilled": True}, ensure_ascii=True),
                migration.version,
            ),
        )
        _record_audit(
            conn,
            migration=migration,
            status="checksum_backfilled",
            detail={"reason": "legacy migration did not carry a checksum"},
        )
        return
    if recorded != migration.checksum:
        raise DatabaseMigrationError(
            f"Migration checksum mismatch for v{migration.version} ({migration.name}). "
            "Restore a verified backup or investigate the migration ledger before proceeding."
        )


def apply_sqlite_migrations(db_path: Path) -> dict[str, object]:
    """Apply the ordered, forward-only SQLite migration ledger."""

    db_path = Path(db_path)
    migrations = _migrations()
    with closing(_open_connection(db_path)) as conn:
        _ensure_legacy_ledger(conn)
        applied_before = _current_rows(conn)
        newly_applied: list[int] = []
        for migration in migrations:
            if migration.version in _current_rows(conn):
                continue
            try:
                # The v1 bootstrap sets WAL mode, which SQLite forbids inside
                # an already-open transaction. Its initializer owns the DDL
                # transaction; every forward migration uses BEGIN IMMEDIATE.
                if migration.version != LEGACY_SCHEMA_VERSION:
                    conn.execute("BEGIN IMMEDIATE")
                migration.apply(conn)
                details = json.dumps(
                    {"forward_only": True, "rollback": "restore_verified_sqlite_backup"},
                    ensure_ascii=True,
                    sort_keys=True,
                )
                if "checksum" in _column_names(conn, "schema_migrations"):
                    conn.execute(
                        """
                        INSERT INTO schema_migrations(
                          version, name, applied_at, rollback_note, checksum, applied_by, details_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            migration.version,
                            migration.name,
                            _now(),
                            "Restore a verified SQLite backup; schema migrations are forward-only.",
                            migration.checksum,
                            "kquant.db.migrations",
                            details,
                        ),
                    )
                else:
                    conn.execute(
                        "INSERT INTO schema_migrations(version, name, applied_at, rollback_note) VALUES (?, ?, ?, ?)",
                        (
                            migration.version,
                            migration.name,
                            _now(),
                            "Restore a verified SQLite backup; schema migrations are forward-only.",
                        ),
                    )
                if _table_exists(conn, "schema_migration_audit"):
                    _record_audit(conn, migration=migration, status="applied", detail={"forward_only": True})
                conn.commit()
                newly_applied.append(migration.version)
            except Exception:
                conn.rollback()
                raise
        for migration in migrations:
            _verify_checksum(conn, migration)
        fingerprint, object_count = schema_fingerprint(conn)
        if _table_exists(conn, "schema_fingerprints"):
            conn.execute(
                """
                INSERT OR IGNORE INTO schema_fingerprints(
                  fingerprint, schema_version, object_count, computed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (fingerprint, LATEST_SCHEMA_VERSION, object_count, _now()),
            )
        conn.commit()
        rows = _current_rows(conn)
        quarantine = []
        if _table_exists(conn, "schema_quarantine"):
            quarantine = [dict(row) for row in conn.execute("SELECT * FROM schema_quarantine ORDER BY object_name").fetchall()]
    return {
        "target": "sqlite",
        "status": "up_to_date",
        "schema_version": LATEST_SCHEMA_VERSION,
        "applied": [dict(rows[migration.version]) for migration in migrations],
        "newly_applied": newly_applied,
        "already_applied": sorted(set(applied_before) & {migration.version for migration in migrations}),
        "schema_fingerprint": fingerprint,
        "schema_object_count": object_count,
        "quarantined_objects": quarantine,
        "rollback": "restore_verified_sqlite_backup",
        "destructive_operations": False,
    }


def inspect_sqlite_migrations(db_path: Path) -> dict[str, object]:
    """Report migration state without creating or changing a database."""

    db_path = Path(db_path)
    if not db_path.exists():
        return {
            "target": "sqlite",
            "status": "initialization_required",
            "schema_version": 0,
            "expected_schema_version": LATEST_SCHEMA_VERSION,
            "database_exists": False,
            "read_only": True,
        }
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "schema_migrations"):
            return {
                "target": "sqlite",
                "status": "legacy_unregistered",
                "schema_version": 0,
                "expected_schema_version": LATEST_SCHEMA_VERSION,
                "database_exists": True,
                "read_only": True,
            }
        rows = _current_rows(conn)
        latest = max(rows) if rows else 0
        fingerprint, object_count = schema_fingerprint(conn)
        checksums_available = "checksum" in _column_names(conn, "schema_migrations")
        expected = {migration.version: migration.checksum for migration in _migrations()}
        checksum_ok = checksums_available and all(
            version in rows and str(rows[version]["checksum"] or "") == checksum
            for version, checksum in expected.items()
        )
        return {
            "target": "sqlite",
            "status": "up_to_date" if latest == LATEST_SCHEMA_VERSION and checksum_ok else "migration_required",
            "schema_version": latest,
            "expected_schema_version": LATEST_SCHEMA_VERSION,
            "database_exists": True,
            "read_only": True,
            "checksum_verified": checksum_ok,
            "applied": [dict(rows[version]) for version in sorted(rows)],
            "schema_fingerprint": fingerprint,
            "schema_object_count": object_count,
        }
    finally:
        conn.close()
