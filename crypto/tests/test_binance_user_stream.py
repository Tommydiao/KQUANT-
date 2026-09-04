from __future__ import annotations

from types import SimpleNamespace

from kquant_crypto.binance_user_stream import BinanceUserDataRuntime, normalize_account_event


def test_normalize_spot_execution_report():
    event = normalize_account_event({
        "e": "executionReport", "E": 1788307200000, "c": "client-1",
        "X": "PARTIALLY_FILLED", "t": 11, "l": "0.2", "L": "100.5",
        "n": "0.001", "N": "BNB",
    }, "spot")
    assert event.client_order_id == "client-1"
    assert event.order_status == "PARTIALLY_FILLED"
    assert event.trade_id == "11"
    assert event.quantity == 0.2


def test_normalize_futures_order_trade_update():
    event = normalize_account_event({
        "e": "ORDER_TRADE_UPDATE", "E": 1788307200000,
        "o": {"c": "client-2", "X": "FILLED", "t": 12, "l": "1", "L": "20", "n": "0.01", "N": "USDT"},
    }, "perpetual")
    assert event.client_order_id == "client-2"
    assert event.order_status == "FILLED"
    assert event.price == 20.0


def test_account_event_is_deduplicated(settings):
    controller = SimpleNamespace(settings=SimpleNamespace(mode=SimpleNamespace(value="testnet")))
    runtime = BinanceUserDataRuntime(settings.db_path, controller)
    payload = {"e": "outboundAccountPosition", "E": 1788307200000, "u": 9, "B": []}
    runtime.process(payload, "spot")
    runtime.process(payload, "spot")
    from kquant_crypto.db.migrations import connect
    with connect(settings.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM crypto_exchange_account_events").fetchone()[0]
    assert count == 1
