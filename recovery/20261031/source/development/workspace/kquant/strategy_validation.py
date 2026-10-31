from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

from .execution_costs import execution_cost_parameters


UTC = timezone.utc


@dataclass(frozen=True)
class BacktestConfig:
    commission_bps_per_side: float = 1.0
    slippage_bps_per_side: float = 5.0
    same_bar_policy: str = "stop_first"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_long_trade(
    candles: list[dict[str, Any]],
    signal_index: int,
    stop_price: float,
    target_price: float,
    horizon_bars: int,
    config: BacktestConfig | None = None,
) -> dict[str, Any]:
    """Evaluate a long signal from the next bar without future leakage."""

    active = config or BacktestConfig()
    entry_index = signal_index + 1
    if entry_index >= len(candles):
        return {"completed": False, "outcome": "insufficient_future_bars"}
    raw_entry = _number(candles[entry_index].get("open"))
    slippage = active.slippage_bps_per_side / 10_000
    commission = active.commission_bps_per_side / 10_000
    entry_price = raw_entry * (1 + slippage)
    risk_per_share = entry_price - stop_price
    if entry_price <= 0 or risk_per_share <= 0 or target_price <= entry_price:
        return {"completed": False, "outcome": "invalid_trade_plan"}

    end_index = min(len(candles) - 1, entry_index + max(1, horizon_bars) - 1)
    max_drawdown_pct = 0.0
    max_runup_pct = 0.0
    exit_price = _number(candles[end_index].get("close")) * (1 - slippage)
    exit_index = end_index
    outcome = "time_exit"
    target_first = False
    stop_first = False

    for index in range(entry_index, end_index + 1):
        bar = candles[index]
        bar_open = _number(bar.get("open"))
        bar_high = _number(bar.get("high"))
        bar_low = _number(bar.get("low"))
        max_drawdown_pct = min(max_drawdown_pct, (bar_low / entry_price - 1) * 100)
        max_runup_pct = max(max_runup_pct, (bar_high / entry_price - 1) * 100)

        if bar_open <= stop_price:
            exit_price = bar_open * (1 - slippage)
            exit_index = index
            outcome = "gap_stop"
            stop_first = True
            break
        if bar_open >= target_price:
            exit_price = bar_open * (1 - slippage)
            exit_index = index
            outcome = "gap_target"
            target_first = True
            break
        hit_stop = bar_low <= stop_price
        hit_target = bar_high >= target_price
        if hit_stop and hit_target:
            if active.same_bar_policy != "stop_first":
                raise ValueError("Only conservative stop_first same-bar handling is supported.")
            exit_price = stop_price * (1 - slippage)
            exit_index = index
            outcome = "same_bar_stop_first"
            stop_first = True
            break
        if hit_stop:
            exit_price = stop_price * (1 - slippage)
            exit_index = index
            outcome = "stop"
            stop_first = True
            break
        if hit_target:
            exit_price = target_price * (1 - slippage)
            exit_index = index
            outcome = "target"
            target_first = True
            break

    round_trip_cost = (entry_price + exit_price) * commission
    realized_r = (exit_price - entry_price - round_trip_cost) / risk_per_share
    return {
        "completed": True,
        "outcome": outcome,
        "entry_index": entry_index,
        "exit_index": exit_index,
        "entry_time": candles[entry_index].get("open_time"),
        "exit_time": candles[exit_index].get("open_time"),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_price": round(stop_price, 4),
        "target_price": round(target_price, 4),
        "realized_r": round(realized_r, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "max_runup_pct": round(max_runup_pct, 4),
        "target_first": target_first,
        "stop_first": stop_first,
        "config": asdict(active),
    }


def evaluate_long_trade_scenarios(
    candles: list[dict[str, Any]],
    signal_index: int,
    stop_price: float,
    target_price: float,
    horizon_bars: int,
    *,
    average_dollar_volume: float,
) -> dict[str, dict[str, Any]]:
    entry_index = signal_index + 1
    entry_price = _number(candles[entry_index].get("open")) if entry_index < len(candles) else 0.0
    results: dict[str, dict[str, Any]] = {}
    for scenario in ("optimistic", "baseline", "conservative"):
        costs = execution_cost_parameters(
            scenario=scenario,
            price=entry_price,
            average_dollar_volume=average_dollar_volume,
        )
        outcome = evaluate_long_trade(
            candles,
            signal_index,
            stop_price,
            target_price,
            horizon_bars,
            BacktestConfig(
                commission_bps_per_side=float(costs["commission_bps_per_side"]),
                slippage_bps_per_side=float(costs["slippage_bps_per_side"]),
            ),
        )
        outcome["execution_costs"] = costs
        results[scenario] = outcome
    return results


def wilson_interval(wins: int, samples: int, z: float = 1.96) -> tuple[float, float]:
    if samples <= 0:
        return 0.0, 0.0
    rate = wins / samples
    denominator = 1 + z * z / samples
    center = (rate + z * z / (2 * samples)) / denominator
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * samples)) / samples) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def walk_forward_split(
    items: list[dict[str, Any]],
    embargo_bars: int = 0,
) -> dict[str, list[dict[str, Any]]]:
    """Split by trading date, keeping every symbol from a date in one partition.

    The embargo is expressed in distinct signal dates, not row count. This avoids
    cross-symbol leakage and removes labels close to a partition boundary.
    """

    ordered = sorted(items, key=lambda item: str(item.get("signal_time") or item.get("created_at") or ""))
    by_date: dict[str, list[dict[str, Any]]] = {}
    for item in ordered:
        value = str(item.get("signal_time") or item.get("created_at") or "")
        if len(value) > 10 and value[10] not in {"T", " "}:
            by_date.setdefault(value, []).append(item)
            continue
        candidate = value[:10]
        try:
            date.fromisoformat(candidate)
            partition_date = candidate
        except ValueError:
            # Preserve malformed fixture identifiers as distinct values rather
            # than silently grouping an entire test/history into one date.
            partition_date = value
        by_date.setdefault(partition_date, []).append(item)
    dates = sorted(by_date)
    total_dates = len(dates)
    train_end = int(total_dates * 0.6)
    validation_end = int(total_dates * 0.8)
    embargo = max(0, int(embargo_bars))
    train_dates = dates[: max(0, train_end - embargo)]
    validation_dates = dates[min(total_dates, train_end + embargo) : max(train_end, validation_end - embargo)]
    test_dates = dates[min(total_dates, validation_end + embargo) :]
    return {
        "train": [item for date in train_dates for item in by_date[date]],
        "validation": [item for date in validation_dates for item in by_date[date]],
        "test": [item for date in test_dates for item in by_date[date]],
    }


