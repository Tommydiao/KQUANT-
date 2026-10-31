from __future__ import annotations

import os
import threading
import queue
import time
from collections import OrderedDict
from types import SimpleNamespace
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable


class MarketMailbox:
    """Coalesce display snapshots, but never replace a confirmed candle."""
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.serial = 0
        self.coalesced = 0

    def put_nowait(self, item):
        kind, symbol, event, _ = item
        with self.condition:
            self.serial += 1
            key = (kind, symbol, str(getattr(event, "period", "")))
            if kind == "candle" and getattr(event, "is_confirmed", False):
                key += (self.serial,)
            if key in self.pending:
                self.coalesced += 1
                if kind == "quote":
                    previous = self.pending[key][2]
                    fields = ("last_done", "open", "high", "low", "timestamp", "volume", "turnover", "trade_status", "trade_session", "current_volume", "current_turnover")
                    values = {name: getattr(event, name, None) if getattr(event, name, None) is not None else getattr(previous, name, None) for name in fields}
                    item = (kind, symbol, SimpleNamespace(**values), item[3])
            self.pending[key] = item
            self.condition.notify()

    def get(self, block=True, timeout=None):
        deadline = time.monotonic() + timeout if timeout is not None else None
        with self.condition:
            while not self.pending:
                remaining = None if deadline is None else deadline - time.monotonic()
                if not block or (remaining is not None and remaining <= 0):
                    raise queue.Empty
                self.condition.wait(remaining)
            return self.pending.popitem(last=False)[1]

    def get_nowait(self):
        return self.get(False)

    def qsize(self):
        with self.condition:
            return len(self.pending)

    def empty(self):
        return self.qsize() == 0


