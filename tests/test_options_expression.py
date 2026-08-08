from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from kquant.options_expression import record_option_paper_observation, screen_option_contract
from kquant.stock_store import connect


def _snapshot(direction: str = "CALL") -> dict:
    expiry = (date.today() + timedelta(days=28)).isoformat()
    return {
        "contract_symbol": "NVDA260905C00100000",
        "underlying_symbol": "NVDA",
        "expiry_date": expiry,
        "strike_price": 100,
        "direction": direction,
        "is_standard": True,
        "contract_multiplier": 100,
        "bid": 5.00,
        "ask": 5.20,
        "mid": 5.10,
        "spread_pct": 3.92,
        "delta": 0.52 if direction == "CALL" else -0.52,
        "open_interest": 1200,
        "volume": 250,
        "provider_status": "available",
        "depth_status": "available",
        "quote_time": datetime.now(UTC).isoformat(),
    }


def test_long_call_screen_requires_triggered_underlying_and_event_calendar() -> None:
    eligible = screen_option_contract(
        _snapshot(), underlying_price=101, instruction_state="TRIGGERED", event_calendar_ready=True
    )
    blocked = screen_option_contract(
        _snapshot(), underlying_price=101, instruction_state="READY", event_calendar_ready=False
    )
    assert eligible["status"] == "eligible"
    assert eligible["max_loss"] == 520
    assert eligible["breakeven"] == 105.2
    assert blocked["status"] == "blocked"
    assert len(blocked["blockers"]) == 2


def test_long_put_remains_paper_research_only() -> None:
    result = screen_option_contract(
        _snapshot("PUT"), underlying_price=101, instruction_state="MONITORING", event_calendar_ready=True
    )
    assert result["status"] == "paper_only"


def test_one_contract_paper_observation_uses_ask_and_real_bbo(tmp_path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    now = datetime.now(UTC).isoformat()
    snapshot = _snapshot()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO option_expression_candidates(
              candidate_id, instruction_id, contract_symbol, underlying_symbol, expression_type,
              status, score, max_loss, breakeven, rationale_json, snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("candidate-1", "instruction-1", snapshot["contract_symbol"], "NVDA", "LONG_CALL",
             "eligible", 90, 520, 105.2, "{}", json.dumps(snapshot), now, now),
        )
        conn.commit()
    opened = record_option_paper_observation(
        db_path, {"action": "open", "candidate_id": "candidate-1", "underlying_price": 101}
    )
    assert opened["contracts"] == 1
    assert opened["entry_price"] == 5.2
    assert opened["max_loss"] == 520
    closed = record_option_paper_observation(
        db_path,
        {"action": "close", "observation_id": opened["observation_id"], "underlying_price": 104, "exit_price": 6.2},
    )
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] == pytest.approx(100)

