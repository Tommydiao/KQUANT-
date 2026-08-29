from __future__ import annotations

from datetime import UTC, datetime

from kquant.realtime_instructions import (
    acknowledge_alert,
    evaluate_instruction_state,
    list_alerts,
    list_instructions,
    persist_instruction,
)


def _signal() -> dict:
    return {
        "symbol": "NVDA",
        "strategy_version": "swing_long_v1.1.0",
        "entry_plan": {"entry_low": 100, "entry_high": 102},
        "stop_plan": {"stop": 96},
        "target_plan": {"target_low": 112, "target_high": 115},
        "risk_reward_plan": {"risk_reward_value": 2.5},
        "hard_veto": {"active": False, "reasons": []},
        "factor_snapshot": {"factor_snapshot_hash": "factor-123"},
    }


def _snapshot(*, price: float = 101, trust: str = "live_quote", closed: bool = True) -> dict:
    return {
        "symbol": "NVDA",
        "provider_status": "available",
        "trust": trust,
        "quote_fresh": True,
        "session": "regular",
        "buy_actions_allowed_by_data": True,
        "quote": {"last": price, "bid": price - 0.05, "ask": price + 0.05, "quote_time": "2026-08-08T14:00:00+00:00"},
        "candles_5m": [{"close": 100.5, "bar_state": "closed_candle" if closed else "forming_candle"}],
    }


def test_closed_five_minute_and_live_bbo_can_trigger_manual_review() -> None:
    result = evaluate_instruction_state(_signal(), _snapshot(), datetime(2026, 8, 8, 14, tzinfo=UTC))
    assert result["state"] == "TRIGGERED"
    assert result["action"] == "BUY_REVIEW"
    assert result["evidence"]["data_eligible"] is True
    assert result["order_submission_enabled"] is False


def test_stale_or_forming_market_data_cannot_trigger() -> None:
    stale = evaluate_instruction_state(_signal(), _snapshot(trust="stale_longbridge_cache"))
    forming = evaluate_instruction_state(_signal(), _snapshot(closed=False))
    assert stale["state"] == "INVALIDATED"
    assert stale["action"] == "DO_NOT_ENTER"
    assert forming["state"] == "READY"
    assert forming["action"] == "PREPARE_REVIEW"
    assert forming["evidence"]["blockers"]


def test_material_state_is_deduplicated_and_alert_can_be_acknowledged(tmp_path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    instruction = evaluate_instruction_state(_signal(), _snapshot())
    first = persist_instruction(db_path, instruction)
    second = persist_instruction(db_path, instruction)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    stored = list_instructions(db_path)
    alerts = list_alerts(db_path)
    assert len(stored["instructions"]) == 1
    assert len(alerts["alerts"]) == 1
    acknowledged = acknowledge_alert(db_path, alerts["alerts"][0]["alert_id"])
    assert acknowledged["acknowledged_at"]

