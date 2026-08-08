from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kquant.data_coverage import api_stock_data_coverage
from kquant.stock_store import connect


def test_data_coverage_requires_longbridge_and_required_bar_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "coverage.sqlite3"
    start = datetime(2025, 1, 1, tzinfo=UTC)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("NVDA", "NVIDIA", "Technology", "Chips", "[]", 1, 1, start.isoformat()))
        for interval, count in (("1d", 220), ("1h", 20)):
            for index in range(count):
                stamp = start + timedelta(days=index) if interval == "1d" else start + timedelta(hours=index)
                conn.execute(
                    """
                        INSERT INTO market_candles(symbol, interval, open_time, adjustment_mode, dataset_version, primary_source, provider_symbol,
                          provider_status, freshness_seconds, bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at)
                        VALUES (?, ?, ?, 'provider', 'test', 'longbridge_candles', 'US.NVDA', 'available', 0, 'closed_candle', 100, 101, 99, 100, 1000, ?, ?, ?)
                    """,
                    ("NVDA", interval, stamp.isoformat(), start.isoformat(), start.isoformat(), start.isoformat()),
                )
        conn.commit()
    payload = api_stock_data_coverage(db_path)
    nvda = payload["symbols"][0]

    assert nvda["eligible_for_canonical_validation"] is True
    assert payload["interval_summary"]["1d"]["longbridge_eligible_symbols"] == 1
    assert payload["event_calendar"]["trade_eligible"] is False
