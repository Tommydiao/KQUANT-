from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable


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
        self._candle_subscriptions: set[tuple[str, str]] = set()

    def _build_context(self) -> Any:
        from longbridge.openapi import Config, QuoteContext  # type: ignore

        config = Config.from_apikey(
            os.environ.get("LONGBRIDGE_APP_KEY"),
            os.environ.get("LONGBRIDGE_APP_SECRET"),
            os.environ.get("LONGBRIDGE_ACCESS_TOKEN"),
            enable_print_quote_packages=False,
        )
        return QuoteContext(config)

    def context(self) -> Any:
        with self._state_lock:
            if self._context is None:
                self._context = self._build_context()
            return self._context

    def _reset(self) -> None:
        with self._state_lock:
            context = self._context
            self._context = None
            self._quote_subscriptions.clear()
            self._candle_subscriptions.clear()
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
            future.cancel()
            self._reset()
            raise TimeoutError(f"Longbridge {label} timed out after {timeout_seconds}s") from exc
        except Exception:
            self._reset()
            raise

    def quote(self, symbol: str, timeout_seconds: int) -> Any:
        def operation(context: Any) -> Any:
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
            subscription_key = (symbol, period_key)
            initial_rows: Any = []
            if subscription_key not in self._candle_subscriptions:
                try:
                    initial_rows = context.subscribe_candlesticks(symbol, period)
                    self._candle_subscriptions.add(subscription_key)
                except TypeError:
                    # Older SDK builds require the optional trade-session arg.
                    try:
                        initial_rows = context.subscribe_candlesticks(symbol, period, None)
                        self._candle_subscriptions.add(subscription_key)
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

    def health(self) -> dict[str, Any]:
        return {
            "runtime": "persistent_quote_context",
            "context_initialized": self._context is not None,
            "quote_subscription_count": len(self._quote_subscriptions),
            "candle_subscription_count": len(self._candle_subscriptions),
            "market_data_only": True,
            "account_context_enabled": False,
            "trade_context_enabled": False,
        }


_RUNTIME = LongbridgeReadOnlyRuntime()


def longbridge_runtime() -> LongbridgeReadOnlyRuntime:
    return _RUNTIME
