from __future__ import annotations

from pathlib import Path

from kquant.stock_signals import persist_candles
from kquant.stock_store import connect


def _payload(source_type: str, *, close: float = 101.0) -> dict:
    return {
        "symbol": "NVDA",
        "provider_symbol": "NVDA.US",
        "interval": "1d",
        "source_type": source_type,
        "provider_status": "available",
        "freshness_seconds": 4,
        "adjustment_mode": "unadjusted",
        "dataset_version": "market_data_contract_v1",
        "candles": [
            {
                "open_time": "2026-07-22T13:30:00+00:00",
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": close,
                "volume": 1_500_000,
                "bar_state": "closed_candle",
            }
        ],
    }


def test_canonical_market_candle_store_dedupes_and_preserves_source_lineage(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    persist_candles(db_path, _payload("longbridge_candles"))
    persist_candles(db_path, _payload("longbridge_candles", close=101.5))
    persist_candles(db_path, _payload("yahoo_public_fallback", close=100.75))

    with connect(db_path) as conn:
        canonical = conn.execute(
            """
            SELECT close, primary_source, provider_symbol, adjustment_mode,
                   dataset_version, fetched_at, provider_status
            FROM market_candles
            """
        ).fetchall()
        observations = conn.execute(
            "SELECT source FROM market_candle_observations ORDER BY source"
        ).fetchall()

    assert len(canonical) == 1
    assert canonical[0]["close"] == 101.5
    assert canonical[0]["primary_source"] == "longbridge_candles"
    assert canonical[0]["provider_symbol"] == "NVDA.US"
    assert canonical[0]["adjustment_mode"] == "unadjusted"
    assert canonical[0]["dataset_version"] == "market_data_contract_v1"
    assert canonical[0]["fetched_at"]
    assert canonical[0]["provider_status"] == "available"
    assert [row["source"] for row in observations] == ["longbridge_candles", "yahoo_public_fallback"]


def test_split_like_gap_is_recorded_as_corporate_action_caution(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    first = _payload("longbridge_candles")
    first["candles"][0]["open_time"] = "2026-07-21T13:30:00+00:00"
    first["candles"][0].update({"open": 100.0, "high": 102.0, "low": 99.0, "close": 100.0})
    second = _payload("longbridge_candles", close=50.0)
    second["candles"][0].update({"open": 50.0, "high": 51.0, "low": 49.0})

    persist_candles(db_path, first)
    persist_candles(db_path, second)

    with connect(db_path) as conn:
        event = conn.execute(
            "SELECT action_type, price_ratio, status FROM corporate_action_events"
        ).fetchone()

    assert event["action_type"] == "suspected_split"
    assert event["price_ratio"] == 2.0
    assert event["status"] == "caution"
