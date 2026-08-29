from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping, Sequence

from .backtest import BacktestBar
from .bayesian_model import PointInTimeFeatureSnapshot, infer_bayesian_posterior
from .factor_engine import FactorMarketInput, OHLCVBar, compute_factor_value_series
from .evaluation_models import stable_hash
from .roll_engine import CRYPTO_ROLL_STRATEGY_VERSION, RollAction, RollInput, evaluate_roll


ROLL_VALIDATION_VERSION = "crypto_roll_validation_v1.0.0"


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _scaled(value: float | None, scale: float) -> float | None:
    if value is None:
        return None
    return _clamp(float(value) * scale)


def _coverage_for_bars(bars: Sequence[BacktestBar], interval_minutes: int) -> float:
    if len(bars) < 2:
        return 0.0
    try:
        timestamps = [
            datetime.fromisoformat(str(item.start_time).replace("Z", "+00:00"))
            for item in bars
        ]
    except (TypeError, ValueError):
        return 0.0
    expected = max(1, int((timestamps[-1] - timestamps[0]).total_seconds() // (interval_minutes * 60)) + 1)
    return min(1.0, len(set(timestamps)) / expected)


def build_roll_series_from_validation(
    series: Mapping[str, Any],
    *,
    source_dataset_id: str,
    interval_minutes: int = 60,
    min_history_bars: int = 55,
) -> tuple[dict[str, tuple["RollBar", ...]], dict[str, Any]]:
    """Build roll inputs from the same closed-bar features used by replay.

    This adapter is intentionally conservative. It derives a versioned,
    point-in-time Bayesian baseline from registered OHLCV/benchmark features;
    it never invents ETF, funding, on-chain, or derivative values that are
    absent from the source dataset. Missing snapshots become DATA_BLOCKED.
    """

    output: dict[str, tuple[RollBar, ...]] = {}
    excluded: list[dict[str, Any]] = []
    items = series.items() if isinstance(series, Mapping) else ((item.symbol, item) for item in series)
    for key, item in sorted(items, key=lambda pair: str(pair[0])):
        bars = tuple(item.bars)
        if len(bars) < max(1, int(min_history_bars)):
            excluded.append({"symbol": item.symbol, "bars": len(bars), "reason": "insufficient_closed_bars"})
            continue
        ohlcv = tuple(OHLCVBar(close=bar.close, high=bar.high, low=bar.low, volume=bar.volume) for bar in bars)
        benchmarks = {
            str(name).upper(): tuple(
                OHLCVBar(close=bar.close, high=bar.high, low=bar.low, volume=bar.volume)
                for bar in values
            )
            for name, values in (item.benchmark_bars or {}).items()
        }
        factors = compute_factor_value_series(FactorMarketInput(
            bars=ohlcv,
            benchmark_bars=benchmarks,
            derivative_series=tuple(item.derivative_series or ()),
        ))
        derivative_series = tuple(item.derivative_series or ())
        built: list[RollBar] = []
        coverage = _coverage_for_bars(bars, interval_minutes)
        for index, bar in enumerate(bars):
            if index < min_history_bars - 1:
                continue
            values = factors[index]
            reclaim = values.get("trend_ema_reclaim")
            slope = _scaled(values.get("trend_ema_slope"), 100.0)
            relative_parts = [
                _scaled(values.get("relative_strength_btc"), 20.0),
                _scaled(values.get("relative_strength_eth"), 20.0),
            ]
            relative = (
                sum(value for value in relative_parts if value is not None) / len([value for value in relative_parts if value is not None])
                if any(value is not None for value in relative_parts)
                else None
            )
            momentum = _scaled(values.get("momentum_acceleration"), 20.0)
            volume_pressure = _scaled(values.get("volume_acceleration"), 2.0)
            recent_closes = [value.close for value in bars[max(0, index - 19): index + 1]]
            peak = max(recent_closes) if recent_closes else 0.0
            drawdown_risk = None if peak <= 0 else _clamp((peak - bar.close) / peak, 0.0, 1.0)
            trend_score = None if reclaim is None or slope is None else _clamp((1.0 if reclaim >= 0.5 else -1.0) * 0.6 + slope * 0.4)
            feature_values = {
                "trend_score": trend_score,
                "relative_strength": relative,
                "momentum": momentum,
                "volume_pressure": volume_pressure,
                "drawdown_risk": drawdown_risk,
            }
            missing = tuple(sorted(name for name, value in feature_values.items() if value is None))
            signal_time = str(bar.start_time)
            feature_snapshot = PointInTimeFeatureSnapshot.create(
                asset_id=item.asset_id,
                symbol=item.symbol,
                signal_time=signal_time,
                available_at=signal_time,
                source_status="closed",
                features={name: value for name, value in feature_values.items() if value is not None},
                source_snapshot_ids=(f"parquet:{source_dataset_id}",),
                required_features=tuple(feature_values),
            )
            posterior = infer_bayesian_posterior(feature_snapshot)
            derivative = derivative_series[index] if index < len(derivative_series) else {}
            funding = derivative.get("funding_rate") if isinstance(derivative, Mapping) else None
            if funding is not None:
                try:
                    funding_stress = _clamp(abs(float(funding)) / 0.001, 0.0, 1.0)
                except (TypeError, ValueError):
                    funding_stress = None
            else:
                funding_stress = None
            if funding_stress is not None:
                feature_snapshot = PointInTimeFeatureSnapshot.create(
                    asset_id=item.asset_id,
                    symbol=item.symbol,
                    signal_time=signal_time,
                    available_at=signal_time,
                    source_status="closed",
                    features=feature_snapshot.features | {"funding_stress": funding_stress},
                    source_snapshot_ids=feature_snapshot.source_snapshot_ids,
                    required_features=tuple(feature_values),
                )
                posterior = infer_bayesian_posterior(feature_snapshot)
            missing_fields = feature_snapshot.missing_features
            built.append(RollBar(
                start_time=signal_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                roll_input=RollInput(
                    asset_id=item.asset_id,
                    symbol=item.symbol.removesuffix("USDT"),
                    asset_type=str(getattr(item, "asset_type", "crypto_spot") or "crypto_spot"),
                    instrument_id=str(getattr(item, "instrument_id", "") or f"binance:spot:{item.symbol}"),
                    as_of_time=signal_time,
                    data_cutoff_time=signal_time,
                    source_status="closed",
                    coverage=coverage,
                    hard_veto=coverage < 0.95,
                    market_state=posterior.most_likely_state,
                    state_probability=posterior.state_probabilities.get(posterior.most_likely_state, 0.0),
                    target_before_stop_probability=posterior.target_before_stop_probability or 0.0,
                    positive_return_probability=posterior.positive_return_probability or 0.0,
                    drawdown_probability=posterior.drawdown_probability if posterior.drawdown_probability is not None else 1.0,
                    feature_snapshot_id=feature_snapshot.snapshot_id,
                    model_version=posterior.model_version,
                    source_snapshot_ids=feature_snapshot.source_snapshot_ids,
                    missing_fields=missing_fields,
                    warnings=("derivative_evidence_missing",) if funding_stress is None else (),
                    instrument_data_status=str(getattr(item, "instrument_data_status", "") or ""),
                    underlying_proxy_used=bool(getattr(item, "underlying_proxy_used", False)),
                    research_only=True,
                ),
            ))
        if built:
            output[item.symbol] = tuple(built)
        else:
            excluded.append({"symbol": item.symbol, "bars": len(bars), "reason": "no_point_in_time_features"})
    return output, {
        "source_dataset_id": source_dataset_id,
        "interval_minutes": interval_minutes,
        "min_history_bars": min_history_bars,
        "series_count": len(output),
        "eligible_symbols": sorted(output),
        "excluded": excluded,
        "feature_contract": "roll_features_from_closed_bar_prefix_only",
        "derivative_values_are_optional_and_missing_is_explicit": True,
        "dataset_hash": stable_hash({
            symbol: [bar.roll_input.to_mapping() for bar in values]
            for symbol, values in sorted(output.items())
        }),
    }


def asset_group_for_roll(symbol: str, asset_type: str = "") -> str:
    normalized = str(symbol or "").upper().replace("USDT", "")
    if normalized in {"BTC", "ETH"}:
        return "btc_eth"
    if normalized == "ETHU":
        return "ethu"
    if normalized == "MSTR":
        return "mstr"
    if normalized == "MSTU":
        return "mstu"
    if str(asset_type).lower() in {"crypto_leveraged_etf", "listed_crypto_proxy", "crypto_equity_proxy"}:
        return "listed_crypto_proxy"
    return "crypto_alt"


@dataclass(frozen=True)
class RollBar:
    start_time: str
    open: float
    high: float
    low: float
    close: float
    roll_input: RollInput

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RollBar":
        return cls(
            start_time=str(value["start_time"]),
            open=float(value["open"]),
            high=float(value["high"]),
            low=float(value["low"]),
            close=float(value["close"]),
            roll_input=RollInput.from_mapping(value.get("roll_input") or value),
        )


@dataclass(frozen=True)
class RollValidationConfig:
    target_return: float = 0.10
    stop_return: float = -0.05
    max_hold_bars: int = 20
    fee_bps_per_side: float = 1.0
    slippage_bps_per_side: float = 5.0
    train_ratio: float = 0.60
    validation_ratio: float = 0.20
    embargo_bars: int = 1
    bootstrap_iterations: int = 1000
    bootstrap_seed: int = 7
    oos_folds: int = 3

    @property
    def cost_rate_per_side(self) -> float:
        return (self.fee_bps_per_side + self.slippage_bps_per_side) / 10000.0

    def to_mapping(self) -> dict[str, Any]:
        return self.__dict__ | {"cost_rate_per_side": self.cost_rate_per_side}


@dataclass(frozen=True)
class RollOutcome:
    symbol: str
    asset_id: str
    action: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    realized_r: float
    exit_reason: str
    asset_group: str = "crypto_alt"

    @property
    def win(self) -> bool:
        return self.realized_r > 0

    def to_mapping(self) -> dict[str, Any]:
        return self.__dict__ | {"win": self.win}


def _fill_buy(price: float, cost: float) -> float:
    return price * (1.0 + cost)


def _fill_sell(price: float, cost: float) -> float:
    return price * (1.0 - cost)


def run_roll_backtest(
    bars: Sequence[RollBar],
    *,
    config: RollValidationConfig | None = None,
    signal_start_index: int = 0,
    signal_end_index: int | None = None,
) -> list[RollOutcome]:
    """Replay roll actions using only the signal bar and later bars."""

    policy = config or RollValidationConfig()
    if len(bars) < 2:
        return []
    end = min(len(bars) - 1, signal_end_index if signal_end_index is not None else len(bars) - 1)
    index = max(0, int(signal_start_index))
    outcomes: list[RollOutcome] = []
    next_available = index
    while index < end:
        if index < next_available:
            index += 1
            continue
        decision = evaluate_roll(bars[index].roll_input)
        if decision.action not in {RollAction.ROLL_BUY.value, RollAction.ROLL_ADD.value, RollAction.ROTATE_TO.value}:
            index += 1
            continue
        entry_index = index + 1
        entry_price = _fill_buy(bars[entry_index].open, policy.cost_rate_per_side)
        stop_price = entry_price * (1.0 + policy.stop_return)
        target_price = entry_price * (1.0 + policy.target_return)
        final_index = min(len(bars) - 1, entry_index + max(1, policy.max_hold_bars) - 1)
        exit_index = final_index
        exit_price = _fill_sell(bars[final_index].close, policy.cost_rate_per_side)
        reason = "time_exit"
        for position in range(entry_index, final_index + 1):
            bar = bars[position]
            if bar.open <= stop_price:
                exit_index, exit_price, reason = position, _fill_sell(bar.open, policy.cost_rate_per_side), "gap_stop"
                break
            if bar.open >= target_price:
                exit_index, exit_price, reason = position, _fill_sell(bar.open, policy.cost_rate_per_side), "gap_target"
                break
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
            if hit_stop:
                exit_index, exit_price, reason = position, _fill_sell(stop_price, policy.cost_rate_per_side), "stop_first" if hit_target else "stop"
                break
            if hit_target:
                exit_index, exit_price, reason = position, _fill_sell(target_price, policy.cost_rate_per_side), "target"
                break
        risk = entry_price - stop_price
        if risk <= 0:
            index += 1
            continue
        outcomes.append(RollOutcome(
            symbol=bars[index].roll_input.symbol,
            asset_id=bars[index].roll_input.asset_id,
            action=decision.action,
            signal_time=bars[index].start_time,
            entry_time=bars[entry_index].start_time,
            exit_time=bars[exit_index].start_time,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=stop_price,
            target_price=target_price,
            realized_r=(exit_price - entry_price) / risk,
            exit_reason=reason,
            asset_group=asset_group_for_roll(bars[index].roll_input.symbol, bars[index].roll_input.asset_type),
        ))
        next_available = exit_index + 1
        index = next_available
    return outcomes


def _bootstrap_interval(values: Sequence[float], *, iterations: int, seed: int) -> tuple[float, float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    samples = tuple(float(value) for value in values)
    means = sorted(sum(rng.choice(samples) for _ in samples) / len(samples) for _ in range(max(100, iterations)))
    return means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]


def summarize_roll_outcomes(
    outcomes: Sequence[RollOutcome],
    *,
    config: RollValidationConfig | None = None,
    _include_breakdown: bool = True,
) -> dict[str, Any]:
    policy = config or RollValidationConfig()
    values = [float(item.realized_r) for item in outcomes]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "sample_count": len(values),
        "evidence_status": "insufficient" if len(values) < 30 else "limited" if len(values) < 100 else "robust",
        "win_rate": len(wins) / len(values) if values else None,
        "average_r": sum(values) / len(values) if values else None,
        "expected_r": sum(values) / len(values) if values else None,
        "average_win_r": sum(wins) / len(wins) if wins else None,
        "average_loss_r": sum(losses) / len(losses) if losses else None,
        "average_win_loss_ratio": (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown_r": drawdown,
        "bootstrap_expected_r_interval_95": _bootstrap_interval(values, iterations=policy.bootstrap_iterations, seed=policy.bootstrap_seed),
        "target_first_rate": sum(item.exit_reason in {"target", "gap_target"} for item in outcomes) / len(values) if values else None,
        "stop_first_rate": sum(item.exit_reason in {"stop", "stop_first", "gap_stop"} for item in outcomes) / len(values) if values else None,
        "by_action": {
            action: summarize_roll_outcomes(
                [item for item in outcomes if item.action == action],
                config=policy,
                _include_breakdown=False,
            )
            for action in sorted({item.action for item in outcomes})
        } if _include_breakdown else {},
        "by_asset_group": {
            group: summarize_roll_outcomes(
                [item for item in outcomes if item.asset_group == group],
                config=policy,
                _include_breakdown=False,
            )
            for group in sorted({item.asset_group for item in outcomes})
        } if _include_breakdown else {},
    }


def _date_partitions(dates: Sequence[str], train_ratio: float, validation_ratio: float) -> dict[str, tuple[str, ...]]:
    unique = tuple(sorted(set(dates)))
    if len(unique) < 3:
        return {"train": unique, "validation": (), "test": ()}
    train_end = min(len(unique) - 2, max(1, int(len(unique) * train_ratio)))
    validation_end = min(len(unique) - 1, max(train_end + 1, int(len(unique) * (train_ratio + validation_ratio))))
    return {"train": unique[:train_end], "validation": unique[train_end:validation_end], "test": unique[validation_end:]}


def _rolling_oos_partitions(dates: Sequence[str], fold_count: int) -> list[dict[str, tuple[str, ...]]]:
    """Build expanding-train, disjoint validation/test windows by date."""
    unique = tuple(sorted(set(dates)))
    requested = max(1, int(fold_count))
    window = max(1, len(unique) // (requested + 4))
    initial_train = len(unique) - (requested + 1) * window
    if initial_train < 1:
        return []
    partitions: list[dict[str, tuple[str, ...]]] = []
    for index in range(requested):
        validation_start = initial_train + index * window
        test_start = validation_start + window
        test_end = min(len(unique), test_start + window)
        if test_start >= len(unique) or test_start >= test_end:
            break
        partitions.append({
            "train": unique[:validation_start],
            "validation": unique[validation_start:test_start],
            "test": unique[test_start:test_end],
        })
    return partitions


def _outcomes_for_dates(
    series: Mapping[str, Sequence[RollBar]],
    dates: Sequence[str],
    *,
    config: RollValidationConfig,
    apply_embargo: bool,
) -> list[RollOutcome]:
    if not dates:
        return []
    wanted = set(dates)
    outcomes: list[RollOutcome] = []
    for bars in series.values():
        indices = [index for index, bar in enumerate(bars) if bar.start_time[:10] in wanted]
        if not indices:
            continue
        start = min(indices) + (config.embargo_bars if apply_embargo else 0)
        end = max(indices) + 1
        values = run_roll_backtest(bars, config=config, signal_start_index=start, signal_end_index=end)
        outcomes.extend(item for item in values if item.exit_time[:10] <= dates[-1])
    return outcomes


def evaluate_roll_validation_gate(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("partitions", {}).get("test", {}).get("summary", {})
    interval = summary.get("bootstrap_expected_r_interval_95") or ()
    lower = interval[0] if len(interval) else None
    checks = [
        ("test_partition_lock", report.get("test_is_locked") is True, report.get("test_is_locked"), True),
        ("oos_folds", int(report.get("oos_fold_count") or 0) >= 3, report.get("oos_fold_count"), 3),
        ("test_trades", int(summary.get("sample_count") or 0) >= 100, summary.get("sample_count"), 100),
        ("core_actions", int(report.get("core_action_count_test") or 0) >= 30, report.get("core_action_count_test"), 30),
        ("expected_r", summary.get("expected_r") is not None and float(summary["expected_r"]) >= 0.15, summary.get("expected_r"), 0.15),
        ("profit_factor", summary.get("profit_factor") is not None and float(summary["profit_factor"]) >= 1.25, summary.get("profit_factor"), 1.25),
        ("average_win_loss", summary.get("average_win_loss_ratio") is not None and float(summary["average_win_loss_ratio"]) >= 1.5, summary.get("average_win_loss_ratio"), 1.5),
        ("max_drawdown", summary.get("max_drawdown_r") is not None and float(summary["max_drawdown_r"]) <= 10.0, summary.get("max_drawdown_r"), 10.0),
        ("bootstrap_lower", lower is not None and float(lower) > 0.0, lower, 0.0),
    ]
    failed = [item[0] for item in checks if not item[1]]
    return {
        "version": ROLL_VALIDATION_VERSION,
        "status": "PASS" if not failed else "NO_GO",
        "passed": not failed,
        "failed_checks": failed,
        "checks": [{"id": item[0], "passed": item[1], "observed": item[2], "required": item[3]} for item in checks],
        "note": "Research evidence only; this gate never authorizes a wallet, exchange account or order.",
    }


def run_roll_walk_forward(
    series: Mapping[str, Sequence[RollBar]],
    *,
    config: RollValidationConfig | None = None,
) -> dict[str, Any]:
    policy = config or RollValidationConfig()
    all_dates = [bar.start_time[:10] for bars in series.values() for bar in bars]
    partitions = _date_partitions(all_dates, policy.train_ratio, policy.validation_ratio)
    report: dict[str, Any] = {
        "strategy_version": CRYPTO_ROLL_STRATEGY_VERSION,
        "validation_version": ROLL_VALIDATION_VERSION,
        "dataset_hash": stable_hash({
            key: [
                {
                    "start_time": bar.start_time,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "roll_input": bar.roll_input.to_mapping(),
                }
                for bar in value
            ]
            for key, value in sorted(series.items())
        }),
        "split_config": {key: list(value) for key, value in partitions.items()} | {"embargo_bars": policy.embargo_bars},
        "backtest_config": policy.to_mapping(),
        "partitions": {},
        "test_is_locked": True,
    }
    for name, dates in partitions.items():
        outcomes = _outcomes_for_dates(series, dates, config=policy, apply_embargo=name != "train")
        report["partitions"][name] = {"summary": summarize_roll_outcomes(outcomes, config=policy), "outcomes": [item.to_mapping() for item in outcomes]}
    oos_outcomes: list[RollOutcome] = []
    report["oos_folds"] = []
    for fold_number, fold_dates in enumerate(_rolling_oos_partitions(all_dates, policy.oos_folds), start=1):
        fold_outcomes = _outcomes_for_dates(series, fold_dates["test"], config=policy, apply_embargo=True)
        oos_outcomes.extend(fold_outcomes)
        report["oos_folds"].append({
            "fold": fold_number,
            "dates": {key: list(value) for key, value in fold_dates.items()},
            "summary": summarize_roll_outcomes(fold_outcomes, config=policy),
            "outcomes": [item.to_mapping() for item in fold_outcomes],
            "test_is_locked": True,
        })
    report["oos_fold_count"] = len(report["oos_folds"])
    report["oos_summary"] = summarize_roll_outcomes(oos_outcomes, config=policy)
    test_outcomes = report["partitions"]["test"]["outcomes"]
    report["core_action_count_test"] = sum(item["action"] in {RollAction.ROLL_BUY.value, RollAction.ROLL_ADD.value} for item in test_outcomes)
    report["validation_gate"] = evaluate_roll_validation_gate(report)
    return report


__all__ = [
    "ROLL_VALIDATION_VERSION",
    "build_roll_series_from_validation",
    "RollBar",
    "RollValidationConfig",
    "RollOutcome",
    "run_roll_backtest",
    "summarize_roll_outcomes",
    "evaluate_roll_validation_gate",
    "run_roll_walk_forward",
    "asset_group_for_roll",
]
