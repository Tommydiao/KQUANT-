from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import kquant.stock_signals as stock_signals
from kquant.market_clock import MarketClock, market_clock, session_bounds_utc
from kquant.stock_signals import (
    _parse_market_time,
    aggregate_intraday_candles,
    ai_hard_veto,
    api_stock_market_data_self_check,
    api_stock_strategy_validation,
    merge_quote_into_candles,
)
from kquant.stock_store import connect
from kquant.strategy_validation import BacktestConfig, evaluate_long_trade, summarize_outcomes, walk_forward_split


UTC = timezone.utc


def candle(open_time: datetime, price: float, *, high: float | None = None, low: float | None = None) -> dict:
    return {
        "open_time": open_time.isoformat(),
        "time": int(open_time.timestamp()),
        "open": price,
        "high": high if high is not None else price,
        "low": low if low is not None else price,
        "close": price,
        "volume": 100,
    }


def test_market_clock_handles_us_summer_and_winter_time() -> None:
    summer = market_clock(datetime(2026, 7, 9, 13, 30, tzinfo=UTC))
    assert summer.session == "regular"
    assert summer.regular_open_utc == "2026-07-09T13:30:00+00:00"
    assert summer.regular_close_utc == "2026-07-09T20:00:00+00:00"

    winter = market_clock(datetime(2026, 1, 5, 14, 30, tzinfo=UTC))
    assert winter.session == "regular"
    assert winter.regular_open_utc == "2026-01-05T14:30:00+00:00"
    assert winter.regular_close_utc == "2026-01-05T21:00:00+00:00"


def test_longbridge_naive_datetime_contract_is_utc() -> None:
    # Longbridge documents API timestamps as UTC.  A naive SDK datetime must
    # never be reinterpreted as America/New_York during summer time.
    parsed = _parse_market_time(datetime(2026, 7, 9, 13, 30))
    assert parsed is not None
    assert parsed.isoformat() == "2026-07-09T13:30:00+00:00"


def test_market_clock_handles_holiday_and_early_close() -> None:
    independence_observed = market_clock(datetime(2026, 7, 3, 15, 0, tzinfo=UTC))
    assert independence_observed.session == "closed"
    assert independence_observed.is_trading_day is False

    early_open, early_close = session_bounds_utc(date(2026, 11, 27))
    assert early_open.isoformat() == "2026-11-27T14:30:00+00:00"
    assert early_close.isoformat() == "2026-11-27T18:00:00+00:00"


def test_quote_updates_forming_minute_and_five_minute_aggregation() -> None:
    start = datetime(2026, 7, 9, 13, 30, tzinfo=UTC)
    one_minute = [candle(start + timedelta(minutes=index), 100 + index) for index in range(6)]
    quote = {
        "last": 107.5,
        "quote_time": (start + timedelta(minutes=5, seconds=40)).isoformat(),
    }
    merged = merge_quote_into_candles(one_minute, quote, "1m")
    assert merged[-1]["close"] == 107.5
    assert merged[-1]["high"] == 107.5
    assert merged[-1]["bar_state"] == "forming_candle"
    assert merged[-1]["quote_merged"] is True

    five_minute = aggregate_intraday_candles(
        merged,
        "5m",
        now=start + timedelta(minutes=5, seconds=40),
    )
    assert len(five_minute) == 2
    assert five_minute[0]["component_count"] == 5
    assert five_minute[0]["bar_state"] == "closed_candle"
    assert five_minute[1]["component_count"] == 1
    assert five_minute[1]["bar_state"] == "forming_candle"


