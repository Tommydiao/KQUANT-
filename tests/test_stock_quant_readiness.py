from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kquant.stock_quant_readiness import stock_quant_validation_readiness, stock_quant_window_coverage
from kquant.stock_store import connect


def _insert_candles(
    db_path: Path,
    *,
    symbol: str,
    interval: str,
    stamps: list[datetime],
) -> None:
    with connect(db_path) as conn:
        for stamp in stamps:
            conn.execute(
                """
                INSERT INTO market_candles(
                  symbol, interval, open_time, adjustment_mode, dataset_version,
                  primary_source, provider_symbol, provider_status,
                  freshness_seconds, bar_state, open, high, low, close, volume,
                  fetched_at, first_seen_at, updated_at
                ) VALUES (?, ?, ?, 'provider', 'test', 'longbridge_candles', ?, 'available', 0,
                          'closed_candle', 100, 101, 99, 100, 1000, ?, ?, ?)
                """,
                (symbol, interval, stamp.isoformat(), f"US.{symbol}", stamp.isoformat(), stamp.isoformat(), stamp.isoformat()),
            )
        conn.commit()


def _seed_universe(db_path: Path) -> None:
    with connect(db_path) as conn:
        for rank, symbol in enumerate(("AAA", "BBB"), start=1):
            conn.execute(
                """
                INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at)
                VALUES (?, ?, 'Technology', 'Core', '[]', ?, 1, ?)
                """,
                (symbol, symbol, rank, "2026-01-01T00:00:00+00:00"),
            )
        conn.commit()


def test_validation_window_coverage_is_stricter_than_recent_bar_coverage(tmp_path: Path) -> None:
    db_path = tmp_path / "readiness.sqlite3"
    _seed_universe(db_path)
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 7, 1, tzinfo=UTC)
    daily = [window_start - timedelta(days=221 - index) for index in range(220)] + [window_end]
    confirmation_full = [window_start - timedelta(hours=20 - index) for index in range(20)] + [window_end]
    confirmation_late = [window_start + timedelta(days=1, hours=index) for index in range(20)] + [window_end]
    for symbol in ("AAA", "BBB"):
        _insert_candles(db_path, symbol=symbol, interval="1d", stamps=daily)
    _insert_candles(db_path, symbol="AAA", interval="1h", stamps=confirmation_full)
    _insert_candles(db_path, symbol="BBB", interval="1h", stamps=confirmation_late)

    coverage = stock_quant_window_coverage(
        db_path,
        start_date=window_start.date().isoformat(),
        end_date=window_end.date().isoformat(),
    )

    assert coverage["current_signal_eligible_symbols"] == 2
    assert coverage["validation_window_eligible_symbols"] == 1
    assert coverage["reason_counts"]["confirmation_starts_after_window"] == 1
    assert coverage["reason_counts"]["confirmation_history_below_window_start"] == 1
    by_symbol = {item["symbol"]: item for item in coverage["symbols"]}
    assert by_symbol["AAA"]["validation_window_eligible"] is True
    assert by_symbol["BBB"]["validation_window_eligible"] is False


def test_validation_readiness_is_explicit_before_any_dataset_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "empty-readiness.sqlite3"
    _seed_universe(db_path)

    readiness = stock_quant_validation_readiness(db_path)

    assert readiness["status"] == "not_materialized"
    assert readiness["read_only_research"] is True
