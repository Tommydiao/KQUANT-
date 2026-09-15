"""Point-in-time, regime-conditioned block bootstrap for action risk evidence."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .math_action_contract import CORE_SYMBOLS, canonical_hash


MODEL_VERSION = "math_action_regime_block_bootstrap_dev_v1.0.1"
REGIME_BINS = 4
MINIMUM_BLOCKS = 30


def _outcome_from_close_paths(
    close_paths: np.ndarray,
    *,
    entry_reference: float,
    stop: float,
    target: float,
    fee: float,
    slippage: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return net R and outcome codes; stop wins a same-step collision."""
    entry = entry_reference * (1.0 + slippage)
    stop_fill = stop * (1.0 - slippage)
    base_r = entry - stop_fill + fee * (entry + stop_fill)
    if base_r <= 0:
        raise ValueError("Invalid Monte Carlo BASE R")
    stop_hit = close_paths <= stop
    target_hit = close_paths >= target
    net_r = np.empty(len(close_paths), dtype=float)
    outcome = np.empty(len(close_paths), dtype=np.int8)
    for index in range(len(close_paths)):
        stops = np.flatnonzero(stop_hit[index])
        targets = np.flatnonzero(target_hit[index])
        first_stop = int(stops[0]) if len(stops) else close_paths.shape[1]
        first_target = int(targets[0]) if len(targets) else close_paths.shape[1]
        if first_stop < close_paths.shape[1] and first_stop <= first_target:
            raw_exit, outcome[index] = stop, -1
        elif first_target < close_paths.shape[1]:
            raw_exit, outcome[index] = target, 1
        else:
            raw_exit, outcome[index] = close_paths[index, -1], 0
        exit_price = raw_exit * (1.0 - slippage)
        pnl = exit_price - entry - fee * (entry + exit_price)
        net_r[index] = pnl / base_r
    return net_r, outcome


