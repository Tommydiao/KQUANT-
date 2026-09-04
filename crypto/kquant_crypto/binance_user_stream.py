from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import websockets

from .execution_store import save_account_event, save_exchange_fill, update_order_from_account_event


def _iso(milliseconds: Any) -> str:
    try:
        return datetime.fromtimestamp(float(milliseconds) / 1000.0, UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ExchangeAccountEvent:
    market_type: str
    event_type: str
    source_time: str
    sequence_key: str
    client_order_id: str | None
    order_status: str | None
    trade_id: str | None
    quantity: float
    price: float
    commission: float
    commission_asset: str | None
    payload: dict[str, Any]


def normalize_account_event(payload: dict[str, Any], market_type: str) -> ExchangeAccountEvent:
    event_type = str(payload.get("e") or "unknown")
    order = dict(payload.get("o") or {}) if market_type == "perpetual" and event_type == "ORDER_TRADE_UPDATE" else payload
    is_order = event_type in {"ORDER_TRADE_UPDATE", "executionReport"}
    client_order_id = str(order.get("c") or "") or None if is_order else None
    status = str(order.get("X") or "") or None if is_order else None
    raw_trade_id = order.get("t") if is_order else None
    trade_id = str(raw_trade_id) if raw_trade_id not in (None, -1) else None
    return ExchangeAccountEvent(
        market_type=market_type,
        event_type=event_type,
        source_time=_iso(payload.get("E")),
        sequence_key=(f"{client_order_id}:{trade_id}:{status}" if is_order else f"{event_type}:{payload.get('E')}:{payload.get('u', '')}"),
        client_order_id=client_order_id,
        order_status=status,
        trade_id=trade_id,
        quantity=float(order.get("l") or 0.0) if is_order else 0.0,
        price=float(order.get("L") or 0.0) if is_order else 0.0,
        commission=float(order.get("n") or 0.0) if is_order else 0.0,
        commission_asset=str(order.get("N") or "") or None if is_order else None,
        payload=payload,
    )


class BinanceUserDataRuntime:
    """Persist account events; stream loss disarms before reconciliation."""

    def __init__(self, db_path: Path, controller: Any, *, connect: Callable[[str], Any] = websockets.connect, keepalive_seconds: float = 1800.0):
        self.db_path = db_path
        self.controller = controller
        self.connect = connect
        self.keepalive_seconds = keepalive_seconds
        self.running = False
        self.last_event_at: str | None = None
        self.last_error: str | None = None

    def websocket_url(self, market_type: str, listen_key: str) -> str:
        testnet = self.controller.settings.mode.value == "testnet"
        if market_type == "perpetual":
            host = "stream.binancefuture.com" if testnet else "fstream.binance.com"
        else:
            host = "stream.testnet.binance.vision" if testnet else "stream.binance.com:9443"
        return f"wss://{host}/ws/{listen_key}"

    def process(self, payload: dict[str, Any], market_type: str) -> ExchangeAccountEvent:
        event = normalize_account_event(payload, market_type)
        received_at = datetime.now(UTC).isoformat()
        created = save_account_event(
            self.db_path, execution_mode=self.controller.settings.mode.value,
            market_type=market_type, event_type=event.event_type,
            source_time=event.source_time, received_at=received_at,
            sequence_key=event.sequence_key, payload=payload,
        )
        if created and event.client_order_id and event.order_status:
            order = update_order_from_account_event(
                self.db_path, client_order_id=event.client_order_id,
                status=event.order_status, response_payload=payload,
            )
            if order and event.trade_id and event.quantity > 0 and event.price > 0:
                save_exchange_fill(
                    self.db_path, local_order_id=str(order["local_order_id"]), exchange_trade_id=event.trade_id,
                    quantity=event.quantity, price=event.price, commission=event.commission,
                    commission_asset=event.commission_asset, filled_at=event.source_time, payload=payload,
                )
            if order and event.order_status == "FILLED":
                self.controller.cancel_sibling_protection(order)
        self.last_event_at = received_at
        return event

    async def _keepalive(self, client: Any, market_type: str, listen_key: str) -> None:
        while True:
            await asyncio.sleep(self.keepalive_seconds)
            await asyncio.to_thread(client.keepalive_user_stream, market_type, listen_key)

    async def run_market(self, market_type: str) -> None:
        while self.controller.settings.credentials_configured:
            client = self.controller._client_factory()
            keepalive = None
            try:
                listen_key = await asyncio.to_thread(client.start_user_stream, market_type)
                keepalive = asyncio.create_task(self._keepalive(client, market_type, listen_key))
                async with self.connect(self.websocket_url(market_type, listen_key)) as stream:
                    async for message in stream:
                        self.process(json.loads(message), market_type)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.controller.disarm("user_data_stream_disconnected")
                await asyncio.to_thread(self.controller.reconcile)
                await asyncio.sleep(5.0)
            finally:
                if keepalive:
                    keepalive.cancel()
                    await asyncio.gather(keepalive, return_exceptions=True)
                client.close()

    async def run(self) -> None:
        self.running = True
        try:
            await self.run_market("spot")
        finally:
            self.running = False

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "market_types": ["spot"],
            "last_event_at": self.last_event_at,
            "last_error": self.last_error,
        }
