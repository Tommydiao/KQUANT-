from __future__ import annotations

from kquant.hard_veto import evaluate_hard_veto
from kquant.stock_signals import build_trade_conclusion


def _signal() -> dict:
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
        "historical_edge": {"sample_count": 20, "focus_win_rate": 60.0, "focus_avg_return": 1.0},
        "features": {"extension_pct": 2.0},
        "risk_reward_plan": {"risk_reward_value": 2.2},
        "exit_risk": {"status": "CLEAR"},
        "readiness_gate": {"ready": True, "status": "READY_FOR_MANUAL_REVIEW"},
        "profile_name": "swing_long_v1",
        "strategy_label": "1W Tactical",
        "level": "BUY SETUP",
    }


def test_hard_veto_requires_all_data_market_risk_and_evidence_checks() -> None:
    clean = evaluate_hard_veto(_signal(), {"regime": "RISK_ON"})
    blocked_signal = _signal()
    blocked_signal["data_status"]["data_quality"] = "caution"
    blocked_signal["trade_risk_assessment"] = {"hard_vetoes": ["invalid_stop"]}
    blocked_signal["features"]["extension_pct"] = 7.0
    blocked = evaluate_hard_veto(blocked_signal, {"regime": "RISK_OFF"})

    assert clean["active"] is False
    assert blocked["active"] is True
    assert {"data_quality_not_clean", "invalid_stop", "extension_too_high", "market_regime_risk_off"}.issubset(blocked["reasons"])


def test_hard_veto_forces_wait_conclusion() -> None:
    signal = _signal()
    signal["hard_veto"] = {"active": True, "reasons": ["invalid_stop"]}

    conclusion = build_trade_conclusion(signal, {"regime": "RISK_ON"})

    assert conclusion["action"] == "WAIT"
    assert conclusion["confidence"] == "LOW"
    assert any("Hard veto: invalid_stop." == item for item in conclusion["blockers"])
