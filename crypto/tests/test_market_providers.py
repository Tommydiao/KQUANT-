from __future__ import annotations

from datetime import UTC, datetime

from kquant_crypto.market_models import SequenceTracker
from kquant_crypto.provider_runtime import ProviderSupervisor
from kquant_crypto.providers.binance import build_stream_names, normalize_binance_message
from kquant_crypto.providers.coinbase import build_subscription as coinbase_subscription, normalize_coinbase_message
from kquant_crypto.providers.kraken import normalize_kraken_message
from kquant_crypto.providers.okx import build_subscription as okx_subscription, normalize_okx_message


NOW = datetime(2026, 8, 22, tzinfo=UTC)


def test_binance_public_events_share_canonical_contract():
    event = normalize_binance_message({"stream": "btcusdt@bookTicker", "data": {"e": "bookTicker", "E": 1000, "s": "BTCUSDT", "u": 8, "b": "100", "B": "2", "a": "101", "A": "3"}}, received_at=NOW)
    assert event is not None
    assert event.asset_id == "asset:btc"
    assert event.instrument_id == "binance:spot:BTCUSDT"
    assert event.event_type == "book_ticker"
    assert event.sequence == 8
    assert len(build_stream_names(["BTCUSDT"], futures=True)) == 5


def test_binance_kline_marks_forming_bar_without_treating_it_as_closed():
    event = normalize_binance_message({"data": {"e": "kline", "E": 1000, "s": "ETHUSDT", "k": {"t": 1000, "s": "ETHUSDT", "i": "1m", "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": False}}}, received_at=NOW)
    assert event is not None
    assert event.payload["closed"] is False


def test_okx_and_reference_messages_normalize_without_credentials():
    okx = normalize_okx_message({"arg": {"channel": "tickers", "instId": "BTC-USDT"}, "data": [{"instId": "BTC-USDT", "ts": "1000", "last": "1", "bidPx": "0.9", "askPx": "1.1"}]}, received_at=NOW)
    assert okx[0].venue == "okx"
    assert okx[0].payload["bid"] == "0.9"
    assert okx_subscription(["BTCUSDT"])["args"][0]["instId"] == "BTC-USDT"
    coinbase = normalize_coinbase_message({"channel": "ticker", "sequence_num": 3, "timestamp": "2026-08-22T00:00:00Z", "events": [{"type": "snapshot", "tickers": [{"product_id": "BTC-USD", "price": "1", "best_bid": "0.9", "best_ask": "1.1"}]}]}, received_at=NOW)
    assert coinbase[0].instrument_id == "coinbase:spot:BTC-USD"
    assert coinbase_subscription(["BTCUSDT"])["product_ids"] == ["BTC-USD"]
    kraken = normalize_kraken_message({"channel": "ticker", "data": [{"symbol": "BTC/USD", "last": 1, "bid": 0.9, "ask": 1.1}]}, received_at=NOW)
    assert kraken[0].asset_id == "asset:btc"


def test_sequence_gap_duplicate_and_out_of_order_are_distinguished():
    tracker = SequenceTracker()
    assert tracker.observe("btc", 1) == "first"
    assert tracker.observe("btc", 3, previous_sequence=1) == "ok"
    assert tracker.observe("btc", 5, previous_sequence=3) == "ok"
    assert tracker.observe("btc", 7, previous_sequence=4) == "gap"
    assert tracker.observe("btc", 7) == "duplicate"
    assert tracker.observe("btc", 2) == "out_of_order"
    assert tracker.gaps == 1
    assert tracker.duplicates == 1
    assert tracker.out_of_order == 1


def test_non_strict_provider_sequence_can_jump_without_being_a_gap():
    tracker = SequenceTracker()
    assert tracker.observe("ticker", 10, strict=False) == "first"
    assert tracker.observe("ticker", 100, strict=False) == "ok"
    assert tracker.gaps == 0


def test_binance_supervisor_runs_spot_and_perpetual_adapters(settings):
    supervisor = ProviderSupervisor(settings)
    adapters = supervisor._adapters("binance")
    assert [adapter.futures for adapter in adapters] == [False, True]
