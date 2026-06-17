from __future__ import annotations

import json

import pytest

from btc_eth_15m import live_market


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_live_ticker_parses_public_binance_payload(monkeypatch):
    def fake_urlopen(request, timeout):
        assert "symbol=BTCUSDT" in request.full_url
        assert timeout == 2.0
        return FakeResponse(
            {
                "symbol": "BTCUSDT",
                "lastPrice": "68321.50",
                "priceChangePercent": "1.25",
                "highPrice": "69000.00",
                "lowPrice": "67000.00",
                "volume": "123.45",
                "quoteVolume": "8420000.00",
                "openTime": 1717977600000,
                "closeTime": 1718063999999,
            }
        )

    monkeypatch.setattr(live_market, "urlopen", fake_urlopen)

    payload = live_market.fetch_live_ticker("btcusdt", timeout=2.0)

    assert payload["ok"] is True
    assert payload["symbol"] == "BTCUSDT"
    assert payload["source_type"] == "public_live_market_data"
    assert payload["price"] == 68321.5
    assert payload["price_change_pct_24h"] == 1.25
    assert payload["open_time"].startswith("2024-06-10T")
    assert payload["error"] is None


def test_safe_live_ticker_returns_unavailable_payload_on_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise OSError("network unavailable")

    monkeypatch.setattr(live_market, "urlopen", fake_urlopen)

    payload = live_market.safe_live_ticker("BTCUSDT", timeout=0.1)

    assert payload["ok"] is False
    assert payload["symbol"] == "BTCUSDT"
    assert payload["price"] is None
    assert "network unavailable" in payload["error"]


def test_fetch_live_ticker_rejects_non_usdt_symbol():
    with pytest.raises(ValueError, match="Unsupported live market symbol"):
        live_market.fetch_live_ticker("AAPL")
