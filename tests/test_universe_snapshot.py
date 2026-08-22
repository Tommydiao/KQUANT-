from __future__ import annotations

import json
from pathlib import Path

from kquant.stock_signals import api_stock_universe
from kquant.stock_store import connect
from kquant.universe_registry import (
    ensure_current_universe_registry,
    ensure_stock_universe_catalog,
    restore_universe_from_registry,
)
from kquant.universe_store import persist_universe_snapshot, universe_snapshot_status


def test_universe_snapshot_is_immutable_and_labels_missing_history(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    stocks = [
        {"symbol": "NVDA", "name": "NVIDIA", "sector": "Technology", "layer": "AI", "tags": ["ai"], "rank": 1},
        {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "sector": "ETF", "layer": "Index", "tags": ["index"], "rank": 2},
    ]

    first = persist_universe_snapshot(
        db_path, universe="default", as_of_date="2026-07-23", stocks=stocks, recorded_at="2026-07-23T12:00:00+00:00"
    )
    repeated = persist_universe_snapshot(
        db_path, universe="default", as_of_date="2026-07-23", stocks=stocks, recorded_at="2026-07-23T12:01:00+00:00"
    )

    assert repeated["definition_hash"] == first["definition_hash"]
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stock_universe_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM stock_universe_memberships").fetchone()[0] == 2

    today = universe_snapshot_status(db_path, universe="default", as_of_date="2026-07-23")
    older = universe_snapshot_status(db_path, universe="default", as_of_date="2024-07-23")
    assert today["exact_snapshot_available"] is True
    assert older["exact_snapshot_available"] is False
    assert older["survivorship_limited"] is True
    assert older["historical_membership_complete"] is False


def test_api_universe_records_the_current_runtime_snapshot(tmp_path: Path) -> None:
    payload = api_stock_universe("default", db_path=tmp_path / "kquant.sqlite3")

    point_in_time = payload["point_in_time"]
    assert point_in_time["current_snapshot"]["membership_count"] == payload["count"]
    assert point_in_time["exact_snapshot_available"] is True
    assert point_in_time["survivorship_limited"] is True


def test_api_universe_read_does_not_rewrite_canonical_registry(tmp_path: Path) -> None:
    db_path = tmp_path / "read-only-universe.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO stock_universe(
              symbol, name, sector, layer, tags_json, rank, active, updated_at
            ) VALUES ('LOCAL', 'Local addition', 'Technology', 'Research', '["local"]', 999, 1, '2026-01-01T00:00:00+00:00')
            """
        )
        conn.commit()

    before = ensure_current_universe_registry(db_path)
    with connect(db_path) as conn:
        before_row = dict(conn.execute("SELECT * FROM stock_universe WHERE symbol='LOCAL'").fetchone())

    payload = api_stock_universe("default", db_path=db_path)

    after = ensure_current_universe_registry(db_path)
    with connect(db_path) as conn:
        after_row = dict(conn.execute("SELECT * FROM stock_universe WHERE symbol='LOCAL'").fetchone())

    assert payload["count"] == 200
    assert after["registry_id"] == before["registry_id"]
    assert after["content_hash"] == before["content_hash"]
    assert after_row == before_row


def test_catalog_bootstrap_is_explicit_and_does_not_replace_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "catalog.sqlite3"

    seeded = ensure_stock_universe_catalog(db_path)
    repeated = ensure_stock_universe_catalog(db_path)

    assert seeded["status"] == "seeded"
    assert seeded["active_symbols"] == 264
    assert repeated["status"] == "existing"
    assert repeated["inserted_symbols"] == 0

    with connect(db_path) as conn:
        row_before = dict(conn.execute("SELECT * FROM stock_universe WHERE symbol='NVDA'").fetchone())
        conn.execute("UPDATE stock_universe SET name='Locally curated NVDA' WHERE symbol='NVDA'")
        conn.commit()

    preserved = ensure_stock_universe_catalog(db_path)
    with connect(db_path) as conn:
        row_after = dict(conn.execute("SELECT * FROM stock_universe WHERE symbol='NVDA'").fetchone())

    assert preserved["status"] == "existing"
    assert row_before["name"] != row_after["name"]
    assert row_after["name"] == "Locally curated NVDA"


def test_registry_repair_restores_a_sealed_version_and_records_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "repair.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES ('TEST', 'Original', 'Tech', 'Core', '[]', 1, 1, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    original = ensure_current_universe_registry(db_path)
    with connect(db_path) as conn:
        conn.execute("UPDATE stock_universe SET name='Drifted' WHERE symbol='TEST'")
        conn.commit()
    drifted = ensure_current_universe_registry(db_path)

    repaired = restore_universe_from_registry(db_path, original["registry_id"], reason="test repair")

    assert drifted["registry_id"] != original["registry_id"]
    assert repaired["status"] == "repaired"
    assert repaired["after_hash"] == original["content_hash"]
    assert ensure_current_universe_registry(db_path)["registry_id"] == original["registry_id"]
    with connect(db_path) as conn:
        row = conn.execute("SELECT name FROM stock_universe WHERE symbol='TEST'").fetchone()
        audit = conn.execute(
            "SELECT payload_json FROM audit_events WHERE event_type='universe_registry_repair' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["name"] == "Original"
    assert json.loads(audit["payload_json"])["registry_id"] == original["registry_id"]
