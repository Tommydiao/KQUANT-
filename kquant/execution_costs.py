from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExecutionCostScenario:
    name: str
    commission_bps_per_side: float
    base_slippage_bps_per_side: float
    low_liquidity_slippage_bps: float
    low_price_slippage_bps: float


SCENARIOS = {
    "optimistic": ExecutionCostScenario("optimistic", 0.5, 2.0, 3.0, 2.0),
    "baseline": ExecutionCostScenario("baseline", 1.0, 5.0, 8.0, 5.0),
    "conservative": ExecutionCostScenario("conservative", 1.5, 10.0, 20.0, 12.0),
}


def execution_cost_parameters(*, scenario: str, price: float, average_dollar_volume: float) -> dict[str, float | str]:
    selected = SCENARIOS.get(scenario, SCENARIOS["baseline"])
    slippage = selected.base_slippage_bps_per_side
    liquidity_bucket = "liquid"
    if average_dollar_volume < 5_000_000:
        slippage += selected.low_liquidity_slippage_bps
        liquidity_bucket = "low_liquidity"
    elif average_dollar_volume < 25_000_000:
        slippage += selected.low_liquidity_slippage_bps / 2
        liquidity_bucket = "medium_liquidity"
    if price < 10:
        slippage += selected.low_price_slippage_bps
    return {
        "scenario": selected.name,
        "commission_bps_per_side": selected.commission_bps_per_side,
        "slippage_bps_per_side": slippage,
        "price": float(price),
        "average_dollar_volume": float(average_dollar_volume),
        "liquidity_bucket": liquidity_bucket,
    }


def scenario_catalog() -> dict[str, dict[str, float | str]]:
    return {name: asdict(scenario) for name, scenario in SCENARIOS.items()}
