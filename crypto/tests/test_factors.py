from __future__ import annotations

import pytest

from kquant_crypto.factor_registry import FACTOR_VERSION, MEME_FACTOR_VERSION, FactorRegistry, MemeFactorRegistry, score_registered_factors


def test_factor_registry_is_versioned_and_low_redundancy(settings):
    registry = FactorRegistry(settings.db_path)
    assert FACTOR_VERSION == "crypto_factor_v1.0.1"
    assert 8 <= len(registry.ids) <= 12
    assert registry.validate(["trend_ema_reclaim"]) == []
    assert registry.validate(["llm_magic_factor"]) == ["llm_magic_factor"]


def test_unknown_factor_cannot_create_snapshot(settings):
    registry = FactorRegistry(settings.db_path)
    with pytest.raises(ValueError):
        registry.snapshot(asset_id="asset:btc", strategy_version="v1", as_of_time="2026-08-22T00:00:00Z", values={"not_registered": 1}, contributions={})


def test_factor_score_exposes_contributions_and_missing_values(settings):
    registry = FactorRegistry(settings.db_path)
    result = score_registered_factors(registry, {"trend_ema_reclaim": 1.0, "volume_acceleration": None}, {"trend_ema_reclaim": 0.5, "volume_acceleration": 0.2})
    assert result["score"] == 0.5
    assert result["missing_factor_ids"] == ["volume_acceleration"]


def test_factor_snapshot_can_be_retrieved_by_id(settings):
    registry = FactorRegistry(settings.db_path)
    snapshot = registry.snapshot(
        asset_id="asset:btc",
        strategy_version="crypto_early_v1.0.0",
        as_of_time="2026-08-22T00:00:00+00:00",
        values={"trend_ema_reclaim": 1.0},
        contributions={"trend_ema_reclaim": 0.5},
    )
    loaded = registry.get_snapshot(snapshot["factor_snapshot_id"])
    assert loaded is not None
    assert loaded["content_hash"] == snapshot["content_hash"]
    assert loaded["values"] == {"trend_ema_reclaim": 1.0}


def test_meme_factor_namespace_is_versioned_and_separate(settings):
    registry = MemeFactorRegistry(settings.db_path)
    assert registry.factor_version == MEME_FACTOR_VERSION == "crypto_meme_factor_v1.0.0"
    assert registry.ids == {
        "meme_volume_acceleration",
        "meme_buy_pressure",
        "meme_liquidity_growth",
        "meme_price_momentum",
        "meme_holder_growth",
        "meme_security_pass",
    }
    snapshot = registry.snapshot(
        asset_id="solana:token",
        strategy_version="crypto_meme_factor_v1.0.0",
        as_of_time="2026-08-22T00:00:00+00:00",
        values={"meme_security_pass": 1.0},
        contributions={"meme_security_pass": 10.0},
    )
    assert snapshot["factor_version"] == MEME_FACTOR_VERSION
