from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kquant.capital_rotation import _load_daily_rows, latest_capital_rotation, run_capital_rotation
from kquant.stock_store import connect
from kquant.theme_taxonomy import build_theme_taxonomy


def _seed(db_path: Path) -> None:
    symbols = [f"AI{i}" for i in range(1, 9)]
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            [
                (symbol, symbol, "Technology", "AI Chips", '["ai", "liquid"]', index, "2026-01-01T00:00:00+00:00")
                for index, symbol in enumerate(symbols, 1)
            ],
        )
        rows = []
        start = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
        for symbol_index, symbol in enumerate([*symbols, "SPY"]):
            base = 100.0 + symbol_index
            for day in range(45):
                close = base + day * (1.0 if symbol != "SPY" else 0.6)
                open_time = start + timedelta(days=day)
                rows.append(
                    (
                        symbol,
                        "1d",
                        open_time.isoformat(),
                        "unadjusted",
                        "rotation_test_v1",
                        "longbridge_candles",
                        f"US.{symbol}",
                        "available",
                        0,
                        "closed_candle",
                        close - 0.5,
                        close + 1.0,
                        close - 1.0,
                        close,
                        100_000 + symbol_index * 1_000,
                        (open_time + timedelta(hours=7)).isoformat(),
                        (open_time + timedelta(hours=7)).isoformat(),
                        (open_time + timedelta(hours=7)).isoformat(),
                    )
                )
        conn.executemany(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()


def test_capital_rotation_is_point_in_time_and_caps_member_concentration(tmp_path: Path) -> None:
    db_path = tmp_path / "rotation.sqlite3"
    _seed(db_path)
    taxonomy = build_theme_taxonomy(db_path=db_path, as_of_date="2026-02-20")
    assert taxonomy["summary"]["mapped_theme_symbols"] == 8

    first = run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    second = run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    assert first["content_hash"] == second["content_hash"]
    assert first["summary"]["future_data_used"] is False
    ranked = [row for row in first["scores"] if row["score"] is not None]
    assert ranked
    assert all(row["top_member_contribution"] <= 0.15 for row in ranked)
    assert all(not row["features"]["stress_direction_flip"] for row in ranked)
    assert first["summary"]["stress_unreasonable_flips"] == 0

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES ('AI1', '1d', '2026-03-01T14:30:00+00:00', 'unadjusted', 'rotation_test_v1',
              'longbridge_candles', 'US.AI1', 'available', 0, 'closed_candle', 500, 501, 499, 500, 100000,
              '2026-03-01T21:30:00+00:00', '2026-03-01T21:30:00+00:00', '2026-03-01T21:30:00+00:00')
            """
        )
        conn.commit()
    after_future_perturbation = run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    assert after_future_perturbation["content_hash"] == first["content_hash"]
    assert latest_capital_rotation(db_path)["status"] == "materialized"


def test_capital_rotation_uses_market_availability_not_later_local_fetch_time(tmp_path: Path) -> None:
    db_path = tmp_path / "availability.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES ('NVDA', '1d', '2026-01-02T14:30:00+00:00', 'unadjusted', 'test',
              'longbridge_candles', 'US.NVDA', 'available', 0, 'closed_candle', 100, 101, 99, 100, 1000,
              '2026-01-10T21:00:00+00:00', '2026-01-10T21:00:00+00:00', '2026-01-10T21:00:00+00:00')
            """
        )
        conn.commit()

    rows = _load_daily_rows(db_path, {"NVDA"}, datetime(2026, 1, 4, tzinfo=UTC))

    assert len(rows["NVDA"]) == 1


def test_latest_rotation_is_marked_stale_when_taxonomy_run_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "stale-rotation.sqlite3"
    _seed(db_path)
    first_taxonomy = build_theme_taxonomy(db_path=db_path, as_of_date="2026-02-20")
    rotation = run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    assert rotation["summary"]["taxonomy_run_id"] == first_taxonomy["run_id"]

    with connect(db_path) as conn:
        conn.execute("UPDATE stock_universe SET name='Changed after rotation' WHERE symbol='AI1'")
        conn.commit()
    build_theme_taxonomy(db_path=db_path, as_of_date="2026-02-21")

    latest = latest_capital_rotation(db_path)

    assert latest["status"] == "stale_taxonomy"
    assert latest["taxonomy_alignment"]["aligned"] is False
