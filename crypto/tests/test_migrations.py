from __future__ import annotations

import sqlite3

from kquant_crypto.db.migrations import LATEST_SCHEMA_VERSION, migration_status, migrate, schema_fingerprint


def test_empty_database_migrates_and_records_evaluation_schema(settings):
    status = migrate(settings.db_path)
    assert status["status"] == "ready"
    assert status["current_version"] == LATEST_SCHEMA_VERSION
    assert LATEST_SCHEMA_VERSION == 21
    with sqlite3.connect(settings.db_path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "crypto_trade_plan_drafts",
        "crypto_evaluation_runs",
        "crypto_evaluation_blockers",
        "crypto_execution_intents",
        "crypto_exchange_orders",
        "crypto_reconciliation_runs",
        "crypto_kill_switch_events",
        "crypto_market_scan_runs",
        "crypto_opportunity_candidates",
        "crypto_exchange_account_events",
        "crypto_universe_instrument_memberships",
        "crypto_model_evidence_packets",
    } <= names


def test_migration_is_idempotent_and_fingerprint_stable(settings):
    first = migration_status(settings.db_path)
    migrate(settings.db_path)
    second = migration_status(settings.db_path)
    assert first["fingerprint"] == second["fingerprint"] == schema_fingerprint(__import__("kquant_crypto.db.migrations", fromlist=["connect"]).connect(settings.db_path))
    assert len(second["migrations"]) == LATEST_SCHEMA_VERSION
