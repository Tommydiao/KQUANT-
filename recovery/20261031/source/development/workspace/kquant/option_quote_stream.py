"""Bounded display subscriptions; no research, notification or order side effects."""
import asyncio
import json
import queue
import re
import uuid

from .longbridge_provider import longbridge_runtime
from .options_expression import _number, _timestamp, _attr
from .stock_chart import depth_row
from .option_quote_evidence import book_fields


def contract_list(raw: str) -> list[str]:
    values = list(dict.fromkeys(value.strip().upper() for value in raw.split(",") if value.strip()))
    if not values or len(values) > 50 or any(not re.fullmatch(r"[A-Z0-9]+\d{6}[CP]\d+\.US", value) for value in values):
        raise ValueError("ONE_TO_FIFTY_OPTION_CONTRACTS_REQUIRED")
    return values


def quote_patch(row, received):
    payload = {key: _number(_attr(row, source)) for key, source in
               (("last", "last_done"), ("volume", "volume"), ("turnover", "turnover"))}
    payload.update(quote_time=_timestamp(_attr(row, "timestamp")), quote_received_at=received,
                   trade_status=str(_attr(row, "trade_status")) if _attr(row, "trade_status") is not None else None)
    return {key: value for key, value in payload.items() if value is not None}


async def stream(request, contracts):
    runtime = longbridge_runtime()
    owner = "option-chain-" + uuid.uuid4().hex
    sink = runtime.event_queue(owner, kinds=("quote", "depth"))
    underlyings = {re.match(r"^([A-Z]+)\d{6}[CP]", contract).group(1) + ".US" for contract in contracts if re.match(r"^([A-Z]+)\d{6}[CP]", contract)}
    underlying = next(iter(underlyings)) if len(underlyings) == 1 else None
    sequence = 0
    try:
        await asyncio.to_thread(runtime.retain_quote_group, owner, contracts)
        if underlying:
            await asyncio.to_thread(runtime.retain_subscription, owner, underlying, quote=True)
        yield 'event: ready\ndata: {"stream":"connected"}\n\n'
        while not await request.is_disconnected():
            try:
                kind, symbol, row, received = await asyncio.to_thread(sink.get, True, 5)
            except queue.Empty:
                yield ': heartbeat\n\n'
                continue
            payload = quote_patch(row, received) if kind == "quote" else depth_row(row, received)
            sequence += 1
            if kind == "depth":
                payload.update(book_fields(bid=payload.get("bid"), ask=payload.get("ask"),
                    bid_size=payload.get("bid_size"), ask_size=payload.get("ask_size"), received_at=received))
                payload.update(bbo_epoch=owner, bbo_sequence=sequence)
            payload["strict_fill_eligible"] = False
            yield "data: " + json.dumps({"kind": "underlying" if symbol == underlying else kind, "contract_symbol": symbol, "received_at": received, "payload": payload}) + "\n\n"
    except Exception as exc:
        yield "event: failure\ndata: " + json.dumps({"error_code": type(exc).__name__}) + "\n\n"
    finally:
        await asyncio.shield(asyncio.to_thread(runtime.release_subscriptions, owner))
