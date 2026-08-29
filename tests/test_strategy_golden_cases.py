from __future__ import annotations

from copy import deepcopy

import pytest

from kquant.hard_veto import evaluate_hard_veto
from kquant.stock_signals import build_trade_conclusion


def _base_signal() -> dict:
    return {
        "data_status": {
            "data_quality": "clean",
            "daily_provider_status": "available",
            "hourly_provider_status": "available",
            "longbridge_required_for_buy": True,
            "longbridge_live_data_clean": True,
            "session": "regular",
        },
        "trade_risk_assessment": {"hard_vetoes": []},
        "historical_edge": {"sample_count": 30, "focus_win_rate": 60.0, "focus_avg_return": 1.0},
        "features": {"extension_pct": 2.0},
        "risk_reward_plan": {"risk_reward_value": 2.2},
        "exit_risk": {"status": "CLEAR"},
        "readiness_gate": {"ready": True, "status": "READY_FOR_MANUAL_REVIEW"},
        "profile_name": "swing_long_v1",
        "strategy_label": "1W Tactical",
        "level": "BUY SETUP",
    }


GOLDEN_CASES = [
    ("ideal_trend", {}, "RISK_ON", False, "BUY"),
    ("normal_watch", {"level": "WATCH"}, "RISK_ON", False, "WAIT"),
    ("normal_pass", {"level": "PASS"}, "RISK_ON", False, "DO_NOT_BUY"),
    ("false_breakout_watch", {"level": "WATCH", "features.extension_pct": 4.0}, "MIXED", False, "WAIT"),
    ("overextended", {"features.extension_pct": 6.0}, "RISK_ON", True, "WAIT"),
    ("large_gap_warning", {"trade_risk_assessment.hard_vetoes": ["elevated_gap_risk"]}, "RISK_ON", True, "WAIT"),
    ("daily_data_missing", {"data_status.data_quality": "caution"}, "RISK_ON", True, "WAIT"),
    ("provider_failed", {"data_status.daily_provider_status": "unavailable"}, "RISK_ON", True, "WAIT"),
    ("hourly_provider_failed", {"data_status.hourly_provider_status": "unavailable"}, "RISK_ON", True, "WAIT"),
    ("yahoo_fallback", {"data_status.longbridge_live_data_clean": False}, "RISK_ON", True, "WAIT"),
    ("pre_market", {"data_status.session": "pre_market"}, "RISK_ON", True, "WAIT"),
    ("after_hours", {"data_status.session": "after_hours"}, "RISK_ON", True, "WAIT"),
    ("risk_off", {}, "RISK_OFF", True, "WAIT"),
    ("market_data_caution", {}, "DATA_CAUTION", True, "WAIT"),
    ("invalid_stop", {"trade_risk_assessment.hard_vetoes": ["invalid_stop"]}, "RISK_ON", True, "WAIT"),
    ("low_risk_reward", {"risk_reward_plan.risk_reward_value": 1.4}, "RISK_ON", True, "WAIT"),
    ("low_liquidity", {"trade_risk_assessment.hard_vetoes": ["insufficient_liquidity"]}, "RISK_ON", True, "WAIT"),
    ("insufficient_evidence", {"historical_edge.sample_count": 4}, "RISK_ON", True, "WAIT"),
    ("stale_data", {"data_status.data_quality": "caution", "trade_risk_assessment.hard_vetoes": ["stale_market_data"]}, "RISK_ON", True, "WAIT"),
    ("multiple_blockers", {"features.extension_pct": 8.0, "data_status.session": "closed", "historical_edge.sample_count": 0}, "RISK_OFF", True, "WAIT"),
]


def _set_path(payload: dict, path: str, value: object) -> None:
    target = payload
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


@pytest.mark.parametrize("name, changes, regime, veto_active, action", GOLDEN_CASES, ids=[item[0] for item in GOLDEN_CASES])
def test_strategy_golden_cases(name: str, changes: dict[str, object], regime: str, veto_active: bool, action: str) -> None:
    signal = deepcopy(_base_signal())
    for path, value in changes.items():
        _set_path(signal, path, value)
    market_regime = {"regime": regime}
    signal["hard_veto"] = evaluate_hard_veto(signal, market_regime)
    conclusion = build_trade_conclusion(signal, market_regime)

    assert signal["hard_veto"]["active"] is veto_active, name
    assert conclusion["action"] == action, name
