from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kquant_crypto.binance_execution import BinanceUnknownExecutionState
from kquant_crypto.execution_models import ExecutionIntent, ExecutionRiskDecision, SymbolTradingRules
from kquant_crypto.execution_store import list_execution_orders, save_execution_intent
from kquant_crypto.order_manager import BinanceOrderManager, ProtectionOrderError


def intent() -> ExecutionIntent:
    return ExecutionIntent.create(
        intent_id="intent_order_test",
        evaluation_id="eval_order_test",
        strategy_version="crypto_early_v1.0.0",
        symbol="BTCUSDT",
        market_type="spot",
        direction="long",
        entry_limit=100.0,
        stop_price=95.0,
        target_price=110.0,
        validation_gate_status="PASS",
        material_state_hash="order_state",
        expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )


def decision(value: ExecutionIntent) -> ExecutionRiskDecision:
    return ExecutionRiskDecision(
        decision_id="risk_order_test",
        intent_id=value.intent_id,
        allowed=True,
        blockers=(),
        warnings=(),
        quantity=0.1,
        estimated_notional=10.0,
        estimated_risk_usdt=0.5,
        capital_basis_usdt=50.0,
    )


def rules(*, tick_size: float = 0.01, step_size: float = 0.001) -> SymbolTradingRules:
    return SymbolTradingRules(
        symbol="BTCUSDT",
        market_type="spot",
        min_qty=0.001,
        step_size=step_size,
        min_notional=5.0,
        tick_size=tick_size,
    )


class FakeClient:
    def __init__(self, *, fail_protection: bool = False, unknown_entry: bool = False):
        self.fail_protection = fail_protection
        self.unknown_entry = unknown_entry
        self.calls = []

    def configure_futures_symbol(self, symbol, leverage):
        self.calls.append(("configure", symbol, leverage))

    def place_order(self, market_type, params):
        self.calls.append(("order", market_type, dict(params)))
        if self.unknown_entry and params.get("timeInForce") == "IOC":
            raise BinanceUnknownExecutionState("timeout")
        return {"orderId": 99, "status": "FILLED", "executedQty": params.get("quantity", "0"), "price": params.get("price", "100")}

    def place_spot_oco(self, params):
        self.calls.append(("oco", dict(params)))
        if self.fail_protection:
            raise RuntimeError("oco unavailable")
        return {"orderListId": 101, "listStatusType": "EXEC_STARTED"}


def test_spot_entry_is_ioc_and_filled_quantity_gets_native_oco(settings):
    value = intent()
    save_execution_intent(settings.db_path, value)
    client = FakeClient()
    manager = BinanceOrderManager(settings.db_path, client, execution_mode="testnet")
    result = manager.submit(value, decision(value), rules())
    assert result["status"] == "protected"
    entry = next(call[2] for call in client.calls if call[0] == "order")
    assert entry["type"] == "LIMIT"
    assert entry["timeInForce"] == "IOC"
    oco = next(call[1] for call in client.calls if call[0] == "oco")
    assert oco["quantity"] == "0.1"
    assert {item["order_role"] for item in list_execution_orders(settings.db_path)} == {"entry", "protection"}


def test_unknown_entry_state_activates_critical_callback_without_retry(settings):
    value = intent()
    save_execution_intent(settings.db_path, value)
    client = FakeClient(unknown_entry=True)
    failures = []
    manager = BinanceOrderManager(settings.db_path, client, execution_mode="testnet", on_critical_failure=failures.append)
    with pytest.raises(BinanceUnknownExecutionState):
        manager.submit(value, decision(value), rules())
    assert failures == ["entry_order_state_unknown"]
    assert len([call for call in client.calls if call[0] == "order"]) == 1
    assert list_execution_orders(settings.db_path)[0]["status"] == "unknown"


def test_protection_failure_emergency_exits_and_triggers_kill_switch(settings):
    value = intent()
    save_execution_intent(settings.db_path, value)
    client = FakeClient(fail_protection=True)
    failures = []
    manager = BinanceOrderManager(settings.db_path, client, execution_mode="testnet", on_critical_failure=failures.append)
    with pytest.raises(ProtectionOrderError):
        manager.submit(value, decision(value), rules())
    market_exit = [call[2] for call in client.calls if call[0] == "order" and call[2]["type"] == "MARKET"]
    assert len(market_exit) == 1
    assert failures == ["protection_order_failed"]
    assert {item["status"] for item in list_execution_orders(settings.db_path)} >= {"protection_failed", "FILLED"}


def test_all_submitted_prices_and_quantity_follow_exchange_steps(settings):
    value = ExecutionIntent.create(
        **{
            **intent().as_dict(),
            "intent_id": "intent_tick_alignment",
            "entry_limit": 100.037,
            "stop_price": 95.019,
            "target_price": 110.029,
        }
    )
    risk = ExecutionRiskDecision(
        **{**decision(value).__dict__, "intent_id": value.intent_id, "quantity": 0.1009}
    )
    save_execution_intent(settings.db_path, value)
    client = FakeClient()
    manager = BinanceOrderManager(settings.db_path, client, execution_mode="testnet")
    manager.submit(value, risk, rules(tick_size=0.05, step_size=0.001))
    entry = next(call[2] for call in client.calls if call[0] == "order")
    protection = next(call[1] for call in client.calls if call[0] == "oco")
    assert entry["price"] == "100"
    assert entry["quantity"] == "0.1"
    assert protection["abovePrice"] == "110"
    assert protection["belowStopPrice"] == "95"
    assert protection["belowPrice"] == "94.9"
