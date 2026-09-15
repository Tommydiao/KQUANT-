"""Runnable synthetic reservation/trigger/exit lifecycle; never live protection."""
from decimal import Decimal
import socket

import pytest

from kquant_crypto.hybrid_mock_broker import BrokerRejected, OrderIntent, SymbolRules
from kquant_crypto.hybrid_mock_oms import MockOMS
from kquant_crypto.hybrid_mock_protection import MockEmergencyPolicy, MockProtection, ProtectiveMockBroker


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("no network in mock protection")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def venue(fee_asset="quote"):
    rule = SymbolRules("BTCUSDT", "BTC", "USDT", "0.01", "0.001", "0.001", "100",
                       "1", "1000000", "0.01", "1000000", 10000)
    return ProtectiveMockBroker({rule.symbol: rule}, {"BTC": "0", "USDT": "1000"}, fee_asset=fee_asset)


def protector(oms, action="CANCEL_ENTRY_REMAINDERS_AND_ALERT", expiry=10):
    return MockProtection(oms, {"BTCUSDT": {"stop_price": "95", "limit_price": "94"}},
                          admission_until=expiry, emergency_policy=MockEmergencyPolicy("fixture-policy", action))


def entry(oms, iid="entry"):
    i = OrderIntent(iid, "BTCUSDT", "BUY", "1", "100", oms.broker.rules["BTCUSDT"].rule_hash)
    oms.stage(i, now=1)
    return oms.dispatch(iid, now=1)


def partial(oms, protection, *, key="one", quantity="0.4", now=2):
    row = oms.order("entry")
    fill = oms.broker.fill_order(row["client_id"], quantity=quantity, price="100", fill_key=key)
    protection.on_fill(fill, now=now)
    return fill


def tickets(protection, kind="protection"):
    return [t for t in protection.state["tickets"] if t["kind"] == kind]


