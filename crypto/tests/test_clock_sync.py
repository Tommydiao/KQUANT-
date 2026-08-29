from __future__ import annotations

from kquant_crypto.clock_sync import _server_ms


def test_provider_clock_payload_parsers():
    assert _server_ms("binance", {"serverTime": 1000}) == 1000
    assert _server_ms("okx", {"data": [{"ts": "1000"}]}) == 1000
    assert _server_ms("kraken", {"result": {"unixtime": 1}}) == 1000
    assert _server_ms("coinbase", {}) is None
