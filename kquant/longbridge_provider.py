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
        return self.call("quote", lambda context: context.quote([symbol]), timeout_seconds)

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

    def health(self) -> dict[str, Any]:
        return {
            "runtime": "persistent_quote_context",
            "context_initialized": self._context is not None,
            "market_data_only": True,
            "account_context_enabled": False,
            "trade_context_enabled": False,
        }


_RUNTIME = LongbridgeReadOnlyRuntime()


def longbridge_runtime() -> LongbridgeReadOnlyRuntime:
    return _RUNTIME