def test_backtest_enters_next_bar_and_uses_stop_first() -> None:
    start = datetime(2026, 1, 2, tzinfo=UTC)
    candles = [
        candle(start, 100),
        candle(start + timedelta(days=1), 101, high=106, low=94),
        candle(start + timedelta(days=2), 102),
    ]
    outcome = evaluate_long_trade(
        candles,
        signal_index=0,
        stop_price=95,
        target_price=105,
        horizon_bars=2,
        config=BacktestConfig(commission_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert outcome["entry_index"] == 1
    assert outcome["entry_price"] == 101
    assert outcome["outcome"] == "same_bar_stop_first"
    assert outcome["stop_first"] is True
    assert outcome["target_first"] is False


def test_walk_forward_and_evidence_quality_do_not_overstate_small_samples() -> None:
    events = [
        {"signal_time": f"2026-01-{index + 1:02d}", "completed": True, "realized_r": 1 if index % 2 else -1}
        for index in range(10)
    ]
    split = walk_forward_split(events)
    assert [len(split[name]) for name in ("train", "validation", "test")] == [6, 2, 2]
    summary = summarize_outcomes(events)
    assert summary["sample_count"] == 10
    assert summary["evidence_quality"] == "insufficient"
    assert summary["limited_evidence"] is True


def test_regular_session_stale_longbridge_quote_hard_vetoes_buy_actions() -> None:
    signal = {
        "data_status": {
            "data_quality": "clean",
            "daily_provider_status": "available",
            "hourly_provider_status": "available",
            "daily_candles": 252,
            "hourly_candles": 35,
            "longbridge_required_for_buy": True,
            "market_session": "regular",
            "realtime_quote_provider_status": "available",
            "realtime_quote_fresh": False,
            "realtime_quote_age_seconds": 61,
        },
        "trade_conclusion": {"action": "BUY"},
        "exit_risk": {"status": "CLEAR"},
        "historical_edge": {"focus_win_rate": 55, "focus_avg_return": 1.2},
    }
    veto = ai_hard_veto(signal, {"regime": "RISK_ON"})
    assert veto["active"] is True
    assert veto["can_ai_buy"] is False
    assert any("realtime_quote=available age=61" in reason for reason in veto["reasons"])


def test_realtime_snapshot_combines_quote_and_longbridge_bars(monkeypatch) -> None:
    start = datetime(2026, 7, 9, 13, 30, tzinfo=UTC)
    clock = MarketClock(
        session="regular",
        market_date="2026-07-09",
        exchange_timezone="America/New_York",
        display_timezone="Asia/Shanghai",
        regular_open_utc=start.isoformat(),
        regular_close_utc=datetime(2026, 7, 9, 20, 0, tzinfo=UTC).isoformat(),
        is_trading_day=True,
        is_early_close=False,
    )
    monkeypatch.setattr(stock_signals, "market_clock", lambda *args, **kwargs: clock)
    monkeypatch.setattr(
        stock_signals,
        "api_stock_quote",
        lambda *args, **kwargs: {
            "symbol": "NVDA",
            "provider": "longbridge",
            "source_type": "longbridge_quote",
            "provider_status": "available",
            "last": 101.5,
            "bid": 101.4,
            "ask": 101.6,
            "depth_status": "available",
            "quote_time": (start + timedelta(minutes=1, seconds=20)).isoformat(),
            "freshness_seconds": 2,
            "session": "regular",
        },
    )
    monkeypatch.setattr(
        stock_signals,
        "api_stock_candles",
        lambda *args, **kwargs: {
            "symbol": "NVDA",
            "provider_status": "available",
            "source_type": "longbridge_candles",
            "provider_errors": [],
            "candles": [candle(start, 100)],
        },
    )
    payload = stock_signals.api_stock_realtime_snapshot("NVDA")
    assert payload["provider_status"] == "available"
    assert payload["quote_fresh"] is True
    assert payload["buy_actions_allowed_by_data"] is True
    assert payload["current_1m_bar"]["close"] == 101.5
    assert payload["current_1m_bar"]["bar_state"] == "forming_candle"
    assert payload["current_5m_bar"]["bar_state"] == "forming_candle"
    assert payload["trade_context_enabled"] is False
    assert payload["order_submission_enabled"] is False


def test_strategy_validation_persists_walk_forward_report(tmp_path: Path) -> None:
    db = tmp_path / "kquant_us.sqlite3"
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO ai_action_events(
              event_key, symbol, profile, action, signal_time, decision_price,
              entry_price, stop_price, target_price, risk_reward, market_regime,
              data_source, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "NVDA",
                "tactical_1w_v1",
                "AI_PULLBACK_BUY",
                "2026-01-02T20:00:00+00:00",
                100,
                101,
                95,
                113,
                2,
                "RISK_ON",
                "longbridge_candles",
                "{}",
                "2026-01-02T20:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_action_outcomes(
              event_key, horizon_bars, entry_time, entry_price, exit_time, exit_price,
              outcome, realized_r, max_drawdown_pct, max_runup_pct, target_first,
              stop_first, completed, evaluated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                5,
                "2026-01-05T14:30:00+00:00",
                101,
                "2026-01-08T14:30:00+00:00",
                113,
                "target",
                2,
                -1.2,
                12,
                1,
                0,
                1,
                "2026-01-09T00:00:00+00:00",
            ),
        )
        conn.commit()

    outputs = tmp_path / "outputs"
    payload = api_stock_strategy_validation(db_path=db, outputs_dir=outputs)
    assert payload["completed_event_count"] == 1
    assert payload["overall"]["average_r"] == 2
    assert payload["overall"]["evidence_quality"] == "insufficient"
    assert (outputs / "ai-action-validation.json").exists()
    assert (outputs / "ai-action-validation.md").exists()
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM strategy_validation_runs").fetchone()["count"] == 4


def test_market_data_self_check_records_local_readiness(monkeypatch, tmp_path: Path) -> None:
    clock = MarketClock(
        session="closed",
        market_date="2026-07-12",
        exchange_timezone="America/New_York",
        display_timezone="Asia/Shanghai",
        regular_open_utc=None,
        regular_close_utc=None,
        is_trading_day=False,
        is_early_close=False,
    )
    monkeypatch.setattr(stock_signals, "market_clock", lambda *args, **kwargs: clock)
    monkeypatch.setattr(
        stock_signals,
        "api_stock_market_data_status",
        lambda **kwargs: {
            "provider": "longbridge",
            "status": "available",
            "longbridge_env": "configured",
            "longbridge_sdk": "installed",
            "longbridge_market_data_only": True,
            "longbridge_account_enabled": False,
            "longbridge_trade_enabled": False,
        },
    )
    monkeypatch.setattr(
        stock_signals,
        "api_stock_quote",
        lambda **kwargs: {
            "provider_status": "available",
            "quote_time": "2026-07-11T20:00:00+00:00",
            "freshness_seconds": 1,
            "depth_status": "available",
            "depth_mode": "subscription_cache",
        },
    )
    payload = api_stock_market_data_self_check(symbol="NVDA", db_path=tmp_path / "kquant.sqlite3")
    assert payload["status"] == "ready"
    assert payload["realtime_buy_data_ready"] is False
    assert payload["no_account_or_order_path"] is True
    with connect(tmp_path / "kquant.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"] == 1
