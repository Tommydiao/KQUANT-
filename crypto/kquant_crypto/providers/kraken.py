from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..market_models import NormalizedMarketEvent, content_hash


PUBLIC_WS_URL = "wss://ws.kraken.com/v2"


def _product(value: str) -> str:
    upper = value.upper().replace("-", "/")
    if "/" in upper:
        base, quote = upper.split("/", 1)
        return f"{base}/USD" if quote in {"USDT", "USDC"} else upper
    for quote in ("USDT", "USDC", "USD"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"{upper[:-len(quote)]}/USD"
    return upper


def normalize_kraken_message(message: dict[str, Any], *, received_at: datetime | None = None) -> list[NormalizedMarketEvent]:
    received = received_at or datetime.now(UTC)
    channel = str(message.get("channel") or "")
    events: list[NormalizedMarketEvent] = []
    for item in message.get("data") or []:
        symbol = str(item.get("symbol") or "")
        if not symbol:
            continue
        payload = {"last": item.get("last"), "bid": item.get("bid"), "ask": item.get("ask"), "bid_size": item.get("bid_qty"), "ask_size": item.get("ask_qty"), "volume_24h": item.get("volume"), "side": item.get("side"), "price": item.get("price"), "size": item.get("qty")}
        events.append(NormalizedMarketEvent(
            asset_id=f"asset:{symbol.split('/')[0].lower()}",
            venue="kraken",
            instrument_id=f"kraken:spot:{symbol}",
            market_type="spot",
            event_type="ticker" if channel == "ticker" else channel or "unknown",
            source_time=str(item.get("timestamp") or received.isoformat()),
            received_at=received.isoformat(),
            sequence=int(item["trade_id"]) if str(item.get("trade_id", "")).isdigit() else None,
            provider_status="live",
            content_hash=content_hash(payload),
            payload=payload,
        ))
    return events


def build_subscription(symbols: list[str]) -> dict[str, Any]:
    return {"method": "subscribe", "params": {"channel": "ticker", "symbol": [_product(value) for value in symbols], "snapshot": True}}


class KrakenPublicAdapter:
    name = "kraken"
    url = PUBLIC_WS_URL

    def subscription(self, symbols: list[str]) -> dict[str, Any]:
        return build_subscription(symbols)

    async def stream(self, symbols: list[str], callback: Callable[[NormalizedMarketEvent], Awaitable[None]]) -> None:
        import websockets

        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(json.dumps(self.subscription(symbols)))
            async for raw in socket:
                for event in normalize_kraken_message(json.loads(raw)):
                    await callback(event)
