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
    values = {
        name: ProviderHealth(name, enabled, status="disabled" if not enabled else "configured_pending").as_dict()
        for name, enabled in settings.providers.as_dict().items()
    }
    values["binance"]["endpoint_family"] = "binance_public_market_data"
    values["binance"]["endpoint"] = settings.binance_public_endpoints.spot_stream
    return values


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
        self.high_frequency_symbols = set(settings.high_frequency_symbols)
        self.health = {name: ProviderHealth(name, enabled, status="disabled" if not enabled else "configured_pending") for name, enabled in settings.providers.as_dict().items()}
        self.sequence = SequenceTracker()
        self._stop = asyncio.Event()
        self._restart = asyncio.Event()
        self._symbols: tuple[str, ...] = ()
        binance_health = self.health.get("binance")
        if binance_health is not None:
            binance_health.endpoint_family = "binance_public_market_data"
            binance_health.endpoint = settings.binance_public_endpoints.spot_stream

    async def _default_handler(self, event: NormalizedMarketEvent) -> None:
        record_provider_event(self.settings.db_path, event)

    def stop(self) -> None:
        self._stop.set()
        self._restart.set()

    def update_symbols(self, symbols: list[str], high_frequency_symbols: list[str] | None = None) -> bool:
        normalized = tuple(dict.fromkeys(str(value).upper() for value in symbols if value))
        if not normalized:
            return False
        high_frequency = set(str(value).upper() for value in (high_frequency_symbols or ()) if value)
        changed = normalized != self._symbols or high_frequency != self.high_frequency_symbols
        self._symbols = normalized
        self.high_frequency_symbols = high_frequency
        if changed:
            self._restart.set()
        return changed

    def _adapters(self, name: str):
        if name == "binance":
            return [
                BinancePublicAdapter(
                    futures=False,
                    high_frequency_symbols=self.high_frequency_symbols,
                    stream_url=self.settings.binance_public_endpoints.spot_stream,
                ),
                BinancePublicAdapter(
                    futures=True,
                    high_frequency_symbols=self.high_frequency_symbols,
                    stream_url=self.settings.binance_public_endpoints.futures_stream,
                ),
            ]
        return {
            "okx": OKXPublicAdapter(high_frequency_symbols=self.high_frequency_symbols),
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
        try:
            await self.on_event(event)
        except Exception:
            health.handler_errors += 1
            raise
        health.accepted_events += 1

    async def _run_adapter(self, name: str, adapter: Any, symbols: list[str]) -> None:
        delay = 1.0
        while not self._stop.is_set():
            health = self.health[name]
            try:
                # Public provider clock calibration is shared through the
                # provider health record, so each adapter uses the same
                # fail-closed timestamp contract.
                if health.clock_offset_seconds is None:
                    calibration = await calibrate_provider_clock(
                        name,
                        binance_base_url=self.settings.binance_public_endpoints.spot_rest,
                    )
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
        jobs = []
        for adapter in adapters:
            # The dynamic universe is a Binance Spot scanner. Futures and
            # cross-source reference venues stay on the configured core set
            # until their own instrument registry and validation gates exist.
            adapter_symbols = symbols
            if name != "binance" or bool(getattr(adapter, "futures", False)):
                adapter_symbols = list(self.settings.core_symbols)
            jobs.append(self._run_adapter(name, adapter, adapter_symbols))
        await asyncio.gather(*jobs)

    async def run(self, symbols: list[str]) -> None:
        self.update_symbols(symbols, list(self.high_frequency_symbols))
        while not self._stop.is_set():
            self._restart.clear()
            current = list(self._symbols)
            tasks = [
                asyncio.create_task(self.run_provider(name, current))
                for name, value in self.settings.providers.as_dict().items()
                if value and name in {"binance", "okx", "coinbase", "kraken"}
            ]
            restart_wait = asyncio.create_task(self._restart.wait())
            stop_wait = asyncio.create_task(self._stop.wait())
            waiters = [*tasks, restart_wait, stop_wait]
            if not tasks:
                await stop_wait
            else:
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            for task in waiters:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
