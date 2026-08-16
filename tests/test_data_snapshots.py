from __future__ import annotations

from pathlib import Path

from kquant.data_snapshots import create_market_data_snapshot, read_data_snapshot
from kquant.stock_store import connect
from kquant.universe_store import persist_universe_snapshot, resolve_universe_membership


def _insert_candle(
    db_path: Path,
    *,
    symbol: str,
    source: str,
    open_time: str,
    fetched_at: str,
    bar_state: str = "closed_candle",
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_candles(
              symbol, interval, open_time, adjustment_mode, dataset_version,
              primary_source, provider_symbol, provider_status, freshness_seconds,
              bar_state, open, high, low, close, volume, fetched_at, first_seen_at, updated_at
            ) VALUES (?, '1d', ?, 'unadjusted', 'snapshot-test', ?, ?, 'available', 0, ?, 100, 101, 99, 100, 1000, ?, ?, ?)
            """,
            (symbol, open_time, source, f"US.{symbol}", bar_state, fetched_at, fetched_at, fetched_at),
        )
        conn.commit()


def test_snapshot_is_reproducible_and_future_or_forming_candles_do_not_enter(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshots.sqlite3"
    _insert_candle(
        db_path,
        symbol="NVDA",
        source="longbridge_candles",
        open_time="2026-01-02T14:30:00+00:00",
        fetched_at="2026-01-02T21:00:00+00:00",
    )
    _insert_candle(
        db_path,
        symbol="NVDA",
        source="longbridge_candles",
        open_time="2026-01-03T14:30:00+00:00",
        fetched_at="2026-01-03T15:00:00+00:00",
        bar_state="forming_candle",
    )
    cutoff = "2026-01-05T00:00:00+00:00"
    first = create_market_data_snapshot(db_path, symbol="NVDA", intervals=["1d"], as_of_time=cutoff)

    _insert_candle(
        db_path,
        symbol="NVDA",
        source="longbridge_candles",
        open_time="2026-01-08T14:30:00+00:00",
        fetched_at="2026-01-08T21:00:00+00:00",
    )
    repeated = create_market_data_snapshot(db_path, symbol="NVDA", intervals=["1d"], as_of_time=cutoff)

    assert first["snapshot_id"] == repeated["snapshot_id"]
    assert first["content_hash"] == repeated["content_hash"]
    assert first["eligibility_status"] == "eligible"
    assert first["item_count"] == 1
    assert first["details"]["exclusions"]["forming_or_unknown_bar_state"] == 1
    assert first["items"][0]["available_at"] == "2026-01-02T21:00:00+00:00"
    assert read_data_snapshot(db_path, snapshot_id=first["snapshot_id"])["items"] == first["items"]


def test_yahoo_reference_snapshot_is_retained_but_ineligible(tmp_path: Path) -> None:
    db_path = tmp_path / "reference.sqlite3"
    _insert_candle(
        db_path,
        symbol="SPY",
        source="live_yahoo_chart",
        open_time="2026-01-02T14:30:00+00:00",
        fetched_at="2026-01-02T21:00:00+00:00",
    )

    snapshot = create_market_data_snapshot(
        db_path,
        symbol="SPY",
        intervals=["1d"],
        as_of_time="2026-01-03T00:00:00+00:00",
    )

    assert snapshot["eligibility_status"] == "reference_only"
    assert snapshot["details"]["eligible_for_model"] is False
    assert snapshot["items"][0]["source"] == "live_yahoo_chart"
    assert snapshot["items"][0]["exclusion_reason"] == "reference_source"


def test_universe_resolution_never_backfills_membership_from_the_future(tmp_path: Path) -> None:
    db_path = tmp_path / "universe.sqlite3"
    persist_universe_snapshot(
        db_path,
        universe="default",
        as_of_date="2026-01-10",
        recorded_at="2026-01-10T22:00:00+00:00",
        stocks=[{"symbol": "NVDA", "name": "NVIDIA", "sector": "Technology", "layer": "Chips", "tags": ["ai"], "rank": 1}],
    )

    before = resolve_universe_membership(db_path, universe="default", as_of_date="2026-01-09")
    after = resolve_universe_membership(db_path, universe="default", as_of_date="2026-01-12")

    assert before["resolution"] == "unavailable"
    assert before["membership_count"] == 0
    assert after["resolution"] == "latest_prior_observation"
    assert after["members"][0]["symbol"] == "NVDA"
    assert after["survivorship_limited"] is True
    assert after["eligible_for_model"] is False
