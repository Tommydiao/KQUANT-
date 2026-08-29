from __future__ import annotations

import random
from dataclasses import dataclass
import re
from typing import Any, Mapping, Sequence

from .factor_engine import FactorMarketInput, OHLCVBar, compute_factor_value_series
from .factor_registry import FactorRegistry, score_registered_factors


@dataclass(frozen=True)
class BacktestBar:
    start_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float

    def as_factor_bar(self) -> OHLCVBar:
        return OHLCVBar(close=self.close, high=self.high, low=self.low, volume=self.volume)


@dataclass(frozen=True)
class BacktestConfig:
    setup_threshold: float = 60.0
    stop_atr_multiple: float = 1.5
    target_r_multiple: float = 2.0
    max_hold_bars: int = 24
    fee_bps_per_side: float = 1.0
    slippage_bps_per_side: float = 5.0
    min_history_bars: int = 55

    @property
    def cost_rate_per_side(self) -> float:
        return (self.fee_bps_per_side + self.slippage_bps_per_side) / 10000.0


def bars_for_duration(interval: str, *, hours: int = 24) -> int:
    """Convert a wall-clock holding window into closed-bar count."""

    value = str(interval).strip().lower()
    match = re.fullmatch(r"(\d+)([mhd])", value)
    if match is None:
        raise ValueError(f"Unsupported bar interval: {interval}")
    amount = int(match.group(1))
    unit = match.group(2)
    minutes = amount if unit == "m" else amount * 60 if unit == "h" else amount * 1440
    return max(1, int(round(hours * 60 / minutes)))


@dataclass(frozen=True)
class TradeOutcome:
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    realized_r: float
    exit_reason: str
    setup_score: float
    factor_ids: tuple[str, ...]
    asset_id: str | None = None
    symbol: str | None = None
    # Point-in-time inputs at the signal bar.  Keeping these with the outcome
    # lets model benchmarks use only information available before entry.
    factor_values: tuple[tuple[str, float | None], ...] = ()

    @property
    def win(self) -> bool:
        return self.realized_r > 0

    @property
    def factor_map(self) -> dict[str, float | None]:
        return dict(self.factor_values)


def _atr(bars: Sequence[BacktestBar], index: int, period: int = 14) -> float | None:
    if index < period:
        return None
    true_ranges: list[float] = []
    for position in range(index - period + 1, index + 1):
        previous_close = bars[position - 1].close
        current = bars[position]
        true_ranges.append(max(current.high - current.low, abs(current.high - previous_close), abs(current.low - previous_close)))
    return sum(true_ranges) / period


def _atr_series(bars: Sequence[BacktestBar], period: int = 14) -> list[float | None]:
    values: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return values
    true_ranges = [0.0] * len(bars)
    for index in range(1, len(bars)):
        previous_close = bars[index - 1].close
        current = bars[index]
        true_ranges[index] = max(current.high - current.low, abs(current.high - previous_close), abs(current.low - previous_close))
    running = sum(true_ranges[1 : period + 1])
    values[period] = running / period
    for index in range(period + 1, len(bars)):
        running += true_ranges[index] - true_ranges[index - period]
        values[index] = running / period
    return values


def _fill_buy(price: float, cost_rate: float) -> float:
    return price * (1.0 + cost_rate)


def _fill_sell(price: float, cost_rate: float) -> float:
    return price * (1.0 - cost_rate)


def _exit_trade(
    bars: Sequence[BacktestBar],
    *,
    entry_index: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
    config: BacktestConfig,
) -> tuple[int, float, str]:
    cost = config.cost_rate_per_side
    final_index = min(len(bars) - 1, entry_index + max(1, config.max_hold_bars) - 1)
    for index in range(entry_index, final_index + 1):
        bar = bars[index]
        if bar.open <= stop_price:
            return index, _fill_sell(bar.open, cost), "gap_stop"
        if bar.open >= target_price:
            return index, _fill_sell(bar.open, cost), "gap_target"
        hit_stop = bar.low <= stop_price
        hit_target = bar.high >= target_price
        if hit_stop:
            return index, _fill_sell(stop_price, cost), "stop_first" if hit_target else "stop"
        if hit_target:
            return index, _fill_sell(target_price, cost), "target"
    return final_index, _fill_sell(bars[final_index].close, cost), "time_exit"