def bootstrap_mean_interval(
    values: Iterable[float],
    *,
    samples: int = 2_000,
    seed: int = 20260713,
) -> tuple[float, float]:
    data = [float(value) for value in values]
    if not data:
        return 0.0, 0.0
    if len(data) == 1:
        return data[0], data[0]
    rng = random.Random(seed)
    means = sorted(
        sum(rng.choice(data) for _ in data) / len(data)
        for _ in range(max(100, samples))
    )
    low_index = int((len(means) - 1) * 0.025)
    high_index = int((len(means) - 1) * 0.975)
    return means[low_index], means[high_index]


def summarize_outcomes(outcomes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in outcomes if item.get("completed")]
    samples = len(completed)
    wins = sum(1 for item in completed if _number(item.get("realized_r")) > 0)
    losses = samples - wins
    values = [_number(item.get("realized_r")) for item in completed]
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    cumulative = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown_r = min(max_drawdown_r, cumulative - peak)
    low, high = wilson_interval(wins, samples)
    expected_low, expected_high = bootstrap_mean_interval(values)
    evidence = "robust" if samples >= 100 else "limited" if samples >= 30 else "insufficient"
    return {
        "sample_count": samples,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / samples * 100, 2) if samples else 0.0,
        "average_r": round(sum(values) / samples, 4) if samples else 0.0,
        "average_win_r": round(positive / wins, 4) if wins else 0.0,
        "average_loss_r": round(-negative / losses, 4) if losses else 0.0,
        "profit_factor": round(positive / negative, 4) if negative else (999.0 if positive else 0.0),
        "max_drawdown_r": round(max_drawdown_r, 4),
        "target_first_rate": round(sum(bool(item.get("target_first")) for item in completed) / samples * 100, 2) if samples else 0.0,
        "stop_first_rate": round(sum(bool(item.get("stop_first")) for item in completed) / samples * 100, 2) if samples else 0.0,
        "confidence_interval_95": [round(low * 100, 2), round(high * 100, 2)],
        "expected_r_interval_95": [round(expected_low, 4), round(expected_high, 4)],
        "evidence_quality": evidence,
        "limited_evidence": samples < 100,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def summarize_by_dimensions(events: list[dict[str, Any]]) -> dict[str, Any]:
    dimensions = (
        "profile",
        "action",
        "market_regime",
        "sector",
        "stock_layer",
        "volatility_bucket",
        "data_source",
        "split_name",
    )
    result: dict[str, Any] = {}
    for dimension in dimensions:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for item in events:
            key = str(item.get(dimension) or "unknown")
            buckets.setdefault(key, []).append(item)
        result[dimension] = {key: summarize_outcomes(rows) for key, rows in sorted(buckets.items())}
    return result
