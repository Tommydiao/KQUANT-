from __future__ import annotations

from datetime import UTC, datetime

from kquant_crypto.providers.defillama import (
    DEFILLAMA_API,
    DEFILLAMA_STABLECOINS_API,
    DefiLlamaPublicAdapter,
)


def test_defillama_maps_latest_stablecoin_point_with_source_time():
    def request(url: str):
        assert url == f"{DEFILLAMA_STABLECOINS_API}/stablecoincharts/all"
        return [
            {"date": "1704067200", "totalCirculatingUSD": {"peggedUSD": 100}},
            {"date": "1704153600", "totalCirculatingUSD": {"peggedUSD": 125}},
        ]

    result = DefiLlamaPublicAdapter(requester=request).fetch(
        asset_id="asset:btc",
        symbol="BTC",
        category="onchain",
        available_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert result.status == "complete"
    assert result.snapshot.values == {"stablecoin_supply": 125.0}
    assert result.snapshot.source_time == "2024-01-02T00:00:00+00:00"
    assert "mvrv" in result.snapshot.missing_fields


def test_defillama_maps_protocol_tvl_only():
    def request(url: str):
        assert url == f"{DEFILLAMA_API}/tvl/aave"
        return 123456.0

    result = DefiLlamaPublicAdapter(requester=request).fetch(
        asset_id="asset:aave",
        symbol="AAVE",
        category="protocol_metric",
    )
    assert result.status == "complete"
    assert result.snapshot.values == {"tvl_usd": 123456.0}
    assert result.snapshot.missing_fields == ("active_users", "fees_usd", "token_unlock_usd")
    assert result.snapshot.trust_status == "data_caution"


def test_defillama_disabled_or_unsupported_is_fail_closed():
    adapter = DefiLlamaPublicAdapter(requester=lambda _: {})
    disabled = adapter.fetch(asset_id="asset:btc", symbol="BTC", category="onchain", enabled=False)
    unsupported = adapter.fetch(asset_id="asset:pump", symbol="PUMP", category="onchain")
    assert disabled.status == "provider_disabled"
    assert unsupported.status == "unsupported_asset"
    assert disabled.snapshot.values == {}
    assert unsupported.snapshot.values == {}
