from __future__ import annotations

import asyncio
import statistics
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .market_buffer import MarketDataBuffer
from .market_models import NormalizedMarketEvent
from .market_models import content_hash
from .market_registry import register_market_identity
from .parquet_store import ParquetMarketStore


class MarketDataRuntime:
    def __init__(
        self,
        data_dir: Path,
        *,
        db_path: Path | None = None,
        flush_every: int = 200,
        trade_bucket_seconds: int = 60,
        quote_sample_seconds: float = 5.0,
        ticker_sample_seconds: float = 10.0,
    ):
        self.buffer = MarketDataBuffer()
        self.store = ParquetMarketStore(data_dir)
        self.db_path = db_path
        self._registered_identities: set[tuple[str, str]] = set()
        self.flush_every = max(1, flush_every)
        self.trade_bucket_seconds = max(1, int(trade_bucket_seconds))
        self.quote_sample_seconds = max(0.0, float(quote_sample_seconds))
        self.ticker_sample_seconds = max(0.0, float(ticker_sample_seconds))
        self._pending: list[NormalizedMarketEvent] = []
        self._trade_buckets: dict[str, dict[str, Any]] = {}
        self._last_persisted_quote: dict[tuple[str, str], datetime] = {}
        self._run_started_at = datetime.now(UTC).isoformat()
        self._run_event_count = 0
        self._run_streams: dict[str, dict[str, Any]] = {}
        self._flush_lock = asyncio.Lock()

    async def ingest(self, event: NormalizedMarketEvent) -> None:
        identity_key = (event.venue, event.instrument_id)
        if self.db_path is not None and identity_key not in self._registered_identities:
            await asyncio.to_thread(register_market_identity, self.db_path, event)
            self._registered_identities.add(identity_key)
        self.buffer.ingest(event)
        self._record_run_event(event)
        self._stage_for_persistence(event)
        if len(self._pending) >= self.flush_every:
            await self.flush_async()

    async def flush_async(self) -> list[Path]:
        """Flush storage without blocking the provider/event-loop tasks."""

        async with self._flush_lock:
            return await asyncio.to_thread(self.flush)

    def flush(self, *, force: bool = False) -> list[Path]:
        if force:
            for instrument_id in tuple(self._trade_buckets):
                summary = self._finalize_trade_bucket(instrument_id)
                if summary is not None:
                    self._pending.append(summary)
        if not self._pending:
            return []
        events, self._pending = self._pending, []
        return self.store.write_events(events)

    @staticmethod
    def _event_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _stage_for_persistence(self, event: NormalizedMarketEvent) -> None:
        """Keep high-frequency input in memory but persist bounded evidence.

        The buffer still receives every public trade and quote above, so live
        CVD and freshness remain responsive. The append-only archive stores
        one trade summary per bucket and time-sampled quotes instead of
        millions of tiny raw files per day.
        """

        if event.event_type == "trade":
            self._accumulate_trade(event)
            return
        if event.event_type in {"book_ticker", "ticker"}:
            interval = self.quote_sample_seconds if event.event_type == "book_ticker" else self.ticker_sample_seconds
            key = (event.instrument_id, event.event_type)
            try:
                received = self._event_time(event.received_at)
            except (TypeError, ValueError):
                received = datetime.now(UTC)
            previous = self._last_persisted_quote.get(key)
            if previous is not None and interval > 0 and (received - previous).total_seconds() < interval:
                return
            self._last_persisted_quote[key] = received
            payload = {
                **event.payload,
                "storage_sampling": "time_sampled",
                "storage_sample_seconds": interval,
                "source_event_type": event.event_type,
            }
            self._pending.append(replace(event, payload=payload, content_hash=content_hash(payload)))
            return
        self._pending.append(event)

    def _accumulate_trade(self, event: NormalizedMarketEvent) -> None:
        try:
            source = self._event_time(event.source_time)
        except (TypeError, ValueError):
            source = self._event_time(event.received_at)
        bucket_seconds = self.trade_bucket_seconds
        epoch = int(source.timestamp()) // bucket_seconds * bucket_seconds
        bucket_start = datetime.fromtimestamp(epoch, UTC)
        current = self._trade_buckets.get(event.instrument_id)
        if current is not None and bucket_start < current["bucket_start"]:
            # Late events are already represented by the provider's sequence
            # checks. Do not reopen an old bucket after it was persisted.
            return
        if current is not None and bucket_start > current["bucket_start"]:
            summary = self._finalize_trade_bucket(event.instrument_id)
            if summary is not None:
                self._pending.append(summary)
        current = self._trade_buckets.setdefault(event.instrument_id, {
            "seed": event,
            "bucket_start": bucket_start,
            "last_received_at": event.received_at,
            "trade_count": 0,
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "buy_notional": 0.0,
            "sell_notional": 0.0,
            "max_trade_size": 0.0,
            "trade_sizes": [],
        })
        price = self._number(event.payload.get("price"))
        size = self._number(event.payload.get("size")) or 0.0
        side = str(event.payload.get("side") or "").lower()
        notional = price * size if price is not None else 0.0
        current["trade_count"] += 1
        current["last_received_at"] = max(str(current["last_received_at"]), str(event.received_at))
        current["max_trade_size"] = max(float(current["max_trade_size"]), size)
        if size > 0:
            sizes = current["trade_sizes"]
            baseline = statistics.median(sizes) if sizes else 0.0
            if side == "buy":
                current["buy_volume"] += size
                current["buy_notional"] += notional
            elif side == "sell":
                current["sell_volume"] += size
                current["sell_notional"] += notional
            sizes.append(size)
            if len(sizes) > 2048:
                del sizes[: len(sizes) - 2048]
            current["large_trade_count"] = int(current.get("large_trade_count", 0)) + int(baseline > 0 and size >= baseline * 5)

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _finalize_trade_bucket(self, instrument_id: str) -> NormalizedMarketEvent | None:
        bucket = self._trade_buckets.pop(instrument_id, None)
        if bucket is None:
            return None
        seed = bucket["seed"]
        buy_volume = float(bucket["buy_volume"])
        sell_volume = float(bucket["sell_volume"])
        payload = {
            "interval": f"{self.trade_bucket_seconds}s",
            "closed": True,
            "aggregation": "trade_summary",
            "provenance": "runtime_trade_aggregation",
            "source_event_type": "trade",
            "bucket_start": bucket["bucket_start"].isoformat(),
            "trade_count": int(bucket["trade_count"]),
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "net_volume": buy_volume - sell_volume,
            "buy_notional": float(bucket["buy_notional"]),
            "sell_notional": float(bucket["sell_notional"]),
            "cvd": buy_volume - sell_volume,
            "max_trade_size": float(bucket["max_trade_size"]),
            "large_trade_count": int(bucket.get("large_trade_count", 0)),
        }
        return NormalizedMarketEvent(
            asset_id=seed.asset_id,
            venue=seed.venue,
            instrument_id=seed.instrument_id,
            market_type=seed.market_type,
            event_type="trade_summary",
            source_time=bucket["bucket_start"].isoformat(),
            received_at=str(bucket["last_received_at"]),
            sequence=None,
            provider_status=seed.provider_status,
            content_hash=content_hash(payload),
            payload=payload,
        )

    def snapshot(self, instrument_id: str) -> dict[str, Any]:
        return self.buffer.snapshot(instrument_id)

    def hydrate_recent_closed_klines(self, symbols: tuple[str, ...] | list[str], *, limit_per_instrument: int = 1500) -> dict[str, Any]:
        """Warm the ring buffer from the immutable compacted 1m snapshot."""

        path = self.store.compacted_closed_kline_path
        if not path.exists():
            return {"status": "not_collected", "loaded_events": 0, "symbols": []}
        import duckdb

        wanted = [f"binance:spot:{str(symbol).strip().upper()}" for symbol in symbols if str(symbol).strip()]
        if not wanted:
            return {"status": "not_collected", "loaded_events": 0, "symbols": []}
        placeholders = ",".join("?" for _ in wanted)
        query = f"""
            WITH ranked AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY instrument_id ORDER BY source_time DESC
              ) AS row_number
              FROM read_parquet(?)
              WHERE market_type='spot' AND interval='1m' AND instrument_id IN ({placeholders})
            )
            SELECT asset_id, venue, instrument_id, market_type, source_time,
                   received_at, provider_status, open, high, low, close, volume
            FROM ranked
            WHERE row_number <= ?
            ORDER BY instrument_id, source_time
        """
        with duckdb.connect(database=":memory:") as conn:
            rows = conn.execute(query, [[str(path)], *wanted, max(1, int(limit_per_instrument))]).fetchall()
        events: list[NormalizedMarketEvent] = []
        columns = ("asset_id", "venue", "instrument_id", "market_type", "source_time", "received_at", "provider_status", "open", "high", "low", "close", "volume")
        for row in rows:
            value = dict(zip(columns, row))
            payload = {
                "interval": "1m",
                "open": value["open"],
                "high": value["high"],
                "low": value["low"],
                "close": value["close"],
                "volume": value["volume"],
                "closed": True,
                "provenance": "compacted_parquet_hydration",
            }
            events.append(NormalizedMarketEvent(
                asset_id=str(value["asset_id"]), venue=str(value["venue"]),
                instrument_id=str(value["instrument_id"]), market_type="spot",
                event_type="kline", source_time=str(value["source_time"]),
                received_at=str(value["received_at"]), sequence=None,
                provider_status="historical", content_hash=content_hash(payload),
                payload=payload,
            ))
        loaded = self.buffer.hydrate_closed_klines(events)
        return {
            "status": "available" if loaded else "not_collected",
            "loaded_events": loaded,
            "symbols": sorted({event.instrument_id for event in events}),
            "source": "compacted_closed_klines",
            "path": str(path),
            "limit_per_instrument": limit_per_instrument,
        }

    def coverage(self) -> dict[str, Any]:
        return {
            "storage": self.store.coverage(),
            "in_memory_instruments": self.buffer.instruments(),
            "collection_window": {
                "started_at": self._run_started_at,
                "event_count": self._run_event_count,
                "streams": sorted(self._run_streams.values(), key=lambda item: item["instrument_id"]),
            },
        }

    def query(self, **filters: Any) -> list[dict[str, Any]]:
        self.flush()
        return self.store.query(**filters)

    def _record_run_event(self, event: NormalizedMarketEvent) -> None:
        self._run_event_count += 1
        stream = self._run_streams.setdefault(event.instrument_id, {
            "asset_id": event.asset_id,
            "venue": event.venue,
            "market_type": event.market_type,
            "instrument_id": event.instrument_id,
            "event_count": 0,
            "min_source_time": event.source_time,
            "max_source_time": event.source_time,
            "last_received_at": event.received_at,
            "event_types": [],
        })
        stream["event_count"] += 1
        stream["min_source_time"] = min(stream["min_source_time"], event.source_time)
        stream["max_source_time"] = max(stream["max_source_time"], event.source_time)
        stream["last_received_at"] = max(stream["last_received_at"], event.received_at)
        try:
            start = datetime.fromisoformat(str(stream["min_source_time"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(stream["max_source_time"]).replace("Z", "+00:00"))
            stream["span_hours"] = round((end - start).total_seconds() / 3600.0, 4)
        except (TypeError, ValueError):
            stream["span_hours"] = None
        if event.event_type not in stream["event_types"]:
            stream["event_types"].append(event.event_type)
