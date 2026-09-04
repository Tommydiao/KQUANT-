from __future__ import annotations

from typing import Any, Mapping

from .factor_registry import FactorRegistry
from .signal_agent import SignalProposal, propose_signal


STRATEGY_VERSION = "crypto_spot_momentum_v2.1.0"
FACTOR_IDS = (
    "trend_ema_reclaim",
    "trend_ema_slope",
    "relative_strength_btc",
    "relative_strength_eth",
    "momentum_acceleration",
    "volume_acceleration",
    "cvd_bias",
    "volatility_compression",
    "liquidity_spread",
    "breakout_distance",
)
LIVE_ONLY_FACTOR_IDS = frozenset({"cvd_bias", "liquidity_spread"})


def _clip(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _linear(value: float | None, scale: float, points: float) -> float:
    if value is None or scale <= 0:
        return 0.0
    return _clip(float(value) / scale, -1.0, 1.0) * points


def score_spot_momentum_v21(
    registry: FactorRegistry,
    values: Mapping[str, float | None],
    *,
    include_live_only: bool = True,
) -> dict[str, Any]:
    """Score early strength with bounded, interpretable contributions.

    Inputs remain raw registered factors. Each contribution is capped so one
    extreme return or volume print cannot dominate the candidate score.
    """

    active_ids = tuple(
        factor_id for factor_id in FACTOR_IDS
        if include_live_only or factor_id not in LIVE_ONLY_FACTOR_IDS
    )
    unknown = registry.validate(list(active_ids))
    if unknown:
        raise ValueError(f"Unknown factor IDs: {', '.join(unknown)}")

    reclaim = values.get("trend_ema_reclaim")
    compression = values.get("volatility_compression")
    breakout = values.get("breakout_distance")
    spread_pass = values.get("liquidity_spread")

    volatility_points = 0.0
    if compression is not None:
        ratio = float(compression)
        if 0.55 <= ratio <= 0.95:
            volatility_points = 9.0
        elif 0.95 < ratio <= 1.25:
            volatility_points = 5.0
        elif ratio > 1.60:
            volatility_points = -8.0
        elif ratio < 0.40:
            volatility_points = -4.0

    breakout_points = 0.0
    if breakout is not None:
        distance = float(breakout)
        if -0.02 <= distance <= 0.03:
            breakout_points = 13.0
        elif 0.03 < distance <= 0.08:
            breakout_points = 5.0
        elif distance > 0.08:
            breakout_points = -12.0
        elif distance < -0.08:
            breakout_points = -8.0

    contributions = {
        "trend_ema_reclaim": 20.0 if reclaim is not None and float(reclaim) >= 1.0 else -10.0 if reclaim is not None else 0.0,
        "trend_ema_slope": _linear(values.get("trend_ema_slope"), 0.03, 13.0),
        "relative_strength_btc": _linear(values.get("relative_strength_btc"), 0.08, 9.0),
        "relative_strength_eth": _linear(values.get("relative_strength_eth"), 0.08, 7.0),
        "momentum_acceleration": _linear(values.get("momentum_acceleration"), 0.08, 11.0),
        "volume_acceleration": _linear(values.get("volume_acceleration"), 1.5, 8.0),
        "cvd_bias": _linear(values.get("cvd_bias"), 0.60, 8.0),
        "volatility_compression": volatility_points,
        "liquidity_spread": 6.0 if spread_pass is not None and float(spread_pass) >= 1.0 else -12.0 if spread_pass is not None else 0.0,
        "breakout_distance": breakout_points,
    }
    contributions = {key: round(value, 8) for key, value in contributions.items() if key in active_ids}
    missing = sorted(factor_id for factor_id in active_ids if values.get(factor_id) is None)
    score = round(_clip(sum(contributions.values()), 0.0, 100.0), 8)
    return {
        "score": score,
        "contributions": contributions,
        "missing_factor_ids": missing,
        "factor_version": registry.factor_version,
    }


def evaluate_spot_momentum_v21(
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
    scored = score_spot_momentum_v21(registry, setup_values)
    return propose_signal(
        registry,
        asset_id=asset_id,
        symbol=symbol,
        asset_type="cex_spot",
        strategy_version=STRATEGY_VERSION,
        factor_values=setup_values,
        weights={factor_id: 1.0 for factor_id in FACTOR_IDS},
        scored_result=scored,
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
        "factor_ids": list(FACTOR_IDS),
        "score_contract": "bounded_interpretable_contributions",
        "entry_timing": "next_tradable_bar",
        "same_bar_conflict": "stop_first",
        "status": "research_challenger",
        "execution_gate": "locked_oos_and_eval_required",
    }


__all__ = [
    "STRATEGY_VERSION",
    "FACTOR_IDS",
    "LIVE_ONLY_FACTOR_IDS",
    "score_spot_momentum_v21",
    "evaluate_spot_momentum_v21",
    "policy_manifest",
]
