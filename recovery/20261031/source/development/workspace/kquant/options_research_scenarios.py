from __future__ import annotations

import math
from typing import Any

from .options_research_features import content_hash


SCENARIO_VERSION = "options_deterministic_scenario_v0.1.0"


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def black_scholes(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    rate: float,
    dividend_yield: float,
    right: str,
) -> dict[str, float]:
    if spot <= 0 or strike <= 0 or years <= 0 or volatility <= 0:
        raise ValueError("spot, strike, years, and volatility must be positive")
    right = right.upper()
    if right not in {"CALL", "PUT"}:
        raise ValueError("right must be CALL or PUT")
    root_time = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * volatility * volatility) * years) / (volatility * root_time)
    d2 = d1 - volatility * root_time
    discount_rate = math.exp(-rate * years)
    discount_dividend = math.exp(-dividend_yield * years)
    if right == "CALL":
        price = spot * discount_dividend * _normal_cdf(d1) - strike * discount_rate * _normal_cdf(d2)
        delta = discount_dividend * _normal_cdf(d1)
        rho = strike * years * discount_rate * _normal_cdf(d2) / 100.0
        theta_year = (
            -spot * discount_dividend * _normal_pdf(d1) * volatility / (2.0 * root_time)
            - rate * strike * discount_rate * _normal_cdf(d2)
            + dividend_yield * spot * discount_dividend * _normal_cdf(d1)
        )
    else:
        price = strike * discount_rate * _normal_cdf(-d2) - spot * discount_dividend * _normal_cdf(-d1)
        delta = -discount_dividend * _normal_cdf(-d1)
        rho = -strike * years * discount_rate * _normal_cdf(-d2) / 100.0
        theta_year = (
            -spot * discount_dividend * _normal_pdf(d1) * volatility / (2.0 * root_time)
            + rate * strike * discount_rate * _normal_cdf(-d2)
            - dividend_yield * spot * discount_dividend * _normal_cdf(-d1)
        )
    gamma = discount_dividend * _normal_pdf(d1) / (spot * volatility * root_time)
    vega = spot * discount_dividend * _normal_pdf(d1) * root_time / 100.0
    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta_per_day": theta_year / 365.0,
        "vega_per_volatility_point": vega,
        "rho_per_rate_percentage_point": rho,
    }


def local_greeks_scenario_grid(feature_snapshot: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    values = feature_snapshot.get("values") or {}
    spot = values.get("underlying_spot")
    mid = values.get("mid")
    delta = values.get("delta")
    gamma = values.get("gamma")
    theta = values.get("theta_per_day")
    vega = values.get("vega_per_volatility_point")
    required = {"spot": spot, "mid": mid, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega}
    missing = sorted(name for name, value in required.items() if value is None)
    scenario = protocol["scenario_demo"]
    cases: list[dict[str, Any]] = []
    if not missing:
        for return_shock in scenario["underlying_return_shocks"]:
            for iv_points in scenario["iv_shocks_percentage_points"]:
                for days in scenario["elapsed_calendar_days"]:
                    delta_spot = float(spot) * float(return_shock)
                    delta_component = float(delta) * delta_spot
                    gamma_component = 0.5 * float(gamma) * delta_spot * delta_spot
                    vega_component = float(vega) * float(iv_points)
                    theta_component = float(theta) * float(days)
                    total_change = delta_component + gamma_component + vega_component + theta_component
                    cases.append(
                        {
                            "underlying_return_shock": return_shock,
                            "iv_shock_percentage_points": iv_points,
                            "elapsed_calendar_days": days,
                            "delta_component": delta_component,
                            "gamma_component": gamma_component,
                            "vega_component": vega_component,
                            "theta_component": theta_component,
                            "local_approximation_change": total_change,
                            "local_approximation_value": float(mid) + total_change,
                            "model": "LOCAL_GREEKS_APPROXIMATION",
                            "probability": None,
                            "executable_price": False,
                        }
                    )
    material = {
        "version": SCENARIO_VERSION,
        "feature_snapshot_id": feature_snapshot.get("snapshot_id"),
        "grid": scenario,
        "cases": cases,
    }
    return {
        "scenario_run_id": f"scenario-{content_hash(material)[:24]}",
        "scenario_version": SCENARIO_VERSION,
        "contract_id": feature_snapshot.get("entity_id"),
        "feature_snapshot_id": feature_snapshot.get("snapshot_id"),
        "status": "COMPLETE" if cases else "PARTIAL_INPUTS",
        "missing_inputs": missing,
        "cases": cases,
        "case_count": len(cases),
        "probabilities_assigned": False,
        "expected_profit_computed": False,
        "theoretical_value_is_executable_bid": False,
        "limitations": [
            "Local Greeks are a first/second-order explanation and omit cross terms and higher-order effects.",
            "No rate, dividend, American exercise, or discrete-dividend repricing is asserted for the real contract.",
            "Scenario values are deterministic sensitivities, not forecasts or executable prices.",
        ],
        "content_hash": content_hash(material),
    }


def synthetic_scenario_validation() -> dict[str, Any]:
    parameters = {
        "spot": 100.0,
        "strike": 100.0,
        "years": 30.0 / 365.0,
        "volatility": 0.25,
        "rate": 0.04,
        "dividend_yield": 0.0,
        "right": "CALL",
    }
    base = black_scholes(**parameters)
    small_spot_move = 0.01
    shifted = black_scholes(**{**parameters, "spot": parameters["spot"] + small_spot_move})
    local = base["price"] + base["delta"] * small_spot_move + 0.5 * base["gamma"] * small_spot_move**2
    parity_call = base["price"]
    put = black_scholes(**{**parameters, "right": "PUT"})
    parity_gap = parity_call - put["price"] - (
        parameters["spot"] * math.exp(-parameters["dividend_yield"] * parameters["years"])
        - parameters["strike"] * math.exp(-parameters["rate"] * parameters["years"])
    )
    checks = {
        "positive_call_price": base["price"] > 0,
        "call_delta_bounds": 0 < base["delta"] < 1,
        "positive_gamma": base["gamma"] > 0,
        "small_move_local_error_below_1e_6": abs(shifted["price"] - local) < 1e-6,
        "european_put_call_parity_below_1e_10": abs(parity_gap) < 1e-10,
    }
    return {
        "case": "SYNTHETIC_EUROPEAN_CALL_UNIT_TEST_ONLY",
        "parameters": parameters,
        "base": base,
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "not_real_market_evidence": True,
    }


__all__ = ["SCENARIO_VERSION", "black_scholes", "local_greeks_scenario_grid", "synthetic_scenario_validation"]
