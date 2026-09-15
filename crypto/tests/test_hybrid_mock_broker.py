"""Synthetic-only Spot broker contract tests. No exchange/accounts/credentials."""
from dataclasses import replace
from decimal import Decimal
import ast
from pathlib import Path
import socket

import pytest

from kquant_crypto.hybrid_mock_broker import (BrokerRejected, MockBroker, OrderIntent,
                                             SymbolRules, UnknownExecution, decimal)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden in isolated mock tests")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def rules(**changes):
    return replace(SymbolRules("BTCUSDT", "BTC", "USDT", "0.01", "0.001", "0.001", "100",
                               "1", "1000000", "0.01", "1000000", 10000), **changes)


def broker(**kwargs):
    return MockBroker({"BTCUSDT": rules()}, {"BTC": "2", "USDT": "10000"}, **kwargs)


def intent(b, iid="economic-1", **kwargs):
    return OrderIntent(iid, "BTCUSDT", kwargs.pop("side", "BUY"), kwargs.pop("quantity", "1"),
                       kwargs.pop("limit_price", "100"), b.rules["BTCUSDT"].rule_hash, **kwargs)


def test_capabilities_no_external_entity_or_account_claim():
    cap = broker().get_capabilities()
    assert cap["account_status"] == "UNKNOWN_NOT_ACCESSED"
    assert cap["network"] == "DENY_NO_TRANSPORT"
    assert not cap["credentials"] and not cap["native_protection"]
    assert not cap["testnet_verified"] and cap["G8"] == "NOT_PASSED"
    with pytest.raises(TypeError):
        MockBroker({}, {}, api_key="not-accepted")


@pytest.mark.parametrize("value", [0.1, True, "NaN", "Infinity", "-1", "1e999"])
def test_decimal_rejects_unsafe_inputs(value):
    with pytest.raises(ValueError):
        decimal(value)


@pytest.mark.parametrize("changes", [{"quantity": "0.0009"}, {"quantity": "0.0105"},
                                     {"quantity": "101"}, {"limit_price": "100.001"},
                                     {"quantity": "0.001", "limit_price": "1"}])
def test_filters_reject_never_round_up(changes):
    b = broker()
    with pytest.raises(BrokerRejected):
        b.submit_order(intent(b, **changes), now=1)
    assert not b.orders and b.get_account_snapshot()["balances"]["USDT"]["total"] == "10000"


def test_downward_risk_rounding_still_skips_below_notional():
    b = broker()
    quantity = b.rules["BTCUSDT"].round_quantity("0.0019")
    assert quantity == "0.001"
    with pytest.raises(BrokerRejected):
        b.submit_order(intent(b, quantity=quantity), now=1)


def test_rules_expiry_status_and_open_order_limit():
    b = broker()
    with pytest.raises(BrokerRejected, match="stale"):
        b.submit_order(intent(b), now=10001)
    b.rules["BTCUSDT"] = rules(trading=False)
    with pytest.raises(BrokerRejected):
        b.submit_order(intent(b), now=1)
    b.rules["BTCUSDT"] = rules(max_orders=1)
    b.submit_order(intent(b), now=1)
    with pytest.raises(BrokerRejected, match="order limit"):
        b.submit_order(intent(b, "economic-2"), now=1)


def test_stable_order_identity_immutable_reuse_ack_separate_from_fill():
    b = broker()
    i = intent(b)
    ack = b.submit_order(i, now=1)
    assert ack == b.submit_order(i, now=2)
    assert len(ack["client_order_id"]) <= 36
    assert b.get_fills()["fills"] == []
    assert b.get_order(exchange_order_id=ack["exchange_order_id"]) == ack
    with pytest.raises(BrokerRejected, match="conflicts"):
        b.submit_order(replace(i, quantity="2"), now=2)
    other = broker()
    assert other.submit_order(i, now=1) == ack
    assert broker(epoch="epoch-2").client_id(i.intent_id) != ack["client_order_id"]


@pytest.mark.parametrize("fee_asset,expected_btc,expected_usdt", [
    ("quote", "2.4", "9963.964"), ("base", "2.3996", "9964")])
