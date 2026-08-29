from __future__ import annotations

from kquant.today_workbench import build_today_workbench


def test_today_workbench_cannot_show_normal_buy_when_data_or_go_no_go_fails() -> None:
    result = build_today_workbench(
        run={"provider_status": "degraded", "provider_error_count": 1, "daily_candidates": {"buy_setups": [{"symbol": "NVDA"}], "watch": []}},
        market_regime={"regime": "RISK_ON", "label": "Risk On"},
        market_data={}, ai_status={"status": "available"}, operational_health={"status": "healthy"}, weekly_review={},
        production_readiness={"decision": "NO_GO", "failed_gate_count": 3},
    )
    assert result["decision"] == "NO_TRADE"
    assert result["top_candidates"][0]["symbol"] == "NVDA"
    assert result["order_submission_enabled"] is False
