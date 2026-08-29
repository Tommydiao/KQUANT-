from __future__ import annotations

import pytest

from kquant_crypto.dex_models import DexPairSnapshot, DexSecurityStore, TokenSecurityInput, assess_token_security


def test_dex_pair_uses_chain_and_contract_identity():
    pair = DexPairSnapshot.from_dexscreener({
        "chainId": "solana",
        "dexId": "raydium",
        "pairAddress": "POOL1",
        "baseToken": {"address": "TOKEN1", "symbol": "MOON"},
        "quoteToken": {"address": "USDC", "symbol": "USDC"},
        "priceUsd": "0.12",
        "liquidity": {"usd": 100000},
        "volume": {"m5": 25000},
        "txns": {"m5": {"buys": 50, "sells": 20}},
    })
    assert pair.asset_id == "solana:token1"
    assert pair.pool_id == "pool:solana:pool1"
    assert pair.buys_5m == 50


def test_dex_pair_rejects_missing_contract_identity():
    with pytest.raises(ValueError):
        DexPairSnapshot.from_dexscreener({"chainId": "base", "pairAddress": "POOL"})


def test_security_unknown_and_honeypot_fail_closed(settings):
    unknown = assess_token_security(TokenSecurityInput("solana:token", "solana", "goplus", "unavailable"))
    assert unknown.status == "unknown"
    blocked = assess_token_security(TokenSecurityInput(
        "solana:token", "solana", "goplus", "live", honeypot=True,
        sell_enabled=True, buy_tax=0.01, sell_tax=0.01, blacklist=False,
        lp_locked=True,
    ))
    assert blocked.status == "blocked"
    assert blocked.blockers[0]["code"] == "honeypot"
    store = DexSecurityStore(settings.db_path)
    saved = store.save_security(TokenSecurityInput(
        "solana:token", "solana", "goplus", "live", honeypot=True,
        sell_enabled=True, buy_tax=0.01, sell_tax=0.01, blacklist=False,
        lp_locked=True, holder_count=100, top10_concentration=0.45,
    ), blocked)
    assert saved["status"] == "blocked"
    assert store.latest_holder("solana:token")["holder_count"] == 100
    repeated = store.save_security(TokenSecurityInput(
        "solana:token", "solana", "goplus", "live", honeypot=True,
        sell_enabled=True, buy_tax=0.01, sell_tax=0.01, blacklist=False,
        lp_locked=True,
    ), blocked)
    assert repeated["deduplicated"] is True
