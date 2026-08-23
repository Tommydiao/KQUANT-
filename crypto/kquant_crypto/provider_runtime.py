from __future__ import annotations

import asyncio
from dataclasses import replace
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ProviderFlags, Settings
from .clock_sync import calibrate_provider_clock
from .db.migrations import connect, migrate
from .market_models import NormalizedMarketEvent, ProviderHealth, SequenceTracker
from .providers import BinancePublicAdapter, CoinbasePublicAdapter, KrakenPublicAdapter, OKXPublicAdapter


def provider_health(settings: Settings, supervisor: "ProviderSupervisor | None" = None) -> dict[str, dict[str, Any]]:
    if supervisor is not None:
        return {name: value.as_dict() for name, value in supervisor.health.items()}
    return {
        name: ProviderHealth(name, enabled, status="disabled" if not enabled else "configured_pending").as_dict()
        for name, enabled in settings.providers.as_dict().items()
    }


def record_provider_event(db_path: Path, event: NormalizedMarketEvent, *, event_type: str = "market_event") -> None:
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO provider_events(provider,event_type,severity,source_time,received_at,details_json) VALUES(?,?,?,?,?,?)",
            (event.venue, event_type, "info", event.source_time, event.received_at, __import__("json").dumps(event.as_dict(), ensure_ascii=True, separators=(",", ":"))),
        )


class ProviderSupervisor:
    """Public-data supervisor with gap detection and bounded reconnects."""

    def __init__(self, settings: Settings, *, on_event: Callable[[NormalizedMarketEvent], Awaitable[None]] | None = None):
        self.settings = settings
        self.on_event = on_event or self._default_handler
        self.health = {name: ProviderHealth(name, enabled, status="disabled" if not enabled else "configured_pending") for name, enabled in settings.providers.as_dict().items()}
        self.sequence = SequenceTracker()
        self._stop = asyncio.Event()

    async def _default_handler(self, event: NormalizedMarketEvent) -> None:
        record_provider_event(self.settings.db_path, event)

    def stop(self) -> None:
        self._stop.set()

    def _adapters(self, name: str):
        if name == "binance":
            return [BinancePublicAdapter(futures=False), BinancePublicAdapter(futures=True)]
        return {
            "okx": OKXPublicAdapter(),
            "coinbase": CoinbasePublicAdapter(),
            "kraken": KrakenPublicAdapter(),
        }.get(name, None)

    def _adapter(self, name: str):
        """Compatibility accessor for tests and provider diagnostics."""

        adapters = self._adapters(name)
        return adapters[0] if adapters else None

    async def _handle(self, name: str, event: NormalizedMarketEvent) -> None:
        source = datetime.fromisoformat(event.source_time.replace("Z", "+00:00"))
        received = datetime.fromisoformat(event.received_at.replace("Z", "+00:00"))
        source = source if source.tzinfo else source.replace(tzinfo=UTC)
        received = received if received.tzinfo else received.replace(tzinfo=UTC)
        health = self.health[name]
        calibration_offset = health.clock_offset_seconds or 0.0
        clock_skew = (source - (received + timedelta(seconds=calibration_offset))).total_seconds()
        if clock_skew > 5 or clock_skew < -900:
            health.status = "clock_skew" if clock_skew > 5 else "source_stale"
            health.last_error = f"clock_skew_seconds={clock_skew:.1f}"
            event = replace(event, provider_status=health.status)
        status = self.sequence.observe(
            event.instrument_id + ":" + event.event_type,
            event.sequence,
            previous_sequence=event.previous_sequence,
            strict=event.previous_sequence is not None,
        )
        if status == "gap":
            health.sequence_gaps = self.sequence.gaps
            health.status = "resync_required"
            # Do not pass a potentially incomplete stream to downstream
            # factors.  The next event starts a fresh sequence window; a
            # future REST snapshot adapter will explicitly clear this state.
            self.sequence.reset(event.instrument_id + ":" + event.event_type)
            return
        elif status == "duplicate":
            health.duplicate_events = self.sequence.duplicates
            return
        elif status == "out_of_order":
            health.out_of_order_events = self.sequence.out_of_order
            return
        health.last_source_time = event.source_time
        health.last_received_at = event.received_at
        await self.on_event(event)

    async def _run_adapter(self, name: str, adapter: Any, symbols: list[str]) -> None:
        delay = 1.0
        while not self._stop.is_set():
            health = self.health[name]
            try:
                # Public provider clock calibration is shared through the
                # provider health record, so each adapter uses the same
                # fail-closed timestamp contract.
                if health.clock_offset_seconds is None:
                    calibration = await calibrate_provider_clock(name)
                    if calibration:
                        health.clock_offset_seconds = calibration.offset_seconds
                        health.clock_source = calibration.source
                    elif name in {"binance", "okx", "kraken"}:
                        health.status = "clock_unavailable"
                        health.last_error = "provider_clock_calibration_failed"
                health.status = "connecting"
                health.connected = True
                await adapter.stream(symbols, lambda event: self._handle(name, event))
                health.status = "closed"
                health.connected = False
                delay = 1.0
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # provider failure is isolated and fail-closed
                health.status = "error"
                health.connected = False
                health.last_error = type(exc).__name__
                health.reconnect_count += 1
                await asyncio.sleep(min(delay, 30.0))
                delay = min(delay * 2, 30.0)

    async def run_provider(self, name: str, symbols: list[str]) -> None:
        adapters = self._adapters(name)
        if not adapters or not self.health[name].enabled:
            return
        await asyncio.gather(*(self._run_adapter(name, adapter, symbols) for adapter in adapters))

    async def run(self, symbols: list[str]) -> None:
        tasks = [asyncio.create_task(self.run_provider(name, symbols)) for name, value in self.settings.providers.as_dict().items() if value and name in {"binance", "okx", "coinbase", "kraken"}]
        if tasks:
            await asyncio.gather(*tasks)
