from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from kquant_crypto.historical_dataset import load_parquet_validation_dataset
from kquant_crypto.market_models import NormalizedMarketEvent, content_hash
from kquant_crypto.market_runtime import MarketDataRuntime
from kquant_crypto.parquet_store import ParquetMarketStore


def _event(index: int, *, closed: bool = True) -> NormalizedMarketEvent:
    source = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(minutes=index)
    payload = {
        "interval": "1m",
        "open": str(100 + index),
        "high": str(101 + index),
        "low": str(99 + index),
        "close": str(100.5 + index),
        "volume": "10",
        "closed": closed,
    }
    return NormalizedMarketEvent(
        asset_id="asset:sol",
        venue="binance",
        instrument_id="binance:spot:SOLUSDT",
        market_type="spot",
        event_type="kline",
        source_time=source.isoformat(),
        received_at=(source + timedelta(seconds=1)).isoformat(),
        sequence=index,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def test_loader_uses_closed_parquet_bars_and_reports_exclusions(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        for index in range(3):
            await runtime.ingest(_event(index))
        await runtime.ingest(_event(3, closed=False))
        runtime.flush()

    asyncio.run(write())
    dataset = load_parquet_validation_dataset(tmp_path / "data", symbols=("SOLUSDT",), min_bars=2)

    assert len(dataset.series) == 1
    assert len(dataset.series[0].bars) == 3
    assert dataset.coverage["source"] == "parquet:binance:spot"
    assert dataset.coverage["dataset_hash"]


def test_loader_does_not_promote_short_history_to_validation(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        await runtime.ingest(_event(0))
        runtime.flush()

    asyncio.run(write())
    dataset = load_parquet_validation_dataset(tmp_path / "data", symbols=("SOLUSDT",), min_bars=55)

    assert dataset.series == ()
    assert dataset.excluded[0]["reason"] == "insufficient_closed_bars"


def test_compacted_closed_kline_snapshot_is_used_for_validation(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        for index in range(3):
            await runtime.ingest(_event(index))
        runtime.flush()

    asyncio.run(write())
    store = ParquetMarketStore(tmp_path / "data")
    manifest = store.compact_closed_klines()
    assert manifest["status"] == "available"
    dataset = load_parquet_validation_dataset(tmp_path / "data", symbols=("SOLUSDT",), min_bars=2)
    assert dataset.coverage["storage_mode"] == "compacted_closed_klines"
    assert len(dataset.series[0].bars) == 3


def test_compacted_snapshots_are_partitioned_by_interval(tmp_path):
    store = ParquetMarketStore(tmp_path / "data")
    assert store.compacted_closed_kline_path_for("1m") == store.compacted_closed_kline_path
    assert store.compacted_closed_kline_path_for("1h").name == "closed_klines_1h.parquet"
    assert store.compacted_closed_kline_manifest_path_for("15m").name == "closed_klines_15m.manifest.json"


def test_loader_uses_native_compacted_interval_when_available(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        for index in (0, 15):
            base = _event(index)
            payload = {**base.payload, "interval": "15m"}
            await runtime.ingest(replace(base, payload=payload, content_hash=content_hash(payload)))
        runtime.flush()

    asyncio.run(write())
    store = ParquetMarketStore(tmp_path / "data")
    store.compact_closed_klines(interval="15m")
    dataset = load_parquet_validation_dataset(tmp_path / "data", symbols=("SOLUSDT",), interval="15m", min_bars=2)
    assert dataset.coverage["source_interval"] == "15m"
    assert len(dataset.series[0].bars) == 2


def test_symbol_compaction_merges_into_existing_interval_snapshot(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        from dataclasses import replace

        await runtime.ingest(_event(0))
        eth = _event(0)
        await runtime.ingest(replace(eth, asset_id="asset:eth", instrument_id="binance:spot:ETHUSDT"))
        runtime.flush()

    asyncio.run(write())
    store = ParquetMarketStore(tmp_path / "data")
    store.compact_closed_klines(interval="1m")
    store.compact_closed_klines(interval="1m", symbols=("SOLUSDT",))
    dataset = load_parquet_validation_dataset(tmp_path / "data", interval="1m", min_bars=1)
    assert sorted(item.symbol for item in dataset.series) == ["ETHUSDT", "SOLUSDT"]


def test_loader_aggregates_closed_one_minute_bars_without_future_rows(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        for index in range(4):
            await runtime.ingest(_event(index))
        runtime.flush()

    asyncio.run(write())
    store = ParquetMarketStore(tmp_path / "data")
    store.compact_closed_klines()

    dataset = load_parquet_validation_dataset(tmp_path / "data", symbols=("SOLUSDT",), interval="2m", min_bars=2)

    assert len(dataset.series) == 1
    assert len(dataset.series[0].bars) == 2
    assert dataset.coverage["interval"] == "2m"
    assert dataset.coverage["source_interval"] == "1m"
    assert dataset.series[0].bars[0].open == 100.0
    assert dataset.series[0].bars[0].close == 101.5
