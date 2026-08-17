from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kquant.capital_rotation import run_capital_rotation
from kquant.leadership import latest_leadership, run_leadership, theme_leaders
from kquant.stock_store import connect
from kquant.theme_taxonomy import build_theme_taxonomy


def _seed(db_path: Path) -> None:
    symbols = [f"AI{i}" for i in range(1, 9)]
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            [(symbol, symbol, "Technology", "AI Chips", '["ai", "liquid"]', index, "2026-01-01T00:00:00+00:00") for index, symbol in enumerate(symbols, 1)],
        )
        rows = []
        start = datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
        for symbol_index, symbol in enumerate([*symbols, "SPY"]):
            base = 100.0 + symbol_index
            for day in range(45):
                slope = 1.0 + (symbol_index % 3) * 0.2 if symbol != "SPY" else 0.6
                close = base + day * slope
                open_time = start + timedelta(days=day)
                rows.append((symbol, "1d", open_time.isoformat(), "unadjusted", "leadership_test_v1", "longbridge_candles", f"US.{symbol}", "available", 0, "closed_candle", close - 0.5, close + 1.0, close - 1.0, close, 100_000 + symbol_index * 1_000, (open_time + timedelta(hours=7)).isoformat(), (open_time + timedelta(hours=7)).isoformat(), (open_time + timedelta(hours=7)).isoformat()))
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


def test_leadership_is_same_timestamp_and_has_explanations(tmp_path: Path) -> None:
    db_path = tmp_path / "leadership.sqlite3"
    _seed(db_path)
    build_theme_taxonomy(db_path=db_path, as_of_date="2026-02-20")
    rotation = run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    result = run_leadership(db_path)
    assert result["status"] == "materialized"
    assert result["rotation_run_id"] == rotation["run_id"]
    assert result["summary"]["future_prediction_used"] is False
    assert result["summary"]["future_data_used"] is False
    assert len(result["leaders"]) == 8
    assert {row["state"] for row in result["leaders"]} <= {"Leader", "Emerging", "Neutral", "Weakening"}
    assert all(row["features"]["as_of_time"] == "2026-02-20T23:00:00+00:00" for row in result["leaders"])
    assert all({"theme_relative_strength", "market_relative_strength", "volume_confirmation", "persistence_score"} <= set(row) for row in result["leaders"])
    assert latest_leadership(db_path)["content_hash"] == result["content_hash"]
    assert len(theme_leaders(db_path, "theme.ai_infrastructure")["leaders"]) == 8


def test_future_candles_do_not_change_leadership_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "leadership-pit.sqlite3"
    _seed(db_path)
    build_theme_taxonomy(db_path=db_path, as_of_date="2026-02-20")
    run_capital_rotation(db_path=db_path, as_of_time="2026-02-20T23:00:00+00:00")
    before = run_leadership(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES ('AI1', '1d', '2026-03-01T14:30:00+00:00', 'unadjusted', 'leadership_test_v1',
              'longbridge_candles', 'US.AI1', 'available', 0, 'closed_candle', 500, 501, 499, 500, 100000,
              '2026-03-01T21:30:00+00:00', '2026-03-01T21:30:00+00:00', '2026-03-01T21:30:00+00:00')
            """
        )
        conn.commit()
    after = run_leadership(db_path)
    assert after["content_hash"] == before["content_hash"]
