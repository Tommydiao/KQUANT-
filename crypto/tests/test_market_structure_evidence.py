from __future__ import annotations

from datetime import UTC, datetime

from kquant_crypto.market_structure_evidence import (
    BINANCE_SPOT_REST,
    fetch_binance_market_structure_evidence,
)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, params))
        assert url == f"{BINANCE_SPOT_REST}/api/v3/ticker/24hr"
        return _Response(self.payload)


def test_market_structure_maps_breadth_and_relative_strength_without_inference():
    client = _Client([
        {"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "1", "closeTime": 1724457600000},
        {"symbol": "ETHUSDT", "lastPrice": "5", "priceChangePercent": "2", "closeTime": 1724457600000},
        {"symbol": "SOLUSDT", "lastPrice": "1", "priceChangePercent": "-1", "closeTime": 1724457600000},
        {"symbol": "AAVEUSDT", "lastPrice": "10", "priceChangePercent": "3", "closeTime": 1724457600000},
        {"symbol": "ENAUSDT", "lastPrice": "2", "priceChangePercent": "-2", "closeTime": 1724457600000},
    ])
    result = fetch_binance_market_structure_evidence(
        asset_id="asset:btc",
        symbol="BTC",
        universe_symbols=("AAVEUSDT", "ENAUSDT"),
        client=client,
        available_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert result.status == "complete"
    assert result.snapshot.values == {"breadth": 0.5, "eth_btc": 0.05, "sol_btc": 0.01}
    assert result.snapshot.trust_status == "data_caution"
    assert "market_regime" in result.snapshot.missing_fields
    assert "btc_dominance" in result.snapshot.missing_fields
    assert client.calls[0][1]["symbols"] == '["BTCUSDT","ETHUSDT","SOLUSDT","AAVEUSDT","ENAUSDT"]'


def test_market_structure_provider_failure_is_fail_closed():
    class Broken:
        def get(self, *_args, **_kwargs):
            raise TimeoutError("offline")

    result = fetch_binance_market_structure_evidence(
        asset_id="asset:btc", symbol="BTC", universe_symbols=("AAVEUSDT",), client=Broken()
    )
    assert result.status == "provider_unavailable"
    assert result.snapshot.values == {}
    assert result.snapshot.trust_status == "data_caution"
    assert result.snapshot.source_status == "provider_unavailable"
