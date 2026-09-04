from __future__ import annotations

from kquant_crypto.factor_registry import FactorRegistry
from kquant_crypto.strategy_momentum_v2 import STRATEGY_VERSION, evaluate_spot_momentum, policy_manifest


def test_v2_policy_is_versioned_and_shared():
    manifest = policy_manifest()
    assert manifest["strategy_version"] == STRATEGY_VERSION
    assert manifest["setup_interval"] == "1H"
    assert manifest["trigger_interval"] == "5m"


def test_v2_policy_returns_observation_for_unconfirmed_setup(settings):
    proposal = evaluate_spot_momentum(
        FactorRegistry(settings.db_path),
        asset_id="asset:BTC", symbol="BTCUSDT",
        setup_values={"trend_ema_reclaim": 0.5},
        trigger_score=20.0, five_period_return=0.01, ema20_deviation=0.01,
        data_quality_status="live", liquidity_status="available",
        market_regime="RISK_ON", as_of_time="2026-09-02T00:00:00+00:00",
    )
    assert proposal.strategy_version == STRATEGY_VERSION
    assert proposal.stage in {"MONITORING", "EARLY_WATCH"}