def test_partial_fill_idempotency_fee_asset_and_balance_identity(fee_asset, expected_btc, expected_usdt):
    b = broker(fee_asset=fee_asset)
    cid = b.submit_order(intent(b), now=1)["client_order_id"]
    fill = b.fill_order(cid, quantity="0.4", price="90", fill_key="trade-a")
    assert fill == b.fill_order(cid, quantity="0.4", price="90", fill_key="trade-a")
    assert len(b.get_fills()["fills"]) == 1
    assert b.get_order(cid)["status"] == "PARTIALLY_FILLED"
    account = b.get_account_snapshot()["balances"]
    assert Decimal(account["BTC"]["total"]) == Decimal(expected_btc)
    assert Decimal(account["USDT"]["total"]) == Decimal(expected_usdt)
    for value in account.values():
        assert Decimal(value["free"]) + Decimal(value["reserved"]) == Decimal(value["total"])
    with pytest.raises(BrokerRejected, match="conflicting"):
        b.fill_order(cid, quantity="0.5", price="90", fill_key="trade-a")


def test_fill_quantity_and_limit_and_spot_no_oversell():
    b = broker()
    with pytest.raises(BrokerRejected, match="balance"):
        b.submit_order(intent(b, side="SELL", quantity="3"), now=1)
    cid = b.submit_order(intent(b), now=1)["client_order_id"]
    for q, price in [("2", "90"), ("1", "101")]:
        with pytest.raises(BrokerRejected):
            b.fill_order(cid, quantity=q, price=price, fill_key="invalid")
    assert not b.fills


def test_ioc_fixture_remainder_expires_and_cancel_race_keeps_full_fill():
    b = broker()
    cid = b.submit_order(intent(b, time_in_force="IOC"), now=1)["client_order_id"]
    b.fill_order(cid, quantity="0.4", price="90", fill_key="a")
    assert b.finish_ioc(cid)["status"] == "EXPIRED"
    assert b.get_account_snapshot()["balances"]["USDT"]["reserved"] == "0"
    cid2 = b.submit_order(intent(b, "other"), now=1)["client_order_id"]
    b.fill_order(cid2, quantity="1", price="90", fill_key="b")
    assert b.cancel_order(cid2)["status"] == "FILLED"


def test_timeout_after_accept_and_before_accept_are_both_unknown():
    for fault, accepted in [("before_accept", False), ("after_accept", True), ("5xx_after_accept", True)]:
        b = broker()
        b.submit_fault = fault
        i = intent(b)
        with pytest.raises(UnknownExecution):
            b.submit_order(i, now=1)
        assert bool(b.get_order(b.client_id(i.intent_id))) is accepted


def test_no_production_or_network_imports():
    root = Path(__file__).parents[1] / "kquant_crypto"
    forbidden = {"httpx", "requests", "socket", "websockets", "subprocess", "config", "binance_execution",
                 "order_manager", "execution_store", "candidate_simulation", "candidate_forward"}
    for name in ("hybrid_mock_broker.py", "hybrid_mock_oms.py"):
        tree = ast.parse((root / name).read_text())
        imports = {n.module.split(".")[-1] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imports.update(a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
        assert not imports & forbidden


def test_decimal_results_independent_of_ambient_context():
    from decimal import localcontext
    b = broker()
    with localcontext() as ctx:
        ctx.prec = 3
        cid = b.submit_order(intent(b, quantity="1.234"), now=1)["client_order_id"]
        b.fill_order(cid, quantity="0.1234", price="99.99", fill_key="exact")
        assert b.get_account_snapshot()["balances"]["USDT"]["total"] == "9987.648895234"


@pytest.mark.parametrize("base", ["BTC", "ETH", "SOL"])
def test_fixed_spot_symbols_keep_distinct_ids(base):
    r = replace(rules(), symbol=base + "USDT", base=base)
    b = MockBroker({r.symbol: r}, {"USDT": "1000"})
    i = OrderIntent("signal-" + base, r.symbol, "BUY", "1", "100", r.rule_hash)
    assert b.submit_order(i, now=1)["intent"]["symbol"] == r.symbol
