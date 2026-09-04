from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .evaluation_models import iso_now, stable_hash
from .factor_registry import FactorRegistry, score_registered_factors


class SetupStage(StrEnum):
    MONITORING = "MONITORING"
    EARLY_WATCH = "EARLY_WATCH"
    ARMED = "ARMED"
    BUY_REVIEW = "BUY_REVIEW"
    LATE_WAIT_PULLBACK = "LATE_WAIT_PULLBACK"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class SignalProposal:
    asset_id: str
    symbol: str
    asset_type: str
    strategy_version: str
    stage: str
    setup_score: float
    trigger_score: float | None
    factor_version: str
    factor_values: dict[str, float | None]
    factor_contributions: dict[str, float]
    missing_factor_ids: tuple[str, ...]
    supporting_factors: tuple[dict[str, Any], ...]
    opposing_factors: tuple[dict[str, Any], ...]
    data_quality_status: str
    security_status: str
    liquidity_status: str
    market_regime: str
    as_of_time: str
    material_state_hash: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "strategy_version": self.strategy_version,
            "stage": self.stage,
            "setup_score": self.setup_score,
            "trigger_score": self.trigger_score,
            "factor_version": self.factor_version,
            "factor_values": self.factor_values,
            "factor_contributions": self.factor_contributions,
            "missing_factor_ids": list(self.missing_factor_ids),
            "supporting_factors": list(self.supporting_factors),
            "opposing_factors": list(self.opposing_factors),
            "data_quality_status": self.data_quality_status,
            "security_status": self.security_status,
            "liquidity_status": self.liquidity_status,
            "market_regime": self.market_regime,
            "as_of_time": self.as_of_time,
            "material_state_hash": self.material_state_hash,
        }


def propose_signal(
    registry: FactorRegistry,
    *,
    asset_id: str,
    symbol: str,
    asset_type: str,
    strategy_version: str,
    factor_values: dict[str, float | None],
    weights: dict[str, float],
    trigger_score: float | None = None,
    five_day_return: float | None = None,
    ema20_deviation: float | None = None,
    invalidated: bool = False,
    data_quality_status: str = "unknown",
    security_status: str = "unknown",
    liquidity_status: str = "unknown",
    market_regime: str = "unknown",
    as_of_time: str | None = None,
    scored_result: Mapping[str, Any] | None = None,
) -> SignalProposal:
    """Create a deterministic candidate stage from registered factors only.

    This function does not authorize an alert or a Paper observation.  It is
    intentionally unaware of notification and persistence; EVAL remains the
    final reviewer.
    """

    unknown = registry.validate(list(factor_values) + list(weights))
    if unknown:
        raise ValueError(f"Unknown factor IDs: {', '.join(unknown)}")

    scored = dict(scored_result) if scored_result is not None else score_registered_factors(registry, factor_values, weights)
    unknown_contributions = registry.validate(list(scored.get("contributions") or {}))
    if unknown_contributions:
        raise ValueError(f"Unknown contribution factor IDs: {', '.join(unknown_contributions)}")
    scored.setdefault("factor_version", registry.factor_version)
    scored.setdefault("missing_factor_ids", sorted(key for key in weights if factor_values.get(key) is None))
    setup_score = float(scored["score"])
    stage = SetupStage.MONITORING.value
    if setup_score >= 60:
        stage = SetupStage.EARLY_WATCH.value
    if setup_score >= 72:
        stage = SetupStage.ARMED.value
    if stage == SetupStage.ARMED.value and trigger_score is not None and trigger_score >= 70:
        stage = SetupStage.BUY_REVIEW.value
    if (five_day_return is not None and five_day_return > 0.15) or (ema20_deviation is not None and ema20_deviation > 0.10):
        if stage in {SetupStage.ARMED.value, SetupStage.BUY_REVIEW.value}:
            stage = SetupStage.LATE_WAIT_PULLBACK.value
    if invalidated:
        stage = SetupStage.INVALIDATED.value

    contributions = dict(scored["contributions"])
    supporting = tuple(
        {"factor_id": factor_id, "value": factor_values.get(factor_id), "contribution": contribution}
        for factor_id, contribution in sorted(contributions.items(), key=lambda item: item[1], reverse=True)
        if contribution > 0
    )
    opposing = tuple(
        {"factor_id": factor_id, "value": factor_values.get(factor_id), "contribution": contribution}
        for factor_id, contribution in sorted(contributions.items(), key=lambda item: item[1])
        if contribution < 0
    )
    timestamp = as_of_time or iso_now()
    material_state_hash = stable_hash({
        "asset_id": asset_id,
        "strategy_version": strategy_version,
        "stage": stage,
        "setup_score": setup_score,
        "trigger_score": trigger_score,
        "factor_version": scored["factor_version"],
        "factor_values": factor_values,
        "data_quality_status": data_quality_status,
        "security_status": security_status,
        "liquidity_status": liquidity_status,
        "market_regime": market_regime,
        "as_of_time": timestamp,
    })
    return SignalProposal(
        asset_id=asset_id,
        symbol=symbol,
        asset_type=asset_type,
        strategy_version=strategy_version,
        stage=stage,
        setup_score=setup_score,
        trigger_score=trigger_score,
        factor_version=scored["factor_version"],
        factor_values=dict(factor_values),
        factor_contributions=dict(contributions),
        missing_factor_ids=tuple(scored["missing_factor_ids"]),
        supporting_factors=supporting,
        opposing_factors=opposing,
        data_quality_status=data_quality_status,
        security_status=security_status,
        liquidity_status=liquidity_status,
        market_regime=market_regime,
        as_of_time=timestamp,
        material_state_hash=material_state_hash,
    )
