from __future__ import annotations

import json
import asyncio

from kquant_crypto.dex_models import DexMarketStore, DexPairSnapshot, TokenSecurityInput
from kquant_crypto.dex_runtime import DexDiscoveryRuntime
from scripts.run_dex_discovery import collect
from kquant_crypto.providers.dexscreener import DexScreenerPublicAdapter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def sample_pair(address: str = "POOL1") -> dict:
    return {
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": address,
        "baseToken": {"address": "TOKEN1", "symbol": "MOON"},
        "quoteToken": {"address": "USDC", "symbol": "USDC"},
        "priceUsd": "0.12",
        "liquidity": {"usd": 100000},
        "volume": {"m5": 25000},
        "txns": {"m5": {"buys": 50, "sells": 20}},
    }


def test_dexscreener_adapter_normalizes_and_deduplicates_queries():
    def opener(_request, timeout):
        assert timeout == 10.0
        return FakeResponse({"pairs": [sample_pair(), sample_pair()]})

    adapter = DexScreenerPublicAdapter(opener=opener)
    pairs = adapter.discover(["MOON", "TOKEN1"], max_pairs=10)
    assert len(pairs) == 1
    assert pairs[0].asset_id == "solana:token1"


def test_dex_market_store_persists_and_deduplicates(settings):
    pair = DexPairSnapshot.from_dexscreener(sample_pair())
    store = DexMarketStore(settings.db_path)
    first = store.save_pair(pair)
    second = store.save_pair(pair)
    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    from kquant_crypto.db.migrations import connect

    with connect(settings.db_path) as conn:
        pool = conn.execute("SELECT pool_id,status FROM crypto_liquidity_pools WHERE pool_id=?", (pair.pool_id,)).fetchone()
        snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM crypto_dex_market_snapshots WHERE pool_id=?", (pair.pool_id,)).fetchone()["count"]
    assert pool["status"] == "active"
    assert snapshot_count == 1


def test_dex_discovery_runtime_persists_one_cycle(settings):
    pair = DexPairSnapshot.from_dexscreener(sample_pair("POOL-RUNTIME"))

    class FakeAdapter:
        def discover(self, queries, *, max_pairs):
            assert queries == ["MOON"]
            assert max_pairs == 100
            return [pair]

    runtime = DexDiscoveryRuntime(settings, queries=["MOON"], adapter=FakeAdapter())
    result = asyncio.run(runtime.run_once())
    assert result["status"] == "available"
    assert result["saved"] == 1
    assert runtime.status()["last_discovered"] == 1


def test_dex_discovery_zero_hours_means_one_shot(settings):
    pair = DexPairSnapshot.from_dexscreener(sample_pair("POOL-ONESHOT"))

    class FakeAdapter:
        def discover(self, _queries, *, max_pairs):
            assert max_pairs == 100
            return [pair]

    runtime = DexDiscoveryRuntime(settings, adapter=FakeAdapter())
    result = asyncio.run(collect(runtime, 0))
    assert result["runs"] == 1
    assert result["last"]["saved"] == 1


def test_dex_runtime_can_attach_fail_closed_security_checks(settings):
    pair = DexPairSnapshot.from_dexscreener(sample_pair("POOL-SECURITY"))

    class FakeAdapter:
        def discover(self, _queries, *, max_pairs):
            return [pair]

    class FakeSecurityAdapter:
        def inspect(self, chain_id, contract_address):
            assert chain_id == "solana"
            assert contract_address == "token1"
            return TokenSecurityInput(
                "solana:token1", "solana", "goplus", "live", honeypot=False,
                sell_enabled=True, buy_tax=0.01, sell_tax=0.01,
                blacklist=False, lp_locked=True,
            )

    runtime = DexDiscoveryRuntime(settings, adapter=FakeAdapter(), security_adapter=FakeSecurityAdapter())
    result = asyncio.run(runtime.run_once())
    assert result["security_checked"] == 1
    assert result["security_saved"] == 1
