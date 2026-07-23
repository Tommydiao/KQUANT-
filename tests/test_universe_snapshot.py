from __future__ import annotations

from pathlib import Path

from kquant.stock_signals import api_stock_universe
from kquant.stock_store import connect
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
