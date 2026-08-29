from datetime import UTC, datetime

import pytest

from kquant_crypto.providers.coinglass import (
    COINGLASS_EVIDENCE_VERSION,
    CoinGlassPublicAdapter,
)


class _FakeCoinGlass:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, path, *, params, headers):
        self.calls.append((path, dict(params), dict(headers)))
        return self.payload


class _RoutingFakeCoinGlass:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def __call__(self, path, *, params, headers):
        self.calls.append((path, dict(params), dict(headers)))
        if path in self.payloads:
            return self.payloads[path]
        return self.payloads["default"]


def test_coinglass_derivatives_maps_explicit_market_fields_without_secret_leak():
    fake = _FakeCoinGlass({
        "code": "0",
        "data": [{
            "symbol": "BTC",
            "timestamp": 1776945600000,
            "open_interest_usd": 123456.0,
            "funding_rate": 0.0002,
            "basis": 0.001,
            "taker_buy_volume_usd_5m": 200.0,
            "taker_sell_volume_usd_5m": 101.0,
            "cvd_usd": 99.0,
            "long_liquidation_usd_24h": 12.0,
            "short_liquidation_usd_24h": 8.0,
        }],
    })
    result = CoinGlassPublicAdapter(api_key="secret-value", requester=fake).fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="exchange_derivatives",
        available_at=datetime(2026, 8, 24, tzinfo=UTC),
    )

    assert result.status == "complete"
    assert result.snapshot.source == "coinglass_optional"
    assert result.snapshot.source_version == COINGLASS_EVIDENCE_VERSION
    assert result.snapshot.values["open_interest"] == 123456.0
    assert result.snapshot.values["liquidations_usd"] == 20.0
    assert result.snapshot.trust_status == "data_caution"
    assert fake.calls[0][0] == "/api/futures/pairs-markets"
    assert fake.calls[0][2]["CG-API-KEY"] == "secret-value"
    assert "secret-value" not in str(result.to_mapping())


def test_coinglass_etf_history_maps_explicit_windows_and_net_assets():
    fake = _RoutingFakeCoinGlass({
        "/api/etf/bitcoin/flow-history": {
            "code": 0,
            "data": [
                {"timestamp": 1776945600000, "flow_usd": "100"},
                {"timestamp": 1776427200000, "flow_usd": "-25"},
                {"timestamp": 1774267200000, "flow_usd": "50"},
            ],
        },
        "/api/etf/bitcoin/net-assets/history": {
            "code": 0,
            "data": [{"timestamp": 1776945600000, "net_assets_usd": "1000"}],
        },
        "/api/etf/bitcoin/premium-discount/history": {
            "code": 0,
            "data": [{"timestamp": 1776945600000, "list": [{"ticker": "IBIT", "premium_discount_details": "0.2"}]}],
        },
    })
    result = CoinGlassPublicAdapter(api_key="key", requester=fake).fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="etf_flow",
    )

    assert result.status == "complete"
    assert result.snapshot.values == {
        "flow_usd": 100.0,
        "flow_7d_usd": 75.0,
        "flow_30d_usd": 75.0,
        "aum_usd": 1000.0,
        "premium_discount": 0.2,
    }
    assert len(fake.calls) == 3


def test_coinglass_etf_missing_windows_stay_missing():
    fake = _FakeCoinGlass({
        "code": 0,
        "data": [{"flow_usd": "100"}],
    })
    result = CoinGlassPublicAdapter(api_key="key", requester=fake).fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="etf_flow",
    )

    assert result.status == "complete"
    assert result.snapshot.values == {"flow_usd": 100.0}
    assert "flow_7d_usd" in result.snapshot.missing_fields
    assert "flow_30d_usd" in result.snapshot.missing_fields
    assert fake.calls[0][0] == "/api/etf/bitcoin/flow-history"


def test_coinglass_without_key_and_unsupported_category_fail_closed():
    missing = CoinGlassPublicAdapter().fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="exchange_derivatives",
    )
    assert missing.status == "provider_unavailable"
    assert missing.snapshot.trust_status == "data_caution"
    assert missing.snapshot.values == {}

    unsupported = CoinGlassPublicAdapter(api_key="key").fetch(
        asset_id="asset:aave",
        symbol="AAVE",
        category="protocol_metric",
    )
    assert unsupported.status == "unsupported_category"
    assert unsupported.snapshot.values == {}


def test_coinglass_rejects_invalid_identity():
    with pytest.raises(ValueError):
        CoinGlassPublicAdapter(api_key="key").fetch(asset_id="", symbol="BTC", category="etf_flow")


def test_coinglass_onchain_uses_documented_btc_endpoints_and_keeps_missing_metrics_na():
    payloads = {
        "/api/index/stableCoin-marketCap-history": {
            "code": 0,
            "data": [{
                "data_list": [120.0, 125.5],
                "time_list": [1776859200, 1776945600],
            }],
        },
        "default": {
        "code": 0,
        "data": [
            {
                "exchange_name": "Binance",
                "balance_change_1d": 12.5,
                "net_unpnl": 0.21,
                "sth_sopr": 1.04,
                "active_address_count": 1234,
            },
        ],
        },
    }

    fake = _RoutingFakeCoinGlass(payloads)
    result = CoinGlassPublicAdapter(api_key="key", requester=fake).fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="onchain",
    )

    assert result.status == "complete"
    assert result.snapshot.values["exchange_netflow"] == 12.5
    assert result.snapshot.values["stablecoin_supply"] == 125.5
    assert result.snapshot.source_time == "2026-04-23T12:00:00+00:00"
    assert result.snapshot.values["nupl"] == 0.21
    assert result.snapshot.values["sopr"] == 1.04
    assert result.snapshot.values["active_addresses"] == 1234.0
    assert "mvrv" in result.snapshot.missing_fields
    assert "realized_cap_usd" in result.snapshot.missing_fields
    assert {call[0] for call in fake.calls} == {
        "/api/exchange/balance/list",
        "/api/index/stableCoin-marketCap-history",
        "/api/index/bitcoin-net-unrealized-profit-loss",
        "/api/index/bitcoin-sth-sopr",
        "/api/index/bitcoin-active-addresses",
    }


def test_coinglass_whale_aggregates_recent_transfers_without_inventing_holder_concentration():
    fake = _FakeCoinGlass({
        "code": "0",
        "data": [
            {"amount_usd": "10000000", "transfer_type": 1, "block_timestamp": 1776945600},
            {"amount_usd": "2500000", "transfer_type": 2, "block_timestamp": 1776945601},
        ],
    })
    result = CoinGlassPublicAdapter(api_key="key", requester=fake).fetch(
        asset_id="asset:sol",
        symbol="SOL",
        category="whale",
    )

    assert result.status == "complete"
    assert result.snapshot.values["large_transfer_count"] == 2.0
    assert result.snapshot.values["large_transfer_volume_usd"] == 12_500_000.0
    assert result.snapshot.values["exchange_inflow_usd"] == 10_000_000.0
    assert result.snapshot.values["exchange_outflow_usd"] == 2_500_000.0
    assert "top_holder_concentration" in result.snapshot.missing_fields
    assert fake.calls[0][0] == "/api/chain/v2/whale-transfer"
    assert "start_time" in fake.calls[0][1]
    assert "end_time" in fake.calls[0][1]
