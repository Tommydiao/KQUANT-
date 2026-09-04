from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.market_models import NormalizedMarketEvent, content_hash
from kquant_crypto.market_runtime import MarketDataRuntime
from kquant_crypto.notifications import NotificationHub
from kquant_crypto.realtime_supervisor import RealtimeSupervisor
from kquant_crypto.signal_runtime import CEXSignalRuntime
from kquant_crypto.evaluation_store import latest_evaluations

TOTAL_MINUTES = 310
_NOW = datetime.now(UTC)
# Keep the synthetic impulse inside a completed 5m bucket regardless of the
# wall-clock minute when the full suite starts.
BASE_TIME = _NOW.replace(minute=_NOW.minute - (_NOW.minute % 5), second=0, microsecond=0)


def _event(index: int, *, closed: bool = True, event_type: str = "kline") -> NormalizedMarketEvent:
    start = BASE_TIME - timedelta(minutes=TOTAL_MINUTES - index)
    # Flat base followed by a measured six-bar impulse. This is a setup
    # candidate, not a claim that a profitable signal exists.
    close = 100.0 if index < TOTAL_MINUTES - 6 else 100.0 + (index - (TOTAL_MINUTES - 7)) * 1.8
    volume = 100.0 if index < TOTAL_MINUTES - 10 else 500.0
    payload = {
        "interval": "1m",
        "open": str(close - 0.2),
        "high": str(close + 0.5),
        "low": str(close - 0.5),
        "close": str(close),
        "volume": str(volume),
        "closed": closed,
    }
    if event_type == "book_ticker":
        payload = {"bid": str(close - 0.01), "ask": str(close + 0.01), "bid_size": "10", "ask_size": "10"}
    return NormalizedMarketEvent(
        asset_id="asset:rklb",
        venue="binance",
        instrument_id="binance:spot:RKLBUSDT",
        market_type="spot",
        event_type=event_type,
        source_time=start.isoformat(),
        received_at=(start + timedelta(seconds=1)).isoformat(),
        sequence=index,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def test_forming_candle_never_reaches_signal_runtime(settings):
    runtime = MarketDataRuntime(settings.data_dir, db_path=settings.db_path, flush_every=10_000)
    registry = FactorRegistry(settings.db_path)
    supervisor = RealtimeSupervisor(settings.db_path, NotificationHub(), settings)
    signals = CEXSignalRuntime(settings.db_path, runtime, registry, supervisor)

    result = asyncio.run(runtime.ingest(_event(0, closed=False)))
    assert result is None
    assert signals.on_market_event(_event(0, closed=False)) is None
    assert signals.status()["evaluations_created"] == 0
    assert latest_evaluations(settings.db_path) == []


def test_closed_candidate_without_sixty_closed_hourly_bars_is_blocked(settings):
    runtime = MarketDataRuntime(settings.data_dir, db_path=settings.db_path, flush_every=10_000)
    registry = FactorRegistry(settings.db_path)
    supervisor = RealtimeSupervisor(settings.db_path, NotificationHub(), settings)
    signals = CEXSignalRuntime(settings.db_path, runtime, registry, supervisor)

    asyncio.run(runtime.ingest(_event(0, event_type="book_ticker")))
    for index in range(TOTAL_MINUTES):
        value = _event(index)
        asyncio.run(runtime.ingest(value))
        signals.on_market_event(value)

    status = signals.status()
    assert status["evaluations_created"] == 0
    evaluations = latest_evaluations(settings.db_path)
    assert evaluations == []

    assert status["skipped_insufficient_history"] > 0
    duplicate = signals.on_market_event(_event(309))
    assert duplicate is not None
    assert duplicate["status"] == "duplicate"
