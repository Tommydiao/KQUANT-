from __future__ import annotations

from kquant_crypto.market_models import NormalizedMarketEvent
from kquant_crypto.parquet_store import ParquetMarketStore


def test_parquet_writer_uses_atomic_file_and_reads_back(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    event = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:00+00:00",
        sequence=1,
        provider_status="live",
        content_hash="hash",
        payload={"price": "1"},
    )
    files = store.write_events([event])
    assert len(files) == 1
    assert files[0].suffix == ".parquet"
    assert not list(files[0].parent.glob("*.tmp"))
    coverage = store.coverage()
    assert coverage["event_count"] == 1
    assert coverage["streams"][0]["instrument_id"] == "binance:spot:BTCUSDT"
    assert coverage["streams"][0]["span_hours"] == 0.0


def test_coverage_index_can_be_rebuilt_after_legacy_collection(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    event = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:00+00:00",
        sequence=1,
        provider_status="live",
        content_hash="hash",
        payload={"price": "1"},
    )
    store.write_events([event])
    (tmp_path / "data" / "market" / "_coverage_index.json").unlink()

    rebuilt = store.rebuild_coverage_index()

    assert rebuilt["coverage_index_status"] == "complete"
    assert rebuilt["event_count"] == 1
    assert rebuilt["streams"][0]["instrument_id"] == "binance:spot:BTCUSDT"


def test_coverage_uses_incremental_index_without_scanning_raw_files(tmp_path, monkeypatch):
    store = ParquetMarketStore(tmp_path / "data")
    event = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:00+00:00",
        sequence=1,
        provider_status="live",
        content_hash="hash",
        payload={"price": "1"},
    )
    store.write_events([event])
    monkeypatch.setattr(store, "files", lambda: (_ for _ in ()).throw(AssertionError("raw scan")))

    coverage = store.coverage()

    assert coverage["coverage_index_status"] == "complete"
    assert coverage["file_count"] == 1
    assert coverage["event_count"] == 1


def test_files_can_narrow_compaction_scope(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    spot = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:00+00:00",
        sequence=1,
        provider_status="live",
        content_hash="spot",
        payload={"price": "1"},
    )
    perpetual = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:perpetual:BTCUSDT",
        market_type="perpetual",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:00+00:00",
        sequence=1,
        provider_status="live",
        content_hash="perpetual",
        payload={"price": "1"},
    )
    store.write_events([spot, perpetual])
    assert len(store.files(venue="binance", market_type="spot")) == 1
    assert len(store.files(venue="binance", market_type="perpetual")) == 1


def test_query_handles_mixed_optional_sequence_schema(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    first = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-23T00:00:00+00:00",
        received_at="2026-08-23T00:00:01+00:00",
        sequence=None,
        provider_status="live",
        content_hash="old",
        payload={"price": 1},
    )
    second = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-23T00:00:02+00:00",
        received_at="2026-08-23T00:00:03+00:00",
        sequence=2,
        provider_status="live",
        content_hash="new",
        payload={"price": 2},
    )
    store.write_events([first])
    store.write_events([second])

    rows = store.query(venue="binance", market_type="spot", symbol="BTCUSDT", limit=10)
    assert len(rows) == 2
    assert {row["sequence"] for row in rows} == {None, 2}


def test_derivative_compaction_keeps_latest_source_row(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    base = {
        "asset_id": "asset:btc",
        "venue": "binance",
        "instrument_id": "binance:perpetual:BTCUSDT",
        "market_type": "perpetual",
        "sequence": None,
        "provider_status": "historical",
    }
    store.write_events([
        NormalizedMarketEvent(
            **base,
            event_type="funding_rate",
            source_time="2026-08-23T00:00:00+00:00",
            received_at="2026-08-23T00:01:00+00:00",
            content_hash="funding-old",
            payload={
                "funding_rate": 0.001,
                "available_at": "2026-08-23T00:00:00+00:00",
                "provenance": "historical_rest_replay",
            },
        ),
        NormalizedMarketEvent(
            **base,
            event_type="funding_rate",
            source_time="2026-08-23T00:00:00+00:00",
            received_at="2026-08-23T00:02:00+00:00",
            content_hash="funding-new",
            payload={
                "funding_rate": 0.002,
                "available_at": "2026-08-23T00:00:00+00:00",
                "provenance": "historical_rest_replay",
            },
        ),
        NormalizedMarketEvent(
            **base,
            event_type="open_interest",
            source_time="2026-08-23T01:00:00+00:00",
            received_at="2026-08-23T01:01:00+00:00",
            content_hash="oi",
            payload={
                "open_interest": 42,
                "open_interest_value": 4200,
                "available_at": "2026-08-23T01:00:00+00:00",
                "provenance": "historical_rest_replay",
            },
        ),
    ])

    manifest = store.compact_derivative_snapshots(symbols=["BTCUSDT"])

    assert manifest["status"] == "available"
    assert manifest["row_count"] == 2
    import duckdb

    with duckdb.connect(database=":memory:") as conn:
        rows = conn.execute(
            "SELECT event_type, funding_rate, open_interest, provenance FROM read_parquet(?) ORDER BY event_type",
            [[str(store.compacted_derivative_path)]],
        ).fetchall()
    assert rows == [
        ("funding_rate", 0.002, None, "historical_rest_replay"),
        ("open_interest", None, 42.0, "historical_rest_replay"),
    ]