def run_early_start_backtest(
    registry: FactorRegistry,
    bars: Sequence[BacktestBar],
    *,
    benchmark_bars: Mapping[str, Sequence[BacktestBar]] | None = None,
    weights: dict[str, float],
    config: BacktestConfig | None = None,
    derivative_series: Sequence[Mapping[str, float | None]] | None = None,
    signal_start_index: int | None = None,
    signal_end_index: int | None = None,
    asset_id: str | None = None,
    symbol: str | None = None,
) -> list[TradeOutcome]:
    """Replay the deterministic setup policy without looking beyond a signal bar."""

    policy = config or BacktestConfig()
    if len(bars) < policy.min_history_bars + 2:
        return []
    factor_bars = tuple(item.as_factor_bar() for item in bars)
    factor_benchmarks = {
        name: tuple(item.as_factor_bar() for item in value)
        for name, value in (benchmark_bars or {}).items()
    }
    data = FactorMarketInput(
        bars=factor_bars,
        benchmark_bars=factor_benchmarks,
        derivative_series=tuple(derivative_series or ()),
    )
    factor_series = compute_factor_value_series(data)
    atr_series = _atr_series(bars)
    outcomes: list[TradeOutcome] = []
    next_available_signal = policy.min_history_bars
    signal_index = max(policy.min_history_bars, signal_start_index or policy.min_history_bars)
    end_index = min(len(bars) - 1, signal_end_index if signal_end_index is not None else len(bars) - 1)
    while signal_index < end_index:
        if signal_index < next_available_signal:
            signal_index += 1
            continue
        values = factor_series[signal_index]
        scored = score_registered_factors(registry, values, weights)
        if scored["missing_factor_ids"] or float(scored["score"]) < policy.setup_threshold:
            signal_index += 1
            continue
        atr = atr_series[signal_index]
        if atr is None or atr <= 0:
            signal_index += 1
            continue
        next_index = signal_index + 1
        raw_entry = bars[next_index].open
        entry_price = _fill_buy(raw_entry, policy.cost_rate_per_side)
        stop_price = bars[signal_index].close - policy.stop_atr_multiple * atr
        risk = entry_price - stop_price
        if risk <= 0:
            signal_index += 1
            continue
        target_price = entry_price + policy.target_r_multiple * risk
        exit_index, exit_price, reason = _exit_trade(
            bars,
            entry_index=next_index,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            config=policy,
        )
        outcomes.append(TradeOutcome(
            signal_time=bars[signal_index].start_time,
            entry_time=bars[next_index].start_time,
            exit_time=bars[exit_index].start_time,
            entry_price=entry_price,
            exit_price=exit_price,
            stop_price=stop_price,
            target_price=target_price,
            realized_r=(exit_price - entry_price) / risk,
            exit_reason=reason,
            setup_score=float(scored["score"]),
            factor_ids=tuple(sorted(weights)),
            asset_id=asset_id,
            symbol=symbol,
            factor_values=tuple(
                sorted(
                    (key, None if value is None else float(value))
                    for key, value in values.items()
                )
            ),
        ))
        next_available_signal = exit_index + 1
        signal_index = next_available_signal
    return outcomes


def _wilson_interval(successes: int, samples: int, z: float = 1.959963984540054) -> tuple[float, float] | None:
    if samples <= 0:
        return None
    proportion = successes / samples
    denominator = 1.0 + z * z / samples
    centre = (proportion + z * z / (2.0 * samples)) / denominator
    margin = z * ((proportion * (1.0 - proportion) / samples + z * z / (4.0 * samples * samples)) ** 0.5) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _bootstrap_mean_interval(values: Sequence[float], *, iterations: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    samples = tuple(float(value) for value in values)
    means = []
    for _ in range(max(100, iterations)):
        means.append(sum(rng.choice(samples) for _ in samples) / len(samples))
    means.sort()
    low = means[int(0.025 * (len(means) - 1))]
    high = means[int(0.975 * (len(means) - 1))]
    return (low, high)


def summarize_outcomes(
    outcomes: Sequence[TradeOutcome],
    *,
    bootstrap_iterations: int = 1000,
    bootstrap_seed: int = 7,
    _include_breakdown: bool = True,
) -> dict[str, Any]:
    values = [item.realized_r for item in outcomes]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    sample_count = len(values)
    status = "insufficient" if sample_count < 30 else "limited" if sample_count < 100 else "robust"
    by_symbol: dict[str, dict[str, Any]] = {}
    if _include_breakdown:
        symbols = sorted({item.symbol for item in outcomes if item.symbol})
        for symbol in symbols:
            by_symbol[symbol] = summarize_outcomes(
                [item for item in outcomes if item.symbol == symbol],
                bootstrap_iterations=bootstrap_iterations,
                bootstrap_seed=bootstrap_seed,
                _include_breakdown=False,
            )
    return {
        "sample_count": sample_count,
        "evidence_status": status,
        "win_rate": len(wins) / sample_count if sample_count else None,
        "win_rate_interval_95": _wilson_interval(len(wins), sample_count),
        "average_r": sum(values) / sample_count if sample_count else None,
        "average_win_r": sum(wins) / len(wins) if wins else None,
        "average_loss_r": sum(losses) / len(losses) if losses else None,
        "expected_r": sum(values) / sample_count if sample_count else None,
        "bootstrap_expected_r_interval_95": _bootstrap_mean_interval(
            values,
            iterations=bootstrap_iterations,
            seed=bootstrap_seed,
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "max_drawdown_r": abs(max_drawdown),
        "target_first_rate": sum(item.exit_reason in {"target", "gap_target"} for item in outcomes) / sample_count if sample_count else None,
        "stop_first_rate": sum(item.exit_reason in {"stop", "stop_first", "gap_stop"} for item in outcomes) / sample_count if sample_count else None,
        "by_symbol": by_symbol,
    }


@dataclass(frozen=True)
class TimeSplit:
    train: tuple[int, ...]
    validation: tuple[int, ...]
    test: tuple[int, ...]
    embargoed: tuple[int, ...]


def date_split(timestamps: Sequence[str], *, embargo_bars: int = 0) -> TimeSplit:
    """Split by unique calendar dates, never by shuffled trade rows."""

    if not timestamps:
        return TimeSplit((), (), (), ())
    dates: list[str] = []
    for timestamp in timestamps:
        date = timestamp[:10]
        if not dates or dates[-1] != date:
            dates.append(date)
    train_end = max(1, int(len(dates) * 0.60))
    validation_end = max(train_end + 1, int(len(dates) * 0.80))
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:validation_end])
    test_dates = set(dates[validation_end:])
    train = tuple(index for index, timestamp in enumerate(timestamps) if timestamp[:10] in train_dates)
    validation = tuple(index for index, timestamp in enumerate(timestamps) if timestamp[:10] in validation_dates)
    test = tuple(index for index, timestamp in enumerate(timestamps) if timestamp[:10] in test_dates)
    embargoed = tuple(index for index in range(max(0, train_end and train[-1] + 1 - embargo_bars), min(len(timestamps), train[-1] + 1 + embargo_bars)) if index not in train)
    return TimeSplit(train, validation, test, embargoed)
