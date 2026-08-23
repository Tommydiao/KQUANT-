from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

from .market_buffer import MarketDataBuffer
from .market_models import NormalizedMarketEvent
from .market_models import content_hash
from .market_registry import register_market_identity
from .parquet_store import ParquetMarketStore


class MarketDataRuntime:
    def __init__(self, data_dir: Path, *, db_path: Path | None = None, flush_every: int = 200):
        self.buffer = MarketDataBuffer()
        self.store = ParquetMarketStore(data_dir)
        self.db_path = db_path
        self._registered_identities: set[tuple[str, str]] = set()
        self.flush_every = max(1, flush_every)
        self._pending: list[NormalizedMarketEvent] = []
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
        self._pending.append(event)
        if len(self._pending) >= self.flush_every:
            await self.flush_async()

    async def flush_async(self) -> list[Path]:
        """Flush storage without blocking the provider/event-loop tasks."""

        async with self._flush_lock:
            return await asyncio.to_thread(self.flush)

    def flush(self) -> list[Path]:
        if not self._pending:
            return []
        events, self._pending = self._pending, []
        return self.store.write_events(events)

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
