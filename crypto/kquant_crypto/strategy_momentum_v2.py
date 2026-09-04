from __future__ import annotations

from typing import Any

from .factor_registry import FactorRegistry
from .signal_agent import SignalProposal, propose_signal


STRATEGY_VERSION = "crypto_spot_momentum_v2.0.0"

# Frozen research weights. They are intentionally versioned here so live and
# historical replay import the same policy rather than copying thresholds.
SETUP_WEIGHTS: dict[str, float] = {
    "trend_ema_reclaim": 28.0,
    "trend_ema_slope": 420.0,
    "relative_strength_btc": 150.0,
    "relative_strength_eth": 100.0,
    "momentum_acceleration": 120.0,
    "volume_acceleration": 18.0,
    "cvd_bias": 8.0,
    "volatility_compression": 4.0,
    "liquidity_spread": 8.0,
    "breakout_distance": -18.0,
}


def evaluate_spot_momentum(
    registry: FactorRegistry,
    *,
    asset_id: str,
    symbol: str,
    setup_values: dict[str, float | None],
    trigger_score: float | None,
    five_period_return: float | None,
    ema20_deviation: float | None,
    data_quality_status: str,
    liquidity_status: str,
    market_regime: str,
    as_of_time: str,
    security_status: str = "not_required_cex",
) -> SignalProposal:
    """Pure v2 policy shared by realtime analysis and historical replay."""

    return propose_signal(
        registry,
        asset_id=asset_id,
        symbol=symbol,
        asset_type="cex_spot",
        strategy_version=STRATEGY_VERSION,
        factor_values=setup_values,
        weights=SETUP_WEIGHTS,
        trigger_score=trigger_score,
        five_day_return=five_period_return,
        ema20_deviation=ema20_deviation,
        data_quality_status=data_quality_status,
        security_status=security_status,
        liquidity_status=liquidity_status,
        market_regime=market_regime,
        as_of_time=as_of_time,
    )


def policy_manifest() -> dict[str, Any]:
    return {
        "strategy_version": STRATEGY_VERSION,
        "market_type": "spot",
        "direction": "long",
        "setup_interval": "1H",
        "trigger_interval": "5m",
        "weights": dict(SETUP_WEIGHTS),
        "entry_timing": "next_tradable_bar",
        "same_bar_conflict": "stop_first",
        "execution_gate": "validation_and_eval_required",
    }
