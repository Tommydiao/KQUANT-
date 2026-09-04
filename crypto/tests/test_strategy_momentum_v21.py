from __future__ import annotations

from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.strategy_momentum_v21 import (
    STRATEGY_VERSION,
    evaluate_spot_momentum_v21,
    policy_manifest,
    score_spot_momentum_v21,
)


def _values(**updates):
    values = {
        "trend_ema_reclaim": 1.0,
        "trend_ema_slope": 0.025,
        "relative_strength_btc": 0.06,
        "relative_strength_eth": 0.05,
        "momentum_acceleration": 0.05,
        "volume_acceleration": 1.0,
        "cvd_bias": 0.40,
        "volatility_compression": 0.85,
        "liquidity_spread": 1.0,
        "breakout_distance": 0.01,
    }
    values.update(updates)
    return values


def test_v21_score_is_bounded_and_penalizes_late_expansion(settings):
    registry = FactorRegistry(settings.db_path)
    early = score_spot_momentum_v21(registry, _values())
    late = score_spot_momentum_v21(
        registry,
        _values(breakout_distance=0.14, volatility_compression=1.9),
    )

    assert 0 <= late["score"] < early["score"] <= 100
    assert late["contributions"]["breakout_distance"] < 0
    assert late["contributions"]["volatility_compression"] < 0


def test_v21_policy_is_deterministic_and_marks_late_chase(settings):
    registry = FactorRegistry(settings.db_path)
    args = dict(
        registry=registry,
        asset_id="asset:arb",
        symbol="ARBUSDT",
        setup_values=_values(),
        trigger_score=80.0,
        five_period_return=0.18,
        ema20_deviation=0.12,
        data_quality_status="live",
        liquidity_status="pass",
        market_regime="RISK_ON",
        as_of_time="2026-09-04T00:00:00+00:00",
    )
    first = evaluate_spot_momentum_v21(**args)
    second = evaluate_spot_momentum_v21(**args)

    assert first.strategy_version == STRATEGY_VERSION
    assert first.stage == "LATE_WAIT_PULLBACK"
    assert first.material_state_hash == second.material_state_hash
    assert policy_manifest()["status"] == "research_challenger"


def test_v21_historical_score_excludes_live_only_missing_factors(settings):
    result = score_spot_momentum_v21(
        FactorRegistry(settings.db_path),
        _values(cvd_bias=None, liquidity_spread=None),
        include_live_only=False,
    )
    assert "cvd_bias" not in result["missing_factor_ids"]
    assert "liquidity_spread" not in result["contributions"]
