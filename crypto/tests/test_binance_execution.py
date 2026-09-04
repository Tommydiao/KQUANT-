from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest

from kquant_crypto.binance_execution import (
    BinanceCredentials,
    BinanceExecutionClient,
    BinanceUnknownExecutionState,
    sign_query,
)


def client(handler):
    return BinanceExecutionClient(
        BinanceCredentials("api-key", "api-secret"),
        spot_base_url="https://spot.test",
        futures_base_url="https://futures.test",
        clock_ms=lambda: 1_700_000_000_000,
        transport=httpx.MockTransport(handler),
    )


def test_signed_query_is_deterministic():
    value = sign_query({"symbol": "BTCUSDT", "timestamp": 123}, "secret")
    unsigned = "symbol=BTCUSDT&timestamp=123"
    expected = hmac.new(b"secret", unsigned.encode(), hashlib.sha256).hexdigest()
    assert value == f"{unsigned}&signature={expected}"


def test_account_request_uses_api_key_but_never_sends_secret():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"balances": []})

    value = client(handler)
    try:
        assert value.account("spot") == {"balances": []}
    finally:
        value.close()
    assert captured["headers"]["x-mbx-apikey"] == "api-key"
    assert "api-secret" not in captured["url"]
    assert "api-secret" not in str(captured["headers"])


def test_write_5xx_has_unknown_state_and_is_not_retried():
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"msg": "try later"})

    value = client(handler)
    try:
        with pytest.raises(BinanceUnknownExecutionState):
            value.place_order("spot", {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT"})
    finally:
        value.close()
    assert calls == 1
