from __future__ import annotations

from collections import OrderedDict
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .bayesian_model import PointInTimeFeatureSnapshot, infer_bayesian_posterior
from .market_buffer import Candle
from .model_evidence import (
    ModelEvidencePacket,
    build_model_evidence_packet,
    save_model_evidence_packet,
)
from .monte_carlo import MonteCarloConfig, simulate_monte_carlo


EVIDENCE_PIPELINE_VERSION = "crypto_evidence_pipeline_v1.0.0"
REQUIRED_BAYESIAN_FEATURES = (
    "trend_score",
    "relative_strength",
    "momentum",
    "volume_pressure",
    "drawdown_risk",
)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _clip(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _bayesian_features(factors: Mapping[str, object]) -> dict[str, float]:
    reclaim = _number(factors.get("trend_ema_reclaim"))
    slope = _number(factors.get("trend_ema_slope"))
    relative = [
        value
        for key in ("relative_strength_btc", "relative_strength_eth")
        if (value := _number(factors.get(key))) is not None
    ]
    momentum = _number(factors.get("momentum_acceleration"))
    volume = _number(factors.get("volume_acceleration"))
    compression = _number(factors.get("volatility_compression"))
    result: dict[str, float] = {}
    if reclaim is not None and slope is not None:
        result["trend_score"] = _clip((2.0 * reclaim - 1.0) * 0.6 + _clip(slope / 0.02) * 0.4)
    if relative:
        result["relative_strength"] = _clip((sum(relative) / len(relative)) / 0.10)
    if momentum is not None:
        result["momentum"] = _clip(momentum / 0.10)
    if volume is not None:
        result["volume_pressure"] = _clip(volume)
    if compression is not None:
        result["drawdown_risk"] = _clip(compression - 1.0)
    return result


def _daily_returns(hourly_bars: Sequence[Candle]) -> tuple[float, ...]:
    daily_closes: OrderedDict[str, float] = OrderedDict()
    for bar in hourly_bars:
        if not bar.closed:
            continue
        day = str(bar.start_time)[:10]
        daily_closes[day] = float(bar.close)
    closes = tuple(daily_closes.values())
    return tuple(
        closes[index] / closes[index - 1] - 1.0
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    )


def build_research_model_evidence(
    *,
    db_path: Path,
    asset_id: str,
    symbol: str,
    market_type: str,
    strategy_version: str,
    signal_time: str,
    available_at: str,
    hourly_bars: Sequence[Candle],
    factor_values: Mapping[str, object],
    entry_zone: Sequence[float],
    stop_zone: Sequence[float],
    target_zone: Sequence[float],
    source_snapshot_ids: Sequence[str],
    source_status: str,
    random_seed: int = 7,
) -> ModelEvidencePacket:
    """Build and persist fail-closed mathematical evidence for one plan.

    Bayesian and Monte Carlo evidence are produced from point-in-time inputs.
    No Logistic or Quantile result is invented; until trained artifacts and
    calibration exist, the resulting packet remains ``RESEARCH_ONLY``.
    """

    features = _bayesian_features(factor_values)
    feature_snapshot = PointInTimeFeatureSnapshot.create(
        asset_id=asset_id,
        symbol=symbol,
        signal_time=signal_time,
        available_at=available_at,
        source_status=source_status,
        features=features,
        source_snapshot_ids=tuple(str(item) for item in source_snapshot_ids),
        required_features=REQUIRED_BAYESIAN_FEATURES,
    )
    history_start = next((bar.start_time for bar in hourly_bars if bar.closed), None)
    bayesian = infer_bayesian_posterior(
        feature_snapshot,
        training_window_start=history_start,
        training_window_end=available_at,
        training_dataset_hash=feature_snapshot.content_hash,
        random_seed=random_seed,
    )

    entry = sum(float(value) for value in entry_zone) / len(entry_zone)
    stop = max(float(value) for value in stop_zone)
    target = min(float(value) for value in target_zone)
    if entry <= 0 or stop >= entry or target <= entry:
        raise ValueError("invalid_trade_plan_geometry")
    monte_carlo = simulate_monte_carlo(
        _daily_returns(hourly_bars),
        config=MonteCarloConfig(
            horizons_days=(5, 20, 60),
            paths=5_000,
            block_size=5,
            seed=random_seed,
            target_return=target / entry - 1.0,
            stop_return=stop / entry - 1.0,
            instrument_type=market_type,
            instrument_id=f"binance:{market_type}:{symbol}",
            instrument_data_status="actual",
            spread_bps=_number(factor_values.get("spread_bps")) or 0.0,
            slippage_bps=5.0,
        ),
    )
    packet = build_model_evidence_packet(
        asset_id=asset_id,
        symbol=symbol,
        market_type=market_type,
        strategy_version=strategy_version,
        signal_time=signal_time,
        available_at=available_at,
        evidence_history_start=history_start,
        bayesian_posterior=bayesian.to_mapping(),
        monte_carlo_result=monte_carlo.to_mapping(),
        logistic_result={"status": "unavailable", "reason": "trained_artifact_not_available"},
        expected_return_quantiles={"status": "unavailable", "reason": "trained_artifact_not_available"},
        calibration_status="not_trained",
        source_snapshot_ids=source_snapshot_ids,
    )
    save_model_evidence_packet(db_path, packet)
    return packet


__all__ = [
    "EVIDENCE_PIPELINE_VERSION",
    "REQUIRED_BAYESIAN_FEATURES",
    "build_research_model_evidence",
]
