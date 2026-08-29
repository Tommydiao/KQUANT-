from __future__ import annotations

from types import SimpleNamespace

from kquant.longbridge_provider import LongbridgeReadOnlyRuntime


class FakeQuoteContext:
    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.candle_unsubscribed: list[tuple[str, object]] = []

    def subscribe(self, symbols, subtypes) -> None:
        self.subscribed.extend(symbols)

    def unsubscribe(self, symbols, subtypes) -> None:
        self.unsubscribed.extend(symbols)

    def quote(self, symbols):
        return [SimpleNamespace(last_done=100, timestamp="2026-07-13T14:00:00+00:00")]

    def realtime_depth(self, symbol):
        return SimpleNamespace(
            bids=[SimpleNamespace(price=99.9, volume=10)],
            asks=[SimpleNamespace(price=100.1, volume=12)],
        )

    def depth(self, symbol):
        return self.realtime_depth(symbol)

    def subscribe_candlesticks(self, symbol, period, *args):
        return []

    def realtime_candlesticks(self, symbol, period, count):
        return [SimpleNamespace(close=100)]

    def history_candlesticks_by_date(self, symbol, period, adjust_type, start, end):
        return [SimpleNamespace(symbol=symbol, period=period, adjust_type=adjust_type, start=start, end=end)]

    def unsubscribe_candlesticks(self, symbol, period):
        self.candle_unsubscribed.append((symbol, period))


def test_context_is_reused_and_switching_symbol_unsubscribes() -> None:
    runtime = LongbridgeReadOnlyRuntime()
    context = FakeQuoteContext()
    runtime._context = context
    first_context = runtime.context()
    runtime.quote("NVDA.US", 2)
    runtime.realtime_candlesticks("NVDA.US", "Min_1", 10, None, 2)
    runtime.quote("MSFT.US", 2)
    assert runtime.context() is first_context
    assert "NVDA.US" in context.unsubscribed
    assert context.candle_unsubscribed == [("NVDA.US", "Min_1")]
    assert runtime.health()["active_symbol"] == "MSFT.US"
    runtime._executor.shutdown(wait=True)


def test_depth_uses_subscription_cache() -> None:
    runtime = LongbridgeReadOnlyRuntime()
    runtime._context = FakeQuoteContext()
    depth, mode = runtime.depth("NVDA.US", 2)
    assert mode == "subscription_cache"
    assert depth.bids[0].price == 99.9
    assert runtime.health()["depth_subscription_count"] == 1
    runtime._executor.shutdown(wait=True)


def test_history_candlesticks_stays_inside_quote_runtime() -> None:
    runtime = LongbridgeReadOnlyRuntime()
    runtime._context = FakeQuoteContext()

    rows = runtime.history_candlesticks_by_date(
        "NVDA.US", "Min_60", "NoAdjust", "2025-01-01", "2025-03-31", 2
    )

    assert rows[0].symbol == "NVDA.US"
    assert rows[0].start == "2025-01-01"
    assert rows[0].end == "2025-03-31"
    assert runtime.health()["trade_context_enabled"] is False
    runtime._executor.shutdown(wait=True)
