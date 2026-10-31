from __future__ import annotations

import math
from statistics import NormalDist, mean, pstdev
from typing import Any, Callable, Iterable

from .strategy_validation import bootstrap_mean_interval, summarize_outcomes


ROBUSTNESS_SCHEMA_VERSION = "strategy_robustness_v1"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ordered(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((dict(item) for item in items), key=lambda item: str(item.get("signal_time") or item.get("created_at") or ""))


def rolling_walk_forward_windows(
    items: Iterable[dict[str, Any]],
    *,
    train_size: int | None = None,
    validation_size: int | None = None,
    test_size: int | None = None,
    windows: int = 3,
    embargo_bars: int = 0,
) -> list[dict[str, Any]]:
    """Create chronological, overlapping walk-forward windows without shuffling."""

    ordered = _ordered(items)
    total = len(ordered)
    if total < 3:
        return []
    train = train_size or max(1, int(total * 0.5))
    validation = validation_size or max(1, int(total * 0.2))
    test = test_size or max(1, int(total * 0.2))
    span = train + validation + test
    if span > total:
        train = max(1, total - validation - test)
        span = train + validation + test
    if span > total or train <= 0:
        return []
    count = max(1, min(int(windows), total - span + 1))
    starts = [0] if count == 1 else sorted({round(index * (total - span) / (count - 1)) for index in range(count)})
    embargo = max(0, int(embargo_bars))
    result: list[dict[str, Any]] = []
    for index, start in enumerate(starts, start=1):
        train_end = start + train
        validation_end = train_end + validation
        test_end = validation_end + test
        train_rows = ordered[start : max(start, train_end - embargo)]
        validation_rows = ordered[min(validation_end, train_end + embargo) : max(train_end, validation_end - embargo)]
        test_rows = ordered[min(test_end, validation_end + embargo) : test_end]
        if not train_rows or not validation_rows or not test_rows:
            continue
        result.append(
            {
                "window": index,
                "chronological": True,
                "embargo_bars": embargo,
                "train": summarize_outcomes(train_rows),
                "validation": summarize_outcomes(validation_rows),
                "test": summarize_outcomes(test_rows),
                "ranges": {
                    "train": [train_rows[0].get("signal_time"), train_rows[-1].get("signal_time")],
                    "validation": [validation_rows[0].get("signal_time"), validation_rows[-1].get("signal_time")],
                    "test": [test_rows[0].get("signal_time"), test_rows[-1].get("signal_time")],
                },
            }
        )
    return result


def default_parameter_variants() -> list[dict[str, Any]]:
    """Neighbouring policy variations. Results must come from a fresh replay."""

    return [
        {"name": "baseline", "overrides": {}},
        {"name": "ema_fast_minus_2", "overrides": {"ema_fast": 18}},
        {"name": "ema_fast_plus_2", "overrides": {"ema_fast": 22}},
        {"name": "volume_minus_10pct", "overrides": {"min_relative_volume": 1.035}},
        {"name": "volume_plus_10pct", "overrides": {"min_relative_volume": 1.265}},
        {"name": "atr_stop_minus_10pct", "overrides": {"atr_stop_multiplier_factor": 0.9}},
        {"name": "atr_stop_plus_10pct", "overrides": {"atr_stop_multiplier_factor": 1.1}},
        {"name": "risk_reward_minus_10pct", "overrides": {"risk_reward_factor": 0.9}},
        {"name": "risk_reward_plus_10pct", "overrides": {"risk_reward_factor": 1.1}},
    ]


def parameter_sensitivity_report(
    replay_variant: Callable[[dict[str, Any]], Iterable[dict[str, Any]]],
    *,
    variants: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run nearby deterministic policy variants and report stability, not optimum."""

    rows: list[dict[str, Any]] = []
    for variant in variants or default_parameter_variants():
        outcomes = list(replay_variant(dict(variant.get("overrides") or {})))
        summary = summarize_outcomes(outcomes)
        rows.append({"name": variant["name"], "overrides": variant.get("overrides") or {}, "summary": summary})
    average_rs = [_number(row["summary"].get("average_r")) for row in rows]
    baseline = next((row for row in rows if row["name"] == "baseline"), rows[0] if rows else {"summary": {}})
    baseline_r = _number(baseline["summary"].get("average_r"))
    deviations = [abs(value - baseline_r) for value in average_rs]
    return {
        "schema_version": ROBUSTNESS_SCHEMA_VERSION,
        "method": "neighbouring_parameter_replay",
        "variants": rows,
        "baseline_average_r": round(baseline_r, 4),
        "worst_variant_average_r": round(min(average_rs), 4) if average_rs else 0.0,
        "median_like_average_r": round(sorted(average_rs)[len(average_rs) // 2], 4) if average_rs else 0.0,
        "max_absolute_average_r_deviation": round(max(deviations), 4) if deviations else 0.0,
        "stable": bool(average_rs) and min(average_rs) >= 0 and max(deviations) <= max(0.25, abs(baseline_r) * 0.75),
        "not_an_optimization_search": True,
    }


def market_regime_report(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in trades:
        base = str(item.get("market_regime") or "DATA_CAUTION")
        volatility = str(item.get("volatility_bucket") or "unknown")
        trend = str(item.get("trend_condition") or "unknown")
        buckets.setdefault(f"regime:{base}", []).append(item)
        buckets.setdefault(f"volatility:{volatility}", []).append(item)
        buckets.setdefault(f"trend:{trend}", []).append(item)
    return {key: summarize_outcomes(rows) for key, rows in sorted(buckets.items())}


def concentration_report(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in trades if item.get("completed")]

    def group(field: str) -> list[dict[str, Any]]:
        values: dict[str, list[dict[str, Any]]] = {}
        for item in rows:
            values.setdefault(str(item.get(field) or "Unknown"), []).append(item)
        output = []
        for key, members in values.items():
            total_r = sum(_number(item.get("realized_r")) for item in members)
            output.append({"name": key, "sample_count": len(members), "total_r": round(total_r, 4), "average_r": summarize_outcomes(members)["average_r"]})
        return sorted(output, key=lambda item: (-item["total_r"], item["name"]))

    by_symbol = group("symbol")
    by_sector = group("sector")
    by_layer = group("stock_layer")
    best_five_symbols = {item["name"] for item in by_symbol[:5]}
    without_best_five = [item for item in rows if str(item.get("symbol") or "Unknown") not in best_five_symbols]
    return {
        "by_symbol": by_symbol,
        "by_sector": by_sector,
        "by_stock_layer": by_layer,
        "without_best_five_symbols": summarize_outcomes(without_best_five),
        "top_symbol_concentration_pct": round(
            (by_symbol[0]["total_r"] / sum(item["total_r"] for item in by_symbol) * 100) if by_symbol and sum(item["total_r"] for item in by_symbol) else 0.0,
            4,
        ),
    }


def deflated_sharpe_report(returns: Iterable[float], *, trial_count: int = 1) -> dict[str, Any]:
    values = [float(value) for value in returns]
    if len(values) < 2:
        return {"available": False, "reason": "insufficient_return_observations", "trial_count": max(1, trial_count)}
    deviation = pstdev(values)
    observed = mean(values) / deviation * math.sqrt(252) if deviation else 0.0
    trials = max(1, int(trial_count))
    expected_max = NormalDist().inv_cdf(1 - 1 / (trials + 1)) * math.sqrt(1 / max(1, len(values) - 1))
    standard_error = math.sqrt((1 + 0.5 * observed * observed) / max(1, len(values) - 1))
    probability = NormalDist().cdf((observed - expected_max) / standard_error) if standard_error else 0.0
    return {
        "available": True,
        "observed_sharpe": round(observed, 4),
        "trial_count": trials,
        "expected_max_sharpe_under_trials": round(expected_max, 4),
        "deflated_sharpe_probability": round(probability, 4),
        "method_limitations": "Approximate normal-return deflation; not a substitute for independent out-of-sample evidence.",
    }


def statistical_confidence_report(trades: Iterable[dict[str, Any]], *, trial_count: int = 1) -> dict[str, Any]:
    rows = [dict(item) for item in trades if item.get("completed")]
    values = [_number(item.get("realized_r")) for item in rows]
    low, high = bootstrap_mean_interval(values, samples=2_000, seed=20260723)
    summary = summarize_outcomes(rows)
    return {
        "summary": summary,
        "bootstrap_average_r_interval_95": [round(low, 4), round(high, 4)],
        "wilson_win_rate_interval_95": summary["confidence_interval_95"],
        "deflated_sharpe": deflated_sharpe_report(values, trial_count=trial_count),
        "multiple_trial_record": {"trial_count": max(1, int(trial_count)), "registered": True},
        "overfit_risk_score": overfit_risk_score(summary, trial_count=trial_count),
    }


def overfit_risk_score(summary: dict[str, Any], *, trial_count: int) -> dict[str, Any]:
    samples = int(summary.get("sample_count") or 0)
    width = abs(_number((summary.get("expected_r_interval_95") or [0, 0])[1]) - _number((summary.get("expected_r_interval_95") or [0, 0])[0]))
    risk = 0.0
    risk += max(0.0, 40 - min(40.0, samples / 2))
    risk += min(20.0, width * 10)
    risk += min(25.0, max(0, int(trial_count) - 1) * 3)
    risk += 15.0 if _number(summary.get("average_r")) <= 0 else 0.0
    score = min(100.0, risk)
    return {"score": round(score, 2), "label": "high" if score >= 60 else "medium" if score >= 30 else "low"}


def evidence_score(
    *,
    test_summary: dict[str, Any],
    sensitivity: dict[str, Any],
    regime: dict[str, Any],
    concentration: dict[str, Any],
    portfolio_metrics: dict[str, Any],
    benchmark_return_pct: float | None = None,
) -> dict[str, Any]:
    """Score research evidence only; it never generates a buy decision."""

    samples = _number(test_summary.get("sample_count"))
    components = {
        "sample_size": min(16.0, samples / 100 * 16),
        "out_of_sample": 18.0 if _number(test_summary.get("average_r")) > 0 and _number(test_summary.get("profit_factor")) >= 1.1 else 0.0,
        "parameter_stability": 12.0 if sensitivity.get("stable") else 0.0,
        "regime_stability": 12.0 if sum(1 for value in regime.values() if _number(value.get("average_r")) > 0) >= 2 else 0.0,
        "diversification": max(0.0, 10.0 - _number(concentration.get("top_symbol_concentration_pct")) / 10),
        "cost_sensitivity": 10.0 if _number(test_summary.get("average_r")) > 0 else 0.0,
        "benchmark_excess": 10.0 if benchmark_return_pct is not None and _number(portfolio_metrics.get("total_return_pct")) > benchmark_return_pct else 0.0,
        "drawdown": max(0.0, 12.0 - abs(_number(portfolio_metrics.get("max_drawdown_pct"))) * 1.2),
    }
    total = min(100.0, max(0.0, sum(components.values())))
    return {
        "score": round(total, 2),
        "components": {key: round(value, 2) for key, value in components.items()},
        "forward_observation_eligible": total >= 70 and samples >= 100,
        "not_a_buy_signal": True,
        "evidence_label": "strong" if total >= 80 else "developing" if total >= 55 else "insufficient",
    }
