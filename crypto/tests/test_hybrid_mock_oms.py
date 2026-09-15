"""Durable isolated outbox failures; synthetic fills are not performance data."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import socket
import sqlite3

import pytest

from kquant_crypto.hybrid_mock_broker import BrokerRejected, MockBroker, OrderIntent, SymbolRules
from kquant_crypto.hybrid_mock_oms import MockOMS


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


def venue(fee_asset="quote"):
    r = SymbolRules("BTCUSDT", "BTC", "USDT", "0.01", "0.001", "0.001", "100",
                    "1", "1000000", "0.01", "1000000", 10000)
    return MockBroker({r.symbol: r}, {"BTC": "0", "USDT": "1000"}, fee_asset=fee_asset)


def intent(b, iid="signal-entry", **changes):
    return replace(OrderIntent(iid, "BTCUSDT", "BUY", "1", "100", b.rules["BTCUSDT"].rule_hash), **changes)


def start(path, b):
    oms = MockOMS(path, b)
    assert oms.recover()["ready"]
    return oms


def test_begin_lock_failure_blocks_dispatch_until_reconciliation(tmp_path):
    b = venue()
    path = tmp_path / 'locked.sqlite3'
    with start(path, b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        oms.db.execute('PRAGMA busy_timeout=20')
        competitor = sqlite3.connect(path, isolation_level=None)
        try:
            competitor.execute('BEGIN IMMEDIATE')
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                oms.dispatch(i.intent_id, now=2)
            assert not oms.ready
            assert b.submit_calls == 0
            assert oms.order(i.intent_id)['state'] == 'RESERVED'
        finally:
            competitor.rollback()
            competitor.close()
        with pytest.raises(RuntimeError, match='recover'):
            oms.dispatch(i.intent_id, now=3)
        assert oms.recover()['ready']
        oms.dispatch(i.intent_id, now=4)
        assert b.submit_calls == 1


@pytest.mark.parametrize("fault,expected", [("after_accept", "ACKNOWLEDGED"),
                                           ("5xx_after_accept", "ACKNOWLEDGED"), ("before_accept", "UNKNOWN")])
def test_unknown_restart_queries_only_never_blind_submit(tmp_path, fault, expected):
    b = venue()
    i = intent(b)
    path = tmp_path / "oms.sqlite3"
    with start(path, b) as oms:
        first = oms.stage(i, now=1)
        assert oms.stage(i, now=1) == first
        assert Decimal(oms.account()["USDT"]["reserved"]) == Decimal("100.100")
        b.submit_fault = fault
        assert oms.dispatch(i.intent_id, now=1)["state"] == "UNKNOWN"
        with pytest.raises(RuntimeError):
            oms.stage(intent(b, "new-risk"), now=1)
    with MockOMS(path, b) as oms:
        status = oms.recover()
        assert oms.order(i.intent_id)["state"] == expected
        oms.dispatch(i.intent_id, now=2)
        assert b.submit_calls == 1 and b.query_calls >= 2
        assert status["ready"] is (expected != "UNKNOWN")
        assert Decimal(oms.account()["USDT"]["reserved"]) == Decimal("100.100")


def test_crash_after_external_accept_before_local_ack_is_query_recovered(tmp_path, monkeypatch):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    i = intent(b)
    with start(path, b) as oms:
        oms.stage(i, now=1)
        def crash(*args):
            raise RuntimeError("injected crash before ACK commit")
        monkeypatch.setattr(oms, "_ack", crash)
        with pytest.raises(RuntimeError):
            oms.dispatch(i.intent_id, now=1)
        assert oms.order(i.intent_id)["state"] == "SUBMITTING"
    with MockOMS(path, b) as oms:
        assert oms.recover()["ready"]
        assert oms.order(i.intent_id)["state"] == "ACKNOWLEDGED"
        assert b.submit_calls == 1


@pytest.mark.parametrize("fee_asset", ["base", "quote"])
def test_partial_out_of_order_duplicate_fills_accounted_once_and_recovered(tmp_path, fee_asset):
    b = venue(fee_asset)
    path = tmp_path / "oms.sqlite3"
    i = intent(b)
    with start(path, b) as oms:
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        assert oms.db.execute("SELECT count(*) FROM mock_fills").fetchone()[0] == 0
        first = b.fill_order(ack["client_id"], quantity="0.4", price="90", fill_key="first")
        second = b.fill_order(ack["client_id"], quantity="0.6", price="95", fill_key="second")
        assert oms.apply_fill(second)
        assert oms.order(i.intent_id)["state"] == "PARTIALLY_FILLED"
        assert not oms.apply_fill(second)
        assert oms.apply_fill(first)
        assert oms.order(i.intent_id)["state"] == "FILLED"
        assert oms.account() == b.get_account_snapshot()["balances"]
        assert not oms.status()["protection_installed"]
    with MockOMS(path, b) as oms:
        assert oms.recover()["ready"]
        assert oms.status()["fill_cursor"] == 2
        assert oms.db.execute("SELECT count(*) FROM mock_fills").fetchone()[0] == 2
        assert Decimal(oms.account()["BTC"]["total"]) == (Decimal("0.999") if fee_asset == "base" else Decimal("1"))


def test_fill_db_failure_rolls_back_balance_and_fill_then_reconciles(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        fill = b.fill_order(ack["client_id"], quantity="0.4", price="90", fill_key="one")
        before = deepcopy(oms.account())
        oms.db.execute("CREATE TEMP TRIGGER disk_fail BEFORE UPDATE ON mock_balances BEGIN SELECT RAISE(ABORT,'injected disk failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="disk failure"):
            oms.apply_fill(fill)
        assert oms.account() == before
        assert oms.db.execute("SELECT count(*) FROM mock_fills").fetchone()[0] == 0
        assert not oms.ready
        oms.db.execute("DROP TRIGGER disk_fail")
        assert oms.recover()["ready"]
        assert oms.account() == b.get_account_snapshot()["balances"]


def test_cancel_after_partial_and_lost_ack_reconciles_fills_and_remaining_reserve(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        b.fill_order(ack["client_id"], quantity="0.4", price="90", fill_key="one")
        b.cancel_fault = "after_cancel"
        assert oms.cancel(i.intent_id)["state"] == "UNKNOWN"
        assert oms.recover()["ready"]
        assert oms.order(i.intent_id)["state"] == "CANCELED"
        assert Decimal(oms.account()["BTC"]["total"]) == Decimal("0.4")
        assert Decimal(oms.account()["USDT"]["reserved"]) == 0
        assert len(b.orders) == 1


def test_full_fill_wins_cancel_race(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        b.fill_order(ack["client_id"], quantity="1", price="90", fill_key="one")
        assert oms.cancel(i.intent_id)["state"] == "FILLED"
        assert oms.account() == b.get_account_snapshot()["balances"]


def test_definitive_rejection_and_unsent_cancel_stay_terminal_on_restart(tmp_path):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with start(path, b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        assert oms.dispatch(i.intent_id, now=10001)["state"] == "REJECTED"
        j = intent(b, "never-sent")
        oms.stage(j, now=1)
        assert oms.cancel(j.intent_id)["state"] == "CANCELED"
    with MockOMS(path, b) as oms:
        assert oms.recover()["ready"]
        assert oms.order(i.intent_id)["state"] == "REJECTED"
        assert oms.order(j.intent_id)["state"] == "CANCELED"
        assert Decimal(oms.account()["USDT"]["reserved"]) == 0


def test_second_writer_and_foreign_database_are_rejected(tmp_path):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with start(path, b):
        with pytest.raises(OSError):
            MockOMS(path, b)
    with MockOMS(path, b):
        pass
    foreign = tmp_path / "production.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE production(value TEXT)")
    with pytest.raises(ValueError, match="dedicated"):
        MockOMS(foreign, b)


@pytest.mark.parametrize("change", ["epoch", "fee", "rules"])
def test_restart_version_epoch_and_rule_mismatch_rejected(tmp_path, change):
    b = venue()
    path = tmp_path / "oms.sqlite3"
    with start(path, b):
        pass
    if change == "epoch":
        b.epoch = "reset-epoch"
    elif change == "fee":
        b.fee_rate = "0.002"
    else:
        b.rules["BTCUSDT"] = replace(b.rules["BTCUSDT"], step_size="0.002")
    with pytest.raises(ValueError, match="binding mismatch"):
        MockOMS(path, b)


def test_external_balance_and_manual_orders_block_new_risk(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        b.balances["USDT"] -= Decimal("1")
        status = oms.recover()
        assert not status["ready"]
        difference = status['last_reconciliation']
        assert difference['balance_differences'][0]['asset'] == 'USDT'
        assert not difference['market_pnl_inferred']
        assert not difference['automatic_balance_adjustment']
        with pytest.raises(RuntimeError):
            oms.stage(intent(b), now=1)
        b.balances["USDT"] += Decimal("1")
        b.submit_order(intent(b, "manual"), now=1)
        status = oms.recover()
        assert not status["ready"]
        assert status['last_reconciliation']['unmanaged_order_ids']
        assert oms.db.execute("SELECT COUNT(*) FROM mock_events WHERE state='RECONCILIATION'").fetchone()[0] >= 3


def test_reconciliation_difference_survives_restart_without_balance_rewrite(tmp_path):
    b = venue()
    path = tmp_path / 'oms.sqlite3'
    with start(path, b) as oms:
        original = oms.account()
        b.balances['USDT'] -= Decimal('2')
        difference = oms.recover()['last_reconciliation']
        assert oms.account() == original
    with MockOMS(path, b) as oms:
        assert not oms.ready
        assert oms.status()['last_reconciliation'] == difference
        assert oms.account() == original
        assert not oms.recover()['ready']


def test_open_order_snapshot_disconnect_cannot_leave_ready(tmp_path):
    from kquant_crypto.hybrid_mock_broker import UnknownExecution
    b = venue()
    with start(tmp_path / 'oms.sqlite3', b) as oms:
        def disconnected():
            raise UnknownExecution('synthetic open orders unavailable')
        b.get_open_orders = disconnected
        assert not oms.recover()['ready']
        assert oms.reason == 'venue_unavailable'


def test_conflicting_intent_fill_and_insufficient_reserved_funds_fail_closed(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b, quantity="9")
        oms.stage(i, now=1)
        with pytest.raises(ValueError, match="reused"):
            oms.stage(replace(i, quantity="8"), now=1)
        with pytest.raises(BrokerRejected):
            oms.stage(intent(b, "second", quantity="2"), now=1)
        oms.recover()
        ack = oms.dispatch(i.intent_id, now=1)
        fill = b.fill_order(ack["client_id"], quantity="1", price="90", fill_key="one")
        oms.apply_fill(fill)
        with pytest.raises(ValueError, match="conflicting"):
            oms.apply_fill({**fill, "quantity": "2"})
        assert oms.order(i.intent_id)["filled"] == "1"


def test_transaction_failure_before_submit_never_calls_broker(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        oms.db.execute("CREATE TEMP TRIGGER deny_submit BEFORE UPDATE ON mock_outbox BEGIN SELECT RAISE(ABORT,'disk failure'); END")
        with pytest.raises(sqlite3.IntegrityError):
            oms.dispatch(i.intent_id, now=1)
        assert b.submit_calls == 0
        assert oms.order(i.intent_id)["state"] == "RESERVED"


def test_disconnect_after_partial_fill_keeps_unknown_until_query_returns(tmp_path):
    b = venue()
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        b.fill_order(ack["client_id"], quantity="0.4", price="90", fill_key="one")
        b.online = False
        assert not oms.recover()["ready"]
        assert oms.order(i.intent_id)["state"] == "UNKNOWN"
        b.online = True
        assert oms.recover()["ready"]
        assert oms.order(i.intent_id)["filled"] == "0.4"
        assert b.submit_calls == 1


def test_base_fee_reduces_sellable_inventory_and_dust_remains(tmp_path):
    b = venue("base")
    with start(tmp_path / "oms.sqlite3", b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        b.fill_order(ack["client_id"], quantity="1", price="90", fill_key="buy")
        oms.recover()
        with pytest.raises(BrokerRejected):
            oms.stage(intent(b, "oversell", side="SELL"), now=2)
        oms.recover()
        sell = intent(b, "sell", side="SELL", quantity="0.998")
        oms.stage(sell, now=2)
        ack = oms.dispatch(sell.intent_id, now=2)
        b.fill_order(ack["client_id"], quantity="0.998", price="101", fill_key="sell")
        assert oms.recover()["ready"]
        assert Decimal(oms.account()["BTC"]["total"]) == Decimal("0.000002")


def test_backup_of_actual_ledger_restores_without_repeating_fill(tmp_path):
    b = venue()
    path, backup = tmp_path / "original.sqlite3", tmp_path / "backup.sqlite3"
    with start(path, b) as oms:
        i = intent(b)
        oms.stage(i, now=1)
        ack = oms.dispatch(i.intent_id, now=1)
        b.fill_order(ack["client_id"], quantity="0.4", price="90", fill_key="one")
        oms.recover()
        with sqlite3.connect(backup) as target:
            oms.db.backup(target)
    with MockOMS(backup, b) as oms:
        assert oms.recover()["ready"]
        assert oms.order(i.intent_id)["filled"] == "0.4"
        assert oms.db.execute("SELECT count(*) FROM mock_fills").fetchone()[0] == 1
        assert b.submit_calls == 1