class LongbridgeReadOnlyRuntime:
    """Persistent, quote-only Longbridge SDK runtime.

    The runtime never creates a trade context. Calls are serialized because the
    SDK quote context owns a network event loop and is safest when reused from a
    single worker.
    """

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._context: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kquant-longbridge-quote")
        self._quote_subscriptions: set[str] = set()
        self._depth_subscriptions: set[str] = set()
        self._candle_subscriptions: set[tuple[str, str]] = set()
        self._candle_periods: dict[tuple[str, str], Any] = {}
        self._active_symbol: str | None = None
        self._max_subscription_symbols = 1
        self._owners: dict[str, dict[str, Any]] = {}
        self._event_queues: dict[str, queue.Queue] = {}
        self._event_filters: dict[str, dict] = {}
        self._dropped_events = 0
        self._callback_context: Any | None = None
        self._restore_failures: dict[str, str] = {}
        self._queue_timeouts = 0

    def _build_context(self) -> Any:
        from longbridge.openapi import Config, QuoteContext  # type: ignore

        config = Config.from_apikey(
            os.environ.get("LONGBRIDGE_APP_KEY"),
            os.environ.get("LONGBRIDGE_APP_SECRET"),
            os.environ.get("LONGBRIDGE_ACCESS_TOKEN"),
            enable_print_quote_packages=False,
            enable_papertrading=False,
        )
        return QuoteContext(config)

    def context(self) -> Any:
        with self._state_lock:
            if self._context is None:
                self._context = self._build_context()
                self._install_callbacks(self._context)
                self._restore_failures.clear()
                from longbridge.openapi import SubType
                for flag, subtype, actual in (("quote", SubType.Quote, self._quote_subscriptions),
                                              ("depth", SubType.Depth, self._depth_subscriptions)):
                    symbols = sorted({item["symbol"] for item in self._owners.values() if item.get(flag)})
                    for offset in range(0, len(symbols), 50):
                        batch = symbols[offset:offset + 50]
                        try:
                            self._context.subscribe(batch, [subtype])
                            actual.update(batch)
                        except Exception as exc:
                            self._restore_failures[f"{flag}:{offset}"] = type(exc).__name__
                for key, request in self._owners.items():
                    try:
                        self._subscribe_owned(self._context, {**request, "quote": False, "depth": False})
                    except Exception as exc:
                        self._restore_failures[key] = type(exc).__name__
            return self._context

    def _install_callbacks(self, context: Any) -> None:
        if self._callback_context is context:
            return
        for kind, method in (("candle", "set_on_candlestick"), ("quote", "set_on_quote"), ("depth", "set_on_depth")):
            setter = getattr(context, method, None)
            if callable(setter):
                setter(lambda symbol, event, kind=kind: self._enqueue_event(kind, symbol, event))
        self._callback_context = context

    def _enqueue_event(self, kind: str, symbol: str, event: Any) -> None:
        # SDK callbacks only enqueue. No database, calculation, or provider calls.
        received_at = datetime.now(UTC).isoformat()
        for owner, sink in tuple(self._event_queues.items()):
            requests = [r for r in tuple(self._owners.values()) if r["owner"] == owner and r["symbol"] == symbol]
            if not any((kind == "candle" and str(r.get("period")) == str(getattr(event, "period", None)))
                       or (kind != "candle" and r.get(kind)) for r in requests):
                continue
            filters = self._event_filters.get(owner)
            if filters:
                if kind not in filters["kinds"]:
                    continue
                if filters.get("confirmed_only") and not getattr(event, "is_confirmed", False):
                    continue
                if not any(request["owner"] == owner and request["symbol"] == symbol
                           and (kind != "candle" or str(request.get("period")) == str(getattr(event, "period", None)))
                           for request in tuple(self._owners.values())):
                    continue
            try:
                sink.put_nowait((kind, symbol, event, received_at))
            except queue.Full:
                self._dropped_events += 1

    def event_queue(self, owner: str, *, kinds=None, confirmed_only=False) -> queue.Queue:
        with self._state_lock:
            if kinds is not None:
                self._event_filters[owner] = {"kinds": tuple(kinds), "confirmed_only": confirmed_only}
            # Confirmed-only streams have at most one event per symbol/period.
            # Never drop their evidence when a consumer is briefly unavailable.
            return self._event_queues.setdefault(owner, queue.Queue() if confirmed_only else MarketMailbox())

    def _subscribe_owned(self, context: Any, request: dict) -> None:
        from longbridge.openapi import SubType
        symbol = request["symbol"]
        for flag, subtype, actual in (("quote", SubType.Quote, self._quote_subscriptions),
                                      ("depth", SubType.Depth, self._depth_subscriptions)):
            if request.get(flag) and symbol not in actual:
                context.subscribe([symbol], [subtype])
                actual.add(symbol)
        period = request.get("period")
        key = (symbol, str(period))
        if period is not None and key not in self._candle_subscriptions:
            context.subscribe_candlesticks(symbol, period)
            self._candle_subscriptions.add(key)
            self._candle_periods[key] = period

    def retain_subscription(self, owner: str, symbol: str, *, quote: bool = False,
                            depth: bool = False, period: Any = None, timeout_seconds: int = 10) -> None:
        if not owner or owner == "ui":
            raise ValueError("EXPLICIT_BACKGROUND_OWNER_REQUIRED")
        request = {"symbol": symbol, "quote": quote, "depth": depth, "period": period}
        key = f"{owner}:{symbol}:{period}"
        def operation(context: Any) -> None:
            self._install_callbacks(context)
            self._subscribe_owned(context, request)
            self._owners[key] = {**request, "owner": owner}
        self.call("retain_subscription", operation, timeout_seconds)

    def _retained(self, symbol: str, kind: str, period: Any = None) -> bool:
        return any(item["symbol"] == symbol and
                   (str(item.get("period")) == str(period) if kind == "candle" else item.get(kind))
                   for item in self._owners.values())

    def retain_quote_group(self, owner: str, symbols: list[str], timeout_seconds=15) -> None:
        if not owner or len(symbols) > 50:
            raise ValueError("BOUNDED_OWNER_REQUIRED")
        def operation(context):
            from longbridge.openapi import SubType
            for symbol in symbols:
                self._owners[f"{owner}:{symbol}:None"] = {"owner": owner, "symbol": symbol, "quote": True, "depth": True, "period": None}
            for kind, subtype, actual in (("quote", SubType.Quote, self._quote_subscriptions),
                                          ("depth", SubType.Depth, self._depth_subscriptions)):
                missing = [symbol for symbol in symbols if symbol not in actual]
                if missing:
                    context.subscribe(missing, [subtype])
                    actual.update(missing)
        self.call("retain_quote_group", operation, timeout_seconds)

    def release_subscriptions(self, owner: str, timeout_seconds: int = 10) -> None:
        # Stop delivery even if the provider is unavailable during unsubscribe.
        with self._state_lock:
            self._event_queues.pop(owner, None)
            self._event_filters.pop(owner, None)
        def operation(context: Any) -> None:
            from longbridge.openapi import SubType
            removed = [item for item in self._owners.values() if item["owner"] == owner]
            self._owners = {key: item for key, item in self._owners.items() if item["owner"] != owner}
            symbols = {item["symbol"] for item in removed if item["symbol"] != self._active_symbol}
            for kind, subtype, actual in (("quote", SubType.Quote, self._quote_subscriptions),
                                          ("depth", SubType.Depth, self._depth_subscriptions)):
                release = sorted(symbol for symbol in symbols if symbol in actual and not self._retained(symbol, kind))
                for offset in range(0, len(release), 50):
                    batch = release[offset:offset + 50]
                    context.unsubscribe(batch, [subtype])
                    actual.difference_update(batch)
            for symbol in symbols:
                self._release_unowned(context, symbol)
            self._event_queues.pop(owner, None)
            self._event_filters.pop(owner, None)
        self.call("release_subscriptions", operation, timeout_seconds)

    def _release_unowned(self, context: Any, symbol: str) -> None:
        from longbridge.openapi import SubType
        for kind, subtype, actual in (("quote", SubType.Quote, self._quote_subscriptions),
                                      ("depth", SubType.Depth, self._depth_subscriptions)):
            if symbol in actual and not self._retained(symbol, kind):
                context.unsubscribe([symbol], [subtype])
                actual.discard(symbol)
        for key in tuple(self._candle_subscriptions):
            period = self._candle_periods.get(key, key[1])
            if key[0] == symbol and not self._retained(symbol, "candle", period):
                context.unsubscribe_candlesticks(symbol, period)
                self._candle_subscriptions.discard(key)
                self._candle_periods.pop(key, None)

    def _reset(self) -> None:
        with self._state_lock:
            context = self._context
            self._context = None
            self._quote_subscriptions.clear()
            self._depth_subscriptions.clear()
            self._candle_subscriptions.clear()
            self._candle_periods.clear()
            self._active_symbol = None
            self._callback_context = None
        close = getattr(context, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def call(self, label: str, fn: Callable[[Any], Any], timeout_seconds: int) -> Any:
        future = self._executor.submit(lambda: fn(self.context()))
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            if future.cancel():
                self._queue_timeouts += 1
                raise TimeoutError(f"Longbridge {label} queue deadline exceeded after {timeout_seconds}s") from exc
            # Never close a context while its SDK operation is still running.
            future.add_done_callback(lambda completed: self._reset())
            raise TimeoutError(f"Longbridge {label} timed out after {timeout_seconds}s") from exc
        except Exception as exc:
            # A bad symbol, entitlement, or request quota is not a broken socket.
            if isinstance(exc, (ConnectionError, OSError)):
                self._reset()
            raise

    def _activate_symbol(self, context: Any, symbol: str) -> None:
        if self._active_symbol == symbol:
            return
        previous = self._active_symbol
        if previous:
            self._release_unowned(context, previous)
        self._active_symbol = symbol

    def quote(self, symbol: str, timeout_seconds: int) -> Any:
        def operation(context: Any) -> Any:
            self._activate_symbol(context, symbol)
            # Subscribe once so the SDK maintains a websocket-backed quote cache.
            # The pull call remains the authoritative response for this request.
            if symbol not in self._quote_subscriptions:
                try:
                    from longbridge.openapi import SubType  # type: ignore

                    context.subscribe([symbol], [SubType.Quote])
                    self._quote_subscriptions.add(symbol)
                except Exception:
                    # A subscription entitlement failure must not hide a pull-quote
                    # response. The caller will still expose the provider status.
                    pass
            return context.quote([symbol])

        return self.call("quote", operation, timeout_seconds)

    def pull_quote(self, symbol: str, timeout_seconds: int) -> Any:
        """Pull a quote without changing the websocket subscription owner.

        Background research jobs use this path so a multi-symbol scan cannot
        evict the symbol currently shown by the chart or realtime supervisor.
        """

        return self.call("pull_quote", lambda context: context.quote([symbol]), timeout_seconds)

    def pull_quotes(self, symbols: list[str], timeout_seconds: int) -> Any:
        """Pull a bounded quote batch without changing subscription ownership."""

        return self.call("pull_quotes", lambda context: context.quote(symbols), timeout_seconds)

    def static_info(self, symbols: list[str], timeout_seconds: int) -> Any:
        """Read security identities in one provider request."""

        return self.call("static_info", lambda context: context.static_info(symbols), timeout_seconds)

    def depth(self, symbol: str, timeout_seconds: int) -> tuple[Any, str]:
        def operation(context: Any) -> tuple[Any, str]:
            self._activate_symbol(context, symbol)
            try:
                from longbridge.openapi import SubType  # type: ignore

                if symbol not in self._depth_subscriptions:
                    context.subscribe([symbol], [SubType.Depth])
                    self._depth_subscriptions.add(symbol)
                try:
                    cached = context.realtime_depth(symbol)
                except Exception:
                    cached = None
                if cached is not None:
                    return cached, "subscription_cache"
            except Exception:
                pass
            return context.depth(symbol), "pull"

        return self.call("depth", operation, timeout_seconds)

    def pull_depth(self, symbol: str, timeout_seconds: int) -> tuple[Any, str]:
        """Pull one depth snapshot without subscribing or changing active symbol."""

        return self.call("pull_depth", lambda context: (context.depth(symbol), "isolated_pull"), timeout_seconds)

    def candlesticks(
        self,
        symbol: str,
        period: Any,
        count: int,
        adjust_type: Any,
        timeout_seconds: int,
    ) -> Any:
        return self.call(
            "candlesticks",
            lambda context: context.candlesticks(symbol, period, count, adjust_type),
            timeout_seconds,
        )

    def history_candlesticks_by_date(
        self,
        symbol: str,
        period: Any,
        adjust_type: Any,
        start: Any,
        end: Any,
        timeout_seconds: int,
        trade_sessions: Any = None,
    ) -> Any:
        """Read a bounded historical page without creating a trade context."""

        return self.call(
            "history_candlesticks_by_date",
            lambda context: context.history_candlesticks_by_date(
                symbol, period, adjust_type, start, end
            ) if trade_sessions is None else context.history_candlesticks_by_date(
                symbol, period, adjust_type, start, end, trade_sessions
            ),
            timeout_seconds,
        )

    def realtime_candlesticks(
        self,
        symbol: str,
        period: Any,
        count: int,
        adjust_type: Any,
        timeout_seconds: int,
    ) -> tuple[Any, str]:
        """Read websocket-backed bars, falling back to the candle pull endpoint.

        Longbridge keeps real-time candlesticks locally after subscription.  The
        first subscription can return initial bars, while a new context may not
        have cache entries yet; in that case the regular pull endpoint seeds the
        response without creating another QuoteContext.
        """

        period_key = str(period)

        def operation(context: Any) -> tuple[Any, str]:
            self._activate_symbol(context, symbol)
            subscription_key = (symbol, period_key)
            initial_rows: Any = []
            if subscription_key not in self._candle_subscriptions:
                try:
                    initial_rows = context.subscribe_candlesticks(symbol, period)
                    self._candle_subscriptions.add(subscription_key)
                    self._candle_periods[subscription_key] = period
                except TypeError:
                    # Older SDK builds require the optional trade-session arg.
                    try:
                        initial_rows = context.subscribe_candlesticks(symbol, period, None)
                        self._candle_subscriptions.add(subscription_key)
                        self._candle_periods[subscription_key] = period
                    except Exception:
                        initial_rows = []
                except Exception:
                    # Subscription rights and websocket setup can be temporarily
                    # unavailable. A direct pull is still useful and must remain
                    # available to the read-only data path.
                    initial_rows = []

            try:
                cached_rows = context.realtime_candlesticks(symbol, period, count)
            except Exception:
                cached_rows = []
            if cached_rows:
                return cached_rows, "subscription_cache"
            if initial_rows:
                return initial_rows, "subscription_initial"
            return context.candlesticks(symbol, period, count, adjust_type), "pull_fallback"

        return self.call("realtime_candlesticks", operation, timeout_seconds)

    def trading_sessions(self, timeout_seconds: int) -> Any:
        return self.call("trading_session", lambda context: context.trading_session(), timeout_seconds)

    def trading_days(self, market: Any, begin: Any, end: Any, timeout_seconds: int) -> Any:
        return self.call(
            "trading_days",
            lambda context: context.trading_days(market, begin, end),
            timeout_seconds,
        )

    def option_expiry_dates(self, symbol: str, timeout_seconds: int) -> Any:
        return self.call(
            "option_expiry_dates",
            lambda context: context.option_chain_expiry_date_list(symbol),
            timeout_seconds,
        )

    def option_chain(self, symbol: str, expiry_date: Any, timeout_seconds: int) -> Any:
        return self.call(
            "option_chain",
            lambda context: context.option_chain_info_by_date(symbol, expiry_date),
            timeout_seconds,
        )

    def option_quotes(self, symbols: list[str], timeout_seconds: int) -> Any:
        return self.call(
            "option_quotes",
            lambda context: context.option_quote(symbols),
            timeout_seconds,
        )

    def calc_indexes(self, symbols: list[str], indexes: list[Any], timeout_seconds: int) -> Any:
        return self.call(
            "calc_indexes",
            lambda context: context.calc_indexes(symbols, indexes),
            timeout_seconds,
        )

    def quote_packages(self, timeout_seconds: int) -> Any:
        return self.call(
            "quote_packages",
            lambda context: context.quote_package_details(),
            timeout_seconds,
        )

    def health(self) -> dict[str, Any]:
        return {
            "runtime": "persistent_quote_context",
            "context_initialized": self._context is not None,
            "quote_subscription_count": len(self._quote_subscriptions),
            "depth_subscription_count": len(self._depth_subscriptions),
            "candle_subscription_count": len(self._candle_subscriptions),
            "active_symbol": self._active_symbol,
            "max_subscription_symbols": self._max_subscription_symbols,
            "background_subscription_requests": len(self._owners),
            "subscription_owner_count": len({item["owner"] for item in self._owners.values()}),
            "callback_events_dropped": self._dropped_events,
            "request_queue_timeouts": self._queue_timeouts,
            "event_queue_sizes": {owner: sink.qsize() for owner, sink in tuple(self._event_queues.items())},
            "event_queue_coalesced": {owner: getattr(sink, "coalesced", 0) for owner, sink in tuple(self._event_queues.items())},
            "subscription_restore_failures": dict(self._restore_failures),
            "market_data_only": True,
            "account_context_enabled": False,
            "trade_context_enabled": False,
        }


_RUNTIME = LongbridgeReadOnlyRuntime()


def longbridge_runtime() -> LongbridgeReadOnlyRuntime:
    return _RUNTIME
