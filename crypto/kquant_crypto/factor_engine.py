from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .factor_registry import FactorRegistry, score_registered_factors


@dataclass(frozen=True)
class OHLCVBar:
    close: float
    high: float
    low: float
    volume: float


@dataclass(frozen=True)
class FactorMarketInput:
    bars: tuple[OHLCVBar, ...]
    benchmark_bars: Mapping[str, tuple[OHLCVBar, ...]]
    derivative_series: Sequence[Mapping[str, float | None]] = ()
    cvd: float | None = None
    buy_volume: float | None = None
    sell_volume: float | None = None
    oi_change: float | None = None
    funding_rate: float | None = None
    spread_bps: float | None = None


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    result = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for value in values[period:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _ema_series(values: Sequence[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < period:
        return output
    current = sum(values[:period]) / period
    output[period - 1] = current
    alpha = 2.0 / (period + 1)
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        output[index] = current
    return output


def _return(values: Sequence[float], lookback: int) -> float | None:
    if len(values) <= lookback or values[-1 - lookback] == 0:
        return None
    return values[-1] / values[-1 - lookback] - 1.0


def _atr(bars: Sequence[OHLCVBar], period: int) -> float | None:
    if len(bars) <= period:
        return None
    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        previous_close = bars[index - 1].close
        bar = bars[index]
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return sum(true_ranges[-period:]) / period


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _atr_series(bars: Sequence[OHLCVBar], period: int) -> list[float | None]:
    """Build the same trailing ATR values as ``_atr`` in one pass."""

    values: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return values
    true_ranges = [0.0] * len(bars)
    for index in range(1, len(bars)):
        previous_close = bars[index - 1].close
        current = bars[index]
        true_ranges[index] = max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        )
    running = sum(true_ranges[1 : period + 1])
    values[period] = running / period
    for index in range(period + 1, len(bars)):
        running += true_ranges[index] - true_ranges[index - period]
        values[index] = running / period
    return values


def _indexed_return(values: Sequence[float], index: int, lookback: int) -> float | None:
    if index <= lookback or values[index - lookback] == 0:
        return None
    return values[index] / values[index - lookback] - 1.0


def compute_factor_value_series(data: FactorMarketInput) -> tuple[dict[str, float | None], ...]:
    """Compute every point-in-time factor snapshot in linear time.

    The live runtime normally needs one snapshot, while historical replay
    needs one at every signal bar. Keeping this prefix calculation here makes
    both paths use the same formulas without recomputing all EMAs and ATRs for
    every historical index.
    """

    bars = tuple(data.bars)
    if not bars:
        return ()
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    ema9_series = _ema_series(closes, 9)
    ema20_series = _ema_series(closes, 20)
    atr14 = _atr_series(bars, 14)
    atr50 = _atr_series(bars, 50)
    volume_prefix = [0.0]
    for volume in volumes:
        volume_prefix.append(volume_prefix[-1] + volume)
    benchmark_closes = {
        name.upper(): [bar.close for bar in values]
        for name, values in (data.benchmark_bars or {}).items()
    }
    cvd_bias = _safe_ratio(data.cvd, abs(data.buy_volume or 0.0) + abs(data.sell_volume or 0.0))
    snapshots: list[dict[str, float | None]] = []
    for index, close in enumerate(closes):
        derivative = data.derivative_series[index] if index < len(data.derivative_series) else {}
        point_cvd = derivative.get("cvd_bias", cvd_bias)
        point_oi_change = derivative.get("oi_change", data.oi_change)
        point_funding_rate = derivative.get("funding_rate", data.funding_rate)
        point_spread_bps = derivative.get("spread_bps", data.spread_bps)
        ema9 = ema9_series[index]
        ema20 = ema20_series[index]
        previous_ema20 = ema20_series[index - 5] if index >= 5 else None
        price_return_5 = _indexed_return(closes, index, 5)
        price_return_6 = _indexed_return(closes, index, 6)
        price_return_24 = _indexed_return(closes, index, 24)
        slope_ratio = _safe_ratio(ema20, previous_ema20)
        volume_acceleration: float | None = None
        if index >= 24:
            recent = (volume_prefix[index + 1] - volume_prefix[index - 4]) / 5.0
            baseline = (volume_prefix[index - 4] - volume_prefix[index - 24]) / 20.0
            relative_volume = _safe_ratio(recent, baseline)
            volume_acceleration = None if relative_volume is None else relative_volume - 1.0
        values: dict[str, float | None] = {
            "trend_ema_reclaim": None if ema9 is None or ema20 is None else float(close > ema20 and ema9 > ema20),
            "trend_ema_slope": None if slope_ratio is None else slope_ratio - 1.0,
            "relative_strength_btc": None,
            "relative_strength_eth": None,
            "momentum_acceleration": None if price_return_6 is None or price_return_24 is None else price_return_6 - price_return_24,
            "volume_acceleration": volume_acceleration,
            "cvd_bias": point_cvd,
            "volatility_compression": _safe_ratio(atr14[index], atr50[index]),
            "oi_price_alignment": None if point_oi_change is None or price_return_24 is None else float((price_return_24 >= 0) == (point_oi_change >= 0)),
            "funding_extreme": None if point_funding_rate is None else float(abs(point_funding_rate) <= 0.0005),
            "liquidity_spread": None if point_spread_bps is None else float(point_spread_bps <= 20.0),
            "breakout_distance": None if index < 19 else _safe_ratio(close, max(bar.high for bar in bars[index - 19 : index + 1])) - 1.0,
        }
        for benchmark_name, factor_id in (("BTC", "relative_strength_btc"), ("ETH", "relative_strength_eth")):
            benchmark = benchmark_closes.get(benchmark_name)
            if benchmark:
                benchmark_index = min(len(benchmark), index + 1) - 1
                if benchmark_index >= 5 and price_return_5 is not None:
                    benchmark_return = _indexed_return(benchmark, benchmark_index, 5)
                    if benchmark_return is not None:
                        values[factor_id] = price_return_5 - benchmark_return
        snapshots.append(values)
    return tuple(snapshots)


def compute_factor_values(data: FactorMarketInput, *, as_of_index: int | None = None) -> dict[str, float | None]:
    """Compute registered factor inputs using only bars through ``as_of_index``."""

    if as_of_index is None:
        as_of_index = len(data.bars) - 1
    if as_of_index < 0:
        return {}
    bars = tuple(data.bars[: as_of_index + 1])
    if not bars:
        return {}
    prefix = FactorMarketInput(
        bars=bars,
        benchmark_bars=data.benchmark_bars,
        derivative_series=tuple(data.derivative_series[: as_of_index + 1]),
        cvd=data.cvd,
        buy_volume=data.buy_volume,
        sell_volume=data.sell_volume,
        oi_change=data.oi_change,
        funding_rate=data.funding_rate,
        spread_bps=data.spread_bps,
    )
    return dict(compute_factor_value_series(prefix)[-1])


def compute_and_score(
    registry: FactorRegistry,
    data: FactorMarketInput,
    *,
    weights: dict[str, float],
    as_of_index: int | None = None,
) -> dict[str, Any]:
    values = compute_factor_values(data, as_of_index=as_of_index)
    score = score_registered_factors(registry, values, weights)
    return {"values": values, **score}
