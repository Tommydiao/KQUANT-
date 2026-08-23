from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..market_models import NormalizedMarketEvent, content_hash, timestamp_ms


PUBLIC_WS_URL = "wss://advanced-trade-ws.coinbase.com"


def _product(value: str) -> str:
    upper = value.upper().replace("/", "-")
    if "-" in upper:
        return upper
    for quote in ("USDT", "USDC", "USD"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"{upper[:-len(quote)]}-USD"
    return upper


def normalize_coinbase_message(message: dict[str, Any], *, received_at: datetime | None = None) -> list[NormalizedMarketEvent]:
    received = received_at or datetime.now(UTC)
    channel = str(message.get("channel") or "")
    sequence = int(message["sequence_num"]) if message.get("sequence_num") is not None else None
    events: list[NormalizedMarketEvent] = []
    for event in message.get("events") or []:
        for ticker in event.get("tickers") or []:
            product = str(ticker.get("product_id") or "")
            if not product:
                continue
            symbol = product.replace("-", "")
            payload = {"last": ticker.get("price"), "bid": ticker.get("best_bid"), "ask": ticker.get("best_ask"), "bid_size": ticker.get("best_bid_quantity"), "ask_size": ticker.get("best_ask_quantity"), "volume_24h": ticker.get("volume_24_h")}
            events.append(NormalizedMarketEvent(
                asset_id=f"asset:{product.split('-')[0].lower()}",
                venue="coinbase",
                instrument_id=f"coinbase:spot:{product}",
                market_type="spot",
                event_type="ticker" if channel == "ticker" else channel or "unknown",
                source_time=str(message.get("timestamp") or received.isoformat()),
                received_at=received.isoformat(),
                sequence=sequence,
                provider_status="live",
                content_hash=content_hash(payload),
                payload=payload,
            ))
    return events


def build_subscription(symbols: list[str]) -> dict[str, Any]:
    products = [_product(value) for value in symbols]
    return {"type": "subscribe", "product_ids": products, "channel": "ticker"}


class CoinbasePublicAdapter:
    name = "coinbase"
    url = PUBLIC_WS_URL

    def subscription(self, symbols: list[str]) -> dict[str, Any]:
        return build_subscription(symbols)

    async def stream(self, symbols: list[str], callback: Callable[[NormalizedMarketEvent], Awaitable[None]]) -> None:
        import json
        import websockets

        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(json.dumps(self.subscription(symbols)))
            async for raw in socket:
                for event in normalize_coinbase_message(json.loads(raw)):
                    await callback(event)
