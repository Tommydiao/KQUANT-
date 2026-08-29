from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ..market_models import NormalizedMarketEvent, content_hash, timestamp_ms


PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


def _symbol(value: str) -> str:
    return value.replace("-", "").upper()


def _instrument(value: str) -> str:
    upper = value.upper().replace("/", "-")
    if "-" in upper:
        return upper
    for quote in ("USDT", "USDC", "USD", "BTC", "ETH"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"{upper[:-len(quote)]}-{quote}"
    return upper


def _event(inst_id: str, market_type: str, event_type: str, source: str, received: str, sequence: int | None, previous_sequence: int | None, payload: dict[str, Any]) -> NormalizedMarketEvent:
    return NormalizedMarketEvent(
        asset_id=f"asset:{inst_id.split('-')[0].lower()}",
        venue="okx",
        instrument_id=f"okx:{market_type}:{inst_id}",
        market_type=market_type,
        event_type=event_type,
        source_time=source,
        received_at=received,
        sequence=sequence,
        previous_sequence=previous_sequence,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def normalize_okx_message(message: dict[str, Any], *, received_at: datetime | None = None) -> list[NormalizedMarketEvent]:
    received = received_at or datetime.now(UTC)
    arg = message.get("arg") or {}
    channel = str(arg.get("channel") or "")
    data = message.get("data") or []
    result: list[NormalizedMarketEvent] = []
    for item in data:
        inst_id = str(item.get("instId") or arg.get("instId") or "")
        if not inst_id:
            continue
        market_type = "perpetual" if inst_id.endswith("-SWAP") else "spot"
        source = timestamp_ms(item.get("ts") or item.get("uTime"), fallback=received)
        sequence = item.get("seqId") or item.get("tradeId")
        sequence_int = int(sequence) if sequence is not None and str(sequence).isdigit() else None
        previous = item.get("prevSeqId")
        previous_int = int(previous) if previous is not None and str(previous).isdigit() else None
        if channel == "tickers":
            event_type = "ticker"
            payload = {"last": item.get("last"), "bid": item.get("bidPx"), "ask": item.get("askPx"), "bid_size": item.get("bidSz"), "ask_size": item.get("askSz"), "volume_24h": item.get("vol24h")}
        elif channel in {"books", "books5", "bbo-tbt"}:
            event_type = "book_ticker"
            bids = item.get("bids") or []
            asks = item.get("asks") or []
            payload = {"bid": bids[0][0] if bids else None, "bid_size": bids[0][1] if bids else None, "ask": asks[0][0] if asks else None, "ask_size": asks[0][1] if asks else None, "depth": {"bids": bids, "asks": asks}}
        elif channel == "trades":
            event_type = "trade"
            payload = {"price": item.get("px"), "size": item.get("sz"), "side": item.get("side"), "trade_id": item.get("tradeId")}
        elif channel.startswith("candle"):
            values = item if isinstance(item, list) else []
            if not values:
                continue
            source = timestamp_ms(values[0], fallback=received)
            event_type = "kline"
            payload = {"interval": channel.removeprefix("candle"), "open": values[1], "high": values[2], "low": values[3], "close": values[4], "volume": values[5], "closed": str(values[-1]) == "1"}
        elif channel in {"mark-price", "funding-rate"}:
            event_type = "derivative"
            payload = {"mark_price": item.get("markPx"), "funding_rate": item.get("fundingRate"), "next_funding_time": item.get("nextFundingTime")}
        else:
            continue
        result.append(_event(inst_id, market_type, event_type, source, received.isoformat(), sequence_int, previous_int, payload))
    return result


def build_subscription(
    symbols: list[str],
    *,
    include_derivatives: bool = True,
    high_frequency_symbols: set[str] | None = None,
) -> dict[str, Any]:
    args: list[dict[str, str]] = []
    normalized_high_frequency = {
        _symbol(item) for item in high_frequency_symbols
    } if high_frequency_symbols is not None else None
    for value in symbols:
        inst = _instrument(value)
        args.extend([
            {"channel": "tickers", "instId": inst},
            {"channel": "candle1m", "instId": inst},
        ])
        high_frequency = normalized_high_frequency is None or _symbol(inst) in normalized_high_frequency
        if high_frequency:
            args.extend([
                {"channel": "books5", "instId": inst},
                {"channel": "trades", "instId": inst},
            ])
        if include_derivatives and high_frequency:
            swap = inst.removesuffix("-SPOT") + "-SWAP"
            args.extend([{ "channel": "mark-price", "instId": swap }, {"channel": "funding-rate", "instId": swap}])
    return {"op": "subscribe", "args": args}


class OKXPublicAdapter:
    name = "okx"
    url = PUBLIC_WS_URL

    def __init__(self, *, high_frequency_symbols: set[str] | None = None):
        self.high_frequency_symbols = high_frequency_symbols

    def subscription(self, symbols: list[str]) -> dict[str, Any]:
        return build_subscription(symbols, high_frequency_symbols=self.high_frequency_symbols)

    async def stream(self, symbols: list[str], callback: Callable[[NormalizedMarketEvent], Awaitable[None]]) -> None:
        import websockets

        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as socket:
            await socket.send(json.dumps(self.subscription(symbols)))
            async for raw in socket:
                for event in normalize_okx_message(json.loads(raw)):
                    await callback(event)
