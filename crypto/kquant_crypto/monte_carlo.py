from __future__ import annotations

import random
from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

from .evaluation_models import stable_hash


MONTE_CARLO_MODEL_VERSION = "crypto_monte_carlo_v1.0.0"


@dataclass(frozen=True)
class MonteCarloConfig:
    horizons_days: tuple[int, ...] = (5, 20, 60)
    paths: int = 5000
    block_size: int = 5
    seed: int = 7
    target_return: float = 0.10
    stop_return: float = -0.05
    ruin_return: float = -0.25
    instrument_type: str = "spot"
    instrument_id: str = ""
    instrument_data_status: str = ""
    underlying_proxy_used: bool = False
    daily_leverage: float = 1.0
    management_fee_bps: float = 0.0
    tracking_error_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0

    def normalized(self) -> "MonteCarloConfig":
        horizons = tuple(sorted({int(value) for value in self.horizons_days if int(value) > 0}))
        if not horizons:
            raise ValueError("horizons_days must contain a positive horizon")
        paths = int(self.paths)
        if paths < 100 or paths > 10000:
            raise ValueError("paths must be between 100 and 10000")
        if int(self.block_size) < 1:
            raise ValueError("block_size must be positive")
        if self.stop_return >= 0 or self.target_return <= 0:
            raise ValueError("target_return must be positive and stop_return negative")
        if self.instrument_type == "leveraged_etf" and self.daily_leverage <= 0:
            raise ValueError("daily_leverage must be positive for leveraged_etf")
        return MonteCarloConfig(
            horizons_days=horizons,
            paths=paths,
            block_size=int(self.block_size),
            seed=int(self.seed),
            target_return=float(self.target_return),
            stop_return=float(self.stop_return),
            ruin_return=float(self.ruin_return),
            instrument_type=str(self.instrument_type),
            instrument_id=str(self.instrument_id),
            instrument_data_status=str(self.instrument_data_status).lower(),
            underlying_proxy_used=bool(self.underlying_proxy_used),
            daily_leverage=float(self.daily_leverage),
            management_fee_bps=float(self.management_fee_bps),
            tracking_error_bps=float(self.tracking_error_bps),
            spread_bps=float(self.spread_bps),
            slippage_bps=float(self.slippage_bps),
        )

    def to_mapping(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            "horizons_days": list(value.horizons_days),
            "paths": value.paths,
            "block_size": value.block_size,
            "seed": value.seed,
            "target_return": value.target_return,
            "stop_return": value.stop_return,
            "ruin_return": value.ruin_return,
            "instrument_type": value.instrument_type,
            "instrument_id": value.instrument_id,
            "instrument_data_status": value.instrument_data_status,
            "underlying_proxy_used": value.underlying_proxy_used,
            "daily_leverage": value.daily_leverage,
            "management_fee_bps": value.management_fee_bps,
            "tracking_error_bps": value.tracking_error_bps,
            "spread_bps": value.spread_bps,
            "slippage_bps": value.slippage_bps,
        }


@dataclass(frozen=True)
class MonteCarloResult:
    status: str
    model_version: str
    sample_count: int
    config: dict[str, Any]
    horizons: dict[str, dict[str, Any]]
    result_hash: str
    limitations: tuple[str, ...] = ()
    input_hash: str = ""
    target_regime: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model_version": self.model_version,
            "sample_count": self.sample_count,
            "config": self.config,
            "horizons": self.horizons,
            "result_hash": self.result_hash,
            "limitations": list(self.limitations),
            "input_hash": self.input_hash,
            "target_regime": self.target_regime,
        }


def _instrument_return(value: float, config: MonteCarloConfig) -> float:
    if config.instrument_type != "leveraged_etf":
        return value
    # This applies daily reset mechanics to the supplied instrument return.
    # It does not synthesize an ETF series from an unrelated underlying.
    leverage = config.daily_leverage
    fee = config.management_fee_bps / 10000.0 / 365.0
    friction = (config.tracking_error_bps + config.spread_bps + config.slippage_bps) / 10000.0
    volatility_drag = 0.5 * max(0.0, leverage - 1.0) * value * value
    return leverage * value - fee - friction - volatility_drag


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _max_drawdown(path: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    maximum = 0.0
    for value in path:
        equity *= 1.0 + value
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak if peak else 0.0)
    return maximum


