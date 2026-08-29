from __future__ import annotations

"""Frozen contract cases for cross-project regression tests.

Stock cases intentionally describe the frozen stock strategy boundary rather
than reimplementing the stock engine inside the crypto repository.  The two
repositories can consume this same contract without sharing databases.
"""

from typing import Any


GOLDEN_CASE_VERSION = "research_golden_cases_v1.0.0"


def crypto_golden_cases() -> list[dict[str, Any]]:
    valid = {
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "asset_type": "crypto_spot",
        "instrument_id": "binance:spot:ETHUSDT",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "hard_veto": False,
        "market_state": "BULL",
        "state_probability": 0.82,
        "target_before_stop_probability": 0.72,
        "positive_return_probability": 0.70,
        "drawdown_probability": 0.18,
        "feature_snapshot_id": "golden_features_v1",
        "model_version": "crypto_bayesian_v1.0.0",
        "realized_profit": 100.0,
        "proposed_capital": 50.0,
        "probability_improvement": 0.10,
        "research_only": True,
    }
    cases: list[dict[str, Any]] = []
    for index in range(5):
        cases.append({**valid, "case_id": f"crypto_roll_buy_{index + 1:02d}", "asset_id": "asset:ETH", "current_exposure": 0.0, "expected_action": "ROLL_BUY"})
    for index in range(5):
        cases.append({**valid, "case_id": f"crypto_roll_add_{index + 1:02d}", "asset_id": "asset:ETH", "current_exposure": 80.0, "expected_action": "ROLL_ADD"})
    for index in range(3):
        cases.append({**valid, "case_id": f"crypto_rotate_{index + 1:02d}", "asset_id": "asset:SOL", "symbol": "SOL", "asset_type": "crypto_spot", "instrument_id": "binance:spot:SOLUSDT", "current_exposure": 80.0, "rotation_target": "SOL", "current_score": 0.40, "rotation_score": 0.65, "expected_action": "ROTATE_TO"})
    for index in range(3):
        cases.append({**valid, "case_id": f"crypto_reduce_{index + 1:02d}", "asset_id": "asset:ETH", "current_exposure": 80.0, "floating_pnl": -20.0, "drawdown_probability": 0.60, "expected_action": "REDUCE"})
    for index in range(2):
        cases.append({**valid, "case_id": f"crypto_hold_{index + 1:02d}", "asset_id": "asset:ETH", "current_exposure": 80.0, "floating_pnl": -20.0, "drawdown_probability": 0.20, "expected_action": "HOLD_CORE"})
    cases.append({**valid, "case_id": "crypto_blocked_stale", "source_status": "stale", "expected_action": "DATA_BLOCKED"})
    cases.append({**valid, "case_id": "crypto_blocked_missing", "missing_fields": ["mvrv"], "expected_action": "DATA_BLOCKED"})
    return cases


def stock_golden_cases() -> list[dict[str, Any]]:
    symbols = (
        "NVDA", "MSTR", "SPY", "QQQ", "RKLB", "PLTR", "COIN", "MARA", "IBIT", "BITX",
        "ETHU", "MSFT", "AMD", "AVGO", "TSLA", "CRWD", "SMCI", "APP", "HOOD", "IONQ",
    )
    return [
        {
            "case_id": f"stock_frozen_{index + 1:02d}",
            "scope": "stock",
            "symbol": symbol,
            "strategy_version": "swing_long_v1.1.0",
            "expected": "frozen_baseline_contract",
            "data_source": "longbridge_candles_only",
        }
        for index, symbol in enumerate(symbols)
    ]


def golden_case_catalog() -> dict[str, Any]:
    return {
        "version": GOLDEN_CASE_VERSION,
        "stock": stock_golden_cases(),
        "crypto": crypto_golden_cases(),
        "note": "Golden cases are regression contracts, not performance evidence.",
    }


__all__ = ["GOLDEN_CASE_VERSION", "crypto_golden_cases", "stock_golden_cases", "golden_case_catalog"]
