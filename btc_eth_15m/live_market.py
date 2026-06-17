from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BINANCE_FAPI_BASE = "https://fapi.binance.com"
TICKER_24HR_PATH = "/fapi/v1/ticker/24hr"
DEFAULT_LIVE_SYMBOL = "BTCUSDT"


def fetch_live_ticker(symbol: str = DEFAULT_LIVE_SYMBOL, *, timeout: float = 5.0) -> dict[str, Any]:
    """Read a public Binance USD-M Futures live ticker without credentials."""

    normalized = _normalize_symbol(symbol)
    started = time.monotonic()
    query = urlencode({"symbol": normalized})
    request = Request(
        f"{BINANCE_FAPI_BASE}{TICKER_24HR_PATH}?{query}",
        headers={"User-Agent": "kquant-live-market/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public Binance endpoint
        payload = json.loads(response.read().decode("utf-8"))
    latency_ms = int((time.monotonic() - started) * 1000)
    return _ticker_payload(payload, latency_ms=latency_ms)


def safe_live_ticker(symbol: str = DEFAULT_LIVE_SYMBOL, *, timeout: float = 5.0) -> dict[str, Any]:
    try:
        return fetch_live_ticker(symbol, timeout=timeout)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "symbol": _safe_symbol(symbol),
            "source": "Binance USD-M Futures public REST",
            "source_type": "public_live_market_data",
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            "price": None,
            "price_change_pct_24h": None,
            "high_price_24h": None,
            "low_price_24h": None,
            "volume_24h": None,
            "quote_volume_24h": None,
            "open_time": None,
            "close_time": None,
            "latency_ms": None,
            "error": str(exc),
        }


def _ticker_payload(payload: dict[str, Any], *, latency_ms: int) -> dict[str, Any]:
    symbol = _normalize_symbol(str(payload.get("symbol") or DEFAULT_LIVE_SYMBOL))
    return {
        "ok": True,
        "symbol": symbol,
        "source": "Binance USD-M Futures public REST",
        "source_type": "public_live_market_data",
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "price": _number(payload.get("lastPrice")),
        "price_change_pct_24h": _number(payload.get("priceChangePercent")),
        "high_price_24h": _number(payload.get("highPrice")),
        "low_price_24h": _number(payload.get("lowPrice")),
        "volume_24h": _number(payload.get("volume")),
        "quote_volume_24h": _number(payload.get("quoteVolume")),
        "open_time": _millis_iso(payload.get("openTime")),
        "close_time": _millis_iso(payload.get("closeTime")),
        "latency_ms": latency_ms,
        "error": None,
    }


def _normalize_symbol(symbol: str) -> str:
    normalized = _safe_symbol(symbol)
    if not normalized.endswith("USDT") or not normalized.replace("USDT", "").isalnum():
        raise ValueError(f"Unsupported live market symbol: {symbol}")
    return normalized


def _safe_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())[:24] or DEFAULT_LIVE_SYMBOL


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _millis_iso(value: Any) -> str | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()