def _simulate_horizon(
    returns: Sequence[float],
    config: MonteCarloConfig,
    horizon: int,
    rng: random.Random,
) -> dict[str, Any]:
    transformed = [_instrument_return(value, config) for value in returns]
    paths: list[float] = []
    drawdowns: list[float] = []
    target_first = 0
    stop_first = 0
    ruin = 0
    for _ in range(config.paths):
        path: list[float] = []
        cumulative = 1.0
        target_hit = False
        stop_hit = False
        index = rng.randrange(len(transformed))
        for _step in range(horizon):
            for _block_step in range(config.block_size):
                if len(path) >= horizon:
                    break
                path.append(transformed[(index + _block_step) % len(transformed)])
            index = rng.randrange(len(transformed))
        ruin_hit = False
        for value in path[:horizon]:
            cumulative *= 1.0 + value
            total_return = cumulative - 1.0
            if not target_hit and not stop_hit:
                if total_return >= config.target_return:
                    target_hit = True
                    target_first += 1
                elif total_return <= config.stop_return:
                    stop_hit = True
                    stop_first += 1
            if total_return <= config.ruin_return:
                ruin_hit = True
        if ruin_hit:
            ruin += 1
        final_return = cumulative - 1.0
        paths.append(final_return)
        drawdowns.append(_max_drawdown(path[:horizon]))
    risk_unit = abs(config.stop_return)
    return {
        "horizon_days": horizon,
        "path_count": config.paths,
        "p_target_before_stop": target_first / config.paths,
        "p_stop_before_target": stop_first / config.paths,
        "expected_return": sum(paths) / len(paths),
        "expected_r": (sum(paths) / len(paths)) / risk_unit if risk_unit else None,
        "p10_return": _percentile(paths, 0.10),
        "p50_return": _percentile(paths, 0.50),
        "p90_return": _percentile(paths, 0.90),
        "p50_max_drawdown": _percentile(drawdowns, 0.50),
        "p90_max_drawdown": _percentile(drawdowns, 0.90),
        "risk_of_ruin": ruin / config.paths,
    }


def simulate_monte_carlo(
    returns: Sequence[float],
    *,
    config: MonteCarloConfig | None = None,
    regime_labels: Sequence[str] | None = None,
    target_regime: str | None = None,
) -> MonteCarloResult:
    """Run a deterministic regime-conditioned block bootstrap.

    The function refuses short or non-finite histories. A missing result is
    represented explicitly instead of returning zero-valued probabilities.
    """

    policy = (config or MonteCarloConfig()).normalized()
    labels = list(regime_labels or ())
    if labels and len(labels) != len(returns):
        raise ValueError("regime_labels must have the same length as returns")
    wanted_regime = str(target_regime or "").upper()
    normalized_inputs: list[float | None] = []
    for value in returns:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
        normalized_inputs.append(parsed if parsed is not None and isfinite(parsed) else None)
    input_hash = stable_hash({
        "returns": normalized_inputs,
        "regime_labels": labels,
        "target_regime": wanted_regime or None,
    })
    if policy.instrument_type == "leveraged_etf":
        listed_limitations: list[str] = []
        if not policy.instrument_id:
            listed_limitations.append("actual_listed_instrument_id_required")
        if policy.instrument_data_status != "actual":
            listed_limitations.append("actual_listed_instrument_series_required")
        if policy.underlying_proxy_used:
            listed_limitations.append("underlying_proxy_substitution_forbidden")
        if listed_limitations:
            payload = {
                "model_version": MONTE_CARLO_MODEL_VERSION,
                "sample_count": 0,
                "config": policy.to_mapping(),
                "limitations": listed_limitations,
                "input_hash": input_hash,
            }
            return MonteCarloResult(
                status="simulation_unavailable",
                model_version=MONTE_CARLO_MODEL_VERSION,
                sample_count=0,
                config=policy.to_mapping(),
                horizons={},
                result_hash=stable_hash(payload),
                limitations=tuple(listed_limitations + ["no_probability_is_reported"]),
                input_hash=input_hash,
                target_regime=wanted_regime or None,
            )
    clean_values: list[float] = []
    for index, value in enumerate(returns):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(parsed) and (not labels or not wanted_regime or str(labels[index]).upper() == wanted_regime):
            clean_values.append(parsed)
    clean = tuple(clean_values)
    minimum = max(20, policy.block_size * 4)
    if len(clean) < minimum:
        payload = {
            "model_version": MONTE_CARLO_MODEL_VERSION,
            "sample_count": len(clean),
            "config": policy.to_mapping(),
            "input_hash": input_hash,
            "target_regime": wanted_regime or None,
        }
        return MonteCarloResult(
            status="simulation_unavailable",
            model_version=MONTE_CARLO_MODEL_VERSION,
            sample_count=len(clean),
            config=policy.to_mapping(),
            horizons={},
            result_hash=stable_hash(payload),
            limitations=(f"at_least_{minimum}_finite_returns_required", "no_probability_is_reported"),
            input_hash=input_hash,
            target_regime=wanted_regime or None,
        )
    rng = random.Random(policy.seed)
    horizons = {
        str(horizon): _simulate_horizon(clean, policy, horizon, rng)
        for horizon in policy.horizons_days
    }
    payload = {
        "model_version": MONTE_CARLO_MODEL_VERSION,
        "sample_count": len(clean),
        "config": policy.to_mapping(),
        "horizons": horizons,
        "returns_hash": stable_hash(list(clean)),
        "input_hash": input_hash,
        "target_regime": wanted_regime or None,
    }
    return MonteCarloResult(
        status="available",
        model_version=MONTE_CARLO_MODEL_VERSION,
        sample_count=len(clean),
        config=policy.to_mapping(),
        horizons=horizons,
        result_hash=stable_hash(payload),
        limitations=(
            "block_bootstrap_is_historical_evidence_not_a_guarantee",
            "regime_conditioned" if labels and wanted_regime else "regime_labels_not_supplied",
        ),
        input_hash=input_hash,
        target_regime=wanted_regime or None,
    )


__all__ = ["MONTE_CARLO_MODEL_VERSION", "MonteCarloConfig", "MonteCarloResult", "simulate_monte_carlo"]
