from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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


def test_corrupt_incremental_index_is_not_replaced_by_current_write_batch(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    first = NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="trade",
        source_time="2026-08-22T00:00:00+00:00",
        received_at="2026-08-22T00:00:01+00:00",
        sequence=1,
        provider_status="live",
        content_hash="first",
        payload={"price": 1},
    )
    second = NormalizedMarketEvent(
        **{**first.__dict__, "source_time": "2026-08-22T00:00:01+00:00", "received_at": "2026-08-22T00:00:02+00:00", "sequence": 2, "content_hash": "second"},
    )
    store.write_events([first])
    index_path = tmp_path / "data" / "market" / "_coverage_index.json"
    index_path.write_bytes(b"\x00corrupt")

    store.write_events([second])

    assert index_path.read_bytes() == b"\x00corrupt"
    assert len(store.files(venue="binance", market_type="spot", symbols=["BTCUSDT"])) == 2


def test_coverage_rebuild_isolates_an_unreadable_parquet_file(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    store.write_events([
        NormalizedMarketEvent(
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
    ])
    broken = tmp_path / "data" / "market" / "venue=binance" / "market_type=spot" / "symbol=BAD" / "date=2026-08-22" / "events-broken.parquet"
    broken.parent.mkdir(parents=True)
    broken.write_bytes(b"PAR1partial")
    (tmp_path / "data" / "market" / "_coverage_index.json").unlink()

    rebuilt = store.rebuild_coverage_index()

    assert rebuilt["coverage_index_status"] == "partial"
    assert rebuilt["event_count"] == 1
    assert rebuilt["unreadable_file_count"] == 1
    assert rebuilt["raw_index_repair_required"] is True
    assert rebuilt["unreadable_files"][0]["reason"] == "file_too_small"


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


def test_corrupt_coverage_index_recovers_from_compacted_snapshot(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    store.write_events([
        NormalizedMarketEvent(
            asset_id="asset:btc",
            venue="binance",
            instrument_id="binance:spot:BTCUSDT",
            market_type="spot",
            event_type="kline",
            source_time="2026-08-22T00:00:00+00:00",
            received_at="2026-08-22T00:00:01+00:00",
            sequence=None,
            provider_status="closed",
            content_hash="kline",
            payload={
                "interval": "1m",
                "closed": True,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 10,
            },
        )
    ])
    store.compact_closed_klines(venue="binance", market_type="spot", symbols=["BTCUSDT"])
    (tmp_path / "data" / "market" / "_coverage_index.json").write_bytes(b"\x00" * 128)

    coverage = store.coverage()

    assert coverage["coverage_index_status"] == "recovered_compacted"
    assert coverage["coverage_index_issue"] == "nul_bytes"
    assert coverage["raw_index_repair_required"] is True
    assert coverage["streams"][0]["instrument_id"] == "binance:spot:BTCUSDT"
    assert coverage["streams"][0]["coverage_basis"] == "compacted_closed_klines"


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


def test_scoped_coverage_rebuild_writes_fragment_and_safe_merge(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    store.write_events([
        NormalizedMarketEvent(
            asset_id="asset:btc",
            venue="binance",
            instrument_id="binance:spot:BTCUSDT",
            market_type="spot",
            event_type="trade",
            source_time="2026-08-22T00:00:00+00:00",
            received_at="2026-08-22T00:00:01+00:00",
            sequence=1,
            provider_status="live",
            content_hash="btc",
            payload={"price": 1},
        ),
        NormalizedMarketEvent(
            asset_id="asset:eth",
            venue="okx",
            instrument_id="okx:perpetual:ETHUSDT",
            market_type="perpetual",
            event_type="trade",
            source_time="2026-08-22T00:00:00+00:00",
            received_at="2026-08-22T00:00:01+00:00",
            sequence=2,
            provider_status="live",
            content_hash="eth",
            payload={"price": 2},
        ),
    ])
    (tmp_path / "data" / "market" / "_coverage_index.json").write_bytes(b"corrupt")

    fragment = store.rebuild_coverage_index(venue="binance", market_type="spot", symbols=["BTCUSDT"], batch_size=1)

    assert fragment["scan_status"] == "complete"
    assert fragment["published_fragment"]
    assert fragment["scope"]["symbols"] == ["BTCUSDT"]
    assert (tmp_path / "data" / "market" / "_coverage_index.json").read_bytes() == b"corrupt"

    scopes = store.coverage_scope_manifest()
    merged = store.merge_coverage_fragments(scope_manifest=scopes, publish=True)
    assert merged["status"] == "partial"
    assert merged["published"] is False
    assert merged["missing_scope_keys"]
    assert (tmp_path / "data" / "market" / "_coverage_index.json").read_bytes() == b"corrupt"

    store.rebuild_coverage_index(venue="okx", market_type="perpetual", symbols=["ETHUSDT"], batch_size=1)
    merged = store.merge_coverage_fragments(scope_manifest=scopes, publish=True)
    assert merged["status"] == "complete"
    assert merged["published"] is True
    assert store.coverage()["coverage_index_status"] == "complete"
    assert store.coverage()["event_count"] == 2


def test_scoped_coverage_fragments_can_scan_in_parallel_without_manifest_collision(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    store.write_events([
        NormalizedMarketEvent(
            asset_id="asset:btc",
            venue="binance",
            instrument_id="binance:spot:BTCUSDT",
            market_type="spot",
            event_type="trade",
            source_time="2026-08-22T00:00:00+00:00",
            received_at="2026-08-22T00:00:01+00:00",
            sequence=1,
            provider_status="live",
            content_hash="btc",
            payload={"price": 1},
        ),
        NormalizedMarketEvent(
            asset_id="asset:eth",
            venue="okx",
            instrument_id="okx:perpetual:ETHUSDT",
            market_type="perpetual",
            event_type="trade",
            source_time="2026-08-22T00:00:00+00:00",
            received_at="2026-08-22T00:00:01+00:00",
            sequence=2,
            provider_status="live",
            content_hash="eth",
            payload={"price": 2},
        ),
    ])
    scopes = [
        {"venue": "binance", "market_type": "spot", "symbols": ["BTCUSDT"]},
        {"venue": "okx", "market_type": "perpetual", "symbols": ["ETHUSDT"]},
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda scope: store.rebuild_coverage_index(**scope, batch_size=1, lock=False),
            scopes,
        ))
    assert [item["scan_status"] for item in results] == ["complete", "complete"]
    assert len(list((tmp_path / "data" / "market" / "_coverage_fragments").glob("coverage-*.json"))) == 2


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
