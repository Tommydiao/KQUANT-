from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..market_models import NormalizedMarketEvent, content_hash, timestamp_ms


SPOT_STREAM_URL = "wss://stream.binance.com:9443/stream"
FUTURES_STREAM_URL = "wss://fstream.binance.com/stream"
_QUOTE_ASSETS = ("USDT", "USDC", "FDUSD", "BTC", "ETH", "BNB")


def _asset_id(symbol: str) -> str:
    upper = symbol.upper()
    for quote in _QUOTE_ASSETS:
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"asset:{upper[:-len(quote)].lower()}"
    return f"asset:{upper.lower()}"


def _event(symbol: str, market_type: str, event_type: str, source_time: str, received_at: str, sequence: int | None, payload: dict[str, Any]) -> NormalizedMarketEvent:
    venue = "binance"
    return NormalizedMarketEvent(
        asset_id=_asset_id(symbol),
        venue=venue,
        instrument_id=f"{venue}:{market_type}:{symbol.upper()}",
        market_type=market_type,
        event_type=event_type,
        source_time=source_time,
        received_at=received_at,
        sequence=sequence,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def normalize_binance_message(message: dict[str, Any], *, received_at: datetime | None = None, futures: bool = False) -> NormalizedMarketEvent | None:
    received = received_at or datetime.now(UTC)
    data = message.get("data", message)
    event_name = data.get("e")
    if not event_name:
        return None
    symbol = str(data.get("s") or data.get("symbol") or "").upper()
    if not symbol:
        return None
    market_type = "perpetual" if futures else "spot"
    source = timestamp_ms(data.get("E") or data.get("T"), fallback=received)
    sequence: int | None = None
    event_type = "unknown"
    payload: dict[str, Any]
    if event_name == "24hrTicker":
        event_type = "ticker"
        payload = {"last": data.get("c"), "base_volume_24h": data.get("v"), "quote_volume_24h": data.get("q"), "price_change_pct_24h": data.get("P")}
    elif event_name == "bookTicker":
        event_type = "book_ticker"
        sequence = int(data["u"]) if data.get("u") is not None else None
        payload = {"bid": data.get("b"), "bid_size": data.get("B"), "ask": data.get("a"), "ask_size": data.get("A")}
    elif event_name in {"trade", "aggTrade"}:
        event_type = "trade"
        raw_sequence = data.get("t") or data.get("a")
        sequence = int(raw_sequence) if raw_sequence is not None else None
        payload = {"price": data.get("p"), "size": data.get("q"), "side": "sell" if data.get("m") else "buy", "trade_id": raw_sequence}
    elif event_name == "kline":
        event_type = "kline"
        kline = data.get("k") or {}
        symbol = str(kline.get("s") or symbol).upper()
        source = timestamp_ms(kline.get("t") or data.get("E"), fallback=received)
        payload = {"interval": kline.get("i"), "open": kline.get("o"), "high": kline.get("h"), "low": kline.get("l"), "close": kline.get("c"), "volume": kline.get("v"), "closed": bool(kline.get("x"))}
    elif event_name == "markPriceUpdate":
        event_type = "mark_price"
        payload = {"mark_price": data.get("p"), "index_price": data.get("i"), "funding_rate": data.get("r"), "next_funding_time": data.get("T")}
    else:
        return None
    return _event(symbol, market_type, event_type, source, received.isoformat(), sequence, payload)


def build_stream_names(
    symbols: list[str],
    *,
    futures: bool = False,
    high_frequency_symbols: set[str] | None = None,
) -> list[str]:
    names: list[str] = []
    for value in symbols:
        symbol = value.replace("/", "").replace("-", "").lower()
        names.extend([f"{symbol}@ticker", f"{symbol}@kline_1m"])
        high_frequency = high_frequency_symbols is None or symbol.upper() in high_frequency_symbols
        if high_frequency:
            names.extend([f"{symbol}@bookTicker", f"{symbol}@trade"])
        if futures and high_frequency:
            names.append(f"{symbol}@markPrice@1s")
    return names


def build_stream_url(
    symbols: list[str],
    *,
    futures: bool = False,
    high_frequency_symbols: set[str] | None = None,
) -> str:
    base = FUTURES_STREAM_URL if futures else SPOT_STREAM_URL
    streams = "/".join(build_stream_names(
        symbols,
        futures=futures,
        high_frequency_symbols=high_frequency_symbols,
    ))
    return f"{base}?streams={streams}"


class BinancePublicAdapter:
    name = "binance"

    def __init__(self, *, futures: bool = False, high_frequency_symbols: set[str] | None = None):
        self.futures = futures
        self.high_frequency_symbols = high_frequency_symbols

    def subscription_url(self, symbols: list[str]) -> str:
        return build_stream_url(
            symbols,
            futures=self.futures,
            high_frequency_symbols=self.high_frequency_symbols,
        )

    async def stream(self, symbols: list[str], callback: Callable[[NormalizedMarketEvent], Awaitable[None]]) -> None:
        import websockets

        async with websockets.connect(self.subscription_url(symbols), ping_interval=20, ping_timeout=20) as socket:
            async for raw in socket:
                message = json.loads(raw)
                event = normalize_binance_message(message, futures=self.futures)
                if event:
                    await callback(event)


async def consume_once(adapter: BinancePublicAdapter, symbols: list[str], callback: Callable[[NormalizedMarketEvent], Awaitable[None]]) -> None:
    await adapter.stream(symbols, callback)