def _outcome_from_ohlc_paths(
    open_paths: np.ndarray,
    high_paths: np.ndarray,
    low_paths: np.ndarray,
    close_paths: np.ndarray,
    *,
    entry_reference: float,
    stop: float,
    target: float,
    fee: float,
    slippage: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate synthetic OHLC paths with the historical stop-first contract."""
    if not (
        open_paths.shape == high_paths.shape == low_paths.shape == close_paths.shape
        and open_paths.ndim == 2
        and open_paths.shape[1] > 0
    ):
        raise ValueError("OHLC paths must share a non-empty two-dimensional shape")
    entry = entry_reference * (1.0 + slippage)
    stop_fill = stop * (1.0 - slippage)
    base_r = entry - stop_fill + fee * (entry + stop_fill)
    if base_r <= 0:
        raise ValueError("Invalid Monte Carlo BASE R")
    net_r = np.empty(len(close_paths), dtype=float)
    outcomes = np.zeros(len(close_paths), dtype=np.int8)
    for path_index in range(len(close_paths)):
        exit_reference = float(close_paths[path_index, -1])
        for step in range(close_paths.shape[1]):
            if open_paths[path_index, step] <= stop:
                exit_reference, outcomes[path_index] = float(open_paths[path_index, step]), -1
                break
            if open_paths[path_index, step] >= target:
                exit_reference, outcomes[path_index] = float(open_paths[path_index, step]), 1
                break
            if low_paths[path_index, step] <= stop:
                exit_reference, outcomes[path_index] = stop, -1
                break
            if high_paths[path_index, step] >= target:
                exit_reference, outcomes[path_index] = target, 1
                break
        exit_price = exit_reference * (1.0 - slippage)
        net_r[path_index] = (exit_price - entry - fee * (entry + exit_price)) / base_r
    return net_r, outcomes


def _synchronized_ohlc_blocks(dataset, signal_time: int, block_hours: int):
    block_size = block_hours * 12
    by_symbol = {
        symbol: {bar.start: bar for bar in dataset.bars[symbol]["5m"] if bar.start + 300 <= signal_time}
        for symbol in CORE_SYMBOLS
    }
    common = sorted(set.intersection(*(set(by_symbol[symbol]) for symbol in CORE_SYMBOLS)))
    starts = []
    blocks = {symbol: [] for symbol in CORE_SYMBOLS}
    pre_volatility = []
    for index in range(1, len(common) - block_size + 1):
        start = common[index]
        if start % 86400 != 0 or common[index : index + block_size] != list(
            range(start, start + block_size * 300, 300)
        ):
            continue
        prior = common[max(1, index - 288) : index]
        if len(prior) < 288 or prior != list(range(start - 288 * 300, start, 300)):
            continue
        block_values = {}
        vol_values = []
        for symbol in CORE_SYMBOLS:
            source = by_symbol[symbol]
            previous_close = source[common[index - 1]].close
            values = []
            for stamp in common[index : index + block_size]:
                bar = source[stamp]
                values.append(
                    (
                        math.log(bar.open / previous_close),
                        math.log(bar.high / bar.open),
                        math.log(bar.low / bar.open),
                        math.log(bar.close / bar.open),
                    )
                )
                previous_close = bar.close
            block_values[symbol] = np.asarray(values, dtype=float)
            prior_closes = np.asarray([source[stamp].close for stamp in prior], dtype=float)
            vol_values.append(float(np.std(np.diff(np.log(prior_closes))) * math.sqrt(288.0)))
        starts.append(start)
        pre_volatility.append(float(np.mean(vol_values)))
        for symbol in CORE_SYMBOLS:
            blocks[symbol].append(block_values[symbol])
    return (
        np.asarray(starts, dtype=np.int64),
        {symbol: np.asarray(values, dtype=float) for symbol, values in blocks.items()},
        np.asarray(pre_volatility, dtype=float),
    )


def run_synchronized_ohlc_bootstrap(
    dataset,
    plan_rows: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Run a shared block draw for all open plans; it never authorizes an entry."""
    if not plan_rows:
        return {
            "status": "SKIPPED_NO_RESEARCH_CANDIDATE",
            "runtime_admission": False,
            "results": [],
        }
    signal_time = int(plan_rows[0]["signal_time"])
    if any(int(row["signal_time"]) != signal_time for row in plan_rows):
        raise ValueError("Synchronized plans must share a signal time")
    block_hours = max(int(row.get("horizon_hours", 24)) for row in plan_rows)
    starts, blocks, pre_volatility = _synchronized_ohlc_blocks(dataset, signal_time, block_hours)
    if len(starts) < MINIMUM_BLOCKS:
        return {
            "status": "SIMULATION_UNAVAILABLE",
            "reason": "insufficient_synchronized_point_in_time_blocks",
            "eligible_blocks": int(len(starts)),
            "runtime_admission": False,
            "results": [],
        }
    boundaries = np.quantile(pre_volatility, np.linspace(0.0, 1.0, REGIME_BINS + 1))
    current = float(np.mean([row["sigma_24h"] for row in plan_rows]))
    regime = min(REGIME_BINS - 1, int(np.searchsorted(boundaries[1:-1], current, side="right")))
    matched = np.flatnonzero(np.searchsorted(boundaries[1:-1], pre_volatility, side="right") == regime)
    if len(matched) < MINIMUM_BLOCKS:
        return {
            "status": "SIMULATION_UNAVAILABLE",
            "reason": "insufficient_synchronized_regime_blocks",
            "eligible_blocks": int(len(matched)),
            "runtime_admission": False,
            "results": [],
        }
    seed = int(contract["monte_carlo"]["seed"]) + int(
        canonical_hash(sorted(row["sample_id"] for row in plan_rows))[:8], 16
    )
    paths = int(contract["monte_carlo"]["paths"])
    rng = np.random.default_rng(seed)
    selected = matched[rng.integers(0, len(matched), size=paths)]
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) / 10000.0
    results = []
    for row in plan_rows:
        horizon_steps = int(row.get("horizon_hours", 24)) * 12
        ratios = blocks[row["symbol"]][selected, :horizon_steps]
        opens = np.empty((paths, horizon_steps), dtype=float)
        highs = np.empty_like(opens)
        lows = np.empty_like(opens)
        closes = np.empty_like(opens)
        previous = np.full(paths, float(row["signal_reference"]), dtype=float)
        for step in range(horizon_steps):
            opens[:, step] = previous * np.exp(ratios[:, step, 0])
            highs[:, step] = opens[:, step] * np.exp(ratios[:, step, 1])
            lows[:, step] = opens[:, step] * np.exp(ratios[:, step, 2])
            closes[:, step] = opens[:, step] * np.exp(ratios[:, step, 3])
            previous = closes[:, step]
        net_r, outcome = _outcome_from_ohlc_paths(
            opens,
            highs,
            lows,
            closes,
            entry_reference=float(row["signal_reference"]),
            stop=float(row["stop"]),
            target=float(row["target"]),
            fee=fee,
            slippage=slippage,
        )
        results.append(
            {
                "sample_id": row["sample_id"],
                "symbol": row["symbol"],
                "horizon_hours": int(row.get("horizon_hours", 24)),
                "probability_stop": float(np.mean(outcome == -1)),
                "probability_target": float(np.mean(outcome == 1)),
                "probability_time_exit": float(np.mean(outcome == 0)),
                "expected_net_r": float(np.mean(net_r)),
                "net_r_q05_q50_q95": [float(value) for value in np.quantile(net_r, [0.05, 0.5, 0.95])],
            }
        )
    payload = {
        "status": "DEV_ONLY_SYNCHRONIZED_OHLC_RISK_EVIDENCE",
        "model_version": "math_action_synchronized_ohlc_bootstrap_dev_v1.0.0",
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "runtime_admission": False,
        "paths": paths,
        "seed": seed,
        "regime": regime,
        "eligible_blocks": int(len(matched)),
        "shared_block_draws": True,
        "results": results,
        "limitations": [
            "Uses synchronized historical OHLC ratio blocks, not an exchange order-book simulator",
            "Bootstrap frequencies are risk scenarios, not calibrated market probabilities",
            "Monte Carlo cannot create or upgrade a trading action",
        ],
    }
    payload["result_hash"] = canonical_hash(payload)
    return payload


