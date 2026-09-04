from datetime import UTC, datetime

import pytest

from kquant_crypto.public_evidence import fetch_binance_derivatives_evidence, fetch_okx_derivatives_evidence


class _Response:
    def __init__(self, body, *, error: Exception | None = None):
        self.body = body
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.body


class _Client:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, *, params):
        name = url.rsplit("/", 1)[-1]
        self.calls.append((name, params))
        response = self.responses[name]
        if isinstance(response, Exception):
            raise response
        return _Response(response)


def test_binance_public_derivatives_snapshot_normalizes_all_available_endpoints():
    client = _Client({
        "premiumIndex": {"markPrice": "101", "indexPrice": "100", "lastFundingRate": "0.0001", "time": 1776945600000},
        "openInterest": {"openInterest": "12345", "time": 1776945600000},
        "fundingRate": [{"fundingRate": "0.0002", "fundingTime": 1776945600000}],
        "depth": {"E": 1776945600000, "bids": [["100", "2"]], "asks": [["101", "3"]]},
        "aggTrades": [
            {"p": "100", "q": "2", "m": False, "T": 1776945600000},
            {"p": "101", "q": "1", "m": True, "T": 1776945600000},
        ],
        "allForceOrders": [{"price": "100", "origQty": "3", "time": 1776945600000}],
    })
    result = fetch_binance_derivatives_evidence(
        asset_id="asset:BTC",
        symbol="BTC",
        client=client,
        available_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert result.status == "complete"
    assert result.snapshot.source == "binance_public_derivatives"
    assert result.snapshot.values["funding_rate"] == 0.0002
    assert result.snapshot.values["open_interest"] == 12345.0
    assert result.snapshot.values["mark_price"] == 101.0
    assert result.snapshot.values["index_price"] == 100.0
    assert result.snapshot.values["spread_bps"] > 0
    assert result.snapshot.values["depth_usd"] == 503.0
    assert result.snapshot.values["active_buy_volume"] == 200.0
    assert result.snapshot.values["active_sell_volume"] == 101.0
    assert result.snapshot.values["cvd"] == 99.0
    assert result.snapshot.values["liquidations_usd"] == 300.0
    assert len(client.calls) == 6


def test_binance_endpoint_failure_is_partial_and_missing_values_are_not_filled():
    client = _Client({
        "premiumIndex": {"markPrice": "101", "indexPrice": "100", "time": 1776945600000},
        "openInterest": TimeoutError("timeout"),
        "fundingRate": [],
        "depth": {"E": 1776945600000, "bids": [], "asks": []},
        "aggTrades": [],
        "allForceOrders": [],
    })
    result = fetch_binance_derivatives_evidence(
        asset_id="asset:ETH",
        symbol="ETHUSDT",
        client=client,
        available_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert result.status == "partial"
    assert result.snapshot.trust_status == "data_caution"
    assert "open_interest" in result.snapshot.missing_fields
    assert "open_interest" not in result.snapshot.values
    assert result.error_types["open_interest"] == "TimeoutError"


def test_public_evidence_rejects_missing_identity():
    with pytest.raises(ValueError):
        fetch_binance_derivatives_evidence(asset_id="", symbol="BTC", client=_Client({}))


def test_provider_clock_ahead_does_not_break_available_at_ordering():
    client = _Client({
        "premiumIndex": {"markPrice": "101", "indexPrice": "100", "time": 4102444800000},
        "openInterest": {"openInterest": "12345", "time": 4102444800000},
        "fundingRate": [{"fundingRate": "0.0002", "fundingTime": 4102444800000}],
        "depth": {"E": 4102444800000, "bids": [["100", "2"]], "asks": [["101", "3"]]},
    })
    result = fetch_binance_derivatives_evidence(
        asset_id="asset:BTC",
        symbol="BTC",
        client=client,
        available_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )
    assert result.snapshot.source_time <= result.snapshot.available_at


class _OkxClient:
    def get(self, url, *, params):
        path = url.split(".com", 1)[-1]
        if path == "/api/v5/public/mark-price":
            return _Response({"code": "0", "data": [{"markPx": "100", "ts": "1776945600000"}]})
        if path == "/api/v5/market/index-tickers":
            return _Response({"code": "0", "data": [{"idxPx": "99", "ts": "1776945600000"}]})
        if path == "/api/v5/public/open-interest":
            return _Response({"code": "0", "data": [{"oi": "123", "ts": "1776945600000"}]})
        if path == "/api/v5/public/funding-rate":
            return _Response({"code": "0", "data": [{"fundingRate": "0.0001", "fundingTime": "1776945600000"}]})
        if path == "/api/v5/market/books":
            return _Response({"code": "0", "data": [{"bids": [["99", "10", "0", "1"]], "asks": [["101", "12", "0", "1"]], "ts": "1776945600000"}]})
        if path == "/api/v5/market/trades":
            return _Response({"code": "0", "data": [{"px": "100", "sz": "2", "side": "buy", "ts": "1776945600000"}, {"px": "101", "sz": "1", "side": "sell", "ts": "1776945600000"}]})
        raise AssertionError(path)


def test_okx_public_evidence_uses_public_endpoints_and_source_lineage():
    result = fetch_okx_derivatives_evidence(asset_id="asset:BTC", symbol="BTC", client=_OkxClient())
    assert result.status == "complete"
    assert result.snapshot.source == "okx_public_derivatives"
    assert result.snapshot.source_version == "crypto_public_evidence_v1.2.0"
    assert result.snapshot.values["open_interest"] == 123
    assert result.snapshot.values["funding_rate"] == 0.0001
    assert result.snapshot.values["mark_price"] == 100.0
    assert result.snapshot.values["index_price"] == 99.0
    assert result.snapshot.values["basis"] == pytest.approx(100 / 99 - 1)
    assert result.snapshot.values["spread_bps"] > 0
    assert result.snapshot.values["active_buy_volume"] == 200
    assert result.snapshot.values["active_sell_volume"] == 101
    assert result.snapshot.values["cvd"] == 99
    assert result.snapshot.content_hash


def test_okx_public_evidence_provider_error_is_fail_closed():
    class BrokenClient:
        def get(self, url, *, params):
            raise TimeoutError("offline")

    result = fetch_okx_derivatives_evidence(asset_id="asset:BTC", symbol="BTC", client=BrokenClient())
    assert result.status == "provider_unavailable"
    assert result.snapshot.trust_status == "data_caution"
    assert result.snapshot.values == {}
