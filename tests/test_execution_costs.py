from __future__ import annotations

from kquant.execution_costs import execution_cost_parameters
from kquant.strategy_validation import evaluate_long_trade_scenarios


def _candles() -> list[dict]:
    return [
        {"open_time": "2026-01-01T14:30:00+00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
        {"open_time": "2026-01-02T14:30:00+00:00", "open": 101.0, "high": 105.0, "low": 100.0, "close": 104.0},
        {"open_time": "2026-01-03T14:30:00+00:00", "open": 104.0, "high": 106.0, "low": 102.0, "close": 105.0},
    ]


def test_low_liquidity_and_low_price_raise_slippage() -> None:
    liquid = execution_cost_parameters(scenario="baseline", price=100.0, average_dollar_volume=50_000_000)
    illiquid_low_price = execution_cost_parameters(scenario="baseline", price=5.0, average_dollar_volume=1_000_000)

    assert liquid["liquidity_bucket"] == "liquid"
    assert illiquid_low_price["liquidity_bucket"] == "low_liquidity"
    assert illiquid_low_price["slippage_bps_per_side"] > liquid["slippage_bps_per_side"]


def test_execution_scenarios_include_optimistic_baseline_and_conservative() -> None:
    results = evaluate_long_trade_scenarios(
        _candles(), 0, stop_price=98.0, target_price=104.0, horizon_bars=2, average_dollar_volume=1_000_000
    )

    assert list(results) == ["optimistic", "baseline", "conservative"]
    assert results["conservative"]["execution_costs"]["slippage_bps_per_side"] > results["optimistic"]["execution_costs"]["slippage_bps_per_side"]
    assert results["baseline"]["completed"] is True
