from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant_crypto.market_buffer import MarketDataBuffer
from kquant_crypto.market_models import NormalizedMarketEvent, content_hash
from kquant_crypto.market_runtime import MarketDataRuntime


def event(index: int, *, event_type: str = "kline", closed: bool = True, side: str | None = None, size: str = "1") -> NormalizedMarketEvent:
    source = datetime(2026, 8, 22, tzinfo=UTC) + timedelta(minutes=index)
    payload = {
        "interval": "1m",
        "open": str(100 + index),
        "high": str(101 + index),
        "low": str(99 + index),
        "close": str(100.5 + index),
        "volume": "10",
        "closed": closed,
    }
    if event_type == "trade":
        payload = {"price": "100", "size": size, "side": side or "buy"}
    return NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type=event_type,
        source_time=source.isoformat(),
        received_at=(source + timedelta(seconds=1)).isoformat(),
        sequence=index,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def test_forming_candle_is_visible_but_not_history():
    buffer = MarketDataBuffer()
    buffer.ingest(event(0, closed=False))
    snapshot = buffer.snapshot("binance:spot:BTCUSDT", now=datetime(2026, 8, 22, 0, 1, tzinfo=UTC))
    assert snapshot["forming"]["1m"]["closed"] is False
    assert snapshot["closed"]["1m"] is None


def test_clock_skew_status_is_not_presented_as_live():
    buffer = MarketDataBuffer()
    skewed = event(0)
    from dataclasses import replace

    buffer.ingest(replace(skewed, provider_status="clock_skew"))
    snapshot = buffer.snapshot("binance:spot:BTCUSDT")
    assert snapshot["trust"] == "clock_skew"
    assert snapshot["provider_status"] == "clock_skew"


def test_closed_one_minute_bars_aggregate_only_complete_intervals():
    buffer = MarketDataBuffer()
    for index in range(60):
        buffer.ingest(event(index))
    snapshot = buffer.snapshot("binance:spot:BTCUSDT")
    assert snapshot["closed"]["5m"]["component_count"] == 5
    assert snapshot["closed"]["15m"]["component_count"] == 15
    assert snapshot["closed"]["1H"]["component_count"] == 60
    assert snapshot["closed"]["4H"] is None


def test_order_flow_and_bbo_are_transparent():
    buffer = MarketDataBuffer()
    buffer.ingest(event(0, event_type="book_ticker", closed=True))
    buffer.ingest(event(1, event_type="trade", side="buy", size="10"))
    buffer.ingest(event(2, event_type="trade", side="sell", size="4"))
    snapshot = buffer.snapshot("binance:spot:BTCUSDT")
    assert snapshot["order_flow"]["cvd"] == 6
    assert snapshot["last_trade"]["side"] == "sell"


def test_parquet_and_duckdb_round_trip(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=2)
    import asyncio

    async def write():
        await runtime.ingest(event(0))
        await runtime.ingest(event(1))
        await runtime.ingest(event(2))
        runtime.flush()

    asyncio.run(write())
    result = runtime.query(venue="binance", market_type="spot", symbol="BTCUSDT")
    assert len(result) == 3
    assert runtime.coverage()["storage"]["file_count"] >= 1


def test_high_frequency_trades_are_persisted_as_bounded_summaries(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=1, trade_bucket_seconds=60)
    from dataclasses import replace
    import asyncio
    import json

    first = event(0, event_type="trade", side="buy", size="10")
    second = replace(
        event(0, event_type="trade", side="sell", size="4"),
        source_time="2026-08-22T00:00:30+00:00",
        received_at="2026-08-22T00:00:31+00:00",
        sequence=2,
    )
    next_bucket = replace(
        event(0, event_type="trade", side="buy", size="2"),
        source_time="2026-08-22T00:01:00+00:00",
        received_at="2026-08-22T00:01:01+00:00",
        sequence=3,
    )

    async def write():
        await runtime.ingest(first)
        await runtime.ingest(second)
        await runtime.ingest(next_bucket)
        runtime.flush(force=True)

    asyncio.run(write())
    rows = runtime.query(venue="binance", market_type="spot", symbol="BTCUSDT", limit=10)
    summaries = [row for row in rows if row["event_type"] == "trade_summary"]
    assert len(summaries) == 2
    first_payload = json.loads(next(row["payload_json"] for row in summaries if "00:00:00" in row["source_time"]))
    assert first_payload["trade_count"] == 2
    assert first_payload["cvd"] == 6.0
    assert first_payload["provenance"] == "runtime_trade_aggregation"
    assert all(row["event_type"] != "trade" for row in rows)


def test_store_symbol_filter_is_bounded_to_requested_partition(tmp_path):
    runtime = MarketDataRuntime(tmp_path / "data", flush_every=100)

    async def write():
        await runtime.ingest(event(0))
        other = event(1)
        from dataclasses import replace

        await runtime.ingest(replace(other, instrument_id="binance:spot:ETHUSDT", asset_id="asset:eth"))
        runtime.flush()

    import asyncio
    asyncio.run(write())
    store = runtime.store
    paths = store.files(venue="binance", market_type="spot", symbols=("BTCUSDT",))
    assert paths
    assert all("symbol=BTCUSDT" in path.parts for path in paths)
