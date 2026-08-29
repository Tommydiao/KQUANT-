from __future__ import annotations

import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .market_models import NormalizedMarketEvent


INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1H": 60, "4H": 240, "1D": 1440}


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Candle:
    instrument_id: str
    interval: str
    start_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool
    component_count: int
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "interval": self.interval,
            "start_time": self.start_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "closed": self.closed,
            "component_count": self.component_count,
            "source": self.source,
        }


@dataclass
class InstrumentBuffer:
    events: deque[NormalizedMarketEvent] = field(default_factory=lambda: deque(maxlen=4096))
    candles: dict[str, deque[Candle]] = field(default_factory=lambda: {interval: deque(maxlen=4096) for interval in INTERVAL_MINUTES})
    forming: dict[str, Candle] = field(default_factory=dict)
    last_quote: dict[str, Any] = field(default_factory=dict)
    last_trade: dict[str, Any] = field(default_factory=dict)
    derivative: dict[str, Any] = field(default_factory=dict)
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    trade_sizes: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    big_trade_count: int = 0
    last_source_time: str | None = None
    last_received_at: str | None = None
    provider_status: str = "unknown"


class MarketDataBuffer:
    """Bounded in-memory market state; only closed candles enter history."""

    def __init__(self, *, max_events: int = 4096):
        self.max_events = max_events
        self._instruments: dict[str, InstrumentBuffer] = defaultdict(
            lambda: InstrumentBuffer(events=deque(maxlen=max_events))
        )
        self._asset_instruments: dict[str, set[str]] = defaultdict(set)

    def ingest(self, event: NormalizedMarketEvent) -> None:
        state = self._instruments[event.instrument_id]
        self._asset_instruments[event.asset_id].add(event.instrument_id)
        state.events.append(event)
        state.last_source_time = event.source_time
        state.last_received_at = event.received_at
        state.provider_status = event.provider_status
        if event.event_type in {"ticker", "book_ticker"}:
            state.last_quote = dict(event.payload)
        elif event.event_type == "trade":
            self._ingest_trade(state, event)
        elif event.event_type == "mark_price":
            state.derivative = dict(event.payload)
        elif event.event_type == "kline":
            self._ingest_kline(state, event)

    def hydrate_closed_klines(self, events: list[NormalizedMarketEvent]) -> int:
        """Load historical closed 1m events without replaying each rebuild.

        Hydration is a read-only warm start from an immutable Parquet snapshot.
        It never enters the event writer queue and is intentionally separate
        from live ingestion so historical data cannot masquerade as fresh.
        """

        grouped: dict[str, list[tuple[NormalizedMarketEvent, Candle]]] = defaultdict(list)
        for event in events:
            if event.event_type != "kline" or not bool(event.payload.get("closed")):
                continue
            interval = str(event.payload.get("interval") or "1m")
            if interval not in {"1m", "1", "1M"}:
                continue
            candle = self._kline_from_event(event, interval="1m", closed=True)
            if candle is not None:
                grouped[event.instrument_id].append((event, candle))
        loaded = 0
        for instrument_id, values in grouped.items():
            state = self._instruments[instrument_id]
            values.sort(key=lambda item: item[1].start_time)
            existing = {item.start_time for item in state.candles["1m"]}
            for event, candle in values:
                self._asset_instruments[event.asset_id].add(event.instrument_id)
                state.provider_status = event.provider_status
                state.last_source_time = max(state.last_source_time or event.source_time, event.source_time)
                state.last_received_at = max(state.last_received_at or event.received_at, event.received_at)
                if candle.start_time not in existing:
                    state.candles["1m"].append(candle)
                    existing.add(candle.start_time)
                    loaded += 1
            self._rebuild_aggregates(instrument_id)
        return loaded

    def _ingest_trade(self, state: InstrumentBuffer, event: NormalizedMarketEvent) -> None:
        price = _number(event.payload.get("price"))
        size = _number(event.payload.get("size")) or 0.0
        side = str(event.payload.get("side") or "").lower()
        state.last_trade = dict(event.payload)
        if side == "buy":
            state.buy_volume += size
        elif side == "sell":
            state.sell_volume += size
        if size > 0:
            baseline = statistics.median(state.trade_sizes) if state.trade_sizes else 0.0
            if baseline > 0 and size >= baseline * 5:
                state.big_trade_count += 1
            state.trade_sizes.append(size)
        if price is not None:
            state.last_trade["price"] = price

    def _kline_from_event(self, event: NormalizedMarketEvent, *, interval: str, closed: bool) -> Candle | None:
        values = [_number(event.payload.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            return None
        volume = _number(event.payload.get("volume")) or 0.0
        return Candle(
            instrument_id=event.instrument_id,
            interval=interval,
            start_time=event.source_time,
            open=values[0] or 0.0,
            high=values[1] or 0.0,
            low=values[2] or 0.0,
            close=values[3] or 0.0,
            volume=volume,
            closed=closed,
            component_count=1,
            source=event.venue,
        )

    def _ingest_kline(self, state: InstrumentBuffer, event: NormalizedMarketEvent) -> None:
        interval = str(event.payload.get("interval") or "1m")
        interval = "1m" if interval in {"1", "1m", "1M"} else interval
        if interval not in INTERVAL_MINUTES:
            return
        candle = self._kline_from_event(event, interval=interval, closed=bool(event.payload.get("closed")))
        if candle is None:
            return
        if not candle.closed:
            state.forming[interval] = candle
            return
        state.candles[interval].append(candle)
        state.forming.pop(interval, None)
        if interval == "1m":
            self._rebuild_aggregates(event.instrument_id)

    def _rebuild_aggregates(self, instrument_id: str) -> None:
        state = self._instruments[instrument_id]
        one_minute = list(state.candles["1m"])
        if not one_minute:
            return
        for interval, minutes in INTERVAL_MINUTES.items():
            if interval == "1m":
                continue
            groups: dict[datetime, list[Candle]] = defaultdict(list)
            for candle in one_minute:
                start = _dt(candle.start_time)
                bucket_epoch = int(start.timestamp()) // (minutes * 60) * (minutes * 60)
                groups[datetime.fromtimestamp(bucket_epoch, UTC)].append(candle)
            rebuilt: list[Candle] = []
            for start, components in sorted(groups.items()):
                components.sort(key=lambda item: item.start_time)
                expected = minutes
                slots = {_dt(item.start_time) for item in components}
                complete = len(components) == expected and all(
                    start + timedelta(minutes=index) in slots for index in range(expected)
                )
                if not complete:
                    continue
                rebuilt.append(Candle(
                    instrument_id=instrument_id,
                    interval=interval,
                    start_time=start.isoformat(),
                    open=components[0].open,
                    high=max(item.high for item in components),
                    low=min(item.low for item in components),
                    close=components[-1].close,
                    volume=sum(item.volume for item in components),
                    closed=True,
                    component_count=len(components),
                    source=components[-1].source,
                ))
            state.candles[interval].clear()
            state.candles[interval].extend(rebuilt[-state.candles[interval].maxlen:])

    def latest_closed(self, instrument_id: str, interval: str = "1m") -> Candle | None:
        values = self._instruments[instrument_id].candles.get(interval)
        return values[-1] if values else None

    def closed_history(self, instrument_id: str, interval: str = "1m", limit: int | None = None) -> tuple[Candle, ...]:
        """Return only completed candles in chronological order.

        Signal code must use this accessor instead of reaching into the
        forming-candle buffer.  A bounded copy also prevents downstream
        callers from mutating the live ring buffer.
        """

        values = self._instruments[instrument_id].candles.get(interval)
        if not values:
            return ()
        items = list(values)
        return tuple(items[-limit:] if limit is not None and limit > 0 else items)

    def snapshot(self, instrument_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        state = self._instruments[instrument_id]
        current = now or datetime.now(UTC)
        received = _dt(state.last_received_at) if state.last_received_at else None
        age_seconds = max(0.0, (current - received).total_seconds()) if received else None
        quote = dict(state.last_quote)
        bid = _number(quote.get("bid"))
        ask = _number(quote.get("ask"))
        spread = ask - bid if bid is not None and ask is not None and ask >= bid else None
        mid = (ask + bid) / 2 if bid is not None and ask is not None else None
        return {
            "instrument_id": instrument_id,
            "quote": quote,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "spread_bps": (spread / mid * 10000) if spread is not None and mid else None,
            "last_trade": dict(state.last_trade),
            "derivative": dict(state.derivative),
            "order_flow": {
                "buy_volume": state.buy_volume,
                "sell_volume": state.sell_volume,
                "cvd": state.buy_volume - state.sell_volume,
                "big_trade_count": state.big_trade_count,
            },
            "forming": {key: value.as_dict() for key, value in state.forming.items()},
            "closed": {
                interval: state.candles[interval][-1].as_dict() if state.candles[interval] else None
                for interval in INTERVAL_MINUTES
            },
            "last_source_time": state.last_source_time,
            "last_received_at": state.last_received_at,
            "age_seconds": age_seconds,
            "provider_status": state.provider_status,
            "trust": state.provider_status if state.provider_status != "live" else ("live" if age_seconds is not None and age_seconds <= 30 else "stale"),
        }

    def instruments(self) -> list[str]:
        return sorted(self._instruments)

    def instruments_for_asset(self, asset_id: str) -> list[str]:
        return sorted(self._asset_instruments.get(asset_id, set()))
