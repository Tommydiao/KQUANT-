from __future__ import annotations

import hashlib
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Callable

from .binance_execution import BinanceExecutionClient, BinanceExecutionError, BinanceUnknownExecutionState
from .execution_models import ExecutionIntent, ExecutionRiskDecision, SymbolTradingRules
from .execution_store import save_exchange_fill, save_exchange_order


class ProtectionOrderError(RuntimeError):
    pass


def _number(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _aligned(value: float, step: float, *, round_up: bool = False) -> float:
    if step <= 0:
        raise ValueError("exchange_step_missing")
    decimal_step = Decimal(str(step))
    units = Decimal(str(value)) / decimal_step
    rounding = ROUND_CEILING if round_up else ROUND_FLOOR
    return float(units.to_integral_value(rounding=rounding) * decimal_step)


def client_order_id(intent_id: str, role: str) -> str:
    digest = hashlib.sha256(f"{intent_id}|{role}".encode("utf-8")).hexdigest()[:20]
    return f"kq_{role[:4]}_{digest}"[:36]


class BinanceOrderManager:
    """Submit one approved intent and install exchange-native protection."""

    def __init__(
        self,
        db_path: Path,
        client: BinanceExecutionClient,
        *,
        execution_mode: str,
        max_leverage: int = 2,
        on_critical_failure: Callable[[str], None] | None = None,
    ):
        self.db_path = db_path
        self.client = client
        self.execution_mode = execution_mode
        self.max_leverage = min(2, max(1, int(max_leverage)))
        self.on_critical_failure = on_critical_failure or (lambda _reason: None)

    def _record_order(
        self,
        intent: ExecutionIntent,
        *,
        role: str,
        params: dict[str, Any],
        status: str,
        response: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return save_exchange_order(
            self.db_path,
            intent_id=intent.intent_id,
            client_order_id=str(params.get("newClientOrderId") or params.get("listClientOrderId")),
            execution_mode=self.execution_mode,
            symbol=intent.symbol,
            market_type=intent.market_type,
            order_role=role,
            side=str(params.get("side")),
            order_type=str(params.get("type") or "OCO"),
            status=status,
            quantity=float(params.get("quantity") or 0.0),
            price=float(params["price"]) if params.get("price") is not None else None,
            stop_price=float(params.get("stopPrice") or params.get("belowStopPrice")) if (params.get("stopPrice") or params.get("belowStopPrice")) is not None else None,
            reduce_only=str(params.get("reduceOnly", "false")).lower() == "true",
            request_payload=params,
            response_payload=response,
        )

    def submit(
        self,
        intent: ExecutionIntent,
        decision: ExecutionRiskDecision,
        rules: SymbolTradingRules,
    ) -> dict[str, Any]:
        if not decision.allowed:
            raise ValueError("execution_risk_not_approved")
        if decision.intent_id != intent.intent_id:
            raise ValueError("risk_decision_intent_mismatch")
        if rules.symbol != intent.symbol or rules.market_type != intent.market_type:
            raise ValueError("exchange_rules_intent_mismatch")
        if not rules.tradable:
            raise ValueError("symbol_not_tradable")
        quantity = _aligned(decision.quantity, rules.step_size)
        if quantity <= 0:
            raise ValueError("quantity_below_exchange_step")
        entry_limit = _aligned(intent.entry_limit, rules.tick_size, round_up=intent.direction == "short")
        if intent.market_type == "perpetual":
            self.client.configure_futures_symbol(intent.symbol, self.max_leverage)

        entry_id = client_order_id(intent.intent_id, "entry")
        entry_params: dict[str, Any] = {
            "symbol": intent.symbol,
            "side": "BUY" if intent.direction == "long" else "SELL",
            "type": "LIMIT",
            "timeInForce": "IOC",
            "quantity": _number(quantity),
            "price": _number(entry_limit),
            "newClientOrderId": entry_id,
            "newOrderRespType": "RESULT" if intent.market_type == "perpetual" else "FULL",
        }
        self._record_order(intent, role="entry", params=entry_params, status="sending")
        try:
            entry = self.client.place_order(intent.market_type, entry_params)
        except BinanceUnknownExecutionState:
            self._record_order(intent, role="entry", params=entry_params, status="unknown")
            self.on_critical_failure("entry_order_state_unknown")
            raise
        except BinanceExecutionError:
            self._record_order(intent, role="entry", params=entry_params, status="rejected")
            raise

        entry_status = str(entry.get("status") or "UNKNOWN")
        entry_row = self._record_order(intent, role="entry", params=entry_params, status=entry_status, response=entry)
        executed_quantity = float(entry.get("executedQty") or 0.0)
        if executed_quantity <= 0:
            return {"status": "not_filled", "entry": entry, "protection": None}

        average_price = float(entry.get("avgPrice") or entry.get("price") or intent.entry_limit)
        fills = entry.get("fills") if isinstance(entry.get("fills"), list) else ()
        if fills:
            for index, fill in enumerate(fills):
                save_exchange_fill(
                    self.db_path,
                    local_order_id=str(entry_row["local_order_id"]),
                    exchange_trade_id=str(fill.get("tradeId") or f"response_{index}"),
                    quantity=float(fill.get("qty") or 0.0),
                    price=float(fill.get("price") or average_price),
                    commission=float(fill.get("commission") or 0.0),
                    commission_asset=str(fill.get("commissionAsset") or "") or None,
                    payload=dict(fill),
                )
        else:
            save_exchange_fill(
                self.db_path,
                local_order_id=str(entry_row["local_order_id"]),
                exchange_trade_id=str(entry.get("orderId") or "entry_response"),
                quantity=executed_quantity,
                price=average_price,
                payload=entry,
            )

        try:
            protection = self._protect(intent, executed_quantity, rules)
        except Exception as exc:
            self._record_order(intent, role="protection", params={"side": "", "quantity": executed_quantity, "newClientOrderId": client_order_id(intent.intent_id, "protection")}, status="protection_failed")
            self._emergency_exit(intent, executed_quantity)
            self.on_critical_failure("protection_order_failed")
            raise ProtectionOrderError(type(exc).__name__) from exc
        return {"status": "protected", "entry": entry, "protection": protection}

    def _protect(self, intent: ExecutionIntent, quantity: float, rules: SymbolTradingRules) -> dict[str, Any]:
        exit_side = "SELL" if intent.direction == "long" else "BUY"
        round_up = exit_side == "BUY"
        stop_price = _aligned(intent.stop_price, rules.tick_size, round_up=round_up)
        target_price = _aligned(intent.target_price, rules.tick_size, round_up=round_up)
        if intent.market_type == "spot":
            stop_limit = _aligned(stop_price * 0.999, rules.tick_size)
            params = {
                "symbol": intent.symbol,
                "side": exit_side,
                "quantity": _number(quantity),
                "aboveType": "LIMIT_MAKER",
                "abovePrice": _number(target_price),
                "belowType": "STOP_LOSS_LIMIT",
                "belowStopPrice": _number(stop_price),
                "belowPrice": _number(stop_limit),
                "belowTimeInForce": "GTC",
                "listClientOrderId": client_order_id(intent.intent_id, "oco"),
                "aboveClientOrderId": client_order_id(intent.intent_id, "target"),
                "belowClientOrderId": client_order_id(intent.intent_id, "stop"),
            }
            response = self.client.place_spot_oco(params)
            self._record_order(intent, role="protection", params=params, status=str(response.get("listStatusType") or "EXEC_STARTED"), response=response)
            return response

        responses: dict[str, Any] = {}
        for role, order_type, trigger in (
            ("stop", "STOP_MARKET", stop_price),
            ("target", "TAKE_PROFIT_MARKET", target_price),
        ):
            params = {
                "symbol": intent.symbol,
                "side": exit_side,
                "type": order_type,
                "quantity": _number(quantity),
                "stopPrice": _number(trigger),
                "reduceOnly": "true",
                "workingType": "MARK_PRICE",
                "newClientOrderId": client_order_id(intent.intent_id, role),
            }
            response = self.client.place_order("perpetual", params)
            self._record_order(intent, role=role, params=params, status=str(response.get("status") or "NEW"), response=response)
            responses[role] = response
        return responses

    def _emergency_exit(self, intent: ExecutionIntent, quantity: float) -> dict[str, Any]:
        params = {
            "symbol": intent.symbol,
            "side": "SELL" if intent.direction == "long" else "BUY",
            "type": "MARKET",
            "quantity": _number(quantity),
            "newClientOrderId": client_order_id(intent.intent_id, "emergency"),
        }
        if intent.market_type == "perpetual":
            params["reduceOnly"] = "true"
        response = self.client.place_order(intent.market_type, params)
        self._record_order(intent, role="emergency_exit", params=params, status=str(response.get("status") or "UNKNOWN"), response=response)
        return response
