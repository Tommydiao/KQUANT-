from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from kquant.options_expression import option_contract_snapshot, record_option_paper_observation, screen_option_contract
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


def test_option_snapshot_keeps_trade_time_separate_from_bbo_and_normalizes_greeks(monkeypatch) -> None:
    class Runtime:
        def option_quotes(self, symbols, timeout):
            return [{
                "last_done": 5.1,
                "timestamp": datetime(2026, 9, 14, 13, 40, tzinfo=UTC),
                "volume": 250,
                "option_extend": {
                    "underlying_symbol": "NVDA.US",
                    "expiry_date": "2026-09-18",
                    "direction": "C",
                    "strike_price": 100,
                    "contract_multiplier": 100,
                    "implied_volatility": 52,
                    "historical_volatility": 40,
                    "open_interest": 1200,
                },
            }]

        def calc_indexes(self, symbols, indexes, timeout):
            return [{"delta": 0.52, "gamma": 0.03, "theta": -2, "vega": 8, "rho": 1}]

        def pull_depth(self, symbol, timeout):
            return ({"bids": [{"price": 5.0, "volume": 4}], "asks": [{"price": 5.2, "volume": 3}]}, "isolated_pull")

    monkeypatch.setattr("kquant.options_expression.longbridge_runtime", lambda: Runtime())
    monkeypatch.setattr("kquant.options_expression._greek_indexes", lambda: [])

    snapshot = option_contract_snapshot("NVDA260918C100000.US")

    assert snapshot["bid_size"] == 4
    assert snapshot["ask_size"] == 3
    assert snapshot["implied_volatility"] == pytest.approx(0.52)
    assert snapshot["theta"] == pytest.approx(-0.02)
    assert snapshot["vega"] == pytest.approx(0.08)
    assert snapshot["quote_time_meaning"] == "latest_trade_time_not_bbo_time"
    assert snapshot["bbo_time_source"] == "receipt_time_only"
    assert snapshot["strict_fill_eligible"] is False
    assert snapshot["pricing_input_status"] == "rates_and_dividends_not_ingested"


def test_flat_sdk_fields_small_percent_values_and_receipt_clock(monkeypatch):
    from types import SimpleNamespace
    from kquant import options_expression as options
    clock = datetime(2026, 9, 15, 13, 40, tzinfo=UTC)
    class Runtime:
        def option_quotes(self, *args):
            return [SimpleNamespace(symbol='SPY-C', underlying_symbol='SPY.US',
                direction='OptionDirection.Call', expiry_date=date(2026,9,18), strike_price=100,
                timestamp=datetime(2026,9,15,21,40), contract_multiplier=100,
                implied_volatility=2, historical_volatility=1, volume=250, open_interest=600)]
        def calc_indexes(self,*args):
            return [{'delta':0.5,'theta':-2,'vega':8}]
        def pull_depth(self,*args):
            nonlocal clock
            clock += timedelta(seconds=2)
            return {'bids':[{'price':1,'volume':2}],'asks':[{'price':1.02,'volume':3}]},'isolated_pull'
    monkeypatch.setattr(options,'longbridge_runtime',lambda:Runtime())
    monkeypatch.setattr(options,'_greek_indexes',lambda:[])
    monkeypatch.setattr(options,'_now',lambda:clock.isoformat())
    result=options.option_contract_snapshot('SPY-C')
    assert result['underlying_symbol']=='SPY' and result['direction']=='CALL'
    assert result['strike_price']==100 and result['expiry_date']=='2026-09-18'
    assert result['implied_volatility']==0.02
    assert result['quote_time'] is None and result['quote_time_status']=='timezone_unknown'
    assert datetime.fromisoformat(result['bbo_received_at'])-datetime.fromisoformat(result['bbo_request_started_at'])==timedelta(seconds=2)
    assert result['strict_fill_eligible'] is False
