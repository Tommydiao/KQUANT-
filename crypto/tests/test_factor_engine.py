from __future__ import annotations

from kquant_crypto.factor_engine import FactorMarketInput, OHLCVBar, compute_and_score, compute_factor_value_series, compute_factor_values
from kquant_crypto.factor_registry import FactorRegistry


def _bars(count: int = 70) -> tuple[OHLCVBar, ...]:
    return tuple(
        OHLCVBar(close=100 + index * 0.7, high=101 + index * 0.7, low=99 + index * 0.7, volume=1000 + index * 10)
        for index in range(count)
    )


def test_factor_engine_is_point_in_time_and_future_perturbation_safe():
    prefix = _bars(60)
    future = tuple(OHLCVBar(close=5000, high=5100, low=4900, volume=1) for _ in range(10))
    data = FactorMarketInput(bars=prefix + future, benchmark_bars={"BTC": prefix, "ETH": prefix})
    before = compute_factor_values(data, as_of_index=59)
    after = compute_factor_values(data, as_of_index=69)
    assert before["trend_ema_reclaim"] == 1.0
    assert before["breakout_distance"] == compute_factor_values(FactorMarketInput(bars=prefix, benchmark_bars={"BTC": prefix, "ETH": prefix}))["breakout_distance"]
    assert after["breakout_distance"] != before["breakout_distance"]


def test_factor_engine_exposes_missing_registered_inputs(settings):
    registry = FactorRegistry(settings.db_path)
    result = compute_and_score(
        registry,
        FactorMarketInput(bars=_bars(20), benchmark_bars={}),
        weights={"trend_ema_reclaim": 20.0, "relative_strength_btc": 20.0},
    )
    assert "relative_strength_btc" in result["missing_factor_ids"]
    assert result["factor_version"] == "crypto_factor_v1.0.1"


def test_factor_series_matches_point_in_time_snapshots():
    bars = _bars(80)
    data = FactorMarketInput(bars=bars, benchmark_bars={"BTC": bars, "ETH": bars})
    series = compute_factor_value_series(data)
    for index in (0, 19, 24, 55, 79):
        assert series[index] == compute_factor_values(data, as_of_index=index)


def test_derivative_series_is_point_in_time_and_does_not_leak_future_values():
    bars = _bars(80)
    derivative = tuple(
        {"funding_rate": 0.0001} if index < 79 else {"funding_rate": 0.02}
        for index in range(80)
    )
    data = FactorMarketInput(
        bars=bars,
        benchmark_bars={"BTC": bars, "ETH": bars},
        derivative_series=derivative,
    )

    before = compute_factor_values(data, as_of_index=55)
    after = compute_factor_values(data, as_of_index=79)

    assert before["funding_extreme"] == 1.0
    assert after["funding_extreme"] == 0.0