def _historical_blocks(dataset, symbol: str, signal_time: int, block_hours: int) -> tuple[np.ndarray, np.ndarray]:
    fives = [bar for bar in dataset.bars[symbol]["5m"] if bar.start + 300 <= signal_time]
    hours = [bar for bar in dataset.bars[symbol]["1h"] if bar.start + 3600 <= signal_time]
    if len(fives) < block_hours * 12 + 1 or len(hours) < 49:
        return np.empty((0, block_hours * 12)), np.empty(0)
    close_by_hour = {bar.start + 3600: bar.close for bar in hours}
    hour_times = sorted(close_by_hour)
    hourly_returns = {
        hour_times[index]: math.log(close_by_hour[hour_times[index]] / close_by_hour[hour_times[index - 1]])
        for index in range(1, len(hour_times))
    }
    closes = np.asarray([bar.close for bar in fives], dtype=float)
    starts = np.asarray([bar.start for bar in fives], dtype=np.int64)
    returns = np.diff(np.log(closes), prepend=np.nan)
    block_size = block_hours * 12
    blocks = []
    pre_volatility = []
    for index in range(1, len(fives) - block_size + 1):
        start = int(starts[index])
        if start % 86400 != 0 or start + block_hours * 3600 > signal_time:
            continue
        prior_hours = [hourly_returns.get(start - offset * 3600) for offset in range(24, 0, -1)]
        if any(value is None for value in prior_hours):
            continue
        block = returns[index : index + block_size]
        if not np.isfinite(block).all():
            continue
        blocks.append(block)
        pre_volatility.append(float(np.std(prior_hours) * math.sqrt(24.0)))
    if not blocks:
        return np.empty((0, block_size)), np.empty(0)
    return np.asarray(blocks, dtype=float), np.asarray(pre_volatility, dtype=float)


