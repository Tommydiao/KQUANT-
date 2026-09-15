"""Negative controls and dependence-aware uncertainty for frozen trend research."""

from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
from typing import Any

import numpy as np

from .math_action_contract import CORE_SYMBOLS, canonical_hash, file_hash
from .trend_evidence_research import (
    EnrichedDataset,
    _performance_metrics,
    evaluate_ridge_candidates,
    replay_candidate_fold,
)


HOUR = 3600
DAY = 86400
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "trend_evidence_controls_v1.json"


def load_controls_contract(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    import json

    path = path.resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != "DEV_ONLY_EXPOSED_RESEARCH":
        raise ValueError("Controls may only use exposed development evidence")
    if value.get("claims") != {
        "independent_oos": False,
        "calibrated_probability": False,
        "performance_gate_passed": False,
        "runtime_admission": False,
    }:
        raise ValueError("Control claims must remain fail-closed")
    if int(value["random_control"]["repetitions"]) != 200:
        raise ValueError("Random-control repetitions changed")
    uncertainty = value["uncertainty"]
    if int(uncertainty["block_days"]) != 7 or int(uncertainty["paths"]) != 2000:
        raise ValueError("Registered uncertainty contract changed")
    result = dict(value)
    result["config_path"] = str(path)
    result["config_sha256"] = file_hash(path)
    result["contract_hash"] = canonical_hash(value)
    return result


def trailing_return_6h(dataset: EnrichedDataset, symbol: str, signal_time: int) -> float:
    bars = {bar.start: bar for bar in dataset.base.bars[symbol]["1h"]}
    current = bars.get(signal_time - HOUR)
    prior = bars.get(signal_time - 7 * HOUR)
    if current is None or prior is None or current.close <= 0 or prior.close <= 0:
        raise ValueError(f"Missing point-in-time 6H return for {symbol} at {signal_time}")
    return math.log(current.close / prior.close)


def price_momentum_predictions(
    rows: list[dict[str, Any]],
    folds: list[dict[str, int]],
    dataset: EnrichedDataset,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a no-fit price-only control from information known at signal time."""
    fold_by_number = {int(fold["fold"]): fold for fold in folds}
    predictions: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_rows = [row for row in rows if row["candidate_id"] == candidate["id"]]
        for fold_number, fold in fold_by_number.items():
            for row in candidate_rows:
                if not fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]:
                    continue
                score = trailing_return_6h(dataset, row["symbol"], int(row["signal_time"]))
                predictions.append(
                    {
                        "sample_id": row["sample_id"],
                        "candidate_id": candidate["id"],
                        "fold": fold_number,
                        "signal_time": row["signal_time"],
                        "symbol": row["symbol"],
                        "predicted_net_r": score,
                        "passes_research_gate": score > 0.0,
                        "model_artifact_hash": None,
                        "decision_authority": "DEV_PRICE_MOMENTUM_CONTROL_ONLY",
                    }
                )
    return predictions


def _compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    candidates = {}
    for candidate_id, item in evaluation["candidate_results"].items():
        candidates[candidate_id] = {
            key: value
            for key, value in item.items()
            if key not in {"trades", "equity_curve"}
        }
    payload = {
        "status": evaluation["status"],
        "candidate_results": candidates,
        "claims": evaluation["claims"],
    }
    payload["result_hash"] = canonical_hash(payload)
    return payload


def run_price_momentum_control(
    base_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    folds: list[dict[str, int]],
    dataset: EnrichedDataset,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    predictions = price_momentum_predictions(base_rows, folds, dataset, contract["candidates"])
    ridge_like = {"folds": folds, "predictions": predictions}
    evaluation = evaluate_ridge_candidates(base_rows, stress_rows, ridge_like, dataset, contract)
    result = _compact_evaluation(evaluation)
    result["status"] = "DEV_ONLY_PRICE_MOMENTUM_CONTROL"
    result["definition"] = "trailing_6h_log_return_gt_zero_ranked_cross_sectionally"
    result["result_hash"] = canonical_hash({key: value for key, value in result.items() if key != "result_hash"})
    return result, predictions


def _positive_opportunity_counts(
    predictions: list[dict[str, Any]],
) -> dict[tuple[str, int], int]:
    grouped: defaultdict[tuple[str, int], set[int]] = defaultdict(set)
    for row in predictions:
        if row.get("passes_research_gate"):
            grouped[(row["candidate_id"], int(row["fold"]))].add(int(row["signal_time"]))
    return {key: len(value) for key, value in grouped.items()}


def matched_random_predictions(
    rows: list[dict[str, Any]],
    folds: list[dict[str, int]],
    candidates: list[dict[str, Any]],
    opportunity_counts: dict[tuple[str, int], int],
    *,
    seed: int,
) -> list[dict[str, Any]]:
    """Select random hourly opportunities without reading labels or future paths."""
    rng = np.random.default_rng(seed)
    predictions: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_rows = [row for row in rows if row["candidate_id"] == candidate["id"]]
        for fold in folds:
            eligible: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in candidate_rows:
                if fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]:
                    eligible[int(row["signal_time"])].append(row)
            timestamps = sorted(eligible)
            count = min(opportunity_counts.get((candidate["id"], int(fold["fold"])), 0), len(timestamps))
            if not count:
                continue
            selected_indices = rng.permutation(len(timestamps))[:count]
            for index in selected_indices:
                stamp = timestamps[int(index)]
                choices = sorted(eligible[stamp], key=lambda row: CORE_SYMBOLS.index(row["symbol"]))
                row = choices[int(rng.integers(0, len(choices)))]
                score = float(rng.random()) + 1e-12
                predictions.append(
                    {
                        "sample_id": row["sample_id"],
                        "candidate_id": candidate["id"],
                        "fold": int(fold["fold"]),
                        "signal_time": stamp,
                        "symbol": row["symbol"],
                        "predicted_net_r": score,
                        "passes_research_gate": True,
                        "model_artifact_hash": None,
                        "decision_authority": "DEV_MATCHED_RANDOM_CONTROL_ONLY",
                    }
                )
    return predictions


def _finite_quantiles(values: list[float | None]) -> dict[str, float | None]:
    finite = np.asarray([value for value in values if value is not None and math.isfinite(value)], dtype=float)
    if not len(finite):
        return {"q05": None, "q50": None, "q95": None}
    q05, q50, q95 = np.quantile(finite, [0.05, 0.5, 0.95])
    return {"q05": float(q05), "q50": float(q50), "q95": float(q95)}


def run_matched_random_control(
    rows: list[dict[str, Any]],
    folds: list[dict[str, int]],
    dataset: EnrichedDataset,
    contract: dict[str, Any],
    reference_predictions: list[dict[str, Any]],
    controls_contract: dict[str, Any],
) -> dict[str, Any]:
    settings = controls_contract["random_control"]
    reference_opportunity_counts = _positive_opportunity_counts(reference_predictions)
    repetitions = int(settings["repetitions"])
    base_seed = int(settings["seed"])
    samples: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    runtime_cache: dict[str, Any] = {}
    target_trade_counts: dict[tuple[str, int], int] = {}
    selected_opportunity_counts: dict[tuple[str, int], int] = {}
    for candidate in contract["candidates"]:
        for fold in folds:
            key = (candidate["id"], int(fold["fold"]))
            reference = [
                row
                for row in reference_predictions
                if row["candidate_id"] == candidate["id"] and int(row["fold"]) == int(fold["fold"])
            ]
            replay = replay_candidate_fold(
                rows,
                reference,
                dataset,
                fold,
                contract,
                timeline_mode="decision_events",
                runtime_cache=runtime_cache,
            )
            target = int(replay["metrics"]["trades"])
            target_trade_counts[key] = target
            eligible_times = {
                int(row["signal_time"])
                for row in rows
                if row["candidate_id"] == candidate["id"]
                and fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]
            }
            maximum = len(eligible_times)
            if not target or not maximum:
                selected_opportunity_counts[key] = 0
                continue
            low, high = 1, maximum
            best_count, best_error = 1, math.inf
            calibration_seed = base_seed - 1 + int(canonical_hash(key)[:8], 16)
            while low <= high:
                count = (low + high) // 2
                trial = matched_random_predictions(
                    rows,
                    [fold],
                    [candidate],
                    {key: count},
                    seed=calibration_seed,
                )
                trial_replay = replay_candidate_fold(
                    rows,
                    trial,
                    dataset,
                    fold,
                    contract,
                    timeline_mode="decision_events",
                    runtime_cache=runtime_cache,
                )
                actual = int(trial_replay["metrics"]["trades"])
                error = abs(actual - target)
                if error < best_error or (error == best_error and count < best_count):
                    best_count, best_error = count, error
                if actual < target:
                    low = count + 1
                elif actual > target:
                    high = count - 1
                else:
                    break
            selected_opportunity_counts[key] = best_count
    for repetition in range(repetitions):
        predictions = matched_random_predictions(
            rows,
            folds,
            contract["candidates"],
            selected_opportunity_counts,
            seed=base_seed + repetition,
        )
        for candidate in contract["candidates"]:
            selected = [row for row in predictions if row["candidate_id"] == candidate["id"]]
            replays = [
                replay_candidate_fold(
                    rows,
                    selected,
                    dataset,
                    fold,
                    contract,
                    timeline_mode="decision_events",
                    runtime_cache=runtime_cache,
                )
                for fold in folds
            ]
            trades = [trade for replay in replays for trade in replay["trades"]]
            curve = [point for replay in replays for point in replay["equity_curve"]]
            metrics = _performance_metrics(trades, curve)
            metrics["maximum_drawdown_fraction"] = max(
                (replay["metrics"]["maximum_drawdown_fraction"] or 0.0 for replay in replays),
                default=None,
            )
            samples[candidate["id"]].append(metrics)
    candidate_results = {}
    for candidate in contract["candidates"]:
        values = samples[candidate["id"]]
        candidate_results[candidate["id"]] = {
            "reference_positive_hourly_opportunities": sum(
                reference_opportunity_counts.get((candidate["id"], int(fold["fold"])), 0) for fold in folds
            ),
            "target_realized_trades": sum(
                target_trade_counts.get((candidate["id"], int(fold["fold"])), 0) for fold in folds
            ),
            "selected_random_hourly_opportunities": sum(
                selected_opportunity_counts.get((candidate["id"], int(fold["fold"])), 0) for fold in folds
            ),
            "realized_trades": _finite_quantiles([float(item["trades"]) for item in values]),
            "mean_net_r": _finite_quantiles([item["mean_net_r"] for item in values]),
            "profit_factor_r": _finite_quantiles([item["profit_factor_r"] for item in values]),
            "maximum_drawdown_fraction": _finite_quantiles(
                [item["maximum_drawdown_fraction"] for item in values]
            ),
            "probability_mean_net_r_gt_zero": (
                sum(1 for item in values if item["mean_net_r"] is not None and item["mean_net_r"] > 0)
                / len(values)
            ),
        }
    result = {
        "status": "DEV_ONLY_MATCHED_RANDOM_CONTROL",
        "frequency_definition": settings["frequency_basis"],
        "repetitions": repetitions,
        "seed": base_seed,
        "equity_observation_grid": "decision_exit_and_utc_day_boundary_events",
        "candidate_results": candidate_results,
        "claims": controls_contract["claims"],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def run_equal_weight_buy_hold(
    dataset: EnrichedDataset,
    folds: list[dict[str, int]],
    research_contract: dict[str, Any],
    *,
    cost_multiplier: float,
) -> dict[str, Any]:
    fee = float(research_contract["costs"]["spot"]["fee_bps_per_side"]) * cost_multiplier / 10000.0
    slippage = (
        float(research_contract["costs"]["spot"]["slippage_bps_per_side"])
        * cost_multiplier
        / 10000.0
    )
    bars = {
        symbol: {bar.start: bar for bar in dataset.base.bars[symbol]["5m"]}
        for symbol in CORE_SYMBOLS
    }
    fold_results = []
    for fold in folds:
        timestamps = list(range(int(fold["evaluation_start"]), int(fold["evaluation_end_exclusive"]), 300))
        timestamps = [stamp for stamp in timestamps if all(stamp in bars[symbol] for symbol in CORE_SYMBOLS)]
        if not timestamps:
            raise ValueError("No synchronized buy-and-hold evaluation bars")
        first, last = timestamps[0], timestamps[-1]
        quantities = {
            symbol: (1.0 / len(CORE_SYMBOLS)) / (bars[symbol][first].open * (1.0 + fee + slippage))
            for symbol in CORE_SYMBOLS
        }
        curve = []
        peak = 1.0
        drawdown = 0.0
        for stamp in timestamps:
            value = math.fsum(
                quantities[symbol] * bars[symbol][stamp].close * (1.0 - fee - slippage)
                for symbol in CORE_SYMBOLS
            )
            curve.append(value)
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        fold_results.append(
            {
                "fold": int(fold["fold"]),
                "start": first,
                "end": last + 300,
                "net_return": curve[-1] - 1.0,
                "maximum_drawdown_fraction": drawdown,
            }
        )
    result = {
        "status": "DEV_ONLY_EQUAL_WEIGHT_BUY_HOLD_CONTROL",
        "cost_multiplier": cost_multiplier,
        "folds": fold_results,
        "mean_fold_net_return": math.fsum(item["net_return"] for item in fold_results) / len(fold_results),
        "worst_fold_net_return": min(item["net_return"] for item in fold_results),
        "maximum_drawdown_fraction": max(item["maximum_drawdown_fraction"] for item in fold_results),
    }
    result["result_hash"] = canonical_hash(result)
    return result


def block_bootstrap_trade_uncertainty(
    trades: list[dict[str, Any]],
    folds: list[dict[str, int]],
    controls_contract: dict[str, Any],
) -> dict[str, Any]:
    settings = controls_contract["uncertainty"]
    block_days = int(settings["block_days"])
    paths = int(settings["paths"])
    rng = np.random.default_rng(int(settings["seed"]))
    trades_by_fold_day: defaultdict[tuple[int, int], list[float]] = defaultdict(list)
    for trade in trades:
        trades_by_fold_day[(int(trade["fold"]), int(trade["signal_time"]) // DAY)].append(float(trade["net_r"]))
    blocks: list[list[list[float]]] = []
    total_days = 0
    for fold in folds:
        start_day = int(fold["evaluation_start"]) // DAY
        end_day = (int(fold["evaluation_end_exclusive"]) - 1) // DAY
        days = list(range(start_day, end_day + 1))
        total_days += len(days)
        for offset in range(0, max(0, len(days) - block_days + 1)):
            blocks.append(
                [trades_by_fold_day[(int(fold["fold"]), day)] for day in days[offset : offset + block_days]]
            )
    if not trades or not blocks:
        return {
            "status": "UNCERTAINTY_UNAVAILABLE_NO_TRADES",
            "paths": 0,
            "runtime_admission": False,
        }
    draws = math.ceil(total_days / block_days)
    mean_values = []
    profit_factors = []
    maximum_drawdowns_r = []
    for _ in range(paths):
        sampled_days: list[list[float]] = []
        for index in rng.integers(0, len(blocks), size=draws):
            sampled_days.extend(blocks[int(index)])
        sampled_days = sampled_days[:total_days]
        values = [value for day in sampled_days for value in day]
        if not values:
            continue
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value <= 0]
        mean_values.append(math.fsum(values) / len(values))
        if losses and math.fsum(losses) < 0:
            profit_factors.append(math.fsum(wins) / -math.fsum(losses))
        cumulative = 0.0
        peak = 0.0
        drawdown = 0.0
        for day in sampled_days:
            cumulative += math.fsum(day)
            peak = max(peak, cumulative)
            drawdown = max(drawdown, peak - cumulative)
        maximum_drawdowns_r.append(drawdown)
    minimum_days = int(settings["minimum_weeks_for_stability"]) * block_days
    result = {
        "status": "DEV_ONLY_SYNCHRONIZED_UTC_BLOCK_BOOTSTRAP",
        "block_days": block_days,
        "requested_paths": paths,
        "completed_paths": len(mean_values),
        "seed": int(settings["seed"]),
        "eligible_utc_days": total_days,
        "eligible_blocks": len(blocks),
        "stability": (
            "AT_LEAST_12_UTC_WEEKS" if total_days >= minimum_days else "UNSTABLE_LESS_THAN_12_UTC_WEEKS"
        ),
        "mean_net_r": _finite_quantiles(mean_values),
        "profit_factor_r": _finite_quantiles(profit_factors),
        "maximum_drawdown_r": _finite_quantiles(maximum_drawdowns_r),
        "probability_mean_net_r_gt_zero": sum(value > 0 for value in mean_values) / len(mean_values),
        "claims": controls_contract["claims"],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def lead_time_vs_positive_price_momentum(
    trades: list[dict[str, Any]],
    dataset: EnrichedDataset,
    *,
    maximum_hours: int = 72,
) -> dict[str, Any]:
    leads = []
    already_positive = 0
    censored = 0
    for trade in trades:
        signal_time = int(trade["signal_time"])
        first_positive = None
        for offset in range(maximum_hours + 1):
            try:
                value = trailing_return_6h(dataset, trade["symbol"], signal_time + offset * HOUR)
            except ValueError:
                break
            if value > 0:
                first_positive = offset
                break
        if first_positive is None:
            censored += 1
        else:
            leads.append(float(first_positive))
            if first_positive == 0:
                already_positive += 1
    result = {
        "definition": "hours_until_trailing_6h_price_return_first_exceeds_zero_after_candidate_entry",
        "trades": len(trades),
        "observed": len(leads),
        "censored": censored,
        "already_positive_at_entry": already_positive,
        "positive_lead_fraction": sum(value > 0 for value in leads) / len(leads) if leads else None,
        "lead_hours": _finite_quantiles(leads),
        "selection_uses_future_lead": False,
    }
    result["result_hash"] = canonical_hash(result)
    return result
