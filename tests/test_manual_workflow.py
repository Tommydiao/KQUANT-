from __future__ import annotations

from pathlib import Path

from kquant.decision_ledger import (
    create_decision_ledger_entry,
    record_manual_trade_journal,
    weekly_personal_review,
)
from kquant.manual_workflow import build_daily_candidate_board, build_manual_trade_plan, calculate_manual_position_size


def _signal(symbol: str, level: str, score: float, veto: bool = False) -> dict:
    return {
        "symbol": symbol,
        "level": level,
        "score": score,
        "hard_veto": {"active": veto, "reasons": ["stale"] if veto else []},
        "data_status": {"data_quality": "clean"},
        "historical_edge": {"focus_win_rate": 60, "focus_avg_return": 1},
        "trade_conclusion": {"action": "BUY"},
        "trade_risk_assessment": {"status": "clear", "warnings": [], "hard_vetoes": []},
        "stop_plan": {"stop": 95, "basis": "ATR", "invalidation": ["stop"]},
        "entry_plan": {"zone": "100 - 101", "entry_low": 100, "entry_high": 101, "trigger": "reclaim"},
        "target_plan": {"target_low": 110, "target_high": 115},
        "risk_reward_plan": {"risk_reward": "2.0R", "risk_reward_value": 2},
        "features": {"close": 100},
        "holding_period": "1W",
    }


def test_candidate_limits_plan_and_local_position_calculator() -> None:
    board = build_daily_candidate_board([_signal(f"B{index}", "BUY SETUP", 90 - index) for index in range(5)] + [_signal("BLOCKED", "BUY SETUP", 99, True)])
    assert len(board["buy_setups"]) == 3
    plan = build_manual_trade_plan(_signal("NVDA", "BUY SETUP", 90))
    assert plan["target_two"] == 115
    size = calculate_manual_position_size(account_value=10_000, risk_per_trade_pct=1, entry_price=100, stop_price=95, max_total_risk_pct=2)
    assert size["max_shares"] == 20
    assert size["no_order_submission"] is True


def test_ledger_journal_and_weekly_review_are_manual_only(tmp_path: Path) -> None:
    db = tmp_path / "ledger.sqlite3"
    entry = create_decision_ledger_entry(
        {
            "signal_id": "signal-1", "symbol": "NVDA", "strategy_version": "swing_long_v1.1.0",
            "data_snapshot": {"source": "longbridge"}, "system_decision": {"action": "BUY"},
            "user_decision": "take", "entry_plan": {"entry": 100}, "veto_status": "clear",
            "final_execution": "manual_execution_reported", "outcome": "target", "outcome_r": 2,
            "error_owner": "normal_strategy_loss", "lesson": "follow plan",
        },
        db,
    )
    journal = record_manual_trade_journal({"ledger_id": entry["ledger_id"], "symbol": "NVDA", "stage": "pre_trade", "reason": "setup", "plan_followed": True}, db)
    assert journal["no_order_submission"] is True
    review = weekly_personal_review(db, week_start=entry["created_at"][:10])
    assert review["signal_count"] == 1
    assert review["manual_execution_reported_count"] == 1