def run_regime_block_bootstrap(
    dataset,
    row: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    if row["symbol"] not in CORE_SYMBOLS or row["market_type"] != "spot" or row["direction"] != "long":
        raise ValueError("Only registered Spot-long actions are supported")
    paths = int(contract["monte_carlo"]["paths"])
    block_hours = int(contract["monte_carlo"]["block_hours"])
    blocks, pre_volatility = _historical_blocks(dataset, row["symbol"], row["signal_time"], block_hours)
    if len(blocks) < MINIMUM_BLOCKS:
        return {
            "sample_id": row["sample_id"],
            "status": "SIMULATION_UNAVAILABLE",
            "reason": "insufficient_point_in_time_blocks",
            "eligible_blocks": int(len(blocks)),
            "runtime_admission": False,
        }
    boundaries = np.quantile(pre_volatility, np.linspace(0.0, 1.0, REGIME_BINS + 1))
    current = float(row["features"]["realized_volatility_24h"])
    regime = min(REGIME_BINS - 1, int(np.searchsorted(boundaries[1:-1], current, side="right")))
    block_regimes = np.searchsorted(boundaries[1:-1], pre_volatility, side="right")
    eligible = blocks[block_regimes == regime]
    if len(eligible) < MINIMUM_BLOCKS:
        return {
            "sample_id": row["sample_id"],
            "status": "SIMULATION_UNAVAILABLE",
            "reason": "insufficient_regime_matched_blocks",
            "eligible_blocks": int(len(eligible)),
            "regime": regime,
            "runtime_admission": False,
        }
    seed = int(contract["monte_carlo"]["seed"]) + int(row["sample_id"][:8], 16)
    rng = np.random.default_rng(seed)
    sampled = eligible[rng.integers(0, len(eligible), size=paths)]
    close_paths = float(row["signal_reference"]) * np.exp(np.cumsum(sampled, axis=1))
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) / 10000.0
    net_r, outcome = _outcome_from_close_paths(
        close_paths,
        entry_reference=float(row["signal_reference"]),
        stop=float(row["stop"]),
        target=float(row["target"]),
        fee=fee,
        slippage=slippage,
    )
    result = {
        "sample_id": row["sample_id"],
        "signal_time": row["signal_time"],
        "symbol": row["symbol"],
        "status": "DEV_RISK_EVIDENCE",
        "model_version": MODEL_VERSION,
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "runtime_admission": False,
        "paths": paths,
        "block_hours": block_hours,
        "regime_bins": REGIME_BINS,
        "regime": regime,
        "eligible_blocks": int(len(eligible)),
        "seed": seed,
        "probability_stop": float(np.mean(outcome == -1)),
        "probability_target": float(np.mean(outcome == 1)),
        "probability_time_exit": float(np.mean(outcome == 0)),
        "expected_net_r": float(np.mean(net_r)),
        "net_r_q05_q50_q95": [float(value) for value in np.quantile(net_r, [0.05, 0.5, 0.95])],
        "calibrated_probability": False,
        "veto_authority": "risk_only",
        "limitations": [
            "Uses point-in-time historical 5-minute close-return blocks, not order-book or exchange-fill paths",
            "Close-only barrier frequencies are diagnostic and must not be reported as formal stop/target probabilities",
            "Regime is a deterministic quartile of prior 24-hour realized volatility",
            "Probabilities are bootstrap frequencies and are not calibrated forecasts",
            "Monte Carlo cannot upgrade a Bayesian or data failure",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result