def test_partial_fill_reserves_protection_and_cannot_double_sell(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        assert not p.reconcile_and_protect(now=1)["guard"]["blocked"]
        entry(oms)
        partial(oms, p)
        assert oms.account()["BTC"] == {"total": "0.4", "reserved": "0.4", "free": "0"}
        assert not p.status()["guard"]["blocked"]
        assert p.status()["uncovered_inventory"]["BTC"] == "0"
        sell = OrderIntent("illegal-second-sell", "BTCUSDT", "SELL", "0.4", "94", b.rules["BTCUSDT"].rule_hash)
        with pytest.raises(BrokerRejected):
            oms.stage(sell, now=2)
        assert len(b.orders) == 2


def test_incremental_fill_gets_incremental_lock_and_duplicates_do_not_add_orders(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        first = partial(oms, p)
        p.on_fill(first, now=2)
        partial(oms, p, key="two", quantity="0.3")
        assert len(tickets(p)) == 2
        assert [t["intent"]["quantity"] for t in tickets(p)] == ["0.4", "0.3"]
        assert oms.account()["BTC"]["reserved"] == "0.7"
        assert not p.status()["guard"]["blocked"]


def test_partial_fill_guards_new_buys_before_protection_callback(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        row = entry(oms)
        fill = b.fill_order(row["client_id"], quantity="0.4", price="100", fill_key="one")
        oms.apply_fill(fill)
        assert oms.risk_guard()["blocked"]
        with pytest.raises(BrokerRejected, match="guard"):
            entry(oms, "new-risk")
        p.reconcile_and_protect(now=2)
        assert not oms.risk_guard()["blocked"]


def test_trigger_is_not_fill_or_guaranteed_stop_price_and_admission_expiry_keeps_protection(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        t = tickets(p)[0]
        cid = b.client_id(t["intent"]["intent_id"])
        with pytest.raises(BrokerRejected, match="not triggered"):
            b.fill_order(cid, quantity="0.4", price="94", fill_key="early")
        p.reconcile_and_protect(now=11)
        assert oms.risk_guard()["blocked"]
        with pytest.raises(BrokerRejected, match="guard"):
            oms.stage(OrderIntent("late", "BTCUSDT", "BUY", "1", "100", b.rules["BTCUSDT"].rule_hash), now=11)
        result = p.trigger("BTCUSDT", bid="90", observation_id="gap")
        assert result[0]["triggered"] and not result[0]["fill_guaranteed"]
        assert len(b.fills) == 1
        # Stop-limit below-market gap can remain unfilled. No fabricated liquidation.
        with pytest.raises(BrokerRejected):
            b.fill_order(cid, quantity="0.4", price="90", fill_key="unreachable")
        fill = b.fill_order(cid, quantity="0.4", price="94", fill_key="later-explicit-liquidity")
        p.on_fill(fill, now=12)
        assert oms.account()["BTC"]["total"] == "0"
        assert b.get_order(cid)["status"] == "FILLED"
        assert p.status()["native_protection_status"] == "UNKNOWN_UNVERIFIED"
        assert p.status()["G8"] == "NOT_PASSED"


def test_strategy_exit_reconciles_cancel_before_reusing_inventory(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        protect_id = tickets(p)[0]["intent"]["intent_id"]
        p.strategy_exit("BTCUSDT", limit_price="90", now=3)
        assert oms.order("entry")["state"] == "CANCELED"
        assert oms.order(protect_id)["state"] == "CANCELED"
        exit_ticket = tickets(p, "strategy_exit")[0]
        assert exit_ticket["intent"]["quantity"] == "0.4"
        count = len(b.orders)
        p.strategy_exit("BTCUSDT", limit_price="90", now=3)
        assert len(b.orders) == count
        cid = b.client_id(exit_ticket["intent"]["intent_id"])
        fill = b.fill_order(cid, quantity="0.4", price="90", fill_key="exit")
        p.on_fill(fill, now=3)
        assert oms.account()["BTC"]["total"] == "0"


def test_lost_protection_cancel_ack_blocks_exit_until_query_proves_release(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        oms.cancel("entry")
        b.cancel_fault = "after_cancel"
        p.strategy_exit("BTCUSDT", limit_price="90", now=3)
        assert not tickets(p, "strategy_exit")
        assert oms.account()["BTC"]["reserved"] == "0.4"
        p.strategy_exit("BTCUSDT", limit_price="90", now=3)
        assert len(tickets(p, "strategy_exit")) == 1
        assert len(b.orders) == 3


def test_protection_fill_wins_cancel_race_no_replacement_sell(tmp_path, monkeypatch):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        oms.cancel("entry")
        cid = b.client_id(tickets(p)[0]["intent"]["intent_id"])
        p.trigger("BTCUSDT", bid="94", observation_id="hit")
        original = b.cancel_order

        def race(client_id):
            if client_id == cid:
                b.fill_order(cid, quantity="0.4", price="94", fill_key="race")
            return original(client_id)

        monkeypatch.setattr(b, "cancel_order", race)
        p.strategy_exit("BTCUSDT", limit_price="90", now=3)
        assert not tickets(p, "strategy_exit")
        assert oms.account()["BTC"]["total"] == "0"


@pytest.mark.parametrize("action,entry_state", [("HOLD_AND_ALERT", "PARTIALLY_FILLED"),
                                                ("CANCEL_ENTRY_REMAINDERS_AND_ALERT", "CANCELED")])
def test_failure_latches_guard_and_applies_only_explicit_emergency_policy(tmp_path, action, entry_state):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with MockOMS(path, b) as oms:
        p = protector(oms, action=action)
        p.reconcile_and_protect(now=1)
        entry(oms)
        b.protection_fault = True
        partial(oms, p)
        assert p.state["failure_latched"]
        assert oms.order("entry")["state"] == entry_state
        assert oms.risk_guard()["blocked"]
        assert all(f["side"] == "BUY" for f in b.fills)
        with pytest.raises(BrokerRejected):
            entry(oms, "forbidden")
    with MockOMS(path, b) as oms:
        p = protector(oms, action=action)
        p.reconcile_and_protect(now=3)
        with pytest.raises(BrokerRejected):
            entry(oms, "still-forbidden")
        assert not p.state["alerts"][0]["delivered_to_owner"]


def test_missing_emergency_policy_and_changed_binding_are_rejected(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        with pytest.raises(ValueError, match="emergency"):
            MockProtection(oms, {"BTCUSDT": {"stop_price": "95", "limit_price": "94"}},
                           admission_until=10, emergency_policy=None)
        protector(oms)
        with pytest.raises(ValueError, match="binding"):
            protector(oms, expiry=20)
    with pytest.raises(ValueError):
        MockEmergencyPolicy("unapproved-sale", "SELL_ALL")


def test_existing_reserved_buy_cannot_dispatch_after_admission_expiry(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        oms.stage(OrderIntent("pending", "BTCUSDT", "BUY", "1", "100", b.rules["BTCUSDT"].rule_hash), now=1)
        with pytest.raises(BrokerRejected):
            oms.dispatch("pending", now=11)
        assert b.submit_calls == 0


def test_restart_reuses_confirmed_protection_without_extra_reservation(tmp_path):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        ids = list(b.orders)
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=2)
        assert list(b.orders) == ids
        assert oms.account()["BTC"]["reserved"] == "0.4"
        assert not oms.risk_guard()["blocked"]


def test_persisted_protection_plan_recovers_crash_before_stage(tmp_path, monkeypatch):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        row = entry(oms)
        fill = b.fill_order(row["client_id"], quantity="0.4", price="100", fill_key="one")
        original = oms.stage

        def crash(intent, **kwargs):
            if intent.side == "SELL":
                raise RuntimeError("crash before protection stage")
            return original(intent, **kwargs)

        monkeypatch.setattr(oms, "stage", crash)
        with pytest.raises(RuntimeError):
            p.on_fill(fill, now=2)
        assert oms.risk_guard()["blocked"]
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=2)
        assert len(tickets(p)) == 1
        assert len(b.orders) == 2
        assert oms.account()["BTC"]["reserved"] == "0.4"


def test_base_fee_dust_is_explicit_uncovered_not_silently_protected(tmp_path):
    b = venue("base")
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        assert Decimal(p.status()["uncovered_inventory"]["BTC"]) > 0
        assert oms.risk_guard()["blocked"]
        assert Decimal(oms.account()["BTC"]["reserved"]) <= Decimal(oms.account()["BTC"]["total"])


def test_incremental_protection_failure_keeps_old_protection_active(tmp_path):
    b = venue()
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        partial(oms, p)
        original = oms.order(tickets(p)[0]["intent"]["intent_id"])
        b.protection_fault = True
        partial(oms, p, key="second", quantity="0.3")
        assert b.get_order(original["client_id"])["status"] == "ACKNOWLEDGED"
        assert oms.risk_guard()["blocked"]
        p.trigger("BTCUSDT", bid="94", observation_id="while-failed")
        fill = b.fill_order(original["client_id"], quantity="0.4", price="94", fill_key="old-protection")
        p.on_fill(fill, now=12)
        assert oms.account()["BTC"]["total"] == "0.3"
        assert oms.risk_guard()["blocked"]


def test_unknown_protection_queries_on_restart_without_second_submission(tmp_path):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=1)
        entry(oms)
        b.submit_fault = "after_accept"
        partial(oms, p)
        assert oms.order(tickets(p)[0]["intent"]["intent_id"])["state"] == "UNKNOWN"
        assert b.submit_calls == 2
    with MockOMS(path, b) as oms:
        p = protector(oms)
        p.reconcile_and_protect(now=3)
        assert b.submit_calls == 2
        assert oms.order(tickets(p)[0]["intent"]["intent_id"])["state"] == "ACKNOWLEDGED"
        assert oms.risk_guard()["blocked"]  # Reconciliation does not reset a failure latch.


def test_ordinary_sell_reservation_is_not_misreported_as_protection(tmp_path):
    b = venue()
    b.balances["BTC"] = Decimal("1")
    with MockOMS(tmp_path / "oms.sqlite3", b) as oms:
        oms.recover()
        sell = OrderIntent("ordinary", "BTCUSDT", "SELL", "1", "110", b.rules["BTCUSDT"].rule_hash)
        oms.stage(sell, now=1)
        oms.dispatch(sell.intent_id, now=1)
        p = protector(oms)
        result = p.reconcile_and_protect(now=2)
        assert result["guard"]["blocked"]
        assert result["uncovered_inventory"]["BTC"] == "1"
