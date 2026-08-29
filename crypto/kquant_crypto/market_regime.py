from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REGIMES = ("RISK_ON", "ALT_EXPANSION", "BTC_DOMINANT", "DELEVERAGING", "LIQUIDITY_STRESS", "DATA_CAUTION")


@dataclass(frozen=True)
class MarketRegimeInput:
    btc_return: float | None
    eth_return: float | None
    sol_return: float | None
    alt_breadth: float | None
    funding_mean: float | None
    oi_change: float | None
    liquidation_pressure: float | None
    stablecoin_deviation: float | None
    data_ready: bool


def classify_regime(value: MarketRegimeInput) -> dict[str, Any]:
    evidence: list[str] = []
    if not value.data_ready or any(item is None for item in (value.btc_return, value.eth_return, value.alt_breadth)):
        return {"regime": "DATA_CAUTION", "confidence": "low", "evidence": ["required_market_inputs_missing"]}
    if value.stablecoin_deviation is not None and abs(value.stablecoin_deviation) >= 0.01:
        evidence.append("stablecoin_deviation")
        return {"regime": "LIQUIDITY_STRESS", "confidence": "high", "evidence": evidence}
    if (value.liquidation_pressure or 0) >= 0.7 or (value.oi_change or 0) <= -0.15:
        evidence.extend(["liquidation_pressure", "open_interest_deleveraging"])
        return {"regime": "DELEVERAGING", "confidence": "high", "evidence": evidence}
    if value.alt_breadth >= 0.6 and value.eth_return >= value.btc_return and value.sol_return is not None and value.sol_return >= value.btc_return:
        evidence.extend(["alt_breadth_expanding", "core_alt_relative_strength"])
        return {"regime": "ALT_EXPANSION", "confidence": "medium", "evidence": evidence}
    if value.btc_return >= 0 and value.eth_return < value.btc_return and value.alt_breadth < 0.5:
        evidence.extend(["btc_relative_strength", "weak_alt_breadth"])
        return {"regime": "BTC_DOMINANT", "confidence": "medium", "evidence": evidence}
    if value.btc_return >= 0 and value.eth_return >= 0 and value.alt_breadth >= 0.5:
        evidence.extend(["positive_core_returns", "healthy_breadth"])
        return {"regime": "RISK_ON", "confidence": "medium", "evidence": evidence}
    return {"regime": "DATA_CAUTION", "confidence": "low", "evidence": ["mixed_or_unconfirmed_market_state"]}
